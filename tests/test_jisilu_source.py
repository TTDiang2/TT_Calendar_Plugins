"""集思录投资日历数据源单元测试（解析层 + source_ref 去重键稳定性）。

去重键（2026-09-21 修复背景）：jisilu 编辑底层数据时会换发新 id 但代码/标题/描述
不变，原按 id 散列会导致同一事件被重复入库（典型表现：同一转债的【申购日】
出现两次）。新 key 用 code + 日期 + 子动作（与 id 解耦）后，再导入会自动合并。

不发起真实 HTTP（API 端反爬限速；解析层足够定位 bug）。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jisilu import _parse_item  # noqa: E402


# ---------------------------------------------------------------------------
# 去重键稳定性：jisilu 重新发号（id 不同、code/日期/子动作相同）→ 同一 source_ref
# ---------------------------------------------------------------------------


def test_ref_par_with_id_change() -> None:
    """同一只转债【申购日】同一天，jisilu 给两次不同的 id → 应映射为同一 source_ref。"""
    item_old = {
        "id": "CNV58092", "code": "118076", "qtype": "CNV",
        "title": "【申购日】先锋转债",
        "start": "2026-08-06", "description": "转债代码:118076 申购代码:718605",
    }
    item_new = {
        "id": "CNV58343", "code": "118076", "qtype": "CNV",
        "title": "【申购日】先锋转债",
        "start": "2026-08-06", "description": "转债代码:118076 申购代码:718605",
    }
    e1 = _parse_item(item_old, "jisilu_CNV", "CNV")
    e2 = _parse_item(item_new, "jisilu_CNV", "CNV")
    assert e1 is not None and e2 is not None
    assert e1.source_ref == e2.source_ref, (
        f"id 变 → 应映射到同一 ref；旧={e1.source_ref} 新={e2.source_ref}"
    )
    assert e1.source_ref == "CNV:118076:2026-08-06:申购日"


def test_ref_distinct_sub_action_same_day() -> None:
    """同一只转债同一天不同子动作（如申购日 vs 配售日）→ 不同 source_ref（保留两条）。"""
    a = {
        "id": "CNV58092", "code": "118076", "qtype": "CNV",
        "title": "【申购日】先锋转债",
        "start": "2026-08-06",
    }
    b = {
        "id": "CNV58093", "code": "118076", "qtype": "CNV",
        "title": "【配售日】先锋转债",
        "start": "2026-08-06",
    }
    e_a = _parse_item(a, "jisilu_CNV", "CNV")
    e_b = _parse_item(b, "jisilu_CNV", "CNV")
    assert e_a is not None and e_b is not None
    assert e_a.source_ref != e_b.source_ref
    assert e_a.source_ref == "CNV:118076:2026-08-06:申购日"
    assert e_b.source_ref == "CNV:118076:2026-08-06:配售日"


def test_ref_distinct_codes_same_day() -> None:
    """同日不同转债 → 不同 source_ref。"""
    a = {"id": "1", "code": "118076", "qtype": "CNV", "title": "【申购日】A", "start": "2026-08-06"}
    b = {"id": "2", "code": "111026", "qtype": "CNV", "title": "【申购日】B", "start": "2026-08-06"}
    assert _parse_item(a, "jisilu_CNV", "CNV").source_ref != _parse_item(b, "jisilu_CNV", "CNV").source_ref


def test_ref_without_sub_action() -> None:
    """标题没有【子动作】子动作时，仍按 code+date 稳定散列。"""
    item = {
        "id": "X1", "code": "600999", "qtype": "newstock_apply",
        "title": "某新股申购",  # 无【...】前缀
        "start": "2026-08-06",
    }
    e = _parse_item(item, "jisilu_newstock_apply", "newstock_apply")
    assert e is not None
    assert e.source_ref == "newstock_apply:600999:2026-08-06"


def test_ref_fallback_when_code_missing() -> None:
    """code 缺失 → 回退到 id 散列（向后兼容，避免误合并无关事件）。"""
    item = {
        "id": "ABC123", "code": None, "qtype": "OTHER",
        "title": "无码事件",
        "start": "2026-08-06",
    }
    e = _parse_item(item, "jisilu_OTHER", "OTHER")
    assert e is not None
    assert e.source_ref == "OTHER:ABC123"


# ---------------------------------------------------------------------------
# 基本解析
# ---------------------------------------------------------------------------


def test_basic_parsed_fields() -> None:
    item = {
        "id": "X1", "code": "123281", "color": "#FFB300",
        "title": "【申购日】中伦转债",
        "start": "2026-08-06", "description": "<p>转债代码:123281 申购代码:371565</p>",
        "url": "/data/convert_bond_detail/123281",
    }
    e = _parse_item(item, "jisilu_CNV", "CNV")
    assert e is not None
    assert e.date == date(2026, 8, 6)
    assert e.title == "【申购日】中伦转债"
    assert e.layer_id == "jisilu_CNV"
    assert e.source == "jisilu"
    assert e.color == "#FFB300"
    assert e.extra["qtype"] == "CNV"
    assert e.extra["code"] == "123281"
    assert e.extra["url"] == "https://www.jisilu.cn/data/convert_bond_detail/123281"
    # description 已转纯文本（去掉 <p>）
    assert "<p>" not in (e.description or "")


def test_invalid_date_returns_none() -> None:
    assert _parse_item({"id": "x", "code": "c", "qtype": "CNV",
                        "title": "【申购日】X", "start": ""},
                       "jisilu_CNV", "CNV") is None
    assert _parse_item({"id": "x", "code": "c", "qtype": "CNV",
                        "title": "", "start": "2026-08-06"},
                       "jisilu_CNV", "CNV") is None