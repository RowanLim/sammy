"""凝视漂移 + 好奇 + 缓动过渡（第二轮 U2）—— 先写判据，实现对着判据做。

为什么这些必须变成数字（肉眼很难判）：
- 凝视每几秒才换一次方向、一次缓动只有 0.55 秒 —— 盯着看根本数不清"该看不该看"；
- 「好奇」（看向左右边缘时脸纵向拉高 ~7%）在 0.55 倍缩放的窗口里只有几个像素；
- 换表情的交叉淡化 0.38 秒 —— 是不是"啪"地切断，只有逐帧抓图对比能对账。

所以分两层：
- 纯函数层（anim.py 的 Animator）：钉行为 —— 范围、频率、平滑、睡觉冻结、淡化数学；
- 渲染层（真窗口离屏抓图）：钉像素 —— 脸真的横移了、真的拉高了、淡化真的是两帧叠加。
"""

from __future__ import annotations

import itertools
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import anim
from sammy.anim import Animator, Frame

T0 = 10.0  # 热身后的时间（第一个凝视目标一定已经出现）


def _walk(a: Animator, span: float, step: float = 0.05, t0: float = T0):
    """按固定步长走一遍时间轴，返回 [(t, Frame), ...]。"""
    n = int(span / step)
    return [(t0 + i * step, a.frame_at(t0 + i * step)) for i in range(n)]


# ── 凝视：范围与"真的在看" ─────────────────────────


def test_gaze_targets_stay_inside_the_box():
    """望向的位置不许越界 —— 越界就是脸要滑出它的格子。"""
    a = Animator(seed=21)
    for _, f in _walk(a, 240):
        assert abs(f.gx) <= anim.GAZE_MAX_X, f"凝视横向越界：{f.gx}"
        assert abs(f.gy) <= anim.GAZE_MAX_Y, f"凝视纵向越界：{f.gy}"


def test_gaze_actually_roams_both_ways():
    """240 秒里必须看得见"往左看"和"往右看"，且不是小碎步 —— 否则这功能等于没做。"""
    a = Animator(seed=22)
    xs = [f.gx for _, f in _walk(a, 240)]
    assert max(xs) >= anim.GAZE_MAX_X * 0.7, f"从没看向右边缘：max={max(xs)}"
    assert min(xs) <= -anim.GAZE_MAX_X * 0.7, f"从没看向左边缘：min={min(xs)}"
    spread = max(xs) - min(xs)
    assert spread >= anim.GAZE_MAX_X * 1.4, f"左右摆幅太小：{spread}"


def test_gaze_moves_smoothly_never_teleports():
    """两个相邻驱动帧（33ms）之间位移不许跳 —— 跳一下就是"瞬移"，不像眼睛。

    物理上限：幅度 2×GAZE_MAX_X，缓动 0.55 秒，正弦缓动的最大速度
    ≈ (2×10) × (π/2) / 0.55 ≈ 57 像素/秒 → 每帧 ≈ 1.9 像素，取整再宽一点。
    """
    a = Animator(seed=23)
    prev = a.frame_at(T0)
    worst_x = worst_y = 0
    t = T0
    for _ in range(int(60 / anim.ANIM_DT)):
        t += anim.ANIM_DT
        f = a.frame_at(t)
        worst_x = max(worst_x, abs(f.gx - prev.gx))
        worst_y = max(worst_y, abs(f.gy - prev.gy))
        prev = f
    assert worst_x <= 3, f"横向单帧跳了 {worst_x} 像素"
    assert worst_y <= 3, f"纵向单帧跳了 {worst_y} 像素"


def test_gaze_changes_direction_every_few_seconds():
    """换方向的频率：每 2.6~7.4 秒一次 —— 太快像抽搐，太慢像死物。"""
    a = Animator(seed=24)
    n = len(a.gaze_times(250))
    assert 28 <= n <= 105, f"250 秒里换了 {n} 次方向"


def test_gaze_is_deterministic_with_seed():
    assert Animator(seed=42).gaze_times(90) == Animator(seed=42).gaze_times(90)


def test_reset_drops_past_gaze():
    a = Animator(seed=25)
    a.gaze_times(50)
    a.reset(t=40.0)
    assert all(s > 40.0 for s in a.gaze_times(41.0))


# ── 好奇：看向边缘时拉高 ───────────────────────────


def test_curiosity_stretches_face_at_horizontal_edges():
    """越靠左右边缘，脸越"探"（纵向拉高）；正中时不拉。"""
    a = Animator(seed=26)
    frames = [f for _, f in _walk(a, 240)]
    # 正中附近 ≈ 不拉高
    centered = [f for f in frames if abs(f.gx) <= 1]
    assert centered, "240 秒里一次都没经过正中附近？"
    for f in centered:
        assert f.stretch <= 1 + anim.CURIOSITY_STRETCH * 0.05
    # 最边缘（采样里 |gx| 最大的那批）明显更高
    edge = max(frames, key=lambda f: abs(f.gx))
    assert abs(edge.gx) >= anim.GAZE_MAX_X * 0.7
    assert edge.stretch >= 1 + anim.CURIOSITY_STRETCH * 0.45
    # 拉伸只随 |gx| 单调
    pairs = sorted(frames, key=lambda f: abs(f.gx))
    for prev, nxt in itertools.pairwise(pairs):
        assert nxt.stretch >= prev.stretch - 1e-9


# ── 睡觉：凝视冻住，醒来接得上 ──────────────────────


def test_gaze_freezes_while_asleep_and_resumes_without_jump():
    """睡着时眼睛不游走（定格在睡前看向的方向），醒来时从定格处接着缓动过去。"""
    a = Animator(seed=27)
    before = a.frame_at(T0)
    first = a.frame_at(T0 + 0.2, calm=True)
    frozen = [(T0 + 0.2 + i * 0.2, a.frame_at(T0 + 0.2 + i * 0.2, calm=True)) for i in range(150)]
    for _, f in frozen:  # 30 秒里一动不动
        assert (f.gx, f.gy) == (first.gx, first.gy), "睡着时凝视还在游走"
        assert f.stretch == first.stretch
    # 睡前→入睡第一帧：连续（不是"跳回正中"）
    assert abs(first.gx - before.gx) <= 3 and abs(first.gy - before.gy) <= 3
    # 醒来第一帧：从定格处接上（不跳）
    wake = a.frame_at(T0 + 40.0, calm=False)
    assert abs(wake.gx - first.gx) <= 1, f"醒来跳了：{first.gx} → {wake.gx}"
    assert abs(wake.gy - first.gy) <= 1
    # 醒来之后恢复游走（2 秒后已经在往新目标动或到达）
    later = [a.frame_at(T0 + 42.0 + i * 0.25, calm=False) for i in range(40)]
    assert any((f.gx, f.gy) != (wake.gx, wake.gy) for f in later), "醒来后凝视不再动"


# ── 缓动过渡（换表情：交叉淡化） ────────────────────


def test_first_expression_never_fades():
    """第一次设表情没有"上一张脸" —— 不许凭空淡化。"""
    a = Animator(seed=31)
    a.set_expression(9, 2.0)
    assert a.expr_fade(2.0) == (None, 1.0)
    assert a.expr_fade(90.0) == (None, 1.0)


def test_fade_starts_from_old_face_and_ends_clean():
    a = Animator(seed=32)
    a.set_expression(3, 0.0)
    a.set_expression(4, 5.0)
    prev, alpha = a.expr_fade(5.0)
    assert prev == 3 and alpha == pytest.approx(0.0, abs=1e-6), "淡化起点必须是老脸全可见"
    prev, alpha = a.expr_fade(5.0 + anim.FADE_DURATION / 2)
    assert prev == 3 and alpha == pytest.approx(0.5, abs=0.01), "中段应该正好各一半"
    assert a.expr_fade(5.0 + anim.FADE_DURATION) == (None, 1.0)
    assert a.expr_fade(9.0) == (None, 1.0)


def test_fade_alpha_is_eased_not_linear():
    """缓动的形状：两端慢、中间快（线性淡化看着像机械渐变）。"""
    a = Animator(seed=33)
    a.set_expression(3, 0.0)
    a.set_expression(4, 10.0)
    q1 = a.expr_fade(10.0 + anim.FADE_DURATION * 0.25)[1]
    q3 = a.expr_fade(10.0 + anim.FADE_DURATION * 0.75)[1]
    assert q1 < 0.22, f"1/4 处已经 {q1:.2f}，太线性"
    assert q3 > 0.78, f"3/4 处才 {q3:.2f}，太线性"


def test_fade_restarts_when_interrupted():
    """淡化未完又换脸：从"上一张要显示的脸"重新起步，别把旧中间态留着。"""
    a = Animator(seed=34)
    a.set_expression(3, 0.0)
    a.set_expression(4, 5.0)
    a.set_expression(6, 5.2)
    assert a.expr_fade(5.2) == (4, pytest.approx(0.0, abs=1e-6))
    assert a.expr_fade(5.2 + anim.FADE_DURATION)[0] is None


def test_same_expression_does_not_start_a_fade():
    a = Animator(seed=35)
    a.set_expression(4, 0.0)
    a.set_expression(4, 1.0)
    assert a.expr_fade(1.0) == (None, 1.0)


def test_instant_mode_never_fades():
    """动画关着（SAMMY_ANIM=off）时没有时间轴，只能瞬间切 —— 也不许留淡化状态。"""
    a = Animator(seed=36)
    a.set_expression(3, 0.0)
    a.set_expression(4, None)
    assert a.expr_fade(0.0) == (None, 1.0)
    assert a.expr_fade(99.0) == (None, 1.0)
    # 之后的正常切换仍然从 4 淡出（_expr 没丢）
    a.set_expression(6, 100.0)
    assert a.expr_fade(100.0)[0] == 4


# ── 与老行为共存 ───────────────────────────────────


def test_idle_property_covers_gaze_and_stretch():
    assert Frame().idle is True
    assert Frame(gx=1).idle is False
    assert Frame(gy=-1).idle is False
    assert Frame(stretch=1.01).idle is False


def test_calm_still_kills_blink_and_dampens_sway():
    """老判据在加了凝视之后仍然成立（睡觉不眨眼、位移收敛）。"""
    a = Animator(seed=37)
    a.blink_times(50)
    for i in range(400):
        f = a.frame_at(T0 + i * 0.05, calm=True)
        assert f.squash == 1.0
        assert abs(f.dy) <= max(1, anim.BREATH_AMPLITUDE * anim.CALM_FACTOR)
        assert abs(f.dx) <= max(1, anim.SWAY_AMPLITUDE * anim.CALM_FACTOR)


# ── 渲染层：真窗口离屏抓图，像素真的动了吗 ──────────
# （纯函数说"该动"，这里说"屏幕上真的动了" —— 两码事。）

from PySide6.QtCore import QRect  # noqa: E402

GREEN_MIN = 80  # 荧光绿判据：g 通道 > 80 且 g > 2r、g > 2b（见 tests 校准）
SEED_GAZE = 7  # 校准过的种子：400 秒内左右都探到边
SEED_FADE = 8


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """别碰用户真实的状态文件（和 test_pet 同一套隔离）。"""
    from sammy import attention, care, drives

    monkeypatch.setattr(attention, "STATE_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(drives, "STATE_FILE", tmp_path / "drives.json")
    monkeypatch.setattr(care, "STATE_FILE", tmp_path / "care.json")


@pytest.fixture
def win(qapp):
    from sammy.pet import SammyWindow

    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()  # 时间轴由测试自己拨（不给定时器抢）
    yield w
    w.close()


def _face_region(win_) -> QRect:
    """脸那一块（比布局的脸框略放宽，横移后也不裁掉）。"""
    r = win_.lay.face.adjusted(-10, -10, 10, 2)
    s = win_.scale
    return QRect(
        int(r.x() * s) + win_._offset[0],
        int(r.y() * s) + win_._offset[1],
        int(r.width() * s) + 2,
        int(r.height() * s) + 2,
    )


def _green_mask(win_) -> set[tuple[int, int]]:
    """抓图 → 荧光绿像素集合。字节序实测为 [B,G,R,A]（RGB32）。"""
    from PySide6.QtGui import QImage

    img = win_.grab().toImage().convertToFormat(QImage.Format_RGB32)
    buf = bytes(img.constBits())  # 立刻拷贝，别持有视图（faces.py 的教训）
    stride = img.bytesPerLine()
    clip = _face_region(win_).intersected(QRect(0, 0, img.width(), img.height()))
    mask: set[tuple[int, int]] = set()
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            b, g, r = buf[i], buf[i + 1], buf[i + 2]
            if g > GREEN_MIN and g > 2 * r and g > 2 * b:
                mask.add((x, y))
    return mask


def _centroid(mask) -> tuple[float, float]:
    sx = sum(x for x, _ in mask)
    sy = sum(y for _, y in mask)
    return sx / len(mask), sy / len(mask)


def _bbox(mask) -> tuple[int, int, int, int]:
    xs = [x for x, _ in mask]
    ys = [y for _, y in mask]
    return min(xs), min(ys), max(xs), max(ys)


def _clean_times(a, count: int, spread: float) -> tuple[float, float]:
    """扫时间轴，找两个"干净"的定格：一个看向最右、一个看向最左。

    干净 = 没在眨眼（squash==1）、没在弹（pop==1）——免得形态变化污染对比。
    """
    best_right = best_left = None
    t = T0
    while t < 400.0:
        f = a.frame_at(t)
        if f.squash == 1.0 and f.pop == 1.0:
            if best_right is None or f.gx > best_right[1].gx:
                best_right = (t, f)
            if best_left is None or f.gx < best_left[1].gx:
                best_left = (t, f)
        t += 0.05
    assert best_right is not None and best_left is not None
    assert best_right[1].gx - best_left[1].gx >= spread, "种子不好：左右摆幅不够，重新校准"
    return best_right[0], best_left[0]


def test_window_gaze_shifts_the_face_horizontally(win):
    """看向右边缘 vs 左边缘：屏幕上脸的质心要真的横向分开。"""
    w = win
    w.anim = anim.Animator(seed=SEED_GAZE)
    w.set_expression(9)  # 吐舌：没有动图，画面只有凝视在动
    t_right, t_left = _clean_times(w.anim, 2, spread=anim.GAZE_MAX_X * 1.2)

    w.anim_t = t_right
    mask_r = _green_mask(w)
    w.anim_t = t_left
    mask_l = _green_mask(w)

    assert len(mask_r) > 1500 and len(mask_l) > 1500, "抓到的绿像素太少，区域搞错了？"
    cx_r, _ = _centroid(mask_r)
    cx_l, _ = _centroid(mask_l)
    gap = cx_r - cx_l
    expect = (anim.GAZE_MAX_X * 2) * w.scale
    assert gap >= expect * 0.45, f"质心只分开 {gap:.1f}px（期望 ≈{expect:.1f}），脸没在动"


def test_window_face_stretches_when_peering_to_the_side(win):
    """好奇：看向边缘时脸纵向拉高（只拉高、不拉宽）。"""
    w = win
    w.anim = anim.Animator(seed=SEED_GAZE)
    w.set_expression(9)
    t_edge, _ = _clean_times(w.anim, 2, spread=anim.GAZE_MAX_X * 1.2)

    w.anim_t = 0.5  # 第一个目标（≥1 秒后）还没出现：正中、无拉伸
    assert w.anim.frame_at(0.5).gx == 0
    center = _green_mask(w)
    w.anim_t = t_edge
    edge = _green_mask(w)

    _, y0c, _, y1c = _bbox(center)
    _, y0e, _, y1e = _bbox(edge)
    x0c, _, x1c, _ = _bbox(center)
    x0e, _, x1e, _ = _bbox(edge)
    h_gain = (y1e - y0e) - (y1c - y0c)
    assert h_gain >= 2, f"看向边缘时高度只多了 {h_gain}px"
    assert abs((x1e - x0e) - (x1c - x0c)) <= 6, "好奇只许纵向拉高，宽度不该变"


def test_window_crossfade_is_a_real_blend(win):
    """换表情不是"啪"地切断、也不是"已经切完了"：中段应该是两张脸的叠加。"""
    w = win
    w.anim = anim.Animator(seed=SEED_FADE)
    w.set_expression(9)
    w.anim_t = 0.0
    w.set_expression(13)  # 淡化 9→13，从 t=0 起
    w.anim_t = 0.19  # 正好中段（FADE_DURATION=0.38）
    mid = _green_mask(w)

    orig = w.anim.expr_fade
    w.anim.expr_fade = lambda t: (None, 1.0)  # 旁路淡化：拍两张"纯脸"做参照
    pure13 = _green_mask(w)
    w.expression = 9
    pure9 = _green_mask(w)
    w.anim.expr_fade = orig

    assert len(pure9 ^ pure13) >= 500, "参照两张脸差异太小，这个用例选错表情了"
    d9 = len(mid ^ pure9)
    d13 = len(mid ^ pure13)
    assert d9 >= 100, "淡化中画面和纯老脸一模一样 —— 这是硬切"
    assert d13 >= 100, "淡化中画面已经和新脸一模一样 —— 没有过渡"
    total = len(pure9 ^ pure13)
    assert abs((d9 + d13) - total) <= max(60, 0.3 * total), (
        f"叠加代数对不上：d9={d9} d13={d13} 应为 {total}（中段=两张脸各半）"
    )


def test_window_after_fade_finishes_it_looks_exactly_like_the_new_face(win):
    w = win
    w.anim = anim.Animator(seed=SEED_FADE)
    w.set_expression(9)
    w.anim_t = 0.0
    w.set_expression(13)
    w.anim_t = 1.0  # 早该淡完了
    done = _green_mask(w)
    orig = w.anim.expr_fade
    w.anim.expr_fade = lambda t: (None, 1.0)
    pure13 = _green_mask(w)
    w.anim.expr_fade = orig
    assert len(done ^ pure13) <= 30, "淡完之后还有残影"
