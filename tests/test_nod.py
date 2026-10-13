"""困得点头（自选小步·第十次）——「困了的时候，一点一点地打盹」。

动机：犯困（energy 低于驱力的犯困线）原先只写在状态行和一张静态脸里 ——
一个真的活物快扛不住睡意时会**小鸡啄米**：脸慢慢沉下去、眼皮掉下来、撑住
一下，再猛地弹回来。和 Z（睡着）、哈欠（醒来）、叹气（无聊）同一条思路：
状态要能被眼睛读出来 —— 这条补上「困」。

两块机制：
- 形状：nod_amount 一条曲线（沉下去 → 撑住 → 猛弹回），纯函数逐点可钉；
- 节奏：note_sleepy 每隔 NOD_MIN_GAP~NOD_MAX_GAP 秒排一下（随机，别像节拍器）；
  刚犯困不马上点（那是抽搐不是打盹）、不困了就停、正在点的那下让它点完
  （半路掐掉像被抽了一下）。

四层判据（和 test_sigh 一个框架）：
1. 纯函数：曲线时间线逐点对账、节奏器行为、只加不改、reset 清态、确定性；
2. 窗口链路：犯困才排；睡着 / 刚交互 / 思考中 / 动画关各拦一次；
3. 渲染（真窗口离屏双胞胎）：顶沿下沉、脸矮掉近一半、宽度不动、收完逐字节归零；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：七个 NOD_* 常量在 anim.py 顶部，困的判定沿用驱力自己的
drives.sleepy；调参速查表第 20 节。）
"""

from __future__ import annotations

import math
import pathlib
import sys
import time
from itertools import pairwise

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import anim, drives
from sammy.anim import Animator

pytestmark = pytest.mark.usefixtures("qapp")  # 窗口层要 QApplication

T0 = 30.0  # 热身后的时刻（初始凝视 / 眨眼早已跑起来）


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet / test_sigh 同一套隔离）。"""
    from sammy import attention, care

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


def _walk(a: Animator, t0: float, t1: float, step: float = 0.05):
    """走时间轴，返回 [(t, frame)]，步长固定、确定性。"""
    n = round((t1 - t0) / step)
    out = []
    for i in range(n + 1):
        t = round(t0 + i * step, 6)
        out.append((t, a.frame_at(t)))
    return out


def _blink_squash(a: Animator, t: float) -> float:
    """按眨眼时间表复算这一刻的 squash（没有点头成分）—— 对账用。"""
    s = 1.0
    for start in a.blink_times(t):
        if start <= t <= start + anim.BLINK_DURATION:
            s = min(
                s,
                1.0
                - (1.0 - anim.BLINK_MIN_SQUASH) * anim._envelope((t - start) / anim.BLINK_DURATION),
            )
    return s


# ── 纯函数层：曲线与节奏 ──────────────────────────


def test_nod_constants_stay_subtle():
    """常量必须停在「犯困」量级：沉得慢、弹得快、节奏别密得像节拍器。"""
    total = anim.nod_total()
    assert 1.4 <= total <= 3.0, f"整段 {total}s —— 太短看不清过程，太长像慢动作"
    assert 0.8 <= anim.NOD_SAG_S <= 2.2
    assert 0.1 <= anim.NOD_HOLD_S <= 0.8
    assert 0.15 <= anim.NOD_SNAP_S <= 0.6
    assert anim.NOD_SNAP_S < anim.NOD_SAG_S / 3, "弹回来要比沉下去快得多：惊醒是瞬间的"
    assert 0.30 <= anim.NOD_SQUINT_MIN <= 0.65, "眼皮要掉下来（<0.65），又别合到眨眼的程度"
    assert 2 <= anim.NOD_SINK_PX <= 6, "下沉是像素级的小动作"
    assert 15.0 <= anim.NOD_MIN_GAP < anim.NOD_MAX_GAP <= 180.0, "节奏窗口不成立"
    assert anim.NOD_MIN_GAP >= anim.SIGH_MIN_GAP, "打盹是比叹气更稀有的重事件"


def test_nod_shape_sags_holds_and_snaps():
    """形状三段拼一条时间线：沉下去 → 撑住 → 猛弹回；两头精确为 0、两段单调。"""
    assert anim.nod_amount(-0.1) == 0.0, "还没开始就不该有"
    assert anim.nod_amount(0.0) == 0.0, "从静息起步"
    assert anim.nod_amount(anim.NOD_SAG_S / 2) == pytest.approx(0.5), "沉到一半正好一半"
    assert anim.nod_amount(anim.NOD_SAG_S) == pytest.approx(1.0)
    assert anim.nod_amount(anim.NOD_SAG_S + anim.NOD_HOLD_S / 2) == 1.0, "撑住段是满的"
    k = anim.NOD_SAG_S + anim.NOD_HOLD_S
    assert anim.nod_amount(k + anim.NOD_SNAP_S / 2) == pytest.approx(0.5)
    assert anim.nod_amount(anim.nod_total()) == 0.0, "弹完就该是零"
    assert anim.nod_amount(anim.nod_total() + 5.0) == 0.0
    down = [anim.nod_amount(anim.NOD_SAG_S * i / 20) for i in range(21)]
    assert all(b >= a for a, b in pairwise(down)), "沉下去段不单调"
    up = [anim.nod_amount(k + anim.NOD_SNAP_S * i / 20) for i in range(21)]
    assert all(b <= a for a, b in pairwise(up)), "弹回来段不单调"


def test_note_sleepy_first_nod_waits_a_gap():
    """刚犯困：先等一个（随机）间隔再点第一下 —— 立刻点那是抽搐，不是打盹。"""
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.note_sleepy(T0, True)
    assert a._nod_at == -99.0, "刚犯困就点头，那叫抽搐"
    assert a._nod_next_at is not None
    first = a._nod_next_at
    assert T0 + anim.NOD_MIN_GAP <= first <= T0 + anim.NOD_MAX_GAP
    a.note_sleepy(first - 0.5, True)
    assert a._nod_at == -99.0, "还没到点就点了"
    a.note_sleepy(first, True)
    assert a._nod_at == first, "到点了没点"
    nxt = a._nod_next_at
    assert nxt is not None and first + anim.NOD_MIN_GAP <= nxt <= first + anim.NOD_MAX_GAP, (
        "点完没接着排下一下"
    )


def test_note_sleepy_gap_is_randomized_not_a_metronome():
    """一直困：间隔全落在窗口里，而且不止一个值 —— 别像节拍器。"""
    a = Animator(seed=9)
    a.note_sleepy(0.0, True)
    times = []
    for _ in range(60):
        t = a._nod_next_at
        a.note_sleepy(t, True)
        times.append(t)
    assert a._nod_at == times[-1]
    gaps = [b - p for p, b in pairwise(times)]
    assert all(anim.NOD_MIN_GAP <= g <= anim.NOD_MAX_GAP for g in gaps), gaps
    assert len(set(gaps)) >= 3, "间隔全一个样 —— 成节拍器了"


def test_note_sleepy_off_clears_pending_schedule():
    """不困了：排期清掉；之后不再点新的。"""
    c = Animator(seed=13)
    c.note_sleepy(T0, True)
    assert c._nod_next_at is not None
    c.note_sleepy(T0 + 1.0, False)
    assert c._nod_next_at is None, "不困了排期还留着"
    for i in range(120):
        c.note_sleepy(T0 + 2.0 + i, False)
    assert c._nod_at == -99.0, "说不困了又点了一下"


def test_one_in_flight_nod_finishes_after_sleepiness_stops():
    """正在点的那下让它点完：'不困'只清排期，不掐当前 —— 半路掐掉像被抽了一下。"""
    a, b = Animator(seed=11), Animator(seed=11)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.nod(T0)
    a.note_sleepy(T0 + 0.4, False)  # 中途不困了
    for tau in (0.4, 0.9, 1.4):
        t = round(T0 + tau, 6)
        assert a.frame_at(t) != b.frame_at(t), f"{t}：排着的那下被'不困'掐掉了？"
    end = round(T0 + anim.nod_total() + 0.3, 6)
    assert a.frame_at(end) == b.frame_at(end), "收完没回到常态"


def test_nod_only_adds_other_channels_do_not_move():
    """只打了点头的一方与完全没打的孪生：别的通道一个都不许动；窗外全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.nod(T0)
    live = 0
    for i in range(1, 121):
        t = round(T0 + i * 0.025, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (fa.dx, fa.pop, fa.gx, fa.gy, fa.stretch, fa.talk_y, fa.talk_sq) == (
            fb.dx,
            fb.pop,
            fb.gx,
            fb.gy,
            fb.stretch,
            fb.talk_y,
            fb.talk_sq,
        ), f"{t} 时别的通道被点头带偏了"
        if t < T0 + anim.nod_total():
            if (fa.squash, fa.dy) != (fb.squash, fb.dy):
                live += 1
        else:
            assert (fa.squash, fa.dy) == (fb.squash, fb.dy), f"{t} 收完之后还没回到常态"
    assert live >= 40, f"窗口里只有 {live} 帧真的变了 —— 点头没点起来"


def test_nod_matches_formula_point_by_point():
    """整段逐点对账（0.02 秒网格）：两个通道按公式对齐到每个采样点。"""
    a = Animator(seed=11)
    _walk(a, 0.0, T0)
    a.nod(T0)
    live = 0
    for i in range(131):
        t = round(T0 + i * 0.02, 6)
        k = anim.nod_amount(t - T0)
        f = a.frame_at(t)
        assert f.squash == pytest.approx(
            min(_blink_squash(a, t), 1.0 - (1.0 - anim.NOD_SQUINT_MIN) * k)
        ), t
        assert f.dy == round(
            anim.BREATH_AMPLITUDE * math.sin(2 * math.pi * t / anim.BREATH_PERIOD)
        ) + round(anim.NOD_SINK_PX * k), t
        if k > 0:
            live += 1
    assert live >= 60, f"窗口里只有 {live} 帧在动"


def test_nod_and_sigh_together_compose_without_overreach():
    """点头碰上叹气（又困又闷）：压扁取更狠的那条、下沉相加 —— 组合也不出格。"""
    a, c = Animator(seed=25), Animator(seed=25)
    _walk(a, 0.0, T0)
    _walk(c, 0.0, T0)
    a.nod(T0)
    a.sigh(T0)
    c.sigh(T0)
    for i in range(1, 80):
        t = round(T0 + i * 0.02, 6)
        kn = anim.nod_amount(t - T0)
        ks = anim.sigh_amount(t - T0)
        f = a.frame_at(t)
        exp_sq = min(
            _blink_squash(a, t),
            1.0 - (1.0 - anim.NOD_SQUINT_MIN) * kn,
            1.0 - (1.0 - anim.SIGH_DEFLATE) * ks,
        )
        assert f.squash == pytest.approx(exp_sq), t
        assert f.dy == round(
            anim.BREATH_AMPLITUDE * math.sin(2 * math.pi * t / anim.BREATH_PERIOD)
        ) + round(anim.NOD_SINK_PX * kn) + round(anim.SIGH_SINK_PX * ks), t
        # 与「只叹气」的孪生比：压扁只会更狠（min）、不会更浅；下沉只会更多
        fc = c.frame_at(t)
        assert f.squash <= fc.squash + 1e-9, t
        assert f.dy >= fc.dy - 1e-9, t


def test_nod_is_suppressed_when_calm_and_resumes_after():
    """睡着不点头（定格优先）；醒来接着点（不是半路掐掉重来）。"""
    a, b = Animator(seed=15), Animator(seed=15)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.nod(T0)
    for i in range(1, 25):
        t = round(T0 + i * 0.05, 6)
        fa = a.frame_at(t, calm=True)
        fb = b.frame_at(t, calm=True)
        assert (fa.squash, fa.dy) == (fb.squash, fb.dy), f"{t} 睡着时点头漏出来了"
    mid = round(T0 + anim.NOD_SAG_S + anim.NOD_HOLD_S + anim.NOD_SNAP_S * 0.5, 6)
    assert a.frame_at(mid) != b.frame_at(mid), "醒了没接着点（被 calm 掐了）"


def test_nod_restart_starts_fresh():
    """中途再排一次：从沉下去重新起步 —— 与「只在这一刻开始」的孪生全等。"""
    a, d = Animator(seed=17), Animator(seed=17)
    _walk(a, 0.0, T0)
    _walk(d, 0.0, T0)
    a.nod(T0)
    assert a.frame_at(T0 + 0.3) != d.frame_at(T0 + 0.3), "前提不成立：a 没有在点"
    t2 = T0 + 0.5
    a.nod(t2)
    d.nod(t2)
    for tau in (0.0, 0.1, 0.35, 0.7, 1.0, 1.5, 2.2):
        t = round(t2 + tau, 6)
        assert a.frame_at(t) == d.frame_at(t), f"{t} 重开后没有从头起步"


def test_nod_reset_clears_state():
    """时间线被拨动（reset）：旧的那下不作数、排期也清掉。"""
    a, b = Animator(seed=19), Animator(seed=19)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.nod(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.1, 0.5, 1.0, 1.9):
        t = round(T0 + 0.2 + tau, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} reset 之后旧点头还在"
    c = Animator(seed=21)
    c.note_sleepy(T0, True)
    assert c._nod_next_at is not None
    c.nod(T0 + 1.0)
    c.reset(T0 + 2.0)
    assert c._nod_at == -99.0
    assert c._nod_next_at is None, "reset 后旧排期还留着"


def test_nod_is_deterministic():
    """同一条序列跑两遍逐值相等（种子相同 = 演出相同）。"""

    def run():
        a = Animator(seed=23)
        out = []
        for i in range(1, 161):
            t = round(i * 0.05, 6)
            if i == 40:
                a.nod(t)
            if i == 60:
                a.note_sleepy(t, True)
            f = a.frame_at(t)
            out.append((round(f.squash, 12), f.dy, round(f.stretch, 12), f.gx, f.gy))
        return out

    assert run() == run()


def test_geometry_guard_covers_the_nod_channel():
    """全局几何预算守卫（test_yawn）必须把点头通道算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "anim.NOD_SQUINT_MIN" in text and "anim.NOD_SINK_PX" in text, (
        "test_yawn 的全局预算守卫里没有点头通道 —— 调大 NOD_* 就没人拦了"
    )


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import SammyWindow  # noqa: E402

SEED_NOD = 7


def _mk(scale: float = 1.0) -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留点头这一个变量。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = scale
    w._offset = (0, 0)
    w.resize(round(800 * scale), round(480 * scale))
    w._relayout()
    # 眨眼与点头共用同一条 squash 通道（min 取更狠的）：量的那一刻撞上眨眼，
    # 点头的压扁会被整个遮住（实测撞过一次连眨两下，squash 0.186 —— 数字全废）。
    # 量几何时先把眨眼请出去；眨眼自己有 test_anim 管。
    w.anim = anim.Animator(seed=SEED_NOD, blink_gap=(600.0, 600.0))
    w.look_on = False  # 光标不参与（盯的是点头这一件事）
    w.set_expression(27)  # 犯困脸：和点头同台的那张
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    return w


def _img_bytes(w: SammyWindow) -> bytes:
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(img.constBits())


def _lit_bbox(w: SammyWindow, clip: QRect) -> tuple[int, int, int, int]:
    """clip 里的「不透明亮像素」外接框。

    两个条件缺一不可：颜色接近 faces.LIT（从常量读）且 **不透明**（alpha ≥ 200）——
    面板描边是半透明白，只看颜色会把它当成脸（test_yawn 踩过同一个坑）。
    """
    from sammy import faces

    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    x0 = y0 = 10**9
    x1 = y1 = -1
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
            if a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70:
                x0 = min(x0, x)
                x1 = max(x1, x)
                y0 = min(y0, y)
                y1 = max(y1, y)
    assert x1 >= 0, "clip 里一个亮像素都没有 —— 区域搞错了？"
    return x0, y0, x1, y1


def test_nod_sinks_the_face_and_snaps_back(qapp):
    """scale 1.0 双胞胎：顶沿下沉、脸矮掉近一半、宽度不动、收完逐字节归零。"""
    a, b = _mk(), _mk()
    try:
        a.anim.nod(8.5)
        box = a.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)

        def look(w: SammyWindow, t: float):
            w.anim_t = t
            return _lit_bbox(w, clip)

        full = round(8.5 + anim.NOD_SAG_S + anim.NOD_HOLD_S * 0.5, 6)  # 沉到底（撑住中段）
        x0a, y0a, x1a, y1a = look(a, full)
        x0b, y0b, x1b, y1b = look(b, full)
        drop = y0a - y0b
        assert drop >= 15, f"顶沿没沉下去：{drop}px"
        assert y1a <= y1b - 8, f"下沿该被压上来（脸矮掉）：{y1a} vs {y1b}"
        h_a, h_b = y1a - y0a, y1b - y0b
        assert h_a <= h_b * 0.65, f"脸没矮掉一半的读数：{h_a} vs {h_b}"
        assert abs((x1a - x0a) - (x1b - x0b)) <= 2, "点头不该动宽度"
        half = round(8.5 + anim.NOD_SAG_S * 0.5, 6)
        _, y0h, _, _ = look(a, half)
        _, y0bh, _, _ = look(b, half)
        assert 2 <= (y0h - y0bh) <= drop, "沉下去不是渐进的"
        after = round(8.5 + anim.nod_total() + 0.4, 6)
        a.anim_t = after
        b.anim_t = after
        assert _img_bytes(a) == _img_bytes(b), "点头收完还不回到常态"
    finally:
        a.close()
        b.close()


def test_nod_key_moment_stays_inside_the_repainted_region(qapp):
    """沉到底那一帧必须落在局部重绘区里 —— 在外面那圈不刷新（脸会花）。"""
    w = _mk()
    try:
        w.anim.nod(8.5)
        box = w.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)
        region = w._face_region()
        w.anim_t = round(8.5 + anim.NOD_SAG_S + anim.NOD_HOLD_S * 0.5, 6)
        x0, y0, x1, y1 = _lit_bbox(w, clip)
        deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        assert region.contains(deformed), f"沉到底时脸 {deformed} 冒出重绘区 {region}"
    finally:
        w.close()


# ── 链路：窗口把「困」喂给动画层 ────────────────────


def test_window_schedules_and_fires_nods_when_sleepy(qapp):
    """犯困 + 没在忙：先排、到点、点完接着排 —— 一路都在窗口这一层。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0  # 冻结驱力漂移（边界用例的老规矩）
        w.drives.energy = 0.25
        w.anim_t = 50.0
        w._tick()
        first = w.anim._nod_next_at
        assert first is not None, "困了却没排点头"
        assert 50.0 + anim.NOD_MIN_GAP <= first <= 50.0 + anim.NOD_MAX_GAP
        assert w.anim._nod_at == -99.0, "排期不该当场就点"
        w.anim_t = round(first - 0.2, 6)
        w._tick()
        assert w.anim._nod_at == -99.0, "还没到点就点了"
        w.anim_t = first
        w._tick()
        assert w.anim._nod_at == first, "到点了没点"
        nxt = w.anim._nod_next_at
        assert nxt is not None and nxt >= first + anim.NOD_MIN_GAP, "点完没接着排"
        w.anim_t = nxt
        w._tick()
        assert w.anim._nod_at == nxt, "第二下没来"
    finally:
        w.close()


def test_window_gates_sleepiness_and_recent_interaction(qapp):
    """两道闸门：不够困不排；刚交互完的 5 秒不排（别让人看见它栽头）。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.drives.energy = 0.30  # 犯困线正好上（严格小于才算困）
        w.anim_t = 30.0
        w._tick()
        assert w.anim._nod_next_at is None, "在犯困线上不该排"
        w.drives.energy = 0.29  # 过线
        w.anim_t = 31.0
        w._tick()
        assert w.anim._nod_next_at is not None, "过了犯困线没排"
        w.drives.energy = 0.9  # 不困了：排期清掉
        w.anim_t = 32.0
        w._tick()
        assert w.anim._nod_next_at is None, "不困了排期还留着"
        w.drives.energy = 0.25
        w._last_interaction_at = time.time()
        w.anim_t = 33.0
        w._tick()
        assert w.anim._nod_next_at is None, "刚聊完就打盹？"
        w._last_interaction_at = time.time() - 6.0
        w.anim_t = 34.0
        w._tick()
        assert w.anim._nod_next_at is not None, "5 秒过了还不排"
    finally:
        w.close()


def test_window_is_silent_when_asleep_anim_off_or_thinking(qapp):
    """睡着 / 动画关 / 思考中：三个都别排 —— 关就该关彻底。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.drives.energy = 0.25
        w.drives.asleep = True
        w.anim_t = 40.0
        w._tick()
        assert w.anim._nod_next_at is None, "睡着还排点头"
        w.drives.asleep = False
        w.anim_on = False
        w.anim_t = 41.0
        w._tick()
        assert w.anim._nod_next_at is None, "动画关着还排点头"
        w.anim_on = True
        w.thinking = True
        w.anim_t = 42.0
        w._tick()
        assert w.anim._nod_next_at is None, "思考中还排点头"
        w.thinking = False
        w.anim_t = 43.0
        w._tick()
        assert w.anim._nod_next_at is not None, "都恢复了还不排"
    finally:
        w.close()


# ── 纪律与素材 ────────────────────────────────────


def test_nod_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "nod_preview.py").is_file()
    assert "nod-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("nod-strip.png", "nod-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
