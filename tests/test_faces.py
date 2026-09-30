"""表情目录与渲染取景。"""

import pytest

from sammy import faces
from sammy.expressions import (
    ASSETS_DIR,
    EMOTIONS,
    EXPR_EMOJI,
    EXPR_NAMES,
    expression_for,
    name_of,
)


def test_assets_present():
    assert faces.assets_ready(), f"表情资产缺失: {ASSETS_DIR}"
    assert len(EXPR_NAMES) == 35
    assert len(EXPR_EMOJI) == 35
    for index in EXPR_NAMES:
        assert (ASSETS_DIR / f"{index}.bmp").exists(), f"缺 {index}.bmp"


def test_tables_agree():
    """编号表、emoji 表、情绪映射表必须互相自洽。"""
    assert set(EXPR_NAMES) == set(EXPR_EMOJI)
    for key, index in EMOTIONS.items():
        assert index in EXPR_NAMES, f"情绪 {key} 指向了不存在的表情 {index}"


def test_expression_fallback():
    assert expression_for("happy") == EMOTIONS["happy"]
    assert expression_for("HAPPY") == EMOTIONS["happy"]  # 大小写不敏感
    assert expression_for("不存在的情绪") == 2  # 回落到「普通」
    assert expression_for("") == 2
    assert name_of(999) == "未知"


def test_bboxes_are_sane(qapp):
    """每个表情的描线外框必须在图内、且不为空 —— 这是裁切正确的前提。"""
    boxes = faces._scan_bboxes()
    assert set(boxes) == set(EXPR_NAMES)
    for index, box in boxes.items():
        assert box.width() > 0 and box.height() > 0, f"#{index} 外框为空"
        assert box.x() >= 0 and box.y() >= 0, f"#{index} 外框越界"
        assert box.x() + box.width() <= 128, f"#{index} 外框超宽"
        assert box.y() + box.height() <= 64, f"#{index} 外框超高"


def test_frame_fits_every_face(qapp):
    """统一画框必须装得下最大的那张脸，否则会有脸被切掉。"""
    frame = faces.content_bounds()
    for index, box in faces._scan_bboxes().items():
        assert box.width() <= frame.width(), f"#{index} 比画框还宽"
        assert box.height() <= frame.height(), f"#{index} 比画框还高"


def test_pixmap_actually_has_lit_pixels(qapp):
    """踩过的坑：constBits() 悬空视图导致像素静默丢失、表情碎成几块。
    这里直接数绿像素，丢像素就红。"""
    box = faces.face_box()
    size = faces.face_box().size()
    empty = 0
    for index in EXPR_NAMES:
        pm = faces.face_pixmap(index, size)
        assert not pm.isNull(), f"#{index} 渲染失败"
        img = pm.toImage()
        lit = sum(
            1
            for y in range(0, img.height(), 3)
            for x in range(0, img.width(), 3)
            if img.pixelColor(x, y).green() > 100
        )
        if lit == 0:
            empty += 1
    assert empty == 0, f"{empty} 张表情渲染后没有像素（裁切或阈值化出错）"
    assert box.width() > 0


def test_pixmap_is_cached(qapp):
    """同一 (index, size) 必须命中缓存 —— 绘制在 paintEvent 里，每帧都调。"""
    size = faces.face_box().size()
    first = faces.face_pixmap(4, size)
    second = faces.face_pixmap(4, size)
    assert first is second


def test_render_is_fast(qapp):
    """全量预热要够快，否则窗口启动会卡。"""
    import time

    start = time.perf_counter()
    assert faces.preload() == 35
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize("index", [1, 2, 4, 16, 27])
def test_known_expression_names(qapp, index):
    assert name_of(index) in EXPR_NAMES.values()
