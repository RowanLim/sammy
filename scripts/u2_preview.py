#!/usr/bin/env python3
"""U2 素材：凝视漂移条 + 交叉淡化条（离屏渲染，走和真机同一段绘制代码）。

为什么要脚本：验收"看起来对不对"的东西（凝视的幅度、淡化的形状），
测试只能量数字；图必须随时能重生成，而且不能靠画图软件手拼 ——
这里每一帧都是离屏抓的真窗口。

用法:
    .venv/bin/python scripts/u2_preview.py [--out DIR]   # 默认 .tmp/u2-preview/
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from PySide6.QtWidgets import QApplication


from sammy import anim

from sammy.pet import SammyWindow


BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
REF = QColor(232, 192, 90, 140)  # 正中参照线（琥珀色，和脸的绿区分开）
SEED = 7  # 和 tests/test_gaze.py 同一个种子：图与判据对得上
LABEL_H = 40


def _fresh() -> SammyWindow:
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    return w


def _panel(w: SammyWindow, title: str, sub: str, ref_x: int | None = None) -> QImage:
    grab = w.grab()
    panel = QImage(grab.width(), grab.height() + LABEL_H, QImage.Format_ARGB32)
    panel.fill(BG)
    p = QPainter(panel)
    p.drawImage(0, 0, grab.toImage())
    if ref_x is not None:
        p.setPen(QPen(REF, 2))
        p.drawLine(ref_x, 0, ref_x, grab.height())
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


def gaze_strip(out_dir: Path) -> str:
    """6 个"看定了"的时刻横排 —— 一眼看出脸真的在往两边看。"""
    w = _fresh()
    w.anim = anim.Animator(seed=SEED)
    w.set_expression(9)
    a = w.anim
    seen: dict[int, tuple[float, anim.Frame]] = {}
    t = 0.0
    while t < 400.0:
        f = a.frame_at(t)
        f2 = a.frame_at(t + 0.4)
        if (f.gx, f.gy) == (f2.gx, f2.gy) and f.gx not in seen:  # 看定段（0.4 秒还不动）
            seen[f.gx] = (t + 0.2, f)
        t += 0.1
    xs = sorted(seen)
    if len(xs) < 6:
        raise SystemExit(f"种子 {SEED} 下只有 {len(xs)} 个方向，凑不出条")
    picks = [seen[xs[round(i * (len(xs) - 1) / 5)]] for i in range(6)]
    ref_x = int(w.lay.face.center().x() * w.scale) + w._offset[0]
    panels = []
    for tt, f in picks:
        w.anim_t = tt
        panels.append(
            _panel(
                w,
                f"t={tt:6.1f}s · 看向 ({f.gx:+d}, {f.gy:+d})",
                f"好奇拉伸 {f.stretch:.3f}×",
                ref_x,
            )
        )
    w.close()
    title = "U2 凝视漂移：每 2.6~7.4 秒缓动到新的随机方向（琥珀竖线 = 正中参照）"
    return _grid(title, panels, 3, out_dir / "u2-gaze-strip.png")


def fade_strip(out_dir: Path) -> str:
    """换表情的 5 个中间帧 —— 证明是"缓过去"而不是"切过去"。"""
    w = _fresh()
    w.anim = anim.Animator(seed=SEED)
    w.set_expression(9)  # 吐舌（没有动图，画面只有淡化在动）
    w.anim_t = 0.0
    w.set_expression(13)  # 得意
    panels = []
    for tt in (0.0, 0.095, 0.19, 0.285, 0.395):
        w.anim_t = tt
        _, alpha = w.anim.expr_fade(tt)
        panels.append(_panel(w, f"t={tt:.2f}s", f"新脸不透明度 {alpha:.0%}"))
    w.close()
    title = "U2 交叉淡化：换表情（吐舌 → 得意）0.38 秒缓过去，不是啪地切断"
    return _grid(title, panels, 5, out_dir / "u2-fade-strip.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".tmp" / "u2-preview"))
    args = ap.parse_args()
    _app = QApplication.instance() or QApplication([])  # 保住引用（窗口要用）
    out = Path(args.out)
    print("  ✅", gaze_strip(out))
    print("  ✅", fade_strip(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
