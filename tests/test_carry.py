"""搬运凝视「被带去哪儿就看哪儿」（自选小步·第五次）—— 先写判据，实现对着判据做。

动机：U2 让脸学会「看」；第三个小步让它会「看你」—— 还剩一种视角没处理：
**它自己被搬动的时候**。「把窗口拖来拖去」在桌面上就是「被抱起来搬走」，
脸该看向被带去的方向（像被抱着的猫看着走的方向），而不是一路发呆。

做法沿用两条已经验证过的思路（代码一行没抄别人的）：
1. 转向走光标凝视那套「追加凝视指令」机制 —— 0.55 秒缓动 + 定格；
2. 目标映射仍用 cursor_target 的规则（方向不扭曲、压进凝视盒），
   前面加一个增益（CARRY_GAIN）：慢慢挪只有小小一瞥，一阵快搬直接贴边。

三层判据：
1. 纯函数（anim.carry_target 与 Animator.begin_carry / note_carry / end_carry）：
   映射数值钉死、攒够才转、限速两次转视、按住不搬等于没发生、
   睡着不计醒来接上、放手不泄气；
2. 回归：**没搬运时行为一个字节都不许变**（金色基线逐字段对账）；
3. 渲染（真窗口离屏抓图 + 真鼠标事件合成）：按住脸把窗口拖走，脸的质心
   真的朝行进方向偏；拖拽期间不再读光标（手是拿着它的手）；开关拨 off 后一步都不喂。
"""

from __future__ import annotations

import math
import pathlib
import sys

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


def _carry_frames(a: Animator, t0: float, dx: float, dy: float, ticks: int, dt: float = 0.033):
    """按帧喂搬运位移（每帧 dx, dy 设备像素，模拟鼠标在动），返回 [(t, frame)]。"""
    out = []
    t = t0
    for _ in range(ticks):
        t = round(t + dt, 6)
        a.note_carry(dx, dy)
        out.append((t, a.frame_at(t)))
    return out


# ── 纯函数层：映射 ──────────────────────────────────


def test_carry_target_maps_movement_into_the_gaze_box():
    """搬动位移按增益换算后压进凝视盒：远了贴边，方向不扭曲。"""
    assert anim.carry_target(1000.0, 0.0) == (anim.GAZE_MAX_X, 0)
    assert anim.carry_target(-1000.0, 0.0) == (-anim.GAZE_MAX_X, 0)
    assert anim.carry_target(0.0, -1000.0) == (0, -anim.GAZE_MAX_Y)
    assert anim.carry_target(0.0, 1000.0) == (0, anim.GAZE_MAX_Y)
    assert anim.carry_target(300.0, 150.0) == (10, 5)
    assert anim.carry_target(0.0, 0.0) == (0, 0)
    # 小位移如实映射（增益之后）：100 设备像素 → 8
    assert anim.carry_target(100.0, 0.0) == (8, 0)


def test_carry_target_shares_the_cursor_mapping_rules():
    """与光标共用同一条映射：carry_target 恒等于 cursor_target 乘增益。"""
    cases = [(0.0, 0.0), (12.0, 0.0), (37.5, -18.0), (-240.0, 480.0), (5000.0, -900.0)]
    for dx, dy in cases:
        want = anim.cursor_target(dx * anim.CARRY_GAIN, dy * anim.CARRY_GAIN)
        assert anim.carry_target(dx, dy) == want, (dx, dy)
    # 方向不扭曲（和光标同一口径）：任意方向、任意大小，角度偏差都很小
    for dx, dy in [(120.0, 90.0), (-66.0, 210.0), (60.0, -30.0), (-400.0, -400.0)]:
        x, y = anim.carry_target(dx, dy)
        assert (x, y) != (0, 0), (dx, dy)
        assert abs(x) <= anim.GAZE_MAX_X and abs(y) <= anim.GAZE_MAX_Y
        assert abs(math.atan2(y, x) - math.atan2(dy, dx)) < 0.12, (dx, dy)


# ── 纯函数层：转向、限速、边界 ──────────────────────


def test_fast_carry_looks_toward_the_direction():
    """快搬：脸朝行进方向看（右 → 右边缘、好奇拉高），且是滑过去不是跳过去。"""
    a = Animator(seed=51)
    _walk(a, 0.0, T0)
    a.begin_carry()
    seq = _carry_frames(a, T0, 20.0, 0.0, ticks=72)  # 每帧 20 设备像素 ≈ 600 每秒
    a.end_carry()
    tail = _walk(a, seq[-1][0], seq[-1][0] + 0.8)
    late = [f for t, f in tail if t >= seq[-1][0] + 0.5] + [f for _, f in seq[-6:]]
    assert late and all((f.gx, f.gy) == (anim.GAZE_MAX_X, 0) for f in late)
    assert round(seq[-1][1].stretch, 4) == 1.07
    # 不许瞬移：单帧位移不超过 3 像素（和光标追视同一口径）
    worst = 0
    prev = a.frame_at(T0)
    for _, f in seq:
        worst = max(worst, abs(f.gx - prev.gx), abs(f.gy - prev.gy))
        prev = f
    assert worst <= 3, f"搬运追视单帧跳了 {worst} 像素"


def test_slow_carry_is_only_a_glance():
    """慢挪：只给小小一瞥（明显小于贴边），不是满幅。"""
    a = Animator(seed=52)
    _walk(a, 0.0, T0)
    a.begin_carry()
    seq = _carry_frames(a, T0, 2.0, 0.0, ticks=45)  # 每帧 2 像素 ≈ 60 每秒，搬 1.5 秒
    a.end_carry()
    _walk(a, seq[-1][0], seq[-1][0] + 1.2)  # 停手，让最后一瞥缓完
    f = a.frame_at(seq[-1][0] + 1.3)
    assert (f.gx, f.gy) == (2, 0), f"慢挪的一瞥不对：({f.gx}, {f.gy})"
    assert abs(anim.GAZE_MAX_X - f.gx) > abs(f.gx - 0), "慢挪不该贴边"


def test_carry_retarget_is_rate_limited():
    """限速：两次转视之间至少 CARRY_RETARGET_MIN_S 秒 —— 立刻反向也压得住。"""
    a = Animator(seed=53)
    b = Animator(seed=53)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.begin_carry()
    b.begin_carry()
    a.note_carry(1000.0, 0.0)
    b.note_carry(1000.0, 0.0)
    t0 = round(T0 + 0.033, 6)
    a.frame_at(t0)
    b.frame_at(t0)  # 两端同时发生第一次转视（向右）
    a.note_carry(-1000.0, 0.0)  # a 立刻反向；b 不
    t = t0
    while t < t0 + 0.30:
        t = round(t + 0.033, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (fa.gx, fa.gy) == (fb.gx, fb.gy), f"{t} 时反向没被限速窗口压住"
    _walk(a, t, t0 + 1.1)
    _walk(b, t, t0 + 1.1)
    assert (a.frame_at(t0 + 1.2).gx, a.frame_at(t0 + 1.2).gy) == (-anim.GAZE_MAX_X, 0)
    assert (b.frame_at(t0 + 1.2).gx, b.frame_at(t0 + 1.2).gy) == (anim.GAZE_MAX_X, 0)


def test_grab_clears_pending_cursor_look_and_hold_still_changes_nothing():
    """抓起来的一瞬：待办的光标凝视作废；按住不搬 = 什么都没发生（与孪生同帧）。"""
    a = Animator(seed=54)
    b = Animator(seed=54)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.note_cursor(-300.0, 0.0, T0)
    a.note_cursor(300.0, 0.0, T0 + 0.1)
    assert a._look_dirty is True
    a.begin_carry()
    assert a._look_dirty is False
    for i in range(1, 61):
        t = round(T0 + 0.11 + i * 0.05, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert fa == fb, f"{t} 时「按住没搬」露了馅"


def test_below_threshold_nudges_do_not_look():
    """小抖动：攒不到 CARRY_MOVE_MIN 就不转视线（与孪生同帧），攒到了才看一眼。"""
    a = Animator(seed=57)
    b = Animator(seed=57)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.begin_carry()
    a.note_carry(10.0, 0.0)  # 只动 10 设备像素：不够
    for i in range(1, 21):
        t = round(T0 + i * 0.05, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} 时小挪被当成了搬动"
    a.note_carry(3.0, 0.0)  # 攒到 13：够了，该给一眼了
    _walk(a, T0 + 1.0, T0 + 2.2)
    assert (a.frame_at(T0 + 2.3).gx, a.frame_at(T0 + 2.3).gy) == (1, 0)


def test_sleeping_ignores_carry_and_wakes_toward_it():
    """睡着不追搬运（定格），醒来从定格处缓动到搬运方向（不跳）。"""
    a = Animator(seed=55)
    _walk(a, 0.0, T0)
    a.begin_carry()
    first = a.frame_at(T0 + 0.01, calm=True)
    frozen = (first.gx, first.gy)
    t = T0 + 0.01
    while t < T0 + 8.0:
        t = round(t + 0.05, 6)
        a.note_carry(20.0, 0.0)  # 睡着时被搬：一直往右挪
        f = a.frame_at(t, calm=True)
        assert (f.gx, f.gy) == frozen, "睡着还追搬运"
    w1 = a.frame_at(T0 + 8.05, calm=False)
    assert abs(w1.gx - frozen[0]) <= 3 and abs(w1.gy - frozen[1]) <= 3, "醒来跳了"
    _walk(a, T0 + 8.05, T0 + 9.6)
    assert (a.frame_at(T0 + 9.7).gx, a.frame_at(T0 + 9.7).gy) == (anim.GAZE_MAX_X, 0)


def test_release_clears_the_tail_so_it_does_not_deflate():
    """放手：最后一小段零头作废 —— 收尾不许从满幅往回泄一截（b 是对照）。"""
    a = Animator(seed=58)
    b = Animator(seed=58)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.begin_carry()
    b.begin_carry()
    seq_a = _carry_frames(a, T0, 20.0, 0.0, ticks=37)
    _carry_frames(b, T0, 20.0, 0.0, ticks=37)
    a.end_carry()
    t_end = seq_a[-1][0]
    _walk(a, t_end, t_end + 1.5)
    _walk(b, t_end, t_end + 1.5)
    fa = a.frame_at(t_end + 1.6)
    fb = b.frame_at(t_end + 1.6)
    assert (fa.gx, fa.gy) == (anim.GAZE_MAX_X, 0), "放手后泄气了"
    assert (fb.gx, fb.gy) == (5, 0), "对照端该看到回泄（说明 end_carry 是必要的）"


def test_without_carry_behaviour_is_exactly_unchanged():
    """没喂搬运时与改造前的金色基线逐字段一致（回归红线）。"""
    rows = {
        2.0: (10, -6, 1.07, 2, 1, 1.0, 1.0),
        6.0: (7, -5, 1.0343, 0, 2, 1.0, 1.0),
        17.0: (10, 3, 1.07, 0, -2, 1.0, 1.0),
        40.0: (3, 6, 1.0063, 0, -1, 1.0, 1.0),
    }
    a = Animator(seed=7)
    for t in (0.5, 1.0, 2.0, 3.5, 6.0, 9.0, 13.0, 17.0, 25.0, 40.0):
        f = a.frame_at(t)
        if t in rows:
            want = rows[t]
            got = (f.gx, f.gy, round(f.stretch, 4), f.dx, f.dy, round(f.squash, 4), round(f.pop, 4))
            assert got == want, f"{t} 时基线变了：{got}"
    assert [round(x, 3) for x in a.gaze_times(40.0)] == [
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


def test_carry_is_deterministic_with_seed_and_timeline():
    def run():
        a = Animator(seed=56)
        out = []
        i = 0
        t = 0.0
        while t < T0:
            i += 1
            t = round(i * 0.033, 6)
            if i % 40 == 0:
                a.note_carry(60.0 * (1 if (i // 40) % 2 else -1), 0.0)
            f = a.frame_at(t)
            out.append((f.gx, f.gy))
        return out

    assert run() == run()


# ── 渲染层：真窗口离屏抓图 + 真鼠标事件 ─────────────
# （纯函数说「该看向哪」，这里说「屏幕上真的往哪偏」、开关真的断在哪。）

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402

SEED_CARRY = 7


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


def _mk(seed: int = SEED_CARRY):
    """稳态窗口：种子 / 表情 / 时间轴全钉住，光标也钉住（别读真机器）。"""
    from sammy.pet import SammyWindow

    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.anim = anim.Animator(seed=seed)
    w.set_expression(9)  # 吐舌：没有动图，画面里动的只有凝视
    w.finish_typing()
    w.anim_t = 8.0
    w.look_on = True
    w._cursor_now = lambda: w.mapToGlobal(QPoint(0, 0))
    return w


def _step(w) -> None:
    """推进一帧：_anim_tick 之后把这一帧算出来（离屏没有事件循环）。"""
    w._anim_tick()
    w.anim.frame_at(w.anim_t)


def _press(w) -> QPointF:
    """在脸中心按住（走真 mousePressEvent）—— 返回抓点全局坐标。"""
    c = w.lay.face.center()
    s = w.scale
    local = QPointF(int(c.x() * s + w._offset[0]), int(c.y() * s + w._offset[1]))
    g = QPointF(w.mapToGlobal(local.toPoint()))
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress, local, g, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    w.mousePressEvent(ev)
    return g


def _move(w, g: QPointF) -> None:
    local = QPointF(w.mapFromGlobal(g.toPoint()))
    ev = QMouseEvent(QEvent.Type.MouseMove, local, g, Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    w.mouseMoveEvent(ev)


def _release(w, g: QPointF) -> None:
    local = QPointF(w.mapFromGlobal(g.toPoint()))
    ev = QMouseEvent(
        QEvent.Type.MouseButtonRelease, local, g, Qt.LeftButton, Qt.NoButton, Qt.NoModifier
    )
    w.mouseReleaseEvent(ev)


def _drag(w, dx: float, dy: float, ticks: int = 40) -> None:
    """按住脸中心、把窗口拖走（dx, dy 屏幕像素），每步推一帧。"""
    g = _press(w)
    for i in range(ticks):
        k = (i + 1) / ticks
        _move(w, QPointF(g.x() + dx * k, g.y() + dy * k))
        _step(w)
    _release(w, QPointF(g.x() + dx, g.y() + dy))


def _settle_clean(w, max_steps: int = 600):
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


def _lit_mask(w) -> set[tuple[int, int]]:
    """抓图 → 亮像素（前景色）集合。字节序实测为 [B,G,R,A]（RGB32）。

    ⚠️ 判据从 faces.LIT 读，**不许写死某个色相**：2026-10-12 前景由荧光绿改白，
    写死「绿色主导」的话换配色时会静默失效（集合直接变空，测试跟着乱报）。
    """

    from sammy import faces

    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
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
            if abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70:
                mask.add((x, y))
    return mask


def _centroid(mask) -> tuple[float, float]:
    sx = sum(x for x, _ in mask)
    sy = sum(y for _, y in mask)
    return sx / len(mask), sy / len(mask)


def test_window_feeds_carry_in_device_space():
    """窗口把搬动位移换算成设备像素喂给动画层（数值对账），窗口本身真挪了。"""
    w = _mk()
    try:
        calls = []
        w.anim.note_carry = lambda dx, dy: calls.append((dx, dy))
        x0, y0 = w.pos().x(), w.pos().y()
        g = _press(w)
        _move(w, QPointF(g.x() + 55.0, g.y() + 22.0))
        assert (w.pos().x() - x0, w.pos().y() - y0) == (55, 22), "窗口没真挪"
        assert len(calls) == 1
        dx, dy = calls[0]
        assert abs(dx - 55.0 / w.scale) <= 2.0 and abs(dy - 22.0 / w.scale) <= 2.0
    finally:
        w.close()


def test_dragging_shifts_the_face_toward_motion():
    """拖向右 vs 拖向左：屏幕上脸的质心真的横向分开（行进方向 = 视线方向）。"""
    w_r, w_l = _mk(), _mk()
    try:
        w_r.move(500, 300)
        w_l.move(500, 300)
        _drag(w_r, 260.0, 0.0)
        _drag(w_l, -260.0, 0.0)
        for _ in range(30):
            _step(w_r)
            _step(w_l)
        fr, fl = _settle_clean(w_r), _settle_clean(w_l)
        assert (fr.gx, fr.gy) == (anim.GAZE_MAX_X, 0), (fr.gx, fr.gy)
        assert (fl.gx, fl.gy) == (-anim.GAZE_MAX_X, 0), (fl.gx, fl.gy)
        mr, ml = _lit_mask(w_r), _lit_mask(w_l)
        assert len(mr) > 1500 and len(ml) > 1500, "抓到的绿像素太少，区域搞错了？"
        cx_r, _ = _centroid(mr)
        cx_l, _ = _centroid(ml)
        gap = cx_r - cx_l
        expect = (anim.GAZE_MAX_X * 2) * w_r.scale
        assert gap >= expect * 0.45, f"质心只分开 {gap:.1f}px（期望约 {expect:.1f}）"
    finally:
        w_r.close()
        w_l.close()


def test_pointer_look_is_suspended_while_dragging_and_resumes_after():
    """搬运期间不读光标（手是拿着它的手）；放开后恢复；没按左键的移动不喂。"""
    w = _mk()
    try:
        reads = []
        w._cursor_now = lambda: (reads.append(1), w.mapToGlobal(QPoint(0, 0)))[1]
        notes = []
        orig = w.anim.note_carry

        def spy(dx, dy):
            notes.append((dx, dy))
            return orig(dx, dy)

        w.anim.note_carry = spy
        g = _press(w)
        for i in range(1, 16):
            _move(w, QPointF(g.x() + i * 12.0, g.y()))
            _step(w)
        assert reads == [], "搬运期间不该读光标"
        assert len(notes) == 15, "拖拽期间每步都该喂搬运"
        _release(w, QPointF(g.x() + 180.0, g.y()))
        _step(w)
        assert reads, "放开之后应该恢复读光标"
        n_after = len(notes)
        _move(w, QPointF(g.x() + 260.0, g.y()))
        assert len(notes) == n_after, "没按左键的移动不该喂搬运"
    finally:
        w.close()


def test_holding_still_does_not_change_the_face():
    """按住不搬：脸的形变与「从没碰过它」的孪生完全同帧。"""
    w0 = _mk()
    w1 = _mk()
    try:
        _press(w1)
        for _ in range(40):
            _step(w0)
            _step(w1)
        assert w1.anim_t == w0.anim_t
        assert w1.anim.frame_at(w1.anim_t) == w0.anim.frame_at(w0.anim_t)
        _release(w1, QPointF(0, 0))
    finally:
        w0.close()
        w1.close()


def test_switch_off_ignores_carry():
    """两个开关任一关着：一步都不喂（窗口本身照样能拖）。"""
    for attr in ("look_on", "anim_on"):
        w = _mk()
        try:
            setattr(w, attr, False)
            calls = []
            w.anim.begin_carry = lambda calls=calls: calls.append("begin")
            w.anim.note_carry = lambda dx, dy, calls=calls: calls.append(("note", dx, dy))
            w.anim.end_carry = lambda calls=calls: calls.append("end")
            x0 = w.pos().x()
            g = _press(w)
            for i in range(1, 11):
                _move(w, QPointF(g.x() + i * 20.0, g.y()))
                _step(w)
            _release(w, QPointF(g.x() + 200.0, g.y()))
            assert calls == [], f"{attr} 关着还在喂搬运"
            assert w.pos().x() - x0 == 200, "开关只管脸，窗口照样能拖"
        finally:
            w.close()


# ── 纪律与素材 ─────────────────────────────────────


def test_carry_media_and_script_are_shipped():
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "carry_preview.py").is_file()
    assert "carry-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("carry-strip.png", "carry-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
