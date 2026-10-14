"""绷住（自选小步·第二十六次）——「心情压到低落以下时，整个人缩一小圈」。

动机：蔫一会儿（第二十三次）补的是「垂」的那一下，蔫过头（第二十五次）把心情
映成静态缩量。可这两条之间还缺一段：心情再往下压、压进「低落」档的时候，
它该从「有点蔫」变成「绷紧了」—— 不是变矮，是整个人紧一圈。

它是全表第一批「从心情底色算、不从别的量反推」的东西：第一版曾从静止缩量反推，
结果把 test_shrink 的两条判据顶红（同一件事说两遍），改回读底色才对。

三块机制：
- 曲线：hunch_amount 一条纯函数（心情 -> 绷的量），比蔫过头的线更晚一步；
- 闸门：hunch_ok（动画关 / 睡着不绷）—— 排期在 note_hunch 里统一道；
- 落点：横向收 HUNCH_SQUINT_PX、纵向压到 HUNCH_SQUASH_MIN、好奇拉高按
  HUNCH_STRETCH_ABS 收掉 —— 三条通道一起动，才读得成「缩一圈」。

四层判据（和 test_droop / test_shrink 一个框架）：
1. 纯函数：曲线逐点对账（线上下、量级、单调、有界）、闸门真值表；
2. 动画层：三条通道逐点对公式、缓入不跳变、关掉后逐帧全等、排期间隔随机且受常量约束；
3. 链路：窗口把心情底色喂给动画层，闸门不被绕过；
4. （渲染层与速查表对账见下节。）
"""

from __future__ import annotations

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
    """别碰用户真实的状态文件（和 test_pet / test_hum 同一套隔离）。"""
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


# 纯函数层：曲线与闸门


def test_hunch_constants_stay_subtle():
    a = anim
    assert a.HUNCH_MIN_GAP < a.HUNCH_MAX_GAP
    assert a.HUNCH_MIN_GAP >= a.DROOP_MIN_GAP
    assert a.HUNCH_MAX_GAP >= a.DROOP_MAX_GAP
    assert 0.0 < a.HUNCH_RAMP <= 0.4
    assert a.HUNCH_ABS_BELOW < a.MOOD_SHRINK_BELOW
    assert 1 <= a.HUNCH_SQUINT_PX <= 4
    assert 0.90 <= a.HUNCH_SQUASH_MIN <= 1.0
    assert 0.0 <= a.HUNCH_STRETCH_ABS < 1.0


def test_hunch_amount_curve_is_late_and_linear():
    a = anim
    assert a.hunch_amount(0.15) == 0.0
    assert a.hunch_amount(a.HUNCH_ABS_BELOW) == 0.0
    assert a.hunch_amount(a.HUNCH_ABS_BELOW - a.HUNCH_RAMP / 2) == 0.5
    assert a.hunch_amount(a.HUNCH_ABS_BELOW - a.HUNCH_RAMP) == 1.0
    assert a.hunch_amount(-0.45) == 1.0
    assert a.hunch_amount(-0.90) == 1.0


def test_hunch_amount_is_monotonic_and_bounded():
    a = anim
    vals = [a.hunch_amount(round(0.20 - i * 0.005, 6)) for i in range(141)]
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert all(x <= y for x, y in pairwise(vals))
    assert vals[0] == 0.0 and vals[-1] == 1.0


def test_hunch_gate_truth_table():
    a = anim
    assert a.hunch_ok(True, False) is True
    assert a.hunch_ok(False, False) is False
    assert a.hunch_ok(True, True) is False
    assert a.hunch_ok(False, True) is False


# 动画层：三条通道与排期


def test_hunch_channels_match_the_formula_point_by_point():
    a, b = Animator(seed=7), Animator(seed=7)
    _walk(a, 0.0, T0)
    _walk(b, 0.0, T0)
    b.set_mood_valence(-0.45)
    for i in range(1, 201):
        t = round(i * 0.05, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert fb.squash == pytest.approx(min(fa.squash, anim.HUNCH_SQUASH_MIN))
        assert fb.dx - fa.dx == anim.HUNCH_SQUINT_PX
        assert fb.stretch == pytest.approx(fa.stretch * (1.0 - anim.HUNCH_STRETCH_ABS))


def test_hunch_ramps_in_instead_of_switching_on():
    a, b = Animator(seed=11), Animator(seed=11)
    b.set_mood_valence(anim.HUNCH_ABS_BELOW - 0.1)
    t = 12.0
    fa, fb = a.frame_at(t), b.frame_at(t)
    k = anim.hunch_amount(anim.HUNCH_ABS_BELOW - 0.1)
    assert 0.0 < k < 1.0
    assert fb.dx - fa.dx == round(anim.HUNCH_SQUINT_PX * k)


def test_hunch_off_leaves_every_frame_identical():
    a, b = Animator(seed=13), Animator(seed=13)
    for i in range(1, 301):
        t = round(i * 0.05, 6)
        assert a.frame_at(t) == b.frame_at(t)


def test_note_hunch_first_one_waits_a_gap():
    a = Animator(seed=7)
    _walk(a, 0.0, T0)
    a.note_hunch(T0, True)
    assert a._hunch_at == -99.0
    first = a._hunch_next_at
    assert first is not None
    assert T0 + anim.HUNCH_MIN_GAP <= first <= T0 + anim.HUNCH_MAX_GAP
    a.note_hunch(first - 0.5, True)
    assert a._hunch_at == -99.0
    a.note_hunch(first, True)
    assert a._hunch_at == first


def test_note_hunch_gap_is_randomized():
    a = Animator(seed=9)
    a.note_hunch(0.0, True)
    times = []
    for _ in range(40):
        t = a._hunch_next_at
        a.note_hunch(t, True)
        times.append(t)
    gaps = [b - p for p, b in pairwise(times)]
    assert all(anim.HUNCH_MIN_GAP <= g <= anim.HUNCH_MAX_GAP for g in gaps)
    assert len(set(gaps)) >= 3


def test_note_hunch_off_clears_schedule():
    c = Animator(seed=13)
    c.note_hunch(T0, True)
    assert c._hunch_next_at is not None
    c.note_hunch(T0 + 1.0, False)
    assert c._hunch_next_at is None
    for i in range(120):
        c.note_hunch(T0 + 2.0 + i, False)
    assert c._hunch_at == -99.0


def test_hunch_reset_clears_state():
    c = Animator(seed=23)
    c.note_hunch(T0, True)
    assert c._hunch_next_at is not None
    c.hunch(T0 + 1.0)
    c.reset(T0 + 2.0)
    assert c._hunch_at == -99.0
    assert c._hunch_next_at is None


from sammy.pet import SammyWindow  # noqa: E402


# 窗口链路：心情 -> 动画层 / 闸门
def _mk():
    w = SammyWindow(autoconnect=False)
    w.timer.stop()
    w.anim = anim.Animator(seed=7, blink_gap=(600.0, 600.0))
    w.look_on = False
    w.set_expression(2)
    w.finish_typing()
    w.anim_t = 8.0
    return w


def test_window_feeds_valence_to_the_anim_layer():
    w = _mk()
    w.drives.last_update = time.time() + 10.0
    w.mood.mood.valence = -0.45
    w.anim_t = 50.0
    w._tick()
    f = w.anim.frame_at(50.0)
    a = anim.Animator(seed=7).frame_at(50.0)
    assert f.dx - a.dx >= anim.HUNCH_SQUINT_PX - 1.5
    assert f.squash <= anim.HUNCH_SQUASH_MIN + 1e-9
    assert f.squash >= anim.HUNCH_SQUASH_MIN - 1e-9
    assert f.stretch < a.stretch  # 好奇那点拉高被按比例收掉（方向对：更低）
    w.close()


def test_window_gates_anim_off_and_asleep():
    w = _mk()
    w.drives.last_update = time.time() + 10.0
    w.mood.mood.valence = -0.45
    w.anim_on = False
    w.anim_t = 60.0
    w._tick()
    assert w.anim.frame_at(60.0).squash == 1.0
    w.anim_on = True
    w.anim_t = 61.0
    w._tick()
    assert w.anim.frame_at(61.0).squash < 1.0
    w.drives.asleep = True
    w.anim_t = 62.0
    w._tick()
    assert w.anim.frame_at(62.0).squash == pytest.approx(anim.HUNCH_SQUASH_MIN)
    w.drives.asleep = False
    w.anim_t = 63.0
    w._tick()
    assert w.anim.frame_at(63.0).squash < 1.0
    w.close()


# ── 渲染层：真窗口离屏抓图 ────────────────────────

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402


def _lit_bbox(w: SammyWindow, clip: QRect) -> tuple[int, int, int, int]:
    """clip 里的「不透明亮像素」外接框（按 faces.LIT 常量，不写死色相）。"""
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


def _mk_render(valence: float) -> SammyWindow:
    """稳态窗口：普通脸 + 指定心情底色 —— 只留「绷没绷」一个变量。

    和 test_shrink 的 _mk_render 同一套（scale 1.0 / 800x480 / 钉住种子），
    只把「静止缩量」换成「心情底色」：量到的差异就只归绷住。
    """
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w._relayout()
    w.anim = anim.Animator(seed=7, blink_gap=(600.0, 600.0))
    w.look_on = False
    w.set_expression(2)
    w.finish_typing()
    w.sammy_line = ""
    w.my_line = ""
    w.anim_t = 8.0
    w.anim.set_mood_shrink(1.0)
    w.anim.set_mood_valence(valence)
    return w


def _lit_bbox_face(w: SammyWindow) -> tuple[int, int, int, int]:
    """脸框外扩一圈的区域里，不透明亮像素的外接框（和 test_shrink 同一口径）。"""
    box = w.lay.face
    return _lit_bbox(w, QRect(box.left() - 60, 6, box.width() + 120, 235))


def test_hunch_actually_tightens_the_face_on_screen():
    """双胞胎：绷到底的脸纵向压下去、中心几乎不动、屏幕角落逐像素一致。

    只在纵向断言：脸的美术框比窗口窄，横向本来就被画框裁住，横向量不出区别 ——
    横向那两位（位移与拉高）由动画层的逐点对账负责。
    """
    a = _mk_render(-0.45)
    b = _mk_render(0.2)
    x0a, y0a, x1a, y1a = _lit_bbox_face(a)
    x0b, y0b, x1b, y1b = _lit_bbox_face(b)
    ha, hb = y1a - y0a + 1, y1b - y0b + 1
    assert ha < hb, f"绷住没把脸纵向压下去：{ha} vs {hb}"
    assert abs((y0a + y1a) - (y0b + y1b)) <= 30, "绷住的时候中心上下跑了太多"
    assert abs((x0a + x1a) - (x0b + x1b)) <= 30, "绷住的时候中心左右跑了太多"
    img_a = a.grab().toImage().copy(QRect(4, 4, 60, 40))
    img_b = b.grab().toImage().copy(QRect(4, 4, 60, 40))
    assert bytes(img_a.constBits()) == bytes(img_b.constBits()), (
        "绷住把屏幕角落也动了（脸自己缩，屏不动）"
    )
    a.close()
    b.close()


def test_hunched_face_stays_inside_the_repainted_region():
    """绷到底那一帧必须落在局部重绘区里 —— 在外那圈不刷新（脸会花）。"""
    w = _mk_render(-0.45)
    x0, y0, x1, y1 = _lit_bbox_face(w)
    deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    region = w._face_region()
    assert region.contains(deformed), f"绷到底时脸 {deformed} 冒出重绘区 {region}"
    w.close()


# ── 纪律：速查表与几何预算 ────────────────────────


def test_hunch_tuning_section_is_shipped():
    """速查表第 35 节要对到这一条（纸上写的 = 代码里跑的，见 test_tuning_doc）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "docs" / "TUNING.md").read_text(encoding="utf-8")
    assert "## 35." in text, "速查表缺第 35 节（绷住）"
    for name in ("HUNCH_ABS_BELOW", "HUNCH_RAMP", "HUNCH_SQUASH_MIN"):
        assert name + " = " in text, "第 35 节没钉住 " + name
    strip = root / "docs" / "8h-b2" / "hunch-strip.png"
    assert strip.stat().st_size > 10000, "素材太小，像空壳"


def test_hunch_geometry_guard_is_wired_into_the_budget():
    """全局几何预算守卫（test_yawn）必须把绷住的收量算进去 —— 忘了并入 = 预算悄悄偏松。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "HUNCH_SQUASH_MIN" in text, "test_yawn 的全局预算守卫里没有绷住的压扁通道"
