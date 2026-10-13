"""歪头（自选小步·第十七次）——「被戳了，歪着脑袋看你（唔？）」。

动机：戳一戳是最常用的互动，却一直没有身体语言 —— 光标凝视管「手在动」、
打字凝视管「你在写」、摸摸头管「手停在脸上」、搬运凝视管「被拎着」，
只有戳一戳戳完就完了（换张脸 + 说句话，脸上什么都不会做）。歪头补上它：
醒着被戳，脑袋轻快一歪（像「唔？」）、停一小会、再直回来。它也是第一条
旋转形变 —— 此前所有形变都是平移和缩放，整个动画语汇里没有「转」。

两块机制：
- 形状：tilt_amount 一条三段曲线（歪过去，停住，直回来），纯函数逐点
  可钉；歪过去（TILT_RISE_S）比直回来（TILT_FALL_S）快 —— 轻快的一歪是
  「唔？」，慢吞吞地歪像犯困。
- 方向：一次一换（第一下左半边沉、第二下右半边沉 —— 不掷随机数，理由同
  抽动和喷嚏）。

窗口那层的闸门（都写在 poke 里）：睡着被戳是「叫醒」（哈欠那条路 —— 两条
不叠着演）、累趴不歪、动画关不歪；思考中 poke 本来就早退（原行为，不重复管）。

四层判据（和 test_hum 与 test_sneeze 一个框架）：
1. 纯函数：曲线逐点对账、两端精确 0、各段单调、方向交替、只加不改、
   睡着不歪、确定性；
2. 几何与真渲染：标记点实测 —— 绕脸中心转的是精确 TILT_MAX_DEG（与公式
   误差不超过 0.75px）；真脸上主轴角方向对、量级对；改动的像素全部落在
   重绘区里；
3. 渲染（真窗口离屏双胞胎）：歪两次一边一下、收完与孪生逐字节一致；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：TILT_ 开头的常量在 anim.py 顶部；调参速查表第 27 节。旋转取样保持
最近邻 —— 和全工程一致，理由与实测写在 pet 的 _draw_face 注释里。）
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

T0 = 30.0  # 热身后的时刻（初始凝视和眨眼早已跑起来）


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet 与 test_hum 同一套隔离）。"""
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


# ── 纯函数层：曲线与方向 ──────────────────────────


def test_tilt_constants_stay_subtle():
    """数字要先像样：歪得看得出来、又不像要把脑袋倒过去；一整下别拖太长。"""
    assert 3.0 <= anim.TILT_MAX_DEG <= 8.0, "歪太浅读不出来，太深像要倒了"
    for name in ("TILT_RISE_S", "TILT_HOLD_S", "TILT_FALL_S"):
        assert getattr(anim, name) > 0.0, name
    assert anim.TILT_RISE_S < anim.TILT_FALL_S, "歪过去要轻快、直回来慢一点"
    assert anim.tilt_total() <= 2.0, "被戳一下的回应，别拖成一段舞蹈"


def test_tilt_shape_rises_holds_and_falls():
    """三段拼一条时间线：歪过去缓入、停住恒 1、直回来缓出；两头精确为 0。"""
    assert anim.tilt_amount(-0.1) == 0.0, "还没开始就不该有"
    assert anim.tilt_amount(0.0) == 0.0, "从正位起步"
    assert anim.tilt_amount(anim.TILT_RISE_S / 2) == pytest.approx(0.5)
    assert anim.tilt_amount(anim.TILT_RISE_S) == pytest.approx(1.0)
    assert anim.tilt_amount(anim.TILT_RISE_S + anim.TILT_HOLD_S - 1e-6) == pytest.approx(1.0)
    fall_mid = anim.TILT_RISE_S + anim.TILT_HOLD_S + anim.TILT_FALL_S / 2
    assert anim.tilt_amount(fall_mid) == pytest.approx(0.5)
    assert anim.tilt_amount(anim.tilt_total()) == pytest.approx(0.0), "直回来就该是零"
    assert anim.tilt_amount(anim.tilt_total() + 5.0) == 0.0


def test_tilt_is_smooth_no_jumps():
    """拉网走一遍：没有跳变（方波会读成故障）；三段各自单调。"""
    vals = [anim.tilt_amount(i * 0.005) for i in range(0, int(anim.tilt_total() / 0.005) + 3)]
    steps = [abs(b - a) for a, b in pairwise(vals)]
    assert max(steps) <= 0.05, f"曲线上有跳变（最大一步 {max(steps):.3f}）"
    up = [anim.tilt_amount(anim.TILT_RISE_S * i / 20) for i in range(21)]
    assert all(b >= a for a, b in pairwise(up)), "歪过去段不单调"
    mid = [anim.tilt_amount(anim.TILT_RISE_S + 0.05 * i) for i in range(11)]
    assert all(v == pytest.approx(1.0) for v in mid), "停住段应该是恒 1"
    fall = [
        anim.tilt_amount(anim.TILT_RISE_S + anim.TILT_HOLD_S + anim.TILT_FALL_S * i / 20)
        for i in range(21)
    ]
    assert all(b <= a for a, b in pairwise(fall)), "直回来段不单调"


def test_tilt_direction_alternates():
    """方向一次一换：第一下负角（左半沉）、第二下正角、第三下又回来 —— 不掷随机数。"""
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.tilt(T0)
    hold = round(T0 + anim.TILT_RISE_S + 0.1, 6)
    assert a.frame_at(hold).tilt == -anim.TILT_MAX_DEG, "第一下方向或幅度不对"
    t2 = round(T0 + anim.tilt_total() + 1.0, 6)
    a.tilt(t2)
    assert a.frame_at(round(t2 + anim.TILT_RISE_S + 0.1, 6)).tilt == anim.TILT_MAX_DEG, (
        "第二下没换边"
    )
    t3 = round(t2 + anim.tilt_total() + 1.0, 6)
    a.tilt(t3)
    assert a.frame_at(round(t3 + anim.TILT_RISE_S + 0.1, 6)).tilt == -anim.TILT_MAX_DEG, (
        "第三下又该换回来了"
    )


def test_tilt_does_not_touch_rng_stream():
    """方向交替不掷随机数：歪过之后，眨眼和凝视的表和孪生一模一样。"""
    a, b = Animator(seed=7), Animator(seed=7)
    for i in range(1, 100):
        t = round(i * 0.05, 6)
        a.frame_at(t)
        b.frame_at(t)
        if i in (30, 70):
            a.tilt(t)
    assert a.blink_times(120.0) == b.blink_times(120.0), "歪头动了眨眼随机流"
    assert a.gaze_times(120.0) == b.gaze_times(120.0), "歪头动了凝视随机流"


def test_tilt_only_adds_other_channels_do_not_move():
    """只歪的一方与完全不歪的孪生：别的通道一个都不许动；窗外全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.tilt(T0)
    live = 0
    end = T0 + anim.tilt_total()
    for i in range(1, 161):
        t = round(T0 + i * 0.025, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (
            fa.squash,
            fa.dx,
            fa.dy,
            fa.pop,
            fa.gx,
            fa.gy,
            fa.stretch,
            fa.talk_y,
            fa.talk_sq,
        ) == (
            fb.squash,
            fb.dx,
            fb.dy,
            fb.pop,
            fb.gx,
            fb.gy,
            fb.stretch,
            fb.talk_y,
            fb.talk_sq,
        ), f"{t} 时别的通道被歪头带偏了"
        if t < end:
            if fa.tilt != fb.tilt:
                live += 1
        else:
            assert fa.tilt == fb.tilt == 0.0, f"{t} 歪完之后还没回正"
    assert live >= 40, f"窗口里只有 {live} 帧真的歪着 —— 没歪起来"


def test_tilt_matches_formula_point_by_point():
    """整段逐点对账（0.02 秒网格）：tilt 等于方向乘幅度乘包络，对齐到每个采样点。"""
    a, b = Animator(seed=11), Animator(seed=11)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.tilt(T0)
    d = a._tilt_dir
    live = 0
    for i in range(0, 131):
        t = round(T0 + i * 0.02, 6)
        want = d * anim.TILT_MAX_DEG * anim.tilt_amount(t - T0)
        assert a.frame_at(t).tilt == want, t
        assert b.frame_at(t).tilt == 0.0, t
        if want != 0.0:
            live += 1
    assert live >= 55, f"窗口里只有 {live} 帧歪着"


def test_tilt_suppressed_when_calm_and_resumes_after():
    """睡着不歪（定格优先）；醒来接着歪（不是半路掐掉重来）。"""
    a, b = Animator(seed=15), Animator(seed=15)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.tilt(T0)
    for i in range(1, 20):
        t = round(T0 + i * 0.05, 6)
        assert a.frame_at(t, calm=True).tilt == 0.0, f"{t} 睡着还歪头"
    mid = round(T0 + anim.TILT_RISE_S + 0.2, 6)
    assert a.frame_at(mid).tilt != b.frame_at(mid).tilt, "醒来没接着歪（被 calm 掐了）"


def test_tilt_restart_starts_fresh():
    """歪到一半再来一下：从正位重新起步、方向翻面 —— 与公式对账。"""
    a = Animator(seed=17)
    _walk(a, 0.0, T0)
    a.tilt(T0)
    assert a.frame_at(T0 + 0.6).tilt < 0.0, "前提不成立：a 没有在歪"
    t2 = T0 + 0.8
    a.tilt(t2)  # 第二下（方向翻面 = 正角）
    for tau in (0.0, 0.1, 0.25, 0.6, 1.0):
        t = round(t2 + tau, 6)
        want = anim.TILT_MAX_DEG * anim.tilt_amount(t - t2)
        assert a.frame_at(t).tilt == want, f"{t} 重开后没有从头起步"


def test_tilt_reset_clears_state():
    """时间线被拨动（reset）：旧的那下不作数。"""
    a, b = Animator(seed=19), Animator(seed=19)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.tilt(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.05, 0.2, 0.5, 1.2):
        t = round(T0 + 0.2 + tau, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} reset 之后旧的那下还在"
    assert a._tilt_at == -99.0


def test_tilt_is_deterministic():
    """同一条序列跑两遍逐值相等（种子相同 = 演出相同）。"""

    def run():
        a = Animator(seed=29)
        out = []
        for i in range(1, 161):
            t = round(i * 0.05, 6)
            if i == 40:
                a.tilt(t)
            if i == 120:
                a.tilt(t)
            f = a.frame_at(t)
            out.append((round(f.squash, 12), f.dy, f.dx, round(f.tilt, 12), f.gx, f.gy))
        return out

    assert run() == run()


def test_geometry_guard_covers_the_tilt_channel():
    """全局几何预算守卫（test_yawn）必须把歪头的旋转算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "anim.TILT_MAX_DEG" in text, (
        "test_yawn 的全局预算守卫里没有歪头的旋转通道 —— 调大 TILT_MAX_DEG 就没人拦了"
    )


# ── 窗口链路：戳一戳 → 歪头 ────────────────────────

from sammy.pet import POKE_FACES, SammyWindow  # noqa: E402


def _mk_window() -> SammyWindow:
    """稳态窗口：种子、表情、时间轴全钉住 —— 只留歪头这一个变量。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    w.anim = anim.Animator(seed=7, blink_gap=(600.0, 600.0))
    w.look_on = False  # 光标不参与（盯的是歪头这一件事）
    w.set_expression(2)  # 普通脸
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    return w


def test_window_poke_tilts_when_awake(qapp):
    """链路：醒着被戳会排上歪头；连着戳第二下会换边。"""
    w = _mk_window()
    try:
        w.drives.last_update = time.time() + 10.0  # 冻结驱力漂移（边界用例的老规矩）
        w.drives.asleep = False
        w.drives.energy = 0.8
        w.anim_t = 30.0
        w.poke()
        assert w.anim._tilt_at == 30.0, "醒着被戳没有歪头"
        f = w.anim.frame_at(round(30.0 + anim.TILT_RISE_S + 0.05, 6))
        assert f.tilt < 0.0, "第一下的方向不对"
        w.anim_t = 40.0
        w.poke()
        assert w.anim._tilt_at == 40.0
        f2 = w.anim.frame_at(round(40.0 + anim.TILT_RISE_S + 0.05, 6))
        assert f2.tilt > 0.0, "第二下没换边"
    finally:
        w.close()


def test_window_poke_gates_asleep_exhausted_animoff(qapp):
    """闸门：睡着被戳是叫醒（哈欠，不歪）、累趴不歪、动画关不歪、思考中早退。"""
    w = _mk_window()
    try:
        w.drives.last_update = time.time() + 10.0
        # 睡着被戳：这一下是叫醒 —— 哈欠排上，歪头不许来凑热闹
        w.drives.asleep = True
        w.drives.energy = 0.19  # 一戳（加 0.02）刚好过唤醒线
        w.anim_t = 50.0
        w.poke()
        assert not w.drives.asleep, "前提不成立：没有被戳醒"
        assert w.anim._yawn_at == 50.0, "睡着被戳没有醒来的哈欠"
        assert w.anim._tilt_at == -99.0, "睡着被戳还歪头（该是哈欠那条路）"
        # 累趴（醒着、但够不着唤醒线）：不歪
        w.drives.asleep = False
        w.drives.energy = 0.05
        w.anim_t = 60.0
        w.poke()
        assert w.anim._tilt_at == -99.0, "累趴还歪头"
        # 动画关：不歪
        w.drives.energy = 0.8
        w.anim_on = False
        w.anim_t = 70.0
        w.poke()
        assert w.anim._tilt_at == -99.0, "动画关着还歪头"
        w.anim_on = True
        # 思考中：poke 本来就早退（原行为），歪头也不许排
        w.thinking = True
        w.anim_t = 75.0
        w.poke()
        assert w.anim._tilt_at == -99.0, "思考中还排歪头"
        w.thinking = False
        w.anim_t = 80.0
        w.poke()
        assert w.anim._tilt_at == 80.0, "都恢复了还不歪"
    finally:
        w.close()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402

from sammy import faces  # noqa: E402

SEED_TILT = 7


def _mk_twin() -> SammyWindow:
    return _mk_window()


def _lit_points(w: SammyWindow, clip):
    """矩形里的「不透明亮像素」（判据从 faces.LIT 常量读，不写死色相）。"""
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
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
    """亮像素云的主轴角（度）和质心。旋转会把主轴角精确地转过去 —— 拿它量「真的在转」。"""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    m20 = sum((p[0] - mx) ** 2 for p in pts) / n
    m02 = sum((p[1] - my) ** 2 for p in pts) / n
    m11 = sum((p[0] - mx) * (p[1] - my) for p in pts) / n
    return 0.5 * math.degrees(math.atan2(2 * m11, m20 - m02)), (mx, my)


def test_tilt_rotates_the_real_face(qapp):
    """真脸实测：歪两次一边一下（主轴角反向偏转）、收完与孪生逐字节一致。

    备注：主轴角是从「色彩阈值后的亮像素云」量出来的 —— 阈值会啃掉一点
    抗锯齿边缘，读数约为标称角的 0.8 倍（精确角度由下面的标记点用例钉住，
    这条管「人眼看得见的那种转」）。
    """
    a, b = _mk_twin(), _mk_twin()
    try:
        clip = a.lay.face.adjusted(-30, -30, 30, 30)
        a.anim.tilt(8.0)

        def sample(tau):
            t = round(8.0 + tau, 6)
            a.anim_t = b.anim_t = t
            aa, ca = _moment_angle(_lit_points(a, clip))
            ab, cb = _moment_angle(_lit_points(b, clip))
            return aa - ab, (ca[0] - cb[0], ca[1] - cb[1])

        d_mid, _c_mid = sample(anim.TILT_RISE_S / 2)  # 起手一半
        d_hold, c_hold = sample(anim.TILT_RISE_S + 0.1)  # 满幅停住
        assert d_mid < 0.0 and d_hold < 0.0, f"第一下没往左转（{d_mid:.2f}/{d_hold:.2f}）"
        assert abs(d_mid) < abs(d_hold) + 0.2, "起手一半时转得比满幅还猛？"
        assert 3.0 <= abs(d_hold) <= 5.6, f"满幅只量到 {abs(d_hold):.2f} 度 —— 不太像 5 度"
        assert abs(c_hold[0]) <= 2.5 and abs(c_hold[1]) <= 2.5, "绕中心转不该把重心搬走"

        # 第二下：换边
        t2 = round(8.0 + anim.tilt_total() + 1.0, 6)
        a.anim.tilt(t2)
        a.anim_t = b.anim_t = round(t2 + anim.TILT_RISE_S + 0.1, 6)
        da, _ = _moment_angle(_lit_points(a, clip))
        db, _ = _moment_angle(_lit_points(b, clip))
        assert 3.0 <= (da - db) <= 5.6, f"第二下没往右转（{da - db:.2f} 度）"

        # 收完：逐字节与孪生一致
        end = round(t2 + anim.tilt_total() + 0.4, 6)
        a.anim_t = b.anim_t = end
        ia = a.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        ib = b.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        assert bytes(ia.constBits()) == bytes(ib.constBits()), "歪完还不回到常态"
    finally:
        a.close()
        b.close()


def test_tilt_marker_turns_exactly_the_configured_angle(qapp, monkeypatch):
    """标记点实测（真绘制管线）：绕脸中心转的，就是 TILT_MAX_DEG 这个角度。

    手动把「脸」换成一颗已知位置的红点（monkeypatch face_pixmap），走的是
    真窗口的真绘制代码；同一时刻与孪生（没歪的它）对比，看红点是不是转到了
    旋转公式的落点 —— 与公式误差不超过 0.75px（最近邻取样的圆整量级）。
    """
    a, b = _mk_twin(), _mk_twin()
    try:
        box = a.lay.face
        dot = (120, 60)  # 红点在脸框内（pixmap 本地坐标）

        def fake_pixmap(index, size):
            pm = QPixmap(size)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.fillRect(dot[0] - 5, dot[1] - 5, 10, 10, QColor(255, 0, 0))
            p.end()
            return pm

        monkeypatch.setattr(faces, "face_pixmap", fake_pixmap)
        monkeypatch.setattr(faces, "motion_frame", lambda index, t: None)

        def centroid(w):
            img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
            buf = bytes(img.constBits())
            stride = img.bytesPerLine()
            xs = ys = n = 0
            for y in range(img.height()):
                row = y * stride
                for x in range(img.width()):
                    i = row + x * 4
                    bch, g, r, al = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
                    if al > 150 and r > 180 and g < 90 and bch < 90:
                        xs += x
                        ys += y
                        n += 1
            assert n > 20, f"红点没画出来（{n} 像素）"
            return xs / n, ys / n

        a.anim.tilt(8.0)
        cx, cy = box.center().x(), box.center().y()
        for tau in (anim.TILT_RISE_S + 0.1, anim.TILT_RISE_S + anim.TILT_HOLD_S * 0.6):
            t = round(8.0 + tau, 6)
            a.anim_t = b.anim_t = t
            qa, qb = centroid(a), centroid(b)
            th = math.radians(a.anim.frame_at(t).tilt)
            c, s = math.cos(th), math.sin(th)
            vx, vy = qb[0] - cx, qb[1] - cy
            ex, ey = vx * c - vy * s, vx * s + vy * c
            exx, eyy = cx + ex, cy + ey
            assert abs(qa[0] - exx) <= 0.75, f"{t}s 时红点 x 差 {qa[0] - exx:+.2f}px"
            assert abs(qa[1] - eyy) <= 0.75, f"{t}s 时红点 y 差 {qa[1] - eyy:+.2f}px"
        # 转到位也能反向验一次：tilt 归零后红点回原位
        a.anim_t = b.anim_t = round(8.0 + anim.tilt_total() + 0.3, 6)
        qa, qb = centroid(a), centroid(b)
        assert abs(qa[0] - qb[0]) <= 0.75 and abs(qa[1] - qb[1]) <= 0.75, "收完了红点还没回原位"
    finally:
        a.close()
        b.close()


def test_tilt_changed_pixels_stay_inside_the_repaint_region(qapp):
    """旋转改到的每一个像素都必须落在重绘区里 —— 在外面就不会刷新（脸会花）。"""
    a, b = _mk_twin(), _mk_twin()
    try:
        a.anim.tilt(8.0)
        t = round(8.0 + anim.TILT_RISE_S + 0.1, 6)
        a.anim_t = b.anim_t = t
        ia = a.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        ib = b.grab().toImage().convertToFormat(QImage.Format_ARGB32)
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
        assert inside > 4500, f"只改了 {inside} 个像素 —— 看着不像在转"
        assert outside == 0, f"有 {outside} 个改动像素落在重绘区外 —— 那些帧不会刷新"
    finally:
        a.close()
        b.close()


def test_tilt_renders_on_every_poke_face(qapp):
    """戳一戳随便抽哪张脸都要转得对：抽中的 5 张脸逐张渲染、改动都落在重绘区里。"""
    a, b = _mk_twin(), _mk_twin()
    try:
        region = a._face_region()
        for idx in POKE_FACES:
            for w in (a, b):
                w.anim = anim.Animator(seed=SEED_TILT, blink_gap=(600.0, 600.0))
                w.anim_t = 8.0
                w.set_expression(idx)
            a.anim.tilt(8.0)
            t = round(8.0 + anim.TILT_RISE_S + 0.1, 6)
            a.anim_t = b.anim_t = t
            ia = a.grab().toImage().convertToFormat(QImage.Format_ARGB32)
            ib = b.grab().toImage().convertToFormat(QImage.Format_ARGB32)
            ba, bb = bytes(ia.constBits()), bytes(ib.constBits())
            sa, sb = ia.bytesPerLine(), ib.bytesPerLine()
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
            assert inside > 1200, f"第 {idx} 张脸歪起来只改了 {inside} 个像素"
            assert outside == 0, f"第 {idx} 张脸有 {outside} 个改动像素在重绘区外"
    finally:
        a.close()
        b.close()


# ── 纪律与素材 ────────────────────────────────────


def test_tilt_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "tilt_preview.py").is_file()
    assert "tilt-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("tilt-strip.png", "tilt-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
