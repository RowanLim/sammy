"""打字凝视「看着你写」（自选小步·第十一次）—— 先写判据，实现对着判据做。

为什么做它：在此之前，你在输入框里敲的字对脸是**不可见**的 —— 只有回车
发出去之后它才动起来。一个真的活物，你凑过去跟它说话的时候，它就会看过来。
这一块把「你正在写」变成看得见的注意：视线从四处看的地方收回来，落到输入
框上（正下方）；你停手 TYPING_HOLD_S 秒，它才回去发自己的呆。

和光标凝视「它在看着你」共用同一条凝视盒与转向限速；优先级：光标（手在
指东西）第一 —— 刚指过的那一眼先看够，打字垫底；睡着 / 动画关都不做。

四层判据（和 test_sigh / test_nod 一个框架）：
1. 纯函数：窗口语义（边界 / 刷新 / 只扩不缩）、转向与保持、长时间写、
   只动凝视通道、光标先赢再交还、睡着冻结、reset 清态、确定性；
2. 窗口链路：真信号链（setText → textChanged → _on_typing）喂给动画层；
   睡着 / 动画关不喂；空文本（发送 / 删光）不算一次「在写」；
   写字这段不叹气、不栽头（两条空闲闸门各拦一次）；
3. 渲染（真窗口离屏双胞胎）：视线真的往下落到输入框 —— 质心差与凝视差对账；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：三个 TYPING_* 常量在 anim.py 顶部；调参速查表第 21 节。）
"""

from __future__ import annotations

import pathlib
import sys
import time
from itertools import pairwise

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import anim
from sammy.anim import Animator

pytestmark = pytest.mark.usefixtures("qapp")  # 窗口层要 QApplication


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet / test_nod 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


def _walk(a: Animator, t0: float, t1: float, step: float = 0.05, feed=None):
    """走时间轴，返回 [(t, frame)]，步长固定、确定性。feed = {t: 回调}，帧前触发。"""
    n = round((t1 - t0) / step)
    out = []
    for i in range(n + 1):
        t = round(t0 + i * step, 6)
        if feed and t in feed:
            feed[t](t)
        out.append((t, a.frame_at(t)))
    return out


# ── 纯函数层：窗口语义与凝视 ────────────────────────


def test_typing_constants_stay_gentle():
    """常量停在「轻」的量级：比一次呼吸长、比「走开一会儿」短；转向别比光标还急。"""
    assert 2.0 <= anim.TYPING_HOLD_S <= 8.0, f"保持 {anim.TYPING_HOLD_S}s 不在手感区间"
    assert 0.2 <= anim.TYPING_RETARGET_MIN_S <= anim.LOOK_RETARGET_MIN_S, "打字转向不该比光标更急"
    assert anim.TYPING_GAZE_Y == anim.GAZE_MAX_Y, "输入框在正下方：纵向该拉满凝视盒"
    assert 4 <= anim.TYPING_GAZE_Y <= 8


def test_note_typing_extends_the_window_monotonically():
    """手不停、窗口就一直在；老时间戳不许把窗口缩回去；到点就关。"""
    a = Animator(seed=7)
    assert not a.typing_active(0.0), "还没敲字就算在写？"
    a.note_typing(10.0)
    assert a.typing_active(10.0)
    assert a.typing_active(10.0 + anim.TYPING_HOLD_S), "边界上应该还算「在写」"
    assert not a.typing_active(10.0 + anim.TYPING_HOLD_S + 0.01), "停手超过保持窗口还在写？"
    a.note_typing(12.0)  # 又敲了一个字：窗口顺延
    assert a.typing_active(10.0 + anim.TYPING_HOLD_S + 0.01), "新敲的字没把窗口顺延"
    assert a.typing_active(12.0 + anim.TYPING_HOLD_S)
    a.note_typing(9.0)  # 老的时间戳（乱序喂）：不许把窗口缩回去
    assert a.typing_active(12.0 + anim.TYPING_HOLD_S), "旧时间戳把窗口缩回头了"
    assert not a.typing_active(12.0 + anim.TYPING_HOLD_S + 0.01)


def test_typing_turns_the_gaze_to_the_input_line():
    """敲字后 ~1 秒内看定输入框（正下方）；整个保持窗口里不动摇；之后会溜号。"""
    a = Animator(seed=7)
    a.note_typing(0.5)
    seq = _walk(a, 0.5, 12.5)
    got = {t: (f.gx, f.gy) for t, f in seq}
    assert got[1.0] == (0, anim.TYPING_GAZE_Y), "敲字一秒了还没看输入框"
    for i in range(0, 69):  # 1.00 .. 4.40：整个保持窗口
        t = round(1.0 + i * 0.05, 6)
        assert got[t] == (0, anim.TYPING_GAZE_Y), f"t={t} 没盯着输入框：{got[t]}"
    approach = [got[round(0.5 + i * 0.05, 6)] for i in range(0, 21)]  # 0.50 .. 1.50
    d = [abs(b[0] - p[0]) + abs(b[1] - p[1]) for p, b in pairwise(approach)]
    assert max(d) <= 3, f"转向不是缓动（单步最大 {max(d)}px）"
    after = [t for t, (x, y) in got.items() if t > 4.5 + 1e-9 and (x, y) != (0, anim.TYPING_GAZE_Y)]
    assert after, "停手后它一直钉在输入框上（该回去发呆的）"
    assert min(after) <= 12.0, "溜号来得太晚"


def test_typing_holds_the_input_line_across_a_long_session():
    """手一直不停（每 1 秒一个键、连写 20 秒）：视线一直守着；停了才走。"""
    c = Animator(seed=7)
    feed = {round(10.0 + k, 6): (lambda t: c.note_typing(t)) for k in range(0, 21)}
    seq = _walk(c, 10.0, 45.0, feed=feed)
    got = {t: (f.gx, f.gy) for t, f in seq}
    for t in (15.0, 20.0, 25.0, 29.0, 30.0):
        assert got[t] == (0, anim.TYPING_GAZE_Y), f"连续写着时 t={t} 没在看输入框：{got[t]}"
    left = [t for t, (x, y) in got.items() if t > 34.2 and (x, y) != (0, anim.TYPING_GAZE_Y)]
    assert left and left[0] <= 44.0, "最后一个键过去很久了还不溜号"


def test_typing_only_moves_the_gaze_channels():
    """双胞胎对账：打字只改「看哪儿」（含它派生的好奇拉高），别的通道逐帧全等。"""
    a = Animator(seed=7, blink_gap=(600.0, 600.0))
    b = Animator(seed=7, blink_gap=(600.0, 600.0))
    a.note_typing(0.5)
    diffs = 0
    for i in range(0, 71):  # 0.5 .. 4.0
        t = round(0.5 + i * 0.05, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        for k in ("squash", "dx", "dy", "pop", "talk_y", "talk_sq"):
            assert getattr(fa, k) == getattr(fb, k), f"t={t} 的 {k} 被打字动了"
        if (fa.gx, fa.gy) != (fb.gx, fb.gy):
            diffs += 1
    assert diffs >= 30, "双胞胎的视线几乎没分开 —— 打字凝视没生效？"


def test_typing_yields_to_the_cursor_then_reclaims():
    """光标刚指过（手）优先：先看够那一眼；光标过期后，打字把视线收回输入框。"""
    d = Animator(seed=7)
    d.note_typing(0.5)
    got = {}
    for i in range(0, 189):  # 0.5 .. 9.9
        t = round(0.5 + i * 0.05, 6)
        if t == 2.0:
            d.note_cursor(150.0, 0.0, t)
            d.note_cursor(170.0, 0.0, t)
        if t in (3.5, 6.0):
            d.note_typing(t)
        f = d.frame_at(t)
        got[t] = (f.gx, f.gy)
    assert got[2.6] == (10, 0), "光标动了，它没先看光标"
    assert got[4.5] == (10, 0), "光标那一眼没看够就被打字抢了"
    assert got[5.4] == (0, anim.TYPING_GAZE_Y), "光标过期后打字没把视线收回来"
    assert got[8.0] == (0, anim.TYPING_GAZE_Y)


def test_typing_does_nothing_while_asleep():
    """睡着：冻结的凝视不动（打字叫不醒它 —— 醒来那一下是 send / poke 的事）。"""
    a = Animator(seed=7)
    f0 = a.frame_at(1.0, calm=True)
    a.note_typing(1.5)
    f1 = a.frame_at(2.0, calm=True)
    f2 = a.frame_at(3.0, calm=True)
    assert (f1.gx, f1.gy) == (f0.gx, f0.gy) == (f2.gx, f2.gy), "睡着时打字把凝视推走了"
    f3 = a.frame_at(4.0)  # 醒来：从定格处接着走（不跳）
    assert (f3.gx, f3.gy) == (f0.gx, f0.gy), "醒来那一帧跳了"


def test_typing_reset_clears_state():
    """时间轴被拨动：旧的「在写」不作数。"""
    a = Animator(seed=7)
    a.note_typing(5.0)
    a.reset(6.0)
    assert a._typing_at == float("-inf")
    assert not a.typing_active(6.1)


def test_typing_is_deterministic():
    """同种子、同序列两遍逐值相等。"""

    def run():
        a = Animator(seed=23)
        out = []
        for i in range(1, 241):
            t = round(i * 0.05, 6)
            if t == 1.0:
                a.note_typing(t)
            if t == 3.0:
                a.note_cursor(-150.0, 0.0, t)
                a.note_cursor(-170.0, 0.0, t)
            if t == 5.0:
                a.note_typing(t)
            f = a.frame_at(t)
            out.append((f.gx, f.gy, round(f.squash, 12), f.dy, f.dx))
        return out

    assert run() == run()


# ── 窗口链路：真信号链 ─────────────────────────────
# （setText → textChanged → _on_typing → 动画层；闸门在窗口这一层。）

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

SEED_TYPING = 7


def _mk():
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留「有没有在读你写」这一个变量。"""
    from sammy.pet import SammyWindow

    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    w.anim = anim.Animator(seed=SEED_TYPING)
    w.set_expression(2)  # 普通脸：画面里动的只有视线
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    w.look_on = False  # 光标不参与（盯的是打字这一件事）
    return w


def _step(w):
    """推进一帧并把这一帧算出来（离屏没有事件循环，paint 不会自己跑）。"""
    w._anim_tick()
    return w.anim.frame_at(w.anim_t)


def test_window_feeds_the_animator_and_ignores_empty_text(qapp):
    """setText → textChanged → _on_typing → 动画层；空文本（发送 / 删光）不算「在写」。"""
    w = _mk()
    try:
        w.input.setText("你")
        assert w.anim._typing_at == 8.0, "敲字没喂给动画层"
        assert time.time() - w._last_typing_at < 2.0, "窗口没记下这一次「在写」"
        w.anim_t = 10.0
        w.input.setText("你好")  # 又敲：窗口顺延
        assert w.anim._typing_at == 10.0
        w.input.setText("")  # 发送 / 删光：不算一次新的「在写」
        assert w.anim._typing_at == 10.0, "清空输入框被当成了一次敲字"
    finally:
        w.close()


def test_window_does_not_feed_while_asleep_or_anim_off(qapp):
    """睡着 / 动画关：都不喂（醒来那一下是 send / poke 的事，别抢）。"""
    w = _mk()
    try:
        w.drives.asleep = True
        w.input.setText("睡")
        assert w.anim._typing_at == float("-inf"), "睡着还喂打字凝视"
        w.drives.asleep = False
        w.anim_on = False
        w.input.setText("关")
        assert w.anim._typing_at == float("-inf"), "动画关着还喂"
        w.anim_on = True
        w.anim_t = 12.0
        w.input.setText("醒")
        assert w.anim._typing_at == 12.0, "都恢复了还不喂"
    finally:
        w.close()


def test_window_sigh_and_nod_hold_off_while_you_write(qapp):
    """写字这段时间：不叹气、不栽头 —— 两条空闲闸门各拦一次，停手就恢复。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0  # 冻结驱力漂移（边界用例的老规矩）
        w.drives.boredom = 0.8
        w.drives.energy = 0.25
        w._last_interaction_at = time.time() - 60.0
        w._last_typing_at = time.time()
        w.anim_t = 50.0
        w._tick()
        assert w.anim._sigh_next_at is None, "人在给你写字，你却叹气"
        assert w.anim._nod_next_at is None, "人在给你写字，你却栽头"
        w._last_typing_at = time.time() - (anim.TYPING_HOLD_S + 0.5)
        w.anim_t = 51.0
        w._tick()
        assert w.anim._sigh_next_at is not None, "停手了还不让叹气"
        assert w.anim._nod_next_at is not None, "停手了还不让栽头"
    finally:
        w.close()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────


def _lit_centroid(w, clip):
    """clip 里「亮像素」（按 faces.LIT 常量读色）的质心与个数。"""
    from sammy import faces

    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    img = w.grab().toImage().convertToFormat(QImage.Format_RGB32)
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    xs = ys = n = 0
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            b, g, r = buf[i], buf[i + 1], buf[i + 2]
            if abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70:
                xs += x
                ys += y
                n += 1
    assert n > 1500, "抓到的亮像素太少，区域搞错了？"
    return xs / n, ys / n


def test_window_face_dips_toward_the_input_while_typing(qapp):
    """双胞胎实测：你在写的时候，屏幕上的脸真的往输入框（正下方）偏；
    停手之后它又回去发自己的呆。"""
    a, b = _mk(), _mk()
    try:
        a.input.setText("你")
        fa = fb = None
        for i in range(1, 61):
            fa = _step(a)
            fb = _step(b)
            if (
                i >= 25
                and fa.squash == 1.0
                and fb.squash == 1.0
                and fa.pop == 1.0
                and fb.pop == 1.0
            ):
                break
        else:
            raise AssertionError("60 步里没等到两边都干净的帧")
        assert (fa.gx, fa.gy) == (0, anim.TYPING_GAZE_Y), f"写信时没看输入框：{(fa.gx, fa.gy)}"
        assert fb.gy <= -3, f"对照的脸不该也在输入框上：gy={fb.gy}"
        f = a.lay.face
        clip = QRect(f.left() - 60, 2, f.width() + 120, f.height() + 70)
        ca = _lit_centroid(a, clip)
        cb = _lit_centroid(b, clip)
        dy = ca[1] - cb[1]
        dx = ca[0] - cb[0]
        assert dy >= 8, f"质心没有往下沉：{dy:.1f}px"
        assert abs(dy - (fa.gy - fb.gy)) <= 3.5, f"纵向质心差 {dy:.1f} 与凝视差对不上"
        assert abs(dx - (fa.gx - fb.gx)) <= 3.5, f"横向质心差 {dx:.1f} 与凝视差对不上"
        left = None
        for _ in range(360):  # 停手后 12 秒内它得溜号
            f2 = _step(a)
            if a.anim_t > 12.05 and (f2.gx, f2.gy) != (0, anim.TYPING_GAZE_Y):
                left = a.anim_t
                break
        assert left is not None, "停手 12 秒了还钉在输入框上"
    finally:
        a.close()
        b.close()


# ── 纪律与素材 ─────────────────────────────────────


def test_typing_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "typing_preview.py").is_file()
    assert "typing-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("typing-strip.png", "typing-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
