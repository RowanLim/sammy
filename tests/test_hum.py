"""哼小曲（自选小步·第十六次）——「心情好的时候，摇头晃脑哼两句」。

动机：这批自发动作到上一件为止，全是「状态」或「反射」—— 叹气挂无聊、
点头挂犯困、抽动挂睡着、哈欠挂醒来、喷嚏是纯反射。可一个真的活物还有
「高兴」：心情**很好**的时候，隔一会儿轻轻晃两下脑袋（像哼歌时那样），
右上角冒出一个像素小音符（和睡着的 Z 同一格）。它是第一条只挂心情的
自发动作 —— 好心情也要能被眼睛读出来。

两块机制：
- 形状：hum_amount 一条三段曲线（起手 → 满幅摇晃 → 收尾），纯函数逐点可钉；
  摇晃本身是「包络 × 正弦」：稳段里正弦走三个整周期（晃三下），两头用
  平滑包络收进去、收出来（不许突然起停）。
- 节奏：note_hum 每隔 HUM_MIN_GAP~HUM_MAX_GAP 秒排一段（随机，别像节拍器）；
  刚高兴起来先等一个间隔（立刻哼 = 情绪还没走到脸上）、心情落回去排期清掉、
  正在哼的那一段让它哼完（半路掐掉像被捂住了嘴）。

窗口那层的闸门（_hum_ok）：睡着 / 累趴 / 被拎着 / 正在看你写字 / 心情没到
「很好」—— 都不哼；思考中天然不跑（_tick 整个不跑）。

四层判据（和 test_sneeze 一个框架）：
1. 纯函数：曲线逐点对账、节奏器四件事、只加不改、摆幅两头都到满、确定性；
2. 窗口链路：心情到线才排、各道闸门各拦一次、动画关 / 思考中不排；
3. 渲染（真窗口离屏双胞胎）：左右摆幅实测 ±4px（比孪生）、竖着一点没动、
   收完逐字节归零；音符只在哼时出现、真在动、行程落在重绘区里；
4. 素材纪律：一条命令能重生成 + 素材真在仓库里。

（设计数字：HUM_* 常量在 anim.py 顶部；调参速查表第 26 节。音符矩阵
HUM_NOTE 在 pet.py —— 和 Z 同格的「状态小图标」。）
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
    """别碰用户真实的状态文件（和 test_pet / test_sneeze 同一套隔离）。"""
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


def _hum_term(t: float, hum_at: float) -> int:
    """按实现同一条算式复算：这一刻哼小曲往 dx 上加了多少（没在哼 = 0）。"""
    spent = t - hum_at
    k = anim.hum_amount(spent)
    if k <= 0.0:
        return 0
    return round(anim.HUM_ROCK_PX * k * math.sin(2 * math.pi * spent / anim.HUM_ROCK_PERIOD))


# ── 纯函数层：曲线与节奏 ──────────────────────────


def test_hum_constants_stay_subtle():
    """常量必须停在「哼小曲」量级：段长够看清、摇摆是像素级、节奏不疾不徐。"""
    total = anim.hum_total()
    assert 2.0 <= total <= 3.5, f"整段 {total}s —— 太短看不清摇头晃脑，太长像发条"
    assert 0.45 <= anim.HUM_ROCK_PERIOD <= 0.9, "一拍太疾像哆嗦、太慢像慢动作"
    assert isinstance(anim.HUM_ROCK_CYCLES, int)
    assert 2 <= anim.HUM_ROCK_CYCLES <= 6
    assert 2 <= anim.HUM_ROCK_PX <= 6, "摇摆是像素级的小动作（比微动 ±2 明显一档）"
    assert 0.15 <= anim.HUM_EASE_IN_S <= 0.6
    assert 0.2 <= anim.HUM_EASE_OUT_S <= 0.9
    assert 4 <= anim.HUM_NOTE_RISE_PX <= 12
    assert 30.0 <= anim.HUM_MIN_GAP < anim.HUM_MAX_GAP <= 300.0, "节奏窗口不成立"
    assert anim.HUM_MIN_GAP >= anim.NOD_MIN_GAP, "哼小曲不比打瞌睡还频"
    assert anim.HUM_MAX_GAP <= anim.SNEEZE_MAX_GAP, "哼小曲也别比喷嚏还稀罕"


def test_hum_shape_rises_rocks_and_settles():
    """三段拼一条时间线：起手缓、满幅恒 1、收尾缓；两头精确为 0、各段单调。"""
    assert anim.hum_amount(-0.1) == 0.0, "还没开始就不该有"
    assert anim.hum_amount(0.0) == 0.0, "从静息起步"
    assert anim.hum_amount(anim.HUM_EASE_IN_S / 2) == pytest.approx(0.5)
    assert anim.hum_amount(anim.HUM_EASE_IN_S) == pytest.approx(1.0)
    steady_end = anim.HUM_EASE_IN_S + anim.HUM_ROCK_S
    assert anim.hum_amount(steady_end - 1e-6) == pytest.approx(1.0)
    assert anim.hum_amount(steady_end + anim.HUM_EASE_OUT_S / 2) == pytest.approx(0.5)
    assert anim.hum_amount(anim.hum_total()) == pytest.approx(0.0), "收完就该是零"
    assert anim.hum_amount(anim.hum_total() + 5.0) == 0.0
    up = [anim.hum_amount(anim.HUM_EASE_IN_S * i / 20) for i in range(21)]
    assert all(b >= a for a, b in pairwise(up)), "起手段不单调"
    mid = [anim.hum_amount(anim.HUM_EASE_IN_S + 0.05 * i) for i in range(37)]
    assert all(v == pytest.approx(1.0) for v in mid), "满幅段应该是恒 1"
    down = [anim.hum_amount(steady_end + anim.HUM_EASE_OUT_S * i / 20) for i in range(21)]
    assert all(b <= a for a, b in pairwise(down)), "收尾段不单调"


def test_note_hum_first_one_waits_a_gap():
    """刚高兴起来：先等一个（随机）间隔再哼第一段 —— 立刻哼 = 情绪还没走到脸上。"""
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.note_hum(T0, True)
    assert a._hum_at == -99.0, "刚高兴就立刻哼，像情绪还没来得及长出来"
    assert a._hum_next_at is not None
    first = a._hum_next_at
    assert T0 + anim.HUM_MIN_GAP <= first <= T0 + anim.HUM_MAX_GAP
    a.note_hum(first - 0.5, True)
    assert a._hum_at == -99.0, "还没到点就哼了"
    a.note_hum(first, True)
    assert a._hum_at == first, "到点了没哼"
    nxt = a._hum_next_at
    assert nxt is not None and first + anim.HUM_MIN_GAP <= nxt <= first + anim.HUM_MAX_GAP, (
        "哼完没接着排下一段"
    )


def test_note_hum_gap_is_randomized_not_a_metronome():
    """一直高兴：间隔全落在窗口里，而且不止一个值 —— 别像节拍器。"""
    a = Animator(seed=9)
    a.note_hum(0.0, True)
    times = []
    for _ in range(60):
        t = a._hum_next_at
        a.note_hum(t, True)
        times.append(t)
    assert a._hum_at == times[-1]
    gaps = [b - p for p, b in pairwise(times)]
    assert all(anim.HUM_MIN_GAP <= g <= anim.HUM_MAX_GAP for g in gaps), gaps
    assert len(set(gaps)) >= 3, "间隔全一个样 —— 成节拍器了"


def test_note_hum_off_clears_pending_schedule():
    """心情落了（不能哼了）：排期清掉；之后不再哼新的。"""
    c = Animator(seed=13)
    c.note_hum(T0, True)
    assert c._hum_next_at is not None
    c.note_hum(T0 + 1.0, False)
    assert c._hum_next_at is None, "不能哼了排期还留着"
    for i in range(120):
        c.note_hum(T0 + 2.0 + i, False)
    assert c._hum_at == -99.0, "说不能哼了还哼了一段"


def test_gate_off_feeds_never_leak():
    """怎么喂「不能哼」都和什么都不喂的孪生逐帧全等（400 步）—— 闸门关彻底。"""
    a, b = Animator(seed=31), Animator(seed=31)
    for i in range(1, 401):
        t = round(i * 0.033, 6)
        a.note_hum(t, False)
        assert a.frame_at(t) == b.frame_at(t), f"{t} 闸门关着还漏出动作"


def test_one_in_flight_hum_finishes_after_gate_off():
    """正在哼的这段让它哼完：'不能哼了'只清排期，不掐当前 —— 半路掐掉像被捂住了嘴。"""
    a, b = Animator(seed=11), Animator(seed=11)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.hum(T0)
    a.note_hum(T0 + 0.3, False)  # 哼到一半心情落了
    for tau in (0.4, 1.1, 1.6, 2.3):
        t = round(T0 + tau, 6)
        assert a.frame_at(t).dx != b.frame_at(t).dx, f"{t} 排着的这段被'不能哼'掐掉了？"
    end = round(T0 + anim.hum_total() + 0.3, 6)
    assert a.frame_at(end) == b.frame_at(end), "收完没回到常态"


def test_hum_only_adds_other_channels_do_not_move():
    """只哼小曲的一方与完全没哼的孪生：别的通道一个都不许动；窗外全等。"""
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.hum(T0)
    live = 0
    end = T0 + anim.hum_total()
    for i in range(1, 161):
        t = round(T0 + i * 0.025, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert (fa.squash, fa.dy, fa.pop, fa.gx, fa.gy, fa.stretch, fa.talk_y, fa.talk_sq) == (
            fb.squash,
            fb.dy,
            fb.pop,
            fb.gx,
            fb.gy,
            fb.stretch,
            fb.talk_y,
            fb.talk_sq,
        ), f"{t} 时别的通道被哼小曲带偏了"
        if t < end:
            if fa.dx != fb.dx:
                live += 1
        else:
            assert fa.dx == fb.dx, f"{t} 哼完之后还没回到常态"
    assert live >= 80, f"窗口里只有 {live} 帧真的摆了 —— 没哼起来"


def test_hum_matches_formula_point_by_point():
    """整段逐点对账（0.02 秒网格）：dx 的增量与公式对齐到每个采样点。"""
    a, b = Animator(seed=11), Animator(seed=11)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.hum(T0)
    live = 0
    for i in range(131):
        t = round(T0 + i * 0.02, 6)
        want = _hum_term(t, T0)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert fa.dx - fb.dx == want, t
        assert (fa.squash, fa.dy, fa.pop, fa.gx, fa.gy, fa.stretch, fa.talk_y, fa.talk_sq) == (
            fb.squash,
            fb.dy,
            fb.pop,
            fb.gx,
            fb.gy,
            fb.stretch,
            fb.talk_y,
            fb.talk_sq,
        ), t
        if want != 0:
            live += 1
    assert live >= 90, f"窗口里只有 {live} 帧摆动了"


def test_hum_swing_reaches_both_rails():
    """满幅段里正弦走三个整周期：两头都真的摆到 ±HUM_ROCK_PX（不是擦边）。"""
    a, b = Animator(seed=5), Animator(seed=5)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.hum(T0)
    p = anim.HUM_ROCK_PERIOD
    e = anim.HUM_EASE_IN_S
    for k in range(anim.HUM_ROCK_CYCLES):
        t1 = round(T0 + e + p * (0.25 + k), 6)  # 正弦低谷 = 往左满
        t2 = round(T0 + e + p * (0.75 + k), 6)  # 正弦峰值 = 往右满
        assert a.frame_at(t1).dx - b.frame_at(t1).dx == -anim.HUM_ROCK_PX, t1
        assert a.frame_at(t2).dx - b.frame_at(t2).dx == anim.HUM_ROCK_PX, t2


def test_hum_swing_never_exceeds_the_rails():
    """整段拉网（0.005 秒网格）：摆幅不越界、也确实到得了满。"""
    a, b = Animator(seed=13), Animator(seed=13)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.hum(T0)
    ds = []
    for i in range(0, 700):
        t = round(T0 + i * 0.005, 6)
        ds.append(a.frame_at(t).dx - b.frame_at(t).dx)
    assert max(ds) <= anim.HUM_ROCK_PX and min(ds) >= -anim.HUM_ROCK_PX, "摆幅越界"
    assert max(ds) == anim.HUM_ROCK_PX, "右边没摆满 —— 白摇了"
    assert min(ds) == -anim.HUM_ROCK_PX, "左边没摆满 —— 白摇了"


def test_hum_and_sneeze_compose_on_dx():
    """哼着的时候打喷嚏（反射不躲）：两条横向增量相叠，与公式逐点对齐。"""
    a, b = Animator(seed=25), Animator(seed=25)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.hum(T0)
    a.sneeze(T0 + 1.0)
    d = a._sneeze_dir
    for i in range(1, 160):
        t = round(T0 + i * 0.02, 6)
        want = _hum_term(t, T0)
        ks = anim.sneeze_amount(t - (T0 + 1.0))
        if ks > 0.0:
            want += d * round(anim.SNEEZE_JERK_PX * ks)
        assert a.frame_at(t).dx - b.frame_at(t).dx == want, t


def test_hum_suppressed_when_calm_and_resumes_after():
    """睡着不哼（定格优先）；醒来接着哼（不是半路掐掉重来）。"""
    a, b = Animator(seed=15), Animator(seed=15)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.hum(T0)
    for i in range(1, 30):
        t = round(T0 + i * 0.05, 6)
        fa = a.frame_at(t, calm=True)
        fb = b.frame_at(t, calm=True)
        assert (fa.dx, fa.dy, fa.squash) == (fb.dx, fb.dy, fb.squash), f"{t} 睡着时摇摆漏出来了"
    mid = round(T0 + anim.HUM_EASE_IN_S + anim.HUM_ROCK_PERIOD * 0.75, 6)
    fa, fb = a.frame_at(mid), b.frame_at(mid)
    assert fa.dx != fb.dx, "醒来没接着哼（被 calm 掐了）"


def test_hum_restart_starts_fresh():
    """中途再排一段：从起手重新起步 —— 与「只在这一刻开始」的孪生全等。"""
    a, c = Animator(seed=17), Animator(seed=17)
    _walk(a, 0.0, T0)
    _walk(c, 0.0, T0)
    a.hum(T0)
    assert a.frame_at(T0 + 0.75).dx != c.frame_at(T0 + 0.75).dx, "前提不成立：a 没有在哼"
    t2 = T0 + 1.0  # 哼到一半再来一段
    a.hum(t2)
    c.hum(t2)
    for tau in (0.0, 0.05, 0.2, 0.5, 1.0, 1.8, 2.5):
        t = round(t2 + tau, 6)
        assert a.frame_at(t) == c.frame_at(t), f"{t} 重开后没有从头起步"


def test_hum_reset_clears_state():
    """时间线被拨动（reset）：旧的那段不作数、排期也清掉。"""
    a, b = Animator(seed=19), Animator(seed=19)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    a.hum(T0)
    a.reset(T0 + 0.2)
    b.reset(T0 + 0.2)
    for tau in (0.05, 0.2, 0.5, 1.2):
        t = round(T0 + 0.2 + tau, 6)
        assert a.frame_at(t) == b.frame_at(t), f"{t} reset 之后旧的那段还在"
    c = Animator(seed=23)
    c.note_hum(T0, True)
    assert c._hum_next_at is not None
    c.hum(T0 + 1.0)
    c.reset(T0 + 2.0)
    assert c._hum_at == -99.0
    assert c._hum_next_at is None, "reset 后旧排期还留着"


def test_hum_is_deterministic():
    """同一条序列跑两遍逐值相等（种子相同 = 演出相同）。"""

    def run():
        a = Animator(seed=29)
        out = []
        for i in range(1, 161):
            t = round(i * 0.05, 6)
            if i == 40:
                a.hum(t)
            if i == 60:
                a.note_hum(t, True)
            f = a.frame_at(t)
            out.append((round(f.squash, 12), f.dy, f.dx, round(f.stretch, 12), f.gx, f.gy))
        return out

    assert run() == run()


def test_geometry_guard_covers_the_hum_channel():
    """全局几何预算守卫（test_yawn）必须把哼小曲的摇摆算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "anim.HUM_ROCK_PX" in text, (
        "test_yawn 的全局预算守卫里没有哼小曲的摇摆通道 —— 调大 HUM_ROCK_PX 就没人拦了"
    )


# ── 渲染层：真窗口离屏抓图 ─────────────────────────

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import HUM_NOTE, HUM_NOTE_CELL, SammyWindow  # noqa: E402

SEED_HUM = 7


def _mk() -> SammyWindow:
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留哼小曲这一个变量。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    # 眨眼请出去（和喷嚏同一个理由：量摇摆时画面里越干净越好）
    w.anim = anim.Animator(seed=SEED_HUM, blink_gap=(600.0, 600.0))
    w.look_on = False  # 光标不参与（盯的是哼小曲这一件事）
    w.set_expression(2)  # 普通脸
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    return w


def _img_bytes(w: SammyWindow) -> bytes:
    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(img.constBits())


def _lit_pixels(w: SammyWindow, rect: QRect, exclude: QRect | None = None) -> list[tuple[int, int]]:
    """矩形里的「不透明亮像素」（判据从 faces.LIT 常量读，不写死色相）。"""
    from sammy import faces

    img = w.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    pts = []
    for y in range(max(0, rect.top()), min(img.height() - 1, rect.bottom()) + 1):
        row = y * stride
        for x in range(max(0, rect.left()), min(img.width() - 1, rect.right()) + 1):
            if exclude is not None and exclude.contains(QPoint(x, y)):
                continue
            i = row + x * 4
            b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
            if a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70:
                pts.append((x, y))
    return pts


def _lit_bbox(w: SammyWindow, clip: QRect, exclude: QRect | None = None):
    pts = _lit_pixels(w, clip, exclude)
    assert pts, "clip 里一个亮像素都没有 —— 区域搞错了？"
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _note_box(w: SammyWindow) -> QRect:
    """按 _draw_hum 的算法算出音符的整个行程（和实现同一条算式，不 import 私有方法）。"""
    box = w.lay.face
    s = w.scale
    cell = max(1, int(HUM_NOTE_CELL * s))
    ww = len(HUM_NOTE[0]) * cell
    hh = len(HUM_NOTE) * cell
    x = box.right() - ww - int(20 * s)
    y = box.top() + int(10 * s) - int(anim.HUM_NOTE_RISE_PX * s)
    return QRect(x, y, ww, hh + int(anim.HUM_NOTE_RISE_PX * s))


def test_hum_rocks_the_face_side_to_side(qapp):
    """scale 1.0 双胞胎：左右摆幅实测 ±HUM_ROCK_PX（纯平移）、竖着没动、收完逐字节归零。"""
    a, b = _mk(), _mk()
    try:
        a.anim.hum(8.5)
        box = a.lay.face
        clip = QRect(box.left() - 60, 6, box.width() + 120, 235)
        nb = _note_box(a)
        p = anim.HUM_ROCK_PERIOD
        e = anim.HUM_EASE_IN_S
        for k in range(anim.HUM_ROCK_CYCLES):
            for sign, f in ((-1, 0.25), (1, 0.75)):
                t = round(8.5 + e + p * (f + k), 6)
                a.anim_t = t
                b.anim_t = t
                la = _lit_bbox(a, clip, nb)
                lb = _lit_bbox(b, clip, nb)
                assert la[0] - lb[0] == sign * anim.HUM_ROCK_PX, (t, la, lb)
                assert (la[1], la[3]) == (lb[1], lb[3]), f"{t} 竖着不该动"
                assert abs((la[2] - la[0]) - (lb[2] - lb[0])) <= 1
        end = round(8.5 + anim.hum_total() + 0.4, 6)
        a.anim_t = end
        b.anim_t = end
        assert _img_bytes(a) == _img_bytes(b), "哼完还不回到常态"
    finally:
        a.close()
        b.close()


def test_hum_note_appears_only_while_humming(qapp):
    """音符只在哼时出现：没哼时右上角空的、哼着有、真在动、停了一干二净。"""
    w = _mk()
    try:
        nb = _note_box(w)
        w.anim_t = 10.0
        base = _lit_pixels(w, nb)
        assert base == [], f"没哼的时候右上角就不该有东西（{len(base)} 像素）"
        w.anim.hum(10.0)
        w.anim_t = round(10.0 + anim.HUM_EASE_IN_S + anim.HUM_ROCK_PERIOD, 6)
        shown = _lit_pixels(w, nb)
        assert len(shown) >= 90, f"哼着却没画音符（{len(shown)} 像素）"
        w.anim_t = round(10.0 + anim.HUM_EASE_IN_S + 0.1, 6)
        s1 = set(_lit_pixels(w, nb))
        w.anim_t = round(10.0 + 2.0, 6)
        s2 = set(_lit_pixels(w, nb))
        assert s1 and s2, "采样点没画出来"
        moved = len(s1 ^ s2)
        assert moved > 10, f"两帧只差 {moved} 像素 —— 音符没在动"
        w.anim_t = round(10.0 + anim.hum_total() + 0.4, 6)
        assert _lit_pixels(w, nb) == [], "哼完了音符还赖着"
    finally:
        w.close()


def test_hum_note_stays_inside_the_repainted_region(qapp):
    """画在重绘区域外面 = 动画帧不会刷新它 = 卡住不动。这条专门钉位置。"""
    w = _mk()
    try:
        region = w._face_region()
        nb = _note_box(w)
        assert region.contains(nb), f"音符行程 {nb} 跑出了重绘区域 {region} —— 它会卡住"
    finally:
        w.close()


# ── 链路：窗口把「能不能哼」喂给动画层 ───────────────


def test_window_schedules_hum_only_when_very_happy(qapp):
    """链路：心情到「很好」才排；落回「不错」清掉；再高兴重新排、到点就哼。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0  # 冻结驱力漂移（边界用例的老规矩）
        w.mood.mood.valence = 0.8
        w.anim_t = 50.0
        w._tick()
        first = w.anim._hum_next_at
        assert first is not None, "高兴着（0.8）却没排哼小曲"
        assert 50.0 + anim.HUM_MIN_GAP <= first <= 50.0 + anim.HUM_MAX_GAP
        assert w.anim._hum_at == -99.0, "排期不该当场就哼"
        w.mood.mood.valence = 0.4  # 落回「不错」档
        w.anim_t = 51.0
        w._tick()
        assert w.anim._hum_next_at is None, "心情都落了还排着哼小曲"
        w.mood.mood.valence = 0.7
        w.anim_t = 52.0
        w._tick()
        second = w.anim._hum_next_at
        assert second is not None and second >= 52.0 + anim.HUM_MIN_GAP, "再高兴没有重新排"
        w.anim_t = second
        w._tick()
        assert w.anim._hum_at == second, "到点了没哼"
        nxt = w.anim._hum_next_at
        assert nxt is not None and nxt >= second + anim.HUM_MIN_GAP, "哼完没接着排"
    finally:
        w.close()


def test_window_gates_asleep_carried_and_typing(qapp):
    """闸门：睡着 / 累趴 / 被拎着 / 正在看着你写字 —— 都不哼；放开就恢复。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.mood.mood.valence = 0.9
        w.anim_t = 30.0
        w._tick()
        assert w.anim._hum_next_at is not None, "高兴着又不忙却不排"
        w.drives.asleep = True
        w.anim_t = 31.0
        w._tick()
        assert w.anim._hum_next_at is None, "睡着还排哼小曲"
        w.drives.asleep = False
        w.drives.energy = 0.05  # 累趴（够不着唤醒线）
        w.anim_t = 32.0
        w._tick()
        assert w.anim._hum_next_at is None, "累趴了还哼"
        w.drives.energy = 0.8
        w._drag = QPoint(1, 1)
        w.anim_t = 33.0
        w._tick()
        assert w.anim._hum_next_at is None, "被拎着还排哼小曲"
        w._drag = None
        w.anim_t = 34.0
        w._tick()
        assert w.anim._hum_next_at is not None, "放下了还不排"
        w._last_typing_at = time.time()
        w.anim_t = 35.0
        w._tick()
        assert w.anim._hum_next_at is None, "正被看着写字还摇头晃脑"
        w._last_typing_at = 0.0
        w.anim_t = 36.0
        w._tick()
        assert w.anim._hum_next_at is not None, "停手了还不排"
    finally:
        w.close()


def test_window_is_silent_when_anim_off_or_thinking(qapp):
    """动画关 / 思考中：都不排 —— 关就该关彻底。"""
    w = _mk()
    try:
        w.drives.last_update = time.time() + 10.0
        w.mood.mood.valence = 0.9
        w.anim_on = False
        w.anim_t = 40.0
        w._tick()
        assert w.anim._hum_next_at is None, "动画关着还排哼小曲"
        w.anim_on = True
        w.thinking = True
        w.anim_t = 41.0
        w._tick()
        assert w.anim._hum_next_at is None, "思考中还排哼小曲"
        w.thinking = False
        w.anim_t = 42.0
        w._tick()
        assert w.anim._hum_next_at is not None, "都恢复了还不排"
    finally:
        w.close()


# ── 纪律与素材 ────────────────────────────────────


def test_hum_media_and_script_are_shipped():
    """素材要能一条命令重生成，而且要真在仓库里（网页上直接能看）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "scripts" / "hum_preview.py").is_file()
    assert "hum-media" in (root / "Makefile").read_text(encoding="utf-8")
    for name in ("hum-strip.png", "hum-demo.mp4"):
        p = root / "docs" / "8h-b2" / name
        assert p.is_file(), f"缺素材：{name}"
        assert p.stat().st_size > 10_000, f"素材太小，像空壳：{name}"
