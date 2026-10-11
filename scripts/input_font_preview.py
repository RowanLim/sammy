#!/usr/bin/env python3
"""输入框像素字体素材 —— U1 补完的前后对比（放大 3 倍，最近邻）。

产物（进 docs/8h-b2/，随仓库走）：
- input-font.png   四格：前与后，各拍空框占位 / 已输入文字

为什么做它：U1 换了像素字体，但输入框是 QLineEdit 子控件 —— 它的字走
样式表，而样式表漏了 font-family 这一项，一直静默用系统字体。这一步补上，
素材把「前 / 后」摆在一起给眼睛验。

纪律（和其他 preview 脚本同一套）：
- 「前」是**修复前那份代码的产出**（样式表字符串逐字拷贝自修复前的
  pet.py），不是手画的近似；「后」走真代码路径；
- 内容全部确定（无随机、无动画、不显示光标闪烁），重跑逐字节一致；
- 放大一律最近邻（平滑会糊，验字体必须硬像素）。

用法（重生成素材就是这一条）:
    .venv/bin/python scripts/input_font_preview.py
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SAMMY_CRT"] = "on"  # 生产观感：扫描线 / 辉光 / 暗角都在
os.environ["SAMMY_BOOT"] = "off"  # 素材永远拍稳态：不播开机
os.environ["SAMMY_ANIM"] = "on"

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

OUT = ROOT / "docs" / "8h-b2" / "input-font.png"
ZOOM = 3
BG = QColor("#0a120d")
EDGE = QColor("#22352a")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
TYPED = "你好 Sammy 在吗？"
MY_LINE = "你：今天好累啊，不想干活。"
SAMMY_LINE = "我在呢，你说。"

_app = QApplication.instance() or QApplication([])

from sammy import layout
from sammy.pet import SammyWindow

layout.load_fonts()


def _fresh() -> SammyWindow:
    """稳态窗口：时间轴不推进、内容钉死、不碰真实状态文件。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.expression = 3
    w.my_line = MY_LINE
    w.sammy_line = SAMMY_LINE
    w.status = "在线"
    w.finish_typing()
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(w, name, lambda: None)  # 素材不是它的一天：关窗别落状态
    w.show()
    w.input.clearFocus()  # 不显示光标闪烁：素材要逐字节可复现
    _app.processEvents()
    return w


def _legacy_qss(w: SammyWindow) -> str:
    """修复前 _layout_input 的样式表 —— 逐字拷贝自修复前的那版 pet.py（无 family）。

    只有 font-size、没有 font-family —— 这就是那一版的真实产出。
    「前」这一格不是摆拍：这段字符串渲染出来什么样，素材里就是什么样。
    """
    return (
        f"QLineEdit {{ background: rgba(18,42,26,190);"
        f" border: 2px solid rgba(61,220,90,110); border-radius: 16px;"
        f" color: #cfead6; padding-left: 18px;"
        f" font-size: {int(w.lay.font_input * w.scale)}px; }}"
    )


def _region(w: SammyWindow) -> QRect:
    """要裁的区域（窗口坐标）：我的行 + 回复 + 输入框那一竖条。"""
    L = w.lay
    u = QRect(L.my_line).united(QRect(L.input)).adjusted(-22, -14, 22, 26)
    s = w.scale
    ox, oy = w._offset
    return QRect(
        round(u.x() * s) + ox,
        round(u.y() * s) + oy,
        round(u.width() * s),
        round(u.height() * s),
    )


def _panel(w: SammyWindow, legacy: bool, typed: bool) -> QImage:
    """抓一帧、裁区域（未放大）。legacy=True 时走修复前的样式表。"""
    w.input.setText(TYPED if typed else "")
    w.input.clearFocus()
    if legacy:
        w.input.setStyleSheet(_legacy_qss(w))
    else:
        w._layout_input()
    w.input.ensurePolished()
    _app.processEvents()
    img = w.grab().toImage().convertToFormat(QImage.Format_RGB32)
    return img.copy(_region(w))


def _diff_pixels(a: QImage, b: QImage) -> int:
    """两张同尺寸图的有差异像素数（原生字节口径）。"""
    ba, bb = bytes(a.constBits()), bytes(b.constBits())
    sa, sb = a.bytesPerLine(), b.bytesPerLine()
    n = 0
    for y in range(min(a.height(), b.height())):
        row_a = ba[y * sa : y * sa + min(a.width(), b.width()) * 4]
        row_b = bb[y * sb : y * sb + min(a.width(), b.width()) * 4]
        n += sum(1 for i in range(0, len(row_a), 4) if row_a[i : i + 4] != row_b[i : i + 4])
    return n


def build() -> Path:
    w = _fresh()
    try:
        before_ph = _panel(w, legacy=True, typed=False)
        after_ph = _panel(w, legacy=False, typed=False)
        before_tp = _panel(w, legacy=True, typed=True)
        after_tp = _panel(w, legacy=False, typed=True)
        d_ph = _diff_pixels(before_ph, after_ph)
        d_tp = _diff_pixels(before_tp, after_tp)
        print(f"  前/后像素差：占位 {d_ph} 像素、已输入 {d_tp} 像素")

        panes = [
            ("前 · 空框（占位文字）", before_ph),
            ("后 · 空框（占位文字）", after_ph),
            ("前 · 已输入「你好 Sammy 在吗？」", before_tp),
            ("后 · 已输入「你好 Sammy 在吗？」", after_tp),
        ]
        cel_w = panes[0][1].width() * ZOOM
        cel_h = panes[0][1].height() * ZOOM
        pad, gap = 26, 44
        head, cap, foot = 74, 30, 40
        width = pad * 2 + cel_w * 2 + gap
        height = head + (cap + cel_h) * 2 + pad + foot
        out = QImage(width, height, QImage.Format_RGB32)
        out.fill(BG)
        p = QPainter(out)
        p.setPen(QPen(EDGE, 1))
        p.drawRect(0, 0, width - 1, height - 1)
        p.setFont(QFont("", 13))
        p.setPen(TITLE)
        p.drawText(pad, 30, "输入框接上像素字体（U1 补完）：前 / 后，放大 3 倍")
        p.setFont(QFont("", 11))
        p.setPen(SUB)
        p.drawText(
            pad,
            52,
            f"前 = 样式表漏了 font-family（所以是系统字体），后 = Sammy Pixel"
            f" —— 占位差 {d_ph} 像素、已输入差 {d_tp} 像素",
        )
        for i, (label, img) in enumerate(panes):
            col, row = i % 2, i // 2
            x = pad + col * (cel_w + gap)
            y = head + row * (cap + cel_h)
            p.setFont(QFont("", 11))
            p.setPen(SUB if col == 0 else TITLE)
            p.drawText(x, y + 16, label)
            big = img.scaled(cel_w, cel_h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            p.drawImage(x, y + cap - 8, big)
            p.setPen(EDGE)
            p.drawRect(x, y + cap - 8, cel_w - 1, cel_h - 1)
        p.setFont(QFont("", 10))
        p.setPen(SUB)
        p.drawText(pad, height - 16, "放大是最近邻（不糊像素）· 重生成：make input-font-media")
        p.end()
        out.save(str(OUT))
    finally:
        w.close()
    return OUT


def main() -> int:
    path = build()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    img = QImage(str(path))
    print(f"已生成 {path.relative_to(ROOT)}  {img.width()}x{img.height()}  sha256:{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
