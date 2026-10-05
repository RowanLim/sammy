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

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics

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

FAMILY = "PingFang SC"  # 中文优先；Linux 上找不到会回落到系统默认无衬线（有中文字形）

# ── 回复区排版 ──────────────────────────────
# 从大到小试。都放不下就**翻页**，绝不硬画到框外（硬画的后果是句子被悄悄切掉，
# 实测用户第一眼看到的就是"话说到一半没了"）。
REPLY_SIZES = (26, 24, 22, 20, 18)
PAGE_SECONDS = 3.6  # 翻页间隔：够读完一页，又不至于让人等
REPLY_FLAGS = Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap
_BREAKS = "。！？；，、…—!?;,. \n"  # 优先在这些地方断开，别把词从中间劈开


@dataclass(frozen=True)
class ReplyFit:
    """回复区排版的结论：用多大字、分几页、要不要翻。"""

    size: int
    pages: tuple[str, ...]
    paged: bool  # True = 一次放不下，正在翻页

    def page_at(self, t: float) -> str:
        """第 t 秒该显示哪一页。"""
        if len(self.pages) <= 1:
            return self.pages[0]
        return self.pages[int(t / PAGE_SECONDS) % len(self.pages)]

    def index_at(self, t: float) -> int:
        if len(self.pages) <= 1:
            return 0
        return int(t / PAGE_SECONDS) % len(self.pages)


def _reply_flags():
    return REPLY_FLAGS


def _fits(text: str, rect: QRect, font: QFont) -> bool:
    return QFontMetrics(font).boundingRect(rect, _reply_flags(), text).height() <= rect.height()


def _nice_cut(text: str, limit: int) -> int:
    """在 limit 附近找个"体面"的断点（标点/空格），宁可短一点也不劈开词。"""
    if limit >= len(text):
        return len(text)
    window = text[:limit]
    for i in range(len(window) - 1, max(0, len(window) - 14), -1):
        if window[i] in _BREAKS:
            return i + 1
    return limit


def _split_pages(text: str, rect: QRect, font: QFont) -> tuple[str, ...]:
    """把文本切成"每页都放得下"的若干页。"""
    pages: list[str] = []
    rest = text
    while rest:
        if _fits(rest, rect, font):
            pages.append(rest)
            break
        lo, hi = 1, len(rest)  # 二分找最长能放下的前缀
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _fits(rest[:mid], rect, font):
                lo = mid
            else:
                hi = mid - 1
        cut = _nice_cut(rest, lo)
        if cut <= 0:  # 一个字都放不下（区域太小）—— 至少塞一个字，别死循环
            cut = 1
        pages.append(rest[:cut])
        rest = rest[cut:].lstrip()
    return tuple(pages) or ("",)


def fit_reply(text: str, rect: QRect, sizes: tuple[int, ...] = REPLY_SIZES) -> ReplyFit:
    """在 rect 里放下 text：优先用大字一页放完；放不下就缩小；还放不下就翻页。

    **不许出现"画到框外"**：这是函数存在的唯一理由。
    旧代码从 26 试到 18，全放不下时照样用 18 硬画 → 句子被裁掉且毫无提示。
    """
    if not text:
        return ReplyFit(sizes[0], ("",), False)
    for size in sizes:
        font = QFont(FAMILY, size)
        if _fits(text, rect, font):
            return ReplyFit(size, (text,), False)
    size = sizes[-1]  # 最小的字号都放不下 → 翻页，绝不裁字
    return ReplyFit(size, _split_pages(text, rect, QFont(FAMILY, size)), True)


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


def _layout(win_w: int, win_h: int, *, device: bool) -> Layout:
    """算整套版面。

    `device=True` 返回**设备单位**（配合绘制层的"先 p.scale() 再画"）；
    `device=False` 返回**像素**（画的时候不用再缩放）。
    两种口径来自同一份设计值，所以不会各算各的、互相漂移。
    """
    if win_w <= 0 or win_h <= 0:
        raise ValueError(f"窗口尺寸必须为正：{win_w}×{win_h}")

    # 两个方向取较小者 → 画布不会小于设计基准
    scale = min(win_w / DEV_W, win_h / DEV_H)
    cw = win_w / scale  # 画布宽（设备单位）
    ch = win_h / scale

    def u(v: float) -> int:
        """设备单位 → 输出单位。"""
        return round(v) if device else round(v * scale)

    W = round(cw) if device else win_w
    H = round(ch) if device else win_h

    m = u(MARGIN)
    inner_w = max(1, W - 2 * m)
    input_h = u(INPUT_H)
    input_y = H - input_h - u(BOTTOM)  # 输入框贴底
    reply_y = u(REPLY_Y)
    # 回复区从设计位置一直伸到输入框上方 —— 高屏就把多出来的高度给它
    reply_h = max(u(40), input_y - u(REPLY_GAP) - reply_y)

    fb = face_box()  # 设计里的脸位置
    return Layout(
        win_w=win_w,
        win_h=win_h,
        scale=scale,
        canvas_w=cw,
        canvas_h=ch,
        panel=QRect(
            u(PANEL_INSET),
            u(PANEL_INSET),
            W - 2 * u(PANEL_INSET),
            H - 2 * u(PANEL_INSET),
        ),
        panel_radius=u(PANEL_RADIUS),
        # 脸**横向居中**（不跟宽度拉伸，免得脸变形）
        face=QRect((W - u(fb.width())) // 2, u(fb.y()), u(fb.width()), u(fb.height())),
        close_c=QPoint(W - u(DEV_W - CLOSE_CX), u(CLOSE_CY)),
        close_r=u(CLOSE_R),
        status=QRect(m, u(STATUS_Y), inner_w, u(36)),
        divider_y=u(DIVIDER_Y),
        my_line=QRect(m, u(MY_Y), inner_w, u(MY_H)),
        reply=QRect(m, reply_y, inner_w, reply_h),
        input=QRect(m, input_y, inner_w, input_h),
        font_label=u(FONT_LABEL),
        font_status=u(FONT_STATUS),
        font_my=u(FONT_MY),
        font_reply=u(FONT_REPLY),
        font_input=u(FONT_INPUT),
    )


def layout_for(win_w: int, win_h: int) -> Layout:
    """**像素**版版面（画的时候不用再缩放）。"""
    return _layout(win_w, win_h, device=False)


def layout_dev(win_w: int, win_h: int) -> Layout:
    """**设备单位**版版面（配合绘制层"先 p.scale() 再画"）。

    在 800×480 上逐像素等价于原来的写死常量 —— 接线不该改变设计尺寸上的样子。
    """
    return _layout(win_w, win_h, device=True)


__all__ = ["BOTTOM", "MARGIN", "Layout", "ReplyFit", "fit_reply", "layout_dev", "layout_for"]
