"""英为财情（Investing.com）经济日历数据源。

数据端点（2026-09 实测，旧 Service/getCalendarFilteredData 已弃用）：

    GET https://endpoints.investing.com/pd-instruments/v1/calendars/economic/events/occurrences
        ?domain_id=6
        &limit=200
        &start_date=2026-09-07T00:00:00.000+08:00
        &end_date=2026-09-13T23:59:59.999+08:00
        &country_ids=25,32,6,37,...        （逗号分隔的 investing 国家 ID）

返回 JSON（浏览器 Network 抓包确认）：

    {
      "events": [        # 事件元数据（每个 event_id 一条）
        {"event_id": 1004, "country_id": 35, "currency": "JPY",
         "importance": "low", "event_translated": "日本外汇储备(美元)", ...}
      ],
      "occurrences": [   # 实际发布记录（同 event 可多次发布）
        {"event_id": 1004, "occurrence_id": 556231,
         "occurrence_time": "2026-09-06T23:50:00Z",   # UTC
         "actual": 1207.5, "forecast": ..., "previous": 1287.1,
         "precision": 1, "unit": "B",
         "reference_period": "八月",
         "actual_to_forecast": "neutral", ...}
      ],
      "next_page_cursor": "..."    # 非空表示还有下一页
    }

国家归属与重要性都取自行内字段（country_id / importance），不能依赖请求参数。
Cloudflare 按 TLS 指纹（JA3）拦截非浏览器客户端：httpx 固定 "python" 指纹会被
边缘直接 403；curl_cffi 的 impersonate 能模拟 Chrome 真实 ClientHello 绕过，
配合浏览器导出的 cf_clearance cookie 才能稳定拉取。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date as date_t, datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from tt_calendar import config as cfg  # 仅 DATA_DIR（cookie 文件位置）
from tt_calendar.models import Event, ImportResult
from tt_calendar.sources.base import LayerSpec, Source

try:
    from curl_cffi import requests as _cffi_requests  # type: ignore[import-not-found]
    _HAS_CFFI = True
except Exception:
    _cffi_requests = None
    _HAS_CFFI = False

log = logging.getLogger(__name__)

# 响应里事件按本地时区展示；occurrence_time 是 UTC，转北京时间展示
_LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_UTC_TZ = timezone.utc

# importance 字符串 → 星级（1-3）
_IMP_RANK = {"low": 1, "medium": 2, "high": 3}

# CF 拦截特征头
_CF_HINT_HEADERS: tuple[str, ...] = ("cf-ray", "cf-mitigated", "cf-cache-status")

# ---------------------------------------------------------------------------
# 源内配置（订阅插件自包含：端点/国家表/请求集都是本源的领域知识）
# ---------------------------------------------------------------------------

_PREFIX = "investing_"        # 国家图层前缀 investing_<country_id>
_OTHER_LAYER = "investing_other"  # 未收录国家的兜底图层

# v2 数据端点（2026-09 浏览器抓包确认；旧 Service/getCalendarFilteredData 已弃用，
# 其响应无视日期/国家过滤且只回当天数据）
_ENDPOINT = "https://endpoints.investing.com/pd-instruments/v1/calendars/economic/events/occurrences"
_DOMAIN_ID = 6  # 中文站 domain_id=6（抓包值）
_PAGE_LIMIT = 200  # 单页上限；实测 ~5-6 天全球事件一页
_MAX_PAGES = 32  # 单次 fetch 最大请求段数（日期窗口拆分兜底）
# 请求头：仿 XHR + 真实 Referer/Origin；CF 仍然会拦，但保留完整头能减少 4xx 多样性
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://cn.investing.com/economic-calendar/",
    "Origin": "https://cn.investing.com",
    "X-Requested-With": "XMLHttpRequest",
}
_TIMEOUT_SECONDS = 20

# 国家 ID（v2 API events[].country_id，2026-09 三次浏览器抓包校准；旧 Service 时代
# 的 ID 表整体失效）。已实测确认（样本 docs/sample.json + investing_v2_sample.json）：
#   5=美 6=加 14=印 25=澳 32=巴 35=日 37=中 39=港 42=马来 43=新西兰
#   48=印尼 51=希腊 72=欧洲央行(讲话) 96=欧元区 110=南非 26=德国
# 行级归属把未收录 country_id 的事件丢进 investing_other 图层，不会错位。
_COUNTRIES: dict[str, dict[str, object]] = {
    "5":   {"name": "美国",     "currency": "USD", "color": "#3F51B5", "enabled": True},
    "37":  {"name": "中国",     "currency": "CNY", "color": "#E53935", "enabled": True},
    "35":  {"name": "日本",     "currency": "JPY", "color": "#EF5350", "enabled": True},
    "96":  {"name": "欧元区",   "currency": "EUR", "color": "#1A237E", "enabled": True},
    "25":  {"name": "澳大利亚", "currency": "AUD", "color": "#6A1B9A", "enabled": False},
    "6":   {"name": "加拿大",   "currency": "CAD", "color": "#D81B60", "enabled": False},
    "26":  {"name": "德国",     "currency": "EUR", "color": "#FFB300", "enabled": False},
    "43":  {"name": "新西兰",   "currency": "NZD", "color": "#0D47A1", "enabled": False},
    "14":  {"name": "印度",     "currency": "INR", "color": "#FF8F00", "enabled": False},
    "110": {"name": "南非",     "currency": "ZAR", "color": "#6D4C41", "enabled": False},
    "42":  {"name": "马来西亚", "currency": "MYR", "color": "#F9A825", "enabled": False},
    "39":  {"name": "中国香港", "currency": "HKD", "color": "#C62828", "enabled": False},
    "48":  {"name": "印度尼西亚", "currency": "IDR", "color": "#5D4037", "enabled": False},
    "32":  {"name": "巴西",     "currency": "BRL", "color": "#2E7D32", "enabled": False},
    "51":  {"name": "希腊",     "currency": "EUR", "color": "#1565C0", "enabled": False},
    "72":  {"name": "欧洲央行", "currency": "EUR", "color": "#4527A0", "enabled": False},
}

# 请求国家全集：浏览器默认勾选集 ∪ 上面已配置国家（保证每个图层都有数据）
_REQUEST_COUNTRY_IDS = (
    "25,32,6,37,72,22,17,39,14,48,10,35,42,43,36,110,11,26,12,46,41,4,5,178"
)

# 桌面端用户从浏览器导出的 CF 绕过 cookie 文件（相对数据目录）
_COOKIE_FILE_NAME = "investing_cookies.json"


# ---------------------------------------------------------------------------
# 统一 HTTP 响应 / session（httpx 兜底、curl_cffi 优先）
# ---------------------------------------------------------------------------


class _Resp:
    """httpx.Response / curl_cffi.Response 的统一形态，解析层只看它。"""

    __slots__ = ("status_code", "headers", "text")

    def __init__(self, status_code: int, headers: dict[str, str], text: str) -> None:
        self.status_code = status_code
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.text = text

    def json(self) -> Any:
        return json.loads(self.text)


class _HttpxSession:
    """httpx 包装（curl_cffi 缺失时的兜底，通常会被 CF 拦）。"""

    def __init__(self, headers: dict[str, str], timeout: int) -> None:
        self._client = httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=True
        )

    async def get(self, url: str, params: list[tuple[str, str]]) -> _Resp:
        r = await self._client.get(url, params=params)
        return _Resp(r.status_code, dict(r.headers), r.text)

    async def close(self) -> None:
        await self._client.aclose()


class _CffiSession:
    """curl_cffi 同步 Session 异步化（asyncio.to_thread 包一层）。

    同步 API + 模拟 Chrome TLS 指纹，是目前唯一能稳定过 Cloudflare 的方案。
    """

    def __init__(self, headers: dict[str, str], timeout: int, cookies: dict[str, str]) -> None:
        self._sess = _cffi_requests.Session(impersonate="chrome120")
        self._timeout = timeout
        for k, v in cookies.items():
            self._sess.cookies.set(k, v, domain=".investing.com")
        self._sess.headers.update(headers)

    async def get(self, url: str, params: list[tuple[str, str]]) -> _Resp:
        def _do() -> _Resp:
            r = self._sess.get(url, params=params, timeout=self._timeout)
            return _Resp(r.status_code, dict(r.headers), r.text)

        return await asyncio.to_thread(_do)

    async def close(self) -> None:
        self._sess.close()


# ---------------------------------------------------------------------------
# 解析（v2 occurrences 响应）
# ---------------------------------------------------------------------------

_IMP_MISSING = object()


def _fmt_num(value: Any, precision: Any, unit: Any) -> str:
    """数值 + 精度 + 单位 → 显示串（"1,207.5B" / "2.5%" / "146.50B"）。"""
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    p = int(precision) if precision is not None else 0
    s = f"{v:,.{p}f}"
    u = str(unit or "").strip()
    return s + u if u else s


def _layer_for_country(country_id: Any) -> tuple[str, bool]:
    """country_id → (layer_id, 是否在已配置国家表)。

    未配置的国家统一进 investing_other 图层（用户可手动开启）。
    """
    code = str(country_id or "")
    if code in _COUNTRIES:
        return _PREFIX + code, True
    return _OTHER_LAYER, False


def _parse_v2_payload(payload: dict[str, Any]) -> list[Event]:
    """把 v2 occurrences 响应转成 Event 列表。

    events[] 是元数据、occurrences[] 是发布记录，按 event_id join；
    occurrence_id 是每条唯一 ID（用作 source_ref 去重）。
    """
    events_by_id: dict[int, dict[str, Any]] = {}
    for ev in payload.get("events") or []:
        eid = ev.get("event_id")
        if eid is not None:
            events_by_id[int(eid)] = ev

    out: list[Event] = []
    for occ in payload.get("occurrences") or []:
        try:
            meta = events_by_id.get(int(occ.get("event_id") or 0), {})
            ev = _parse_occurrence(occ, meta)
            if ev:
                out.append(ev)
        except Exception as e:
            log.warning("investing: occurrence parse failed: %s; occ=%s", e, str(occ)[:200])
    return out


def _parse_occurrence(occ: dict[str, Any], meta: dict[str, Any]) -> Event | None:
    oid = occ.get("occurrence_id")
    if oid is None:
        return None

    country_id = meta.get("country_id")
    layer_id, known = _layer_for_country(country_id)

    title = str(meta.get("event_translated") or meta.get("short_name") or "").strip()
    if not title:
        return None

    # occurrence_time 是 UTC → 转 +08:00 展示；跨日发生在本地日期的归属也以 +8 为准
    dt_local: datetime | None = None
    raw_t = occ.get("occurrence_time")
    if raw_t:
        try:
            s = str(raw_t).replace("Z", "+00:00")
            dt_local = datetime.fromisoformat(s).astimezone(_LOCAL_TZ)
        except ValueError:
            pass
    d = dt_local.date() if dt_local else date_t.today()

    actual_raw = occ.get("actual")
    forecast_raw = occ.get("forecast", _IMP_MISSING)
    previous_raw = occ.get("previous")
    precision = occ.get("precision")
    unit = occ.get("unit")

    actual = _fmt_num(actual_raw, precision, unit)
    forecast = "" if forecast_raw is _IMP_MISSING else _fmt_num(forecast_raw, precision, unit)
    previous = _fmt_num(previous_raw, precision, unit)

    # vs 预期：优先用官方比较；无 actual 就是待公布；已公布但无预测值 → 不写键（无对比）
    atf = occ.get("actual_to_forecast")
    if actual_raw is None:
        vs = "待公布"
    elif atf == "positive":
        vs = "超预期"
    elif atf == "negative":
        vs = "不及"
    elif forecast_raw is not _IMP_MISSING:
        vs = "符合"
    else:
        vs = None  # 无 forecast 可比，前端不显示徽标

    imp = _IMP_RANK.get(str(meta.get("importance") or "").lower(), 0)

    country_info = _COUNTRIES.get(str(country_id or ""), {})

    extra: dict[str, Any] = {
        "country": str(country_info.get("name") or ""),
        "country_code": str(country_id or ""),
        "currency": str(meta.get("currency") or ""),
        "importance": imp,
    }
    if vs:
        extra["vs_forecast"] = vs
    if dt_local:
        extra["time"] = dt_local.strftime("%H:%M")
    if actual:
        extra["actual"] = actual
    if forecast:
        extra["forecast"] = forecast
    if previous:
        extra["previous"] = previous
    period = occ.get("reference_period")
    if period:
        extra["period"] = str(period)

    source_ref = f"{country_id or '?'}:{oid}"

    return Event(
        layer_id=layer_id,
        source="investing",
        date=d,
        title=title,
        description=None,
        color=str(country_info.get("color") or "#6B7280"),
        source_ref=source_ref,
        extra=extra,
        sort_key=0,
    )


# ---------------------------------------------------------------------------
# InvestingSource
# ---------------------------------------------------------------------------


class InvestingSource(Source):
    """英为财情经济日历导入源（v2 occurrences API）。

    一次请求全部国家（country_ids 逗号串），事件按行内 country_id 归属图层
    investing_<id>；未配置国家进 investing_other。
    """

    source_id: str = "investing"
    display_name: str = "英为财情-投资日历"
    group: str = "英为财情-投资日历"
    needs_internet: bool = True
    needs_credentials: bool = False  # 严格说需要 CF cookie，但不算账号凭据
    # 经济日历事件密集、数值实时更新，自动刷新近 2 天补漏 + 未来 14 天排期即可
    refresh_past_days: int = 2
    refresh_future_days: int = 14

    def __init__(self) -> None:
        super().__init__()
        self._session: Any = None  # _HttpxSession 或 _CffiSession

    # ------------------------------------------------------------------
    # 图层声明与播种（订阅插件协议）
    # ------------------------------------------------------------------

    def layer_specs(self) -> list[LayerSpec]:
        specs = [
            LayerSpec(
                layer_id=_PREFIX + code,
                display_name=f"英为财情·{info['name']}",
                enabled=bool(info["enabled"]),
                color=str(info["color"]),
                sort_order=11,
                kind="dot",
                group=self.group,
                config={"country_code": code},
            )
            for code, info in _COUNTRIES.items()
        ]
        specs.append(LayerSpec(
            layer_id=_OTHER_LAYER,
            display_name="英为财情·其他",
            enabled=False,
            color="#6B7280",
            sort_order=12,
            kind="dot",
            group=self.group,
            config={"country_code": "other"},
        ))
        return specs

    def ensure_layers(self, conn: Any) -> None:
        """播种图层。相比默认实现多一步：2026-09 国家 ID 体系更换后，旧图层
        （如 investing_42 曾叫"英为财情·英国"、现在实际是马来西亚）display_name
        与声明不符 → 改名/改色并**按默认 enabled 覆盖**（旧 enabled 语义随国家
        转移而失效）；display_name 一致的图层保持用户手动 enabled 不动。
        """
        from tt_calendar import db

        for spec in self.layer_specs():
            row = conn.execute(
                "SELECT display_name, enabled FROM layer_config WHERE layer_id=?",
                (spec.layer_id,),
            ).fetchone()
            if not row:
                db.upsert_layer_config(
                    conn,
                    db.LayerConfig(
                        layer_id=spec.layer_id,
                        display_name=spec.display_name,
                        enabled=spec.enabled,
                        color=spec.color,
                        sort_order=spec.sort_order,
                        kind=spec.kind,
                        group=self.group,
                        config=spec.config,
                    ),
                )
            elif row["display_name"] != spec.display_name:
                conn.execute(
                    "UPDATE layer_config SET display_name=?, color=?, enabled=?, "
                    "group_name=?, sort_order=?, kind=? WHERE layer_id=?",
                    (spec.display_name, spec.color, 1 if spec.enabled else 0,
                     self.group, spec.sort_order, spec.kind, spec.layer_id),
                )

    # ------------------------------------------------------------------
    # 事件字段 UI 规格（前端 SourceFields 消费）
    # ------------------------------------------------------------------

    def field_specs(self) -> dict[str, Any]:
        return {
            "meta": [
                {"key": "time"},
                {"key": "currency"},
                {"key": "period"},
            ],
            "importance": {"key": "importance", "max": 3},
            "columns": [
                {"key": "actual", "label": "今值"},
                {"key": "forecast", "label": "预测值"},
                {"key": "previous", "label": "前值"},
            ],
            "badges": {
                "key": "vs_forecast",
                "map": {
                    "超预期": {"label": "▲ 超预期", "tone": "good"},
                    "不及": {"label": "▼ 不及预期", "tone": "bad"},
                    "符合": {"label": "● 符合预期", "tone": "info"},
                    "待公布": {"label": "— 待公布", "tone": "muted"},
                },
            },
        }

    # ------------------------------------------------------------------
    # Cookie（CF 绕过凭据，源自行负责）
    # ------------------------------------------------------------------

    @staticmethod
    def _load_cookies(cookies: dict[str, str] | None = None) -> dict[str, str] | None:
        """优先用调用方传入的 cookie；否则读 data/investing_cookies.json（用户导出）。"""
        if cookies:
            return cookies
        path = cfg.DATA_DIR / _COOKIE_FILE_NAME
        if not path.exists():
            return None
        try:
            loaded = load_cookies_file(str(path))
            return loaded or None
        except Exception as e:
            log.warning("load investing cookies failed: %s", e)
            return None

    async def _get_session(self, cookies: dict[str, str] | None = None) -> Any:
        if cookies and _HAS_CFFI:
            log.info("investing: using curl_cffi (chrome120) with %d cookies", len(cookies))
            self._session = _CffiSession(
                dict(_HEADERS),
                _TIMEOUT_SECONDS,
                cookies,
            )
        else:
            if cookies:
                log.info("investing: cookie provided but curl_cffi unavailable, falling back to httpx")
            self._session = _HttpxSession(
                dict(_HEADERS),
                _TIMEOUT_SECONDS,
            )
            if cookies:
                for k, v in cookies.items():
                    self._session._client.cookies.set(k, v)
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch(
        self,
        start: date_t,
        end: date_t,
        countries: list[str] | None = None,
        cookies: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[list[Event], ImportResult]:
        """拉取 [start, end]（含两端）区间的事件，行级归属国家图层。

        Args:
            start/end: 日期范围。
            countries: 请求国家 ID 列表；None 用浏览器抓包全集（服务端过滤范围）。
                图层归属始终以响应 events[].country_id 为准。
            cookies: CF 绕过 cookie 字典；None 时自动读 data/investing_cookies.json。
        """
        if countries is None:
            # 浏览器抓包全集 ∪ 已配置国家：保证用户开启的每个国家图层都能拉到数据
            countries = list(dict.fromkeys(
                _REQUEST_COUNTRY_IDS.split(",") + list(_COUNTRIES.keys())
            ))
        cookies = self._load_cookies(cookies)

        session = await self._get_session(cookies=cookies)
        all_events: list[Event] = []
        errors: list[str] = []
        cf_blocked = False
        bad_status = 0
        try:
            all_events, cf_blocked, bad_status = await self._fetch_range(session, start, end, countries)
        except Exception as e:
            log.warning("investing fetch failed: %s", e)
            errors.append(str(e))

        result = ImportResult(source=self.source_id, layer_id="investing_*")
        result.fetched = len(all_events)
        result.inserted = len(all_events)
        if cf_blocked and not all_events:
            result.error = _cf_block_hint(bad_status)
        elif errors:
            result.error = "; ".join(errors)[:300]
        elif cf_blocked and all_events:
            result.error = (
                f"部分请求被 Cloudflare 拦截，已成功 {len(all_events)} 条；"
                "稍后可再点一次「立即更新」补齐"
            )
        log.info("investing fetch done: %d events; cf_blocked=%s", len(all_events), cf_blocked)
        return all_events, result

    async def _fetch_range(
        self,
        session: Any,
        start: date_t,
        end: date_t,
        countries: list[str],
    ) -> tuple[list[Event], bool, int]:
        """拉取整个 [start, end]。服务端单页上限 200（实测 ~5-6 天全球事件），
        超过则把日期窗口对半拆分递归请求（按日期过滤天然无重复），不依赖
        next_page_cursor（该游标的回传参数名未公开，实测常见名均被忽略）。

        返回 (events, cf_blocked, last_bad_status)。last_bad_status 取最后一次
        非 200 的状态码（无则 0），供全量失败时区分 429 限流 / 403 挑战。
        """
        events: list[Event] = []
        cf_blocked = False
        bad_status = 0
        queue: list[tuple[date_t, date_t]] = [(start, end)]
        pages = 0
        while queue:
            s, e = queue.pop()
            pages += 1
            if pages > _MAX_PAGES:
                log.warning("investing: too many page splits (%d), giving up remainder", pages)
                break
            ok, payload, is_cf, status = await self._get_json_with_retry(
                session, _build_range_params(s, e, countries), pages
            )
            if is_cf:
                cf_blocked = True
            if status != 200:
                bad_status = status
            if status == 429:
                # 限流窗口内剩余分段也必然 429；继续请求只会加重限流判定。
                # 本次到此为止，把"多次尝试"交给用户稍后再点（不锁死）。
                log.warning(
                    "investing: rate limited (429), stopping %d remaining segments; "
                    "retry in 5-15 min", len(queue),
                )
                break
            if not ok or not payload:
                if not is_cf or ok:
                    log.warning("investing: range %s..%s failed status=%d", s, e, status)
                continue
            occs = payload.get("occurrences") or []
            if len(occs) >= _PAGE_LIMIT and s < e:
                mid = s + (e - s) // 2
                queue.append((s, mid))
                queue.append((mid + timedelta(days=1), e))
                continue
            events.extend(_parse_v2_payload(payload))
            await asyncio.sleep(0.4)
        return events, cf_blocked, bad_status

    async def _get_json_with_retry(
        self,
        session: Any,
        params: list[tuple[str, str]],
        page: int,
    ) -> tuple[bool, dict[str, Any], bool, int]:
        """GET 一次 + 最多 2 次重试（覆盖 CF 偶发 challenge/4xx）。

        429 立即中止重试：限流时再请求只会加重，留给外层"稍后再试"。
        """
        last_cf = False
        last_status = 0
        for attempt in range(3):
            resp = await session.get(_ENDPOINT, params=params)
            last_status = resp.status_code
            last_cf = _is_cf_block(resp)
            if resp.status_code == 200:
                try:
                    return True, resp.json(), last_cf, 200
                except Exception as e:
                    log.warning("investing: bad JSON page=%d attempt=%d: %s", page, attempt + 1, e)
                    return False, {}, last_cf, 200
            if resp.status_code == 429:
                break
            if attempt < 2:
                await asyncio.sleep(2.0 * (attempt + 1))
        return False, {}, last_cf, last_status


def _build_range_params(
    start: date_t,
    end: date_t,
    countries: list[str],
) -> list[tuple[str, str]]:
    """v2 API 参数：ISO8601 带 +08:00 的起止时刻 + country_ids 逗号串。

    时区偏移的 + 号交给 HTTP 库编码（自动转 %2B），不要手动预编码，
    否则 % 会被二次编码成 %252B，服务端解析日期失败返回空。
    """
    def iso_day(d: date_t, is_end: bool) -> str:
        if is_end:
            dt = datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=_LOCAL_TZ)
        else:
            dt = datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=_LOCAL_TZ)
        return dt.isoformat()

    return [
        ("domain_id", str(_DOMAIN_ID)),
        ("limit", str(_PAGE_LIMIT)),
        ("start_date", iso_day(start, False)),
        ("end_date", iso_day(end, True)),
        ("country_ids", ",".join(countries)),
    ]


def _is_cf_block(resp: _Resp) -> bool:
    """判断响应是否为 Cloudflare 拦截（403/429/503 + cf-* 头）。"""
    if resp.status_code in (403, 429, 503):
        if any(name in resp.headers for name in _CF_HINT_HEADERS):
            return True
    return False


def _cf_block_hint(last_status: int) -> str:
    """CF 拦截的全量失败提示：强调这是临时状态、允许重试，而非"永久失败"。

    每次点「立即更新」都是全新尝试，失败不会把后续刷新锁死；
    这里按最后状态码区分 429（限流）/ 403（人机验证）给出对应建议。
    """
    if last_status == 429:
        return (
            "当前被 Cloudflare 限流（429，短时间内请求偏多）。这是临时状态、可以重试："
            "请等 5-15 分钟后再点「立即更新」，通常会自行恢复；cookie 大概率没过期，"
            "不必立刻重新导出。"
        )
    return (
        "被 Cloudflare 人机验证拦截（403）。一般是临时拦截：先过几分钟再点「立即更新」重试；"
        "如果反复尝试都失败，再用 Edge 打开 https://cn.investing.com/economic-calendar "
        "重新导出 cookie 到 data/investing_cookies.json。"
    )


# ---------------------------------------------------------------------------
# Cookie 文件读取（桌面应用让用户从浏览器导出）
# ---------------------------------------------------------------------------


def load_cookies_file(path: str) -> dict[str, str]:
    """从 data/investing_cookies.json 读 cookie 字典。

    支持格式：
      {"name": "value", ...}
      或 Netscape cookies.txt（每行 `domain\tflag\tpath\tsecure\texpiry\tname\tvalue`）

    返回 {name: value} 字典。
    """
    try:
        raw = open(path, "r", encoding="utf-8").read()
    except OSError as e:
        raise FileNotFoundError(f"无法读取 cookie 文件 {path}: {e}") from e

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return {str(k): str(v) for k, v in obj.items()}
    except json.JSONDecodeError:
        pass

    out: dict[str, str] = {}
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        parts = s.split("\t")
        if len(parts) < 7:
            continue
        name = parts[5]
        value = parts[6]
        if name and value is not None:
            out[name] = value
    return out


__all__ = [
    "InvestingSource",
    "load_cookies_file",
]
