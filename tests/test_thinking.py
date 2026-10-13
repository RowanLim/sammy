"""思考凝视「想事情的时候，抬起头来」（自选小步·第十三次）—— 先写判据，实现对着判据做。

为什么做它：按下发送之后到回复出现之前，脸**没有任何反应** —— 只有回复区的
思考点在转。一个真的活物，你问了话它会先想想：人想事情会**抬起头**（像在
回忆 / 盘算）；想完了把视线收回来。这一块把「它在想」变成看得见的动作：
发送 → 视线抬到正上方 → 想好了 → 缓动收回正中，再回去发自己的呆。

发送那一刻还顺手做了一件事：**「看着你写」的阶段到此为止**（end_typing）——
话已经交出去、开始被想，视线不该还钉在输入框上。优先级：光标 > 打字 > 思考
（都被叫到先看你）；睡着 / 动画关 / 被搬着不做。

四层判据（和 test_typing / test_nod 一个框架）：
1. 纯函数：电平语义（升 / 降沿）、抬头与收回、只动凝视通道、让位与交还、
   睡着冻结、没喂过 = 一个字节不许动、reset 清态、确定性；
2. 窗口链路：真 send() 链（发送取消打字保持 + 开始想 → 抬头）；睡着 / 动画关 /
   被搬着都不喂（放开就恢复）；想完收回来；
3. 渲染（真窗口离屏双胞胎）：在想的它真的抬起来、想完收回来 —— 质心差与凝视差对账；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：两个 THINKING_* 常量在 anim.py 顶部；调参速查表第 23 节。）
"""

from __future__ import annotations

import pathlib
import sys
from itertools import pairwise

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import anim
from sammy.anim import Animator

pytestmark = pytest.mark.usefixtures("qapp")  # 窗口层要 QApplication


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet / test_typing 同一套隔离）。"""
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


# ── 纯函数层：电平语义与凝视 ────────────────────────


def test_thinking_constants_stay_gentle():
    """常量停在「轻」的量级：转向不急过光标；抬头 = 纵向拉满、朝上。"""
    assert 0.2 <= anim.THINKING_RETARGET_MIN_S <= anim.LOOK_RETARGET_MIN_S, "思考转向不该比光标更急"
    assert anim.THINKING_GAZE_Y == -anim.GAZE_MAX_Y, "抬起头 = 纵向拉满凝视盒（负方向）"
    assert -8 <= anim.THINKING_GAZE_Y <= -4


def test_note_thinking_is_a_level_signal():
    """电平语义：升沿开始、降沿收尾；一直喂 True 不重置；停一下又想：清掉没收完的半拍。"""
    a = Animator(seed=7)
    assert not a.thinking_active(0.0)
    a.note_thinking(1.0, True)
    assert a.thinking_active(1.0) and a.thinking_active(9.9)
    assert a._thinking_at == 1.0, "升沿没记下开始时刻"
    a.note_thinking(2.0, True)  # 一直在想：不重置开始时刻
    assert a._thinking_at == 1.0
    a.note_thinking(3.0, False)
    assert not a.thinking_active(3.0)
    assert a._thinking_break is True, "降沿该把「收视线」记成待办"
    a.note_thinking(4.0, True)  # 停一下又想：半拍作废
    assert a._thinking_break is False
    assert a._thinking_at == 4.0
    assert a.thinking_active(4.0)


def test_thinking_lifts_the_gaze_up():
    """开始想后 ≤1 秒看定上方 (0, THINKING_GAZE_Y)；想的整段时间里不动摇。"""
    a = Animator(seed=7)
    a.note_thinking(0.5, True)
    seq = _walk(a, 0.5, 6.0)
    got = {t: (f.gx, f.gy) for t, f in seq}
    assert got[1.1] == (0, anim.THINKING_GAZE_Y), "开始想一秒了还没抬头"
    for t in (1.5, 2.5, 3.5, 4.0):  # 想的整段时间：钉在上方
        assert got[t] == (0, anim.THINKING_GAZE_Y), f"t={t} 没钉在上方：{got[t]}"
    approach = [got[round(0.5 + i * 0.05, 6)] for i in range(0, 21)]  # 0.50 .. 1.50
    d = [abs(b[0] - p[0]) + abs(b[1] - p[1]) for p, b in pairwise(approach)]
    assert max(d) <= 3, f"抬头不是缓动（单步最大 {max(d)}px）"


def test_thinking_release_pulls_the_gaze_back_to_center():
    """想完了（降沿）：视线缓动收回正中 —— 不是啪地跳；随后回到自己的漂移。"""
    a = Animator(seed=7)
    feed = {4.0: (lambda t: a.note_thinking(t, False))}
    a.note_thinking(0.5, True)
    seq = _walk(a, 0.5, 14.0, feed=feed)
    got = {t: (f.gx, f.gy) for t, f in seq}
    assert got[3.9] == (0, anim.THINKING_GAZE_Y)
    assert got[4.6] == (0, 0), "想完半秒多还没收回正中"  # 4.0 出发 + 0.55 缓动
    back = [got[round(4.0 + i * 0.05, 6)] for i in range(0, 13)]
    d = [abs(b[0] - p[0]) + abs(b[1] - p[1]) for p, b in pairwise(back)]
    assert max(d) <= 3, f"收回不是缓动（单步最大 {max(d)}px）"
    # 收回后它会在正中待一会儿（漂移间隔 2.6~7.4 秒），然后回去发呆
    left = [t for t, (x, y) in got.items() if t > 4.7 and (x, y) != (0, 0)]
    assert left, "收回来后它一直钉在正中（该回去发呆的）"
    assert 8.3 <= min(left) <= 8.6, f"离开正中的时刻不对：{min(left)}s（种子 7 实测 8.45s）"


def test_thinking_only_moves_the_gaze_channels():
    """双胞胎对账：想事情只改「看哪儿」（含它派生的好奇拉高），别的通道逐帧全等。"""
    a = Animator(seed=7, blink_gap=(600.0, 600.0))
    b = Animator(seed=7, blink_gap=(600.0, 600.0))
    a.note_thinking(0.5, True)
    diffs = 0
    for i in range(0, 71):  # 0.5 .. 4.0
        t = round(0.5 + i * 0.05, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        for k in ("squash", "dx", "dy", "pop", "talk_y", "talk_sq"):
            assert getattr(fa, k) == getattr(fb, k), f"t={t} 的 {k} 被思考动了"
        if (fa.gx, fa.gy) != (fb.gx, fb.gy):
            diffs += 1
    assert diffs >= 30, "双胞胎的视线几乎没分开 —— 思考凝视没生效？"


def test_thinking_yields_to_the_cursor_then_reclaims():
    """光标刚指过（手）优先：先看够那一眼；光标过期后，思考把视线收回上方。"""
    d = Animator(seed=7)
    d.note_thinking(0.5, True)
    got = {}
    for i in range(0, 180):  # 0.5 .. 9.45
        t = round(0.5 + i * 0.05, 6)
        if t == 2.0:
            d.note_cursor(150.0, 0.0, t)
            d.note_cursor(170.0, 0.0, t)
        f = d.frame_at(t)
        got[t] = (f.gx, f.gy)
    assert got[1.2] == (0, anim.THINKING_GAZE_Y), "还没被叫到，它该在抬头想"
    assert got[2.6] == (10, 0), "光标动了，它没先看光标"
    assert got[4.5] == (10, 0), "光标那一眼没看够就被思考抢了"
    assert got[5.4] == (0, anim.THINKING_GAZE_Y), "光标过期后思考没把视线收上去"


def test_thinking_yields_to_typing():
    """你又在写（打字保持窗口内）：看输入框优先；停手后接着想（回上方）。"""
    d = Animator(seed=7)
    d.note_thinking(0.5, True)
    got = {}
    for i in range(0, 160):  # 0.5 .. 8.45
        t = round(0.5 + i * 0.05, 6)
        if t == 2.0:
            d.note_typing(t)
        f = d.frame_at(t)
        got[t] = (f.gx, f.gy)
    assert got[1.2] == (0, anim.THINKING_GAZE_Y)
    assert got[2.7] == (0, anim.TYPING_GAZE_Y), "你开始写了，它没看输入框"
    assert got[5.9] == (0, anim.TYPING_GAZE_Y), "写字保持窗口里它没守着输入框"
    assert got[7.0] == (0, anim.THINKING_GAZE_Y), "你停手后它没接着想（回上方）"


def test_thinking_does_nothing_while_asleep():
    """睡着：冻结的凝视不动（想事儿叫不醒它）；醒来接着想（不跳，随后抬头）。"""
    a = Animator(seed=7)
    f0 = a.frame_at(1.0, calm=True)
    a.note_thinking(1.5, True)
    f1 = a.frame_at(2.0, calm=True)
    f2 = a.frame_at(2.5, calm=True)
    assert (f1.gx, f1.gy) == (f0.gx, f0.gy) == (f2.gx, f2.gy), "睡着时思考把凝视推走了"
    f3 = a.frame_at(3.0)  # 醒来那一帧：从定格处接上（不跳）
    assert (f3.gx, f3.gy) == (f0.gx, f0.gy), "醒来那一帧跳了"
    f4 = a.frame_at(4.2)  # 还在想：抬起来
    assert (f4.gx, f4.gy) == (0, anim.THINKING_GAZE_Y), "醒来后还在想却没抬头"


def test_no_feed_stays_byte_identical():
    """没在想的场景一个字节不许动：每帧喂 False 的它与什么都不喂的孪生逐帧全等（20 秒）。"""
    a = Animator(seed=7, blink_gap=(600.0, 600.0))
    b = Animator(seed=7, blink_gap=(600.0, 600.0))
    for i in range(0, 401):
        t = round(i * 0.05, 6)
        a.note_thinking(t, False)  # 窗口每帧都在喂（只是值为 False）
        assert a.frame_at(t) == b.frame_at(t), f"t={t} 喂 False 和没喂对不上"


def test_thinking_reset_clears_state():
    """时间轴被拨动：旧的「在想」不作数（收视线待办、抬过头标记也清）。"""
    a = Animator(seed=7)
    a.note_thinking(5.0, True)
    a.note_thinking(6.0, False)  # 留一条没收完的待办
    a.reset(6.5)
    assert not a.thinking_active(6.6)
    assert a._thinking_break is False
    assert a._thinking_up is False
    assert a._thinking_at == -99.0


def test_thinking_is_deterministic():
    """同种子、同序列两遍逐值相等。"""

    def run():
        a = Animator(seed=23)
        out = []
        for i in range(1, 321):
            t = round(i * 0.05, 6)
            if t == 1.0:
                a.note_thinking(t, True)
            if t == 4.0:
                a.note_thinking(t, False)
            if t == 6.0:
                a.note_thinking(t, True)
            if t == 7.0:
                a.note_cursor(-150.0, 0.0, t)
                a.note_cursor(-170.0, 0.0, t)
            if t == 10.0:
                a.note_typing(t)
            f = a.frame_at(t)
            out.append((f.gx, f.gy, round(f.squash, 12), f.dy, f.dx))
        return out

    assert run() == run()


# ── 窗口链路：真信号链 ─────────────────────────────
# （send → thinking 电平 → _anim_tick → note_thinking → 动画层；闸门在窗口这一层。）

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

SEED_THINKING = 7


class _StubBrain:
    """够 send() 用：chat() 立刻给一条回复（后台线程那次调用不阻塞测试）。"""

    def chat(self, text, memory_context="", on_event=None):
        return {"reply": "假回复", "emotion": "happy", "expression": 4, "latency": 0.1}


def _mk(seed: int = SEED_THINKING):
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留「有没有在想」这一个变量。"""
    from sammy.pet import SammyWindow

    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    w.anim = anim.Animator(seed=seed)
    w.set_expression(2)  # 普通脸：画面里动的只有视线
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    w.look_on = False  # 光标不参与（盯的是「想」这一件事）
    return w


def _step(w):
    """推进一帧并把这一帧算出来（离屏没有事件循环，paint 不会自己跑）。"""
    w._anim_tick()
    return w.anim.frame_at(w.anim_t)


def test_window_send_ends_the_typing_phase_and_starts_thinking(qapp):
    """真 send() 链：发送那一刻「在写」作废（视线别再钉输入框）、并开始想；想完收回来。"""
    w = _mk()
    try:
        w.brain = _StubBrain()
        w.input.setText("你好呀")
        assert w.anim._typing_at == 8.0, "敲字没喂给动画层"
        w.send()  # 真信号链：清空输入框 → 写字阶段结束 → thinking = True
        assert w.thinking is True
        assert w.anim._typing_at == float("-inf"), "发送了，打字保持窗口还留着"
        f = None
        for _ in range(45):  # 走到约 +1.5 秒
            f = _step(w)
        assert (f.gx, f.gy) == (0, anim.THINKING_GAZE_Y), "发送后没抬头（在想）"
        w.thinking = False  # 回复到了
        for _ in range(40):  # 走到约 +1.3 秒
            f = _step(w)
        assert (f.gx, f.gy) == (0, 0), "想完了没把视线收回来（正中）"
    finally:
        w.close()


def test_window_gates_the_feed(qapp):
    """睡着 / 被搬着 / 动画关：都不喂（放开就恢复）。"""
    w = _mk()
    try:
        w.thinking = True
        _step(w)
        assert w.anim._thinking_active is True, "在想却没喂给动画层"
        w.drives.asleep = True
        _step(w)
        assert w.anim._thinking_active is False, "睡着还喂思考凝视"
        w.drives.asleep = False
        w._drag = (5, 5)  # 被搬着：鼠标是「拿着它」的手
        _step(w)
        assert w.anim._thinking_active is False, "被搬着还喂"
        w._drag = None
        w.anim_on = False
        _step(w)
        assert w.anim._thinking_active is False, "动画关着还喂"
        w.anim_on = True
        _step(w)
        assert w.anim._thinking_active is True, "都恢复了还不喂"
    finally:
        w.close()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

SEED_RENDER = 23  # 这个种子下孪生正好停在下方（-6, +5）：抬头的信号最强


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


def test_window_face_lifts_while_thinking_then_returns(qapp):
    """双胞胎实测：在想的时候，屏幕上的脸真的抬起来（看上方）；想完收回来。"""
    a, b = _mk(SEED_RENDER), _mk(SEED_RENDER)
    try:
        a.thinking = True
        fa = fb = None
        for i in range(1, 81):
            fa = _step(a)
            fb = _step(b)
            if (
                i >= 15
                and fa.squash == 1.0
                and fb.squash == 1.0
                and fa.pop == 1.0
                and fb.pop == 1.0
                and (fa.gx, fa.gy) == (0, anim.THINKING_GAZE_Y)
                and fb.gy >= 3
            ):
                break
        else:
            raise AssertionError("80 步里没等到「A 在上、B 在下、两边干净」的帧")
        assert (fa.gx, fa.gy) == (0, anim.THINKING_GAZE_Y)
        f = a.lay.face
        # 只量脸框本身：下沿切在状态行（y≈246）之上 —— 状态文字 / 思考点只在
        # 「在想」的那侧不一样，量进来会污染质心（twitch 那次的同类坑）。
        clip = QRect(f.left() - 60, 0, f.width() + 120, f.top() + f.height() - 8)
        ca = _lit_centroid(a, clip)
        cb = _lit_centroid(b, clip)
        dy = ca[1] - cb[1]
        dx = ca[0] - cb[0]
        assert dy <= -8, f"质心没有抬起来：{dy:.1f}px"
        assert abs(dy - (fa.gy - fb.gy)) <= 3.5, f"纵向质心差 {dy:.1f} 与凝视差对不上"
        assert abs(dx - (fa.gx - fb.gx)) <= 3.5, f"横向质心差 {dx:.1f} 与凝视差对不上"
        # 想完了：视线收回正中（还在想就一直抬着）
        a.thinking = False
        for _ in range(60):  # 走到约 +2 秒
            fa = _step(a)
            _step(b)
        assert (fa.gx, fa.gy) == (0, 0), "想完了没收回正中"
    finally:
        a.close()
        b.close()


# ── 纪律与素材 ─────────────────────────────────────


def test_thinking_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "thinking_preview.py").is_file()
    assert "thinking-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("thinking-strip.png", "thinking-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
