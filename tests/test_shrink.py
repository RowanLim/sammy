"""蔫过头（自选小步·第二十五次）——「心情蔫透了，静止姿态自己收一小圈」。

动机：蔫一会儿（第二十三次）补的是「垂」的那一下 —— 头沉下去、停住、缓起来。
可动作是瞬时的：一垂 3.9 秒，垂与垂之间隔 60~150 秒。心情从早到晚都蔫的
时候，两个动作之间的它看起来又正常了 —— 底色没跟上。这条补的就是那段之间：
心情落进「有点蔫」以下，让它的静止姿态自己收一小圈（不是变矮，是整个人小
一号，缩到 94%）。

它是全表第一次「心情直接改静止姿态」—— 以前心情只决定摆哪张脸
（mood.idle_expression），现在连那张脸多大也归它管。也是第一批不排期、不占
随机流、不掷骰子的东西：它一直在（只要心情在线下面），像呼吸和微动一样属于底噪。

三块机制：
- 曲线：mood_shrink 一条纯函数（心情 -> 缩放），线以上恒 1.0、线到心情下限
之间线性收到 94%；和动作曲线不一样 —— 它不随时间动；
- 闸门：mood_shrink_ok（动画关 / 睡着不收）—— 收在 mood.shrink_for 里统一道；
- 落点：窗口 _tick 每秒喂一次 set_mood_shrink，Frame.shrink 带上它，绘制端把
shrink 并进缩放（纵向横向两路都乘）—— 脸自己缩，屏幕不动。

四层判据（和 test_droop 一个框架）：
1. 纯函数：曲线逐点对账（线上下、下限截断、量级、单调、确定性）；
2. 动画层：喂进去就挂上、不占随机流、不动别的通道、reset 后还在；
3. 渲染（真窗口离屏双胞胎）：脸真的缩了（宽高比约 0.94）、中心不动、缩完仍
落在重绘区里；
4. 素材与文档纪律：素材脚本存在、速查表第 34 节与代码逐条对账。

（设计数字：MOOD_SHRINK_ 常量在 anim.py 顶部；调参速查表第 34 节。）
"""

from __future__ import annotations

import pathlib
import time
from itertools import pairwise

import pytest

from sammy import anim, mood
from sammy.anim import Animator

pytestmark = pytest.mark.usefixtures("qapp")

T0 = 30.0


# ── 纯函数层：心情 -> 静止缩放 ────────────────────


def test_shrink_constants_stay_subtle():
    """常量停在「收一小圈」的量级：看得出来但不夸张、和别的档位不打架。"""
    assert 0.90 <= anim.MOOD_SHRINK_MIN <= 0.97, "收得太狠就变形、太轻看不见"
    assert anim.MOOD_SHRINK_BELOW == -0.05, "和心情标签的「有点蔫」必须同档"
    assert anim.MOOD_SHRINK_FLOOR <= anim.MOOD_SHRINK_BELOW, "下限得在线下面"
    assert anim.MOOD_SHRINK_FLOOR == mood.FLOOR, "下限和心情自己的下限是同一把尺"


def test_shrink_curve_above_the_line_is_flat():
    """线以上一点都不收（平静 / 高兴的它和以前逐值相同）—— 这条改的是底色，不是态度。"""
    for v in (1.0, 0.5, 0.0, -0.04):
        assert anim.mood_shrink(v) == 1.0, v
    assert anim.mood_shrink(-0.05) == 1.0, "门线上（含）还不收 —— 严格低于才收"


def test_shrink_curve_is_linear_to_the_floor():
    """线到下限之间线性收到 94%，到下限为止；比下限更低不更收（心情自己在下限截断）。"""
    span = anim.MOOD_SHRINK_BELOW - anim.MOOD_SHRINK_FLOOR
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = anim.MOOD_SHRINK_BELOW - span * frac
        want = 1.0 - (1.0 - anim.MOOD_SHRINK_MIN) * frac
        assert anim.mood_shrink(v) == pytest.approx(want, abs=1e-6), (frac, v)
    assert anim.mood_shrink(anim.MOOD_SHRINK_FLOOR) == pytest.approx(anim.MOOD_SHRINK_MIN)
    assert anim.mood_shrink(-0.9) == pytest.approx(anim.MOOD_SHRINK_MIN), "更低不更收"


def test_shrink_curve_is_monotone_and_deterministic():
    """越蔫越收（不回头）、同一条心情永远同一个数 —— 底色不能被随机数碰。"""
    vals = [anim.mood_shrink(-0.05 - i * 0.02) for i in range(25)]
    assert all(b <= a for a, b in pairwise(vals)), "蔫过头反而收回来了"
    assert len(set(vals)) > 5, "整段几乎没变化 —— 曲线是焊死的？"
    assert anim.mood_shrink(-0.3) == anim.mood_shrink(-0.3)


def test_gate_only_blocks_anim_off_and_asleep():
    """闸门只管两件事：动画关着不收（没有时间轴就没有静止姿态）、睡着不收（睡相归 calm）。"""
    assert anim.mood_shrink_ok(True, False) is True
    assert anim.mood_shrink_ok(False, False) is False, "动画关着还收"
    assert anim.mood_shrink_ok(True, True) is False, "睡着还收（和睡相抢位置）"
    assert anim.mood_shrink_ok(False, True) is False


def test_mood_shrink_for_folds_the_gate_in():
    """mood.shrink_for = 曲线 + 闸门（窗口只喂这一个数，别自己判两道）。"""
    assert mood.shrink_for(-0.4, True, False) == pytest.approx(anim.mood_shrink(-0.4))
    assert mood.shrink_for(-0.4, False, False) == 1.0, "动画关还收"
    assert mood.shrink_for(-0.4, True, True) == 1.0, "睡着还收"
    assert mood.shrink_for(0.5, True, False) == 1.0, "心情好还收"


# ── 动画层：喂进去就挂上、不占随机流 ───────────────


def test_animator_defaults_to_no_shrink():
    """没喂过 = 一点都不收（1.0）—— 默认值和「安静摆着」是同一个意思。"""
    a = Animator(seed=7)
    for i in range(1, 40):
        f = a.frame_at(round(i * 0.033, 6))
        assert f.shrink == 1.0, i
    assert a.frame_at(1.0).shrink == 1.0


def test_set_mood_shrink_is_sticky_and_does_not_touch_rng():
    """它一直在、不排期、不掷骰子：喂之前喂之后，眨眼 / 凝视两条随机流逐位相同。"""
    a, b = Animator(seed=31), Animator(seed=31)
    a.set_mood_shrink(0.94)
    live = 0
    for i in range(1, 401):
        t = round(i * 0.033, 6)
        fa, fb = a.frame_at(t), b.frame_at(t)
        assert fa.shrink == pytest.approx(0.94), t
        assert (fa.dx, fa.dy, fa.gx, fa.gy, fa.squash, fa.stretch) == (
            fb.dx,
            fb.dy,
            fb.gx,
            fb.gy,
            fb.squash,
            fb.stretch,
        ), f"{t} 收一圈把别的通道带偏了"
        live += 1
    assert live == 400


def test_reset_keeps_the_baseline_and_clears_it():
    """时间线被拨动（reset）也不要把它擦掉 —— 底色不归时间管；喂 1.0 才回常态。"""
    a = Animator(seed=11)
    a.set_mood_shrink(anim.MOOD_SHRINK_MIN)
    a.reset(50.0)
    assert a.frame_at(50.5).shrink == pytest.approx(anim.MOOD_SHRINK_MIN)
    a.set_mood_shrink(1.0)
    assert a.frame_at(50.5).shrink == 1.0


# ── 链路：窗口把「心情蔫不蔫」喂给动画层 ─────────────


def _mk():
    """稳态窗口：种子 / 表情 / 时间轴全钉住 —— 只留「静止收一圈」一个变量。"""
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
    w.anim_t = 8.0
    return w


def test_window_feeds_shrink_only_when_wilting():
    w = _mk()
    w.drives.last_update = time.time() + 10.0
    w.mood.mood.valence = 0.2
    w.anim_t = 50.0
    w._tick()
    assert w.anim.frame_at(50.0).shrink == 1.0, "心情好着就收了"
    w.mood.mood.valence = anim.MOOD_SHRINK_BELOW
    w.anim_t = 51.0
    w._tick()
    assert w.anim.frame_at(51.0).shrink == 1.0, "门线上不该收"
    w.mood.mood.valence = anim.MOOD_SHRINK_FLOOR
    w.anim_t = 52.0
    w._tick()
    assert w.anim.frame_at(52.0).shrink == pytest.approx(anim.MOOD_SHRINK_MIN)
    w.mood.mood.valence = 0.3
    w.anim_t = 53.0
    w._tick()
    assert w.anim.frame_at(53.0).shrink == 1.0, "缓回来没收回去"
    w.close()


def test_window_gates_anim_off_and_asleep():
    """动画关 / 睡着：一律不收 —— 闸门在 mood.shrink_for 里，窗口不该绕过它。"""
    w = _mk()
    w.drives.last_update = time.time() + 10.0
    w.mood.mood.valence = -0.4
    w.anim_on = False
    w.anim_t = 60.0
    w._tick()
    assert w.anim.frame_at(60.0).shrink == 1.0, "动画关着还收"
    w.anim_on = True
    w.anim_t = 61.0
    w._tick()
    assert w.anim.frame_at(61.0).shrink == pytest.approx(anim.mood_shrink(-0.4)), "开着却不收"
    w.drives.asleep = True
    w.anim_t = 62.0
    w._tick()
    assert w.anim.frame_at(62.0).shrink == 1.0, "睡着还收（和睡相抢位置）"
    w.drives.asleep = False
    w.anim_t = 63.0
    w._tick()
    assert w.anim.frame_at(63.0).shrink == pytest.approx(anim.mood_shrink(-0.4))
    w.close()


# ── 渲染层：真窗口离屏抓图 ────────────────────────

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from sammy.pet import SammyWindow  # noqa: E402


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


def _mk_render(shrink: float) -> SammyWindow:
    """稳态窗口：普通脸 + 指定静止缩放 —— 只留「收一圈」一个变量。"""
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
    w.anim.set_mood_shrink(shrink)
    return w


def test_shrink_actually_shrinks_the_face_and_keeps_the_centre():
    """scale 1.0 双胞胎：脸宽高都收到约 94%、中心不动、屏幕角落逐像素一致。"""
    a = _mk_render(anim.MOOD_SHRINK_MIN)
    b = _mk_render(1.0)
    box = a.lay.face
    clip = QRect(box.left() - 60, 6, box.width() + 120, 235)
    x0a, y0a, x1a, y1a = _lit_bbox(a, clip)
    x0b, y0b, x1b, y1b = _lit_bbox(b, clip)
    wa, ha = x1a - x0a, y1a - y0a
    wb, hb = x1b - x0b, y1b - y0b
    assert abs(wa / wb - anim.MOOD_SHRINK_MIN) <= 0.02, f"宽比 {wa / wb:.4f}"
    assert abs(ha / hb - anim.MOOD_SHRINK_MIN) <= 0.02, f"高比 {ha / hb:.4f}"
    assert abs((x0a + x1a) - (x0b + x1b)) <= 3, "缩的时候中心左右跑了"
    assert abs((y0a + y1a) - (y0b + y1b)) <= 3, "缩的时候中心上下跑了"
    img_a = a.grab().toImage().copy(QRect(4, 4, 60, 40))
    img_b = b.grab().toImage().copy(QRect(4, 4, 60, 40))
    assert bytes(img_a.constBits()) == bytes(img_b.constBits()), (
        "缩一圈把屏幕角落也动了（脸自己缩，屏不动）"
    )
    a.close()
    b.close()


def test_shrunken_face_stays_inside_the_repainted_region():
    """收到底那一帧必须落在局部重绘区里 —— 在外那圈不刷新（脸会花）。"""
    w = _mk_render(anim.MOOD_SHRINK_MIN)
    box = w.lay.face
    clip = QRect(box.left() - 60, 6, box.width() + 120, 235)
    x0, y0, x1, y1 = _lit_bbox(w, clip)
    deformed = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    region = w._face_region()
    assert region.contains(deformed), f"收到底时脸 {deformed} 冒出重绘区 {region}"
    w.close()


# ── 纪律：素材与速查表 ────────────────────────────


def test_shrink_tuning_section_is_shipped():
    """速查表第 34 节要对到这一条（纸上写的 = 代码里跑的，见 test_tuning_doc）。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    tuning = root / "docs" / "TUNING.md"
    text = tuning.read_text(encoding="utf-8")
    assert "## 34." in text, "速查表缺第 34 节（蔫过头）"
    for name in ("MOOD_SHRINK_BELOW", "MOOD_SHRINK_MIN", "MOOD_SHRINK_FLOOR"):
        assert name + " = " in text, "第 34 节没钉住 " + name
    strip = root / "docs" / "8h-b2" / "shrink-strip.png"
    assert strip.stat().st_size > 10000, "素材太小，像空壳"


def test_shrink_geometry_guard_is_wired_in_the_budget():
    """全局几何预算守卫（test_yawn）必须把静止缩放算进去 —— 忘了并入 = 脸会花。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "tests" / "test_yawn.py").read_text(encoding="utf-8")
    assert "MOOD_SHRINK_MIN" in text, "test_yawn 的全局预算守卫里没有静止缩放通道"
