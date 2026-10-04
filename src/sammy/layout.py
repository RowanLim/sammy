"""版面自适应 —— 同一套设计，铺满任意屏幕。

设计基准仍是 **800×480**（树莓派那块 5 寸屏）。但"等比缩小后塞进屏幕中间"**不算自适应**：
宽屏上左右留黑边、元素挤在中间一条，屏幕越大越难看。

规则改成：

- **竖向按高度等比**（`scale = 高 / 480`）：脸的大小、行距、字号都跟高度走 ——
  脸的形状永远不变形。
- **横向撑满**：左右边距固定，面板 / 状态行 / 分隔线 / 对话行 / 输入框
  都按画布**实际宽度**铺开。
- 两者取**较小的**缩放比，所以画布只会 ≥ 800×480：
  · 比 5:3 更宽的屏（16:9、带鱼屏）→ 多出来的**宽度**被用掉
  · 更窄或竖屏 → 多出来的**高度**被用掉（回复区变高、输入框贴底）
- 在 800×480 上结果与原设计**逐像素一致**（不回归）。

为什么单独一个模块：它是纯函数 —— 各种屏幕尺寸都能测一遍。
"换块屏就错位"这种事不该靠人肉看截图发现（已经吃过一次亏）。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect

from .faces import DEV_H, DEV_W, face_box

# ── 设计基准（800×480 设备单位）──
MARGIN = 46  # 左右边距
CLOSE_R = 20
CLOSE_CX = 752  # 关闭按钮圆心（设计值）
CLOSE_CY = 34
STATUS_Y = 242
DIVIDER_Y = 284
MY_Y, MY_H = 290, 30
REPLY_Y = 324
REPLY_GAP = 6  # 回复区与输入框之间的缝
INPUT_H = 50
BOTTOM = 30  # 输入框离底边
PANEL_INSET = 2
PANEL_RADIUS = 32

# ── 基准字号（都乘 scale）──
FONT_LABEL = 26
FONT_STATUS = 22
FONT_MY = 20
FONT_REPLY = 26
FONT_INPUT = 30


@dataclass(frozen=True)
class Layout:
    """某块屏上的版面：**像素**坐标（画的时候不用再缩放）。"""

    win_w: int
    win_h: int
    scale: float
    canvas_w: float  # 画布宽（设备单位，≥ DEV_W）
    canvas_h: float
    panel: QRect
    panel_radius: int
    face: QRect
    close_c: QPoint
    close_r: int
    status: QRect
    divider_y: int
    my_line: QRect
    reply: QRect
    input: QRect
    font_label: int
    font_status: int
    font_my: int
    font_reply: int
    font_input: int

    def describe(self) -> str:
        return (
            f"{self.win_w}×{self.win_h}（缩放 {self.scale:.2f}，"
            f"画布 {self.canvas_w:.0f}×{self.canvas_h:.0f}）"
        )


def layout_for(win_w: int, win_h: int) -> Layout:
    """按窗口像素尺寸算出整套版面。"""
    if win_w <= 0 or win_h <= 0:
        raise ValueError(f"窗口尺寸必须为正：{win_w}×{win_h}")

    # 两个方向取较小者 → 画布不会小于设计基准
    scale = min(win_w / DEV_W, win_h / DEV_H)
    cw = win_w / scale  # 画布宽（设备单位）
    ch = win_h / scale

    def px(v: float) -> int:
        """设备单位 → 像素。"""
        return round(v * scale)

    m = px(MARGIN)
    inner_w = max(1, px(cw) - 2 * m)

    fb = face_box()  # 设计里的脸位置
    face = QRect(
        (px(cw) - px(fb.width())) // 2,  # **横向居中**（不跟宽度拉伸，免得脸变形）
        px(fb.y()),
        px(fb.width()),
        px(fb.height()),
    )

    input_h = px(INPUT_H)
    input_y = px(ch) - input_h - px(BOTTOM)  # 输入框贴底
    reply_y = px(REPLY_Y)
    # 回复区从设计位置一直伸到输入框上方 —— 高屏就把多出来的高度给它
    reply_h = max(px(40), input_y - px(REPLY_GAP) - reply_y)

    return Layout(
        win_w=win_w,
        win_h=win_h,
        scale=scale,
        canvas_w=cw,
        canvas_h=ch,
        panel=QRect(
            px(PANEL_INSET),
            px(PANEL_INSET),
            px(cw) - 2 * px(PANEL_INSET),
            px(ch) - 2 * px(PANEL_INSET),
        ),
        panel_radius=px(PANEL_RADIUS),
        face=face,
        close_c=QPoint(px(cw) - px(DEV_W - CLOSE_CX), px(CLOSE_CY)),
        close_r=px(CLOSE_R),
        status=QRect(m, px(STATUS_Y), inner_w, px(36)),
        divider_y=px(DIVIDER_Y),
        my_line=QRect(m, px(MY_Y), inner_w, px(MY_H)),
        reply=QRect(m, reply_y, inner_w, reply_h),
        input=QRect(m, input_y, inner_w, input_h),
        font_label=px(FONT_LABEL),
        font_status=px(FONT_STATUS),
        font_my=px(FONT_MY),
        font_reply=px(FONT_REPLY),
        font_input=px(FONT_INPUT),
    )


__all__ = ["BOTTOM", "MARGIN", "Layout", "layout_for"]
