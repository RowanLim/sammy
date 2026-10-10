#!/usr/bin/env python3
"""face-only 小屏形态的预览图 —— 给"没有那块屏"的人看效果。

为什么要有它：face-only 是给**别的机器上的小屏**准备的（复古壳那台是 4:3），
开发机上没有那块屏，"铺上去好不好看"没法靠盯代码验证。
这个脚本用和真机**同一段绘制代码**把 face-only 版面渲染成 PNG ——
预期效果、回归证据、给 Rowan 看的截图，都是它。

输出默认去 data/previews/（运行产物，不进仓库）。

用法:
    .venv/bin/python scripts/preview_faceonly.py                # 默认几个尺寸
    .venv/bin/python scripts/preview_faceonly.py 1024x768       # 只渲染指定尺寸
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from sammy import screen as screen_mod
from sammy.paths import data_dir
from sammy.pet import SammyWindow

# 代表性屏幕：复古壳 4:3 / 设计基准 5:3 / 16:9 / 竖屏
DEFAULTS = [(1024, 768), (800, 480), (1280, 720), (480, 800)]

LINE = "今天天气不错，我想起你昨晚说的那盆绿萝了。"


def _resolver(w: int, h: int):
    """假装有这么一块屏（和 0×0 兜底测试同款做法）—— kiosk 铺满逻辑照常走。"""

    def resolve(want=None):
        return {
            "index": 9,
            "name": f"PREVIEW-{w}x{h}",
            "x": 0,
            "y": 0,
            "width": w,
            "height": h,
            "primary": False,
        }

    return resolve


def render(w: int, h: int, out: pathlib.Path) -> str:
    """按 w×h 的屏渲染一张 face-only 预览，返回一行摘要（报告里直接引用）。"""
    screen_mod.resolve_screen = _resolver(w, h)
    win = SammyWindow(kiosk=True, face_only=True, autoconnect=False)
    try:
        win.set_expression(3)  # 微笑
        win.sammy_line = LINE
        win._hold_line()  # 让那一行显示"刚说的话"的样子
        win.update()
        img = win.grab()
        if not img.save(str(out)):
            raise SystemExit(f"渲染失败，存不下来：{out}")
        L = win.lay
        return (
            f"{w}×{h} 缩放 {win.scale:.2f} | 脸 {L.face.width()}×{L.face.height()}"
            f"（完整版 440×216）| 状态行 {L.font_status} 号字 | 存 {out.name}"
        )
    finally:
        win.close()


def main(argv: list[str]) -> int:
    sizes = []
    for arg in argv:
        ws, _, hs = arg.partition("x")
        sizes.append((int(ws), int(hs)))
    if not sizes:
        sizes = DEFAULTS

    _app = QApplication([])  # 必须先有它才能建窗口（离屏，不弹窗）
    out_dir = data_dir() / "previews"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"face-only 预览 → {out_dir}")
    for w, h in sizes:
        print("  " + render(w, h, out_dir / f"faceonly-{w}x{h}.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
