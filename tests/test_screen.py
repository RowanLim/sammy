"""小屏模式的测试 —— 重点是那个等比映射的数学。

这块的坑很具体：**拉伸**。屏幕宽高比和 800×480（5:3）不一样时，
如果按宽或按高单独缩放，脸就会被拉扁 —— 而"脸被拉扁"是这个产品最不能出的错。
所以这里把映射（`fit`）当纯函数测干净。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import screen
from sammy.screen import Fit, fit

DEV_W, DEV_H = 800, 480  # 5:3


def test_scale_never_stretches():
    """两条边用**同一个**缩放比 —— 这是"不拉伸"的定义。"""
    f = fit(DEV_W, DEV_H, 1280, 720)
    assert f.width / f.height == pytest.approx(DEV_W / DEV_H, rel=1e-3)
    assert f.width <= 1280 and f.height <= 720


def test_wide_screen_leaves_side_bars():
    """屏幕比设备更宽 → 上下贴边、左右留黑边。"""
    f = fit(DEV_W, DEV_H, 1920, 1080)  # 16:9，比 5:3 宽
    assert f.height == 1080, "高的方向该贴满"
    assert f.width < 1920
    assert f.x > 0 and f.y == 0


def test_tall_screen_leaves_top_bottom_bars():
    """屏幕比设备更高（竖屏）→ 左右贴边、上下留黑边。"""
    f = fit(DEV_W, DEV_H, 800, 1280)
    assert f.width == 800, "宽的方向该贴满"
    assert f.height < 1280
    assert f.y > 0 and f.x == 0


def test_exact_match_scales_to_one():
    f = fit(DEV_W, DEV_H, 800, 480)
    assert f.scale == pytest.approx(1.0)
    assert (f.x, f.y, f.width, f.height) == (0, 0, 800, 480)


def test_double_size_is_scale_two():
    """树莓派之外的大屏：整倍放大，仍然不拉伸。"""
    f = fit(DEV_W, DEV_H, 1600, 960)
    assert f.scale == pytest.approx(2.0)
    assert (f.width, f.height) == (1600, 960)


def test_it_is_always_centered():
    for sw, sh in [(1280, 720), (1920, 1080), (1024, 600), (800, 1280), (2560, 1440)]:
        f = fit(DEV_W, DEV_H, sw, sh)
        assert f.x == (sw - f.width) // 2
        assert f.y == (sh - f.height) // 2


def test_never_returns_zero_sized_window():
    """极小屏也要给一个至少 1×1 的窗口，不能返回 0（Qt 会直接崩）。"""
    f = fit(DEV_W, DEV_H, 10, 10)
    assert f.width >= 1 and f.height >= 1


def test_bad_sizes_are_rejected_loudly():
    for args in [(0, 480, 800, 480), (800, 0, 800, 480), (800, 480, 0, 480), (800, 480, 800, 0)]:
        with pytest.raises(ValueError):
            fit(*args)


def test_fit_is_serializable_for_reports():
    d = fit(DEV_W, DEV_H, 1280, 720).as_dict()
    assert set(d) == {"scale", "x", "y", "width", "height"}
    assert all(isinstance(v, int | float) for v in d.values())


def test_every_common_screen_keeps_the_aspect_ratio():
    """常见的几种小屏都过一遍 —— 换屏是常态，这条是防回归的底线。"""
    for sw, sh in [(1024, 600), (1280, 720), (1920, 1080), (1280, 800), (480, 800), (2560, 1080)]:
        f = fit(DEV_W, DEV_H, sw, sh)
        assert f.width / DEV_W == pytest.approx(f.height / DEV_H, rel=1e-3), (
            f"{sw}×{sh} 上比例被拉歪了"
        )
        assert f.width <= sw and f.height <= sh


# ── 选择记住 ──────────────────────────────────────


def test_screen_choice_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "STATE_FILE", tmp_path / "screen.json")
    assert screen.load_preference() is None
    screen.remember("1")
    assert screen.load_preference() == "1"


def test_corrupt_preference_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "STATE_FILE", tmp_path / "screen.json")
    screen.STATE_FILE.write_text("{ 坏 json", encoding="utf-8")
    assert screen.load_preference() is None


def test_screen_state_lives_inside_the_project():
    """隔离要求：状态在项目里（见 test_isolation.py）。"""
    from sammy.paths import project_root

    assert str(screen.STATE_FILE).startswith(str(project_root()))


def test_fit_is_a_plain_dataclass():
    assert Fit(1.0, 0, 0, 800, 480).scale == 1.0
