"""registry.json 防漂移测试。

registry.json 是**生成物**，不是手写清单——它由 tools/gen_registry.py 从各插件的
类声明读出来。生成物最典型的失效方式是：改了插件代码却忘了重新生成，市场上就出现
「索引说 A、实际是 B」的条目，而这种不一致不会让任何代码报错，只会让用户踩坑。

所以这里把「索引必须与代码一致」变成会失败的断言。附带校验 sha256 与下载地址，
让未来的安装器可以据此验证下载完整性。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import gen_registry as gen  # noqa: E402


def _registry() -> dict:
    path = ROOT / gen.REGISTRY_NAME
    assert path.exists(), (
        f"{gen.REGISTRY_NAME} 不存在。生成：python tools/gen_registry.py"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_registry_matches_plugin_declarations():
    """核心防漂移：索引内容必须等于「此刻从插件声明生成的」内容。"""
    expected = gen.render(gen.build(gen.DEFAULT_SLUG, gen.DEFAULT_BRANCH))
    actual = (ROOT / gen.REGISTRY_NAME).read_text(encoding="utf-8")
    assert actual == expected, (
        f"{gen.REGISTRY_NAME} 与插件声明不一致——改了插件的声明/图层却没重生成。"
        "修复：python tools/gen_registry.py"
    )


def test_registry_is_byte_stable():
    """生成必须字节稳定（含时间戳会让每次 CI 都报漂移，噪声掩盖真问题）。"""
    a = gen.render(gen.build(gen.DEFAULT_SLUG, gen.DEFAULT_BRANCH))
    b = gen.render(gen.build(gen.DEFAULT_SLUG, gen.DEFAULT_BRANCH))
    assert a == b


def test_every_declared_plugin_is_listed():
    """插件文件里的 Source 都必须在索引里，且索引里没有幽灵条目。"""
    reg = _registry()
    listed = {p["file"] for p in reg["plugins"]}
    declared = {p.name for p in gen.plugin_files()}
    assert declared == listed, (
        f"索引与仓库里的插件文件不一致："
        f"仅文件有={declared - listed}，仅索引有={listed - declared}"
    )


def test_source_ids_unique():
    ids = [p["source_id"] for p in _registry()["plugins"]]
    assert len(ids) == len(set(ids)), f"source_id 重复：{ids}"


def test_sha256_matches_plugin_file():
    """下载完整性：索引里的 sha256 必须等于仓库中该文件的实际哈希。"""
    for p in _registry()["plugins"]:
        raw = (ROOT / p["file"]).read_bytes()
        assert p["sha256"] == hashlib.sha256(raw).hexdigest(), f"{p['file']} 哈希不符"
        assert p["size"] == len(raw), f"{p['file']} 大小不符"


def test_download_url_points_at_own_file():
    for p in _registry()["plugins"]:
        assert p["url"].endswith(f"/{gen.DEFAULT_BRANCH}/{p['file']}"), p["url"]
        assert p["file"] in p["url"]


def test_entries_carry_what_an_installer_needs():
    """安装器要靠这些字段做展示与兼容性判断，缺一项就是接口回退。"""
    required = (
        "source_id", "display_name", "file", "url", "sha256", "size",
        "protocol_version", "needs_internet", "needs_credentials",
        "refresh_past_days", "refresh_future_days", "layers",
    )
    for p in _registry()["plugins"]:
        for key in required:
            assert key in p, f"{p.get('source_id')} 缺字段 {key}"
        assert p["display_name"], f"{p['source_id']} 的 display_name 为空"
        assert p["protocol_version"] >= 1
        assert isinstance(p["layers"], list) and p["layers"], (
            f"{p['source_id']} 没有图层，安装器无从展示"
        )
        for layer in p["layers"]:
            assert {"layer_id", "display_name", "kind"} <= set(layer)


def test_registry_protocol_version_tracks_app():
    """顶层 protocol_version = 生成本索引时的 app 所支持的协议版本。

    刻意**不**要求每个插件的 protocol_version 都等于它：目录里出现「要求比当前 app
    更新的插件」是合法的（插件先发布、app 后跟上），安装器届时按版本明确拒绝即可。
    若在这里卡死，就等于「插件一升版本，索引就生成不出来」，反而把目录锁死。
    """
    from tt_calendar.sources.base import Source

    reg = _registry()
    assert reg["protocol_version"] == Source.PROTOCOL_VERSION
    for p in reg["plugins"]:
        assert p["protocol_version"] >= 1, p["source_id"]