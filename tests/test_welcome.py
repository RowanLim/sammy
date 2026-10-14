"""欢迎回来（自选小步·第二十一次）——「你回来啦」。

动机：它此前没有「离开一会儿再回来」这条缝 —— 长离开（几小时）它是睡着的，
醒来那条走哈欠；短离开呢？你回来它一点反应都没有，像一台不在家的机器。
这一条补上：光标（= 你能碰到的唯一全局信号）静够久（WELCOME_AWAY_S，和休息
提醒同一把尺子）= 你离开；再动起来的第一下 = 你回来 —— 整脸抬起来一点
（精神一振）、顺着光标看你一眼，再慢慢放回去（共 1.03 秒）。睡着 / 开局 /
退场 / 动画关都不排；打字 / 戳 / 发送也算「你还在」（消费掉旧的那次离开，
不叠着演欢迎）。

四层判据（和 test_dozeoff / test_survey 一个框架）：
1. 纯函数：形状三段逐点钉死、0.01 秒网格整段对账、醒着才有、重开从头起步、
   reset 清态、确定性、不占随机流；
2. 窗口链路：光标由静到动触发（真信号链 _anim_tick -> _poll_cursor ->
   _note_presence -> anim.welcome）、只触发一次、小抖动不算、睡着安静消费、
   动画关 / 光标功能关 / 开局 / 退场都不排、打字 / 戳消费掉离开；
3. 渲染（真窗口离屏双胞胎）：脸真的抬起来（纵向拉高、横向不动）；收完逐字节
   归零；关键帧落在重绘区里；
4. 素材纪律：一条命令能重生成，素材真在仓库里。

（设计数字：WELCOME_ 八个常量在 anim.py 顶部；调参速查表第 31 节。）
"""

from __future__ import annotations

import itertools
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import anim
from sammy.anim import Animator

pytestmark = pytest.mark.usefixtures("qapp")  # 窗口层要 QApplication

T0 = 30.0  # 热身后的时刻（初始凝视、眨眼早已跑起来）


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_dozeoff 同一套隔离）。"""
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


# ── 纯函数层：常量、形状、公式 ────────────────────


def test_welcome_constants_are_sane():
    """常量的量级与相互关系：抬起来比放回去快；「你走了」的尺子和休息提醒一致。"""
    from sammy import care

    assert anim.WELCOME_AWAY_S == care.ACTIVE_WINDOW_MINUTES * 60, (
        "「你走了」的尺子要和休息提醒用同一把（十分钟）"
    )
    assert 2 <= anim.WELCOME_MOVE_MIN <= 12, "触发阈值停在「碰一下鼠标」的量级"
    assert 0.05 <= anim.WELCOME_RISE_S <= 0.5, "抬起来太快像抽搐、太慢像发呆"
    assert 0.1 <= anim.WELCOME_HOLD_S <= 1.0, "顶着的时间要看得清"
    assert 0.2 <= anim.WELCOME_SETTLE_S <= 1.5, "放回去要有个尾巴"
    assert anim.WELCOME_RISE_S < anim.WELCOME_SETTLE_S, "注意到你该比放松下来快"
    assert 2 <= anim.WELCOME_LIFT_PX <= 8, "抬得太少看不见、太多像弹跳"
    assert 0.03 <= anim.WELCOME_STRETCH <= 0.12, "拉高停在好奇 / 哈欠同一个量级"
    assert anim.welcome_total() <= 2.0, "一次欢迎别演成一段节目"


def test_welcome_shape_three_segments():
    """三段一条线：抬起来（缓动）→ 顶住（恒 1）→ 放回去（缓动）；两头精确 0。"""
    rise, hold, settle = anim.WELCOME_RISE_S, anim.WELCOME_HOLD_S, anim.WELCOME_SETTLE_S
    assert anim.welcome_amount(-0.01) == 0.0
    assert anim.welcome_amount(0.0) == 0.0
    assert anim.welcome_amount(rise / 2) == pytest.approx(0.5)  # 缓动半程
    assert anim.welcome_amount(rise) == 1.0
    for k in (0.0, hold / 2, hold):
        assert anim.welcome_amount(rise + k) == 1.0
    assert 0.0 < anim.welcome_amount(rise + hold + settle / 2) < 1.0
    assert anim.welcome_amount(rise + hold + settle) == 0.0
    assert anim.welcome_amount(rise + hold + settle + 0.5) == 0.0
    up = [anim.welcome_amount(i * 0.01) for i in range(1, round(rise / 0.01))]
    assert all(b >= a for a, b in itertools.pairwise(up)), "抬起来段不是单调的"
    down = [anim.welcome_amount(rise + hold + i * 0.01) for i in range(1, round(settle / 0.01))]
    assert all(b <= a for a, b in itertools.pairwise(down)), "放回去段不是单调的"
    assert anim.welcome_total() == pytest.approx(rise + hold + settle)


def test_welcome_matches_formula_point_by_point():
    """整段逐点对账（0.01 秒网格）：上抬与拉高都按公式对齐到每个采样点。

    双胞胎同种子同喂法，只有一个差别：它演一次欢迎，对照不演。
    """
    a, b = Animator(seed=11), Animator(seed=11)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.welcome(T0)
    live = 0
    n = int(anim.welcome_total() / 0.01)
    for i in range(n + 1):
        t = round(T0 + i * 0.01, 6)
        k = anim.welcome_amount(t - T0)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert fa.dy == fb.dy - round(anim.WELCOME_LIFT_PX * k), t
        assert fa.stretch == pytest.approx(fb.stretch * (1.0 + anim.WELCOME_STRETCH * k)), t
        assert fa.squash == fb.squash and fa.dx == fb.dx, t
        assert (fa.gx, fa.gy) == (fb.gx, fb.gy), t
        assert fa.tilt == fb.tilt, t
        if k > 0:
            live += 1
    assert live >= 80, f"窗口里只有 {live} 个采样点在动"
    t_after = round(T0 + anim.welcome_total() + 0.3, 6)
    assert a.frame_at(t_after) == b.frame_at(t_after), "收完还没回到常态"


def test_welcome_only_draws_when_awake():
    """醒着才有（睡着走哈欠那条边）：calm 里一眼都不许有；收完回到孪生全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.welcome(T0)
    live = 0
    for tau in (0.05, 0.2, 0.4, 0.7, 1.0):
        t = round(T0 + tau, 6)
        if a.frame_at(t) != b.frame_at(t):
            live += 1
    assert live >= 4, f"醒着只有 {live} 个采样点不一样 —— 没演起来"
    for tau in (0.05, 0.2, 0.4, 0.7, 1.0):
        t = round(T0 + tau, 6)
        assert a.frame_at(t, calm=True) == b.frame_at(t, calm=True), (
            f"{t} 睡着时「欢迎回来」漏出来了"
        )
    t_after = round(T0 + anim.welcome_total() + 0.3, 6)
    assert a.frame_at(t_after) == b.frame_at(t_after), "收完还没回到常态"


def test_welcome_restart_starts_fresh():
    """中途再来一次：从抬起来重新起步（旧的那次作废）—— 与「只在那刻开始」全等。"""
    a, d = Animator(seed=17), Animator(seed=17)
    _walk(a, 0.0, T0)
    _walk(d, 0.0, T0)
    a.welcome(T0)
    assert a.frame_at(round(T0 + 0.5, 6)) != d.frame_at(round(T0 + 0.5, 6)), (
        "前提不成立：第一下没在演"
    )
    a.welcome(T0 + 0.6)  # 重开：旧的作废
    d.welcome(T0 + 0.6)
    for tau in (0.0, 0.1, 0.3, 0.6, 1.0, 1.2):
        t = round(T0 + 0.6 + tau, 6)
        assert a.frame_at(t) == d.frame_at(t), f"{t} 重开后没有从头起步"


def test_welcome_reset_clears_state():
    """时间线被拨动（reset）：旧的那次不作数。"""
    a, b = Animator(seed=19), Animator(seed=19)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.welcome(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.05, 0.3, 0.8):
        t = round(T0 + 0.2 + tau, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} reset 之后旧的那次还在"
    c = Animator(seed=21)
    c.welcome(T0)
    c.reset(T0 + 0.5)
    assert c._welcome_at == -99.0, "reset 后旧的那次没作数"


def test_welcome_is_deterministic():
    """同一条序列跑两遍逐值相等；顺带走一遍完整时间线。"""

    def run():
        a = Animator(seed=23)
        out = []
        for i in range(1, 201):
            t = round(i * 0.02, 6)  # 4 秒
            if i == 50:
                a.welcome(t)  # t = 1.0
            f = a.frame_at(t)
            out.append((round(f.stretch, 12), f.dx, f.dy, f.gx, f.gy))
        return out

    assert run() == run()


def test_welcome_does_not_touch_the_random_stream():
    """不掷随机数、不占随机流（同种子孪生对账靠它）。"""
    a, b = Animator(seed=5), Animator(seed=5)
    a.welcome(10.0)
    a.welcome(20.0)
    assert a._rng.random() == b._rng.random(), "welcome() 动了随机流 —— 孪生对比会散架"


# ── 窗口链路：光标由静到动（真信号链）──────────────

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import SammyWindow  # noqa: E402

SEED_WELCOME = 7


def _mk(seed: int = SEED_WELCOME) -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留「你回来」这一个变量。

    眨眼请出去（600 秒才眨一次）：上抬与拉高都和脸高对账，眨眼撞上就量不准。
    look_on / anim_on 默认开着（欢迎回来靠光标信号喂）。
    """
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    w.anim = anim.Animator(seed=seed, blink_gap=(600.0, 600.0))
    w.set_expression(2)  # 普通脸：画面里动的只有欢迎（和底层呼吸 / 漂移）
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    w.anim_on = True
    w.look_on = True
    return w


class _FakeCursor:
    """可拖动的假光标：位置用「相对脸中心」的设备像素表示。"""

    def __init__(self, win: SammyWindow):
        self.win = win
        self.dx = -400.0
        self.dy = 0.0

    def __call__(self):
        c = self.win.lay.face.center()
        s = self.win.scale
        lx = (c.x() + self.dx) * s + self.win._offset[0]
        ly = (c.y() + self.dy) * s + self.win._offset[1]
        return self.win.mapToGlobal(QPoint(round(lx), round(ly)))


def _step(w: SammyWindow):
    """推进一帧（离屏没有事件循环，paint 不会自己跑）。"""
    w._anim_tick()
    return w.anim.frame_at(w.anim_t)


def _arm_away(w: SammyWindow) -> None:
    """把「最近一次有人碰鼠标」往回拨十分钟 —— 模拟「你离开了」。"""
    w._presence_at = w.anim_t - (anim.WELCOME_AWAY_S + 1.0)


def test_window_welcomes_on_first_move_after_away(qapp):
    """真信号链：光标静够久（= 你走了）之后的第一次动 = 你回来 —— 只演一次。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)  # 建立参照
        _arm_away(w)
        _step(w)
        assert w._away is True, "前提不成立：十分钟没人碰，没安上「你走了」"
        assert w.anim._welcome_at == -99.0, "还没回来就演上了"
        cur.dx = -360.0  # 你碰了鼠标
        _step(w)
        assert w.anim._welcome_at == w.anim_t, "你回来了，它没抬头"
        assert w._away is False, "回来之后「你走了」没被消费"
        fired = w.anim._welcome_at
        _step(w)
        _step(w)
        assert w.anim._welcome_at == fired, "一次回来演了不止一次"
    finally:
        w.close()


def test_window_welcome_needs_a_real_move(qapp):
    """贴手小抖（小于阈值）不算「你回来」—— 攒够像素才算。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)
        _arm_away(w)
        _step(w)
        assert w._away is True
        cur.dx = -400.0 + (anim.WELCOME_MOVE_MIN - 1)  # 差一个像素的抖动
        _step(w)
        assert w.anim._welcome_at == -99.0, "小抖动也算回来了？"
        assert w._away is True, "小抖动不该消费掉「你走了」"
        cur.dx = -400.0 + anim.WELCOME_MOVE_MIN  # 刚好到阈值
        _step(w)
        assert w.anim._welcome_at == w.anim_t, "攒够像素了还没抬头"
    finally:
        w.close()


def test_window_welcome_is_silent_when_asleep(qapp):
    """睡着时不演 —— 安静消费掉；醒来之后再离开再回来才演（不叠着哈欠）。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)
        _arm_away(w)
        _step(w)
        assert w._away is True
        w.drives.asleep = True
        cur.dx = -360.0
        _step(w)
        assert w.anim._welcome_at == -99.0, "睡着还「欢迎回来」"
        assert w._away is False, "睡着的回来没被消费 —— 醒来会补演一次"
        w.drives.asleep = False
        _step(w)
        assert w._away is False, "刚回来、还在用电脑：不该马上又安上「你走了」"
        _arm_away(w)
        _step(w)
        assert w._away is True
        cur.dx = -320.0
        _step(w)
        assert w.anim._welcome_at == w.anim_t, "醒着回来却不演"
    finally:
        w.close()


def test_window_welcome_gates(qapp):
    """动画关 / 光标功能关 / 开局 / 退场 —— 都不排（和别的通道同一套闸门）。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        # 动画关：连检测都不做（关就关彻底）
        w.anim_on = False
        _step(w)
        _arm_away(w)
        cur.dx = -360.0
        _step(w)
        assert w.anim._welcome_at == -99.0 and w._away is False, "动画关着还欢迎"
        # 光标功能关：连读都不读（走不到检测那一步）
        w.anim_on = True
        w.look_on = False
        _step(w)
        _arm_away(w)
        cur.dx = -320.0
        _step(w)
        assert w.anim._welcome_at == -99.0, "SAMMY_LOOK 关了还欢迎"
        assert w._presence_ref is None, "光标功能关了还在读位置"
        # 开局 / 退场：不排（但当次离开要被消费掉 —— 不欠着）
        w.look_on = True
        _step(w)  # 重建参照
        _arm_away(w)
        _step(w)
        assert w._away is True
        w._boot_t0 = w.anim_t
        w._boot_lines = ("· 一条",)
        cur.dx = -280.0
        _step(w)
        assert w.anim._welcome_at == -99.0, "开局里还欢迎"
        assert w._away is False, "开局里的回来没被消费"
        w._boot_t0 = None
        w._boot_lines = ()
        _arm_away(w)
        _step(w)
        assert w._away is True
        w._shutdown_t0 = w.anim_t
        cur.dx = -240.0
        _step(w)
        assert w.anim._welcome_at == -99.0, "退场里还欢迎"
        assert w._away is False, "退场里的回来没被消费"
    finally:
        w.close()


def test_window_typing_counts_as_presence(qapp):
    """写长文不算离开：打字也会记一笔「你还在」—— 之后动鼠标不该「欢迎」你。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)
        _arm_away(w)
        _step(w)
        assert w._away is True
        w.input.setText("写")
        assert w._presence_at == w.anim_t, "打字没记「你还在」"
        assert w._away is False, "打字了还说「你走了」"
        cur.dx = -320.0
        _step(w)
        assert w.anim._welcome_at == -99.0, "写长文后动鼠标被误判成「你回来」"
    finally:
        w.close()


def test_window_poke_counts_as_presence(qapp):
    """戳一下 = 你还在（消费掉旧的那次离开）—— 戳完再动鼠标不该再欢迎一次。"""
    w = _mk()
    try:
        cur = _FakeCursor(w)
        w._cursor_now = cur
        _step(w)
        _arm_away(w)
        _step(w)
        assert w._away is True
        w.poke()
        assert w._away is False, "戳了还说「你走了」"
        cur.dx = -320.0
        _step(w)
        assert w.anim._welcome_at == -99.0, "戳完的这次回来被叠着演了欢迎"
    finally:
        w.close()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────


def _img_bytes(w: SammyWindow) -> bytes:
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(img.constBits())


def _clip(w: SammyWindow) -> QRect:
    """扫描区：脸框横向外扩 60，纵向只到 y=239 —— 状态行（y 246 起）不许进来。"""
    box = w.lay.face
    return QRect(box.left() - 60, 4, box.width() + 120, 236)


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


def test_welcome_lifts_and_stretches_the_face(qapp):
    """scale 1.0 双胞胎：顶住那一帧脸真的抬起来（纵向拉高、横向不动）；收完逐字节归零。

    实测（本组常数、seed 7、表情 2）：顶沿 -10 / 下沿 0 / 脸高 +10 / 横向 0。
    """
    a, b = _mk(), _mk()
    try:
        a.anim.welcome(8.5)
        clip = _clip(a)
        peak = round(8.5 + anim.WELCOME_RISE_S + anim.WELCOME_HOLD_S / 2, 6)
        a.anim_t = peak
        b.anim_t = peak
        x0a, y0a, x1a, y1a = _lit_bbox(a, clip)
        x0b, y0b, x1b, y1b = _lit_bbox(b, clip)
        assert y0b - y0a >= 5, f"顶沿没抬起来：{y0b - y0a}px"
        assert abs(y1a - y1b) <= 3, f"下沿不该明显跨：{y1a - y1b}px"
        assert (y1a - y0a) - (y1b - y0b) >= 4, f"脸没被拉高：{y1a - y0a} vs {y1b - y0b}"
        assert abs(x0a - x0b) <= 2 and abs(x1a - x1b) <= 2, "横向不该动"
        after = round(8.5 + anim.welcome_total() + 0.4, 6)
        a.anim_t = after
        b.anim_t = after
        assert _img_bytes(a) == _img_bytes(b), "「欢迎回来」收完还不回到常态"
    finally:
        a.close()
        b.close()


def test_welcome_key_moment_stays_inside_the_repainted_region(qapp):
    """抬到顶那一帧必须落在局部重绘区里 —— 在外面那圈不刷新（脸会花）。"""
    w = _mk()
    try:
        w.anim.welcome(8.5)
        clip = _clip(w)
        region = w._face_region()
        w.anim_t = round(8.5 + anim.WELCOME_RISE_S + anim.WELCOME_HOLD_S / 2, 6)
        x0, y0, x1, y1 = _lit_bbox(w, clip)
        deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        assert region.contains(deformed), f"抬起来时脸 {deformed} 冒出重绘区 {region}"
    finally:
        w.close()


# ── 纪律与素材 ────────────────────────────────────


def test_geometry_guard_covers_the_welcome_channel():
    """全局几何预算守卫（test_yawn）必须把「欢迎回来」算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "anim.WELCOME_LIFT_PX" in text, (
        "test_yawn 的全局预算守卫里没有「欢迎回来」的上抬 —— 调大就没人拦了"
    )
    assert "anim.WELCOME_STRETCH" in text, "守卫里漏了拉高项（和上抬是同一套两半）"


def test_welcome_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "welcome_preview.py").is_file()
    assert "welcome-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("welcome-strip.png", "welcome-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
