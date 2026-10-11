"""表情渲染层。

架构要点（决定了二期能否平滑搬到树莓派）：
- 所有绘制统一在「设备坐标系」800×480 下进行，最后整体缩放。
- 搬到树莓派 5 寸屏时，缩放系数改成 1.0 即可，元素位置全不用动。
- 资产是白底黑线的手绘涂鸦（暗像素≈5%），OLED 上呈现为「黑底绿光线条」。

取景策略（踩过坑）：
- 每张表情的描线外框大小/位置都不一样。直接用并集外框会让小脸缩在角落，
  用各自的紧贴外框又会让脸在表情切换时忽大忽小、跳来跳去。
- 正解：所有表情共用一个固定画框（最大的那张脸 + 留白），
  每张脸按自身外框「居中」放进画框 —— 大小稳定，位置也稳定。

性能：全程走 constBits() 内存缓冲，不做逐像素 pixelColor 调用
（后者在 35 张图上是秒级，前者是毫秒级）。
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap

from .expressions import ASSETS_DIR, EXPR_NAMES

# 设备分辨率：5 寸 IPS 屏（硬件方案定稿规格）
DEV_W, DEV_H = 800, 480

LIT = QColor("#ffffff")  # 亮起的像素：白（2026-10-12 由荧光绿改白 —— Rowan: 绿色太吓人）

_bboxes: dict[int, QRect] | None = None
_frame: QRect | None = None
_gray_cache: dict[int, tuple[bytes, int, int, int] | None] = {}


def _gray(index: int) -> tuple[bytes, int, int, int] | None:
    """返回 (像素缓冲, 宽, 高, 每行字节数)。灰度 8bit，一像素一字节。

    ⚠️ 坑（踩过一次，症状是表情碎成几块、裁切框乱飘）：
    constBits() 返回的 memoryview 指向 QImage 内部缓冲，而这里 convertToFormat
    出来的 QImage 是局部变量，函数一返回就被回收 —— 缓冲随时可能被下一次
    QImage 分配复用，于是读到的其实是别的图的数据。
    必须立刻 bytes() 拷一份出来，并缓存，避免重复解码。
    """
    if index in _gray_cache:
        return _gray_cache[index]

    img = QImage(str(ASSETS_DIR / f"{index}.bmp"))
    if img.isNull():
        _gray_cache[index] = None
        return None
    g = img.convertToFormat(QImage.Format_Grayscale8)
    buf = bytes(g.constBits())  # ← 拷一份，不持有会失效的视图
    result = (buf, g.width(), g.height(), g.bytesPerLine())
    _gray_cache[index] = result
    return result


def _scan_bboxes() -> dict[int, QRect]:
    """逐张算出描线的紧贴外框。"""
    global _bboxes
    if _bboxes is not None:
        return _bboxes

    boxes: dict[int, QRect] = {}
    for index in EXPR_NAMES:
        loaded = _gray(index)
        if loaded is None:
            continue
        buf, w, h, stride = loaded
        x0, y0, x1, y1 = 10_000, 10_000, -1, -1
        for y in range(h):
            row = y * stride
            for x in range(w):
                if buf[row + x] < 128:  # 暗像素 = 描线 = 要发光的部分
                    if x < x0:
                        x0 = x
                    if x > x1:
                        x1 = x
                    if y < y0:
                        y0 = y
                    if y > y1:
                        y1 = y
        if x1 < 0:
            boxes[index] = QRect(0, 0, 1, 1)
        else:
            boxes[index] = QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    _bboxes = boxes
    return boxes


def content_bounds() -> QRect:
    """统一画框 —— 以「最大的那张脸」为准加留白。"""
    global _frame
    if _frame is not None:
        return _frame
    boxes = _scan_bboxes()
    if not boxes:
        _frame = QRect(0, 0, 128, 64)
        return _frame
    max_w = max(b.width() for b in boxes.values())
    max_h = max(b.height() for b in boxes.values())
    margin = 4
    _frame = QRect(0, 0, max_w + margin * 2, max_h + margin * 2)
    return _frame


def frame_size() -> QSize:
    box = content_bounds()
    return QSize(box.width(), box.height())


def debug_frames() -> str:
    """给自检用：画框尺寸 + 各表情自身外框。"""
    boxes = _scan_bboxes()
    frame = content_bounds()
    lines = [f"统一画框: {frame.width()}×{frame.height()}"]
    for index in sorted(boxes):
        b = boxes[index]
        lines.append(f"  {index:>3} 自身 {b.width():>3}×{b.height():<3} @({b.x()},{b.y()})")
    return "\n".join(lines)


def motion(index: int) -> tuple[tuple[QImage, int], ...] | None:
    """动图表情的帧：`((透明底 QImage, 该帧毫秒), ...)`；没有动图就 None。

    为什么用 GIF：要的就是"动图表情"，而 Qt **自带** GIF 解码
    （`QImageReader` 能逐帧读、并给出 `nextImageDelay()`），
    所以运行时**不依赖 Pillow** —— Pillow 只在生成动图时用
    （见 `scripts/make_anim_gifs.py`）。少一个运行时依赖，打包也小。

    帧时长交给 GIF 自己声明：这样"哪张动得快一点"是美术选择，不用改代码。
    """
    path = ASSETS_DIR / "anim" / f"{index}.gif"
    if not path.is_file():
        return None
    reader = QImageReader(str(path))
    if not reader.canRead():
        return None

    frames: list[tuple[QImage, int]] = []
    # 遍历动图要**反复 read()**（顺序取下一帧）。
    # 别用 jumpToImage(0)：实测它对第 0 帧返回 False，于是整个动图被当成"读不出来"，
    # 静默退回了静态脸 —— 这类失败没有报错，只能靠测试发现。
    for _ in range(240):  # 上限：别让坏文件转不出来
        img = reader.read()
        if img.isNull():
            break
        delay = reader.nextImageDelay() or 80
        frames.append((img.convertToFormat(QImage.Format_ARGB32), int(delay)))
    return tuple(frames) or None


# 动图帧的缓存（磁盘读数次，之后只查内存）
_MOTION_CACHE: dict[int, tuple[tuple[QImage, int], ...] | None] = {}


def motion_cached(index: int):
    """带缓存的 `motion()` —— 每帧都读盘会卡。"""
    if index not in _MOTION_CACHE:
        _MOTION_CACHE[index] = motion(index)
    return _MOTION_CACHE[index]


def motion_frame(index: int, t: float) -> QImage | None:
    """按时间取动图当前该显示的一帧。没有动图返回 None（调用方退回落单张）。"""
    frames = motion_cached(index)
    if not frames:
        return None
    total = sum(d for _, d in frames) / 1000.0
    if total <= 0:
        return frames[0][0]
    x = t % total
    acc = 0.0
    for img, delay in frames:
        acc += delay / 1000.0
        if x < acc:
            return img
    return frames[-1][0]


def motion_count() -> int:
    """有多少个表情配了动图（`--voices` 之类的地方可以用）。"""
    d = ASSETS_DIR / "anim"
    return len(list(d.glob("*.gif"))) if d.is_dir() else 0


@lru_cache(maxsize=64)
def face_pixmap(index: int, size: QSize) -> QPixmap:
    """取某个表情的发光像素图，等比放进 size 里居中。"""
    blank = QPixmap(size)
    blank.fill(Qt.transparent)

    loaded = _gray(index)
    if loaded is None:
        return blank
    buf, w, h, stride = loaded

    own = _scan_bboxes().get(index, QRect(0, 0, w, h))
    frame = content_bounds()
    fw, fh = frame.width(), frame.height()

    # 把这张脸自身的紧贴外框「居中」放进统一画框
    off_x = (fw - own.width()) // 2 - own.x()
    off_y = (fh - own.height()) // 2 - own.y()

    out = QImage(fw, fh, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    lit = LIT.rgba()
    # 遍历整张源图，只靠偏移量平移 —— 不假设外框必然包住内容，避免静默丢像素
    for y in range(h):
        dst_y = y + off_y
        if dst_y < 0 or dst_y >= fh:
            continue
        src_row = y * stride
        for x in range(w):
            if buf[src_row + x] < 128:
                dst_x = x + off_x
                if 0 <= dst_x < fw:
                    out.setPixel(dst_x, dst_y, lit)

    scaled = QPixmap.fromImage(out).scaled(
        size,
        Qt.KeepAspectRatio,
        Qt.FastTransformation,  # 最近邻，保留像素锐利感
    )

    painter = QPainter(blank)
    painter.drawPixmap(
        (size.width() - scaled.width()) // 2,
        (size.height() - scaled.height()) // 2,
        scaled,
    )
    painter.end()
    return blank


def face_box() -> QRect:
    """脸部在 800×480 设备坐标系里的位置。"""
    w, h = 440, 216
    return QRect((DEV_W - w) // 2, 16, w, h)


def preload() -> int:
    """预热：算外框 + 渲染全部表情位图。返回成功张数。"""
    content_bounds()
    box = face_box()
    size = QSize(box.width(), box.height())
    return sum(1 for index in EXPR_NAMES if not face_pixmap(index, size).isNull())


def assets_ready() -> bool:
    return ASSETS_DIR.is_dir() and any(ASSETS_DIR.glob("*.bmp"))


__all__ = [
    "DEV_H",
    "DEV_W",
    "LIT",
    "assets_ready",
    "content_bounds",
    "debug_frames",
    "face_box",
    "face_pixmap",
    "frame_size",
    "preload",
]
