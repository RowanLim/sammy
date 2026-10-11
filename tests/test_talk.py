"""说话动脸「字在往外冒，脸跟着动」（自选小步·第六次）—— 先写判据，实现对着判据做。

动机：U3 让回复「一个字一个字打出来」，可打字的时候脸是一动不动的 ——
像一台机器在吐字，不像一个东西在说话。这一块把「打字 = 说话」接上：
字在冒出来的时候，脸跟着说话节奏轻轻起伏（上下弹 + 极轻的一鼓一收）；
字停了，脸也停 —— 像说完话闭上嘴。

三条来路：
1. 经典卡通惯例：角色说话时脑袋本来就会动（哪怕不画嘴），这是「活着」的一部分；
2. 上一轮从 RoboEyes 借的想法里剩的最后一条就是「说话时的动效」（自己实现，一行不抄）；
3. 我们自己的打字机（U3）已经把「什么时候在吐字」变成了可计算的纯函数 ——
   动脸只需要问它要一个布尔值。

三层判据：
1. 纯函数（anim.Animator.note_talk 与 frame_at 新加的两个字段 talk_y 和 talk_sq 两个通道）：
   波形公式逐点对账、峰谷钉死、缓入缓出、打断、重启、睡着不弹、只加不改；
2. 回归：没喂 talk 时的行为一个字节都不许变（与其他凝视用例同一份金色基线）；
3. 渲染（真窗口离屏抓图，scale 1.0 的双胞胎）：它打字时脸上的绿质心真的
   上下弹（幅度至少 2 像素、有振荡、逐帧不瞬移）；打完 + 收口后与孪生逐像素
   0 差异；动画关着（SAMMY_ANIM 设成 off 的语义位）连喂都不喂。

（设计数字：TALK_PERIOD / TALK_BOB_Y / TALK_SQUASH / TALK_EASE_IN / TALK_EASE_OUT
五个常量都在 anim.py 顶部；调参速查表第 16 节也有。）
"""

from __future__ import annotations

import math
import pathlib
import sys
import time
from itertools import pairwise

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import anim
from sammy.anim import Animator

pytestmark = pytest.mark.usefixtures("qapp")  # 窗口层要 QApplication

T0 = 30.0  # 热身后的时刻（初始随机凝视早已跑起来）
TEXT = "今天的风挺舒服的，我陪你坐一会儿。" * 2  # 34 字；reveal 约 1.68 秒，够两组波


def _walk(a: Animator, t0: float, t1: float, step: float = 0.05):
    """走时间轴，返回 [(t, frame)]，步长固定、确定性。"""
    n = round((t1 - t0) / step)
    out = []
    for i in range(n + 1):
        t = round(t0 + i * step, 6)
        out.append((t, a.frame_at(t)))
    return out


def _smooth(p: float) -> float:
    """0 到 1 的平滑缓动 —— 判据按这条曲线对账（和实现里 _smooth01 同一条）。"""
    p = min(1.0, max(0.0, p))
    return 0.5 * (1.0 - math.cos(math.pi * p))


def _env_in(tau: float) -> float:
    """开口包络：tau 秒内从 0 涨到 1。"""
    return _smooth(tau / anim.TALK_EASE_IN)


def _wave(tau: float) -> float:
    """说话波的形状：一上一下为一拍。"""
    return math.sin(2 * math.pi * tau / anim.TALK_PERIOD)


# ── 纯函数层：常量脾气与波形 ────────────────────────


def test_talk_constants_stay_subtle():
    """常量必须停在「轻微」量级：弹幅几像素、鼓收几个百分点、节奏像说话不像抽搐。"""
    assert 0.25 <= anim.TALK_PERIOD <= 0.9  # 约 1 到 4 拍每秒：比呼吸快、比抖慢
    assert 1.0 <= anim.TALK_BOB_Y <= 4.0  # 设备像素级：看得见，又不头晕
    assert 0.0 < anim.TALK_SQUASH <= 0.05  # 只许鼓收 5 个百分点以内
    assert 0.05 <= anim.TALK_EASE_IN <= 0.4
    assert 0.05 <= anim.TALK_EASE_OUT <= 0.6


def test_talk_starts_from_rest_and_peaks_are_pinned():
    """峰谷值钉死：静息起步（0），第一个峰的包络只到 61%（+2），之后是满幅的 ±3。"""
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.note_talk(T0, True)
    assert a.frame_at(T0).talk_y == 0
    assert a.frame_at(T0).talk_sq == 1.0
    assert a.frame_at(T0 + 0.11).talk_y == 2  # 2.6 × 0.671 = 1.745，四舍五入到 2
    assert a.frame_at(T0 + 0.33).talk_y == -3
    assert a.frame_at(T0 + 0.55).talk_y == 3
    assert a.frame_at(T0 + 0.77).talk_y == -3


def test_talk_wave_matches_the_formula_point_by_point():
    """整段波形逐点对账（0.01 秒网格、共 1.6 秒）：形状不靠肉眼看。"""
    a = Animator(seed=11)
    _walk(a, 0.0, T0)
    a.note_talk(T0, True)
    for i in range(161):
        tau = round(i * 0.01, 6)
        f = a.frame_at(T0 + tau)
        env = _env_in(tau)
        w = _wave(tau)
        assert f.talk_y == round(anim.TALK_BOB_Y * env * w), tau
        assert abs(f.talk_sq - (1.0 + anim.TALK_SQUASH * env * w)) < 1e-12, tau
    # 同一条波：弹到顶上时脸略鼓（大于 1），落到谷底略收（小于 1）
    up = a.frame_at(T0 + 0.55)
    down = a.frame_at(T0 + 0.77)
    assert up.talk_y == 3 and up.talk_sq > 1.0
    assert down.talk_y == -3 and down.talk_sq < 1.0


def test_talk_eases_out_to_silence_and_stays_silent():
    """收口：从停下这一刻的音量缓出去；完全停下后长走 5 秒，一动不动。"""
    a = Animator(seed=12)
    _walk(a, 0.0, T0)
    a.note_talk(T0, True)
    stop = T0 + 1.0
    a.note_talk(stop, False)
    for i in range(0, 30):
        t = round(stop + i * 0.01, 6)
        f = a.frame_at(t)
        k = (t - stop) / anim.TALK_EASE_OUT
        env = 0.0 if k >= 1.0 else (1.0 - _smooth(k))
        w = math.sin(2 * math.pi * (t - T0) / anim.TALK_PERIOD)
        assert f.talk_y == round(anim.TALK_BOB_Y * env * w), t
    for i in range(1, 101):
        t = round(stop + 1.0 + i * 0.05, 6)
        f = a.frame_at(t)
        assert f.talk_y == 0 and f.talk_sq == 1.0, t


def test_talk_interrupted_mid_open_fades_from_where_it_was():
    """开口 0.06 秒就被打断（话短）：只到过 25% 的包络，从那里收口 —— 永不弹满。"""
    a = Animator(seed=13)
    _walk(a, 0.0, T0)
    a.note_talk(T0, True)
    stop = T0 + 0.06
    a.note_talk(stop, False)
    mx = 0
    for i in range(0, 80):
        t = round(stop + i * 0.02, 6)
        f = a.frame_at(t)
        mx = max(mx, abs(f.talk_y))
    assert mx <= 1, f"短句被打断却弹到了 {mx}（0.25 的包络 × 2.6 = 0.65，至多 ±1）"
    for i in range(1, 60):
        f = a.frame_at(round(stop + 0.4 + i * 0.05, 6))
        assert f.talk_y == 0 and f.talk_sq == 1.0


def test_talk_restart_after_silence_starts_fresh():
    """一段说完、完全静下来之后再来一段：从静息出发，同样的节奏重演。"""
    a = Animator(seed=14)
    _walk(a, 0.0, T0)
    a.note_talk(T0, True)
    a.note_talk(T0 + 0.8, False)
    _walk(a, T0 + 0.8, T0 + 2.4)
    t2 = T0 + 2.5
    a.note_talk(t2, True)
    assert a.frame_at(t2).talk_y == 0
    assert a.frame_at(t2 + 0.33).talk_y == -3
    assert a.frame_at(t2 + 0.55).talk_y == 3


def test_talk_is_additive_only_other_channels_do_not_move():
    """只喂 talk 的一方与完全不喂的孪生：除 talk_y / talk_sq 外逐字段全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.note_talk(T0, True)
    live = 0
    for i in range(1, 141):
        t = round(T0 + i * 0.02, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (fa.squash, fa.dx, fa.dy, fa.pop, fa.gx, fa.gy, fa.stretch) == (
            fb.squash,
            fb.dx,
            fb.dy,
            fb.pop,
            fb.gx,
            fb.gy,
            fb.stretch,
        ), t
        assert fb.talk_y == 0 and fb.talk_sq == 1.0, t
        if fa.talk_y != 0:
            live += 1
    assert live >= 30, f"2.8 秒里只有 {live} 帧在动，波也太蔫了"


def test_unfed_animator_matches_the_untalked_golden():
    """没喂 talk 的金色基线（与其他凝视用例同一份）：新字段必须是出厂值。"""
    rows = {
        2.0: (10, -6, 1.07, 2, 1, 1.0, 1.0),
        6.0: (7, -5, 1.0343, 0, 2, 1.0, 1.0),
        17.0: (10, 3, 1.07, 0, -2, 1.0, 1.0),
        40.0: (3, 6, 1.0063, 0, -1, 1.0, 1.0),
    }
    a = Animator(seed=7)
    for t in (0.5, 1.0, 2.0, 3.5, 6.0, 9.0, 13.0, 17.0, 25.0, 40.0):
        f = a.frame_at(t)
        assert f.talk_y == 0 and f.talk_sq == 1.0
        if t in rows:
            got = (
                f.gx,
                f.gy,
                round(f.stretch, 4),
                f.dx,
                f.dy,
                round(f.squash, 4),
                round(f.pop, 4),
            )
            assert got == rows[t], f"{t} 时基线变了：{got}"
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


def test_sleep_suppresses_talk_and_waking_resumes():
    """睡着不弹（定格优先）；醒来接着说 —— 波按原相位继续。"""
    a = Animator(seed=15)
    _walk(a, 0.0, T0)
    a.note_talk(T0, True)
    for i in range(1, 61):
        f = a.frame_at(round(T0 + i * 0.02, 6), calm=True)
        assert f.talk_y == 0 and f.talk_sq == 1.0, i
    woke = [a.frame_at(round(T0 + 1.22 + i * 0.05, 6)) for i in range(8)]
    assert any(f.talk_y != 0 for f in woke), "醒了不接着说话，脸就哑了"


def test_talk_is_deterministic_and_reset_clears_state():
    """同序列两遍完全一致；reset 之后（时间线被拨动）清态、可重新喂。"""

    def run():
        a = Animator(seed=16)
        out = []
        for i in range(1, 241):
            t = round(i * 0.05, 6)
            if i == 40:
                a.note_talk(t, True)
            if i == 140:
                a.note_talk(t, False)
            f = a.frame_at(t)
            out.append((f.talk_y, round(f.talk_sq, 12), f.gx, f.gy))
        return out

    assert run() == run()

    a = Animator(seed=16)
    a.note_talk(50.0, True)
    a.frame_at(50.1)
    a.reset(50.1)
    f = a.frame_at(50.3)
    assert f.talk_y == 0 and f.talk_sq == 1.0, "reset 后还在弹"
    a.note_talk(50.4, True)
    assert a.frame_at(50.95).talk_y == 3, "reset 后重新喂，却不动了"


# ── 渲染层：真窗口离屏抓图 ─────────────────────────
# （纯函数说「该不该动、怎么动」，这里说「屏幕上真的在动」、开关真的断在哪。）

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

SEED_TALK = 7


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


def _mk(scale: float = 0.55, face_only: bool = False):
    """稳态窗口：种子 / 表情 / 时间轴全钉住，光标也钉住（别读真机器）。"""
    from sammy.pet import SammyWindow

    w = SammyWindow(face_only=face_only, autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    if scale != 0.55:
        w.scale = scale
        w._offset = (0, 0)
        w.resize(round(800 * scale), round(480 * scale))
    w.anim = anim.Animator(seed=SEED_TALK)
    w.set_expression(9)  # 吐舌：没有动图，画面里动的只有脸自己
    w.finish_typing()
    w.anim_t = 8.0
    w.look_on = True
    w._cursor_now = lambda: w.mapToGlobal(QPoint(0, 0))
    return w


def _step(w) -> None:
    """推进一帧：_anim_tick 之后把这一帧算出来（离屏没有事件循环）。"""
    w._anim_tick()
    w.anim.frame_at(w.anim_t)


def _lit_centroid_y(w) -> float:
    """抓图后量脸区亮像素的质心 y（判据从 faces.LIT 读，换配色不用改测试）。"""
    img = w.grab().toImage().convertToFormat(QImage.Format_RGB32)
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    r = w.lay.face.adjusted(-10, -10, 10, 2)
    clip = QRect(
        int(r.x() * w.scale) + w._offset[0],
        int(r.y() * w.scale) + w._offset[1],
        int(r.width() * w.scale) + 2,
        int(r.height() * w.scale) + 2,
    ).intersected(QRect(0, 0, img.width(), img.height()))
    from sammy import faces

    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    n = sy = 0
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            b, g, rr = buf[i], buf[i + 1], buf[i + 2]
            if abs(rr - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70:
                n += 1
                sy += y
    assert n > 1000, "抓到的亮像素太少，区域搞错了？"
    return sy / n


def test_talking_now_tracks_the_typewriter():
    """「什么时候在说话」= 打字机正在吐字：逐条钉住所有影响它的状态。"""
    from sammy import typewriter

    w = _mk()
    try:
        assert w._talking_now() is False
        w.sammy_line = TEXT
        assert w._talking_now() is False, "还没画出来就自称在说话？"
        w.grab()
        assert w._talking_now() is True
        reveal = typewriter.reveal_seconds(TEXT)
        while w.anim_t - w._type_t0 < reveal + 0.02:
            _step(w)
        assert w._talking_now() is False, "打完了还说"
        w.thinking = True
        w.sammy_line = "……"
        w.grab()
        assert w._talking_now() is False, "思考里也在说？"
        w.thinking = False
    finally:
        w.close()

    w2 = _mk()
    try:
        w2.sammy_line = TEXT
        w2.grab()
        assert w2._talking_now() is True
        w2._boot_t0 = 1.0
        assert w2._talking_now() is False, "开机自检画面里不该动脸"
        w2._boot_t0 = None
        w2._shutdown_t0 = 1.0
        assert w2._talking_now() is False, "关机退场里不该动脸"
        w2._shutdown_t0 = None
        assert w2._talking_now() is True
        w2.finish_typing()
        assert w2._talking_now() is False, "打字机拨到尾（抓图态）就不该再弹"
    finally:
        w2.close()

    w3 = _mk()
    try:
        w3.anim_on = False
        w3.sammy_line = TEXT
        w3.grab()
        assert w3._talking_now() is False, "动画关着还在说？"
    finally:
        w3.close()


def test_talking_now_face_only_follows_its_line():
    """face-only 同一条机器：那一行在逐字打的时候，脸也弹。"""
    from sammy import typewriter

    w = _mk(face_only=True)
    try:
        w.sammy_line = TEXT
        w._line_until = time.time() + 60  # 那一行现在是「它刚说的话」
        assert w._talking_now() is False
        w.grab()
        assert w._talking_now() is True
        while w.anim_t - w._type_t0 < typewriter.reveal_seconds(TEXT) + 0.02:
            _step(w)
        assert w._talking_now() is False
        w._line_until = 0.0  # 那一行过期（回到状态显示）→ 不再算说话
        assert w._talking_now() is False
    finally:
        w.close()


def test_window_feeds_talk_every_tick():
    """每一帧恰好喂一次「在不在说话」；真假与打字机的窗口完全对上。"""
    from sammy import typewriter

    w = _mk()
    try:
        w.sammy_line = TEXT
        w.grab()
        calls: list[tuple[float, bool]] = []
        orig = w.anim.note_talk

        def spy(t, active):
            calls.append((t, active))
            return orig(t, active)

        w.anim.note_talk = spy
        reveal = typewriter.reveal_seconds(TEXT)
        steps = int((reveal + 0.5) / anim.ANIM_DT)
        for _ in range(steps):
            _step(w)
        assert len(calls) == steps, "每帧一喂，一次不多一次不少"
        flags = [active for _, active in calls]
        assert flags[0] is True
        expected_true = sum(1 for k in range(1, steps + 1) if (k * anim.ANIM_DT) < reveal)
        n_true = sum(flags)
        assert n_true == expected_true, f"说了 {n_true} 帧，期望 {expected_true}"
        assert all(f is False for f in flags[expected_true:])
        ts = [t for t, _ in calls]
        assert ts == sorted(ts), "喂的时刻必须单调"
        assert abs(ts[-1] - (8.0 + steps * anim.ANIM_DT)) < 0.01
    finally:
        w.close()


def test_anim_off_feeds_nothing_and_talk_stays_out():
    """动画关着（SAMMY_ANIM 设成 off 的语义位）：连喂都不喂，脸一个像素都不动。"""
    w = _mk()
    try:
        w.anim_on = False
        w.sammy_line = TEXT
        w.grab()
        calls = []
        w.anim.note_talk = lambda t, active: calls.append((t, active))
        for _ in range(10):
            _step(w)
        assert calls == [], "动画关着还在喂 talk"
        f = w.anim.frame_at(w.anim_t)
        assert f.talk_y == 0 and f.talk_sq == 1.0
    finally:
        w.close()


def test_talking_bobs_the_face_pixels_and_stops_when_silent():
    """scale 1.0 的双胞胎：打字时绿质心上下弹；打完与孪生逐像素 0 差异。"""
    from sammy import typewriter

    a, b = _mk(scale=1.0), _mk(scale=1.0)
    try:
        a.sammy_line = b.sammy_line = TEXT
        b.finish_typing()
        a.grab()
        b.grab()
        reveal = typewriter.reveal_seconds(TEXT)
        steps = int((reveal + 0.9) / anim.ANIM_DT)  # 尾部留足安静段：收口 + 长静默
        samples = []
        for _ in range(steps):
            _step(a)
            _step(b)
            d = _lit_centroid_y(a) - _lit_centroid_y(b)
            samples.append((round(a.anim_t - 8.0, 3), d))
        typing = [d for t, d in samples if t <= reveal]
        assert max(typing) >= 2.0, f"打字时没有向上弹：峰值 {max(typing)}"
        assert min(typing) <= -2.0, f"打字时没有向下弹：谷值 {min(typing)}"
        marks = [1 if d > 0.4 else (-1 if d < -0.4 else 0) for d in typing]
        crossings = 0
        last = 0
        for m in marks:  # 采样过零计数：穿过零附近的样本不算断，符号真的翻才算
            if m != 0:
                if last != 0 and m != last:
                    crossings += 1
                last = m
        assert crossings >= 4, f"一个打字段只换向 {crossings} 次，不像在说话"
        per_frame = max(abs(d2 - d1) for d1, d2 in pairwise([d for _, d in samples]))
        assert per_frame <= 3.0, f"单帧弹了 {per_frame} 像素（瞬移）"
        tail = [d for t, d in samples if t >= reveal + 0.4]
        assert len(tail) >= 10
        assert all(abs(d) < 1e-9 for d in tail), f"打完之后脸还在动：{tail[:6]}"
    finally:
        a.close()
        b.close()


def test_poke_quip_is_said_with_a_talking_face():
    """戳一下：回嘴的那句话会被「说出来」—— 打字 + 动脸，不是干瞪眼。"""
    w = _mk()
    try:
        w.thinking = False
        w.poke()
        assert w.sammy_line, "戳了却没话说？"
        w.grab()
        assert w._talking_now() is True
        seen = False
        for _ in range(12):
            _step(w)
            if w.anim.frame_at(w.anim_t).talk_y != 0:
                seen = True
        assert seen, "俏皮话在打，脸却一动不动"
    finally:
        w.close()


# ── 纪律与素材 ─────────────────────────────────────


def test_talk_media_and_script_are_shipped():
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "talk_preview.py").is_file()
    assert "talk-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("talk-strip.png", "talk-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
