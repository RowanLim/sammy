"""上电环顾（自选小步·第二十次）——「上电之后，先看一圈」。

动机：开机自检（终端行滚完、画面淡入）之后，脸当场就进入了随机漂移 ——
一台刚上电的机器不该这样：它应该先站定一下，抬着头把左右两边各看一眼、
再回到正中，然后才开始发自己的呆。这一条给「开机」补上最后一道收尾：
自检是机器的（屏幕在滚），环顾是「它」的（脸在看）。点一下跳过自检也照样看 ——
「上电了」这件事已经发生过了。

三块机制：
- 形状：survey(at) 往凝视时间表里排三条**固定目标**（左、右、回中）——
  复用既有凝视盒（正负 GAZE_MAX_X/Y）与缓动（GAZE_EASE），半点新几何不加；
- 触发：窗口在 `_finish_boot`（自检播完或被人点跳过）那一刻安排一次；
  动画关或睡着时不排（醒来的那一下走哈欠那条边）；
- 纪律：固定目标、不掷随机数（同种子孪生对账靠它）；之后任何互动
  （光标、打字、思考、搬运）照常抢占 —— 它只是凝视表里的三条指令。

四层判据（和 test_dozeoff 一个框架）：
1. 纯函数：三条指令的时刻、目标、起步链逐点钉死；缓动与看定逐帧对账；
   回中之后漂移才接管；不占随机流；
2. 窗口链路：自检播完、点跳过都会环顾；动画关或睡着时不环顾；
3. 渲染（真窗口离屏双胞胎）：脸真的往左、右、回中走 —— 质心差与凝视差对账；
4. 素材纪律：一条命令能重生成，素材真在仓库里。

（设计数字：SURVEY_LEAD_S 等三个常量在 anim.py 顶部；调参速查表第 30 节。）
"""

from __future__ import annotations

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


def _glance_times(t0: float) -> list[float]:
    """三条环顾指令相对 t0 的计划时刻（左、右、回中）。"""
    return [t0 + anim.SURVEY_LEAD_S + i * anim.SURVEY_DWELL_S for i in range(3)]


# ── 纯函数层：形状 ──────────────────────────────


def test_survey_constants_stay_simple():
    """常量停在「看一眼」的量级：不磨蹭、不赶场，目标全在既有凝视盒里。"""
    assert isinstance(anim.SURVEY_TARGETS, tuple) and len(anim.SURVEY_TARGETS) == 3
    (lx, ly), (rx, ry), (cx, cy) = anim.SURVEY_TARGETS
    assert (lx, rx) == (-anim.GAZE_MAX_X, anim.GAZE_MAX_X), "两侧要扫到凝视盒两端"
    assert (cx, cy) == (0, 0), "最后要收回正中"
    for _x, y in anim.SURVEY_TARGETS:
        assert abs(_x) <= anim.GAZE_MAX_X and abs(y) <= anim.GAZE_MAX_Y, (
            "目标越出凝视盒 = 新的几何预算"
        )
    assert ly < 0 and ry < 0, "两侧都略抬眼（负 = 上）—— 探着头看"
    assert -ly == anim.SURVEY_LIFT_PX, "抬眼看的那格像素要和常量对上"
    assert 0.1 <= anim.SURVEY_LEAD_S <= 1.0, "站定太久像卡住、太短像没站稳"
    assert 0.8 <= anim.SURVEY_DWELL_S <= 2.5, "每边要看得出「看定」"
    assert anim.SURVEY_DWELL_S > anim.GAZE_EASE, "停留要长过缓动，否则一直在路上"


def test_survey_schedules_three_fixed_glances():
    """三条指令：时刻、目标、起步链 —— 与「更晚的旧目标被清干净」一起钉死。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    past = [g for g in a._gaze if g.t <= T0]
    assert [g for g in a._gaze if g.t > T0], "前提不成立：热身后本来就该有未来目标"
    a.survey(T0)
    assert [g for g in a._gaze if g.t <= T0] == past, "已经看过的历史不许动"
    fut = [g for g in a._gaze if g.t > T0]
    assert len(fut) == 3, f"环顾之后未来只留三条固定指令，实际 {len(fut)} 条"
    assert [g.t for g in fut] == pytest.approx(_glance_times(T0))
    assert [(g.x, g.y) for g in fut] == list(anim.SURVEY_TARGETS)
    f0 = a.frame_at(T0)
    assert (fut[0].fx, fut[0].fy) == (f0.gx, f0.gy), "第一条没有从当下实际位置起步"
    assert (fut[1].fx, fut[1].fy) == anim.SURVEY_TARGETS[0], "第二条没有从左站出发"
    assert (fut[2].fx, fut[2].fy) == anim.SURVEY_TARGETS[1], "第三条没有从右站出发"


def test_survey_glances_are_eased_and_held():
    """逐帧对账：站定段不动、缓动平滑到位、看定段稳、最后收在正中。"""
    a = Animator(seed=11)
    _walk(a, 0.0, T0)
    start = a.frame_at(T0)
    a.survey(T0)
    lead, dwell, ease = anim.SURVEY_LEAD_S, anim.SURVEY_DWELL_S, anim.GAZE_EASE
    (lx, ly), (rx, ry), _c = anim.SURVEY_TARGETS
    f = a.frame_at(round(T0 + lead / 2, 6))
    assert (f.gx, f.gy) == (start.gx, start.gy), "站定段就动了"
    f = a.frame_at(round(T0 + lead + ease, 6))
    assert (f.gx, f.gy) == (lx, ly), "没走到左边"
    mid = a.frame_at(round(T0 + lead + ease / 2, 6))
    lo, hi = sorted((start.gx, lx))
    assert lo <= mid.gx <= hi, "缓动越界"
    assert abs(mid.gx - (start.gx + lx) / 2) <= 1, "缓动不是平滑的半程"
    for tt in (round(T0 + lead + (ease + dwell) / 2, 6), round(T0 + lead + dwell, 6)):
        f = a.frame_at(tt)
        assert (f.gx, f.gy) == (lx, ly), f"{tt} 没有停在左站"
    f = a.frame_at(round(T0 + lead + dwell + ease, 6))
    assert (f.gx, f.gy) == (rx, ry), "没走到右边"
    f = a.frame_at(round(T0 + lead + 2 * dwell + ease, 6))
    assert (f.gx, f.gy) == (0, 0), "没收回正中"
    prev = a.frame_at(T0)
    t = T0
    for _ in range(round(anim.survey_total() / 0.05)):
        t = round(t + 0.05, 6)
        cur = a.frame_at(t)
        assert abs(cur.gx - prev.gx) <= 4 and abs(cur.gy - prev.gy) <= 4, f"{t} 位置跳了"
        prev = cur


def test_survey_ends_and_drift_resumes():
    """回中站稳之后，随机漂移才接管 —— 不许在环顾里抢戏，也不许永远不回来。"""
    a = Animator(seed=13)
    _walk(a, 0.0, T0)
    a.survey(T0)
    end = round(T0 + anim.SURVEY_LEAD_S + 2 * anim.SURVEY_DWELL_S, 6)
    f = a.frame_at(round(end + anim.GAZE_EASE, 6))
    assert (f.gx, f.gy) == (0, 0)
    after = [t for t in a.gaze_times(end + 40.0) if t > end + 1e-9]
    assert after, "环顾完了，漂移没接管"
    assert after[0] >= end + anim.GAZE_MIN_GAP - 1e-9, "漂移抢在回中刚站稳时就来了"


def test_survey_never_touches_the_random_stream():
    """不掷随机数、不占随机流：环顾自己花的抽数是零。

    两跑对账（眨眼请出去）：眨眼抽数也走主随机流，环顾把「什么时候抽
    扫视数」错开之后，只有把别的抽数请走，剩下的凝视抽值序列才能逐位对上。
    一跑环顾、一跑不环顾 —— 之后每次随机扫视抽到的 (x, y) 必须逐位相同，
    只差相位（谁先谁后）。哪天有人改成在 survey() 里抽数，这条会红。
    """
    a, b = Animator(seed=5), Animator(seed=5)
    a.survey(10.0)
    assert a._rng.random() == b._rng.random(), "survey() 动了随机流"
    c = Animator(seed=5, blink_gap=(600.0, 600.0))
    d = Animator(seed=5, blink_gap=(600.0, 600.0))
    _walk(c, 0.0, T0)
    _walk(d, 0.0, T0)
    c.survey(T0)
    # d 的表里挂着一条「热身前就抽好的未来目标」—— 环顾按纪律把它清掉了；
    # 对账要跳过它：它算的是 T0 之前那笔账，不是环顾之后的抽值。
    pending = len([g for g in d._gaze if g.t > T0])
    _walk(c, T0, T0 + 80.0)
    _walk(d, T0, T0 + 80.0)
    end = T0 + anim.SURVEY_LEAD_S + 2 * anim.SURVEY_DWELL_S
    rc = [g for g in c._gaze if g.t > end]
    rd = [g for g in d._gaze if g.t > T0][pending:]
    assert len(rc) >= 5 and len(rd) >= 5, "走了 80 秒，抽数怎么这么少"
    n = min(len(rc), len(rd))
    assert [(g.x, g.y) for g in rc[:n]] == [(g.x, g.y) for g in rd[:n]], (
        "环顾抢了随机流 —— 之后的扫视抽值被它蹭偏了"
    )
    assert c.blink_times(T0 + 80.0) == d.blink_times(T0 + 80.0), "眨眼表被环顾带偏"


def test_survey_is_deterministic():
    """同一条序列跑两遍逐值相等；顺带走一遍完整时间线。"""

    def run():
        a = Animator(seed=23)
        out = []
        for i in range(1, 301):
            t = round(i * 0.02, 6)  # 6 秒
            if i == 50:
                a.survey(t)  # t = 1.0
            f = a.frame_at(t)
            out.append((round(f.stretch, 12), f.gx, f.gy))
        return out

    assert run() == run()


# ── 链路：窗口在自检交班那一刻安排环顾 ──────────────

from PySide6.QtCore import QEvent, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402

from sammy import boot  # noqa: E402
from sammy.pet import SammyWindow  # noqa: E402

SEED_SURVEY = 7


def _win() -> SammyWindow:
    """稳态窗口：种子、表情、时间轴全钉住 —— 只留「环顾」一个变量。

    眨眼请出去（600 秒一眨）：压合和脸高都对账，撞上就量不准。
    """
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    w.anim = anim.Animator(seed=SEED_SURVEY, blink_gap=(600.0, 600.0))
    w.look_on = False  # 光标不参与（盯的是「环顾」这一件事）
    w.anim_t = 1.0
    return w


def _boot_end(w: SammyWindow) -> float:
    return w._boot_t0 + boot.total_seconds(len(w._boot_lines))


def test_window_surveys_right_after_the_boot(monkeypatch):
    """自检播完：交班同拍安排环顾，且只安排一次；左右两站真的走到。"""
    monkeypatch.setenv("SAMMY_BOOT", "on")
    monkeypatch.setenv("SAMMY_ANIM", "on")
    w = _win()
    try:
        assert w.begin_boot() is True
        w.anim_t = round(_boot_end(w) + 0.02, 6)
        w._anim_tick()  # 越过终点：这一步交班 + 环顾
        assert w._boot_t0 is None
        t0 = w.anim_t
        fut = [g for g in w.anim._gaze if g.t > t0]
        assert len(fut) == 3 and [(g.x, g.y) for g in fut] == list(anim.SURVEY_TARGETS), (
            "自检播完没有安排「看一圈」"
        )
        w.anim_t = round(t0 + 0.5, 6)
        w._anim_tick()
        fut2 = [g for g in w.anim._gaze if g.t > t0]
        assert len(fut2) == 3, "环顾被安排了不止一次"
        lead, dwell, ease = anim.SURVEY_LEAD_S, anim.SURVEY_DWELL_S, anim.GAZE_EASE
        f = w.anim.frame_at(round(t0 + lead + ease, 6))
        assert (f.gx, f.gy) == anim.SURVEY_TARGETS[0]
        f = w.anim.frame_at(round(t0 + lead + dwell + ease, 6))
        assert (f.gx, f.gy) == anim.SURVEY_TARGETS[1]
    finally:
        w.close()


def test_window_skip_click_still_surveys(monkeypatch):
    """点一下跳过自检：照样看一圈 —— 「上电了」这件事已经发生过了。"""
    monkeypatch.setenv("SAMMY_BOOT", "on")
    monkeypatch.setenv("SAMMY_ANIM", "on")
    w = _win()
    try:
        assert w.begin_boot() is True
        w.anim_t = round(w._boot_t0 + 0.8, 6)
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(220, 132),
            QPointF(220, 132),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        w.mousePressEvent(ev)
        assert w._boot_t0 is None, "没跳过"
        t0 = w.anim_t
        fut = [g for g in w.anim._gaze if g.t > t0]
        assert len(fut) == 3 and [(g.x, g.y) for g in fut] == list(anim.SURVEY_TARGETS), (
            "跳过之后没有安排「看一圈」"
        )
    finally:
        w.close()


def test_window_no_survey_when_anim_off_or_asleep(monkeypatch):
    """动画关或睡着时：交班也不环顾（关就该关彻底；醒来走哈欠那条边）。"""
    monkeypatch.setenv("SAMMY_BOOT", "on")
    monkeypatch.setenv("SAMMY_ANIM", "on")
    w = _win()
    try:
        assert w.begin_boot() is True
        w.anim_on = False
        calls = []
        w.anim.survey = lambda at: calls.append(at)  # type: ignore[method-assign]
        w.anim_t = round(_boot_end(w) + 0.02, 6)
        w._anim_tick()
        assert w._boot_t0 is None
        assert calls == [], "动画关着还安排环顾"
    finally:
        w.close()
    w2 = _win()
    try:
        assert w2.begin_boot() is True
        w2.drives.asleep = True
        calls = []
        w2.anim.survey = lambda at: calls.append(at)  # type: ignore[method-assign]
        w2.anim_t = round(_boot_end(w2) + 0.02, 6)
        w2._anim_tick()
        assert w2._boot_t0 is None
        assert calls == [], "睡着时还安排环顾"
    finally:
        w2.close()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────


def _lit_centroid(w: SammyWindow, clip: QRect) -> tuple[float, float]:
    """clip 里「亮像素」（按 faces.LIT 常量读色）的质心。"""
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


def test_survey_moves_the_face_left_right_and_back():
    """双胞胎实测：屏幕上的脸真的先往左、再往右、回到正中 —— 质心差与凝视差对账。"""
    a, b = _win(), _win()
    try:
        b.anim.survey = lambda at: None  # type: ignore[method-assign]  # 对照：不环顾
        t0 = 8.0
        a.anim.survey(t0)
        lead, dwell, ease = anim.SURVEY_LEAD_S, anim.SURVEY_DWELL_S, anim.GAZE_EASE
        samples = (
            ("左看", round(t0 + lead + ease + 0.2, 6), anim.SURVEY_TARGETS[0]),
            ("右看", round(t0 + lead + dwell + ease + 0.2, 6), anim.SURVEY_TARGETS[1]),
            ("回中", round(t0 + lead + 2 * dwell + ease + 0.2, 6), (0, 0)),
        )
        f = a.lay.face
        clip = QRect(f.left() - 60, 4, f.width() + 120, 236)
        for name, tt, want in samples:
            a.anim_t = tt
            b.anim_t = tt
            fa = a.anim.frame_at(tt)
            fb = b.anim.frame_at(tt)
            assert (fa.gx, fa.gy) == want, f"{name}：视线没到位 {(fa.gx, fa.gy)}"
            ca = _lit_centroid(a, clip)
            cb = _lit_centroid(b, clip)
            dx, dy = ca[0] - cb[0], ca[1] - cb[1]
            assert abs(dx - (fa.gx - fb.gx)) <= 3.5, f"{name}：横向质心差 {dx:.1f} 与凝视差对不上"
            assert abs(dy - (fa.gy - fb.gy)) <= 3.5, f"{name}：纵向质心差 {dy:.1f} 与凝视差对不上"
    finally:
        a.close()
        b.close()


# ── 纪律与素材 ────────────────────────────────────


def test_survey_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "survey_preview.py").is_file()
    assert "survey-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("survey-strip.png", "survey-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
