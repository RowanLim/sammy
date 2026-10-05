"""动图表情：加载、循环、回落。

为什么值得测：动图是**运行时读盘**的。文件没了、GIF 坏了、帧时长读不出来 ——
这些只会表现为"脸不动了"或者"卡住"，**不会报错**。
静默失效必须钉住，否则等看到屏幕上不动，还得从头查是不是渲染、是不是定时器。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import faces
from sammy.expressions import EXPR_NAMES

pytestmark = pytest.mark.usefixtures("qapp")

ANIMATED = 21  # 爱心（肯定配了动图的那个）


def _total(index: int) -> float:
    return sum(d for _, d in faces.motion(index)) / 1000.0


def test_anim_gifs_are_shipped():
    """动图必须跟着仓库走 —— 没进仓库的话换台机器就没表情了。"""
    assert faces.motion_count() >= 10, f"只找到 {faces.motion_count()} 个动图"


def test_motion_loads_frames_with_delays():
    frames = faces.motion(ANIMATED)
    assert frames, "爱心没有动图"
    assert len(frames) >= 4, "帧太少，动不起来"
    for img, delay in frames:
        assert (img.width(), img.height()) == (128, 64), "尺寸被改过？"
        assert delay > 0, "帧时长读不出来（GIF 会一直停在同一帧）"


def test_motion_frames_are_transparent():
    """必须是透明底：否则会盖住面板底色，看着像贴了张黑纸。

    ⚠️ 用 `pixelColor()` 判断 alpha：`QColor(img.pixel(x,y))` 会把 QRgb 当
    **预定义颜色**解释（0x0 → 不透明黑），于是"透明"永远测不出来 ——
    这个错让生成器把整张图都当成亮的，动图退化成静态图。
    """
    img = faces.motion(ANIMATED)[0][0]
    assert img.pixelColor(0, 0).alpha() == 0, "左上角不透明（动图会盖住面板底色）"
    lit = sum(
        1
        for y in range(0, img.height(), 4)
        for x in range(0, img.width(), 4)
        if img.pixelColor(x, y).alpha() > 0
    )
    assert 0 < lit < (img.width() // 4) * (img.height() // 4), "整张图都是不透明的（不是透明底）"


def test_motion_frame_changes_over_time():
    """时间推进要真的换帧 —— 只加载不换帧等于静态图。"""
    total = _total(ANIMATED)
    a = faces.motion_frame(ANIMATED, 0.0)
    b = faces.motion_frame(ANIMATED, total * 0.5)
    assert a is not None and b is not None
    assert a is not b, "半个循环后还是同一帧"


def test_motion_frame_wraps_without_gaps():
    """循环必须连续：时间溢出后回到开头，**不能返回 None**（否则脸会闪空一下）。"""
    total = _total(ANIMATED)
    for t in (0.0, total * 0.99, total, total * 3.5, total * 100 + 0.01):
        assert faces.motion_frame(ANIMATED, t) is not None, f"t={t} 取不到帧"


def test_expression_without_gif_falls_back_to_static():
    """没有动图的表情必须能回落 —— 动图是加分项，不该成为崩溃点。"""
    without = [n for n in EXPR_NAMES if faces.motion_cached(n) is None]
    assert without, "所有表情都配了动图？那这条测试该改成别的"
    assert faces.motion_frame(without[0], 1.0) is None


def test_motion_is_cached_not_reread_every_frame():
    """每帧读盘会卡 —— 必须走缓存。"""
    faces.motion_cached(ANIMATED)
    a = faces.motion_cached(ANIMATED)
    b = faces.motion_cached(ANIMATED)
    assert a is b, "每次调用都重新读盘了"


def test_missing_gif_is_not_an_error():
    """文件不存在要安静地返回 None（那时候就该退回静态脸），不该抛异常。"""
    assert faces.motion(99999) is None


def test_face_pixmap_kept_its_cache():
    """face_pixmap 每帧都会被调用（没有动图时就是它画脸），缓存不能丢。"""
    assert hasattr(faces.face_pixmap, "cache_info"), "缓存被谁拿掉了"
