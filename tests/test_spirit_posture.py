"""劲头也管姿态（自选小步·第二十九次）——「冷清也要看得出来」。

动机：第二十八次给心情加了第二根轴（劲头 spirit，正负 1），但它只改了名字：
mood.json 里还是只有一个数；说人话的格子只出现在 --mood 那一行和提示词那一句。
换句话说：一个「走神」的 Sammy 和一个「挺来劲」的 Sammy，静止姿态逐像素相同。
这正是 docs/心情的全谱.md 自己点名的毛病：活物迹象只在有人时才看得到。
你不在的时候它最该像个活物，反而一点变化都没有。

所以这一步让第二根轴也落到静止姿态上，但换一种形变：
- 第一根轴（心情低）= 整个人小一号（mood_shrink，宽高一起缩；已有的，一字不动）；
- 第二根轴（劲头低）= 整个人塌一点（纵向压、横向不缩 —— 没劲是塌下去，不是变小）；
- 劲头高则轻轻提一口气（纵向拉一点点，量级只有塌的一半 —— 别得意忘形）。

为什么不是并进 mood_shrink：那会让两根轴互相代理，而且「低落 + 兴奋」
（心里堵得慌）那一格会被算成反而更小，与全谱的口径打架。
两根轴各管一种形变、谁也盖不住谁，就是这次要钉的东西。

四层判据：
1. 纯函数：线以内恒 1.0（含 0 点）、两头才动、单调、两头截断、确定性、量级不夸张；
2. 不许代理：劲头那根轴不许改 mood_shrink / squash / 凝视 / 随机流；
3. 落点：只在 stretch 上乘一档（其余通道逐值不变 = 真的只动纵向）；
4. 闸门与窗口：动画关 / 睡着不塌（与 mood_shrink 同一道闸门，不另立一条）。

（设计数字：SPIRIT_POSTURE_ 常量在 anim.py 顶部；调参速查表第 35 节。）
"""

from __future__ import annotations

import pytest

from sammy import anim
from sammy.anim import Animator

pytestmark = pytest.mark.usefixtures("qapp")


# -- 纯函数层：劲头 -> 姿态一档 --


def test_spirit_posture_constants_stay_subtle():
    """停在看得出来但不夸张的量级：塌得比缩得浅、提得比塌得浅。"""
    assert 0.95 <= anim.SPIRIT_POSTURE_SINK_MIN <= 0.99
    assert 0.0 < anim.SPIRIT_POSTURE_LIFT_MAX <= 0.05
    assert anim.SPIRIT_POSTURE_FLOOR <= anim.SPIRIT_POSTURE_MILD
    assert anim.SPIRIT_POSTURE_SINK_MIN > anim.MOOD_SHRINK_MIN
    assert anim.SPIRIT_POSTURE_MILD == 0.15


def test_posture_is_flat_inside_the_band():
    """中间的平常什么都不做 —— 绝大多数时候它和加这根轴之前逐值相同。"""
    assert anim.spirit_posture(0.0) == 1.0, "0 点必须逐值不动"
    assert anim.spirit_posture(0.05) == 1.0
    assert anim.spirit_posture(-0.05) == 1.0
    mild = anim.SPIRIT_POSTURE_MILD
    assert anim.spirit_posture(mild) == 1.0, "门线含等号不动"
    assert anim.spirit_posture(-mild) == 1.0, "门线含等号不动"


def test_sinking_is_monotone_and_hits_the_floor():
    """越没劲越塌、到下限为止；比下限更低不更塌。"""
    deep = anim.SPIRIT_POSTURE_FLOOR
    mild = anim.SPIRIT_POSTURE_MILD
    mid = (mild + deep) / 2.0
    a = anim.spirit_posture(-mild - 0.001)
    b = anim.spirit_posture(mid)
    c = anim.spirit_posture(deep)
    assert a > b > c, "越没劲越塌（不回头）"
    assert anim.spirit_posture(deep) == pytest.approx(anim.SPIRIT_POSTURE_SINK_MIN)
    assert anim.spirit_posture(-1.0) == anim.spirit_posture(deep), "更低不更塌"


def test_lifting_is_gentler_than_sinking_and_capped():
    """来劲往上提得比没劲塌得浅 —— 高的一头是加分，不该比低的一头更抢眼。"""
    up = anim.spirit_posture(anim.SPIRIT_POSTURE_MILD + 0.001)
    peak = anim.spirit_posture(1.0)
    down = anim.spirit_posture(anim.SPIRIT_POSTURE_FLOOR)
    assert up > 1.0
    assert peak >= up, "越来劲提得越多（到顶为止）"
    assert (peak - 1.0) < (1.0 - down), "提的幅度必须小于塌的幅度"
    assert peak == pytest.approx(1.0 + anim.SPIRIT_POSTURE_LIFT_MAX)
    assert anim.spirit_posture(9.0) == peak, "越界不越提"


def test_posture_is_deterministic():
    """同一个劲头永远同一个数 —— 底色不能被随机数碰。"""
    assert anim.spirit_posture(-0.3) == anim.spirit_posture(-0.3)
    assert anim.spirit_posture(0.4) == anim.spirit_posture(0.4)


def test_second_axis_never_touches_the_first():
    """核心：劲头这根轴不许改心情那根轴的收量，也不许把门线挪掉。"""
    v = anim.MOOD_SHRINK_FLOOR
    before = anim.mood_shrink(v)
    anim.spirit_posture(0.0)
    anim.spirit_posture(-0.9)
    anim.spirit_posture(0.9)
    assert anim.mood_shrink(v) == before, "心情那根轴被劲头带着走了"
    assert anim.MOOD_SHRINK_BELOW == -0.05, "门线被挪了"


# -- 动画层：喂进去只改纵向，别的通道逐值不动 --


def test_set_spirit_posture_is_sticky_and_touches_only_stretch():
    """喂进去就一直在；眨眼 / 凝视 / 压缩 / 缩放逐值不变 —— 只有纵向那一档动了。"""
    a, b = Animator(seed=31), Animator(seed=31)
    a.set_spirit_posture(0.97)
    assert a.frame_at(1.0).shrink == 1.0
    assert a.frame_at(9.0).stretch == pytest.approx(b.frame_at(9.0).stretch * 0.97), (
        "纵向没按比例挂上"
    )
    assert a.frame_at(2.0).squash == b.frame_at(2.0).squash
    assert a.frame_at(2.0).gx == b.frame_at(2.0).gx and a.frame_at(2.0).gy == b.frame_at(2.0).gy
    assert a.frame_at(2.0).dx == b.frame_at(2.0).dx and a.frame_at(2.0).dy == b.frame_at(2.0).dy
    assert a.frame_at(2.0).pop == b.frame_at(2.0).pop


def test_only_the_vertical_axis_is_scaled():
    """同一条时间线上，a 的 stretch 恰好是 b 的 0.97 倍 —— 别的帧也一样。"""
    a, b = Animator(seed=31), Animator(seed=31)
    a.set_spirit_posture(0.97)
    t = 3.0
    while t < 12.0:
        fa, fb = a.frame_at(round(t, 6)), b.frame_at(round(t, 6))
        assert fa.stretch == pytest.approx(fb.stretch * 0.97), t
        assert fa.squash == fb.squash and fa.shrink == fb.shrink, t
        t = t + 0.5
    assert b.frame_at(3.0).stretch == pytest.approx(Animator(seed=31).frame_at(3.0).stretch), (
        "没喂的它被动了"
    )


def test_reset_keeps_the_posture_and_clearing_restores_it():
    """时间线被拨动（reset）不要把它擦掉 —— 底色不归时间管；喂 1.0 才回常态。"""
    a = Animator(seed=11)
    a.set_spirit_posture(anim.SPIRIT_POSTURE_SINK_MIN)
    a.reset(50.0)
    assert a.frame_at(50.5).stretch == pytest.approx(anim.SPIRIT_POSTURE_SINK_MIN)
    a.set_spirit_posture(1.0)
    assert a.frame_at(50.5).stretch == pytest.approx(1.0)


def test_default_animator_has_no_posture_change():
    """没喂过 = 一点都不塌 —— 默认值和「平常劲头」是同一个意思。"""
    a = Animator(seed=7)
    assert a.frame_at(1.0).stretch == Animator(seed=7).frame_at(1.0).stretch

    assert a.frame_at(1.0).stretch == Animator(seed=7).frame_at(1.0).stretch
    assert a.frame_at(1.0).shrink == 1.0
    assert a.frame_at(1.0).squash == Animator(seed=7).frame_at(1.0).squash


# -- 闸门：和 mood_shrink 同一道，不另立一条 --


def test_posture_gate_folds_into_mood_gate():
    """窗口用的是同一个 shrink_for（动画关 / 睡着回 1.0）—— 塌也走它，不另写一道。"""
    from sammy import mood as m

    assert m.posture_for(-0.9, True, False) == pytest.approx(anim.SPIRIT_POSTURE_SINK_MIN)
    assert m.posture_for(-0.9, False, False) == 1.0, "动画关着还塌"
    assert m.posture_for(-0.9, True, True) == 1.0, "睡着还塌（和睡相抢位置）"
    assert m.posture_for(0.0, True, False) == 1.0, "平常劲头还塌"
