"""睡梦抽动（自选小步·第十二次）——「睡着的时候，偶尔轻轻抽一下」。

动机：睡着原先只有「不动 + 一个 Z」。真的活物睡着会做梦 —— 偶尔轻轻抽一下
（一激灵），然后接着睡。和 Z（睡着）、哈欠（醒来）、叹气（无聊）、点头（困）
同一条思路：状态要能被眼睛读出来 —— 这条补上「梦」。这也是第一条**只在睡着时**
出现的通道：醒着的时候，它一眼都不许有。

两块机制：
- 形状：twitch_amount 一条曲线（猛地一激灵 → 顶住一瞬 → 慢慢松回去），纯函数逐点可钉；
- 节奏：note_asleep 每隔 TWITCH_MIN_GAP~TWITCH_MAX_GAP 秒排一下（随机，别像节拍器）；
  刚睡着不马上抽（那是痉挛不是做梦）、醒了排期清掉、方向一左一右交替
  （不掷随机数：抽动本身很稀疏看不出交替，而且不占随机流 —— 同种子的孪生对比才拼得上）。

四层判据（和 test_nod 一个框架）：
1. 纯函数：曲线时间线逐点对账、节奏器行为、只加不改、reset 清态、确定性；
2. 窗口链路：睡着才排；动画关 / 思考中不许喂；醒着喂 = 一个字节都不许变；
3. 渲染（真窗口离屏双胞胎）：横向一激灵（±TWITCH_SHIFT_PX）、纵向一缩、宽度不动、
   收完逐字节归零；关键帧落在局部重绘区里；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：七个 TWITCH_* 常量在 anim.py 顶部；调参速查表第 22 节。）
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
    """别碰用户真实的状态文件（和 test_pet / test_nod 同一套隔离）。"""
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


def _peak(t0: float) -> float:
    """一次抽动"抽到顶"的时刻（顶住段中段）。"""
    return round(t0 + anim.TWITCH_JOLT_S + anim.TWITCH_HOLD_S / 2, 6)


# ── 纯函数层：曲线与节奏 ──────────────────────────


def test_twitch_constants_stay_subtle():
    """常量必须停在「小抽动」量级：抽得快、松得慢、节奏别密得像节拍器。"""
    total = anim.twitch_total()
    assert 0.2 <= total <= 0.9, f"整段 {total}s —— 太短看不清，太长就不像一激灵了"
    assert 0.04 <= anim.TWITCH_JOLT_S <= 0.15, "抽上去要快（肌肉一激灵）"
    assert 0.02 <= anim.TWITCH_HOLD_S <= 0.2, "顶住的一瞬要够长到能被看见"
    assert 0.15 <= anim.TWITCH_SETTLE_S <= 0.6
    assert anim.TWITCH_SETTLE_S >= 2.5 * anim.TWITCH_JOLT_S, "松回来要比抽上去慢得多"
    assert 0.85 <= anim.TWITCH_DEFLATE <= 0.95, "轻轻一缩：别缩成眨眼"
    assert isinstance(anim.TWITCH_SHIFT_PX, int), "横向幅度按整像素走"
    assert 2 <= anim.TWITCH_SHIFT_PX <= 4, "横向一激灵是像素级的小动作"
    assert 15.0 <= anim.TWITCH_MIN_GAP < anim.TWITCH_MAX_GAP <= 180.0, "节奏窗口不成立"
    assert anim.TWITCH_MIN_GAP >= anim.NOD_MIN_GAP / 2, "抽动是稀疏事件"


def test_twitch_shape_jerks_holds_and_relaxes():
    """形状三段拼一条时间线：抽上去 → 顶住 → 松回来；两头精确为 0、两段单调。"""
    j, h, s = anim.TWITCH_JOLT_S, anim.TWITCH_HOLD_S, anim.TWITCH_SETTLE_S
    assert anim.twitch_amount(-0.1) == 0.0, "还没开始就不该有"
    assert anim.twitch_amount(0.0) == 0.0, "从静息起步"
    assert anim.twitch_amount(j / 2) == pytest.approx(0.5), "抽到一半正好一半"
    assert anim.twitch_amount(j) == pytest.approx(1.0)
    assert anim.twitch_amount(j + h / 2) == 1.0, "顶住段是满的"
    k = j + h
    assert anim.twitch_amount(k + s / 2) == pytest.approx(0.5)
    assert anim.twitch_amount(anim.twitch_total()) == 0.0, "松完就该是零"
    assert anim.twitch_amount(anim.twitch_total() + 5.0) == 0.0
    up = [anim.twitch_amount(j * i / 20) for i in range(21)]
    assert all(b >= a for a, b in pairwise(up)), "抽上去段不单调"
    down = [anim.twitch_amount(k + s * i / 40) for i in range(41)]
    assert all(b <= a for a, b in pairwise(down)), "松回来段不单调"
    assert anim.twitch_total() == pytest.approx(j + h + s)


def test_twitch_alternates_direction_without_drawing_random():
    """方向一左一右交替，而且**不占随机流**（同种子孪生对比靠它）。"""
    a, b = Animator(seed=5), Animator(seed=5)
    a.twitch(10.0)
    a.twitch(20.0)  # 只抽、不画
    assert a._twitch_dir == b._twitch_dir == 1, "抽过两下（一来一回）方向计数该回到原处"
    # 不占随机流：抽了两下之后，与「什么都没抽过」的孪生拉到的随机数一模一样
    assert a._rng.random() == b._rng.random(), "twitch() 动了随机流 —— 孪生对比会散架"
    c = Animator(seed=5)
    c.twitch(10.0)
    assert c.frame_at(_peak(10.0), calm=True).dx == -anim.TWITCH_SHIFT_PX, "第一下该往左"
    c.twitch(20.0)
    assert c.frame_at(_peak(20.0), calm=True).dx == anim.TWITCH_SHIFT_PX, "第二下该换边"


def test_twitch_only_draws_when_asleep():
    """醒着 = 一眼都不许有（calm 定生死）；收完回到与孪生逐字段全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.twitch(T0)
    assert a.frame_at(_peak(T0), calm=True) != b.frame_at(_peak(T0), calm=True), (
        "前提不成立：睡着也没抽起来"
    )
    for tau in (0.0, 0.02, 0.095, 0.2, 0.35):
        t = round(T0 + tau, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} 醒着时抽动漏出来了"
    live = 0
    for tau in (0.0, 0.02, 0.095, 0.2, 0.35):
        t = round(T0 + tau, 6)
        if a.frame_at(t, calm=True) != b.frame_at(t, calm=True):
            live += 1
    assert live >= 3, f"睡着时只有 {live} 个采样点不一样 —— 没抽起来"
    t_after = round(T0 + anim.twitch_total() + 0.2, 6)
    assert a.frame_at(t_after, calm=True) == b.frame_at(t_after, calm=True), "收完还没回到常态"


def test_note_asleep_first_twitch_waits_a_gap():
    """刚睡着：先等一个（随机）间隔再抽第一下 —— 立刻抽那是痉挛，不是做梦。"""
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.note_asleep(T0, True)
    assert a._twitch_at == -99.0, "刚睡着就抽？"
    assert a._twitch_next_at is not None
    first = a._twitch_next_at
    assert T0 + anim.TWITCH_MIN_GAP <= first <= T0 + anim.TWITCH_MAX_GAP
    a.note_asleep(first - 0.5, True)
    assert a._twitch_at == -99.0, "还没到点就抽了"
    a.note_asleep(first, True)
    assert a._twitch_at == first, "到点了没抽"
    nxt = a._twitch_next_at
    assert nxt is not None and first + anim.TWITCH_MIN_GAP <= nxt <= first + anim.TWITCH_MAX_GAP, (
        "抽完没接着排下一下"
    )


def test_note_asleep_gap_is_randomized_not_a_metronome():
    """一直睡着：间隔全落在窗口里，而且不止一个值 —— 别像节拍器。"""
    a = Animator(seed=9)
    a.note_asleep(0.0, True)
    times = []
    for _ in range(40):
        t = a._twitch_next_at
        a.note_asleep(t, True)
        times.append(t)
    assert a._twitch_at == times[-1]
    gaps = [b - a_ for a_, b in pairwise(times)]
    assert all(anim.TWITCH_MIN_GAP <= g <= anim.TWITCH_MAX_GAP for g in gaps), gaps
    assert len(set(gaps)) >= 3, "间隔全一个样 —— 成节拍器了"


def test_note_asleep_wake_clears_pending_schedule():
    """醒了：排期清掉、之后一秒都不许再抽；再睡着重新排（不是接着旧的窗口）。"""
    c = Animator(seed=13)
    c.note_asleep(T0, True)
    assert c._twitch_next_at is not None
    c.note_asleep(T0 + 1.0, False)
    assert c._twitch_next_at is None, "醒了排期还留着"
    for i in range(120):
        c.note_asleep(T0 + 2.0 + i, False)
    assert c._twitch_at == -99.0, "说醒了又抽了一下"
    c.note_asleep(T0 + 200.0, True)
    assert c._twitch_next_at is not None, "再睡着没重排"
    assert T0 + 200.0 + anim.TWITCH_MIN_GAP <= c._twitch_next_at <= T0 + 200.0 + anim.TWITCH_MAX_GAP


def test_twitch_restart_starts_fresh():
    """中途再排一次：从抽上去重新起步 —— 与「只在这一刻开始」的孪生全等。

    方向也得同边：先让两边各消耗掉「第 1 下」，再一起开「第 2 下」。
    """
    a, d = Animator(seed=17), Animator(seed=17)
    _walk(a, 0.0, T0)
    _walk(d, 0.0, T0)
    a.twitch(T0)
    d.twitch(T0 - 10.0)  # 第 1 下（早演完了）：只为了把方向计数对齐
    assert a.frame_at(round(T0 + 0.3, 6), calm=True) != d.frame_at(round(T0 + 0.3, 6), calm=True), (
        "前提不成立：a 没有在抽"
    )
    t2 = T0 + 0.35
    a.twitch(t2)
    d.twitch(t2)
    for tau in (0.0, 0.05, 0.12, 0.25, 0.45, 0.8):
        t = round(t2 + tau, 6)
        assert a.frame_at(t, calm=True) == d.frame_at(t, calm=True), f"{t} 重开后没有从头起步"


def test_twitch_reset_clears_state():
    """时间线被拨动（reset）：旧的那下不作数、排期也清掉。"""
    a, b = Animator(seed=19), Animator(seed=19)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.twitch(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.05, 0.15, 0.3, 0.7):
        t = round(T0 + 0.2 + tau, 6)
        assert a.frame_at(t, calm=True) == b.frame_at(t, calm=True), f"{t} reset 之后旧抽动还在"
    c = Animator(seed=21)
    c.note_asleep(T0, True)
    assert c._twitch_next_at is not None
    c.twitch(T0 + 1.0)
    c.reset(T0 + 2.0)
    assert c._twitch_at == -99.0
    assert c._twitch_next_at is None, "reset 后旧排期还留着"


def test_twitch_is_deterministic():
    """同一条序列跑两遍逐值相等（种子相同 = 演出相同）；顺带走一遍自动排程。"""

    def run():
        a = Animator(seed=23)
        out = []
        for i in range(1, 1601):
            t = round(i * 0.05, 6)
            a.note_asleep(t, True)  # 窗口每秒喂一次 —— 这里每步都喂
            if i == 60:
                a.twitch(t)
            f = a.frame_at(t, calm=True)
            out.append((round(f.squash, 12), f.dx, f.dy, f.gx, f.gy))
        return out

    assert run() == run()


def test_awake_feeds_change_nothing():
    """醒着喂 note_asleep(False)：与「什么都没喂」的孪生逐帧全等（只加不改红线）。"""
    a, b = Animator(seed=29), Animator(seed=29)
    for i in range(0, 401):
        t = round(i * 0.05, 6)
        a.note_asleep(t, False)
        assert a.frame_at(t) == b.frame_at(t), f"{t} 醒着喂 note_asleep 改变了行为"


def test_twitch_matches_formula_point_by_point():
    """整段逐点对账（0.01 秒网格）：两个通道按公式对齐到每个采样点。"""
    a = Animator(seed=11)
    _walk(a, 0.0, T0)
    a.twitch(T0)
    live = 0
    for i in range(1, 61):
        t = round(T0 + i * 0.01, 6)
        k = anim.twitch_amount(t - T0)
        f = a.frame_at(t, calm=True)
        base = round(
            anim.CALM_FACTOR * anim.SWAY_AMPLITUDE * math.sin(2 * math.pi * t / anim.SWAY_PERIOD)
        )
        assert f.dx == base - round(anim.TWITCH_SHIFT_PX * k), t
        assert f.squash == pytest.approx(1.0 - (1.0 - anim.TWITCH_DEFLATE) * k), t
        if k > 0:
            live += 1
    assert live >= 30, f"窗口里只有 {live} 帧在动"
    t_after = round(T0 + anim.twitch_total() + 0.3, 6)
    f = a.frame_at(t_after, calm=True)
    base = round(
        anim.CALM_FACTOR * anim.SWAY_AMPLITUDE * math.sin(2 * math.pi * t_after / anim.SWAY_PERIOD)
    )
    assert f.dx == base and f.squash == 1.0, "收完之后没回到静息"


def test_geometry_guard_covers_the_twitch_channel():
    """全局几何预算守卫（test_yawn）必须把睡梦抽动算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "anim.TWITCH_SHIFT_PX" in text, (
        "test_yawn 的全局预算守卫里没有睡梦抽动通道 —— 调大 TWITCH_* 就没人拦了"
    )


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import SLEEP_EXPR, SammyWindow  # noqa: E402

SEED_TWITCH = 7


def _mk(scale: float = 1.0) -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留抽动这一个变量。

    energy 定在「累趴」档：状态行说「睡着了」而脸是睡脸（不 set asleep 标志 ——
    那样会挂出 Z；Z 有自己的 doze 素材，这里要的是干净的对照）。
    眨眼请出去：快抽动和眨眼共用 squash 通道，撞上就量不准。
    """
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = scale
    w._offset = (0, 0)
    w.resize(round(800 * scale), round(480 * scale))
    w._relayout()
    w.anim = anim.Animator(seed=SEED_TWITCH, blink_gap=(600.0, 600.0))
    w.look_on = False  # 光标不参与（盯的是抽动这一件事）
    w.drives.energy = 0.05  # 累趴：状态行「睡着了」与睡脸一致
    w.set_expression(SLEEP_EXPR)
    w.status = drives.status_text(w.drives)
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    return w


def _img_bytes(w: SammyWindow) -> bytes:
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(img.constBits())


def _clip(w: SammyWindow) -> QRect:
    box = w.lay.face
    return QRect(box.left() - 60, 6, box.width() + 120, 240)


def _lit_bbox(w: SammyWindow, clip: QRect) -> tuple[int, int, int, int]:
    """clip 里的「不透明亮像素」外接框（颜色从 faces.LIT 读，alpha 必须实）。"""
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


def test_twitch_jolts_sideways_and_shrinks_when_asleep(qapp):
    """scale 1.0 双胞胎：横向一激灵正好 ±SHIFT、纵向一缩、宽度不动、收完逐字节归零。"""
    a, b = _mk(), _mk()
    try:
        a.anim.twitch(8.5)
        clip = _clip(a)
        a.anim_t = _peak(8.5)
        b.anim_t = _peak(8.5)
        x0a, y0a, x1a, y1a = _lit_bbox(a, clip)
        x0b, y0b, x1b, y1b = _lit_bbox(b, clip)
        assert x0a - x0b == -anim.TWITCH_SHIFT_PX, (
            f"横向一激灵没量到：左右缘差 ({x0a - x0b:+d}, {x1a - x1b:+d})"
        )
        assert x1a - x1b == -anim.TWITCH_SHIFT_PX, "右缘也要跟着走（是平移不是变形）"
        assert abs((x1a - x0a) - (x1b - x0b)) <= 2, "抽动不该动宽度"
        assert y0a - y0b >= 2, f"顶沿没被压下来：{y0a - y0b}px"
        assert y1b - y1a >= 2, f"下沿没被压上去：{y1b - y1a}px"
        h_a, h_b = y1a - y0a, y1b - y0b
        assert h_a <= h_b - 6, f"脸没缩：{h_a} vs {h_b}"
        after = round(8.5 + anim.twitch_total() + 0.4, 6)
        a.anim_t = after
        b.anim_t = after
        assert _img_bytes(a) == _img_bytes(b), "抽动收完还不回到常态"
        # 第二下换边（往右）
        a.anim.twitch(20.0)
        a.anim_t = _peak(20.0)
        b.anim_t = _peak(20.0)
        x0a2, _, x1a2, _ = _lit_bbox(a, clip)
        x0b2, _, x1b2, _ = _lit_bbox(b, clip)
        assert x0a2 - x0b2 == anim.TWITCH_SHIFT_PX, "第二下没换边"
        assert x1a2 - x1b2 == anim.TWITCH_SHIFT_PX
    finally:
        a.close()
        b.close()


def test_twitch_key_moment_stays_inside_the_repainted_region(qapp):
    """抽到顶那一帧必须落在局部重绘区里 —— 在外面那圈不刷新（脸会花）。"""
    w = _mk()
    try:
        w.anim.twitch(8.5)
        clip = _clip(w)
        region = w._face_region()
        w.anim_t = _peak(8.5)
        x0, y0, x1, y1 = _lit_bbox(w, clip)
        deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        assert region.contains(deformed), f"抽到顶时脸 {deformed} 冒出重绘区 {region}"
    finally:
        w.close()


# ── 链路：窗口把「睡着」喂给动画层 ──────────────────


def test_window_schedules_and_fires_twitches_when_asleep(qapp):
    """睡着 + 没在忙：先排、到点、抽完接着排 —— 一路都在窗口这一层。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0  # 冻结驱力漂移（边界用例的老规矩）
        w.drives.asleep = True
        w.anim_t = 50.0
        w._tick()
        first = w.anim._twitch_next_at
        assert first is not None, "睡着了却没排抽动"
        assert 50.0 + anim.TWITCH_MIN_GAP <= first <= 50.0 + anim.TWITCH_MAX_GAP
        assert w.anim._twitch_at == -99.0, "排期不该当场就抽"
        w.anim_t = round(first - 0.2, 6)
        w._tick()
        assert w.anim._twitch_at == -99.0, "还没到点就抽了"
        w.anim_t = first
        w._tick()
        assert w.anim._twitch_at == first, "到点了没抽"
        nxt = w.anim._twitch_next_at
        assert nxt is not None and nxt >= first + anim.TWITCH_MIN_GAP, "抽完没接着排"
        w.anim_t = nxt
        w._tick()
        assert w.anim._twitch_at == nxt, "第二下没来"
    finally:
        w.close()


def test_window_feeds_wake_and_awake_states(qapp):
    """醒了：排期清掉；一直醒着：喂多少秒都不排。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.drives.asleep = True
        w.anim_t = 50.0
        w._tick()
        assert w.anim._twitch_next_at is not None
        w.drives.asleep = False
        w.anim_t = 51.0
        w._tick()
        assert w.anim._twitch_next_at is None, "醒了排期还留着"
        for i in range(60):
            w.anim_t = 52.0 + i
            w._tick()
        assert w.anim._twitch_next_at is None and w.anim._twitch_at == -99.0, "醒着还抽"
    finally:
        w.close()


def test_window_is_silent_when_anim_off_or_thinking(qapp):
    """动画关 / 思考中：两个都别喂 —— 关就该关彻底。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.drives.asleep = True
        w.anim_on = False
        w.anim_t = 40.0
        w._tick()
        assert w.anim._twitch_next_at is None, "动画关着还排抽动"
        w.anim_on = True
        w.thinking = True
        w.anim_t = 41.0
        w._tick()
        assert w.anim._twitch_next_at is None, "思考中还排抽动"
        w.thinking = False
        w.anim_t = 42.0
        w._tick()
        assert w.anim._twitch_next_at is not None, "都恢复了还不排"
    finally:
        w.close()


# ── 纪律与素材 ────────────────────────────────────


def test_twitch_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "twitch_preview.py").is_file()
    assert "twitch-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("twitch-strip.png", "twitch-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
