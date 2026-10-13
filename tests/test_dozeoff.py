"""入睡的一下（自选小步·第十九次）——「撑不住了」：困到最后头一沉，睡过去。

动机：醒来有哈欠（第八次）、睡着有 Z 和抽动（第七 / 十二次）—— 唯独「真的
睡过去」那一下此前是瞬移：睡脸直接切过来（一次交叉淡化），没有过程。这一条
把它补上：「醒着 → 睡着」那一刻，整脸慢慢往下沉、眼睛合上、屏一会儿
（睡实了）、再松回睡姿 —— 它是「睡着」的入口，和哈欠（「醒来」的出口）
对称；至此昼夜动作链闭合：困（点头）→ 睡着（这一下）→ 睡相（Z / 抽动）
→ 醒（哈欠）。

两块机制：
- 形状：dozeoff_amount 一条曲线（沉下去 → 屏住 → 松回睡姿），纯函数逐点可钉；
- 触发：窗口在 `_tick` 里看到「醒着 → 睡着」这条边时安排一次（一段睡觉只有
  一次）；动画关着不演、唤醒方向（戳 / 说话 / 睡饱）不演 —— 那是哈欠那条边。

四层判据（和 test_twitch 一个框架）：
1. 纯函数：曲线时间线逐点对账、只加不改（醒着一眼都不许有）、reset 清态、
   确定性、不占随机流；
2. 窗口链路：睡着那一刻才演、动画关 / 唤醒方向不许演；
3. 渲染（真窗口离屏双胞胎）：纵向往下沉 + 脸被压合（数字对账）、收完逐字节
   归零、关键帧落在局部重绘区里；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：六个 DOZEOFF_* 常量在 anim.py 顶部；调参速查表第 29 节。）
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
    """别碰用户真实的状态文件（和 test_twitch / test_doze 同一套隔离）。"""
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


# ── 纯函数层：曲线 ──────────────────────────────


def test_dozeoff_constants_stay_subtle():
    """常量必须停在「撑不住了」的量级：慢、深一点、比点头更合眼，但不夸张。"""
    total = anim.dozeoff_total()
    assert 1.5 <= total <= 3.5, f"整段 {total}s —— 太短读不出「慢慢塌」，太长像卡住"
    assert 0.5 <= anim.DOZEOFF_SINK_S <= 1.6, "沉下去要慢（撑不住了是塌，不是点头）"
    assert 0.3 <= anim.DOZEOFF_HOLD_S <= 0.9, "沉到底要停得够长（睡实了的那一瞬）"
    assert 0.5 <= anim.DOZEOFF_SETTLE_S <= 1.5, "松回来也要有过程"
    assert isinstance(anim.DOZEOFF_SINK_PX, int), "下沉量按整像素走"
    assert 4 <= anim.DOZEOFF_SINK_PX <= 10, "比呼吸（±2）明显一档就够"
    assert anim.DOZEOFF_SINK_PX > anim.NOD_SINK_PX, "这一下要比点头更深（是真睡过去）"
    assert 0.3 <= anim.DOZEOFF_SQUINT_MIN <= 0.6, "合得太死像眨眼，合得太浅像没合"
    assert anim.DOZEOFF_SQUINT_MIN < anim.NOD_SQUINT_MIN, "比点头再合一点：眼皮是真落下了"


def test_dozeoff_shape_sinks_holds_and_settles():
    """形状三段拼一条时间线：沉下去 → 屏住 → 松回来；两头精确为 0、两段单调。"""
    s, h, st = anim.DOZEOFF_SINK_S, anim.DOZEOFF_HOLD_S, anim.DOZEOFF_SETTLE_S
    assert anim.dozeoff_amount(-0.1) == 0.0, "还没开始就不该有"
    assert anim.dozeoff_amount(0.0) == 0.0, "从静息起步"
    assert anim.dozeoff_amount(s / 2) == pytest.approx(0.5), "沉到一半正好一半"
    assert anim.dozeoff_amount(s) == pytest.approx(1.0)
    assert anim.dozeoff_amount(s + h / 2) == 1.0, "屏住段是满的"
    k = s + h
    assert anim.dozeoff_amount(k + st / 2) == pytest.approx(0.5)
    assert anim.dozeoff_amount(anim.dozeoff_total()) == 0.0, "松完就该是零"
    assert anim.dozeoff_amount(anim.dozeoff_total() + 5.0) == 0.0
    up = [anim.dozeoff_amount(s * i / 20) for i in range(21)]
    assert all(b >= a for a, b in pairwise(up)), "沉下去段不单调"
    down = [anim.dozeoff_amount(k + st * i / 40) for i in range(41)]
    assert all(b <= a for a, b in pairwise(down)), "松回来段不单调"
    assert anim.dozeoff_total() == pytest.approx(s + h + st)


def test_dozeoff_only_draws_when_calm():
    """醒着 = 一眼都不许有（calm 定生死 —— 和抽动同一套）；收完回到孪生全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.dozeoff(T0)
    for tau in (0.0, 0.2, 0.6, 1.4, 2.3):
        t = round(T0 + tau, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} 醒着时「入睡的一下」漏出来了"
    live = 0
    for tau in (0.05, 0.55, 1.4, 2.2):
        t = round(T0 + tau, 6)
        if a.frame_at(t, calm=True) != b.frame_at(t, calm=True):
            live += 1
    assert live >= 3, f"calm 里只有 {live} 个采样点不一样 —— 没演起来"
    t_after = round(T0 + anim.dozeoff_total() + 0.3, 6)
    assert a.frame_at(t_after, calm=True) == b.frame_at(t_after, calm=True), "收完还没回到常态"


def test_dozeoff_matches_formula_point_by_point():
    """整段逐点对账（0.01 秒网格）：下沉与压合都按公式对齐到每个采样点。"""
    a = Animator(seed=11)
    _walk(a, 0.0, T0)
    a.dozeoff(T0)
    live = 0
    n = int(anim.dozeoff_total() / 0.01)
    for i in range(n + 1):
        t = round(T0 + i * 0.01, 6)
        k = anim.dozeoff_amount(t - T0)
        f = a.frame_at(t, calm=True)
        base = round(
            anim.CALM_FACTOR
            * anim.BREATH_AMPLITUDE
            * math.sin(2 * math.pi * t / anim.BREATH_PERIOD)
        )
        assert f.dy == base + round(anim.DOZEOFF_SINK_PX * k), t
        assert f.squash == pytest.approx(1.0 - (1.0 - anim.DOZEOFF_SQUINT_MIN) * k), t
        if k > 0:
            live += 1
    assert live >= 200, f"窗口里只有 {live} 帧在动"
    t_after = round(T0 + anim.dozeoff_total() + 0.3, 6)
    f = a.frame_at(t_after, calm=True)
    base = round(
        anim.CALM_FACTOR
        * anim.BREATH_AMPLITUDE
        * math.sin(2 * math.pi * t_after / anim.BREATH_PERIOD)
    )
    assert f.dy == base and f.squash == 1.0, "收完之后没回到静息"


def test_dozeoff_restart_starts_fresh():
    """中途再来一次：从沉下去重新起步 —— 与「只在这一刻开始」的孪生全等。"""
    a, d = Animator(seed=17), Animator(seed=17)
    _walk(a, 0.0, T0)
    _walk(d, 0.0, T0)
    a.dozeoff(T0)
    assert a.frame_at(round(T0 + 0.5, 6), calm=True) != d.frame_at(round(T0 + 0.5, 6), calm=True), (
        "前提不成立：第一下没在演"
    )
    a.dozeoff(T0 + 1.0)  # 重开：旧的作废
    d.dozeoff(T0 + 1.0)
    for tau in (0.0, 0.15, 0.5, 1.1, 1.6, 2.4):
        t = round(T0 + 1.0 + tau, 6)
        assert a.frame_at(t, calm=True) == d.frame_at(t, calm=True), f"{t} 重开后没有从头起步"


def test_dozeoff_reset_clears_state():
    """时间线被拨动（reset）：旧的那下不作数。"""
    a, b = Animator(seed=19), Animator(seed=19)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.dozeoff(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.05, 0.4, 0.9, 1.6):
        t = round(T0 + 0.2 + tau, 6)
        assert a.frame_at(t, calm=True) == b.frame_at(t, calm=True), f"{t} reset 之后旧的那个还在"
    c = Animator(seed=21)
    c.dozeoff(T0)
    c.reset(T0 + 1.0)
    assert c._dozeoff_at == -99.0, "reset 后旧的那下没作数"


def test_dozeoff_is_deterministic():
    """同一条序列跑两遍逐值相等；顺带走一遍完整时间线。"""

    def run():
        a = Animator(seed=23)
        out = []
        for i in range(1, 301):
            t = round(i * 0.02, 6)  # 6 秒
            if i == 50:
                a.dozeoff(t)  # t = 1.0
            f = a.frame_at(t, calm=True)
            out.append((round(f.squash, 12), f.dx, f.dy, f.gx, f.gy))
        return out

    assert run() == run()


def test_dozeoff_does_not_touch_the_random_stream():
    """不掷随机数、不占随机流（同种子孪生对比靠它）。"""
    a, b = Animator(seed=5), Animator(seed=5)
    a.dozeoff(10.0)
    a.dozeoff(20.0)
    assert a._rng.random() == b._rng.random(), "dozeoff() 动了随机流 —— 孪生对比会散架"


def test_geometry_guard_covers_the_dozeoff_channel():
    """全局几何预算守卫（test_yawn）必须把「入睡的一下」算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "anim.DOZEOFF_SINK_PX" in text, (
        "test_yawn 的全局预算守卫里没有「入睡的一下」通道 —— 调大 DOZEOFF_* 就没人拦了"
    )
    assert "anim.DOZEOFF_SQUINT_MIN" in text, "守卫里漏了压合项（成对算净量的另一半）"


# ── 链路：窗口把「睡着那一刻」喂给动画层 ──────────────

from sammy.pet import SLEEP_EXPR, SammyWindow  # noqa: E402

SEED_DOZEOFF = 7


def _win(scale: float = 1.0) -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留「睡着那一刻」一个变量。

    energy 定在睡着线下方一点（状态行「睡着了」与睡脸一致 —— 不 set asleep
    标志就不挂 Z；Z 有自己的 doze 素材，这里要的是干净的对照）。
    眨眼请出去：和压合同用 squash 通道，撞上就量不准。
    """
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = scale
    w._offset = (0, 0)
    w.resize(round(800 * scale), round(480 * scale))
    w._relayout()
    w.anim = anim.Animator(seed=SEED_DOZEOFF, blink_gap=(600.0, 600.0))
    w.look_on = False  # 光标不参与（盯的是「睡着那一刻」这一件事）
    w.drives.energy = 0.05  # 累趴
    w.set_expression(SLEEP_EXPR)
    w.status = drives.status_text(w.drives)
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    return w


def test_window_triggers_dozeoff_on_the_sleep_edge(qapp):
    """自己熬到睡着的那一刻：窗口安排一次「撑不住」，且同一拍把睡脸亮起来（calm）。"""
    w = _win()
    try:
        w.drives.last_update = time.time() - 0.25 * 3600  # 0.25 小时 → 这次 tick 掉 ≥0.025
        w.drives.energy = drives.ASLEEP_BELOW + 0.02  # 就压在线上方一点
        w.drives.asleep = False
        w.anim_t = 50.0
        w._tick()
        assert w.drives.asleep is True, "前提不成立：这一次 tick 没睡着"
        assert w.anim._dozeoff_at == 50.0, "睡着那一刻没安排「撑不住」"
        assert w.expression == SLEEP_EXPR, "睡脸该在同一拍亮起来（calm 跟着成立）"
        w.anim_t = 51.0
        w._tick()
        assert w.anim._dozeoff_at == 50.0, "睡着之后再喂 tick 不该重排（一段睡觉一次）"
    finally:
        w.close()


def test_window_dozeoff_needs_anim_on(qapp):
    """动画关着：睡着那一刻也不演 —— 关就该关彻底。"""
    w = _win()
    try:
        w.anim_on = False
        w.drives.last_update = time.time() - 0.25 * 3600
        w.drives.energy = drives.ASLEEP_BELOW + 0.02
        w.drives.asleep = False
        w.anim_t = 40.0
        w._tick()
        assert w.drives.asleep is True, "前提不成立：没睡着"
        assert w.anim._dozeoff_at == -99.0, "动画关着还安排「撑不住」"
    finally:
        w.close()


def test_window_waking_does_not_trigger_dozeoff(qapp):
    """睡饱自己醒来：走哈欠那条边 —— 反向的「撑不住」一眼都不许出现。"""
    w = _win()
    try:
        w.drives.asleep = True
        w.drives.energy = 0.10
        w.drives.last_update = time.time() - 2 * 3600  # 睡了两小时 → 自己醒
        w.anim_t = 60.0
        w._tick()
        assert w.drives.asleep is False, "前提不成立：没醒"
        assert w.anim._yawn_at == 60.0, "唤醒该走哈欠那条边"
        assert w.anim._dozeoff_at == -99.0, "唤醒方向不许出现「入睡的一下」"
    finally:
        w.close()


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402


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


def test_dozeoff_sinks_and_squashes_the_face(qapp):
    """scale 1.0 双胞胎：沉底时脸明显往下走、被压合、宽度不动；收完逐字节归零。

    实测（本组常数、seed 7）：顶沿 +44 / 下沿 -32 / 脸高 138 → 62。
    """
    a, b = _win(), _win()
    try:
        a.anim.dozeoff(8.5)
        clip = _clip(a)
        peak = round(8.5 + anim.DOZEOFF_SINK_S + anim.DOZEOFF_HOLD_S / 2, 6)
        a.anim_t = peak
        b.anim_t = peak
        x0a, y0a, x1a, y1a = _lit_bbox(a, clip)
        x0b, y0b, x1b, y1b = _lit_bbox(b, clip)
        assert y0a - y0b >= 35, f"顶沿没沉下去：{y0a - y0b}px"
        assert y1b - y1a >= 25, f"下沿没被压上来：{y1b - y1a}px"
        assert (y1b - y0b) - (y1a - y0a) >= 60, f"脸没被压合：{y1a - y0a} vs {y1b - y0b}"
        assert abs((x1a - x0a) - (x1b - x0b)) <= 2, "压合不该动宽度"
        assert abs(x0a - x0b) <= 2 and abs(x1a - x1b) <= 2, "横向不该动"
        after = round(8.5 + anim.dozeoff_total() + 0.4, 6)
        a.anim_t = after
        b.anim_t = after
        assert _img_bytes(a) == _img_bytes(b), "「撑不住」收完还不回到常态"
    finally:
        a.close()
        b.close()


def test_dozeoff_key_moment_stays_inside_the_repainted_region(qapp):
    """沉到底那一帧必须落在局部重绘区里 —— 在外面那圈不刷新（脸会花）。"""
    w = _win()
    try:
        w.anim.dozeoff(8.5)
        clip = _clip(w)
        region = w._face_region()
        w.anim_t = round(8.5 + anim.DOZEOFF_SINK_S + anim.DOZEOFF_HOLD_S / 2, 6)
        x0, y0, x1, y1 = _lit_bbox(w, clip)
        deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        assert region.contains(deformed), f"沉到底时脸 {deformed} 冒出重绘区 {region}"
    finally:
        w.close()


# ── 纪律与素材 ────────────────────────────────────


def test_dozeoff_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "dozeoff_preview.py").is_file()
    assert "dozeoff-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("dozeoff-strip.png", "dozeoff-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
