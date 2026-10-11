#!/usr/bin/env python3
"""8 小时总结报告的素材生成器：截图、脸谱、短视频（全部离屏渲染）。

为什么要写成脚本：报告里的每一张图都应该能随时重生成 ——
用和真机同一段绘制代码（离屏抓帧），不手工拼。素材进 docs/8h/（进仓库，
Rowan 直接在 Gitea 上看）。

用法:
    .venv/bin/python scripts/report_8h_media.py           # 图 + 视频全出
    .venv/bin/python scripts/report_8h_media.py --images  # 只出四张图
    .venv/bin/python scripts/report_8h_media.py --video   # 只出短视频
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import expressions
from sammy import screen as screen_mod
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h"
FPS = 20
BG = QColor("#0a120d")  # 深绿黑，和外壳同一个色系
LINE = "今天天气不错，我想起你昨晚说的那盆绿萝了。"

_app = QApplication.instance() or QApplication([])


def _resolver(w: int, h: int):
    """假装有这么大一块屏（kiosk 铺满逻辑照常走）。"""

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


def render_faceonly(w: int, h: int, out: Path) -> str:
    """face-only 形态一张图（和真机同一段绘制代码）。"""
    screen_mod.resolve_screen = _resolver(w, h)
    win = SammyWindow(kiosk=True, face_only=True, autoconnect=False)
    try:
        win.set_expression(3)  # 微笑
        win.sammy_line = LINE
        win._hold_line()
        win.update()
        img = win.grab()
        if not img.save(str(out)):
            raise SystemExit(f"渲染失败，存不下来：{out}")
        lay = win.lay
        return (
            f"{out.name}: {img.width()}x{img.height()}，缩放 {win.scale:.2f}，"
            f"脸 {lay.face.width()}x{lay.face.height()}，状态行 {lay.font_status} 号字"
        )
    finally:
        win.close()


def render_window_chat(out: Path) -> str:
    """完整版窗口的一张定妆照：它正在回一句话（合成在深底上，像浮在桌面）。"""
    win = SammyWindow(autoconnect=False)
    try:
        win.resize(440, 264)
        win.set_expression(4)  # 开心
        win.anim_t = 0.45  # 快照拍稳态：交叉淡化与开场的弹跳先走完
        win.my_line = "今天好累啊，不想干活。"
        win.sammy_line = "先别硬撑，喝口水，跟我唠两句也行。"
        win.status = "在线 · 1.8s"
        win.update()
        _app.processEvents()
        grab = win.grab()
        canvas = QImage(grab.width(), grab.height(), QImage.Format_ARGB32)
        canvas.fill(BG)
        p = QPainter(canvas)
        p.drawImage(0, 0, grab.toImage())
        p.end()
        if not canvas.save(str(out)):
            raise SystemExit(f"渲染失败，存不下来：{out}")
        return f"{out.name}: {canvas.width()}x{canvas.height()}，表情 {expressions.name_of(4)}"
    finally:
        win.close()


STRIP_FACES = (2, 4, 21, 6, 10, 1)  # 普通 / 开心 / 爱心 / 伤心 / 生气 / 睡眠


def render_face_strip(out: Path) -> str:
    """6 张表情的横排脸谱（一眼看它的气质范围）。"""
    from sammy.faces import face_pixmap

    cols, rows = 3, 2
    cell_w, cell_h, pad = 300, 250, 28
    W, H = pad * 2 + cell_w * cols, pad * 2 + cell_h * rows
    canvas = QImage(W, H, QImage.Format_ARGB32)
    canvas.fill(BG)
    p = QPainter(canvas)
    font = QFont()
    font.setPointSize(17)
    p.setFont(font)
    for i, expr in enumerate(STRIP_FACES):
        col, row = i % cols, i // cols
        x, y = pad + col * cell_w, pad + row * cell_h
        face = face_pixmap(expr, QSize(cell_w - 40, 170))
        p.drawPixmap(x + 20, y + 10, face)
        p.setPen(QColor("#c8e6cf"))
        p.drawText(x, y + 195, cell_w, 40, Qt.AlignHCenter | Qt.AlignTop, expressions.name_of(expr))
        p.setPen(QColor("#5f8a6c"))
        p.drawText(x, y + 195, cell_w, 40, Qt.AlignRight | Qt.AlignTop, f"{expr:02d}")
    p.end()
    if not canvas.save(str(out)):
        raise SystemExit(f"渲染失败，存不下来：{out}")
    return f"{out.name}: {W}x{H}，{len(STRIP_FACES)} 张脸"


def _grab_faceonly_frames(dir_out: Path, seconds: float = 3.0) -> int:
    """小屏 face-only 的动画帧（呼吸 / 眨眼都动起来）。"""
    screen_mod.resolve_screen = _resolver(1024, 768)
    win = SammyWindow(kiosk=True, face_only=True, autoconnect=False)
    n = int(seconds * FPS)
    try:
        win.set_expression(3)
        win.sammy_line = LINE
        win._hold_line()
        for i in range(n):
            win.anim_t = i / FPS
            win.update()
            if not win.grab().save(str(dir_out / f"{i:05d}.png")):
                raise SystemExit("帧保存失败")
        return n
    finally:
        win.close()


def _grab_window_frames(dir_out: Path, start: int, exprs, per_sec: float = 1.5) -> int:
    """完整版窗口轮播几个表情的帧（放大 2 倍后铺在 1024x768 深底上）。"""
    win = SammyWindow(autoconnect=False)
    win.resize(440, 264)
    win.show()
    idx = start
    n_per = int(per_sec * FPS)
    try:
        for expr in exprs:
            win.anim_t = 0.0  # 每段从 0 起拍：交叉淡化从片头开始，而不是停在上一段结尾
            win.set_expression(expr)
            for i in range(n_per):
                win.anim_t = i / FPS
                win.update()
                grab = win.grab()
                big = grab.scaled(
                    grab.width() * 2,
                    grab.height() * 2,
                    Qt.IgnoreAspectRatio,
                    Qt.FastTransformation,
                )
                canvas = QImage(1024, 768, QImage.Format_ARGB32)
                canvas.fill(BG)
                p = QPainter(canvas)
                p.drawImage((1024 - big.width()) // 2, (768 - big.height()) // 2, big.toImage())
                p.end()
                if not canvas.save(str(dir_out / f"{idx:05d}.png")):
                    raise SystemExit("帧保存失败")
                idx += 1
        return idx - start
    finally:
        win.close()


def _encode(frames_dir: Path, out: Path, total: int) -> str:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-framerate",
        str(FPS),
        "-i",
        str(frames_dir / "%05d.png"),
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    kb = out.stat().st_size // 1024
    return f"{out.name}: {total} 帧 / {total / FPS:.1f} 秒 / {kb} KB"


def _stats_png(path: Path) -> str:
    """粗略数一下'亮绿点'（脸描线），跟 T3 的逐像素验证同一个思路。"""
    img = QImage(str(path))
    lit = 0
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            c = img.pixelColor(x, y)
            if c.green() > 120 and c.green() > c.red() + 30:
                lit += 1
    return f"{path.name}: {img.width()}x{img.height()}，绿点约 {lit}（步长 3 采样）"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", action="store_true", help="只出四张图")
    ap.add_argument("--video", action="store_true", help="只出短视频")
    args = ap.parse_args(argv)
    if args.images or args.video:
        do_images, do_video = args.images, args.video
    else:
        do_images = do_video = True

    OUT.mkdir(parents=True, exist_ok=True)
    if do_images:
        print("── 图 ──")
        print(" " + render_faceonly(1024, 768, OUT / "faceonly-1024x768.png"))
        print(" " + render_faceonly(800, 480, OUT / "faceonly-800x480.png"))
        print(" " + render_window_chat(OUT / "window-chat.png"))
        print(" " + render_face_strip(OUT / "face-strip.png"))
    if do_video:
        print("── 视频 ──")
        tmp = Path(tempfile.mkdtemp(prefix="sammy8h-frames-"))
        try:
            n1 = _grab_faceonly_frames(tmp)
            n2 = _grab_window_frames(tmp, n1, (4, 6, 1, 21))
            print(f"  帧：小屏 {n1} + 表情 {n2}")
            print(" " + _encode(tmp, OUT / "demo.mp4", n1 + n2))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("── 素材体检（数字）──")
    for name in (
        "faceonly-1024x768.png",
        "faceonly-800x480.png",
        "window-chat.png",
        "face-strip.png",
    ):
        print(" " + _stats_png(OUT / name))
    mp4 = OUT / "demo.mp4"
    if mp4.exists():
        print(f" {mp4.name}: {mp4.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
