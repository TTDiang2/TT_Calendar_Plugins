"""英为财情（v2 occurrences API）解析器单元测试。

不发起真实 HTTP（CF 会拦截，详见 SUBSCRIPTION_INVESTING_HANDOFF.md）。
用浏览器抓包的真实响应做解析断言：docs/investing_v2_sample.json。
"""

from __future__ import annotations

import json
import sys
from datetime import date as date_t
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from investing import (
    InvestingSource,
    _parse_v2_payload,
    _fmt_num,
    load_cookies_file,
)


def _sample() -> dict:
    p = ROOT / "docs" / "investing_v2_sample.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _events() -> list:
    return _parse_v2_payload(_sample())


# ---------------------------------------------------------------------------
# 数值格式化
# ---------------------------------------------------------------------------


def test_fmt_num() -> None:
    assert _fmt_num(1207.5, 1, "B") == "1,207.5B"
    assert _fmt_num(2.5, 1, "%") == "2.5%"
    assert _fmt_num(146.5, 2, "B") == "146.50B"
    assert _fmt_num(3.419, 3, "T") == "3.419T"
    assert _fmt_num(118.1, 1, None) == "118.1"
    assert _fmt_num(0, 1, "%") == "0.0%"
    assert _fmt_num(None, 1, "B") == ""
    assert _fmt_num("abc", 1, "B") == "abc"


# ---------------------------------------------------------------------------
# v2 payload 解析（真实抓包样本）
# ---------------------------------------------------------------------------


def test_parse_sample_event_count() -> None:
    evs = _events()
    assert len(evs) == 9, f"expected 9 occurrences, got {len(evs)}"


def test_parse_sample_occurrence_join_and_fields() -> None:
    """occurrences 与 events 按 event_id join；日本外汇储备落 investing_35。"""
    evs = _events()
    by_ref = {e.source_ref: e for e in evs}
    jp_fx = by_ref.get("35:556231")
    assert jp_fx is not None, f"missing 35:556231, refs={list(by_ref)[:5]}"
    assert jp_fx.layer_id == "investing_35"
    assert jp_fx.date.isoformat() == "2026-09-07"  # UTC 23:50 → 北京次日 07:50
    assert jp_fx.title == "日本外汇储备(美元)"
    assert jp_fx.extra["actual"] == "1,207.5B"
    assert jp_fx.extra["previous"] == "1,287.1B"
    assert jp_fx.extra["time"] == "07:50"
    assert jp_fx.extra["period"] == "八月"
    assert jp_fx.extra["importance"] == 1  # low
    # actual 有但无 forecast → 无对比，不写 vs_forecast（前端无徽标）
    assert "vs_forecast" not in jp_fx.extra
    assert jp_fx.extra["currency"] == "JPY"
    assert jp_fx.extra["country"] == "日本"


def test_parse_sample_positive_vs() -> None:
    """日本领先指标 actual 118.1 > forecast 117.9 → actual_to_forecast=positive → 超预期。"""
    evs = _events()
    by_ref = {e.source_ref: e for e in evs}
    ev = by_ref["35:556213"]
    assert ev.extra["actual"] == "118.1"
    assert ev.extra["forecast"] == "117.9"
    assert ev.extra["vs_forecast"] == "超预期"


def test_parse_sample_no_actual_is_pending() -> None:
    """中国外汇储备无 actual → 待公布；马来西亚无 actual+无 forecast 同。"""
    evs = _events()
    by_ref = {e.source_ref: e for e in evs}
    cn = by_ref["37:555541"]
    assert cn.layer_id == "investing_37"
    assert cn.extra["vs_forecast"] == "待公布"
    assert "actual" not in cn.extra
    assert cn.extra["previous"] == "3.419T"
    my = by_ref["42:556534"]
    assert my.layer_id == "investing_42"
    assert my.extra["vs_forecast"] == "待公布"


def test_parse_sample_unknown_country_other_layer() -> None:
    """42/39/110 已收录进 cfg（马来/香港/南非），都应有专属图层而非 other。"""
    evs = _events()
    by_ref = {e.source_ref: e for e in evs}
    assert by_ref["42:556534"].layer_id == "investing_42"
    assert by_ref["39:556221"].layer_id == "investing_39"
    assert by_ref["110:555526"].layer_id == "investing_110"
    assert by_ref["35:556211"].layer_id == "investing_35"


def test_parse_sample_medium_importance() -> None:
    evs = _events()
    by_ref = {e.source_ref: e for e in evs}
    assert by_ref["37:555541"].extra["importance"] == 2  # medium


def test_parse_occurrence_missing_meta_skipped() -> None:
    """occurrence 引用了不存在的 event_id（无元数据）→ 丢弃不崩。"""
    payload = _sample()
    payload["occurrences"].append(
        {"event_id": 999999, "occurrence_id": 1, "occurrence_time": "2026-09-07T05:00:00Z"}
    )
    evs = _parse_v2_payload(payload)
    assert len(evs) == 9


def test_parse_empty_payload() -> None:
    assert _parse_v2_payload({}) == []
    assert _parse_v2_payload({"events": [], "occurrences": []}) == []


# ---------------------------------------------------------------------------
# 大样本（docs/sample.json，2026-09-08~09 浏览器抓包，34 events）国家 ID 校准
# ---------------------------------------------------------------------------


def _big_sample() -> dict:
    p = ROOT / "docs" / "sample.json"
    return json.loads(p.read_text(encoding="utf-8"))


def test_big_sample_country_layers() -> None:
    """校准过的国家 ID 都应落到对应图层，不再进 other。"""
    evs = _parse_v2_payload(_big_sample())
    layer_ok = {
        e.layer_id for e in evs if e.extra.get("country_code")
    }
    assert "investing_5" in layer_ok    # 美国
    assert "investing_6" in layer_ok    # 加拿大
    assert "investing_14" in layer_ok   # 印度
    assert "investing_26" in layer_ok   # 德国
    assert "investing_32" in layer_ok   # 巴西
    assert "investing_43" in layer_ok   # 新西兰
    assert "investing_51" in layer_ok   # 希腊
    assert "investing_96" in layer_ok   # 欧元区
    assert "investing_72" in layer_ok   # 欧洲央行
    assert "investing_42" in layer_ok   # 马来西亚
    # 每个事件的图层应与国家一致
    for e in evs:
        code = e.extra.get("country_code")
        if code:
            assert e.layer_id in (f"investing_{code}", cfg_other()), \
                f"{e.title[:20]} country={code} layer={e.layer_id}"


def cfg_other() -> str:
    import investing as _inv
    return _inv._OTHER_LAYER


# ---------------------------------------------------------------------------
# 图层声明：min_importance 默认值 + 同日星级排序 sort_key
# ---------------------------------------------------------------------------


def test_layer_specs_min_importance_defaults() -> None:
    """中美图层默认 3★，其余国家/兜底图层默认全显示。"""
    s = InvestingSource()
    specs = {p.layer_id: p for p in s.layer_specs()}
    assert specs["investing_5"].config["min_importance"] == 3
    assert specs["investing_37"].config["min_importance"] == 3
    assert specs["investing_35"].config["min_importance"] == 0
    assert specs[mod._OTHER_LAYER].config["min_importance"] == 0
    for p in s.layer_specs():
        assert p.config.get("country_code") is not None


def test_sort_key_star_priority_then_time() -> None:
    """3★ 在最上（sort_key 最小），同级按当地时间先后；分钟数上限 1439 < 10000 不串档。"""
    evs = _events()
    by_ref = {e.source_ref: e for e in evs}
    jp = by_ref["35:556231"]  # importance=1(low), time=07:50 → 20470
    assert jp.extra["importance"] == 1
    assert jp.sort_key == 2 * 10000 + 7 * 60 + 50
    cn = by_ref["37:555541"]  # importance=2(medium)
    h, m = cn.extra["time"].split(":")
    assert cn.sort_key == 1 * 10000 + int(h) * 60 + int(m)
    from collections import defaultdict
    by_rank: dict[int, list[int]] = defaultdict(list)
    for e in evs:
        by_rank[e.extra["importance"]].append(e.sort_key)
    # 档位不串档：高星级事件 sort_key 恒小于低星级事件
    for low in (0, 1, 2):
        for high in (low + 1, low + 2, low + 3):
            if by_rank[low] and by_rank[high]:
                assert max(by_rank[high]) < min(by_rank[low])


def test_ensure_layers_seeds_min_importance() -> None:
    """旧图层 config 缺 min_importance 键 → 补种 spec 默认值；用户已改过的值不覆盖。"""
    import sqlite3
    from tt_calendar import db

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    s = InvestingSource()
    s.ensure_layers(conn)
    conn.commit()

    conn.execute(
        "UPDATE layer_config SET config_json=? WHERE layer_id='investing_35'",
        ('{"country_code":"35"}',),
    )
    conn.commit()
    s.ensure_layers(conn)
    conn.commit()
    row = conn.execute(
        "SELECT config_json FROM layer_config WHERE layer_id='investing_35'"
    ).fetchone()
    assert json.loads(row["config_json"])["min_importance"] == 0

    conn.execute(
        "UPDATE layer_config SET config_json=? WHERE layer_id='investing_5'",
        ('{"country_code":"5","min_importance":1}',),
    )
    conn.commit()
    s.ensure_layers(conn)
    conn.commit()
    row = conn.execute(
        "SELECT config_json FROM layer_config WHERE layer_id='investing_5'"
    ).fetchone()
    assert json.loads(row["config_json"])["min_importance"] == 1
    conn.close()


# ---------------------------------------------------------------------------
# Cookie 文件解析
# ---------------------------------------------------------------------------


def test_load_cookies_file_json(tmp_path: Path) -> None:
    p = tmp_path / "cookies.json"
    p.write_text(json.dumps({"cf_clearance": "abc123", "sessionid": "xyz"}), encoding="utf-8")
    out = load_cookies_file(str(p))
    assert out == {"cf_clearance": "abc123", "sessionid": "xyz"}


def test_load_cookies_file_netscape(tmp_path: Path) -> None:
    p = tmp_path / "cookies.txt"
    p.write_text(
        "# Netscape HTTP Cookie File\n"
        ".investing.com\tTRUE\t/\tFALSE\t9999999999\tcf_clearance\tabc123\n"
        ".investing.com\tTRUE\t/\tFALSE\t9999999999\tsid\txyz\n"
        "ignored comment line\n"
        "\n"
        ".broken\tFALSE\t/\tFALSE\t1\tname\n"
        , encoding="utf-8")
    out = load_cookies_file(str(p))
    assert out == {"cf_clearance": "abc123", "sid": "xyz"}


def test_load_cookies_file_missing(tmp_path: Path) -> None:
    p = tmp_path / "no_such.json"
    try:
        load_cookies_file(str(p))
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


# ---------------------------------------------------------------------------
# Source 类基础字段 / session 选择
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import investing as mod  # noqa: E402
from investing import _CffiSession, _HttpxSession  # noqa: E402


def test_source_class_metadata() -> None:
    s = InvestingSource()
    assert s.source_id == "investing"
    assert s.display_name == "英为财情-投资日历"
    assert s.needs_internet is True


async def _noop_sleep(*args, **kwargs):
    return None


class _FakeCffiCookies:
    def __init__(self):
        self.sets = []

    def set(self, k, v, domain=None):
        self.sets.append((k, v, domain))


class _FakeCffiSession:
    def __init__(self, impersonate="chrome120"):
        self.impersonate = impersonate
        self.headers = {}
        self.cookies = _FakeCffiCookies()

    def close(self):
        pass


def test_get_session_prefers_cffi_when_cookies(monkeypatch) -> None:
    fake = type("FakeReq", (), {"Session": _FakeCffiSession})
    monkeypatch.setattr(mod, "_HAS_CFFI", True)
    monkeypatch.setattr(mod, "_cffi_requests", fake)
    src = InvestingSource()
    sess = asyncio.run(src._get_session(cookies={"cf_clearance": "x"}))
    assert isinstance(sess, _CffiSession)
    assert sess._sess.impersonate == "chrome120"
    assert sess._sess.cookies.sets[0][2] == ".investing.com"
    asyncio.run(src.close())


def test_get_session_httpx_when_no_cookies(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_HAS_CFFI", True)
    src = InvestingSource()
    sess = asyncio.run(src._get_session(cookies=None))
    assert isinstance(sess, _HttpxSession)
    asyncio.run(src.close())


def test_get_session_httpx_when_cffi_missing(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_HAS_CFFI", False)
    src = InvestingSource()
    sess = asyncio.run(src._get_session(cookies={"cf_clearance": "abc"}))
    assert isinstance(sess, _HttpxSession)
    assert sess._client.cookies.get("cf_clearance") == "abc"
    asyncio.run(src.close())


def test_fetch_one_retries_and_cf_detection(monkeypatch) -> None:
    """403+cf-ray 请求重试 3 次后报错并标记 CF。"""
    from investing import _Resp
    calls = []

    class _FakeSess:
        async def get(self, url, params):
            calls.append(params)
            return _Resp(403, {"cf-ray": "a3735-SIN"}, "403")

    monkeypatch.setattr(mod.asyncio, "sleep", _noop_sleep)
    src = InvestingSource()
    ok, payload, is_cf, status = asyncio.run(
        src._get_json_with_retry(_FakeSess(), [("limit", "3")], page=0)
    )
    assert ok is False
    assert is_cf is True
    assert status == 403
    assert len(calls) == 3


if __name__ == "__main__":
    import tempfile
    import traceback

    tmp = Path(tempfile.mkdtemp(prefix="investing_v2_test_"))
    tests = [
        test_fmt_num,
        test_parse_sample_event_count,
        test_parse_sample_occurrence_join_and_fields,
        test_parse_sample_positive_vs,
        test_parse_sample_no_actual_is_pending,
        test_parse_sample_unknown_country_other_layer,
        test_parse_sample_medium_importance,
        test_parse_occurrence_missing_meta_skipped,
        test_parse_empty_payload,
        test_load_cookies_file_json,
        test_load_cookies_file_netscape,
        test_load_cookies_file_missing,
        test_source_class_metadata,
        test_get_session_prefers_cffi_when_cookies,
        test_get_session_httpx_when_no_cookies,
        test_get_session_httpx_when_cffi_missing,
        test_fetch_one_retries_and_cf_detection,
    ]
    fail = 0
    for t in tests:
        try:
            t(tmp)
            print(f"  PASS  {t.__name__}")
        except Exception:
            fail += 1
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{fail} failed, {len(tests) - fail} passed")
    raise SystemExit(1 if fail else 0)
