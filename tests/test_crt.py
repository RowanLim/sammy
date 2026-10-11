"""CRT 质感（第二轮 U4）—— 扫描线 / 辉光 / 暗角。先写判据，实现对着判据做。

为什么这些必须变成数字：

- 扫描线是**锁定在窗口上的固定网格**（每 2 个物理像素一条暗线）。如果锁在内容上，
  动画一跑条纹就跟着画面漂，看上去像整机在抖 —— 用「暗行永远是绝对偶数行、
  跨帧不变」钉死；
- 辉光是「亮的地方往暗处渗」：数值上 = 亮边缘外的暗背景被点亮、远处不亮。
  不写断言，很容易做成「整屏糊一层灰」还看不出来；
- 暗角必须**只暗面板以内**：窗口是透明背景的浮窗，漏到外面等于在用户桌面上糊黑边；
- `SAMMY_CRT=off` 要回到 U4 之前的干净画面 —— 可关得是真可关，不是摆设。

测试环境里其余判据都跑在「CRT 关」的默认下（conftest 统一设置）：它们量的是内容
本身；这一层装饰在**这里**单独量，开、关两条路都验。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

pytestmark = pytest.mark.usefixtures("qapp")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

from sammy import crt  # noqa: E402

# ── 夹具 ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


def _make_window(face_only: bool = False):
    """稳态窗口：固定种子 + 固定时刻 + 打字机拨到尾（U2/U3 同款做法）。

    两个窗口（开/关）必须长得一模一样才能逐像素比 —— 种子不固定的话
    凝视漂移各飘各的，比出来全是假差异。
    """
    from sammy import anim
    from sammy.pet import SammyWindow

    w = SammyWindow(face_only=face_only, autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.anim = anim.Animator(seed=7)
    w.set_expression(3)
    w.anim_t = 1.0
    w.finish_typing()
    return w


@pytest.fixture
def win_on(qapp, monkeypatch):
    monkeypatch.setenv("SAMMY_CRT", "on")
    w = _make_window()
    yield w
    w.close()


@pytest.fixture
def win_off(qapp, monkeypatch):
    monkeypatch.setenv("SAMMY_CRT", "off")
    w = _make_window()
    yield w
    w.close()


# ── 抓手 ───────────────────────────────────────────


def _grab_rgb(w):
    """抓图 → (像素字节, 每行字节数)。字节序实测 [B,G,R,A]（RGB32）。"""
    img = w.grab().toImage().convertToFormat(QImage.Format_RGB32)
    return bytes(img.constBits()), img.bytesPerLine()


def _row_means(buf, stride, x0, x1, y0, y1, ch=1):
    """每一行的通道均值（默认 G 通道 —— 这张脸就是靠绿说事的）。"""
    out = []
    for y in range(y0, y1 + 1):
        vals = [buf[y * stride + x * 4 + ch] for x in range(x0, x1 + 1)]
        out.append(sum(vals) / len(vals))
    return out


def _no_stripe(rows, y0):
    """取「没有扫描线」的那些行（绝对奇数行）的均值。"""
    vals = [v for y, v in zip(range(y0, y0 + len(rows)), rows, strict=True) if y % 2 == 1]
    return sum(vals) / len(vals)


def _parity(rows, y0):
    """(偶数行均值, 奇数行均值)。

    为什么不用总和比：两组行数常常不等（43 行里偶数行 22、奇数行 21），
    总和比会被行数差顶出一个假比例（曾经算出 0.994 的假象）。
    """
    ev = [v for y, v in zip(range(y0, y0 + len(rows)), rows, strict=True) if y % 2 == 0]
    od = [v for y, v in zip(range(y0, y0 + len(rows)), rows, strict=True) if y % 2 == 1]
    return sum(ev) / len(ev), sum(od) / len(od)


# ── 纯函数层 ───────────────────────────────────────


def test_crt_switch_reads_like_the_other_switches():
    """开关语义和 SAMMY_ANIM 一套：默认开；off/0/false/no 才是关。"""
    assert crt.crt_enabled({}) is True
    assert crt.crt_enabled({"SAMMY_CRT": "on"}) is True
    for v in ("off", "OFF", " 0 ", "false", "No"):
        assert crt.crt_enabled({"SAMMY_CRT": v}) is False, v


def test_scanline_grid_is_every_second_row_starting_at_zero():
    """网格定义：从第 0 行起、每 2 行一条 —— 相位写死在这里。"""
    assert crt.scanline_rows(0, 10) == [0, 2, 4, 6, 8]
    assert crt.scanline_rows(3, 9) == [4, 6, 8]
    assert crt.scanline_rows(1, 2) == []


def test_crt_numbers_are_pinned():
    """这些数字是对账过的，改任何一个都要先想清楚（U5 会给 Rowan 拍板）。"""
    assert crt.SCANLINE_PERIOD == 2
    pinned = {
        "SCANLINE_ALPHA": 0.15,
        "VIGNETTE_ALPHA": 0.30,
        "VIGNETTE_INNER": 0.55,
        "GLOW_OPACITY": 0.40,
        "GLOW_DOWNSCALE": 6,
    }
    for name, want in pinned.items():
        assert getattr(crt, name) == pytest.approx(want), name


def test_vignette_curve_zero_until_inner_then_linear_to_cap():
    """暗角曲线：内圈不暗、往外线性加深、到角落顶格 —— 单调。"""
    assert crt.vignette_alpha_at(0.0) == 0.0
    assert crt.vignette_alpha_at(0.3) == 0.0
    assert crt.vignette_alpha_at(crt.VIGNETTE_INNER) == 0.0
    assert crt.vignette_alpha_at(1.0) == pytest.approx(0.30)
    mid = (crt.VIGNETTE_INNER + 1.0) / 2
    assert crt.vignette_alpha_at(mid) == pytest.approx(0.15)
    vals = [crt.vignette_alpha_at(f / 20) for f in range(21)]
    assert vals == sorted(vals)


def test_blur_spreads_brightness_outward_but_stays_bounded(qapp):
    """辉光的核：亮块被摊开（往外渗）但传播有界（远角落不许被点亮）。"""
    img = QImage(96, 96, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 255))  # 不透明底 —— 和真实缓冲一致
    for y in range(46, 50):
        for x in range(46, 50):
            img.setPixelColor(x, y, QColor(255, 255, 255, 255))
    out = crt.blur_downup(img)
    assert out.size() == img.size()
    assert out.pixelColor(48, 48).red() < 128  # 峰被摊平（原来是 255）
    assert out.pixelColor(52, 48).red() > 5  # 块外 2 像素还有光（往外渗）
    assert out.pixelColor(2, 2).red() == 0  # 远处不亮（有界）


def test_layer_has_stripes_vignette_and_panel_clip(qapp):
    """质感层成图的三件事：隔行暗线、越靠角越暗、面板外全透明。"""
    layer = crt.build_layer(
        220,
        140,
        panel=QRect(10, 10, 200, 120),
        panel_radius=12,
        scale=1.0,
        offset=(0, 0),
        dpr=1.0,
    )
    a = layer.pixelColor
    stripe = round(crt.SCANLINE_ALPHA * 255)
    assert a(110, 70).alpha() == stripe  # 中央偶数行：只有扫描线
    assert a(110, 71).alpha() == 0  # 中央奇数行：干净
    assert a(5, 5).alpha() == 0  # 面板外透明（圆角也裁）
    assert a(219, 139).alpha() == 0
    assert a(11, 11).alpha() == 0  # 拐角本身被圆角裁掉（半径 12）
    assert a(15, 15).alpha() > a(21, 21).alpha() > 0  # 面板内：越靠角越暗
    assert a(15, 15).alpha() >= 45
    assert layer.devicePixelRatio() == 1.0


# ── 真窗口层 ───────────────────────────────────────


def test_off_window_has_no_overlay_and_no_stripes(win_off):
    """关着：没有质感层对象，背景上也没有隔行结构。"""
    w = win_off
    assert w.crt_on is False
    assert getattr(w, "_crt_overlay", None) is None
    buf, stride = _grab_rgb(w)
    rows = _row_means(buf, stride, 3, 19, 84, 126)
    assert _no_stripe(rows, 84) == pytest.approx(sum(rows) / len(rows), abs=0.15)


def test_on_window_stripes_are_locked_to_even_rows_everywhere(win_on):
    """开着：暗行 = 绝对偶数行，整窗都是；连输入框上面那层也有。

    输入框是独立子控件（QLineEdit）—— 画在父窗口里的东西会被它盖住，
    所以质感层必须是单独一个盖在最上面的小控件。这条断言就是验它真的在上面。
    """
    w = win_on
    assert w.crt_on is True
    assert w._crt_overlay is not None
    assert bool(w._crt_overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
    buf, stride = _grab_rgb(w)
    g = _row_means(buf, stride, 3, 19, 84, 126)
    for i in range(0, len(g) - 1, 2):
        assert g[i] < g[i + 1], f"y={84 + i} 该暗却没暗"
    e, o = _parity(g, 84)
    assert e / o == pytest.approx(1 - crt.SCANLINE_ALPHA, abs=0.05)
    gr = _row_means(buf, stride, 420, 434, 84, 126)  # 右侧死区也有 → 整窗网格
    e, o = _parity(gr, 84)
    assert e < o
    gi = _row_means(buf, stride, 300, 380, 228, 240)  # 输入框里也有
    e, o = _parity(gi, 228)
    assert e < o
    assert e / o == pytest.approx(1 - crt.SCANLINE_ALPHA, abs=0.06)


def test_on_window_stripe_phase_survives_animation(win_on):
    """条纹钉在窗口上，不钉在内容上：脸动过之后，暗行还在同一批偶数行。"""
    w = win_on
    for dt in (0.0, 0.5):
        w.anim_t = 1.0 + dt
        buf, stride = _grab_rgb(w)
        g = _row_means(buf, stride, 3, 19, 84, 126)
        for i in range(0, len(g) - 1, 2):
            assert g[i] < g[i + 1], f"t=1.0+{dt}：y={84 + i} 该暗却没暗"


def test_on_window_vignette_darkens_corner_not_center(win_on, win_off):
    """暗角：角落被压暗，画面中部完全不碰（同一张图内对比 + 和关的比）。"""
    on_buf, s1 = _grab_rgb(win_on)
    off_buf, s2 = _grab_rgb(win_off)
    corner_on = _no_stripe(_row_means(on_buf, s1, 9, 21, 9, 21), 9)
    corner_off = _no_stripe(_row_means(off_buf, s2, 9, 21, 9, 21), 9)
    center_on = _no_stripe(_row_means(on_buf, s1, 200, 230, 250, 260), 250)
    center_off = _no_stripe(_row_means(off_buf, s2, 200, 230, 250, 260), 250)
    # 中部：暗角不波及；近处（输入框边框）的辉光最多渗 +2.5（实测 +1.6）
    assert -0.5 <= center_on - center_off <= 2.5
    assert corner_on < corner_off - 1.5  # 角落：被暗角明显压暗（实测 -3.3）
    assert corner_on < center_on * 0.85  # 同一张图里，角落比中底暗


def test_on_window_glow_bleeds_near_the_face_but_not_far(win_on, win_off):
    """辉光：亮脸边的外侧被点亮；远处的角落只有变暗一条路（到不了）。"""
    on_buf, s1 = _grab_rgb(win_on)
    off_buf, s2 = _grab_rgb(win_off)
    near_on = _no_stripe(_row_means(on_buf, s1, 292, 297, 66, 74), 66)
    near_off = _no_stripe(_row_means(off_buf, s2, 292, 297, 66, 74), 66)
    assert near_on >= near_off + 2.0  # 实测 +4.5：亮边外 2~9 像素被渗亮
    corner_on = _no_stripe(_row_means(on_buf, s1, 9, 21, 9, 21), 9)
    corner_off = _no_stripe(_row_means(off_buf, s2, 9, 21, 9, 21), 9)
    assert corner_on <= corner_off - 1.5  # 那里只有暗角（实测 -3.3），辉光到不了


def test_on_window_panel_outside_stays_transparent(win_on):
    """窗口是透明浮窗：面板以外必须还是全透明，暗角没漏出去。"""
    img = win_on.grab().toImage()
    w, h = img.width(), img.height()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        assert img.pixelColor(x, y).alpha() == 0, (x, y)


def test_on_window_overlay_layer_matches_window(win_on):
    """质感层的尺寸 = 窗口尺寸（换屏重建的判据）。"""
    ov = win_on._crt_overlay
    layer = ov.layer()
    assert layer is not None
    assert (layer.width(), layer.height()) == (win_on.width(), win_on.height())


# ── 内容不受装饰破坏 ────────────────────────────────


def _face_green(w):
    """脸区里的荧光绿像素（和 test_gaze 同一把尺）。"""
    img = w.grab().toImage().convertToFormat(QImage.Format_RGB32)
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    r = w.lay.face.adjusted(-12, -12, 12, 12)
    x0, x1 = int(r.x() * w.scale), int(r.right() * w.scale)
    y0, y1 = int(r.y() * w.scale), int(r.bottom() * w.scale)
    pts = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            i = y * stride + x * 4
            b, g, rr = buf[i], buf[i + 1], buf[i + 2]
            if g > 80 and g > 2 * rr and g > 2 * b:
                pts.append((x, y))
    return pts


def test_on_window_content_parity_with_crt_off(win_on, win_off):
    """装饰不改内容：脸的绿像素量与质心，开着和关着要在同一个量级。"""
    p_on = _face_green(win_on)
    p_off = _face_green(win_off)
    assert len(p_off) > 800, "关着都抓不到脸，区域选错了"
    assert 0.75 <= len(p_on) / len(p_off) <= 1.25
    cx_on = sum(x for x, _ in p_on) / len(p_on)
    cx_off = sum(x for x, _ in p_off) / len(p_off)
    assert abs(cx_on - cx_off) <= 2.0


def test_face_only_window_gets_crt_too(qapp, monkeypatch):
    """face-only 形态同一台机器：条纹也有、面板外也透明。"""
    monkeypatch.setenv("SAMMY_CRT", "on")
    w = _make_window(face_only=True)
    try:
        assert w.crt_on is True
        buf, stride = _grab_rgb(w)
        g = _row_means(buf, stride, 8, 34, 120, 180)
        for i in range(0, len(g) - 1, 2):
            assert g[i] < g[i + 1], f"y={120 + i} 该暗却没暗"
        img = w.grab().toImage()
        assert img.pixelColor(0, 0).alpha() == 0
        assert img.pixelColor(w.width() - 1, 0).alpha() == 0
    finally:
        w.close()
