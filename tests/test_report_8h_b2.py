"""U5 收尾的判据：第二轮 UI 的验收清单「说的和真的一样」。

为什么要有这个测试：给 Rowan 的清单如果引用了不存在的 make 目标、
不存在的图 / 视频，那这份清单本身就是假证据 —— 比没有更糟。
这里把「文档所说」和「仓库实际」钉在一起：

1. 清单存在、不是空壳，四件事（字 / 脸 / 话 / 质感）与六个拍板点都点到；
2. 清单里出现的每个 make 目标、每个命令行开关，必须真在仓库里；
3. 清单引用的每张图 / 视频必须真实存在、能按尺寸解析；
4. 素材三件套齐全（两张对比图 + 一条视频），且生成脚本随仓库走；
5. 「之前 / 现在」那一幕的两句文本，在两个脚本里逐字一致（对比才公平）。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CHECKLIST = DOCS / "CHECKLIST-8H-B2.md"
MEDIA = DOCS / "8h-b2"

# 素材三件套（由 scripts/u5_preview.py 生成，make ui-media 可重生成）。
MEDIA_FILES = ("before-after.png", "before-after-zoom.png", "ui-demo.mp4")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_checklist_exists_and_covers_four_blocks():
    text = _text(CHECKLIST)
    assert len(text) >= 1500, "清单太短，像没写完"
    for kw in ("像素字体", "凝视", "打字机", "CRT", "拍板"):
        assert kw in text, f"清单里没点到：{kw}"
    assert text.count("- [ ]") >= 8, "清单要有足够多可勾选条目"


def test_six_decision_points_are_marked():
    marks = re.findall(r"[①②③④⑤⑥]", _text(CHECKLIST))
    assert len(marks) == 6, f"拍板点应是 6 个，实际标了 {len(marks)} 个"


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
    text = _text(CHECKLIST)
    used_targets = set(re.findall(r"make ([a-z][a-z0-9-]*)", text))
    used_flags = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]+", text))
    missing_t = sorted(used_targets - targets)
    missing_f = sorted(used_flags - flags)
    assert not missing_t, f"引用了不存在的 make 目标：{missing_t}"
    assert not missing_f, f"引用了不存在的命令行开关：{missing_f}"


def test_checklist_media_links_exist():
    links = re.findall(r"\]\((8h-b2/[^)\s]+)\)", _text(CHECKLIST))
    assert links, "清单里至少要引用一张对比图或视频"
    for rel in links:
        assert (DOCS / rel).exists(), f"清单引用的文件不存在：{rel}"


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
            assert w >= 800 and h >= 200, f"{name} 尺寸不对：{w}x{h}"
    head = (MEDIA / "ui-demo.mp4").read_bytes()[:64]
    assert b"ftyp" in head, "ui-demo.mp4 不是 MP4 封装"


def test_u5_scripts_are_shipped():
    for rel in ("scripts/u5_preview.py", "scripts/u5_baseline_shot.py"):
        assert (ROOT / rel).is_file(), f"生成脚本不在仓库里：{rel}"


def test_comparison_scene_texts_match():
    """对比图的「之前 / 现在」必须是同一幕 —— 两边的文本逐字一致。"""

    def reply_of(rel: str) -> str:
        m = re.search(r'^REPLY = "(.+)"$', _text(ROOT / rel), re.M)
        assert m, f"{rel} 里找不到 REPLY"
        return m.group(1)

    assert reply_of("scripts/u5_preview.py") == reply_of("scripts/u5_baseline_shot.py")
