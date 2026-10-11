"""输入框接上像素字体 —— U1 的漏网面补完（自选小步，第四步）。

怎么发现的：U1 把界面全换成像素字之后，验收清单里写着
「看状态行 / 你的输入框 / 它的回复 —— 全都是像素字」。但输入框是
**QLineEdit 子控件**：它的字走样式表，而样式表里只写了 font-size、
没写 font-family —— 实测量到的家族名是 Sans Serif（系统字体默认那个）。
典型的静默失效，不专门测就发现不了。

判据三层：
1. 样式表必须点名 layout.FAMILY（含字体缺失时的回落路径）；
2. 真 Qt 解析：input.font() 的家族与度量对得上像素字体；
3. 像素证据：把家族换回系统字体，同一句话渲染出大量像素差异 ——
   证明这一步真的影响屏幕，不是只改了个字符串。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QRect
from PySide6.QtGui import QFont, QFontMetricsF, QImage

from sammy import layout
from sammy.paths import fonts_dir

pytestmark = pytest.mark.usefixtures("qapp")  # 窗口层要 QApplication

FONT_FILE = fonts_dir() / layout.PIXEL_FONT_NAME


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


@pytest.fixture(scope="module", autouse=True)
def _fonts_registered(qapp):
    """整个模块先把像素字体注册进 Qt —— 和真机启动顺序一致。"""
    got = layout.load_fonts()
    assert got == "Sammy Pixel", f"像素字体没注册上：{got!r}"


@pytest.fixture
def win():
    from sammy.pet import SammyWindow

    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.finish_typing()
    # 必须 show：离屏下不 show 的窗口，grab 抓到的 QLineEdit 是陈旧画面
    # （父窗口重画了、子控件没有 —— 修复前的像素证据会假 0 差异）
    w.show()
    yield w
    w.close()


def _crop_input(w) -> tuple[bytes, int, int, int]:
    """抓窗口，裁「输入框内部一小圈」（避开边框与圆角），返回原始字节。"""
    img = w.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    g = w.input.geometry()
    sub = img.copy(QRect(g.x() + 3, g.y() + 3, g.width() - 6, g.height() - 6))
    return bytes(sub.constBits()), sub.bytesPerLine(), sub.width(), sub.height()


def _diff_pixels(a, b) -> int:
    (ba, sa, wa, ha), (bb, sb, wb, hb) = a, b
    n = 0
    for y in range(min(ha, hb)):
        for x in range(min(wa, wb)):
            i, j = y * sa + x * 4, y * sb + x * 4
            if ba[i : i + 3] != bb[j : j + 3]:
                n += 1
    return n


def _strip_family(w) -> None:
    """把样式表里的 font-family 拿掉（= 修复前的行为，只差这一项）。"""
    qss = w.input.styleSheet()
    stripped = qss.replace(f'font-family: "{layout.FAMILY}";', "")
    assert stripped != qss, "样式表里没有可拆的 font-family"
    w.input.setStyleSheet(stripped)
    w.input.ensurePolished()


# ── 一、样式表点名家族 ─────────────────────────────


def test_stylesheet_names_the_current_family(win):
    qss = win.input.styleSheet()
    assert f'font-family: "{layout.FAMILY}"' in qss, f"样式表没点名家族：{qss}"


def test_family_follows_the_fallback_path(win, monkeypatch):
    """字体文件缺失时 FAMILY 会变成回落家族 —— 输入框必须跟着变。"""
    monkeypatch.setattr(layout, "FAMILY", layout.FALLBACK_FAMILY)
    win._layout_input()
    assert f'font-family: "{layout.FALLBACK_FAMILY}"' in win.input.styleSheet()
    win.input.ensurePolished()
    assert win.input.font().family() == layout.FALLBACK_FAMILY


# ── 二、真 Qt 解析 ─────────────────────────────────


def test_input_font_really_resolves_to_the_pixel_family(win):
    win.input.ensurePolished()
    f = win.input.font()
    assert f.family() == "Sammy Pixel", f"解析到的家族是 {f.family()!r}"
    ref = QFont(layout.FAMILY)
    ref.setPixelSize(f.pixelSize())
    sample = "你好 Sammy 123，在吗？"
    got = QFontMetricsF(f).horizontalAdvance(sample)
    want = QFontMetricsF(ref).horizontalAdvance(sample)
    assert got == pytest.approx(want, abs=0.01), f"度量对不上：{got} 对 {want}"


def test_input_pixel_size_follows_the_scale(win):
    win.input.ensurePolished()
    assert win.input.font().pixelSize() == int(win.lay.font_input * win.scale)
    # 缩放 1.0（树莓派整屏那种）下，字号就是设备字号本身、在 12 的网格上
    win.scale = 1.0
    win._relayout()
    win._layout_input()
    win.input.ensurePolished()
    assert win.lay.font_input % layout.PIXEL_STEP == 0
    assert win.input.font().pixelSize() == win.lay.font_input


# ── 三、像素证据 ───────────────────────────────────


def test_render_changes_when_family_reverts_to_system(win):
    """把家族换回系统字体：同一扇窗、同一句话，渲染必须明显不同。

    这是整组判据里唯一直接盯屏幕的一条 —— 前几条都可能被
    「字符串写对了、但 Qt 没吃进去」骗过，这条不会。
    """
    a = _crop_input(win)
    _strip_family(win)
    b = _crop_input(win)
    win._layout_input()  # 换回来，别污染后面的用例
    n = _diff_pixels(a, b)
    assert n > 400, f"占位文字只差 {n} 个像素 —— 家族很可能没真生效"


def test_render_changes_for_typed_text_too(win):
    win.input.setText("你好 Sammy 在吗？")
    win.input.ensurePolished()
    a = _crop_input(win)
    _strip_family(win)
    b = _crop_input(win)
    win._layout_input()
    n = _diff_pixels(a, b)
    assert n > 400, f"已输入文字只差 {n} 个像素 —— 家族很可能没真生效"


# ── 四、防复发与素材 ───────────────────────────────


def test_any_stylesheet_with_a_font_size_also_sets_a_family():
    """根因防复发：任何设了字号的地方都必须同时点名家族。

    QLineEdit 这类子控件不跟随 QPainter 的字体设置，漏一个 family
    就是一次静默的系统字体回落 —— 这一次就是这么漏的。
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for p in (root / "src").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        if "font-size" in src and "font-family" not in src:
            offenders.append(p.name)
    assert offenders == [], f"设了字号却没设家族：{offenders}"


def test_placeholder_text_has_no_missing_glyphs(win):
    """占位文字与常用输入示例的每个字都在字体子集里（不然是方块）。"""
    from fontTools.ttLib import TTFont

    cmap = TTFont(str(FONT_FILE)).getBestCmap()
    samples = [win.input.placeholderText(), "你好 Sammy 在吗", "你：今天好累啊"]
    for s in samples:
        missing = [c for c in s if not c.isspace() and ord(c) not in cmap]
        assert not missing, f"{s!r} 缺字形：{missing}"


def test_media_script_and_asset_are_shipped():
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "input_font_preview.py").is_file()
    assert "input-font-media" in (root / "Makefile").read_text(encoding="utf-8")
    p = root / "docs" / "8h-b2" / "input-font.png"
    assert p.is_file(), f"缺素材：{p.name}"
    assert p.stat().st_size > 10_000, "素材太小，像空壳"
