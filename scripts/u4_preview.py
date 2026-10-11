#!/usr/bin/env python3
"""U4 素材：CRT 质感（扫描线 / 辉光 / 暗角）—— 关 vs 开，一律离屏真窗口抓帧。

为什么要脚本：三样效果都靠眼睛验收，但必须**可重生成**（改一个常数就能再出图）。
放大裁切用最近邻（FastTransformation）—— 平滑缩放会把扫描线的隔行像素糊掉，
验收素材恰恰要看清"每隔一行"这件事。

用法:
    .venv/bin/python scripts/u4_preview.py [--out DIR]   # 默认 .tmp/u4-preview/
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import layout

BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
LABEL_H = 40

REPLY = "先别硬撑，喝口水，跟我唠两句也行。"
CROPS = {
    "回复区 ×2": (QRect(25, 128, 275, 92), 2),  # 状态行 + 回复文字
    "脸缘 ×2": (QRect(235, 35, 100, 75), 2),  # 脸右缘：辉光外渗看得最清
    "角落 ×2": (QRect(0, 0, 62, 62), 2),  # 左上角：暗角 + 圆角裁剪
}


def _fresh(face_only: bool = False, crt: str = "on"):
    from sammy.pet import SammyWindow

    os.environ["SAMMY_CRT"] = crt
    w = SammyWindow(face_only=face_only, autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.set_expression(3)
    w.anim_t = 1.0  # 稳态：交叉淡化/弹跳走完（U2 的教训）
    w.my_line = "今天好累啊，不想干活。"
    w.status = "在线 · 1.8s"
    w.sammy_line = REPLY
    w.finish_typing()  # 拍到的必须是一整句（U3 的教训）
    return w


def _panels(face_only: bool = False):
    out = {}
    for crt in ("off", "on"):
        w = _fresh(face_only=face_only, crt=crt)
        out[crt] = w
    return out


def _panel(img: QImage, title: str, sub: str) -> QImage:
    panel = QImage(img.width(), img.height() + LABEL_H, QImage.Format_ARGB32)
    panel.fill(BG)
    p = QPainter(panel)
    p.drawImage(0, 0, img)
    p.setFont(QFont("", 13))
    p.setPen(TITLE)
    p.drawText(8, img.height() + 16, title)
    p.setFont(QFont("", 11))
    p.setPen(SUB)
    p.drawText(8, img.height() + 32, sub)
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


def off_on_strip(out_dir: Path) -> str:
    """整窗：关 vs 开 —— 第一眼看"这台机器变没变老"。"""
    wins = _panels()
    panels = []
    for crt, label in (("off", "CRT 关（SAMMY_CRT=off）"), ("on", "CRT 开（默认）")):
        img = wins[crt].grab().toImage()
        panels.append(_panel(img, label, "整窗 440×264（桌面浮窗）"))
    for w in wins.values():
        w.close()
    title = "U4 CRT 质感：扫描线（隔行暗线 0.15）+ 辉光（挑亮后加色）+ 暗角（角落 0.30）"
    return _grid(title, panels, 2, out_dir / "u4-off-on.png")


def zoom_strip(out_dir: Path) -> str:
    """三个局部 ×2 放大：回复区 / 脸缘 / 角落 —— 每一处验一样东西。"""
    wins = _panels()
    panels = []
    for name, (rect, zoom) in CROPS.items():
        for crt, tag in (("off", "关"), ("on", "开")):
            img = wins[crt].grab().toImage()
            crop = img.copy(rect)
            big = crop.scaled(
                crop.width() * zoom,
                crop.height() * zoom,
                Qt.IgnoreAspectRatio,
                Qt.FastTransformation,
            )
            sub = {
                "回复区 ×2": "文字上隔行条纹 + 字迹荧光",
                "脸缘 ×2": "亮边外 2~9 像素被渗亮",
                "角落 ×2": "越靠角越暗且圆角外透明",
            }[name]
            panels.append(_panel(big, f"{name} · CRT {tag}", sub))
    for w in wins.values():
        w.close()
    title = "U4 局部对账（最近邻放大，别糊掉隔行像素）"
    return _grid(title, panels, 2, out_dir / "u4-zoom.png")


def faceonly_strip(out_dir: Path) -> str:
    """face-only 小屏形态：同一台机器，条纹与暗角都在。"""
    wins = _panels(face_only=True)
    panels = []
    for crt, label in (("off", "face-only · CRT 关"), ("on", "face-only · CRT 开")):
        img = wins[crt].grab().toImage()
        panels.append(_panel(img, label, "复古壳那一台（只有一张脸 + 一行字）"))
    for w in wins.values():
        w.close()
    title = "U4：face-only 也要有质感（同一段绘制代码，自动沾上）"
    return _grid(title, panels, 2, out_dir / "u4-faceonly.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".tmp" / "u4-preview"))
    args = ap.parse_args()
    _app = QApplication.instance() or QApplication([])  # 保住引用（窗口要用）
    layout.load_fonts()  # 和真机一致：像素字体先注册（U1）
    out = Path(args.out)
    print("  ✅", off_on_strip(out))
    print("  ✅", zoom_strip(out))
    print("  ✅", faceonly_strip(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
