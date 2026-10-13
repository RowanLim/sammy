#!/usr/bin/env python3
"""醒来的哈欠素材 ——「睡醒了先伸个懒腰、打个哈欠」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- yawn-strip.png  6 格：睡着(Z) → 醒了(还没抻) → 抻起来中 → 抻最满 → 眯到底 → 收完回常态
- yawn-demo.mp4   一个完整哈欠（12fps，循环 3 遍），证明它是「在动」不是一帧贴图

用法:
    .venv/bin/python scripts/yawn_preview.py

纪律（和其他素材脚本一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7）；
- 画面走**真绘制代码**（真窗口真 grab），不是拼图；
- 放大一律最近邻；ffmpeg 不在就只出帧带并说明（不静默降级）；
- 顺手把「撑多高 / 眯多扁 / 收完归零」三个数打出来（DEVLOG 引它当证据）。
"""

from __future__ import annotations

import hashlib
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
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from sammy import anim, drives, faces, layout
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_yawn.py 一家的种子（窗口里的随机都钉死）
T0 = 1.0  # 哈欠在时间轴上的起点

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window(*, asleep: bool = False, with_yawn: bool = True) -> SammyWindow:
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED)
    win.look_on = False  # 光标不参与（盯的是哈欠这一件事）
    win.drives.asleep = asleep
    win.set_expression(1 if asleep else 2)
    win._idle_face = None
    # 状态文字必须和脸一致（脸睡着、字写「在线」是最忌讳的自相矛盾 —— doze 那次的坑）
    win.status = drives.status_text(win.drives)
    win.my_line = ""  # 素材里不留上一句的残影
    win.sammy_line = ""
    if with_yawn:
        win.anim.yawn(T0)
    win.show()
    return win


def grab(win: SammyWindow, t: float) -> Image.Image:
    win.anim_t = t
    win.update(win._face_region())
    tmp = ROOT / ".tmp" / "_yawn_frame.png"
    win.grab().save(str(tmp))
    return Image.open(tmp).convert("RGB")


def face_box(win: SammyWindow, t: float) -> tuple[int, int, int, int]:
    """脸内容（不透明亮像素）的外接框 —— 量「撑多高、眯多扁」用。"""
    win.anim_t = t
    img = win.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    box = win.lay.face
    x0 = y0 = 10**9
    x1 = y1 = -1
    for y in range(max(0, box.top() - 70), min(img.height(), box.bottom() + 6)):
        row = y * stride
        for x in range(max(0, box.left() - 70), min(img.width(), box.right() + 70)):
            i = row + x * 4
            b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
            if a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70:
                x0 = min(x0, x)
                x1 = max(x1, x)
                y0 = min(y0, y)
                y1 = max(y1, y)
    assert x1 >= 0, "没扫到脸像素？"
    return x0, y0, x1, y1


# ── 帧带：六个时刻 ────────────────────────────────
awake = make_window(with_yawn=True)
control = make_window(with_yawn=False)  # 对照：同种子、没排哈欠
plan = [
    ("醒了（哈欠还没起）", T0),
    ("抻起来中", round(T0 + anim.YAWN_RISE_S * 0.5, 6)),
    ("抻最满（还没眯）", round(T0 + anim.YAWN_RISE_S, 6)),
    ("眯到底（呵——）", round(T0 + anim.YAWN_SQUINT_DELAY_S + anim.YAWN_SQUINT_RISE_S, 6)),
    ("收完，回到常态", round(T0 + anim.yawn_total() + 0.4, 6)),
]

frames = []
# 第一格：睡着（Z 最亮的时刻）
asleep = make_window(asleep=True, with_yawn=False)
frames.append(("睡着（Z 在冒）", grab(asleep, anim.Z_PERIOD * 0.31)))
asleep.close()

for label, t in plan:
    img_a = grab(awake, t)
    control.anim_t = t  # 对照组跟着走同一根时间轴（状态同步）
    control.grab()
    frames.append((label, img_a))

# 量化证据（打给 DEVLOG / 人看）
tall = round(T0 + anim.YAWN_RISE_S, 6)
shut = round(T0 + anim.YAWN_SQUINT_DELAY_S + anim.YAWN_SQUINT_RISE_S, 6)
xa0, ya0, xa1, ya1 = face_box(awake, tall)
xb0, yb0, xb1, yb1 = face_box(control, tall)
print(
    f"  抻最满：脸高 {ya1 - ya0}px vs 常态 {yb1 - yb0}px（+{ya1 - ya0 - (yb1 - yb0)}px）；"
    f"顶沿上抬 {yb0 - ya0}px；宽度差 {(xa1 - xa0) - (xb1 - xb0)}px"
)
xs0, ys0, xs1, ys1 = face_box(awake, shut)
print(
    f"  眯到底：脸高 {ys1 - ys0}px（常态 {yb1 - yb0}px 的 {100 * (ys1 - ys0) / (yb1 - yb0):.0f}%）"
)
after = round(T0 + anim.yawn_total() + 0.4, 6)
awake.anim_t = after
control.anim_t = after
blob_a = awake.grab().toImage().convertToFormat(QImage.Format_ARGB32)
blob_b = control.grab().toImage().convertToFormat(QImage.Format_ARGB32)
diff = 0
ba, bb = bytes(blob_a.constBits()), bytes(blob_b.constBits())
for i in range(0, len(ba), 4):
    if ba[i : i + 4] != bb[i : i + 4]:
        diff += 1
print(f"  收完对比：与「没打过哈欠」的孪生不同像素 {diff} 个（期望 0）")
awake.close()
control.close()

cell_w, cell_h = int(W * 1.0), int(H * 1.0)
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
sheet.save(OUT / "yawn-strip.png")
print(f"  帧带: {OUT / 'yawn-strip.png'}")

# ── 短视频：一个完整哈欠，循环 3 遍 ─────────────────
fps = 12
start, stop = 0.6, T0 + anim.yawn_total() + 0.6
n = int((stop - start) * fps)
tmpdir = ROOT / ".tmp" / "_yawn_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
win = make_window(with_yawn=True)
for i in range(n):
    grab(win, round(start + i / fps, 6)).save(tmpdir / f"{i:04d}.png")
win.close()

if shutil.which("ffmpeg"):
    mp4 = OUT / "yawn-demo.mp4"
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
    print(f"  短视频: {mp4}（{n} 帧 / {stop - start:.1f} 秒，循环 3 次）")
else:
    print("  ⚠️ 没找到 ffmpeg —— 只出了帧带（短视频没生成，别当它出过了）")
shutil.rmtree(tmpdir, ignore_errors=True)

for name in ("yawn-strip.png", "yawn-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
