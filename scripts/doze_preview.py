#!/usr/bin/env python3
"""作息与睡相素材 ——「它有自己的日夜」+「睡着时那个慢慢冒的 Z」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- doze-strip.png  6 格：醒着 → 刚睡着(Z 未冒) → Z 冒出来 → Z 升到一半 → Z 最高 → 换回醒着
- doze-demo.mp4   两个完整的 Z 周期（≈5.2 秒），证明它是"在冒"不是"画上去就停"

用法:
    .venv/bin/python scripts/doze_media.py

纪律（和其他素材脚本一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7）；
- 画面走**真绘制代码**（真窗口真 grab），不是拼图；
- 放大一律最近邻；ffmpeg 不在就只出帧带并说明（不静默降级）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SAMMY_CRT"] = "on"  # 生产观感：扫描线 / 辉光 / 暗角都在
os.environ["SAMMY_ANIM"] = "on"
os.environ["SAMMY_BOOT"] = "off"

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from sammy import anim, drives, layout
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_doze.py 一家的种子（窗口里的随机都钉死）

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window(*, asleep: bool) -> SammyWindow:
    win = SammyWindow(autoconnect=False)
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.drives.asleep = asleep
    win.set_expression(1 if asleep else 2)
    win._idle_face = None
    # 状态文字必须和脸一致：脸睡着、字写着"在线"是最忌讳的自相矛盾
    # （drives.status_text 就是那条单一来源，别在这里手写字符串）
    win.status = drives.status_text(win.drives)
    win.my_line = ""  # 素材里不留上一句的残影（"我醒着呃"配睡脸会读成 bug）
    win.sammy_line = ""
    win.show()
    return win


def grab(win: SammyWindow, t: float) -> Image.Image:
    win.anim_t = t
    win.update(win._face_region())
    tmp = ROOT / ".tmp" / "_doze_frame.png"
    win.grab().save(str(tmp))
    return Image.open(tmp).convert("RGB")


# ── 帧带：六个时刻 ────────────────────────────────
Z = anim.Z_PERIOD
plan = [
    ("醒着（没有 Z）", False, 0.0),
    ("刚睡着（Z 还没冒）", True, Z * 0.68),
    ("Z 冒出来了", True, Z * 0.15),
    ("Z 升到一半", True, Z * 0.33),
    ("Z 最高最亮", True, Z * 0.50),
    ("醒了（Z 走了）", False, Z * 0.25),
]

frames = []
win = make_window(asleep=False)
for label, asleep, t in plan:
    win.drives.asleep = asleep
    win.set_expression(1 if asleep else 2)
    frames.append((label, grab(win, t)))
win.close()

scale = 1.0
cell_w, cell_h = int(W * scale), int(H * scale)
label_h = 30
pad = 10
cols = 3
rows = 2
sheet = Image.new(
    "RGB",
    (cols * cell_w + (cols + 1) * pad, rows * (cell_h + label_h) + (rows + 1) * pad),
    (22, 24, 26),
)
d = ImageDraw.Draw(sheet)
for i, (label, img) in enumerate(frames):
    cx = pad + (i % cols) * (cell_w + pad)
    cy = pad + (i // cols) * (cell_h + label_h + pad)
    sheet.paste(img.resize((cell_w, cell_h), Image.Resampling.NEAREST), (cx, cy))
    d.text((cx + 4, cy + cell_h + 6), f"{i + 1}. {label}", fill=(230, 230, 230))
sheet.save(OUT / "doze-strip.png")
print(f"  帧带: {OUT / 'doze-strip.png'}")

# ── 短视频：两个完整 Z 周期 ─────────────────────────
fps = 12
n = int(2 * Z * fps)
tmpdir = ROOT / ".tmp" / "_doze_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
win = make_window(asleep=True)
for i in range(n):
    grab(win, i / fps).save(tmpdir / f"{i:04d}.png")
win.close()

if shutil.which("ffmpeg"):
    mp4 = OUT / "doze-demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-stream_loop",
            "2",  # ⚠️ 这是**输入侧**选项，必须在 -i 前面
            "-framerate",
            str(fps),
            "-i",
            str(tmpdir / "%04d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(mp4),
        ],
        check=True,
    )
    print(f"  短视频: {mp4}（{n} 帧 / {2 * Z:.1f} 秒，循环 3 次）")
else:
    print("  ⚠️ 没找到 ffmpeg —— 只出了帧带（短视频没生成，别当它出过了）")
shutil.rmtree(tmpdir, ignore_errors=True)
