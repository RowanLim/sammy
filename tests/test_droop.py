"""蔫一会儿（自选小步·第二十三次）——「心情有点蔫的时候，悄悄往下垂一垂」。

动机：哼小曲（第十六次）是第一条只挂心情的自发动作 —— 但它只讲「高兴」。
这条讲对着的另一头：心情落进「有点蔫」的档里（和心情标签同一档：低于
-0.05），隔一会儿没精神地往下垂一垂（头沉下去、眼皮也耷拉一点），停一段、
自己再慢慢缓起来。往下走的路数（沉 + 压扁）沿用叹气 / 点头那一族，区别在
慢、深、停得久 —— 读的不是一口气，是一段情绪。再往下（「低落」档）它会
直接呆住不动（calm 定格）—— 那是更重的状态，不用叠动作。

两块机制：
- 形状：droop_amount 一条三段曲线（垂下去 → 蔫着停住 → 缓起来），纯函数逐点可钉；
- 节奏：note_droop 每隔 DROOP_MIN_GAP~DROOP_MAX_GAP 秒排一下（随机，别像节拍器）；
  刚蔫下去先等一个间隔（立刻垂 = 情绪还没长出来）、心情缓回来排期清掉、
  正在垂的那下让它垂完（半路掐掉像打了个哆嗦）。

窗口那层的闸门（_droop_ok）：睡着 / 累趴 / 被拎着 / 正在看着你写字 /
刚交互完的 5 秒 / 心情没到「有点蔫」—— 都不垂；思考中天然不跑（_tick 整个不跑）。

四层判据（和 test_hum / test_sigh 一个框架）：
1. 纯函数：曲线逐点对账、节奏器四件事、只加不改、下沉与压扁逐点对齐公式、确定性；
2. 窗口链路：心情到线才排、各道闸门各拦一次、动画关 / 思考中不排；
3. 渲染（真窗口离屏双胞胎）：顶沿下沉 / 下沿上收 / 脸变矮、宽度不动、收完逐字节归零；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：DROOP_* 常量在 anim.py 顶部；调参速查表第 33 节。）
"""

from __future__ import annotations

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
    """别碰用户真实的状态文件（和 test_pet / test_hum 同一套隔离）。"""
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


def _droop_terms(t: float, at: float) -> tuple[int, float]:
    """按实现同一条算式复算：这一刻蔫一会儿往 dy / 压扁项上加了多少。

    dy 只受下沉项影响；压扁项是 min() 的一支（没在垂 = 1.0，等于没压）。
    """
    k = anim.droop_amount(t - at)
    if k <= 0.0:
        return 0, 1.0
    return round(anim.DROOP_SINK_PX * k), 1.0 - (1.0 - anim.DROOP_SQUINT_MIN) * k


# ── 纯函数层：曲线与节奏 ──────────────────────────


def test_droop_constants_stay_subtle():
    """常量必须停在「蔫一会儿」量级：全程都慢、比叹气深、比入睡浅、不疾不徐。"""
    total = anim.droop_total()
    assert 3.0 <= total <= 5.5, f"整段 {total}s —— 太短读不出「一段情绪」，太长像慢放"
    assert anim.DROOP_SINK_S >= anim.SIGH_SINK_S, "垂下去不该比叹气还急"
    assert anim.DROOP_HOLD_S >= anim.NOD_HOLD_S, "停住的一段不该比点头还短"
    assert anim.DROOP_RISE_S >= 0.8
    assert anim.SIGH_SINK_PX < anim.DROOP_SINK_PX <= anim.DOZEOFF_SINK_PX, "深一点、但没到入睡那下"
    assert anim.SIGH_DEFLATE > anim.DROOP_SQUINT_MIN > anim.NOD_SQUINT_MIN, "眼皮比点头浅、比叹气深"
    assert 30.0 <= anim.DROOP_MIN_GAP < anim.DROOP_MAX_GAP <= 300.0, "节奏窗口不成立"
    assert anim.DROOP_MIN_GAP >= anim.HUM_MIN_GAP, "心情另一头也别比哼小曲还频"
    assert anim.DROOP_MAX_GAP <= anim.SNEEZE_MAX_GAP, "也别比喷嚏还稀罕"


def test_droop_shape_sinks_holds_and_recovers():
    """三段拼一条时间线：垂下去缓、停住恒 1、缓起来缓；两头精确为 0、各段单调。"""
    assert anim.droop_amount(-0.1) == 0.0, "还没开始就不该有"
    assert anim.droop_amount(0.0) == 0.0, "从静息起步"
    assert anim.droop_amount(anim.DROOP_SINK_S / 2) == pytest.approx(0.5)
    assert anim.droop_amount(anim.DROOP_SINK_S) == pytest.approx(1.0)
    hold_end = anim.DROOP_SINK_S + anim.DROOP_HOLD_S
    assert anim.droop_amount(hold_end - 1e-6) == pytest.approx(1.0)
    assert anim.droop_amount(hold_end + anim.DROOP_RISE_S / 2) == pytest.approx(0.5)
    assert anim.droop_amount(anim.droop_total()) == pytest.approx(0.0), "收完就该是零"
    assert anim.droop_amount(anim.droop_total() + 5.0) == 0.0
    down = [anim.droop_amount(anim.DROOP_SINK_S * i / 20) for i in range(21)]
    assert all(b >= a for a, b in pairwise(down)), "垂下去段不单调"
    mid = [anim.droop_amount(anim.DROOP_SINK_S + 0.05 * i) for i in range(31)]
    assert all(v == pytest.approx(1.0) for v in mid), "停住段应该是恒 1"
    up = [anim.droop_amount(hold_end + anim.DROOP_RISE_S * i / 20) for i in range(21)]
    assert all(b <= a for a, b in pairwise(up)), "缓起来段不单调"


def test_note_droop_first_one_waits_a_gap():
    """刚蔫下去：先等一个（随机）间隔再垂第一下 —— 立刻垂 = 情绪还没长出来。"""
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.note_droop(T0, True)
    assert a._droop_at == -99.0, "刚蔫就立刻垂，像情绪还没来得及长出来"
    assert a._droop_next_at is not None
    first = a._droop_next_at
    assert T0 + anim.DROOP_MIN_GAP <= first <= T0 + anim.DROOP_MAX_GAP
    a.note_droop(first - 0.5, True)
    assert a._droop_at == -99.0, "还没到点就垂了"
    a.note_droop(first, True)
    assert a._droop_at == first, "到点了没垂"
    nxt = a._droop_next_at
    assert nxt is not None and first + anim.DROOP_MIN_GAP <= nxt <= first + anim.DROOP_MAX_GAP, (
        "垂完没接着排下一下"
    )


def test_note_droop_gap_is_randomized_not_a_metronome():
    """一直蔫：间隔全落在窗口里，而且不止一个值 —— 别像节拍器。"""
    a = Animator(seed=9)
    a.note_droop(0.0, True)
    times = []
    for _ in range(60):
        t = a._droop_next_at
        a.note_droop(t, True)
        times.append(t)
    assert a._droop_at == times[-1]
    gaps = [b - p for p, b in pairwise(times)]
    assert all(anim.DROOP_MIN_GAP <= g <= anim.DROOP_MAX_GAP for g in gaps), gaps
    assert len(set(gaps)) >= 3, "间隔全一个样 —— 成节拍器了"


def test_note_droop_off_clears_pending_schedule():
    """心情缓回来了（不能垂了）：排期清掉；之后不再垂新的。"""
    c = Animator(seed=13)
    c.note_droop(T0, True)
    assert c._droop_next_at is not None
    c.note_droop(T0 + 1.0, False)
    assert c._droop_next_at is None, "不能垂了排期还留着"
    for i in range(120):
        c.note_droop(T0 + 2.0 + i, False)
    assert c._droop_at == -99.0, "说不能垂了还垂了一下"


def test_gate_off_feeds_never_leak():
    """怎么喂「不能垂」都和什么都不喂的孪生逐帧全等（400 步）—— 闸门关彻底。"""
    a, b = Animator(seed=31), Animator(seed=31)
    for i in range(1, 401):
        t = round(i * 0.033, 6)
        a.note_droop(t, False)
        assert a.frame_at(t) == b.frame_at(t), f"{t} 闸门关着还漏出动作"


def test_one_in_flight_droop_finishes_after_gate_off():
    """正在垂的那下让它垂完：'不能垂了'只清排期，不掐当前 —— 半路掐掉像打了个哆嗦。"""
    a, b = Animator(seed=11), Animator(seed=11)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.droop(T0)
    a.note_droop(T0 + 0.3, False)  # 垂到一半心情缓回来了
    for tau in (0.4, 1.2, 2.0, 3.2):
        t = round(T0 + tau, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (fa.dy, fa.squash) != (fb.dy, fb.squash), f"{t} 排着的那下被'不能垂'掐掉了？"
    end = round(T0 + anim.droop_total() + 0.4, 6)
    assert a.frame_at(end) == b.frame_at(end), "收完没回到常态"


def test_droop_only_adds_other_channels_do_not_move():
    """只垂的一方与完全没垂的孪生：别的通道一个都不许动；窗外全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.droop(T0)
    live = 0
    end = T0 + anim.droop_total()
    for i in range(1, 161):
        t = round(T0 + i * 0.025, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (fa.dx, fa.pop, fa.gx, fa.gy, fa.stretch, fa.talk_y, fa.talk_sq, fa.tilt) == (
            fb.dx,
            fb.pop,
            fb.gx,
            fb.gy,
            fb.stretch,
            fb.talk_y,
            fb.talk_sq,
            fb.tilt,
        ), f"{t} 时别的通道被蔫一会儿带偏了"
        if t < end:
            if fa.dy != fb.dy or fa.squash != fb.squash:
                live += 1
        else:
            assert fa.dy == fb.dy and fa.squash == fb.squash, f"{t} 收完之后还没回到常态"
    assert live >= 120, f"窗口里只有 {live} 帧真的垂了 —— 没垂起来"


def test_droop_matches_formula_point_by_point():
    """整段逐点对账（0.02 秒网格）：dy 与压扁项都对到公式的每个采样点。"""
    a, b = Animator(seed=11), Animator(seed=11)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.droop(T0)
    live = 0
    for i in range(201):
        t = round(T0 + i * 0.02, 6)
        want_dy, want_sq = _droop_terms(t, T0)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert fa.dy - fb.dy == want_dy, t
        assert fa.squash == pytest.approx(min(fb.squash, want_sq)), t
        if want_dy != 0:
            live += 1
    assert live >= 150, f"窗口里只有 {live} 帧垂动了"


def test_droop_suppressed_when_calm_and_resumes_after():
    """睡着 / 呆住（calm）不垂（定格优先）；醒来接着垂（不是半路掐掉重来）。"""
    a, b = Animator(seed=15), Animator(seed=15)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.droop(T0)
    for i in range(1, 30):
        t = round(T0 + i * 0.05, 6)
        fa = a.frame_at(t, calm=True)
        fb = b.frame_at(t, calm=True)
        assert (fa.dy, fa.squash) == (fb.dy, fb.squash), f"{t} calm 里下垂漏出来了"
    mid = round(T0 + 1.5, 6)
    fa, fb = a.frame_at(mid), b.frame_at(mid)
    assert fa.squash != fb.squash, "醒来没接着垂（被 calm 掐了）"


def test_droop_restart_starts_fresh():
    """中途再排一下：从垂下去重新起步 —— 与「只在这一刻开始」的孪生全等。"""
    a, c = Animator(seed=17), Animator(seed=17)
    _walk(a, 0.0, T0)
    _walk(c, 0.0, T0)
    a.droop(T0)
    assert a.frame_at(T0 + 0.75).squash != c.frame_at(T0 + 0.75).squash, "前提不成立：a 没有在垂"
    t2 = T0 + 1.0  # 垂到一半再来一下
    a.droop(t2)
    c.droop(t2)
    for tau in (0.0, 0.05, 0.2, 0.5, 1.0, 2.0, 3.0, 4.2):
        t = round(t2 + tau, 6)
        assert a.frame_at(t) == c.frame_at(t), f"{t} 重开后没有从头起步"


def test_droop_reset_clears_state():
    """时间线被拨动（reset）：旧的那下不作数、排期也清掉。"""
    a, b = Animator(seed=19), Animator(seed=19)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.droop(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.05, 0.2, 0.5, 1.2, 2.5):
        t = round(T0 + 0.2 + tau, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} reset 之后旧的那下还在"
    c = Animator(seed=23)
    c.note_droop(T0, True)
    assert c._droop_next_at is not None
    c.droop(T0 + 1.0)
    c.reset(T0 + 2.0)
    assert c._droop_at == -99.0
    assert c._droop_next_at is None, "reset 后旧排期还留着"


def test_droop_is_deterministic():
    """同一条序列跑两遍逐值相等（种子相同 = 演出相同）。"""

    def run():
        a = Animator(seed=29)
        out = []
        for i in range(1, 161):
            t = round(i * 0.05, 6)
            if i == 40:
                a.droop(t)
            if i == 60:
                a.note_droop(t, True)
            f = a.frame_at(t)
            out.append((round(f.squash, 12), f.dy, f.dx, round(f.stretch, 12), f.gx, f.gy))
        return out

    assert run() == run()


def test_geometry_guard_covers_the_droop_channel():
    """全局几何预算守卫（test_yawn）必须把蔫一会儿的下沉算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "anim.DROOP_SINK_PX" in text, (
        "test_yawn 的全局预算守卫里没有蔫一会儿的下沉通道 —— 调大 DROOP_SINK_PX 就没人拦了"
    )


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import DROOP_MOOD_BELOW, SammyWindow  # noqa: E402

SEED_DROOP = 7


def _mk() -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留蔫一会儿这一个变量。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    # 眨眼请出去（和喷嚏 / 哼小曲同一个理由：量下沉时画面里越干净越好）
    w.anim = anim.Animator(seed=SEED_DROOP, blink_gap=(600.0, 600.0))
    w.look_on = False  # 光标不参与（盯的是蔫一会儿这一件事）
    w.set_expression(2)  # 普通脸：「有点蔫」的档里它就是这张
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    return w


def _img_bytes(w: SammyWindow) -> bytes:
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(img.constBits())


def _lit_bbox(w: SammyWindow, clip: QRect) -> tuple[int, int, int, int]:
    """clip 里的「不透明亮像素」外接框（跟 faces.LIT 常量对，不写死色相）。"""
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


def test_droop_sinks_the_face_and_recovers(qapp):
    """scale 1.0 双胞胎：顶沿沉下去、下沿上收、脸变矮、宽度不动、收完逐字节归零。"""
    a, b = _mk(), _mk()
    try:
        a.anim.droop(8.5)
        box = a.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)

        def look(w: SammyWindow, t: float):
            w.anim_t = t
            return _lit_bbox(w, clip)

        full = round(8.5 + anim.DROOP_SINK_S + anim.DROOP_HOLD_S * 0.5, 6)  # 垂到底（停住中段）
        x0a, y0a, x1a, y1a = look(a, full)
        x0b, y0b, x1b, y1b = look(b, full)
        drop = y0a - y0b
        assert 23 <= drop <= 31, f"顶沿没垂下去（或垂过头）：{drop}px"
        assert -19 <= y1a - y1b <= -9, f"下沿该往上收：{y1a - y1b}px"
        h_a, h_b = y1a - y0a, y1b - y0b
        shrink = h_b - h_a
        assert 38 <= shrink <= 52, f"脸没变矮：{shrink}px（{h_a} vs {h_b}）"
        assert abs((x1a - x0a) - (x1b - x0b)) <= 2, "蔫一会儿不该动宽度"
        half = round(8.5 + anim.DROOP_SINK_S * 0.5, 6)
        _, y0h, _, _ = look(a, half)
        _, y0bh, _, _ = look(b, half)
        drop_half = y0h - y0bh
        assert 4 <= drop_half <= drop - 4, "垂下去不是渐进的"
        after = round(8.5 + anim.droop_total() + 0.4, 6)
        a.anim_t = after
        b.anim_t = after
        assert _img_bytes(a) == _img_bytes(b), "蔫一会儿收完还不回到常态"
    finally:
        a.close()
        b.close()


def test_droop_key_moment_stays_inside_the_repainted_region(qapp):
    """垂到底那一帧必须落在局部重绘区里 —— 在外面那圈不刷新（脸会花）。"""
    w = _mk()
    try:
        w.anim.droop(8.5)
        box = w.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)
        region = w._face_region()
        w.anim_t = round(8.5 + anim.DROOP_SINK_S + anim.DROOP_HOLD_S * 0.5, 6)
        x0, y0, x1, y1 = _lit_bbox(w, clip)
        deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        assert region.contains(deformed), f"垂到底时脸 {deformed} 冒出重绘区 {region}"
    finally:
        w.close()


# ── 链路：窗口把「心情蔫不蔫」喂给动画层 ─────────────


def test_window_schedules_droop_only_when_wilting(qapp):
    """链路：心情落进「有点蔫」才排；缓回来清掉；再蔫重新排、到点就垂。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0  # 冻结驱力漂移（边界用例的老规矩）
        w.mood.mood.valence = 0.0
        w.anim_t = 50.0
        w._tick()
        assert w.anim._droop_next_at is None, "平静着就排垂？"
        w.mood.mood.valence = DROOP_MOOD_BELOW  # 正好在门线上（严格低于才算）
        w.anim_t = 51.0
        w._tick()
        assert w.anim._droop_next_at is None, "门线上不该排"
        w.mood.mood.valence = DROOP_MOOD_BELOW - 0.01
        w.anim_t = 52.0
        w._tick()
        first = w.anim._droop_next_at
        assert first is not None, "蔫了（过线）却没排"
        assert 52.0 + anim.DROOP_MIN_GAP <= first <= 52.0 + anim.DROOP_MAX_GAP
        assert w.anim._droop_at == -99.0, "排期不该当场就垂"
        w.mood.mood.valence = 0.2  # 缓回来了
        w.anim_t = 53.0
        w._tick()
        assert w.anim._droop_next_at is None, "心情缓回来了还排着垂"
        w.mood.mood.valence = -0.3
        w.anim_t = 54.0
        w._tick()
        second = w.anim._droop_next_at
        assert second is not None and second >= 54.0 + anim.DROOP_MIN_GAP, "又蔫了没有重新排"
        w.anim_t = second
        w._tick()
        assert w.anim._droop_at == second, "到点了没垂"
        nxt = w.anim._droop_next_at
        assert nxt is not None and nxt >= second + anim.DROOP_MIN_GAP, "垂完没接着排"
    finally:
        w.close()


def test_window_gates_asleep_exhausted_drag_typing_and_recent_interaction(qapp):
    """闸门：睡着 / 累趴 / 被拎着 / 正在看着你写字 / 刚交互完 5 秒 —— 都不垂。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.mood.mood.valence = -0.3
        w.anim_t = 30.0
        w._tick()
        assert w.anim._droop_next_at is not None, "蔫着又不忙却不排"
        w.drives.asleep = True
        w.anim_t = 31.0
        w._tick()
        assert w.anim._droop_next_at is None, "睡着还排蔫"
        w.drives.asleep = False
        w.drives.energy = 0.05  # 累趴（够不着唤醒线）
        w.anim_t = 32.0
        w._tick()
        assert w.anim._droop_next_at is None, "累趴了还垂"
        w.drives.energy = 0.8
        w._drag = QPoint(1, 1)
        w.anim_t = 33.0
        w._tick()
        assert w.anim._droop_next_at is None, "被拎着还排蔫"
        w._drag = None
        w.anim_t = 34.0
        w._tick()
        assert w.anim._droop_next_at is not None, "放下了还不排"
        w._last_typing_at = time.time()
        w.anim_t = 35.0
        w._tick()
        assert w.anim._droop_next_at is None, "正被看着写字还垂脑袋"
        w._last_typing_at = 0.0
        w._last_interaction_at = time.time()
        w.anim_t = 36.0
        w._tick()
        assert w.anim._droop_next_at is None, "刚聊完就垂脑袋？"
        w._last_interaction_at = time.time() - 6.0
        w.anim_t = 37.0
        w._tick()
        assert w.anim._droop_next_at is not None, "5 秒过了还不排"
    finally:
        w.close()


def test_window_is_silent_when_anim_off_or_thinking(qapp):
    """动画关 / 思考中：都不排 —— 关就该关彻底。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.mood.mood.valence = -0.3
        w.anim_on = False
        w.anim_t = 40.0
        w._tick()
        assert w.anim._droop_next_at is None, "动画关着还排蔫"
        w.anim_on = True
        w.thinking = True
        w.anim_t = 41.0
        w._tick()
        assert w.anim._droop_next_at is None, "思考中还排蔫"
        w.thinking = False
        w.anim_t = 42.0
        w._tick()
        assert w.anim._droop_next_at is not None, "都恢复了还不排"
    finally:
        w.close()


# ── 纪律与素材 ────────────────────────────────────


def test_droop_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "droop_preview.py").is_file()
    assert "droop-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("droop-strip.png", "droop-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
