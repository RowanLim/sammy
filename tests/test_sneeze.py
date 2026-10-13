"""打个喷嚏（自选小步·第十五次）——「偶尔呛一下的小家伙（哈啾）」。

动机：上一批自发动作全挂在情绪上 —— 叹气挂无聊、点头挂犯困、抽动挂睡着。
可一个真的活物还有一个**没来由**的动作：喷嚏。老机器里的小家伙也会呛着：
先皱起脸（「哈——」的酝酿）、猛地一缩闭上眼并往上窜一点（「啾！」）、再慢慢
松回来。它是第一条没有前置情绪的自发动作，也是第一条**不躲着交互**的
（喷嚏是反射不是态度 —— 跟人说着话照样打）。

两块机制：
- 形状：sneeze_amount 一条四段曲线（酝酿 → 爆发 → 顶住 → 松回），纯函数逐点可钉；
- 节奏：note_sneeze 每隔 SNEEZE_MIN_GAP~SNEEZE_MAX_GAP 秒排一个（随机，别像
  节拍器）；刚能打（醒来 / 被放下）先等一个间隔（立刻打 = 反射弧太短）、
  不能打了（睡着 / 被拎起来）排期清掉、正在打的那个让它打完（半路掐掉像噎住）。

四层判据（和 test_nod 一个框架）：
1. 纯函数：曲线时间线逐点对账、节奏器行为、只加不改、reset 清态、确定性、方向交替；
2. 窗口链路：醒着且没被拎着才排；睡着 / 被拎着 / 动画关 / 思考中各拦一次；
3. 渲染（真窗口离屏双胞胎）：爆发帧用力闭眼 + 缩进去（顶沿 / 下沿各收 45px 以上）、
   酝酿段只是「皱起来」；收完逐字节归零；关键帧落在重绘区里；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：十个 SNEEZE_* 常量在 anim.py 顶部；调参速查表第 25 节。
第一下往左（_sneeze_dir 初始 +1 取反），之后每次一换边 —— 不掷随机数，
同种子的孪生对比（素材）才拼得上。）
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


def _blink_squash(a: Animator, t: float) -> float:
    """按眨眼时间表复算这一刻的 squash（没有喷嚏成分）—— 对账用。"""
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


def test_sneeze_constants_stay_subtle():
    """常量必须停在「喷嚏」量级：酝酿短、爆发更短、比眨眼还紧一点、比点头更稀有。"""
    total = anim.sneeze_total()
    assert 0.45 <= total <= 0.9, f"整段 {total}s —— 太短看不清过程，太长像慢动作"
    assert 0.12 <= anim.SNEEZE_WINDUP_S <= 0.40
    assert 0.03 <= anim.SNEEZE_BURST_S <= 0.12
    assert anim.SNEEZE_BURST_S < anim.SNEEZE_WINDUP_S / 2, (
        "爆发段必须比酝酿段短得多：快慢对比才是喷嚏"
    )
    assert 0.02 <= anim.SNEEZE_HOLD_S <= 0.15
    assert 0.15 <= anim.SNEEZE_SETTLE_S <= 0.6
    assert 0.08 <= anim.SNEEZE_SQUINT_MIN <= 0.18, "闭眼要闭得干脆（别到眨眼的量级之外）"
    assert anim.SNEEZE_SQUINT_MIN <= anim.BLINK_MIN_SQUASH + 0.01, "喷嚏应该和眨眼一样紧（或更紧）"
    assert 2 <= anim.SNEEZE_LIFT_PX <= 5, "上窜是像素级的小动作"
    assert 1 <= anim.SNEEZE_JERK_PX <= 4, "横向哆嗦也是像素级"
    assert 0.2 <= anim.SNEEZE_WINDUP <= 0.5, "酝酿段的预兆要看得见、但不抢戏"
    assert 60.0 <= anim.SNEEZE_MIN_GAP < anim.SNEEZE_MAX_GAP <= 600.0, "节奏窗口不成立"
    assert anim.SNEEZE_MIN_GAP >= anim.NOD_MIN_GAP, "喷嚏是比点头更稀有的重事件"


def test_sneeze_shape_winds_up_bursts_and_settles():
    """形状四段拼一条时间线：酝酿 → 爆发 → 顶住 → 松回；两头精确为 0、各段单调。"""
    assert anim.sneeze_amount(-0.1) == 0.0, "还没开始就不该有"
    assert anim.sneeze_amount(0.0) == 0.0, "从静息起步"
    assert anim.sneeze_amount(anim.SNEEZE_WINDUP_S / 2) == pytest.approx(anim.SNEEZE_WINDUP / 2)
    assert anim.sneeze_amount(anim.SNEEZE_WINDUP_S) == pytest.approx(anim.SNEEZE_WINDUP)
    mid = anim.SNEEZE_WINDUP_S + anim.SNEEZE_BURST_S / 2
    assert anim.sneeze_amount(mid) == pytest.approx(
        anim.SNEEZE_WINDUP + (1.0 - anim.SNEEZE_WINDUP) / 2
    )
    b_end = anim.SNEEZE_WINDUP_S + anim.SNEEZE_BURST_S
    assert anim.sneeze_amount(b_end) == pytest.approx(1.0), "爆发段终点必须是满量"
    assert anim.sneeze_amount(b_end + anim.SNEEZE_HOLD_S / 2) == 1.0, "顶住段是满的"
    s0 = b_end + anim.SNEEZE_HOLD_S
    assert anim.sneeze_amount(s0 + anim.SNEEZE_SETTLE_S / 2) == pytest.approx(0.5)
    assert anim.sneeze_amount(anim.sneeze_total()) == 0.0, "松完就该是零"
    assert anim.sneeze_amount(anim.sneeze_total() + 5.0) == 0.0
    up = [anim.sneeze_amount(anim.SNEEZE_WINDUP_S * i / 20) for i in range(21)]
    assert all(b >= a for a, b in pairwise(up)), "酝酿段不单调"
    burst = [
        anim.sneeze_amount(anim.SNEEZE_WINDUP_S + anim.SNEEZE_BURST_S * i / 20) for i in range(21)
    ]
    assert all(b >= a for a, b in pairwise(burst)), "爆发段不单调"
    fall = [anim.sneeze_amount(s0 + anim.SNEEZE_SETTLE_S * i / 20) for i in range(21)]
    assert all(b <= a for a, b in pairwise(fall)), "松回段不单调"


def test_note_sneeze_first_one_waits_a_gap():
    """刚能打：先等一个（随机）间隔再打第一个 —— 立刻打那是反射弧太短。"""
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.note_sneeze(T0, True)
    assert a._sneeze_at == -99.0, "刚醒就立刻打喷嚏，像被掐了一下"
    assert a._sneeze_next_at is not None
    first = a._sneeze_next_at
    assert T0 + anim.SNEEZE_MIN_GAP <= first <= T0 + anim.SNEEZE_MAX_GAP
    a.note_sneeze(first - 0.5, True)
    assert a._sneeze_at == -99.0, "还没到点就打了"
    a.note_sneeze(first, True)
    assert a._sneeze_at == first, "到点了没打"
    nxt = a._sneeze_next_at
    assert nxt is not None and first + anim.SNEEZE_MIN_GAP <= nxt <= first + anim.SNEEZE_MAX_GAP, (
        "打完没接着排下一个"
    )


def test_note_sneeze_gap_is_randomized_not_a_metronome():
    """一直醒着：间隔全落在窗口里，而且不止一个值 —— 别像节拍器。"""
    a = Animator(seed=9)
    a.note_sneeze(0.0, True)
    times = []
    for _ in range(60):
        t = a._sneeze_next_at
        a.note_sneeze(t, True)
        times.append(t)
    assert a._sneeze_at == times[-1]
    gaps = [b - p for p, b in pairwise(times)]
    assert all(anim.SNEEZE_MIN_GAP <= g <= anim.SNEEZE_MAX_GAP for g in gaps), gaps
    assert len(set(gaps)) >= 3, "间隔全一个样 —— 成节拍器了"


def test_note_sneeze_off_clears_pending_schedule():
    """不能打了（睡着 / 被拎起来）：排期清掉；之后不再打新的。"""
    c = Animator(seed=13)
    c.note_sneeze(T0, True)
    assert c._sneeze_next_at is not None
    c.note_sneeze(T0 + 1.0, False)
    assert c._sneeze_next_at is None, "不能打了排期还留着"
    for i in range(120):
        c.note_sneeze(T0 + 2.0 + i, False)
    assert c._sneeze_at == -99.0, "说不能打了还打了一个"


def test_gate_off_feeds_never_leak():
    """怎么喂「不能打」都和什么都不喂的孪生逐帧全等（400 步）—— 闸门关彻底。"""
    a, b = Animator(seed=31), Animator(seed=31)
    for i in range(1, 401):
        t = round(i * 0.033, 6)
        a.note_sneeze(t, False)
        assert a.frame_at(t) == b.frame_at(t), f"{t} 闸门关着还漏出动作"


def test_one_in_flight_sneeze_finishes_after_gate_off():
    """正在打的这个让它打完：'不能打了'只清排期，不掐当前 —— 半路掐掉像噎住。"""
    a, b = Animator(seed=11), Animator(seed=11)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.sneeze(T0)
    a.note_sneeze(T0 + 0.3, False)  # 打到一半「睡着」了
    for tau in (0.2, 0.35, 0.55):
        t = round(T0 + tau, 6)
        assert a.frame_at(t) != b.frame_at(t), f"{t}：排着的那个被'不能打'掐掉了？"
    end = round(T0 + anim.sneeze_total() + 0.3, 6)
    assert a.frame_at(end) == b.frame_at(end), "收完没回到常态"


def test_sneeze_only_adds_other_channels_do_not_move():
    """只打喷嚏的一方与完全没打的孪生：别的通道一个都不许动；窗外全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.sneeze(T0)
    live = 0
    end = T0 + anim.sneeze_total()
    for i in range(1, 161):
        t = round(T0 + i * 0.025, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (fa.pop, fa.gx, fa.gy, fa.stretch, fa.talk_y, fa.talk_sq) == (
            fb.pop,
            fb.gx,
            fb.gy,
            fb.stretch,
            fb.talk_y,
            fb.talk_sq,
        ), f"{t} 时别的通道被喷嚏带偏了"
        if t < end:
            if (fa.squash, fa.dy, fa.dx) != (fb.squash, fb.dy, fb.dx):
                live += 1
        else:
            assert (fa.squash, fa.dy, fa.dx) == (fb.squash, fb.dy, fb.dx), (
                f"{t} 收完之后还没回到常态"
            )
    assert live >= 15, f"窗口里只有 {live} 帧真的变了 —— 喷嚏没打起来"


def test_sneeze_matches_formula_point_by_point():
    """整段逐点对账（0.02 秒网格）：三个通道按公式对齐到每个采样点。"""
    a = Animator(seed=11)
    _walk(a, 0.0, T0)
    a.sneeze(T0)
    d = a._sneeze_dir
    live = 0
    for i in range(36):
        t = round(T0 + i * 0.02, 6)
        k = anim.sneeze_amount(t - T0)
        f = a.frame_at(t)
        assert f.squash == pytest.approx(
            min(_blink_squash(a, t), 1.0 - (1.0 - anim.SNEEZE_SQUINT_MIN) * k)
        ), t
        assert f.dy == round(
            anim.BREATH_AMPLITUDE * math.sin(2 * math.pi * t / anim.BREATH_PERIOD)
        ) - round(anim.SNEEZE_LIFT_PX * k), t
        assert f.dx == round(
            anim.SWAY_AMPLITUDE * math.sin(2 * math.pi * t / anim.SWAY_PERIOD)
        ) + d * round(anim.SNEEZE_JERK_PX * k), t
        if k > 0:
            live += 1
    assert live >= 24, f"窗口里只有 {live} 帧在动"


def test_sneeze_and_nod_compose_without_overreach():
    """喷嚏碰上点头（又困又呛）：压扁取更狠、下沉与上窜相抵 —— 组合也不出格。"""
    a, c = Animator(seed=25), Animator(seed=25)
    _walk(a, 0.0, T0)
    _walk(c, 0.0, T0)
    a.sneeze(T0)
    a.nod(T0)
    c.nod(T0)
    d = a._sneeze_dir
    for i in range(1, 60):
        t = round(T0 + i * 0.02, 6)
        ks = anim.sneeze_amount(t - T0)
        kn = anim.nod_amount(t - T0)
        f = a.frame_at(t)
        exp_sq = min(
            _blink_squash(a, t),
            1.0 - (1.0 - anim.NOD_SQUINT_MIN) * kn,
            1.0 - (1.0 - anim.SNEEZE_SQUINT_MIN) * ks,
        )
        assert f.squash == pytest.approx(exp_sq), t
        assert f.dy == round(
            anim.BREATH_AMPLITUDE * math.sin(2 * math.pi * t / anim.BREATH_PERIOD)
        ) + round(anim.NOD_SINK_PX * kn) - round(anim.SNEEZE_LIFT_PX * ks), t
        fc = c.frame_at(t)
        assert f.squash <= fc.squash + 1e-9, t
        assert f.dx - fc.dx == d * round(anim.SNEEZE_JERK_PX * ks), t


def test_sneeze_is_suppressed_when_calm_and_resumes_after():
    """睡着不打喷嚏（定格优先）；醒来接着打（不是半路掐掉重来）。"""
    a, b = Animator(seed=15), Animator(seed=15)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.sneeze(T0)
    for i in range(1, 20):
        t = round(T0 + i * 0.05, 6)
        fa = a.frame_at(t, calm=True)
        fb = b.frame_at(t, calm=True)
        assert (fa.squash, fa.dy, fa.dx) == (fb.squash, fb.dy, fb.dx), f"{t} 睡着时喷嚏漏出来了"
    mid = round(T0 + anim.SNEEZE_WINDUP_S + anim.SNEEZE_BURST_S + anim.SNEEZE_HOLD_S * 0.5, 6)
    assert a.frame_at(mid) != b.frame_at(mid), "醒来没接着打（被 calm 掐了）"


def test_sneeze_restart_starts_fresh():
    """中途再排一次：从皱脸重新起步 —— 与「只在这一刻开始」的孪生全等。"""
    a, d0 = Animator(seed=17), Animator(seed=17)
    _walk(a, 0.0, T0)
    _walk(d0, 0.0, T0)
    a.sneeze(T0)
    assert a.frame_at(T0 + 0.3) != d0.frame_at(T0 + 0.3), "前提不成立：a 没有在打"
    t2 = T0 + 0.5
    a.sneeze(t2)
    d0.sneeze(t2)
    d0._sneeze_dir = a._sneeze_dir  # 方向是每 call 一换的内部状态：比形状前先对齐
    for tau in (0.0, 0.05, 0.2, 0.35, 0.5, 0.7, 1.0):
        t = round(t2 + tau, 6)
        assert a.frame_at(t) == d0.frame_at(t), f"{t} 重开后没有从头起步"


def test_sneeze_direction_alternates_without_touching_rng():
    """方向一次一换、且不占随机流（同种子的孪生连眨眼 / 凝视时间表都一致）。"""
    e, f = Animator(seed=21), Animator(seed=21)
    _walk(e, 0.0, T0)
    _walk(f, 0.0, T0)
    e.sneeze(T0)
    assert e._sneeze_dir == -1, "第一下应该往左（初始 +1 取反）"
    peak1 = round(T0 + anim.SNEEZE_WINDUP_S + anim.SNEEZE_BURST_S + anim.SNEEZE_HOLD_S / 2, 6)
    assert e.frame_at(peak1).dx - f.frame_at(peak1).dx == -2
    e.sneeze(T0 + 2.0)  # 第二下：再来一次从皱脸重新起步，方向换边
    assert e._sneeze_dir == 1, "第二下换边"
    peak2 = round(T0 + 2.0 + anim.SNEEZE_WINDUP_S + anim.SNEEZE_BURST_S + anim.SNEEZE_HOLD_S / 2, 6)
    assert e.frame_at(peak2).dx - f.frame_at(peak2).dx == 2
    assert e.blink_times(120.0) == f.blink_times(120.0), "方向切换动了随机流"
    assert e.gaze_times(120.0) == f.gaze_times(120.0), "方向切换动了随机流"


def test_sneeze_reset_clears_state():
    """时间线被拨动（reset）：旧的那个不作数、排期也清掉。"""
    a, b = Animator(seed=19), Animator(seed=19)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.sneeze(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.05, 0.2, 0.35, 0.6):
        t = round(T0 + 0.2 + tau, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} reset 之后旧喷嚏还在"
    c = Animator(seed=23)
    c.note_sneeze(T0, True)
    assert c._sneeze_next_at is not None
    c.sneeze(T0 + 1.0)
    c.reset(T0 + 2.0)
    assert c._sneeze_at == -99.0
    assert c._sneeze_next_at is None, "reset 后旧排期还留着"


def test_sneeze_is_deterministic():
    """同一条序列跑两遍逐值相等（种子相同 = 演出相同）。"""

    def run():
        a = Animator(seed=29)
        out = []
        for i in range(1, 161):
            t = round(i * 0.05, 6)
            if i == 40:
                a.sneeze(t)
            if i == 60:
                a.note_sneeze(t, True)
            f = a.frame_at(t)
            out.append((round(f.squash, 12), f.dy, f.dx, round(f.stretch, 12), f.gx, f.gy))
        return out

    assert run() == run()


def test_geometry_guard_covers_the_sneeze_channel():
    """全局几何预算守卫（test_yawn）必须把喷嚏通道算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "anim.SNEEZE_SQUINT_MIN" in text and "anim.SNEEZE_LIFT_PX" in text, (
        "test_yawn 的全局预算守卫里没有喷嚏的压扁 / 上窜通道 —— 调大 SNEEZE_* 就没人拦了"
    )
    assert "anim.SNEEZE_JERK_PX" in text, "test_yawn 的全局预算守卫里没有喷嚏的横向哆嗦"


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import SammyWindow  # noqa: E402

SEED_SNEEZE = 7


def _mk(scale: float = 1.0) -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留喷嚏这一个变量。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = scale
    w._offset = (0, 0)
    w.resize(round(800 * scale), round(480 * scale))
    w._relayout()
    # 眨眼和喷嚏共用同一条 squash 通道（min 取更狠的）：量的那一刻撞上眨眼，
    # 喷嚏的压扁会被盖掉。量几何时先把眨眼请出去；眨眼自己有 test_anim 管。
    w.anim = anim.Animator(seed=SEED_SNEEZE, blink_gap=(600.0, 600.0))
    w.look_on = False  # 光标不参与（盯的是喷嚏这一件事）
    w.set_expression(2)  # 普通脸
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    return w


def _img_bytes(w: SammyWindow) -> bytes:
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(img.constBits())


def _lit_bbox(w: SammyWindow, clip: QRect) -> tuple[int, int, int, int]:
    """clip 里的「不透明亮像素」外接框（判据与 test_nod 同一套）。"""
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


def test_sneeze_shuts_eyes_and_shrinks_the_face(qapp):
    """scale 1.0 双胞胎：爆发帧用力闭眼缩进去、酝酿段只是皱起来、收完逐字节归零。"""
    a, b = _mk(), _mk()
    try:
        a.anim.sneeze(8.5)
        box = a.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)

        def look(w: SammyWindow, t: float):
            w.anim_t = t
            return _lit_bbox(w, clip)

        peak = round(8.5 + anim.SNEEZE_WINDUP_S + anim.SNEEZE_BURST_S + anim.SNEEZE_HOLD_S * 0.5, 6)
        x0a, y0a, x1a, y1a = look(a, peak)
        x0b, y0b, x1b, y1b = look(b, peak)
        h_a, h_b = y1a - y0a, y1b - y0b
        assert h_a <= h_b * 0.30, f"爆发帧没缩下去：{h_a} vs {h_b}"
        assert h_a >= h_b * 0.05, f"缩得只剩 {h_a}px，全没了？"
        assert y0a - y0b >= 45, f"顶沿没收进来：{y0a - y0b}px"
        assert y1b - y1a >= 45, f"下沿没收进来：{y1b - y1a}px"
        assert abs((x1a - x0a) - (x1b - x0b)) <= 4, "喷嚏不该明显动宽度"
        wind = round(8.5 + anim.SNEEZE_WINDUP_S * 0.5, 6)
        _, w0a, _, w1a = look(a, wind)
        _, w0b, _, w1b = look(b, wind)
        ratio = (w1a - w0a) / (w1b - w0b)
        assert 0.6 <= ratio <= 0.95, f"酝酿段该只是「皱起来」，实测 {ratio:.2f}"
        after = round(8.5 + anim.sneeze_total() + 0.4, 6)
        a.anim_t = after
        b.anim_t = after
        assert _img_bytes(a) == _img_bytes(b), "喷嚏收完还不回到常态"
    finally:
        a.close()
        b.close()


def test_sneeze_key_moment_stays_inside_the_repainted_region(qapp):
    """爆发帧必须落在局部重绘区里 —— 在外面那圈不刷新（脸会花）。"""
    w = _mk()
    try:
        w.anim.sneeze(8.5)
        box = w.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)
        region = w._face_region()
        w.anim_t = round(
            8.5 + anim.SNEEZE_WINDUP_S + anim.SNEEZE_BURST_S + anim.SNEEZE_HOLD_S * 0.5, 6
        )
        x0, y0, x1, y1 = _lit_bbox(w, clip)
        deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        assert region.contains(deformed), f"爆发时脸 {deformed} 冒出重绘区 {region}"
    finally:
        w.close()


# ── 链路：窗口把「可以呛一下」喂给动画层 ───────────────


def test_window_schedules_and_fires_sneezes(qapp):
    """醒着、没被拎着：先排、到点打、打完接着排 —— 一路都在窗口这一层。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0  # 冻结驱力漂移（边界用例的老规矩）
        w.anim_t = 50.0
        w._tick()
        first = w.anim._sneeze_next_at
        assert first is not None, "醒着却没排喷嚏"
        assert 50.0 + anim.SNEEZE_MIN_GAP <= first <= 50.0 + anim.SNEEZE_MAX_GAP
        assert w.anim._sneeze_at == -99.0, "排期不该当场就打"
        w.anim_t = round(first - 0.2, 6)
        w._tick()
        assert w.anim._sneeze_at == -99.0, "还没到点就打了"
        w.anim_t = first
        w._tick()
        assert w.anim._sneeze_at == first, "到点了没打"
        nxt = w.anim._sneeze_next_at
        assert nxt is not None and nxt >= first + anim.SNEEZE_MIN_GAP, "打完没接着排"
        w.anim_t = nxt
        w._tick()
        assert w.anim._sneeze_at == nxt, "第二个没来"
    finally:
        w.close()


def test_window_gates_asleep_and_carried(qapp):
    """两道闸门：睡着不排（梦里的抽动是另一条通道）；被拎着不排（搬运在管那段）。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.anim_t = 30.0
        w._tick()
        assert w.anim._sneeze_next_at is not None, "醒着没被拎着却不排"
        w.drives.asleep = True
        w.anim_t = 31.0
        w._tick()
        assert w.anim._sneeze_next_at is None, "睡着还排喷嚏"
        w.drives.asleep = False
        w._drag = QPoint(1, 1)
        w.anim_t = 32.0
        w._tick()
        assert w.anim._sneeze_next_at is None, "被拎着还排喷嚏"
        w._drag = None
        w.anim_t = 33.0
        w._tick()
        assert w.anim._sneeze_next_at is not None, "放下了还不排"
    finally:
        w.close()


def test_window_is_silent_when_anim_off_or_thinking(qapp):
    """动画关 / 思考中：都不排 —— 关就该关彻底。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.anim_on = False
        w.anim_t = 40.0
        w._tick()
        assert w.anim._sneeze_next_at is None, "动画关着还排喷嚏"
        w.anim_on = True
        w.thinking = True
        w.anim_t = 41.0
        w._tick()
        assert w.anim._sneeze_next_at is None, "思考中还排喷嚏"
        w.thinking = False
        w.anim_t = 42.0
        w._tick()
        assert w.anim._sneeze_next_at is not None, "都恢复了还不排"
    finally:
        w.close()


# ── 纪律与素材 ────────────────────────────────────


def test_sneeze_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "sneeze_preview.py").is_file()
    assert "sneeze-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("sneeze-strip.png", "sneeze-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
