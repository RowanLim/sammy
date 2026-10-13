"""无聊的叹气（自选小步·第九次）——「没人理的时候，隔一会儿叹一口气」。

动机：无聊（boredom 驱力）原先只写在状态行和一张静态脸里 —— 一个真的活物
闲着发闷会把气叹出来。这一块把「无聊」变成**看得见的小动作**：脸缓缓沉下去
（往下 SIGH_SINK_PX）、瘪一点（压到 SIGH_DEFLATE）、屏住一下，再慢慢回起来。
和 Z（睡着）、哈欠（醒来）同一条思路：状态要能被眼睛读出来。

两块机制：
- 形状：sigh_amount 一条曲线（沉下去 → 屏住 → 慢慢回），纯函数逐点可钉；
- 节奏：note_bored 每隔 SIGH_MIN_GAP~SIGH_MAX_GAP 秒排一口（随机，别像
  节拍器）；刚进入无聊不马上叹（那是反射不是情绪）、不无聊了就停、
  正在叹的那口让它叹完（半路掐掉像噎住）。

四层判据（和 test_yawn 一个框架）：
1. 纯函数：曲线时间线逐点对账、节奏器行为、只加不改、reset 清态、确定性；
2. 窗口链路：无聊过线才排；睡着 / 刚交互 / 思考中 / 动画关各拦一次；
3. 渲染（真窗口离屏双胞胎）：顶沿下沉、脸变矮、宽度不动、收完逐字节归零；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：七个 SIGH_* 常量在 anim.py 顶部，门槛 SIGH_BOREDOM_ABOVE 在
pet.py；调参速查表第 19 节。）
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
    """别碰用户真实的状态文件（和 test_pet / test_yawn 同一套隔离）。"""
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
    """按眨眼时间表复算这一刻的 squash（没有叹气成分）—— 对账用。"""
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


def test_sigh_constants_stay_subtle():
    """常量必须停在「轻微」量级：比眨眼慢、比哈欠轻；节奏别密得像节拍器。"""
    total = anim.sigh_total()
    assert 1.2 <= total <= 3.0, f"整段 {total}s —— 太短看不见过程，太长像慢动作"
    assert 0.3 <= anim.SIGH_SINK_S <= 1.2
    assert 0.0 <= anim.SIGH_HOLD_S <= 0.8
    assert 0.5 <= anim.SIGH_RISE_S <= 1.8
    assert anim.SIGH_SINK_S < anim.SIGH_RISE_S, "回起来该比沉下去慢：撒气快、缓回来"
    assert 0.90 <= anim.SIGH_DEFLATE <= 0.99, "瘪要看得见（<0.99），又不能真扁下去（>=0.90）"
    assert 1 <= anim.SIGH_SINK_PX <= 5, "沉底是像素级的小动作"
    assert 10.0 <= anim.SIGH_MIN_GAP < anim.SIGH_MAX_GAP <= 120.0, "节奏窗口不成立"
    from sammy.pet import SIGH_BOREDOM_ABOVE

    assert 0.4 <= SIGH_BOREDOM_ABOVE <= 0.8, "门槛太低谁都在叹气，太高永远叹不着"


def test_sigh_shape_sinks_holds_and_recovers():
    """形状三段拼一条时间线：沉下去 → 屏住 → 慢慢回；两头精确为 0、两段单调。"""
    assert anim.sigh_amount(-0.1) == 0.0, "还没开始就不该有"
    assert anim.sigh_amount(0.0) == 0.0, "从静息起步"
    assert anim.sigh_amount(anim.SIGH_SINK_S / 2) == pytest.approx(0.5), "沉到一半正好一半"
    assert anim.sigh_amount(anim.SIGH_SINK_S) == pytest.approx(1.0)
    assert anim.sigh_amount(anim.SIGH_SINK_S + anim.SIGH_HOLD_S / 2) == 1.0, "屏住段是满的"
    k = anim.SIGH_SINK_S + anim.SIGH_HOLD_S
    assert anim.sigh_amount(k + anim.SIGH_RISE_S / 2) == pytest.approx(0.5)
    assert anim.sigh_amount(anim.sigh_total()) == 0.0, "回完就该是零"
    assert anim.sigh_amount(anim.sigh_total() + 5.0) == 0.0
    down = [anim.sigh_amount(anim.SIGH_SINK_S * i / 20) for i in range(21)]
    assert all(b >= a for a, b in pairwise(down)), "沉下去段不单调"
    up = [anim.sigh_amount(k + anim.SIGH_RISE_S * i / 20) for i in range(21)]
    assert all(b <= a for a, b in pairwise(up)), "回起来段不单调"


def test_note_bored_first_sigh_waits_a_gap():
    """刚进入无聊：先等一个（随机）间隔再叹头一口 —— 立刻叹是反射，不是情绪。"""
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.note_bored(T0, True)
    assert a._sigh_at == -99.0, "刚无聊就叹气，那叫反射"
    assert a._sigh_next_at is not None
    first = a._sigh_next_at
    assert T0 + anim.SIGH_MIN_GAP <= first <= T0 + anim.SIGH_MAX_GAP
    a.note_bored(first - 0.5, True)
    assert a._sigh_at == -99.0, "还没到点就叹了"
    a.note_bored(first, True)
    assert a._sigh_at == first, "到点了没叹"
    nxt = a._sigh_next_at
    assert nxt is not None and first + anim.SIGH_MIN_GAP <= nxt <= first + anim.SIGH_MAX_GAP, (
        "叹完没接着排下一口"
    )


def test_note_bored_gap_is_randomized_not_a_metronome():
    """一直无聊：间隔全落在窗口里，而且不止一个值 —— 别像节拍器。"""
    a = Animator(seed=9)
    a.note_bored(0.0, True)
    times = []
    for _ in range(60):
        t = a._sigh_next_at
        a.note_bored(t, True)
        times.append(t)
    assert a._sigh_at == times[-1]
    gaps = [b - p for p, b in pairwise(times)]
    assert all(anim.SIGH_MIN_GAP <= g <= anim.SIGH_MAX_GAP for g in gaps), gaps
    assert len(set(gaps)) >= 3, "间隔全一个样 —— 成节拍器了"


def test_note_bored_off_clears_pending_schedule():
    """不无聊了：排期清掉；之后不再叹新的。"""
    c = Animator(seed=13)
    c.note_bored(T0, True)
    assert c._sigh_next_at is not None
    c.note_bored(T0 + 1.0, False)
    assert c._sigh_next_at is None, "不无聊了排期还留着"
    for i in range(120):
        c.note_bored(T0 + 2.0 + i, False)
    assert c._sigh_at == -99.0, "说不无聊了又叹了一口"


def test_one_in_flight_sigh_finishes_after_boredom_stops():
    """正在叹的那口让它叹完：'不无聊'只清排期，不掐当前 —— 半路掐掉像噎住。"""
    a, b = Animator(seed=11), Animator(seed=11)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.sigh(T0)
    a.note_bored(T0 + 0.4, False)  # 中途不无聊了
    for tau in (0.4, 0.8, 1.2):
        t = round(T0 + tau, 6)
        assert a.frame_at(t) != b.frame_at(t), f"{t}：排着的那口被'不无聊'掐掉了？"
    end = round(T0 + anim.sigh_total() + 0.3, 6)
    assert a.frame_at(end) == b.frame_at(end), "收完没回到常态"


def test_sigh_only_adds_other_channels_do_not_move():
    """只打了叹气的一方与完全没打的孪生：别的通道一个都不许动；窗外全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.sigh(T0)
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
        ), f"{t} 时别的通道被叹气带偏了"
        if t < T0 + anim.sigh_total():
            if (fa.squash, fa.dy) != (fb.squash, fb.dy):
                live += 1
        else:
            assert (fa.squash, fa.dy) == (fb.squash, fb.dy), f"{t} 收完之后还没回到常态"
    assert live >= 40, f"窗口里只有 {live} 帧真的变了 —— 叹气没叹起来"


def test_sigh_matches_formula_point_by_point():
    """整段逐点对账（0.02 秒网格）：两个通道按公式对齐到每个采样点。"""
    a = Animator(seed=11)
    _walk(a, 0.0, T0)
    a.sigh(T0)
    live = 0
    for i in range(131):
        t = round(T0 + i * 0.02, 6)
        k = anim.sigh_amount(t - T0)
        f = a.frame_at(t)
        assert f.squash == pytest.approx(
            min(_blink_squash(a, t), 1.0 - (1.0 - anim.SIGH_DEFLATE) * k)
        ), t
        assert f.dy == round(
            anim.BREATH_AMPLITUDE * math.sin(2 * math.pi * t / anim.BREATH_PERIOD)
        ) + round(anim.SIGH_SINK_PX * k), t
        if k > 0:
            live += 1
    assert live >= 60, f"窗口里只有 {live} 帧在动"


def test_sigh_is_suppressed_when_calm_and_resumes_after():
    """睡着不叹气（定格优先）；醒来接着叹（不是半路掐掉重来）。"""
    a, b = Animator(seed=15), Animator(seed=15)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.sigh(T0)
    for i in range(1, 25):
        t = round(T0 + i * 0.05, 6)
        fa = a.frame_at(t, calm=True)
        fb = b.frame_at(t, calm=True)
        assert (fa.squash, fa.dy) == (fb.squash, fb.dy), f"{t} 睡着时叹气漏出来了"
    mid = round(T0 + anim.SIGH_SINK_S + anim.SIGH_HOLD_S + anim.SIGH_RISE_S * 0.5, 6)
    assert a.frame_at(mid) != b.frame_at(mid), "醒了没接着叹（被 calm 掐了）"


def test_sigh_restart_starts_fresh():
    """中途再排一次：从沉下去重新起步 —— 与「只在这一刻开始」的孪生全等。"""
    a, d = Animator(seed=17), Animator(seed=17)
    _walk(a, 0.0, T0)
    _walk(d, 0.0, T0)
    a.sigh(T0)
    assert a.frame_at(T0 + 0.3) != d.frame_at(T0 + 0.3), "前提不成立：a 没有在叹"
    t2 = T0 + 0.5
    a.sigh(t2)
    d.sigh(t2)
    for tau in (0.0, 0.1, 0.35, 0.7, 1.0, 1.5, 2.3):
        t = round(t2 + tau, 6)
        assert a.frame_at(t) == d.frame_at(t), f"{t} 重开后没有从头起步"


def test_sigh_reset_clears_state():
    """时间线被拨动（reset）：旧的那口不作数、排期也清掉。"""
    a, b = Animator(seed=19), Animator(seed=19)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.sigh(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.1, 0.5, 1.0, 1.9):
        t = round(T0 + 0.2 + tau, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} reset 之后旧叹气还在"
    c = Animator(seed=21)
    c.note_bored(T0, True)
    assert c._sigh_next_at is not None
    c.sigh(T0 + 1.0)
    c.reset(T0 + 2.0)
    assert c._sigh_at == -99.0
    assert c._sigh_next_at is None, "reset 后旧排期还留着"


def test_sigh_is_deterministic():
    """同一条序列跑两遍逐值相等（种子相同 = 演出相同）。"""

    def run():
        a = Animator(seed=23)
        out = []
        for i in range(1, 161):
            t = round(i * 0.05, 6)
            if i == 40:
                a.sigh(t)
            if i == 60:
                a.note_bored(t, True)
            f = a.frame_at(t)
            out.append((round(f.squash, 12), f.dy, round(f.stretch, 12), f.gx, f.gy))
        return out

    assert run() == run()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import SammyWindow  # noqa: E402

SEED_SIGH = 7


def _mk(scale: float = 1.0) -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留叹气这一个变量。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = scale
    w._offset = (0, 0)
    w.resize(round(800 * scale), round(480 * scale))
    w._relayout()
    w.anim = anim.Animator(seed=SEED_SIGH)
    w.look_on = False  # 光标不参与（盯的是叹气这一件事）
    w.set_expression(26)  # 无聊脸：和叹气同台的那张
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


def test_sigh_sinks_the_face_and_settles_back(qapp):
    """scale 1.0 双胞胎：顶沿下沉、脸变矮、宽度不动、收完逐字节归零。"""
    a, b = _mk(), _mk()
    try:
        a.anim.sigh(8.5)
        box = a.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)

        def look(w: SammyWindow, t: float):
            w.anim_t = t
            return _lit_bbox(w, clip)

        full = round(8.5 + anim.SIGH_SINK_S + anim.SIGH_HOLD_S * 0.5, 6)  # 沉到底（屏住中段）
        x0a, y0a, x1a, y1a = look(a, full)
        x0b, y0b, x1b, y1b = look(b, full)
        drop = y0a - y0b
        assert drop >= 3, f"顶沿没沉下去：{drop}px"
        assert 1 <= y1a - y1b <= 6, f"下沿位移不合理：{y1a - y1b}px"
        h_a, h_b = y1a - y0a, y1b - y0b
        assert h_b - h_a >= 1, f"脸没瘪：{h_a} vs {h_b}"
        assert abs((x1a - x0a) - (x1b - x0b)) <= 2, "叹气不该动宽度"
        half = round(8.5 + anim.SIGH_SINK_S * 0.5, 6)
        _, y0h, _, _ = look(a, half)
        _, y0bh, _, _ = look(b, half)
        assert 2 <= (y0h - y0bh) <= drop, "沉下去不是渐进的"
        after = round(8.5 + anim.sigh_total() + 0.4, 6)
        a.anim_t = after
        b.anim_t = after
        assert _img_bytes(a) == _img_bytes(b), "叹气收完还不回到常态"
    finally:
        a.close()
        b.close()


def test_sigh_key_moment_stays_inside_the_repainted_region(qapp):
    """沉到底那一帧必须落在局部重绘区里 —— 在外面那圈不刷新（脸会花）。"""
    w = _mk()
    try:
        w.anim.sigh(8.5)
        box = w.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)
        region = w._face_region()
        w.anim_t = round(8.5 + anim.SIGH_SINK_S + anim.SIGH_HOLD_S * 0.5, 6)
        x0, y0, x1, y1 = _lit_bbox(w, clip)
        deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        assert region.contains(deformed), f"沉到底时脸 {deformed} 冒出重绘区 {region}"
    finally:
        w.close()


# ── 链路：窗口把「无聊」喂给动画层 ─────────────────


def test_window_schedules_and_fires_sighs_when_bored(qapp):
    """无聊过线 + 没在忙：先排、到点叹、叹完接着排 —— 一路都在窗口这一层。"""
    w = _mk()
    try:
        w.drives.boredom = 0.9
        w.anim_t = 50.0
        w._tick()
        first = w.anim._sigh_next_at
        assert first is not None, "无聊了却没排叹气"
        assert 50.0 + anim.SIGH_MIN_GAP <= first <= 50.0 + anim.SIGH_MAX_GAP
        assert w.anim._sigh_at == -99.0, "排期不该当场就叹"
        w.anim_t = round(first - 0.2, 6)
        w._tick()
        assert w.anim._sigh_at == -99.0, "还没到点就叹了"
        w.anim_t = first
        w._tick()
        assert w.anim._sigh_at == first, "到点了没叹"
        nxt = w.anim._sigh_next_at
        assert nxt is not None and nxt >= first + anim.SIGH_MIN_GAP, "叹完没接着排"
        w.anim_t = nxt
        w._tick()
        assert w.anim._sigh_at == nxt, "第二口没来"
    finally:
        w.close()


def test_window_gates_boredom_and_recent_interaction(qapp):
    """两道闸门：不够无聊不排；刚交互完的 5 秒不排（别对着人脸叹气）。"""
    w = _mk()
    try:
        # 冻结驱力漂移：把 last_update 拨到未来 —— tick() 变空转。
        # （不然每秒结算会把 boredom 往上推一丁点，边界档位就滑过去了）
        w.drives.last_update = time.time() + 10.0
        w.drives.boredom = 0.55  # 门槛线上（严格大于才算）
        w.anim_t = 30.0
        w._tick()
        assert w.anim._sigh_next_at is None, "在门槛线上不该排"
        w.drives.boredom = 0.56
        w.anim_t = 31.0
        w._tick()
        assert w.anim._sigh_next_at is not None, "过了门槛没排"
        w.drives.boredom = 0.2  # 掉回门下线：排期清掉
        w.anim_t = 32.0
        w._tick()
        assert w.anim._sigh_next_at is None, "不无聊了排期还留着"
        w.drives.boredom = 0.9
        w._last_interaction_at = time.time()
        w.anim_t = 33.0
        w._tick()
        assert w.anim._sigh_next_at is None, "刚聊完就叹气？"
        w._last_interaction_at = time.time() - 6.0
        w.anim_t = 34.0
        w._tick()
        assert w.anim._sigh_next_at is not None, "5 秒过了还不排"
    finally:
        w.close()


def test_window_is_silent_when_asleep_anim_off_or_thinking(qapp):
    """睡着 / 动画关 / 思考中：三个都别排 —— 关就该关彻底。"""
    w = _mk()
    try:
        w.drives.boredom = 0.9
        w.drives.asleep = True
        w.anim_t = 40.0
        w._tick()
        assert w.anim._sigh_next_at is None, "睡着还排叹气"
        w.drives.asleep = False
        w.anim_on = False
        w.anim_t = 41.0
        w._tick()
        assert w.anim._sigh_next_at is None, "动画关着还排叹气"
        w.anim_on = True
        w.thinking = True
        w.anim_t = 42.0
        w._tick()
        assert w.anim._sigh_next_at is None, "思考中还排叹气"
        w.thinking = False
        w.anim_t = 43.0
        w._tick()
        assert w.anim._sigh_next_at is not None, "都恢复了还不排"
    finally:
        w.close()


# ── 纪律与素材 ────────────────────────────────────


def test_sigh_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "sigh_preview.py").is_file()
    assert "sigh-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("sigh-strip.png", "sigh-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
