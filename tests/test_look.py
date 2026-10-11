"""光标凝视「它在看着你」（自选小步·第三次）—— 先写判据，实现对着判据做。

为什么做它：桌面陪伴里最便宜也最有效的「活」信号，是**它看向你的鼠标**。
U2 的凝视系统每几秒随机看一个方向；这一步给这个系统加了第二个目标来源：
全局光标。你动鼠标，它转过来看你一眼；停住几秒，它又发自己的呆。

三层判据：
1. 纯函数（anim.cursor_target 与 Animator.note_cursor 两个入口）：钉映射方向、
   转向节奏、保持窗口、过期释放、睡着不追；
2. 回归：**没喂光标时行为一个字节都不许变**（改造前录的金色基线逐字段对账）；
3. 渲染（真窗口离屏抓图）：光标在左 / 右 / 上 / 下，脸上的质心真的往那边偏；
   把开关 SAMMY_LOOK 拨到 off 之后，它与「光标从没动过」的画面逐像素一致。
"""

from __future__ import annotations

import math
import pathlib
import sys
from itertools import pairwise

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import anim
from sammy.anim import Animator

pytestmark = pytest.mark.usefixtures("qapp")  # 窗口层要 QApplication

T0 = 30.0  # 热身后的时刻（初始随机凝视早已跑起来）


def _walk(a: Animator, t0: float, t1: float, step: float = 0.05):
    """走时间轴，返回 [(t, frame)]，步长固定、确定性。"""
    n = round((t1 - t0) / step)
    out = []
    for i in range(n + 1):
        t = round(t0 + i * step, 6)
        out.append((t, a.frame_at(t)))
    return out


GOLDEN_TIMES = [
    0.5,
    1.0,
    2.0,
    3.5,
    6.0,
    9.0,
    13.0,
    17.0,
    25.0,
    40.0,
]

# (t, gx, gy, stretch, dx, dy, squash, pop) for a never-fed cursor.
GOLDEN = {
    7: [
        (0.5, 0, 0, 1.0, 1, 1, 1.0, 1.0),
        (1.0, 0, 0, 1.0, 1, 2, 1.0, 1.0),
        (2.0, 10, -6, 1.07, 2, 1, 1.0, 1.0),
        (3.5, 10, -6, 1.07, 2, -2, 1.0, 1.0),
        (6.0, 7, -5, 1.0343, 0, 2, 1.0, 1.0),
        (9.0, 7, -5, 1.0343, -2, 0, 1.0, 1.0),
        (13.0, 3, -6, 1.0063, 2, -1, 1.0, 1.0),
        (17.0, 10, 3, 1.07, 0, -2, 1.0, 1.0),
        (25.0, -3, -6, 1.0063, 2, -1, 1.0, 1.0),
        (40.0, 3, 6, 1.0063, 0, -1, 1.0, 1.0),
    ],
    21: [
        (0.5, 0, 0, 1.0, 1, 1, 1.0, 1.0),
        (1.0, 0, 0, 1.0, 1, 2, 1.0, 1.0),
        (2.0, 0, 0, 1.0, 2, 1, 1.0, 1.0),
        (3.5, 10, -2, 1.07, 2, -2, 1.0, 1.0),
        (6.0, 10, -2, 1.07, 0, 2, 1.0, 1.0),
        (9.0, -4, 6, 1.0112, -2, 0, 1.0, 1.0),
        (13.0, 6, -3, 1.0252, 2, -1, 1.0, 1.0),
        (17.0, -3, -3, 1.0063, 0, -2, 1.0, 1.0),
        (25.0, 1, 5, 1.0007, 2, -1, 1.0, 1.0),
        (40.0, -9, 1, 1.0567, 0, -1, 1.0, 1.0),
    ],
}

GOLDEN_GAZES_7 = [
    1.226,
    4.174,
    9.21,
    12.245,
    15.917,
    20.421,
    25.033,
    30.373,
    36.239,
]


# ── 纯函数层：映射 ──────────────────────────────────


def test_cursor_target_maps_direction_into_the_gaze_box():
    """光标方向按比例压进凝视盒：远了贴边，方向不扭曲。"""
    assert anim.cursor_target(500.0, 0.0) == (anim.GAZE_MAX_X, 0)
    assert anim.cursor_target(-500.0, 0.0) == (-anim.GAZE_MAX_X, 0)
    assert anim.cursor_target(0.0, 400.0) == (0, anim.GAZE_MAX_Y)
    assert anim.cursor_target(0.0, -400.0) == (0, -anim.GAZE_MAX_Y)
    assert anim.cursor_target(500.0, 250.0) == (10, 5)
    assert anim.cursor_target(0.0, 0.0) == (0, 0)


def test_cursor_target_keeps_direction_and_never_amplifies():
    # 光标很近：如实映射（方向真的近），不许放大成满幅
    assert anim.cursor_target(3.0, 1.0) == (3, 1)
    cases = [(120.0, 90.0), (-120.0, 90.0), (60.0, -30.0), (-400.0, -400.0), (300.0, 30.0)]
    for dx, dy in cases:
        x, y = anim.cursor_target(dx, dy)
        assert abs(x) <= anim.GAZE_MAX_X and abs(y) <= anim.GAZE_MAX_Y
        assert (x, y) != (0, 0), (dx, dy)
        got = math.atan2(y, x)
        want = math.atan2(dy, dx)
        assert abs(got - want) < 0.12, f"方向被扭曲：{(dx, dy)} → {(x, y)}"


# ── 纯函数层：转向、保持、释放 ──────────────────────


def test_cursor_moves_start_a_look_and_it_holds():
    """向右移动 → 缓动到右边缘并看住；缓动是滑过去的，不是瞬移。"""
    a = Animator(seed=41)
    _walk(a, 0.0, T0)
    a.note_cursor(-300.0, 0.0, T0)  # 第一笔：建立参照（不算动）
    a.note_cursor(300.0, 0.0, T0 + 0.1)  # 明确向右移动
    seq = _walk(a, T0 + 0.1, T0 + 2.4)
    by_t = dict(seq)
    assert (by_t[T0 + 0.9].gx, by_t[T0 + 0.9].gy) == (anim.GAZE_MAX_X, 0)
    for tt in (T0 + 1.4, T0 + 2.4):
        assert (by_t[tt].gx, by_t[tt].gy) == (anim.GAZE_MAX_X, 0), f"{tt} 时刻没看住"
    glide = [f.gx for t, f in seq if T0 + 0.15 <= t <= T0 + 0.7]
    assert all(x <= y for x, y in pairwise(glide)), f"转视不是单调滑过去的：{glide}"


def test_cursor_stop_releases_back_to_drift():
    """光标停下：先看住一拍，然后回到自己的随机漂移（不盯着空处看到天荒地老）。"""
    a = Animator(seed=42)
    _walk(a, 0.0, T0)
    a.note_cursor(-300.0, 0.0, T0)
    a.note_cursor(300.0, 0.0, T0 + 0.1)
    seq = _walk(a, T0 + 0.1, T0 + 12.0)
    hold = [(t, f) for t, f in seq if T0 + 0.8 <= t <= T0 + 2.5]
    assert hold and all((f.gx, f.gy) == (anim.GAZE_MAX_X, 0) for _, f in hold), "看住的窗口里没钉住"
    after = [t for t, f in seq if t > T0 + 2.5 and (f.gx, f.gy) != (anim.GAZE_MAX_X, 0)]
    assert after, "12 秒里一直盯着一个不动的光标，没放开"
    first = min(after)
    assert T0 + 2.6 <= first <= T0 + 8.4, f"放开得太快/太慢：{first - T0:.2f} 秒"


def test_cursor_moving_again_during_hold_re_aims():
    """保持窗口里光标又动了：立刻改看新方向。"""
    a = Animator(seed=43)
    _walk(a, 0.0, T0)
    a.note_cursor(-300.0, 0.0, T0)
    a.note_cursor(300.0, 0.0, T0 + 0.1)
    _walk(a, T0 + 0.1, T0 + 1.0)  # 看向右边
    a.note_cursor(-300.0, 0.0, T0 + 1.1)  # 向左甩
    seq = _walk(a, T0 + 1.1, T0 + 2.2)
    last = seq[-1][1]
    assert (last.gx, last.gy) == (-anim.GAZE_MAX_X, 0), "光标换了方向，脸没跟"


def test_tiny_jitter_never_counts_as_movement():
    """光标微抖（幅度小于阈值）不算「在动」：与没喂光标完全同帧。"""
    a = Animator(seed=43)
    b = Animator(seed=43)
    i = 0
    t = 0.0
    while t < 40.0:
        i += 1
        t = round(i * 0.05, 6)
        a.note_cursor((2.0, 0.0)[i % 2], 0.0, t)
        fa = a.frame_at(t)
        fb = b.frame_at(t)
        assert (fa.gx, fa.gy, fa.dx, fa.dy, fa.stretch, fa.squash) == (
            fb.gx,
            fb.gy,
            fb.dx,
            fb.dy,
            fb.stretch,
            fb.squash,
        ), f"t={t} 时微抖被当成了移动"
    assert a._look_dirty is False


def test_face_never_teleports_while_chasing_the_cursor():
    """光标每 0.3 秒甩到另一头：面每帧位移仍不超 3 像素（不许瞬移）。"""
    a = Animator(seed=44)
    prev = a.frame_at(0.0)
    worst = 0
    side = 1.0
    i = 0
    t = 0.0
    while t < T0 + 10.0:
        i += 1
        t = round(i * anim.ANIM_DT, 6)
        if i % 9 == 0:
            side = -side
            a.note_cursor(600.0 * side, -120.0 * side, t)
        f = a.frame_at(t)
        worst = max(worst, abs(f.gx - prev.gx), abs(f.gy - prev.gy))
        prev = f
    assert worst <= 3, f"追光标时单帧跳了 {worst} 像素"


def test_look_is_deterministic_with_seed_and_timeline():
    def run():
        a = Animator(seed=45)
        out = []
        i = 0
        t = 0.0
        while t < T0:
            i += 1
            t = round(i * anim.ANIM_DT, 6)
            if i % 30 == 0:
                a.note_cursor(80.0 * (i % 3 - 1), 40.0 * (i % 2), t)
            f = a.frame_at(t)
            out.append((f.gx, f.gy, f.dx, f.dy))
        return out

    assert run() == run()


def test_look_waits_while_asleep_and_wakes_with_continuity():
    """睡着不追光标（定格），醒来第一眼接上定格处、看向刚动过的光标。"""
    a = Animator(seed=46)
    _walk(a, 0.0, T0)
    a.note_cursor(-300.0, 0.0, T0)
    a.note_cursor(300.0, 0.0, T0 + 0.1)
    first = a.frame_at(T0 + 0.2, calm=True)
    frozen = (first.gx, first.gy)
    t = T0 + 0.2
    while t < T0 + 10.0:
        t = round(t + 0.05, 6)
        a.note_cursor(300.0 + (t - T0) * 200.0, 0.0, t)  # 睡着时光标一直在动
        f = a.frame_at(t, calm=True)
        assert (f.gx, f.gy) == frozen, "睡着还追光标"
    assert a._look_dirty is True  # 想看，但被「睡着」压着
    a.note_cursor(500.0, 0.0, T0 + 10.1)  # 醒来前光标刚动过
    w1 = a.frame_at(T0 + 10.2, calm=False)
    assert abs(w1.gx - frozen[0]) <= 3 and abs(w1.gy - frozen[1]) <= 3, "醒来跳了"
    _walk(a, T0 + 10.25, T0 + 11.5)
    assert a.frame_at(T0 + 11.6).gx == anim.GAZE_MAX_X, "醒来后没看向动过的光标"


def test_first_note_and_reset_do_not_trigger_a_look():
    a = Animator(seed=48)
    a.note_cursor(2000.0, 2000.0, 1.0)  # 第一笔：参照，不算动
    assert a._look_dirty is False
    a.note_cursor(0.0, 0.0, 2.0)  # 第二笔：动了
    assert a._look_dirty is True
    a.reset(t=3.0)
    assert a._look_dirty is False, "时间线重置后还留着旧方向"


def test_without_cursor_behaviour_is_exactly_unchanged():
    """没喂光标时与改造前的金色基线逐字段一致（回归红线）。"""
    for seed, rows in GOLDEN.items():
        a = Animator(seed=seed)
        got = []
        for t in GOLDEN_TIMES:
            f = a.frame_at(t)
            got.append(
                (
                    t,
                    f.gx,
                    f.gy,
                    round(f.stretch, 6),
                    f.dx,
                    f.dy,
                    round(f.squash, 6),
                    round(f.pop, 6),
                )
            )
        assert got == rows, f"种子 {seed} 的行为变了"
    a = Animator(seed=7)
    for t in GOLDEN_TIMES:
        a.frame_at(t)
    assert [round(x, 3) for x in a.gaze_times(40.0)] == GOLDEN_GAZES_7


# ── 渲染层：真窗口离屏抓图 ──────────────────────────
# （纯函数说"该看向哪"，这里说"屏幕上真的往哪偏"。）

from PySide6.QtCore import QPoint, QRect  # noqa: E402

GREEN_MIN = 80  # 荧光绿判据（和 test_gaze 同一套）
SEED_LOOK = 7


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


def _mk(seed: int = SEED_LOOK):
    """稳态窗口：种子 / 表情 / 时间轴全钉住，时间轴由测试自己拨。"""
    from sammy.pet import SammyWindow

    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.anim = anim.Animator(seed=seed)
    w.set_expression(9)  # 吐舌：没有动图，画面里动的只有凝视
    w.finish_typing()
    w.anim_t = 8.0
    w.look_on = True
    return w


class _FakeCursor:
    """可拖动的假光标：位置用"相对脸中心"的设备像素表示。"""

    def __init__(self, win):
        self.win = win
        self.dx = -200.0
        self.dy = 0.0

    def __call__(self):
        c = self.win.lay.face.center()
        s = self.win.scale
        lx = (c.x() + self.dx) * s + self.win._offset[0]
        ly = (c.y() + self.dy) * s + self.win._offset[1]
        return self.win.mapToGlobal(QPoint(round(lx), round(ly)))


def _step(w) -> None:
    """推进一帧：_anim_tick（含喂光标）之后，把这一帧算出来。

    离屏测试没有事件循环，paintEvent 不会自己跑 —— 这里替它把 frame_at 调上，
    否则"转向"只在最后 grab 时才醒一次，脸来不及跟过去。
    """
    w._anim_tick()
    w.anim.frame_at(w.anim_t)


def _sweep(w, cur, d0: float, d1: float, axis: str = "dx", ticks: int = 36, hold: int = 30):
    """光标先放好建立参照，再平滑移过去（36 帧 = 1.2 秒），最后停住 30 帧。"""
    setattr(cur, axis, d0)
    _step(w)
    for i in range(ticks):
        setattr(cur, axis, d0 + (d1 - d0) * (i + 1) / ticks)
        _step(w)
    for _ in range(hold):
        _step(w)


def _settle_clean(w, max_steps: int = 600):
    """走到一个"干净帧"（不眨眼、不弹跳）再抓图。

    抓在眨眼过程中（squash 0.22）量出来的像素数是眨眼前的一半 —— 判据会假红。
    """
    for _ in range(max_steps):
        f = w.anim.frame_at(w.anim_t)
        if f.squash == 1.0 and f.pop == 1.0:
            return f
        _step(w)
    raise AssertionError("等不到干净帧（600 步）")


def _face_region(w) -> QRect:
    r = w.lay.face.adjusted(-10, -10, 10, 2)
    s = w.scale
    return QRect(
        int(r.x() * s) + w._offset[0],
        int(r.y() * s) + w._offset[1],
        int(r.width() * s) + 2,
        int(r.height() * s) + 2,
    )


def _green_mask(w) -> set[tuple[int, int]]:
    """抓图 → 荧光绿像素集合（字节序 [B,G,R,A]，与 test_gaze 同一套）。"""
    from PySide6.QtGui import QImage

    img = w.grab().toImage().convertToFormat(QImage.Format_RGB32)
    buf = bytes(img.constBits())  # 立刻拷贝，别持有视图（faces.py 的教训）
    stride = img.bytesPerLine()
    clip = _face_region(w).intersected(QRect(0, 0, img.width(), img.height()))
    mask: set[tuple[int, int]] = set()
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            b, g, r = buf[i], buf[i + 1], buf[i + 2]
            if g > GREEN_MIN and g > 2 * r and g > 2 * b:
                mask.add((x, y))
    return mask


def _centroid(mask) -> tuple[float, float]:
    sx = sum(x for x, _ in mask)
    sy = sum(y for _, y in mask)
    return sx / len(mask), sy / len(mask)


def test_window_feeds_the_animator_in_device_space():
    """窗口把全局光标换算成"相对脸中心"的设备像素喂给动画层（数值对账）。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        cur.dx, cur.dy = 42.0, -7.0
        w._anim_tick()
        dx, dy = w.anim._cursor
        assert abs(dx - 42.0) <= 2.0 and abs(dy + 7.0) <= 2.0, f"换算偏了：{(dx, dy)}"
    finally:
        w.close()


def test_window_gaze_leans_toward_the_cursor():
    """光标在右 vs 在左：屏幕上脸的质心真的横向分开。"""
    w_r, w_l = _mk(), _mk()
    try:
        cur_r, cur_l = _FakeCursor(w_r), _FakeCursor(w_l)
        w_r._cursor_now = cur_r
        w_l._cursor_now = cur_l
        _sweep(w_r, cur_r, -200.0, 200.0)
        _sweep(w_l, cur_l, 200.0, -200.0)
        assert _settle_clean(w_r).gx == anim.GAZE_MAX_X
        assert _settle_clean(w_l).gx == -anim.GAZE_MAX_X
        mr, ml = _green_mask(w_r), _green_mask(w_l)
        assert len(mr) > 1500 and len(ml) > 1500, "抓到的绿像素太少，区域搞错了？"
        cx_r, _ = _centroid(mr)
        cx_l, _ = _centroid(ml)
        gap = cx_r - cx_l
        expect = (anim.GAZE_MAX_X * 2) * w_r.scale
        assert gap >= expect * 0.45, f"质心只分开 {gap:.1f}px（期望约 {expect:.1f}）"
    finally:
        w_r.close()
        w_l.close()


def test_window_face_tilts_toward_cursor_height():
    """光标在上 vs 在下：脸的质心纵向分开、横向不变。"""
    w_u, w_d = _mk(), _mk()
    try:
        cur_u, cur_d = _FakeCursor(w_u), _FakeCursor(w_d)
        w_u._cursor_now = cur_u
        w_d._cursor_now = cur_d
        cur_u.dx = cur_d.dx = 0.0
        _sweep(w_u, cur_u, 150.0, -150.0, axis="dy")
        _sweep(w_d, cur_d, -150.0, 150.0, axis="dy")
        assert _settle_clean(w_u).gy == -anim.GAZE_MAX_Y
        assert _settle_clean(w_d).gy == anim.GAZE_MAX_Y
        mu, md = _green_mask(w_u), _green_mask(w_d)
        assert len(mu) > 1500 and len(md) > 1500
        cx_u, cy_u = _centroid(mu)
        cx_d, cy_d = _centroid(md)
        gap = cy_d - cy_u
        expect = (anim.GAZE_MAX_Y * 2) * w_u.scale
        assert gap >= expect * 0.45, f"纵向质心只分开 {gap:.1f}px（期望约 {expect:.1f}）"
        assert abs(cx_u - cx_d) <= 3, "只许纵向偏，横向不该动"
    finally:
        w_u.close()
        w_d.close()


def test_look_off_and_static_cursor_render_the_identical_baseline():
    """开关 off / 光标没动：三种画法逐字节一致；开着且光标在动：必须不一样。"""

    def render(look_on: bool, moving: bool) -> bytes:
        w = _mk()
        try:
            w.look_on = look_on
            cur = _FakeCursor(w)
            w._cursor_now = cur
            if moving:
                _sweep(w, cur, -200.0, 200.0)
            else:
                for _ in range(67):
                    _step(w)
            _settle_clean(w)  # 三条同款变体走到的干净帧时刻一致
            img = w.grab().toImage()
            return bytes(img.constBits())
        finally:
            w.close()

    base = render(False, False)
    assert render(False, True) == base, "开关关着，光标移动也画出了差别？"
    assert render(True, False) == base, "光标没动，画面却被干扰了？"
    assert render(True, True) != base, "开着、光标在动，画面竟然没变"


def test_look_switch_off_stops_polling_entirely():
    w = _mk()
    try:
        w.look_on = False
        calls: list[int] = []
        w._cursor_now = lambda: (calls.append(1), w.mapToGlobal(QPoint(0, 0)))[1]
        for _ in range(5):
            _step(w)
        assert calls == [], "开关关掉了还在读光标"
    finally:
        w.close()


def test_look_switch_parsing():
    from sammy.pet import look_enabled

    assert look_enabled({}) is True
    assert look_enabled({"SAMMY_LOOK": "on"}) is True
    for raw in ("off", "0", "false", "no", "OFF"):
        assert look_enabled({"SAMMY_LOOK": raw}) is False, raw


# ── 纪律与素材 ─────────────────────────────────────


def test_look_media_and_script_are_shipped():
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "look_preview.py").is_file()
    assert "look-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("look-strip.png", "look-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
