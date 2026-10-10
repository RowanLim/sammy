"""屏幕自适应：一份设计值铺满任意屏。

为什么值得测：接线前这些位置是**写死在 pet.py 里的常量**（800×480 一套），
接线后由 `layout` 按窗口尺寸算出来。算错的表现是"某块屏上元素错位 / 脸被拉伸"——
而且**只在那块屏上出现**，本机看着一切正常。
所以这里把"任意尺寸都不该出的错"逐条钉住，而不是靠人肉换屏看截图。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import faces, layout

# 接线前写死在 pet.py 里的值 —— 必须逐项相等，否则就是"接线改坏了设计尺寸"
DESIGN = {
    "panel": (2, 2, 796, 476),
    "close": (752, 34, 20),
    "status_y": 242,
    "divider_y": 284,
    "my_line": (46, 290, 708, 30),
    "reply": (46, 324, 708, 70),
    "input": (46, 400, 708, 50),
}

SIZES = [
    (800, 480),  # 设计基准（树莓派 5 寸屏）
    (1920, 1080),  # 用户的小屏（16:9）
    (1280, 1024),  # 4:3
    (800, 640),  # 更高的比例
    (480, 800),  # 竖屏
    (3840, 1080),  # 带鱼屏
    (440, 264),  # 桌面浮窗（0.55 倍）
]


def _rect(r) -> tuple[int, int, int, int]:
    return (r.x(), r.y(), r.width(), r.height())


def test_design_size_matches_the_old_hardcoded_values():
    """800×480 上必须和接线前的写死常量**逐项相等**。"""
    L = layout.layout_dev(800, 480)
    assert _rect(L.panel) == DESIGN["panel"]
    assert (L.close_c.x(), L.close_c.y(), L.close_r) == DESIGN["close"]
    assert L.status.y() == DESIGN["status_y"]
    assert L.divider_y == DESIGN["divider_y"]
    assert _rect(L.my_line) == DESIGN["my_line"]
    assert _rect(L.reply) == DESIGN["reply"]
    assert _rect(L.input) == DESIGN["input"]
    assert L.scale == 1.0


def test_design_size_face_keeps_its_place():
    """设计尺寸上脸的位置就是 `face_box()` 原样（不重新居中出偏差）。"""
    L = layout.layout_dev(800, 480)
    assert _rect(L.face) == _rect(faces.face_box())


@pytest.mark.parametrize("wh", SIZES)
def test_everything_stays_inside_the_panel(wh):
    """任何屏上元素都不许越出面板（越界 = 被裁掉）。"""
    w, h = wh
    L = layout.layout_dev(w, h)
    panel = L.panel
    for name in ("status", "my_line", "reply", "input"):
        r = getattr(L, name)
        assert r.x() >= panel.x(), f"{name} 越出左边"
        assert r.y() >= panel.y(), f"{name} 越出上边"
        assert r.right() <= panel.right(), f"{name} 越出右边"
        assert r.bottom() <= panel.bottom(), f"{name} 越出下边"
    # 关闭按钮（圆）整个在面板里
    assert L.close_c.x() - L.close_r >= panel.x()
    assert L.close_c.x() + L.close_r <= panel.right()
    assert L.close_c.y() - L.close_r >= panel.y()


@pytest.mark.parametrize("wh", SIZES)
def test_face_is_never_stretched(wh):
    """脸只等比缩放 —— 换屏不该把人脸压扁（这是"自适应"的红线）。"""
    w, h = wh
    fb = faces.face_box()
    L = layout.layout_dev(w, h)
    want = fb.width() / fb.height()
    got = L.face.width() / L.face.height()
    assert abs(got - want) < 0.06, f"{w}×{h} 上脸被拉伸了（{got:.3f} vs {want:.3f}）"


@pytest.mark.parametrize("wh", SIZES)
def test_face_is_horizontally_centered(wh):
    w, h = wh
    L = layout.layout_dev(w, h)
    left = L.face.x() - L.panel.x()
    right = L.panel.right() - L.face.right()
    assert abs(left - right) <= 2, f"{w}×{h} 上脸没居中（左 {left} / 右 {right}）"


def test_wide_screen_uses_the_extra_width():
    """16:9 上多出来的宽度必须被用掉 —— 否则右边白白空一条（这正是这次要修的现象）。"""
    base = layout.layout_dev(800, 480)
    wide = layout.layout_dev(1920, 1080)
    assert wide.canvas_w > base.canvas_w, "画布没变宽"
    assert wide.reply.width() > base.reply.width(), "回复区没变宽"
    assert wide.input.width() > base.input.width(), "输入框没变宽"
    assert wide.panel.width() > base.panel.width()


def test_tall_screen_gives_the_extra_height_to_the_reply():
    """更高的比例：多出来的高度给回复区 —— 文字最缺的就是地方。"""
    base = layout.layout_dev(800, 480)
    tall = layout.layout_dev(800, 640)
    assert tall.canvas_h > base.canvas_h
    assert tall.reply.height() > base.reply.height(), "回复区没变高，白多的高度被浪费了"


@pytest.mark.parametrize("wh", SIZES)
def test_input_sits_near_the_bottom(wh):
    """输入框贴底：任何尺寸下离画布底边的距离都等于设计值 × 缩放。"""
    w, h = wh
    L = layout.layout_dev(w, h)
    gap = round(L.canvas_h) - L.input.bottom()
    assert abs(gap - layout.BOTTOM) <= 2, f"{w}×{h} 输入框没贴底（离底 {gap}）"


def test_pixel_version_agrees_with_device_version():
    """两种口径必须描述同一份版面（像素版 = 设备版 × scale），否则会各算各的。"""
    for w, h in SIZES:
        p = layout.layout_for(w, h)
        d = layout.layout_dev(w, h)
        assert abs(p.scale - d.scale) < 1e-6
        for name in ("panel", "reply", "input", "my_line"):
            rp, rd = getattr(p, name), getattr(d, name)
            assert abs(rp.x() - round(rd.x() * p.scale)) <= 2, f"{name}.x 不一致"
            assert abs(rp.width() - round(rd.width() * p.scale)) <= 2, f"{name}.width 不一致"


def test_bad_size_raises():
    for bad in ((0, 480), (800, 0), (-1, -1)):
        with pytest.raises(ValueError):
            layout.layout_dev(*bad)


# ── face-only 形态（小屏：只留一张脸 + 一行状态）──────────────

FO_SIZES = [
    (800, 480),  # 设计基准（树莓派 5 寸屏）
    (1024, 768),  # 4:3 —— 复古壳那台
    (1024, 600),  # 5:3 变体（10 寸小屏常见）
    (1280, 720),  # 16:9
    (1280, 1024),  # 4:3（大一点）
    (1920, 1080),  # 用户的小屏（16:9）
    (3840, 1080),  # 带鱼屏
    (480, 800),  # 竖屏
    (440, 264),  # 桌面浮窗（0.55 倍）
]


def test_faceonly_design_size_matches_the_pinned_numbers():
    """800×480 上逐项钉死 —— face-only 改坏了这里必须响。"""
    fo = layout.faceonly_layout(800, 480)
    assert fo.scale == 1.0
    assert (round(fo.canvas_w), round(fo.canvas_h)) == (800, 480)
    assert _rect(fo.face) == (70, 30, 660, 324)
    assert _rect(fo.status) == (46, 378, 708, 72)
    assert (fo.close_c.x(), fo.close_c.y(), fo.close_r) == (752, 34, 20)
    assert fo.font_status == 40


def test_faceonly_has_only_a_face_and_one_line():
    """ "只留一张脸 + 一行状态"要在**结构上**成立：回复区 / 输入框 / 我的话都不存在。

    不是"不画"，是**没有这些字段** —— 这样不存在"哪天有人加回一段绘制"的漏洞。
    """
    fo = layout.faceonly_layout(800, 480)
    for banned in ("reply", "input", "my_line", "divider_y"):
        assert not hasattr(fo, banned), f"face-only 里不该有 {banned}"


@pytest.mark.parametrize("wh", FO_SIZES)
def test_faceonly_face_is_always_bigger_than_the_full_version(wh):
    """同一块屏上，face-only 的脸必须明显更大（不然这个形态毫无意义）。"""
    w, h = wh
    fo = layout.faceonly_layout(w, h)
    full = layout.layout_dev(w, h)
    assert fo.face.width() >= full.face.width() * 1.4, f"{w}×{h} 上脸没变大"
    assert fo.face.height() >= full.face.height() * 1.4, f"{w}×{h} 上脸没变高"


@pytest.mark.parametrize("wh", FO_SIZES)
def test_faceonly_fonts_are_enlarged(wh):
    """ "字号加大"的判据：状态行字号 ≥ 完整版的 1.5 倍。"""
    w, h = wh
    fo = layout.faceonly_layout(w, h)
    full = layout.layout_dev(w, h)
    assert fo.font_status >= full.font_status * 1.5, f"{w}×{h} 上字号没加大"


@pytest.mark.parametrize("wh", FO_SIZES)
def test_faceonly_everything_stays_inside_the_panel(wh):
    w, h = wh
    fo = layout.faceonly_layout(w, h)
    panel = fo.panel
    for name in ("face", "status"):
        r = getattr(fo, name)
        assert r.x() >= panel.x() and r.y() >= panel.y(), f"{w}×{h} {name} 越出左上"
        assert r.right() <= panel.right(), f"{w}×{h} {name} 越出右边"
        assert r.bottom() <= panel.bottom(), f"{w}×{h} {name} 越出下边"
    assert fo.close_c.x() - fo.close_r >= panel.x()
    assert fo.close_c.x() + fo.close_r <= panel.right()
    assert fo.close_c.y() + fo.close_r <= panel.bottom()


@pytest.mark.parametrize("wh", FO_SIZES)
def test_faceonly_face_is_never_stretched(wh):
    w, h = wh
    fo = layout.faceonly_layout(w, h)
    fb = faces.face_box()
    assert abs(fo.face.width() / fo.face.height() - fb.width() / fb.height()) < 0.06


@pytest.mark.parametrize("wh", FO_SIZES)
def test_faceonly_face_is_horizontally_centered(wh):
    w, h = wh
    fo = layout.faceonly_layout(w, h)
    left = fo.face.x() - fo.panel.x()
    right = fo.panel.right() - fo.face.right()
    assert abs(left - right) <= 2, f"{w}×{h} 上脸没居中（左 {left} / 右 {right}）"


@pytest.mark.parametrize("wh", FO_SIZES)
def test_faceonly_face_never_collides_with_the_close_button(wh):
    """脸再大也不许蹭到右上角的 ✕ —— 这是有意的容量上限，不是巧合。"""
    w, h = wh
    fo = layout.faceonly_layout(w, h)
    assert fo.face.right() < fo.close_c.x() - fo.close_r, f"{w}×{h} 上脸蹭到关闭按钮"


@pytest.mark.parametrize("wh", FO_SIZES)
def test_faceonly_line_has_room_for_exactly_one_line(wh):
    """状态行的高度：放得下那号字，但明显放不下两行（它就是"一行状态"）。"""
    w, h = wh
    fo = layout.faceonly_layout(w, h)
    assert fo.status.height() >= fo.font_status
    assert fo.status.height() < fo.font_status * 2


@pytest.mark.parametrize("wh", FO_SIZES)
def test_faceonly_face_and_line_do_not_overlap(wh):
    w, h = wh
    fo = layout.faceonly_layout(w, h)
    gap = fo.status.y() - (fo.face.y() + fo.face.height())
    assert gap >= layout.FO_GAP - 2, f"{w}×{h} 上脸和状态行挤在一起（缝 {gap}）"


def test_faceonly_bad_size_raises():
    for bad in ((0, 480), (800, 0), (-1, -1)):
        with pytest.raises(ValueError):
            layout.faceonly_layout(*bad)
