"""关机序列（退场）的判据 —— 收束成一条线、一个点、熄灭。

为什么这些必须变成数字：

- 0.92 秒三段（压扁 0.4 / 收线 0.22 / 熄灭 0.3）眼睛量不出来；
  快了慢了、哪段跳了，只有纯函数能钉住；
- 起手第一帧必须**逐像素等于稳态**（收束起手要是跳一下就该露馅了）；
- 收尾必须落在全黑上（不然退出前闪一帧满屏），且退出**恰好一次**；
- 输入框与扫描线层不许在收束画面里杵在原地（它们是子控件，
  不跟着画面变换走）：退场一开始就得藏起来；
- 只有关闭钮 / 右键菜单这条路播关机（脚本、测试的 w.close() 都是啪一下，
  不播 —— 不然素材全是退场画面）；
- 素材要能一条命令重生成（和开机一套纪律）。
"""

from __future__ import annotations

import pathlib
import sys
from itertools import pairwise

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

pytestmark = pytest.mark.usefixtures("qapp")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sammy import boot  # noqa: E402

# ── 夹具 ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet / test_boot 同一套隔离）。"""
    from sammy import attention, care, drives, recall

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")
    monkeypatch.setattr(recall, "STATE_FILE", tmp_path / "recall.json")


def _env_on(monkeypatch):
    monkeypatch.setenv("SAMMY_BOOT", "on")
    monkeypatch.setenv("SAMMY_ANIM", "on")
    monkeypatch.setenv("SAMMY_CRT", "on")


def _steady(seed=7, face_only=False):
    """稳态窗口：固定种子 + 固定时刻 + 打字机拨到尾（U2/U3 同款做法）。"""
    from sammy import anim
    from sammy.pet import SammyWindow

    w = SammyWindow(face_only=face_only, autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.anim = anim.Animator(seed=seed)
    w.set_expression(3)
    w.anim_t = 1.0
    w.status = "在线 1.8s"
    w.sammy_line = "嗯…我醒着呢。"
    w.finish_typing()
    return w


def _shutting(monkeypatch, face_only=False):
    """已进入关机序列的窗口（开关显式打开，免得开发机 .env 影响判据）。"""
    _env_on(monkeypatch)
    w = _steady(face_only=face_only)
    assert w.begin_shutdown() is True
    return w


def _twin(monkeypatch, face_only=False):
    """按关机窗口的口径藏掉子控件（输入框 / 质感层）的稳态对照窗口。"""
    _env_on(monkeypatch)
    w = _steady(face_only=face_only)
    w.input.hide()
    if w._crt_overlay is not None:
        w._crt_overlay.hide()
    return w


def _img(w):
    img = w.grab().toImage()
    if img.format() != QImage.Format_ARGB32_Premultiplied:
        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    return img


def _bytes(img):
    return bytes(img.constBits()), img.bytesPerLine()


def _diff_count(a, b):
    """两张同尺寸图不一样的像素数。"""
    (ba, sa), (bb, sb) = _bytes(a), _bytes(b)
    n = 0
    for y in range(a.height()):
        ra = ba[y * sa : y * sa + a.width() * 4]
        rb = bb[y * sb : y * sb + b.width() * 4]
        for x in range(0, len(ra), 4):
            if ra[x : x + 4] != rb[x : x + 4]:
                n += 1
    return n


def _lit_stats(img, thr=120):
    """预乘口径下亮像素的个数与外接框（绿通道超阈值）。

    为什么必须用**原生预乘**字节：低透明度下直色仍是饱和值，
    未预乘口径会把已经暗到看不见的像素当成亮的（U4 的奇偶行、U6 的
    半亮比值都栽过这个坑）；预乘字节里亮度天然按透明度衰减。
    """
    buf, stride = _bytes(img)
    x0, y0, x1, y1 = 10**9, 10**9, -1, -1
    n = 0
    for y in range(img.height()):
        base = y * stride
        for x in range(img.width()):
            if buf[base + x * 4 + 1] > thr:
                n += 1
                x0 = min(x0, x)
                y0 = min(y0, y)
                x1 = max(x1, x)
                y1 = max(y1, y)
    if x1 < 0:
        return 0, None
    return n, (x0, y0, x1, y1)


def _extent_y(img, thr=120):
    _, bb = _lit_stats(img, thr)
    assert bb is not None, "画面全暗，找不到亮内容"
    return bb[3] - bb[1], (bb[1] + bb[3]) / 2.0, bb


def _extent_x(img, thr=120):
    _, bb = _lit_stats(img, thr)
    assert bb is not None, "画面全暗，找不到亮内容"
    return bb[2] - bb[0], bb


def _at(w, t):
    """把窗口拨到关机序列的第 t 秒并抓图。"""
    w.anim_t = w._shutdown_t0 + t
    return _img(w)


def _click(w, dx, dy):
    """在窗口里按一下（位置按设计坐标换算）—— 走真正的 mousePressEvent 事件。"""
    px, py = dx * w.scale, dy * w.scale
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(px, py),
        QPointF(px, py),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    w.mousePressEvent(ev)


def _recorder(w):
    calls = []
    w._quit_hook = lambda: calls.append(w.anim_t)
    return calls


# ── 纯函数层：时间轴 ────────────────────────────────


def test_total_is_the_sum_of_the_three_phases():
    assert boot.shutdown_total_seconds() == boot.COLLAPSE_DUR + boot.LINE_DUR + boot.DOT_DUR
    assert boot.shutdown_total_seconds() < 1.0, "退场别拖过一秒"
    assert boot.SQUEEZE_MIN < boot.SHRINK_MIN, "压扁要比收窄更狠"


def test_phases_are_exact():
    assert boot.shutdown_frame_at(0.0).phase == "collapse"
    assert boot.shutdown_frame_at(boot.COLLAPSE_DUR / 2).phase == "collapse"
    assert boot.shutdown_frame_at(boot.COLLAPSE_DUR).phase == "line"
    assert boot.shutdown_frame_at(boot.COLLAPSE_DUR + boot.LINE_DUR / 2).phase == "line"
    assert boot.shutdown_frame_at(boot.COLLAPSE_DUR + boot.LINE_DUR + 0.01).phase == "dot"
    end = boot.shutdown_total_seconds()
    assert boot.shutdown_frame_at(end + 0.01).phase == "done"
    assert boot.shutdown_frame_at(end + 5.0).phase == "done"


def test_start_frame_is_the_steady_frame():
    """起手：不许有任何缩放 / 亮线 / 变暗 —— 第一帧就是稳态本身。"""
    for t in (-1.0, 0.0):
        fr = boot.shutdown_frame_at(t)
        assert (fr.sx, fr.sy, fr.core, fr.alpha) == (1.0, 1.0, 0.0, 1.0), t


def test_squeeze_only_shrinks_and_never_goes_back():
    n = 400
    end = boot.shutdown_total_seconds()
    vals = [boot.shutdown_frame_at(end * i / n).sy for i in range(n + 1)]
    assert vals[0] == 1.0
    for a, b in pairwise(vals):
        assert b <= a + 1e-12, "压扁系数回升了"
    assert vals[-1] == boot.SQUEEZE_MIN


def test_squeeze_curve_shape_is_pinned():
    """平方衰减的形状：快起慢收 —— 三个点把曲线钉死。"""
    cd = boot.COLLAPSE_DUR
    for frac, want in ((0.25, 0.57125), (0.5, 0.265), (0.75, 0.08125)):
        got = boot.shutdown_frame_at(cd * frac).sy
        assert abs(got - want) < 0.005, (frac, got)


def test_line_only_shrinks_and_never_goes_back():
    assert boot.shutdown_frame_at(boot.COLLAPSE_DUR).sx == 1.0
    n = 400
    end = boot.shutdown_total_seconds()
    vals = [boot.shutdown_frame_at(end * i / n).sx for i in range(n + 1)]
    assert vals[0] == 1.0
    for a, b in pairwise(vals):
        assert b <= a + 1e-12, "收窄系数回升了"
    at_line_end = boot.shutdown_frame_at(boot.COLLAPSE_DUR + boot.LINE_DUR).sx
    assert abs(at_line_end - boot.SHRINK_MIN) < 1e-9, at_line_end
    assert vals[-1] == boot.DOT_SHRINK


def test_core_brightens_once_and_stays():
    assert boot.shutdown_frame_at(0.0).core == 0.0
    mid = boot.shutdown_frame_at(boot.COLLAPSE_DUR / 2).core
    assert abs(mid - 0.5) < 0.01, mid
    n = 200
    end = boot.shutdown_total_seconds()
    vals = [boot.shutdown_frame_at(end * i / n).core for i in range(n + 1)]
    for a, b in pairwise(vals):
        assert b >= a - 1e-12, "亮度回落了"
    assert boot.shutdown_frame_at(boot.COLLAPSE_DUR).core == 1.0
    assert vals[-1] == 1.0


def test_dot_fades_to_black():
    end = boot.shutdown_total_seconds()
    dark = boot.COLLAPSE_DUR + boot.LINE_DUR
    assert boot.shutdown_frame_at(dark).alpha == 1.0
    half = boot.shutdown_frame_at(dark + boot.DOT_DUR / 2).alpha
    assert abs(half - 0.5) < 0.01, half
    n = 200
    vals = [boot.shutdown_frame_at(dark + (end - dark) * i / n).alpha for i in range(n + 1)]
    for a, b in pairwise(vals):
        assert b <= a + 1e-12, "透明度回升了"
    assert boot.shutdown_frame_at(end - 0.001).alpha < 0.02
    assert boot.shutdown_frame_at(end + 0.001).alpha == 0.0


def test_switch_semantics_match_the_boot_switch():
    """关机序列和开机共用 SAMMY_BOOT 这一个电源开关。"""
    assert boot.boot_enabled({}) is True
    for raw in ("off", "0", "false", "no", "OFF", " off "):
        assert boot.boot_enabled({"SAMMY_BOOT": raw}) is False, raw


# ── 窗口层：开关、藏子控件、退出的时机 ────────────────


def test_default_quit_hook_is_the_plain_app_quit(monkeypatch):
    _env_on(monkeypatch)
    w = _steady()
    assert w._quit_hook == QApplication.quit
    w.close()


def test_begin_shutdown_respects_the_switches(monkeypatch):
    _env_on(monkeypatch)
    w = _steady()
    assert w.begin_shutdown() is True
    assert w._shutdown_t0 == w.anim_t
    w.close()

    monkeypatch.setenv("SAMMY_BOOT", "off")
    off = _steady()
    assert off.begin_shutdown() is False
    assert off._shutdown_t0 is None
    assert not off.input.isHidden(), "开关关着还动了输入框"
    off.close()

    monkeypatch.setenv("SAMMY_BOOT", "on")
    monkeypatch.setenv("SAMMY_ANIM", "off")
    noanim = _steady()
    assert noanim.begin_shutdown() is False
    assert noanim._shutdown_t0 is None
    noanim.close()


def test_begin_shutdown_hides_input_and_crt_layer(monkeypatch):
    w = _shutting(monkeypatch)
    assert w.input.isHidden(), "退场里输入框还杵着"
    assert w._crt_overlay is not None
    assert w._crt_overlay.isHidden(), "扫描线背着画面留在窗口上"
    w.close()


def test_begin_shutdown_is_idempotent(monkeypatch):
    """已经在关：再来一次就是接着关，不许重开一段（不然时间轴被拉长）。"""
    w = _shutting(monkeypatch)
    t0 = w._shutdown_t0
    w.anim_t += 0.1
    assert w.begin_shutdown() is True
    assert w._shutdown_t0 == t0
    w.close()


def test_begin_shutdown_during_boot_hands_off_cleanly(monkeypatch):
    _env_on(monkeypatch)
    w = _steady()
    assert w.begin_boot() is True
    w.anim_t += 0.5
    assert w.begin_shutdown() is True
    assert w._boot_t0 is None, "开机画面没交班出去"
    assert w._shutdown_t0 is not None
    assert w.input.isHidden()
    w.close()


def test_finish_by_the_clock_quits_exactly_once(monkeypatch):
    w = _shutting(monkeypatch)
    calls = _recorder(w)
    w.anim_t = w._shutdown_t0 + boot.shutdown_total_seconds() / 2
    w._anim_tick()
    assert calls == [], "没到点就退了"
    w.anim_t = w._shutdown_t0 + boot.shutdown_total_seconds() + 0.01
    w._anim_tick()
    assert len(calls) == 1, "到点没退，或退了好多次"
    assert w._shutdown_t0 is None
    w._anim_tick()
    assert len(calls) == 1, "退第二次了"
    w.close()


def test_click_anywhere_skips_and_quits_exactly_once(monkeypatch):
    w = _shutting(monkeypatch)
    calls = _recorder(w)
    w.anim_t = w._shutdown_t0 + 0.2
    _click(w, 400, 240)  # 面板正中间按一下
    assert len(calls) == 1, "点了没退"
    assert w._shutdown_t0 is None
    _click(w, 400, 240)
    assert len(calls) == 1, "退第二次了"
    w.close()


def test_close_button_starts_the_sequence_instead_of_quitting_at_once(monkeypatch):
    _env_on(monkeypatch)
    w = _steady()
    calls = _recorder(w)
    c = w.lay.close_c
    _click(w, c.x(), c.y())
    assert w._shutdown_t0 is not None, "关闭钮没起关机序列"
    assert calls == [], "关闭钮直接退了，动画没播"
    _click(w, c.x(), c.y())  # 关机中再点：跳过
    assert len(calls) == 1
    w.close()


def test_quit_with_the_switch_off_is_immediate(monkeypatch):
    monkeypatch.setenv("SAMMY_BOOT", "off")
    monkeypatch.setenv("SAMMY_ANIM", "on")
    monkeypatch.setenv("SAMMY_CRT", "on")
    w = _steady()
    calls = _recorder(w)
    c = w.lay.close_c
    _click(w, c.x(), c.y())
    assert len(calls) == 1, "开关关着就该直接退"
    assert w._shutdown_t0 is None
    w.close()


def test_click_away_from_the_close_button_never_quits(monkeypatch):
    _env_on(monkeypatch)
    w = _steady()
    calls = _recorder(w)
    _click(w, 300, 300)
    assert calls == [], "随便点一下就退，这日子没法过了"
    assert w._shutdown_t0 is None
    w.close()


def test_plain_close_does_not_play_the_sequence(monkeypatch):
    """脚本和测试的 w.close() 永远是直接关 —— 素材里不许混进退场画面。"""
    _env_on(monkeypatch)
    w = _steady()
    calls = _recorder(w)
    w.close()
    assert calls == []
    assert w._shutdown_t0 is None


# ── 窗口层：画面 ────────────────────────────────────


def test_start_frame_matches_the_steady_window_pixel_for_pixel(monkeypatch):
    """起手第一帧 = 稳态（藏掉子控件后逐像素对账）—— 收束是接上稳态，不是跳一下。"""
    w = _shutting(monkeypatch)
    twin = _twin(monkeypatch)
    img_w = _at(w, 0.0)
    twin.anim_t = w.anim_t
    assert _diff_count(img_w, _img(twin)) == 0
    w.close()
    twin.close()


def test_collapse_squashes_the_picture_but_keeps_it_wide(monkeypatch):
    w = _shutting(monkeypatch)
    twin = _twin(monkeypatch)
    twin.anim_t = w.anim_t
    steady_h, _, _ = _extent_y(_img(twin))

    h1, c1, _ = _extent_y(_at(w, 0.1))
    h2, c2, _ = _extent_y(_at(w, 0.2))
    h3, c3, _ = _extent_y(_at(w, 0.3))
    assert h1 > h2 > h3, (h1, h2, h3)
    assert h2 < 0.35 * steady_h, (h2, steady_h)
    assert h3 < 0.15 * steady_h, (h3, steady_h)

    center_px = w.lay.panel.center().y() * w.scale
    for c in (c1, c2, c3):
        assert abs(c - center_px) < 16, (c, center_px)

    span, _ = _extent_x(_at(w, 0.2))
    panel_w = w.lay.panel.width() * w.scale
    assert span > 0.9 * panel_w, (span, panel_w)
    w.close()
    twin.close()


def test_line_shrinks_to_a_point_in_one_row_band(monkeypatch):
    w = _shutting(monkeypatch)
    s1, _ = _extent_x(_at(w, 0.45))
    s2, _ = _extent_x(_at(w, 0.52))
    s3, _ = _extent_x(_at(w, 0.58))
    assert s1 > s2 > s3, (s1, s2, s3)
    assert s3 < 0.2 * s1, (s3, s1)

    center_px = w.lay.panel.center().y() * w.scale
    for t in (0.45, 0.52, 0.58, 0.62):
        _, bb = _lit_stats(_at(w, t))
        assert bb is not None
        assert bb[1] >= center_px - 8 and bb[3] <= center_px + 8, (t, bb, center_px)
    w.close()


def test_dot_fades_out_and_ends_fully_dark(monkeypatch):
    w = _shutting(monkeypatch)
    n70 = _lit_stats(_at(w, 0.70), thr=60)[0]
    n77 = _lit_stats(_at(w, 0.77), thr=60)[0]
    n85 = _lit_stats(_at(w, 0.85), thr=60)[0]
    assert n70 >= 20, n70
    assert n77 < n70
    assert n85 == 0, "光点该暗到看不见了"

    end = boot.shutdown_total_seconds()
    for t in (end + 0.01, end + 0.3, end + 1.0):
        n, bb = _lit_stats(_at(w, t), thr=30)
        assert (n, bb) == (0, None), (t, n, bb)
    w.close()


def test_faceonly_shutdown_also_works(monkeypatch):
    w = _shutting(monkeypatch, face_only=True)
    twin = _twin(monkeypatch, face_only=True)
    twin.anim_t = w.anim_t
    steady_h, _, _ = _extent_y(_img(twin))
    h2, _, _ = _extent_y(_at(w, 0.2))
    h3, _, _ = _extent_y(_at(w, 0.3))
    assert h2 < 0.35 * steady_h, (h2, steady_h)
    assert h3 < 0.15 * steady_h, (h3, steady_h)
    assert w.input.isHidden(), "face-only 的输入框该从头藏到尾"
    w.close()
    twin.close()


# ── 纪律与集成 ─────────────────────────────────────


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def test_only_the_quit_paths_and_the_preview_may_start_the_shutdown():
    """关机序列只许两处触发：窗口内部（关闭钮 / 菜单）+ 关机素材脚本。

    别的入口（快照、自检、各类素材脚本）一律不许调 —— 不然拍的素材
    会带着退场画面，或者在生成素材的时候把进程退了。
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    hits = {p.name for p in (root / "src").rglob("*.py") if ".begin_shutdown(" in _read(p)}
    assert hits == {"pet.py"}, hits
    scripts = {p.name for p in (root / "scripts").rglob("*.py") if ".begin_shutdown(" in _read(p)}
    assert scripts == {"shutdown_preview.py"}, scripts
    assert ".begin_shutdown(" in _read(root / "tests" / "test_shutdown.py")


def test_menu_and_close_button_route_through_request_quit():
    root = pathlib.Path(__file__).resolve().parent.parent
    src = _read(root / "src" / "sammy" / "pet.py")
    assert 'menu.addAction("退出 Sammy", self._request_quit)' in src
    assert '"退出 Sammy", QApplication.quit' not in src, "菜单还在直接退出"
    assert src.count("self._request_quit") >= 2, "关闭钮那个分支没走退出口"


def test_media_and_script_are_shipped():
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "shutdown_preview.py").is_file()
    assert "shutdown-media" in _read(root / "Makefile")
    for name in ("shutdown-strip.png", "shutdown-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), "缺素材 " + name
        assert p.stat().st_size > 10_000, "素材太小，像空壳 " + name
