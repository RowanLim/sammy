#!/usr/bin/env python3
"""U5 前后对比：用「第二轮开始前」的代码渲染同一幕（离屏真窗口）。

为什么单独一个脚本：对比图要公平 —— 「之前」必须用**当时那份代码**渲染，
而不是拿现在的代码摆拍一个假的之前。导入哪份 sammy 由 SAMMY_SRC 决定，
所以同一份脚本对起点 worktree（f4ff3f7）和现在的代码都跑得动。

用法（一般由 scripts/u5_preview.py 调用）:
    SAMMY_SRC=.tmp/u5-base/src QT_QPA_PLATFORM=offscreen \
        .venv/bin/python scripts/u5_baseline_shot.py --out .tmp/u5/before-window.png
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SRC = os.environ.get("SAMMY_SRC") or str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, _SRC)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from sammy import layout
from sammy.pet import SammyWindow

# 这一幕要和 u5_preview.py 的「现在」逐字一致（两边各写一遍，测试对账）。
REPLY = "先别硬撑，喝口水。绿萝我浇过水了，你歇会儿。"
MY = "今天好累啊，不想干活。"
STATUS = "在线 · 1.8s"


def _freeze(win) -> None:
    """冻住随时间随机的微动 —— 对比图只应该显示「版本差异」。"""
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    a = getattr(win, "anim", None)
    if a is None:
        return
    if hasattr(a, "_blinks"):
        a._blinks = []
    if hasattr(a, "_next_at"):
        a._next_at = 1e9
    gaze = getattr(a, "_gaze", None)  # U2 之前的代码没有凝视
    if gaze:
        g = gaze[0].__class__
        a._gaze = [g(t=0.0, x=0, y=0, fx=0, fy=0), g(t=1e9, x=0, y=0, fx=0, fy=0)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    _app = QApplication.instance() or QApplication([])
    if hasattr(layout, "load_fonts"):  # U1 起才有像素字体
        layout.load_fonts()

    win = SammyWindow(autoconnect=False)
    try:
        win.resize(440, 264)
        win.anim_t = 1.0
        win.set_expression(3)
        win.my_line = MY
        win.sammy_line = REPLY
        if hasattr(win, "finish_typing"):  # U3 起才有打字机
            win.finish_typing()
        win.status = STATUS
        _freeze(win)
        win.update()
        _app.processEvents()
        img = win.grab()
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if not img.save(str(out)):
            raise SystemExit("存不下来: " + str(out))
        print("  ok", out.name, img.width(), "x", img.height())
        return 0
    finally:
        win.close()


if __name__ == "__main__":
    raise SystemExit(main())
