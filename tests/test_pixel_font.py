"""像素字体（U1）：文件在不在、能不能注册、字号有没有吸到像素网格、许可证带没带。

为什么这些要测：字体的失效方式全是**静默**的 ——
- 文件没进仓库 → 换台机器就回落系统字体，界面悄悄变回"现代感"，没人报错；
- 字号不是设计字号的整数倍 → 字形糊一格，看着"有点脏"但说不上哪不对；
- 许可证没随分发 → 法律问题，而且不会有人提醒你。
所以四条都钉住：**文件在、注册得上、字号在网格上、许可证与出处都在。**
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from fontTools.ttLib import TTFont

from sammy import layout
from sammy.paths import fonts_dir

FONT_FILE = fonts_dir() / layout.PIXEL_FONT_NAME


def test_font_file_is_shipped():
    """字体必须跟着仓库走（没进仓库 = 换台机器就没像素字了）。"""
    assert FONT_FILE.is_file(), f"字体不在：{FONT_FILE}"
    size_mb = FONT_FILE.stat().st_size / 1024 / 1024
    assert 0.3 < size_mb < 4, f"字体大小异常：{size_mb:.2f}MB（子集目标 ~1.5MB）"


def test_font_family_name_is_ours_not_upstream():
    """OFL 要求：**改动过的字体不得沿用上游保留名**。我们子集过，所以必须改名。"""
    font = TTFont(str(FONT_FILE))
    families = {r.toUnicode() for r in font["name"].names if r.nameID == 1}
    assert families == {"Sammy Pixel"}, f"家族名不对：{families}"
    assert not any("Fusion" in f or "Ark" in f for f in families), "沿用了上游字体名"


def test_font_covers_everyday_chinese():
    """抽查日常用字 —— 少一个字就是屏幕上出现一个方块。"""
    cmap = TTFont(str(FONT_FILE)).getBestCmap()
    probe = "你好萨米嗨在干嘛呢我你他的一二三四五六七八九十，。！？、：；（）“”…—"
    missing = [c for c in probe if ord(c) not in cmap]
    assert not missing, f"这些字缺字形：{missing}"
    assert len(cmap) > 6000, f"覆盖太少：{len(cmap)} 个码位（GB2312 子集应 ≥7000）"


def test_font_registers_with_qt(qapp, monkeypatch):
    """真的能被 Qt 认出来（不是"文件在"就算数）。"""
    monkeypatch.setattr(layout, "FAMILY", "（未加载）")
    got = layout.load_fonts()
    assert got == "Sammy Pixel", f"注册后家族名是 {got!r}"
    from PySide6.QtGui import QFontDatabase

    assert "Sammy Pixel" in QFontDatabase.families(), "Qt 的字体表里没有它"


def test_missing_font_falls_back_and_says_so(qapp, monkeypatch, tmp_path, capsys):
    """字体不在 → 回落系统字体，并且**说明**（静默回落最难查）。"""
    monkeypatch.setattr(layout, "fonts_dir", lambda: tmp_path)  # 空目录
    monkeypatch.setattr(layout, "FAMILY", "Sammy Pixel")
    got = layout.load_fonts()
    assert got == layout.FALLBACK_FAMILY, "没回落"
    assert "像素字体不在" in capsys.readouterr().out, "回落了却没吭声"
    monkeypatch.setattr(layout, "FAMILY", "Sammy Pixel")  # 收拾干净


@pytest.mark.parametrize(
    "raw,want",
    [(12, 12), (18, 12), (20, 24), (22, 24), (26, 24), (30, 24), (36, 36), (48, 48), (6, 12)],
)
def test_snap_to_pixel_grid(raw, want):
    """吸到 12 的整数倍；平手取小（宁可小一点也别糊）。"""
    assert layout.snap_to_pixel(raw) == want


def test_every_ui_font_size_is_on_the_pixel_grid():
    """界面上用的每一个字号都必须在网格上 —— 否则字形糊一格。"""
    for name in ("FONT_LABEL", "FONT_STATUS", "FONT_MY", "FONT_REPLY", "FONT_INPUT"):
        size = getattr(layout, name)
        assert size % layout.PIXEL_STEP == 0, f"{name}={size} 不在 {layout.PIXEL_STEP} 的倍数上"


def test_reply_sizes_are_on_the_grid_and_descending():
    sizes = layout.REPLY_SIZES
    assert all(s % layout.PIXEL_STEP == 0 for s in sizes), "回复区字号不在网格上"
    assert list(sizes) == sorted(sizes, reverse=True), "应当从大到小试"


def test_license_and_credit_are_shipped():
    """OFL-1.1 要求随分发带上许可证与出处 —— 这条是法律问题，不是审美问题。"""
    lic = fonts_dir() / "LICENSE-OFL.txt"
    readme = fonts_dir() / "README.md"
    assert lic.is_file(), "少了 OFL 许可证原文"
    text = lic.read_text(encoding="utf-8", errors="replace").lower()
    assert "open font license" in text, "许可证文件内容不对"
    assert readme.is_file(), "少了出处说明"
    body = readme.read_text(encoding="utf-8")
    assert "fusion-pixel-font" in body and "OFL" in body, "说明里没写出处与许可"
