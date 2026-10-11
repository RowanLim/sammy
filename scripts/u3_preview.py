#!/usr/bin/env python3
"""U3 素材：打字机条 + 思考点条（离屏真窗口抓帧，走和真机同一段绘制代码）。

为什么要脚本：验收"看起来对不对"的东西（逐字出现的手感、点动没动），
测试只能量数字；图必须随时能重生成，而且不能靠画图软件手拼 ——
这里每一帧都是离屏抓的真窗口，打字进度是**真的**按 anim_t 走的。

用法:
    .venv/bin/python scripts/u3_preview.py [--out DIR]   # 默认 .tmp/u3-preview/
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import layout
from sammy import typewriter as tw
from sammy.pet import SammyWindow

BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
LABEL_H = 40

TEXT = "先别硬撑，喝口水，跟我唠两句也行。"
TY_PICKS = (0.0, 0.25, 0.55, 0.78, 2.0)  # 打字过程采样（打完全长约 0.82 秒）
DOT_PICKS = (0.0, 0.4, 0.8)  # 思考点的三帧


def _fresh(face_only: bool = False) -> SammyWindow:
    w = SammyWindow(face_only=face_only, autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    return w


def _panel(w: SammyWindow, title: str, sub: str) -> QImage:
    grab = w.grab()
    panel = QImage(grab.width(), grab.height() + LABEL_H, QImage.Format_ARGB32)
    panel.fill(BG)
    p = QPainter(panel)
    p.drawImage(0, 0, grab.toImage())
    p.setFont(QFont("", 13))
    p.setPen(TITLE)
    p.drawText(8, grab.height() + 16, title)
    p.setFont(QFont("", 11))
    p.setPen(SUB)
    p.drawText(8, grab.height() + 32, sub)
    p.end()
    return panel


def _grid(title: str, panels: list[QImage], cols: int, out: Path) -> str:
    pad, capt = 14, 34
    pw = max(p.width() for p in panels)
    ph = max(p.height() for p in panels)
    rows = (len(panels) + cols - 1) // cols
    W = pad + (pw + pad) * cols
    H = capt + pad + (ph + pad) * rows
    canvas = QImage(W, H, QImage.Format_ARGB32)
    canvas.fill(BG)
    p = QPainter(canvas)
    p.setFont(QFont("", 16))
    p.setPen(TITLE)
    p.drawText(pad, 24, title)
    for i, panel in enumerate(panels):
        x = pad + (i % cols) * (pw + pad)
        y = capt + (i // cols) * (ph + pad)
        p.drawImage(x, y, panel)
    p.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(out)):
        raise SystemExit(f"存不下来：{out}")
    return f"{out.name}: {W}x{H}，{len(panels)} 格"


def typing_strip(out_dir: Path) -> str:
    """打字过程 5 格 —— 一眼看出"话是一个字一个字出来的"。"""
    w = _fresh()
    w.set_expression(3)
    w.my_line = "今天好累啊，不想干活。"
    w.status = "在线 · 1.8s"
    w.sammy_line = TEXT
    w.anim_t = 0.0
    w.grab()  # 第一眼：把打字机起步定在 t=0（惰性起步，和真机同一套）
    panels = []
    for tt in TY_PICKS:
        w.anim_t = tt
        shown = len(tw.reveal(TEXT, tt))
        panels.append(_panel(w, f"t={tt:.2f}s", f"已出 {shown}/{len(TEXT)} 字"))
    w.close()
    title = "U3 打字机：回复逐字出现（每字 40ms，标点后多停 90ms；末格 = 打完）"
    return _grid(title, panels, 5, out_dir / "u3-typing-strip.png")


def dots_strip(out_dir: Path) -> str:
    """思考点 6 格：上排完整版、下排 face-only —— 点和状态行的省略号都在动。"""
    panels = []
    w = _fresh()
    w.thinking = True
    w.status = "思考中…"
    w.sammy_line = "……"
    w.my_line = ""
    for tt in DOT_PICKS:
        w.anim_t = tt
        panels.append(_panel(w, f"完整版 t={tt:.1f}s", f"思考点 {tw.dots(tt)}"))
    w.close()
    wf = _fresh(face_only=True)
    wf.thinking = True
    wf.status = "思考中…"
    for tt in DOT_PICKS:
        wf.anim_t = tt
        small = tw.dots(tt, tw.DOT_FRAMES_TEXT)
        panels.append(_panel(wf, f"小屏 t={tt:.1f}s", f"那一行：思考中{small}"))
    wf.close()
    title = "U3 思考指示：等待时用会动的点（· 长到 ···，每 0.4 秒一帧，替代干等的省略号）"
    return _grid(title, panels, 3, out_dir / "u3-dots-strip.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".tmp" / "u3-preview"))
    args = ap.parse_args()
    _app = QApplication.instance() or QApplication([])  # 保住引用（窗口要用）
    layout.load_fonts()  # 和真机一致：像素字体先注册（U1），否则量出来的是回落字体的字距
    out = Path(args.out)
    print("  ✅", typing_strip(out))
    print("  ✅", dots_strip(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
