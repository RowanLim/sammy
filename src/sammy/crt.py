"""CRT 质感层（第二轮 U4）—— 扫描线 / 辉光 / 暗角，`SAMMY_CRT=off` 可关。

为什么是「物理像素」而不是设计单位：扫的三样东西描的都是**屏幕自己的网格** ——
条纹隔一行一条，暗角贴着窗口边缘。它们锁在窗口上（跨帧不动）、不锁在内容上
（内容动、网格不动）—— 看着才像一台显示器，而不是贴在动画上的一层滤镜。

三件事各在哪：

- **扫描线 + 暗角**：预先烘成一张与窗口同尺寸的覆盖层图（`build_layer`），
  由 `CrtOverlay` 这**单独一个子控件**盖在最上面 —— 只有它能盖住输入框
  （QLineEdit 是独立子控件，画在父窗口里的一切都会被它压住）；
- **辉光**：内容先画进离屏缓冲，**平方挑亮**（x²/255 曲线 —— 暗底平方后
  接近 0、不再给整屏蒙灰）再缩到 1/6 放回（近似高斯），用 Plus（加色）叠回
  去 —— 亮的像素往暗处渗一点，就是「荧光」；
- 动画只重画「脸那一块」时，质感层跟着一起重画同一块（见 pet.py 的接线）。

数字都被 tests/test_crt.py 钉着：隔 2 行压 1 行、alpha 0.15；暗角 55% 半径以内
不暗、角落顶格（VIGNETTE_ALPHA）；辉光 1/4 缩放、0.30 不透明度叠回。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QWidget

# ── 数字（改之前先想清楚：这些都被判据钉着）──
SCANLINE_PERIOD = 2  # 扫描线周期（物理像素）：每 2 行一条暗线
SCANLINE_ALPHA = 0.15  # 暗线的不透明度
VIGNETTE_ALPHA = 0.30  # 四角最暗处的不透明度
VIGNETTE_INNER = 0.55  # 从中心算起，到这个比例的半径才开始压暗
GLOW_DOWNSCALE = 6  # 辉光模糊：缩到这个分之一再放回（近似高斯）
GLOW_OPACITY = 0.40  # 辉光叠回的不透明度（加色）

_OFF_VALUES = {"off", "0", "false", "no"}


def crt_enabled(env: dict | None = None) -> bool:
    """CRT 质感开关（`SAMMY_CRT=off` 关掉）—— 语义和 SAMMY_ANIM 一套。"""
    if env is not None:
        raw = env.get("SAMMY_CRT", "on")
    else:
        from .voice import config

        raw = config("SAMMY_CRT", "on")
    return str(raw or "on").strip().lower() not in _OFF_VALUES


def scanline_rows(y0: int, y1: int, period: int = SCANLINE_PERIOD) -> list[int]:
    """[y0, y1) 里该画暗线的行号：相位锁在**绝对 0 行**，每 period 行一条。"""
    if period <= 0:
        raise ValueError("period 必须为正")
    start = max(0, y0 + (-y0) % period)
    return list(range(start, y1, period))


def vignette_alpha_at(frac: float) -> float:
    """暗角曲线：内圈 0，往外线性加深，到角落顶格（VIGNETTE_ALPHA）。"""
    if frac <= VIGNETTE_INNER:
        return 0.0
    if frac >= 1.0:
        return VIGNETTE_ALPHA
    return VIGNETTE_ALPHA * (frac - VIGNETTE_INNER) / (1.0 - VIGNETTE_INNER)


def blur_downup(img: QImage, factor: int = GLOW_DOWNSCALE) -> QImage:
    """近似高斯模糊：缩到 1/factor（平滑）再放回原尺寸 —— 大图上也便宜。"""
    w, h = img.width(), img.height()
    sw = max(1, round(w / factor))
    sh = max(1, round(h / factor))
    small = img.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out.setDevicePixelRatio(img.devicePixelRatio())
    return out


def square_half(img: QImage) -> QImage:
    """x²/255：用 Multiply 把图和自己乘一遍 —— 辉光的「挑亮」曲线。

    为什么必须先挑亮：直接拿模糊副本来加色的话，连面板的暗底都会「0.3 倍」
    叠回去，整屏被抬亮一档（实测 +4 亮度）—— 那不叫荧光，叫蒙灰。
    平方让暗底（亮度 14 → 0.8）静默、亮脸（220 → 190）照常发光。
    """
    out = img.copy()
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_Multiply)
    p.drawImage(0, 0, img)
    p.end()
    out.setDevicePixelRatio(img.devicePixelRatio())
    return out


def panel_path(panel: QRect, radius: float) -> QPainterPath:
    """面板（圆角矩形）在**设计单位**里的路径 —— 裁剪与合成共用这一个形状。"""
    path = QPainterPath()
    path.addRoundedRect(QRect(panel), float(radius), float(radius))
    return path


def build_layer(
    w_px: int,
    h_px: int,
    *,
    panel: QRect,
    panel_radius: float,
    scale: float,
    offset: tuple[int, int],
    dpr: float,
) -> QImage:
    """把「扫描线 + 暗角」烘成一张与窗口同尺寸的覆盖层图（物理像素、带 alpha）。

    只在窗口尺寸 / 缩放 / 像素密度变化时重建；之后每次重画只是一次贴图。
    """
    img = QImage(max(1, w_px), max(1, h_px), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    # 与绘制层同一套坐标流水线：设计单位 → 窗口逻辑 → 物理像素。
    p.scale(scale, scale)
    p.translate(*offset)
    p.scale(dpr, dpr)
    p.setClipPath(panel_path(panel, panel_radius))  # 一切都只在面板以内
    p.resetTransform()

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, round(SCANLINE_ALPHA * 255)))
    for y in scanline_rows(0, h_px):
        p.drawRect(0, y, w_px, 1)

    center = QPointF(w_px / 2.0, h_px / 2.0)
    grad = QRadialGradient(center, math.hypot(center.x(), center.y()))  # 到最远角落
    grad.setColorAt(0.0, QColor(0, 0, 0, 0))
    grad.setColorAt(VIGNETTE_INNER, QColor(0, 0, 0, 0))
    grad.setColorAt(1.0, QColor(0, 0, 0, round(VIGNETTE_ALPHA * 255)))
    p.setBrush(grad)
    p.drawRect(img.rect())
    p.end()

    img.setDevicePixelRatio(dpr)
    return img


def compose_glow(
    buf: QImage,
    *,
    panel: QRect,
    panel_radius: float,
    scale: float,
    offset: tuple[int, int],
) -> None:
    """把辉光叠进内容缓冲（原地）：挑亮 → 模糊 → Plus 加色，只在面板以内。"""
    soft = blur_downup(square_half(buf), factor=GLOW_DOWNSCALE)
    p = QPainter(buf)
    p.scale(scale, scale)
    p.translate(*offset)
    p.setClipPath(panel_path(panel, panel_radius))
    p.resetTransform()
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    p.setOpacity(GLOW_OPACITY)
    p.drawImage(0, 0, soft)
    p.end()


class CrtOverlay(QWidget):
    """盖在整个窗口上的质感层（扫描线 + 暗角）。

    为什么必须单独一个子控件：输入框（QLineEdit）是独立子控件，父窗口
    paintEvent 里画的一切都会被它压住 —— 想「盖住全部」只能比它更高。
    鼠标穿透（WA_TransparentForMouseEvents）：拖窗口、点输入框、右键菜单照旧。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._layer: QImage | None = None

    def set_layer(self, img: QImage | None) -> None:
        self._layer = img
        self.update()

    def layer(self) -> QImage | None:
        """测试口子：当前质感层成图。"""
        return self._layer

    def paintEvent(self, event) -> None:
        if self._layer is None or self._layer.isNull():
            return
        p = QPainter(self)
        p.drawImage(0, 0, self._layer)
        p.end()
