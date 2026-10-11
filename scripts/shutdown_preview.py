#!/usr/bin/env python3
"""关机序列素材 —— 收束成一条线、一个点、熄灭，离屏真窗口逐帧抓。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- shutdown-strip.png  8 格关键帧（整窗 2 倍放大 + 时间与阶段标签）
- shutdown-demo.mp4   整段 0.92 秒播两遍（按 25fps 抓帧，880x528 画布 + 底部字幕条）

用法:
    .venv/bin/python scripts/shutdown_preview.py

纪律：一条命令全部重生成。窗口随机全部钉种子（seed=7），抓帧按时间
升序进行 —— 纯函数时间轴，同一份代码重跑出的帧是同一份。
放大一律最近邻（平滑缩放会糊掉像素网格与扫描线，验收素材恰恰要看这些）。
素材脚本不碰真状态：关窗时的保存全换成空操作，退出口换成空函数。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SAMMY_CRT"] = "on"  # 生产观感：扫描线 / 辉光 / 暗角都在
os.environ["SAMMY_BOOT"] = "on"  # 和开机共用同一个电源开关
os.environ["SAMMY_ANIM"] = "on"

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import boot

OUT = ROOT / "docs" / "8h-b2"
TMP = ROOT / ".tmp" / "shutdown"
FPS = 25
ZOOM = 2  # 整窗放大倍数
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")

STRIP = (
    (0.06, "t=0.06s · 起手：画面开始往中缝掉"),
    (0.14, "t=0.14s · 压扁过半"),
    (0.26, "t=0.26s · 快贴到线上了"),
    (0.38, "t=0.38s · 再压一步就是一条线"),
    (0.46, "t=0.46s · 亮线朝中心收"),
    (0.56, "t=0.56s · 快收成一点了"),
    (0.66, "t=0.66s · 只剩一个光点"),
    (0.82, "t=0.82s · 光点在暗下去"),
)

CAPS = {
    "collapse": "压扁：断电的栅格往中缝收（0.4 秒）",
    "line": "收线：亮线朝中心收（0.22 秒）",
    "dot": "熄灭：剩一点光，然后没了（0.3 秒）",
    "done": "关机完成 —— 真实运行时窗口到这里就关掉了",
}

_app = QApplication.instance() or QApplication([])

from sammy import layout

layout.load_fonts()


def _fresh():
    from sammy import anim
    from sammy.pet import SammyWindow

    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.anim = anim.Animator(seed=7)
    w.anim_t = 1.0
    w.set_expression(3)
    w.status = "在线 · 1.8s"
    w.sammy_line = "嗯…我醒着呢。"
    w.finish_typing()  # 素材里的句子永远是一整句（U3 的纪律）
    # 素材脚本不碰真状态：关窗时的保存全换成空操作；退出口换成空函数
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(w, name, lambda: None)
    w._quit_hook = lambda: None
    return w


def _grab2x(w) -> QImage:
    img = w.grab().toImage()
    return img.scaled(
        img.width() * ZOOM, img.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


def _tile(img: QImage, title: str, sub: str) -> QImage:
    panel = QImage(img.width(), img.height() + 40, QImage.Format_ARGB32)
    panel.fill(BG)
    p = QPainter(panel)
    p.drawImage(0, 0, img)
    p.setFont(QFont("", 13))
    p.setPen(TITLE)
    p.drawText(10, img.height() + 18, title)
    p.setFont(QFont("", 11))
    p.setPen(SUB)
    p.drawText(10, img.height() + 34, sub)
    p.end()
    return panel


def _grid(title: str, subtitle: str, panels: list[QImage], cols: int, out: Path) -> str:
    pad, capt = 14, 48
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
    p.drawText(pad, 26, title)
    p.setFont(QFont("", 12))
    p.setPen(SUB)
    p.drawText(pad, 44, subtitle)
    for i, panel in enumerate(panels):
        x = pad + (i % cols) * (pw + pad)
        y = capt + pad + (i // cols) * (ph + pad)
        p.drawImage(x, y, panel)
    p.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(out)):
        raise SystemExit("存不下来：" + str(out))
    return out.name + ": " + str(W) + "x" + str(H) + "，" + str(len(panels)) + " 格"


def _sub_for(t: float) -> str:
    fr = boot.shutdown_frame_at(t)
    if fr.phase == "collapse":
        return "压扁 " + str(int(fr.sy * 100)) + "% · 亮线 " + str(int(fr.core * 100)) + "%"
    if fr.phase == "line":
        return "收线 " + str(int(fr.sx * 100)) + "% · 满亮"
    if fr.phase == "dot":
        return "熄灭 · 光点剩 " + str(int(fr.alpha * 100)) + "%"
    return "熄灭"


def build_strip() -> str:
    w = _fresh()
    try:
        if not w.begin_shutdown():
            raise SystemExit("关机开关没打开（SAMMY_BOOT）——素材需要它开着")
        t0 = w._shutdown_t0
        panels = []
        for t, label in STRIP:
            w.anim_t = t0 + t
            panels.append(_tile(_grab2x(w), label, _sub_for(t)))
        return _grid(
            "关机序列：收束成一条线、一个点、熄灭（整段 0.92 秒）",
            "点一下可跳过 · 和开机共用 SAMMY_BOOT 开关 · 只在关闭钮 / 菜单退出时播",
            panels,
            4,
            OUT / "shutdown-strip.png",
        )
    finally:
        w.close()


def _put_frame(w, frames: Path, idx: int, caption: str) -> int:
    img = _grab2x(w)
    cv = QImage(880, 528 + 36, QImage.Format_ARGB32)
    cv.fill(BG)
    p = QPainter(cv)
    p.drawImage((880 - img.width()) // 2, (528 - img.height()) // 2, img)
    p.setFont(QFont("", 13))
    p.setPen(SUB)
    p.drawText(12, 528 + 24, caption)
    p.end()
    if not cv.save(str(frames / (str(idx).zfill(5) + ".png"))):
        raise SystemExit("帧保存失败")
    return idx + 1


def build_video() -> str:
    frames = Path(tempfile.mkdtemp(prefix="shutv-", dir=str(TMP)))
    total = boot.shutdown_total_seconds()
    per_pass = int(total * FPS) + 1
    w = _fresh()
    idx = 0
    try:
        if not w.begin_shutdown():
            raise SystemExit("关机开关没打开")
        t0 = w._shutdown_t0
        for pass_i in range(2):  # 0.92 秒一遍太快：播两遍，第二遍写明是重放
            for i in range(per_pass):
                t = i / FPS
                w.anim_t = t0 + t
                cap = CAPS[boot.shutdown_frame_at(t).phase]
                if pass_i == 1:
                    cap = "第 2 遍（重放）· " + cap
                idx = _put_frame(w, frames, idx, cap)
        for _ in range(15):  # 尾巴：全黑 + 一行说明（播完这里窗口就关了）
            w.anim_t = t0 + 1.2
            idx = _put_frame(w, frames, idx, CAPS["done"])
    finally:
        w.close()

    out = OUT / "shutdown-demo.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            str(frames / "%05d.png"),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
    )
    kb = out.stat().st_size // 1024
    return (
        out.name
        + ": "
        + str(idx)
        + " 帧 / "
        + str(round(idx / FPS, 1))
        + " 秒 / "
        + str(kb)
        + " KB"
    )


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    print("  关机素材：")
    for line in (build_strip(), build_video()):
        print("  ok " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
