"""摸摸头「手停在脸上的时候，眯起眼呼噜一下」（自选小步·第十四次）—— 先写判据，实现对着判据做。

为什么做它：光标凝视（自选小步·第三次）让「你的手在动」有个回应（转过来看你
一眼）；可**手停下来、放在它脸上**的时候什么都不会发生 —— 一个真的活物被
摸头会眯起眼、轻轻发出呼噜。桌面宠物的「手」就是鼠标：光标停进脸框、停够
PET_DWELL_S 秒 = 在摸它；摸住就慢慢眯起眼（舒服）、配一层轻轻的呼噜起伏；
手拿开再慢慢睁开。路过、划过去都不算 —— 手停下来才有「被摸」的意思。

和光标凝视的分工：光标凝视管「手在动 → 看你一眼」；摸摸头管「手停在你脸上
→ 眯起眼」。睡着 / 动画关 / 被搬着都不做（那时的手不是摸的手）。

四层判据（和 test_thinking / test_twitch 一个框架）：
1. 纯函数：电平语义（升 / 降沿）、停够才眯（dwell）、缓入缓出、只动 squash/dy
   两个通道、睡着（calm）不生效、没喂过 = 一个字节不许动、reset 清态、确定性；
2. 窗口链路：光标停进脸框 → 窗口把「在摸」喂给动画层（脸框外不算）；
   睡着 / 被搬着 / 光标功能关 / 动画关 —— 都不喂（放开就恢复）；
3. 渲染（真窗口离屏双胞胎）：摸住时屏幕上的脸真的眯起来（顶沿 / 下沿各自向
   中心收、宽度不动、按 PET_SQUINT_MIN 与呼噜逐像素对账）、收完与孪生逐
   字节 0 差异；关键帧落在局部重绘区里；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：六个 PET_* 常量在 anim.py 顶部；调参速查表第 24 节。）
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

T0 = 30.0  # 热身后的时刻（初始凝视 / 眨眼早已跑起来）


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet / test_thinking 同一套隔离）。"""
    from sammy import attention, care, drives

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


def _pair(seed: int = 7) -> tuple[Animator, Animator]:
    """双胞胎：眨眼请出去（600 秒才眨一次）—— 眯眼走 squash 通道，撞上眨眼量不准。"""
    return (
        Animator(seed=seed, blink_gap=(600.0, 600.0)),
        Animator(seed=seed, blink_gap=(600.0, 600.0)),
    )


# ── 纯函数层：停够才眯 / 缓入缓出 ────────────────────────


def test_pet_constants_stay_gentle():
    """常量停在「轻」的量级：停够才眯、慢慢眯慢慢睁、呼噜是像素级、节奏和呼吸错开。"""
    assert 0.3 <= anim.PET_DWELL_S <= 1.0, "停够的窗口：太短像路过就摸，太长像没反应"
    assert 0.2 <= anim.PET_EASE_IN_S <= 0.6, "眯起来要慢：是「舒服」，不是「闭眼」"
    assert anim.PET_EASE_OUT_S >= anim.PET_EASE_IN_S, "睁开不该比眯起来还急（像弹簧）"
    assert 0.4 <= anim.PET_SQUINT_MIN <= 0.65, "眯眼深度该在「半眯」邻域（眨眼 14% / 点头 50%）"
    assert anim.PET_SQUINT_MIN >= anim.NOD_SQUINT_MIN, "「困得睁不开」该比「舒服的半眯」深"
    assert isinstance(anim.PET_PURR_PX, int) and 1 <= anim.PET_PURR_PX <= 3, "呼噜是像素级起伏"
    assert 0.5 <= anim.PET_PURR_PERIOD <= 2.0, "呼噜的节拍"
    assert abs(anim.PET_PURR_PERIOD - anim.BREATH_PERIOD) >= 0.5, "呼噜和呼吸同频就分不出来了"


def test_pet_dwell_then_eases_in():
    """停够之前一动不动（路过不算）；停够之后缓入 —— PET_DWELL_S + PET_EASE_IN_S 眯到最深处。"""
    a, b = _pair()
    a.note_pet(T0, True)
    for i in range(0, 12):  # T0 .. T0+0.55：还在 dwell 里，两边逐帧全等
        t = round(T0 + i * 0.05, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} 还没停够就有反应了"
    engaged = round(T0 + anim.PET_DWELL_S, 6)
    b.frame_at(engaged)
    assert a.frame_at(engaged).squash == pytest.approx(1.0), "刚停够那一帧该还是「没眯」"
    full = round(engaged + anim.PET_EASE_IN_S, 6)
    last = 1.0
    for i in range(1, 8):  # 缓入段：单调向下（越眯越深）、单步不跳
        t = round(engaged + i * 0.05, 6)
        fb = b.frame_at(t)
        fa = a.frame_at(t)
        assert fa.squash <= last + 1e-9 and fa.squash < 1.0, f"{t} 缓入不单调"
        assert last - fa.squash <= 0.11, f"{t} 单步跳了 {last - fa.squash:.3f}"
        last = fa.squash
        assert fa.dy != fb.dy or fa.squash != fb.squash, f"{t} 缓入段没动？"
    assert a.frame_at(full).squash == pytest.approx(anim.PET_SQUINT_MIN), "到头没眯到最深处"
    t_later = round(full + 0.5, 6)
    assert a.frame_at(t_later).squash == pytest.approx(anim.PET_SQUINT_MIN), "眯住之后不该再变"


def test_pet_purr_matches_the_formula_point_by_point():
    """呼噜逐点对账（0.01 秒网格）：只加在 dy 上、幅度 ≤ PET_PURR_PX、确实来回摆。"""
    a, b = _pair(seed=11)
    a.note_pet(T0, True)
    full = round(T0 + anim.PET_DWELL_S + anim.PET_EASE_IN_S, 6)
    lo = hi = None
    for i in range(0, 180):  # 1.8 秒 = 两个呼噜周期
        t = round(full + i * 0.01, 6)
        pa, pb = a.frame_at(t), b.frame_at(t)
        assert pa.squash == pytest.approx(anim.PET_SQUINT_MIN), f"{t} 眯眼对不上"
        want = -round(anim.PET_PURR_PX * math.sin(2 * math.pi * t / anim.PET_PURR_PERIOD))
        assert pa.dy - pb.dy == want, f"{t} 呼噜对不上：{pa.dy - pb.dy} vs {want}"
        assert abs(want) <= anim.PET_PURR_PX
        lo = want if lo is None else min(lo, want)
        hi = want if hi is None else max(hi, want)
    assert lo <= -1 and hi >= 1, f"1.8 秒里呼噜没摆起来（{lo}..{hi}）"


def test_pet_release_eases_out_from_current_level():
    """手拿开：从当前档位缓出去（那一帧不跳）；PET_EASE_OUT_S 后与从未被摸过的孪生全等。"""
    a, b = _pair()
    a.note_pet(T0, True)
    t_off = round(T0 + anim.PET_DWELL_S + anim.PET_EASE_IN_S / 2, 6)  # 缓入半路
    b.frame_at(t_off)
    v_before = a.frame_at(t_off).squash
    assert v_before < 1.0, "前提不成立：还没眯起来"
    a.note_pet(t_off, False)
    assert a.frame_at(t_off).squash == pytest.approx(v_before), "手拿开的那一帧跳了"
    last = v_before
    for i in range(1, 12):  # 缓出段：单调向上（慢慢睁开）、单步不跳
        t = round(t_off + i * 0.05, 6)
        b.frame_at(t)  # 孪生同拍（调用史一致）
        fa = a.frame_at(t)
        assert fa.squash >= last - 1e-9, f"{t} 睁开不单调"
        assert fa.squash - last <= 0.09, f"{t} 单步跳了 {fa.squash - last:.3f}"
        last = fa.squash
        if i <= 10:
            assert fa.squash < 1.0, f"{t} 提前睁完了？（缓出 {anim.PET_EASE_OUT_S}s）"
    t_end = round(t_off + anim.PET_EASE_OUT_S + 0.05, 6)
    assert a.frame_at(t_end) == b.frame_at(t_end), "缓出完后还没回到常态"


def test_pet_before_dwell_leaves_nothing():
    """还没停够手就拿开（路过）：什么都不留 —— 与从没被摸过的孪生逐帧全等。"""
    a, b = _pair()
    a.note_pet(T0, True)
    b.frame_at(T0 + 0.3)
    a.frame_at(T0 + 0.3)
    a.note_pet(T0 + 0.3, False)  # dwell（0.6s）还没过
    for i in range(0, 30):
        t = round(T0 + 0.35 + i * 0.05, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} 半路放开之后留下了痕迹"


def test_pet_level_semantics():
    """电平语义：停着就一直算；放开再停上来：dwell 从新锚点重新起算。"""
    a = Animator(seed=9)
    a.note_pet(10.0, True)
    a.note_pet(10.2, True)
    assert a._pet_on is True and a._pet_on_since == 10.0, "停着不该重置锚点"
    a.note_pet(10.3, False)
    assert a._pet_on is False
    a.note_pet(10.5, True)
    assert a._pet_on_since == 10.5, "放开再停上来该从新锚点起算"
    a.frame_at(round(10.5 + anim.PET_DWELL_S - 0.05, 6))  # 还差一点：没立起
    assert a._pet_active is False
    a.frame_at(round(10.5 + anim.PET_DWELL_S + 0.01, 6))  # 过线了：立起
    assert a._pet_active is True
    a.note_pet(11.2, False)
    assert a._pet_on is False and a._pet_active is False
    a.note_pet(11.3, False)  # 重复的 False：无操作，不炸
    assert a._pet_on is False


def test_pet_only_touches_squash_and_dy():
    """双胞胎对账：摸摸头只改 squash（眯眼）与 dy（呼噜），别的通道逐帧全等。"""
    a, b = _pair()
    a.note_pet(T0, True)
    sq = dy = 0
    for i in range(0, 120):  # T0 .. T0+6
        t = round(T0 + i * 0.05, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        for k in ("dx", "pop", "gx", "gy", "stretch", "talk_y", "talk_sq"):
            assert getattr(fa, k) == getattr(fb, k), f"t={t} 的 {k} 被摸摸头动了"
        if fa.squash != fb.squash:
            sq += 1
        if fa.dy != fb.dy:
            dy += 1
    assert sq >= 40 and dy >= 40, f"通道几乎没分开（squash {sq} / dy {dy}）—— 摸摸头没生效？"


def test_pet_does_nothing_while_asleep():
    """睡着（calm）：喂着「手在脸上」也不眯、不呼噜 —— 与孪生 calm 帧逐帧全等。"""
    a, b = _pair()
    a.note_pet(T0, True)
    for i in range(0, 60):  # 6 秒
        t = round(T0 + i * 0.1, 6)
        assert a.frame_at(t, calm=True) == b.frame_at(t, calm=True), f"{t} 睡着时摸摸头漏出来了"


def test_no_feed_stays_identical():
    """没被摸的场景一个字节不许动：每帧喂 False 的它与什么都不喂的孪生逐帧全等（20 秒）。"""
    a, b = _pair()
    for i in range(0, 401):
        t = round(i * 0.05, 6)
        a.note_pet(t, False)
        assert a.frame_at(t) == b.frame_at(t), f"t={t} 喂 False 和没喂对不上"


def test_pet_reset_clears_state():
    """时间轴被拨动（reset）：旧的那一轮摸摸头不作数（在摸 / 缓出档位全清）。"""
    a, b = _pair()
    a.note_pet(5.0, True)
    a.frame_at(5.0)
    b.frame_at(5.0)
    a.frame_at(5.7)
    b.frame_at(5.7)  # 立起「在摸」（两边调用史一致，孪生才拼得上）
    assert a._pet_active is True, "前提不成立：没立起「在摸」"
    a.reset(6.0)
    b.reset(6.0)
    assert a._pet_on is False and a._pet_active is False
    assert a._pet_on_since is None and a._pet_stop_t is None and a._pet_stop_level == 0.0
    for i in range(0, 20):
        t = round(6.05 + i * 0.05, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} reset 之后旧摸摸头还在"


def test_pet_is_deterministic():
    """同种子、同序列两遍逐值相等（种子相同 = 演出相同）。"""

    def run():
        a = Animator(seed=23)
        out = []
        for i in range(1, 241):
            t = round(i * 0.05, 6)
            if t == 2.0:
                a.note_pet(t, True)
            if t == 4.0:
                a.note_pet(t, False)
            if t == 6.0:
                a.note_pet(t, True)
            if t == 9.0:
                a.note_pet(t, False)
            f = a.frame_at(t)
            out.append((round(f.squash, 12), f.dy, f.dx, f.gx, f.gy))
        return out

    assert run() == run()


# ── 窗口链路：真信号链（_anim_tick → _poll_cursor → note_pet）────

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

SEED_PET = 7


def _mk(seed: int = SEED_PET):
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留「摸没摸」这一个变量。

    眨眼请出去（600 秒才眨一次）：摸摸头的眯眼走 squash 通道，眨眼撞上就量不准。
    look_on 默认关 —— 渲染对账直接喂动画层（光标那一段由下面窗口链路的两条单测盯）。
    """
    from sammy.pet import SammyWindow

    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    w.anim = anim.Animator(seed=seed, blink_gap=(600.0, 600.0))
    w.set_expression(2)  # 普通脸：画面里动的只有摸摸头（和底层呼吸 / 漂移）
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    w.look_on = False
    return w


class _FakeCursor:
    """可拖动的假光标：位置用"相对脸中心"的设备像素表示。"""

    def __init__(self, win):
        self.win = win
        self.dx = -400.0
        self.dy = 0.0

    def __call__(self):
        c = self.win.lay.face.center()
        s = self.win.scale
        lx = (c.x() + self.dx) * s + self.win._offset[0]
        ly = (c.y() + self.dy) * s + self.win._offset[1]
        return self.win.mapToGlobal(QPoint(round(lx), round(ly)))


def _step(w):
    """推进一帧并把这一帧算出来（离屏没有事件循环，paint 不会自己跑）。"""
    w._anim_tick()
    return w.anim.frame_at(w.anim_t)


def test_window_feeds_pet_from_cursor_on_face(qapp):
    """光标停进脸框：窗口把「在摸」喂给动画层 —— 停够后眯起来；出了脸框 / 拿开就睁开。"""
    w = _mk()
    try:
        w.look_on = True
        cur = _FakeCursor(w)
        w._cursor_now = cur
        cur.dx, cur.dy = 8.0, -4.0  # 停在脸上（脸框中央附近）
        for _ in range(30):  # 约 1 秒
            f = _step(w)
        assert w.anim._pet_on is True, "光标在脸上却没喂「在摸」"
        assert w.anim._pet_active is True, "停够 0.6 秒了还没立起「在摸」"
        assert f.squash == pytest.approx(anim.PET_SQUINT_MIN), "在摸却没眯起来"
        half = w.lay.face.width() / 2
        cur.dx = half + 40.0  # 挪到脸框之外（还在窗口里）
        for _ in range(3):
            _step(w)
        assert w.anim._pet_on is False, "光标出了脸框还喂「在摸」"
        cur.dx = -400.0  # 手拿开（远远的）
        for _ in range(25):  # 0.8 秒 > 缓出 0.55
            f = _step(w)
        assert w.anim._pet_on is False and w.anim._pet_active is False
        assert f.squash == 1.0, "手拿开 0.8 秒了还没睁开"
    finally:
        w.close()


def test_window_pet_gates(qapp):
    """睡着 / 被搬着 / 光标功能关 / 动画关 —— 都不喂「在摸」（放开就恢复）。"""
    w = _mk()
    try:
        w.look_on = True
        cur = _FakeCursor(w)
        w._cursor_now = cur
        cur.dx, cur.dy = 0.0, 0.0
        _step(w)
        assert w.anim._pet_on is True, "醒着、手在脸上，该喂"
        w.drives.asleep = True
        _step(w)
        assert w.anim._pet_on is False, "睡着还喂摸摸头"
        w.drives.asleep = False
        _step(w)
        assert w.anim._pet_on is True
        w._drag = (5, 5)  # 拎起来了：鼠标是「拿着它」的手
        _step(w)
        assert w.anim._pet_on is False, "被搬着还喂"
        w._drag = None
        _step(w)
        assert w.anim._pet_on is True
        w.look_on = False  # 光标功能关：手一并拿开（关就关彻底）
        _step(w)
        assert w.anim._pet_on is False, "光标功能关了还喂"
        w.look_on = True
        w.anim_on = False  # 动画关：不喂（没有时间线，就没有这回事）
        _step(w)
        assert w.anim._pet_on is False, "动画关着还喂"
        w.anim_on = True
        _step(w)
        assert w.anim._pet_on is True, "都恢复了还不喂"
    finally:
        w.close()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────


def _lit_bbox(w, clip: QRect) -> tuple[int, int, int, int]:
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


def _img_bytes(w) -> bytes:
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(img.constBits())


def _clip(w) -> QRect:
    """只框脸（状态行 y246+ 与关闭钮都在外面）—— 量到的每个像素都必须归脸管。"""
    box = w.lay.face
    return QRect(box.left(), box.top() + 4, box.width(), 218)


def test_petting_squints_on_screen_and_recovers(qapp):
    """scale 1.0 双胞胎：摸住时屏幕上的脸真的眯起来（顶 / 下沿按 PET_SQUINT_MIN + 呼噜
    对账、宽度不动）；手拿开、缓出完之后与孪生逐字节 0 差异。"""
    a, b = _mk(), _mk()
    try:
        t0 = 8.0
        a.anim.note_pet(t0, True)
        for i in range(1, 46):  # ~1.5 秒：a 一直被摸（每帧喂同一行生产入口）
            t = round(t0 + i * 0.033, 6)
            a.anim_t = t
            b.anim_t = t
            a.anim.note_pet(t, True)
            a.anim.frame_at(t)
            b.anim.frame_at(t)
        clip = _clip(a)
        x0a, y0a, x1a, y1a = _lit_bbox(a, clip)
        x0b, y0b, x1b, y1b = _lit_bbox(b, clip)
        assert abs(x0a - x0b) <= 2 and abs(x1a - x1b) <= 2, "摸摸头不该动宽度"
        s = anim.PET_SQUINT_MIN
        cy = a.lay.face.center().y()
        purr = -round(anim.PET_PURR_PX * math.sin(2 * math.pi * a.anim_t / anim.PET_PURR_PERIOD))
        want_top = cy + (y0b - cy) * s + purr
        want_bottom = cy + (y1b - cy) * s + purr
        assert abs(y0a - want_top) <= 2, f"顶沿 {y0a} 对不上公式 {want_top:.1f}（眯 + 呼噜）"
        assert abs(y1a - want_bottom) <= 2, f"下沿 {y1a} 对不上公式 {want_bottom:.1f}（眯 + 呼噜）"
        assert (y1a - y0a) <= 0.75 * (y1b - y0b), "脸高没缩到 3/4 以上 —— 没眯起来"
        t_off = round(a.anim_t + 0.033, 6)
        a.anim.note_pet(t_off, False)
        for i in range(0, 30):
            t = round(t_off + i * 0.033, 6)
            a.anim_t = t
            b.anim_t = t
            a.anim.frame_at(t)
            b.anim.frame_at(t)
        assert _img_bytes(a) == _img_bytes(b), "收完还不回到常态"
    finally:
        a.close()
        b.close()


def test_petting_key_moment_stays_inside_the_repainted_region(qapp):
    """摸到最眯那一帧必须落在局部重绘区里 —— 在外面那圈不刷新（脸会花）。"""
    w = _mk()
    try:
        w.anim.note_pet(8.0, True)
        clip = _clip(w)
        for i in range(1, 40):
            t = round(8.0 + i * 0.033, 6)
            w.anim_t = t
            w.anim.note_pet(t, True)
            w.anim.frame_at(t)
        region = w._face_region()
        x0, y0, x1, y1 = _lit_bbox(w, clip)
        deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        assert region.contains(deformed), f"摸到最眯时脸 {deformed} 冒出重绘区 {region}"
    finally:
        w.close()


# ── 纪律与素材 ─────────────────────────────────────


def test_geometry_guard_covers_the_pet_channel():
    """全局几何预算守卫（test_yawn）必须把摸摸头的呼噜算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "anim.PET_PURR_PX" in text, (
        "test_yawn 的全局预算守卫里没有摸摸头的呼噜通道 —— 调大 PET_PURR_PX 就没人拦了"
    )


def test_petting_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "petting_preview.py").is_file()
    assert "petting-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("petting-strip.png", "petting-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
