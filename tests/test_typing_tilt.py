"""好奇歪头（自选小步·第十八次）——「你在写什么呀」。

动机：歪头（第十七次）先挂上戳一戳 ——「被戳了（唔？）」；可「看着你写」
（第十一次）那一整段里，脸从视线收下去到停手收回来全程一动不动。一个真
的活物在你埋头写字时会好奇：写起来了就隔一会儿歪一下脑袋（你在写什么
呀），停半秒再直回去，接着看你写。这一条把一段注视变成一段有身体语言
的陪伴；旋转语汇（±5 度、绕脸中心、最近邻取样）原样复用 —— 不新增形状、
不新增几何预算（旋转已经折进 FACE_REGION_PAD）。

两块机制：
- 排期：写起来了 → 第一下在 TYPING_TILT_FIRST_MIN_S 到 FIRST_MAX_S 秒之间
  （先看清你在写，不是一敲字就弹）；一直写就一直排，两下之间隔 MIN_GAP 到
  MAX_GAP 秒随机 —— 别像节拍器；手停下来（TYPING_HOLD_S 到点）排期作废，
  下一段重头起算。
- 让位：光标（手在指东西）优先 —— 刚指过的那一眼先看够，歪头一起让位；
  睡着 / 动画关在窗口那层就不喂（和打字凝视同一条闸门）。

一条纪律：排期抽数走**它自己的随机流**（_rng_tilt）。写字的时刻表由外部
事件驱动，要是从主随机流里抽数，「写完字之后」的眨眼 / 凝视时刻表就和
没写过字的孪生对不上 —— 老金色基线会静默漂移（这个仓库把这类问题当
bug 类处理）。有专门用例钉着这条。

四层判据（和 test_tilt 与 test_hum 一个框架）：
1. 纯函数：第一下不抢拍、节奏在区间里且随机、停手清排期、新会话重排、
   光标让位、睡着不补、reset 清态、确定性、不动主随机流；
2. 窗口链路：真信号链（setText → textChanged → _on_typing）真的引出歪头，
   歪的时候还在看你写；发送清排期；睡着 / 动画关不歪、醒来恢复；
3. 渲染（真窗口离屏双胞胎）：写作中真脸绕中心转（主轴角方向对、量级对），
   改动的像素全部落在重绘区里，收完回正；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：TYPING_TILT_ 开头的常量在 anim.py 顶部；调参速查表第 28 节。）
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

T0 = 30.0  # 热身后的时刻（初始凝视和眨眼早已跑起来）


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet 与 test_typing 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


def _fires(a: Animator, t0: float, t1: float, step: float = 0.05, notes=()) -> list[float]:
    """走一遍时间轴，收集每一次「排上歪头」的时刻（_tilt_at 的变化点）。

    notes = 在哪些时刻喂一次 note_typing（保持「在写」的状态）。
    """
    marks = {round(n, 6) for n in notes}
    fires: list[float] = []
    last = a._tilt_at
    for i in range(round((t1 - t0) / step) + 1):
        t = round(t0 + i * step, 6)
        if t in marks:
            a.note_typing(t)
        a.frame_at(t)
        if a._tilt_at != last:
            fires.append(a._tilt_at)
            last = a._tilt_at
    return fires


def _walk(a: Animator, t0: float, t1: float, step: float = 0.05, feed=None):
    """走时间轴，返回 [(t, frame)]；feed = {t: 回调}，在那一帧之前触发。"""
    n = round((t1 - t0) / step)
    out = []
    for i in range(n + 1):
        t = round(t0 + i * step, 6)
        if feed and t in feed:
            feed[t](t)
        out.append((t, a.frame_at(t)))
    return out


# ── 纯函数层：排期与让位 ──────────────────────────


def test_typing_tilt_constants_stay_gentle():
    """数字先像样：第一下要让「写起来」先被看清（不抢拍、也别久到看不见）。"""
    assert 1.0 <= anim.TYPING_TILT_FIRST_MIN_S <= anim.TYPING_TILT_FIRST_MAX_S <= 4.0
    assert anim.TYPING_TILT_FIRST_MAX_S < anim.TYPING_TILT_MIN_GAP
    assert 8.0 <= anim.TYPING_TILT_MIN_GAP < anim.TYPING_TILT_MAX_GAP <= 40.0


def test_first_tilt_waits_for_the_session_to_settle():
    """写起来 → 第一下等一个短窗口：不早于 MIN、也不晚于 MAX 这两头。"""
    a = Animator(seed=7)
    a.note_typing(0.5)
    a.frame_at(0.5)  # 第一帧：排期武装
    nxt = a._typing_tilt_next_at
    lo = round(0.5 + anim.TYPING_TILT_FIRST_MIN_S, 6)
    hi = round(0.5 + anim.TYPING_TILT_FIRST_MAX_S, 6)
    assert nxt is not None and lo <= nxt <= hi, nxt
    fire = None
    for i in range(1, 240):  # 0.5 .. 12.5
        t = round(0.5 + i * 0.05, 6)
        a.frame_at(t)
        if a._tilt_at != -99.0:
            fire = a._tilt_at
            break
    assert fire is not None, "写起来了，第一下一直没来"
    assert lo - 1e-9 <= fire <= hi + 0.06, fire
    full = a.frame_at(round(fire + anim.TILT_RISE_S + 0.05, 6))
    assert full.tilt == -anim.TILT_MAX_DEG, "第一下该左半边沉（和戳一戳同一个方向规矩）"


def test_long_session_keeps_rhythm_between_gaps():
    """一直写：后面的每一下都落在 [MIN_GAP, MAX_GAP] 里。"""
    a = Animator(seed=11)
    notes = [round(0.5 + 0.5 * k, 6) for k in range(0, 201)]
    fires = _fires(a, 0.0, 101.0, notes=notes)
    assert len(fires) >= 4, f"100 秒的连续写字只歪了 {len(fires)} 下"
    lo = 0.5 + anim.TYPING_TILT_FIRST_MIN_S
    hi = 0.5 + anim.TYPING_TILT_FIRST_MAX_S
    assert lo - 1e-9 <= fires[0] <= hi + 0.06
    for f0, f1 in pairwise(fires):
        gap = f1 - f0
        assert anim.TYPING_TILT_MIN_GAP - 1e-9 <= gap <= anim.TYPING_TILT_MAX_GAP + 0.06, gap


def test_directions_alternate_across_fires():
    """方向一次一换（和戳一戳共享同一条交替规矩）—— 不掷随机数。"""
    a = Animator(seed=11)
    marks = {round(0.5 + 0.5 * k, 6) for k in range(0, 121)}
    dirs: list[int] = []
    last = a._tilt_at
    for i in range(0, 1211):  # 0 .. 60.5
        t = round(i * 0.05, 6)
        if t in marks:
            a.note_typing(t)
        a.frame_at(t)
        if a._tilt_at != last:
            dirs.append(a._tilt_dir)
            last = a._tilt_at
    assert len(dirs) >= 2, f"前提不成立：只歪了 {len(dirs)} 下"
    for d0, d1 in pairwise(dirs):
        assert d1 == -d0, f"方向没有一次一换：{dirs}"


def test_gaps_are_randomized_not_a_metronome():
    """同样喂法、不同种子：第一下等待与后续间隔都不该一模一样（别像节拍器）。"""

    def run(seed: int):
        a = Animator(seed=seed)
        marks = {round(0.5 + 0.5 * k, 6) for k in range(0, 81)}
        fires: list[float] = []
        last = a._tilt_at
        for i in range(0, 1011):  # 0 .. 50.5
            t = round(i * 0.05, 6)
            if t in marks:
                a.note_typing(t)
            a.frame_at(t)
            if a._tilt_at != last:
                fires.append(a._tilt_at)
                last = a._tilt_at
        return fires[0] - 0.5, [round(b - x, 3) for x, b in pairwise(fires)]

    runs = [run(s) for s in (7, 11, 23)]
    assert len({round(r[0], 3) for r in runs}) > 1, "第一下的等待像节拍器"
    gaps = [g for r in runs for g in r[1]]
    assert len(gaps) >= 2 and len(set(gaps)) > 1, "间隔像节拍器"


def test_stopping_clears_the_schedule_and_spares_the_future():
    """停手：排期作废（下一段重头起算）；之后 40 秒一下都不许再歪。"""
    a = Animator(seed=7)
    a.note_typing(0.5)
    fires = _fires(a, 0.0, 7.0)
    assert len(fires) == 1, f"一段很短的字，歪了 {len(fires)} 下"
    assert a._typing_tilt_next_at is None, "停手了排期还留着"
    for i in range(141, 941):  # 7.0 .. 47.0
        t = round(i * 0.05, 6)
        a.frame_at(t)
        assert a._tilt_at == fires[0], f"t={t} 停手之后又歪了"


def test_new_session_rearms_and_flips_direction():
    """新一段重头起算：再写起来 → 还会歪，方向接着换边。"""
    a = Animator(seed=13)
    fires: list[float] = []
    dirs: list[int] = []
    last = a._tilt_at
    for i in range(0, 241):  # 0 .. 12.0
        t = round(i * 0.05, 6)
        if t in (0.5, 8.0):
            a.note_typing(t)
        a.frame_at(t)
        if a._tilt_at != last:
            fires.append(a._tilt_at)
            dirs.append(a._tilt_dir)
            last = a._tilt_at
    assert len(fires) == 2, f"两段字，只歪了 {len(fires)} 下"
    assert dirs == [-1, 1], f"方向没接着换边：{dirs}"
    lo = 8.0 + anim.TYPING_TILT_FIRST_MIN_S
    hi = 8.0 + anim.TYPING_TILT_FIRST_MAX_S
    assert lo - 1e-9 <= fires[1] <= hi + 0.06


def test_nothing_fed_no_tilt_ever():
    """没写字就是没写字：喂光标也不行 —— 40 秒里一下都不歪。"""
    a = Animator(seed=7)
    for i in range(0, 801):
        t = round(i * 0.05, 6)
        if i == 100:
            a.note_cursor(-150.0, 0.0, t)
            a.note_cursor(-170.0, 0.0, t)
        a.frame_at(t)
    assert a._tilt_at == -99.0, "没写字也歪了"
    assert a._typing_tilt_next_at is None


def test_cursor_takes_priority_then_the_tilt_fires_late():
    """手刚指过：那一眼先看够 —— 到点的歪头跟着让位；让完照歪。"""
    a, b = Animator(seed=7), Animator(seed=7)
    a.note_typing(0.5)
    b.note_typing(0.5)
    _walk(a, 0.0, 0.6)
    _walk(b, 0.0, 0.6)
    nxt = a._typing_tilt_next_at
    assert nxt is not None and nxt == b._typing_tilt_next_at
    tc = round(nxt - 0.3, 6)
    a.note_cursor(150.0, 0.0, tc)
    a.note_cursor(170.0, 0.0, tc)  # 两次合起来 = 一次真的「在动」
    blocked_end = round(tc + anim.LOOK_HOLD_S, 6)
    fa_fires: list[float] = []
    fb_fires: list[float] = []
    last_a = a._tilt_at
    last_b = b._tilt_at
    marks = {round(tc + dt, 6) for dt in (1.0, 2.0, 3.0, 4.0, 5.0)}
    for i in range(0, 141):  # tc .. tc + 7.0
        t = round(tc + i * 0.05, 6)
        if t in marks:
            a.note_typing(t)
            b.note_typing(t)
        a.frame_at(t)
        b.frame_at(t)
        if a._tilt_at != last_a:
            fa_fires.append(a._tilt_at)
            last_a = a._tilt_at
            assert a._tilt_at >= blocked_end - 1e-9, f"t={t} 光标还没过期就歪了"
        if b._tilt_at != last_b:
            fb_fires.append(b._tilt_at)
            last_b = b._tilt_at
    assert len(fb_fires) == 1, f"对照没按时歪（{fb_fires}）"
    assert fb_fires[0] <= nxt + 0.051, "对照歪得偏晚"
    assert len(fa_fires) == 1, f"主角歪的数目不对（{fa_fires}）"
    assert fa_fires[0] - fb_fires[0] >= 2.1, "只让了一点点（那一眼没看够）"


def test_calm_is_silent_and_wakes_clean():
    """睡着：不排也不歪（与没喂过的孪生逐帧全等）；醒来那笔早过期的账不许补。"""
    a = Animator(seed=11, blink_gap=(600.0, 600.0))
    b = Animator(seed=11, blink_gap=(600.0, 600.0))
    a.note_typing(0.5)  # 只喂 a：睡着这一段，喂与不喂必须长得一样
    for i in range(0, 171):  # 0.5 .. 9.0
        t = round(0.5 + i * 0.05, 6)
        assert a.frame_at(t, calm=True) == b.frame_at(t, calm=True), f"t={t} 睡着时漏出来了"
    assert a._typing_tilt_next_at is None, "睡着期间不该武装排期"
    for i in range(1, 41):  # 9.0 .. 11.0：醒来走一段
        t = round(9.0 + i * 0.05, 6)
        a.frame_at(t)
    assert a._tilt_at == -99.0, "醒来补歪了（那一笔早过期了）"
    assert a._typing_tilt_next_at is None


def test_schedule_keeps_its_own_random_stream():
    """排期只花自己的随机流：写着字的它不该把眨眼 / 凝视的时刻表抽动分毫。

    两跑对账：一跑排期正常（真的歪、也抽数武装），一跑把排期摁住（不许
    武装也不许响）—— 眨眼与凝视的时刻表必须逐位相同。要是哪天有人改成从
    主随机流抽数，写完字之后所有人的眨眼 / 凝视都会静默漂移，这条会红。
    """

    def run(suppress: bool):
        a = Animator(seed=7)
        marks = {round(0.5 + 0.5 * k, 6) for k in range(0, 241)}
        fires = 0
        last = a._tilt_at
        for i in range(0, 2421):  # 0 .. 121 秒
            t = round(i * 0.05, 6)
            if suppress:
                a._typing_tilt_next_at = 10**9  # 摁住：武装与响都不发生
            if t in marks:
                a.note_typing(t)
            a.frame_at(t)
            if a._tilt_at != last:
                fires += 1
                last = a._tilt_at
        return a.blink_times(600.0), a.gaze_times(600.0), fires

    b1, g1, fires = run(False)
    b2, g2, _ = run(True)
    assert fires >= 3, f"前提不成立：正常跑只歪了 {fires} 下"
    assert b1 == b2, "排期动了眨眼随机流"
    assert g1 == g2, "排期动了凝视随机流"


def test_session_only_moves_gaze_and_tilt():
    """双胞胎对账：写字会话里只许动「看哪儿」和「歪头」；收完之后歪头回零。"""
    a = Animator(seed=7, blink_gap=(600.0, 600.0))
    b = Animator(seed=7, blink_gap=(600.0, 600.0))
    a.note_typing(0.5)
    live = 0
    for i in range(0, 281):  # 0.5 .. 7.5
        t = round(0.5 + i * 0.025, 6)
        if t in (3.5, 6.0):
            a.note_typing(t)
        fa, fb = a.frame_at(t), b.frame_at(t)
        for k in ("squash", "dx", "dy", "pop", "talk_y", "talk_sq"):
            assert getattr(fa, k) == getattr(fb, k), f"t={t} 的 {k} 被写字会话动了"
        if fa.tilt != fb.tilt:
            live += 1
    assert live >= 40, f"整段会话只有 {live} 帧真的歪着"
    for i in range(0, 71):  # 10.5 .. 14.0：会话结束、最后一下收完
        t = round(10.5 + i * 0.05, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert fa.tilt == fb.tilt == 0.0, f"t={t} 会话结束后歪头没收干净"


def test_reset_clears_the_schedule():
    """时间线被拨动（reset）：旧排期不作数，之后和孪生逐帧重合。"""
    a, b = Animator(seed=19), Animator(seed=19)
    a.note_typing(T0)
    b.note_typing(T0)
    _walk(a, 0.0, T0 + 0.05)
    _walk(b, 0.0, T0 + 0.05)
    assert a._typing_tilt_next_at is not None and b._typing_tilt_next_at is not None
    assert a._typing_tilt_next_at == b._typing_tilt_next_at, "同种子同喂法排期却不同"
    a.reset(T0 + 1.0)
    b.reset(T0 + 1.0)
    assert a._typing_tilt_next_at is None, "reset 之后旧排期还留着"
    assert b._typing_tilt_next_at is None
    fires = 0
    last = a._tilt_at
    for i in range(0, 801):  # T0+1 .. T0+41：40 秒
        t = round(T0 + 1.0 + i * 0.05, 6)
        fa = a.frame_at(t)
        fb = b.frame_at(t)
        assert fa == fb, f"t={t} reset 之后两边对不上"
        if a._tilt_at != last:
            fires += 1
            last = a._tilt_at
    assert fires == 0 and a._tilt_at == -99.0


def test_typing_tilt_is_deterministic():
    """同种子、同喂法两遍：歪头时刻表与各帧逐值相等。"""

    def run():
        a = Animator(seed=29)
        fires: list[float] = []
        last = a._tilt_at
        out = []
        for i in range(0, 241):  # 0 .. 12.0
            t = round(i * 0.05, 6)
            if t in (0.5, 3.5):
                a.note_typing(t)
            f = a.frame_at(t)
            if a._tilt_at != last:
                fires.append(a._tilt_at)
                last = a._tilt_at
            out.append((round(f.tilt, 12), f.dy, f.dx, round(f.squash, 12)))
        return fires, out

    assert run() == run()


# ── 窗口链路：真信号链 ─────────────────────────────
# （setText → textChanged → _on_typing → note_typing → 排期；闸门在窗口这一层。）

from sammy.pet import SammyWindow  # noqa: E402

SEED_TT = 7


def _mkwin() -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留「有没有在写字」这一个变量。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    w.anim = anim.Animator(seed=SEED_TT, blink_gap=(600.0, 600.0))
    w.set_expression(2)  # 普通脸：画面里动的只有脸
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    w.look_on = False  # 光标不参与（盯的是写字这一件事）
    return w


def _step(w: SammyWindow):
    """推进一帧并把这一帧算出来（离屏没有事件循环，paint 不会自己跑）。"""
    w._anim_tick()
    return w.anim.frame_at(w.anim_t)


def test_window_settext_raises_a_tilt_while_still_watching(qapp):
    """真信号链：往输入框里写字 → 过一小会它好奇地歪一下（且还在看你写）。"""
    w = _mkwin()
    try:
        w.input.setText("你好")  # textChanged → _on_typing → note_typing(8.0)
        assert w.anim._typing_at == 8.0, "敲字没喂给动画层"
        fire = None
        for _ in range(180):  # ~6 秒
            _step(w)
            if w.anim._tilt_at != -99.0:
                fire = w.anim._tilt_at
                break
        assert fire is not None, "写起来了，歪头一直没来"
        lo = 8.0 + anim.TYPING_TILT_FIRST_MIN_S
        hi = 8.0 + anim.TYPING_TILT_FIRST_MAX_S
        assert lo - 1e-9 <= fire <= hi + 0.05, fire
        full = w.anim.frame_at(round(fire + anim.TILT_RISE_S + 0.05, 6))
        assert full.tilt == -anim.TILT_MAX_DEG, "写起来的第一下该左半边沉"
        assert full.gy == anim.TYPING_GAZE_Y, "歪的时候不在看你写（视线不在输入框）"
        fires = 1
        last = w.anim._tilt_at
        for _ in range(300):  # 再走 ~10 秒：停手之后不许再有第二下
            _step(w)
            if w.anim._tilt_at != last:
                fires += 1
                last = w.anim._tilt_at
        assert fires == 1, f"停手之后又歪了（共 {fires} 下）"
        assert w.anim._typing_tilt_next_at is None, "停手了排期还留着"
    finally:
        w.close()


def test_window_gates_asleep_and_anim_off(qapp):
    """睡着 / 动画关：怎么写字都不歪（窗口那层就不喂）；恢复了照旧。"""
    w = _mkwin()
    try:
        w.drives.asleep = True
        w.input.setText("睡")
        for _ in range(300):  # ~10 秒
            _step(w)
        assert w.anim._tilt_at == -99.0, "睡着时歪了"
        assert w.anim._typing_tilt_next_at is None
        w.drives.asleep = False
        w.anim_on = False
        w.input.setText("关")
        for _ in range(180):  # ~6 秒
            _step(w)
        assert w.anim._tilt_at == -99.0, "动画关着还歪"
        w.anim_on = True
        w.input.setText("醒")
        t_feed = w.anim_t
        fire = None
        for _ in range(200):
            _step(w)
            if w.anim._tilt_at != -99.0:
                fire = w.anim._tilt_at
                break
        assert fire is not None, "都恢复了还不歪"
        lo = t_feed + anim.TYPING_TILT_FIRST_MIN_S
        hi = t_feed + anim.TYPING_TILT_FIRST_MAX_S
        assert lo - 1e-9 <= fire <= hi + 0.06, (fire, t_feed)
    finally:
        w.close()


def test_window_sending_clears_the_schedule(qapp):
    """按发送 = 这句交出去了：排期立刻作废（不许在「想事情」的时候补歪一下）。"""
    w = _mkwin()
    try:
        w.input.setText("你好")
        for _ in range(30):  # ~1 秒：排期武装了但还不该响
            _step(w)
        assert w.anim._typing_tilt_next_at is not None, "前提不成立：排期没武装"
        w.send()  # 发送（没接大脑会降级，但「写完了」这条路照走）
        _step(w)
        assert w.anim._typing_tilt_next_at is None, "发送了排期还留着"
        for _ in range(120):  # 再走 ~4 秒
            _step(w)
        assert w.anim._tilt_at == -99.0, "发送之后补歪了"
    finally:
        w.close()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtGui import QImage  # noqa: E402

from sammy import faces  # noqa: E402


def _lit_points(img: QImage, clip):
    """矩形里的「不透明亮像素」（判据从 faces.LIT 常量读，不写死色相）。"""
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    pts = []
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
            if a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70:
                pts.append((x, y))
    return pts


def _moment_angle(pts):
    """亮像素云的主轴角（度）。旋转会把主轴角精确地转过去。"""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    m20 = sum((p[0] - mx) ** 2 for p in pts) / n
    m02 = sum((p[1] - my) ** 2 for p in pts) / n
    m11 = sum((p[0] - mx) * (p[1] - my) for p in pts) / n
    return 0.5 * math.degrees(math.atan2(2 * m11, m20 - m02))


def test_real_face_tilts_while_writing(qapp):
    """真脸实测：写字会话里它真的绕中心转了（方向对、量级对），且没画出重绘区。"""
    a, b = _mkwin(), _mkwin()
    try:
        a.input.setText("在写")
        b.input.setText("在写")  # 两边喂一样的字：唯一差别留给「会不会歪」

        def _no_tilt(at: float) -> None:
            """对照的它：同种子、同喂法，唯独不会歪。"""

        b.anim.tilt = _no_tilt
        fire = None
        for _ in range(150):
            _step(a)
            _step(b)
            if a.anim._tilt_at != -99.0:
                fire = a.anim._tilt_at
                break
        assert fire is not None, "前提不成立：没歪起来"
        t_full = round(fire + anim.TILT_RISE_S + 0.1, 6)
        a.anim_t = b.anim_t = t_full
        ia = a.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        ib = b.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        clip = a.lay.face.adjusted(-30, -30, 30, 30)
        d = _moment_angle(_lit_points(ia, clip)) - _moment_angle(_lit_points(ib, clip))
        assert -5.6 <= d <= -3.0, f"写作中的歪头看不到（主轴角差 {d:.2f} 度）"
        ba, bb = bytes(ia.constBits()), bytes(ib.constBits())
        sa, sb = ia.bytesPerLine(), ib.bytesPerLine()
        region = a._face_region()
        inside = outside = 0
        for y in range(ia.height()):
            ra, rb = y * sa, y * sb
            for x in range(ia.width()):
                i = ra + x * 4
                j = rb + x * 4
                if ba[i : i + 4] != bb[j : j + 4]:
                    if region.contains(x, y):
                        inside += 1
                    else:
                        outside += 1
        assert inside > 4500, f"只改了 {inside} 个像素 —— 不像在转"
        assert outside == 0, f"有 {outside} 个改动像素落在重绘区外"
        t_back = round(fire + anim.tilt_total() + 0.3, 6)
        assert a.anim.frame_at(t_back).tilt == 0.0, "收完了还没回正"
    finally:
        a.close()
        b.close()


# ── 纪律与素材 ────────────────────────────────────


def test_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "typing_tilt_preview.py").is_file()
    assert "typing-tilt-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("typing-tilt-strip.png", "typing-tilt-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
