"""T6 收尾的判据：报告与验收清单「说的和真的一样」。

为什么要有这个测试：给 Rowan 的验收清单如果引用了不存在的 make 目标、
不存在的截图，那这份清单本身就是假证据 —— 比没有更糟。这里把
「文档所说」和「仓库实际」钉在一起：

1. 两份文档存在、不是空壳，报告把五块关键词都点到；
2. 清单里出现的每个 make 目标，必须真在 Makefile 里；
3. 清单里出现的每个命令行开关，必须真被 sammy 认识；
4. 报告引用的每张图 / 视频，必须真存在；
5. 素材目录 5 件套齐全，PNG 能按尺寸解析、视频有 MP4 头。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REPORT = DOCS / "REPORT-8H.md"
CHECKLIST = DOCS / "CHECKLIST-8H.md"
MEDIA = DOCS / "8h"

# 素材 5 件套（由 scripts/report_8h_media.py 生成，make report-media 可重生成）。
MEDIA_FILES = (
    "faceonly-1024x768.png",
    "faceonly-800x480.png",
    "window-chat.png",
    "face-strip.png",
    "demo.mp4",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_two_docs_exist_and_not_hollow():
    report = _text(REPORT)
    checklist = _text(CHECKLIST)
    assert len(report) >= 2000, "报告太短，像没写完"
    assert len(checklist) >= 800, "清单太短，像没写完"
    for kw in ("心情", "回忆", "face-only", "看门狗", "MCP"):
        assert kw in report, f"报告里没点到：{kw}"
    assert "CHECKLIST-8H" in report, "报告末尾要指到验收清单"


def _makefile_targets() -> set[str]:
    out: set[str] = set()
    for line in _text(ROOT / "Makefile").splitlines():
        m = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*:(?!=)", line)
        if m:
            out.add(m.group(1))
    return out


def _cli_flags() -> set[str]:
    src = _text(ROOT / "src" / "sammy" / "__main__.py")
    flags = set(re.findall(r'"(--[a-z][a-z0-9-]+)"', src))
    flags.add("--help")
    return flags


def test_checklist_commands_are_real():
    targets = _makefile_targets()
    flags = _cli_flags()
    used_targets: set[str] = set()
    used_flags: set[str] = set()
    for doc in (REPORT, CHECKLIST):
        text = _text(doc)
        used_targets |= set(re.findall(r"make ([a-z][a-z0-9-]*)", text))
        used_flags |= set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]+", text))
    missing_t = sorted(used_targets - targets)
    missing_f = sorted(used_flags - flags)
    assert not missing_t, f"引用了不存在的 make 目标：{missing_t}"
    assert not missing_f, f"引用了不存在的命令行开关：{missing_f}"


def test_report_media_links_exist():
    links = re.findall(r"\]\((8h/[^)\s]+)\)", _text(REPORT))
    assert links, "报告里至少要引用一张图或视频"
    for rel in links:
        assert (DOCS / rel).exists(), f"报告引用的文件不存在：{rel}"


def _png_size(path: Path) -> tuple[int, int]:
    blob = path.read_bytes()
    assert blob[:4].hex() == "89504e47", f"{path.name} 不是 PNG"
    assert blob[12:16] == b"IHDR", f"{path.name} 缺 IHDR"
    return int.from_bytes(blob[16:20], "big"), int.from_bytes(blob[20:24], "big")


def test_media_set_complete_and_sane():
    for name in MEDIA_FILES:
        p = MEDIA / name
        assert p.exists(), f"素材缺失：{name}"
        assert p.stat().st_size > 10_000, f"{name} 太小，像空文件"
    for name in MEDIA_FILES:
        if name.endswith(".png"):
            w, h = _png_size(MEDIA / name)
            assert w >= 400 and h >= 200, f"{name} 尺寸不对：{w}x{h}"
    head = (MEDIA / "demo.mp4").read_bytes()[:64]
    assert b"ftyp" in head, "demo.mp4 不是 MP4 封装"


def test_checklist_has_checkboxes():
    assert _text(CHECKLIST).count("- [ ]") >= 6, "清单要有至少 6 条可勾选条目"
