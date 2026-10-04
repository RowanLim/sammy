"""脸的动画 —— 只测纯函数（GUI 那层不在这里）。

为什么值得单独测：眨眼只有 **110 毫秒**、微动只有 **±2 像素** ——
盯着屏幕看，根本分辨不出"该眨的时候眨了没有"。所以把该验的事变成数字：
频率、时长、幅度、边界、确定性。
"""

from __future__ import annotations

import itertools
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import anim
from sammy.anim import Animator, Frame


def _not_blinking(a: Animator, t: float) -> bool:
    starts = set(a.blink_times(t + 1))
    return all(not (s <= t <= s + anim.BLINK_DURATION) for s in starts)


def test_no_blink_means_no_squash():
    a = Animator(seed=1)
    for t in [0.4, 1.1, 1.9]:
        if _not_blinking(a, t):
            assert a.frame_at(t).squash == 1.0


def test_blink_actually_squashes_the_face():
    """眨眼要真的把脸压扁（否则这条动画等于没做）。"""
    a = Animator(seed=2)
    first = a.blink_times(30)[0]
    mid = first + anim.BLINK_DURATION / 2
    f = a.frame_at(mid)
    assert f.squash < 0.3, f"眨眼到中段还是 {f.squash:.2f}，压得不够"
    assert f.squash >= anim.BLINK_MIN_SQUASH - 1e-6


def test_blink_starts_and_ends_fully_open():
    """眨眼两头必须是完全睁开的 —— 否则会看到"卡住半睁"的鬼影。"""
    a = Animator(seed=3)
    s = a.blink_times(30)[0]
    assert a.frame_at(s).squash == pytest.approx(1.0, abs=0.02)
    assert a.frame_at(s + anim.BLINK_DURATION).squash == pytest.approx(1.0, abs=0.02)
    assert a.frame_at(s - 0.01).squash == 1.0
    assert a.frame_at(s + anim.BLINK_DURATION + 0.01).squash == 1.0


def test_blink_rate_is_human_like():
    """100 秒里眨眼 10~30 次 —— 太频繁像抽风，太少又像死机。"""
    a = Animator(seed=4)
    n = len(a.blink_times(100))
    assert 10 <= n <= 30, f"100 秒眨了 {n} 次"


def test_blink_duration_is_short():
    assert anim.BLINK_DURATION <= 0.2, "眨眼超过 0.2 秒就像在打瞌睡"


def test_sometimes_double_blinks():
    """偶尔连眨两下 —— 真实的人会这样，全都不连反而机械。"""
    a = Animator(seed=6)
    ts = a.blink_times(400)
    gaps = [round(b - a_, 3) for a_, b in itertools.pairwise(ts)]
    assert any(g < 0.35 for g in gaps), "200 秒里一次连眨都没有"


def test_breath_and_sway_stay_within_limits():
    a = Animator(seed=7)
    for i in range(600):
        f = a.frame_at(i * 0.05)
        assert abs(f.dy) <= anim.BREATH_AMPLITUDE, f"呼吸幅度越界：{f.dy}"
        assert abs(f.dx) <= anim.SWAY_AMPLITUDE, f"微动幅度越界：{f.dx}"


def test_breath_and_sway_are_not_synced():
    """两条正弦必须不同频 —— 同频会变成一种机械的圆周摆动。"""
    assert anim.BREATH_PERIOD != anim.SWAY_PERIOD
    a = Animator(seed=8)
    pairs = {(a.frame_at(i * 0.1).dx, a.frame_at(i * 0.1).dy) for i in range(200)}
    assert len(pairs) > 5, "位移组合太单一，看着会像在原地抖"


def test_calm_face_barely_moves_and_never_blinks():
    """睡着/发呆时：位移收敛、不眨眼 —— 睡着还晃来晃去就不像睡着了。"""
    a = Animator(seed=9)
    a.blink_times(50)  # 先安排一批
    for i in range(400):
        f = a.frame_at(i * 0.05, calm=True)
        assert f.squash == 1.0, "睡着时不该眨眼"
        assert abs(f.dy) <= max(1, anim.BREATH_AMPLITUDE * anim.CALM_FACTOR)
        assert abs(f.dx) <= max(1, anim.SWAY_AMPLITUDE * anim.CALM_FACTOR)


def test_expression_change_pops_once_not_forever():
    """换表情弹一下就好 —— 一直放大就是坏了。"""
    a = Animator(seed=10)
    a.pop(at=5.0)
    assert a.frame_at(4.9).pop == 1.0
    assert a.frame_at(5.0 + anim.POP_DURATION / 2).pop > 1.0
    assert a.frame_at(5.0 + anim.POP_DURATION).pop == pytest.approx(1.0, abs=0.01)
    assert a.frame_at(9.0).pop == 1.0


def test_bad_time_heals_instead_of_crashing():
    """时间坏了（负数/巨大的数）不该崩 —— 界面上一个异常就是整个窗口挂掉。"""
    a = Animator(seed=11)
    for t in (-5.0, -0.001, 0.0, 1e6):
        f = a.frame_at(t)
        assert isinstance(f, Frame)


def test_same_seed_gives_the_same_blinks():
    """确定性：出了怪现象要能复现，否则没法查。"""
    assert Animator(seed=42).blink_times(60) == Animator(seed=42).blink_times(60)


def test_reset_drops_past_blinks():
    a = Animator(seed=13)
    a.blink_times(50)
    a.reset(t=40.0)
    assert all(s > 40.0 for s in a.blink_times(41.0))


def test_idle_property_is_true_only_when_nothing_happens():
    assert Frame().idle is True
    assert Frame(dy=1).idle is False
    assert Frame(squash=0.9).idle is False
