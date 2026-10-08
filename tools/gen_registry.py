"""从插件自身的类声明生成 registry.json（插件市场的机器可读索引）。

为什么不手写 registry：插件的 .py 里已经声明了 source_id / display_name /
PROTOCOL_VERSION / 图层清单等信息。手写的索引迟早会和代码漂移——改了代码忘了
改索引，市场上就会出现「说 A 实际是 B」的条目。这里直接 import 插件读声明，
让二者不可能不一致；tests/test_registry.py 负责在 CI 里挡住漂移。

用法：
    python tools/gen_registry.py                       # 校验并写回 registry.json
    python tools/gen_registry.py --check               # 只校验，不写（CI 用）
    python tools/gen_registry.py --repo owner/name --branch main   # 换源

输出刻意做成**字节稳定**（键序固定、插件按 source_id 排序、不含时间戳），
这样 --check 就是一次纯字节比对，不会有「每次跑都变」的噪声 diff。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SLUG = "TTDiang2/TT_Calendar_Plugins"
DEFAULT_BRANCH = "main"
REGISTRY_NAME = "registry.json"
SCHEMA_VERSION = 1


def _load_tt_calendar() -> None:
    """让 tools/ 能在没有安装 tt_calendar 的环境里跑（测试即在 app 源码树内运行）。

    先找同级的 TT_Calendar 源码树，再退到已安装的包。找不到就报错并说清怎么办，
    而不是抛一个难懂的 ModuleNotFoundError。
    """
    try:
        import tt_calendar  # noqa: F401
        return
    except ImportError:
        pass

    for parent in (REPO_ROOT.parent, REPO_ROOT.parent.parent):
        for name in ("TT_Calendar", "tt-calendar", "TT_Calendar_Neo"):
            cand = parent / name
            if (cand / "tt_calendar" / "__init__.py").exists():
                sys.path.insert(0, str(cand))
                return

    raise SystemExit(
        "找不到 tt_calendar 包。请在 TT_Calendar 源码树内运行本脚本，"
        "或先 pip install 后再运行（插件仓库的测试同样依赖它）。"
    )


def plugin_files() -> list[Path]:
    """仓库根下的插件文件。排除下划线开头、tools/、tests/ 与非 .py。"""
    out = [
        p for p in REPO_ROOT.glob("*.py")
        if not p.name.startswith("_") and p.name != REGISTRY_NAME
    ]
    return sorted(out, key=lambda p: p.name)


def describe(path: Path, slug: str, branch: str) -> dict[str, Any] | None:
    """加载一个插件文件，返回它的注册表条目；文件里没有 Source 子类则 None。"""
    from tt_calendar.sources.base import Source

    mod_name = f"_registry_probe_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"{path.name}: 无法作为 Python 模块加载")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SystemExit(f"{path.name}: 加载失败（{exc.__class__.__name__}: {exc}）")

    raw = path.read_bytes()
    entries: list[dict[str, Any]] = []
    for name in dir(module):
        obj = getattr(module, name)
        if not isinstance(obj, type) or not issubclass(obj, Source) or obj is Source:
            continue
        if not getattr(obj, "source_id", ""):
            continue
        if getattr(obj, "__abstractmethods__", None):
            continue

        inst = obj()
        specs = inst.layer_specs()
        entries.append({
            "source_id": obj.source_id,
            "display_name": obj.display_name,
            "file": path.name,
            "url": f"https://raw.githubusercontent.com/{slug}/{branch}/{path.name}",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            # 插件要求 ≥ N 的 app；比 app 低的不受影响，只有高的会被加载器拦下
            "protocol_version": int(getattr(obj, "PROTOCOL_VERSION", 1)),
            "group": getattr(obj, "group", "") or obj.display_name,
            "needs_internet": bool(obj.needs_internet),
            "needs_credentials": bool(obj.needs_credentials),
            "refresh_past_days": obj.refresh_past_days,
            "refresh_future_days": obj.refresh_future_days,
            "has_field_specs": inst.field_specs() is not None,
            "layers": [
                {
                    "layer_id": s.layer_id,
                    "display_name": s.display_name,
                    "kind": s.kind,
                    "enabled_by_default": bool(s.enabled),
                }
                for s in sorted(specs, key=lambda s: s.layer_id)
            ],
        })

    if not entries:
        return None
    if len(entries) > 1:
        ids = ", ".join(e["source_id"] for e in entries)
        raise SystemExit(
            f"{path.name}: 一个文件里出现了多个 Source（{ids}）。"
            "一个文件一个源，否则下载/卸载无法对应。"
        )
    return entries[0]


def build(slug: str, branch: str) -> dict[str, Any]:
    _load_tt_calendar()
    from tt_calendar.sources.base import Source

    plugins: list[dict[str, Any]] = []
    for path in plugin_files():
        entry = describe(path, slug, branch)
        if entry is not None:
            plugins.append(entry)

    seen: dict[str, str] = {}
    for p in plugins:
        if p["source_id"] in seen:
            raise SystemExit(
                f"source_id 重复：{p['source_id']!r} 同时出现在 "
                f"{seen[p['source_id']]} 与 {p['file']}"
            )
        seen[p["source_id"]] = p["file"]

    if not plugins:
        raise SystemExit("没有发现任何 Source 子类，registry 无从生成")

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": Source.PROTOCOL_VERSION,
        "plugins": sorted(plugins, key=lambda p: p["source_id"]),
    }


def render(registry: dict[str, Any]) -> str:
    return json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="从插件声明生成 registry.json")
    ap.add_argument("--check", action="store_true",
                    help="只校验 registry.json 是否与插件声明一致，不写文件")
    ap.add_argument("--repo", default=DEFAULT_SLUG, help=f"owner/name（默认 {DEFAULT_SLUG}）")
    ap.add_argument("--branch", default=DEFAULT_BRANCH, help=f"分支（默认 {DEFAULT_BRANCH}）")
    args = ap.parse_args()

    target = REPO_ROOT / REGISTRY_NAME
    want = render(build(args.repo, args.branch))

    if args.check:
        if not target.exists():
            print(f"✗ {REGISTRY_NAME} 不存在，请先运行：python tools/gen_registry.py")
            return 1
        have = target.read_text(encoding="utf-8")
        if have != want:
            print(f"✗ {REGISTRY_NAME} 与插件声明不一致。")
            print("  改了插件的声明/图层却没重生成索引。修复：python tools/gen_registry.py")
            return 1
        print(f"✓ {REGISTRY_NAME} 与插件声明一致（{len(json.loads(want)['plugins'])} 个插件）")
        return 0

    target.write_text(want, encoding="utf-8")
    n = len(json.loads(want)["plugins"])
    print(f"✓ 已写入 {REGISTRY_NAME}（{n} 个插件，{len(want.encode('utf-8'))} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())