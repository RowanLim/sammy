#!/usr/bin/env python3
"""上电环顾素材 ——「自检播完，先看一圈」：交班、左右各看一眼、回中。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- survey-strip.png  六格（面板区 1.5 倍最近邻放大）：自检滚完 -> 交班站定 ->
                    看左（探头）-> 看右 -> 回正中 + 判据数字卡
- survey-demo.mp4   从自检尾段到环顾收尾的连续段（12fps，循环 3 遍）

用法:
    .venv/bin/python scripts/survey_preview.py

纪律（和 dozeoff_preview 一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_survey.py 同一个）；
- 触发走**真链路**：anim_t 越过自检终点的那一刻由 `_anim_tick` 交班（和真机
  同一条路），不是直接调 _finish_boot 摆拍；
- 画面走**真绘制代码**（真窗口真 grab）；放大一律最近邻；
- 顺手把「左右 / 回中的亮像素质心 x、脸高（探头拉高）、关键帧在不在重绘区」
  打出来（DEVLOG 引它当证据）。
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
os.environ["SAMMY_BOOT"] = "on"  # 这条素材就拍开机

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import anim, boot, faces
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_survey.py 一家的种子（窗口里的随机都钉死）
PANEL = QRect(2, 2, 796, 476)  # 面板区（自检文字与脸都在里面）
VCROP = QRect(148, 0, 504, 300)  # 视频取景：脸 + 状态行
SCAN = QRect(120, 0, 580, 238)  # 找脸部亮像素的范围（避开状态行与关闭钮）
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")

app = QApplication(sys.argv[:1])
from sammy import layout

layout.load_fonts()


def make_window() -> SammyWindow:
    """只留「环顾」一个变量的窗口：种子 / 时间轴 / 光标全钉住。"""
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED)
    win.look_on = False  # 光标不参与（盯的是「环顾」这一件事）
    win.my_line = ""
    win.sammy_line = ""
    # 素材脚本不碰真状态：关窗时的保存全换成空操作
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(win, name, lambda: None)
    win.show()
    return win


def look(win: SammyWindow, t: float) -> QImage:
    """把窗口拨到 t 并抓整幅。"""
    win.anim_t = round(t, 6)
    return win.grab().toImage()


def _scale15(img: QImage) -> QImage:
    """1.5 倍最近邻放大（FastTransformation = 最近邻取样）。"""
    return img.scaled(
        img.width() * 3 // 2, img.height() * 3 // 2, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


def _crop_panel(img: QImage) -> QImage:
    return _scale15(img.copy(PANEL))


def _crop_video(img: QImage) -> QImage:
    out = img.copy(VCROP)
    return out.scaled(
        out.width() * 2, out.height() * 2, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


def _lit(buf: bytes, stride: int, x: int, y: int) -> bool:
    i = y * stride + x * 4
    b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    return a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70


def lit_bbox(img: QImage, clip: QRect) -> tuple[int, int, int, int]:
    src = img.convertToFormat(QImage.Format_ARGB32)
    buf = bytes(src.constBits())
    stride = src.bytesPerLine()
    x0 = y0 = 10**9
    x1 = y1 = -1
    for y in range(clip.top(), clip.bottom() + 1):
        for x in range(clip.left(), clip.right() + 1):
            if _lit(buf, stride, x, y):
                x0 = min(x0, x)
                x1 = max(x1, x)
                y0 = min(y0, y)
                y1 = max(y1, y)
    assert x1 >= 0, "没扫到脸像素？"
    return x0, y0, x1, y1


def _tile(img: QImage, title: str, sub: str) -> QImage:
    panel = QImage(img.width(), img.height() + 44, QImage.Format_ARGB32)
    panel.fill(BG)
    p = QPainter(panel)
    p.drawImage(0, 0, img)
    p.setFont(QFont("", 14))
    p.setPen(TITLE)
    p.drawText(10, img.height() + 20, title)
    p.setFont(QFont("", 11))
    p.setPen(SUB)
    p.drawText(10, img.height() + 38, sub)
    p.end()
    return panel


def _card(lines: list[str], size: tuple[int, int]) -> QImage:
    img = QImage(size[0], size[1], QImage.Format_ARGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setPen(TITLE)
    p.setFont(QFont("", 16))
    p.drawText(18, 36, "判据数字卡（与 tests/test_survey.py 同口径）")
    p.setFont(QFont("", 12))
    y = 72
    for line in lines:
        p.setPen(TITLE if line.startswith("\u2022") else SUB)
        p.drawText(18, y, line)
        y += 24
    p.end()
    return img


def _grid(title: str, subtitle: str, panels: list[QImage], cols: int, out: Path) -> str:
    pad, capt = 14, 48
    pw = max(p.width() for p in panels)
    ph = max(p.height() for p in panels)
    rows = (len(panels) + cols - 1) // cols
    Wc = pad + (pw + pad) * cols
    Hc = capt + pad + (ph + pad) * rows
    canvas = QImage(Wc, Hc, QImage.Format_ARGB32)
    canvas.fill(BG)
    p = QPainter(canvas)
    p.setFont(QFont("", 16))
    p.setPen(TITLE)
    p.drawText(pad, 26, title)
    p.setFont(QFont("", 12))
    p.setPen(SUB)
    p.drawText(pad, 44, subtitle)
    for i, panel in enumerate(panels):
        cx = pad + (i % cols) * (pw + pad)
        cy = capt + pad + (i // cols) * (ph + pad)
        p.drawImage(cx, cy, panel)
    p.end()
    canvas.save(str(out))
    return str(out)


# ── 主流程：真链路（自检滚完 -> _anim_tick 交班 -> 环顾）──

w = make_window()
assert w.begin_boot() is True, "开机开关没打开（SAMMY_BOOT）——素材需要它开着"
t0 = w._boot_t0
end = round(boot.total_seconds(len(w._boot_lines)), 6)
lead, dwell, ease = anim.SURVEY_LEAD_S, anim.SURVEY_DWELL_S, anim.GAZE_EASE
print(f"  自检：{len(w._boot_lines)} 行，整段 {end:.2f}s（t0={t0:.2f}）")

# (1) 自检滚完（还没交班）：拍一帧
k1_t = round(end - 0.75, 6)
img_k1 = look(w, k1_t)
fr1 = boot.frame_at(k1_t - t0, len(w._boot_lines))
assert fr1.phase == "log", f"k1 该在自检阶段，实际 {fr1.phase}"
print(f"  (1) 自检滚完：t={k1_t:.2f}（第 {fr1.lines} 行，光标{'亮' if fr1.cursor else '灭'}）")

# (2) 视频段：从自检尾段到环顾收尾 —— 交班在段内由 _anim_tick 走真链路
fps = 12
start = round(end - 1.15, 6)
stop_t = round(end + 3.97, 6)
n = int((stop_t - start) * fps) + 1
tmpdir = ROOT / ".tmp" / "_survey_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
ts = None
for i in range(n):
    t = round(start + i / fps, 6)
    if ts is None and t >= end:
        w.anim_t = round(end - 0.01, 6)
        w._anim_tick()  # 越过终点：交班 + 环顾（真链路）
        assert w._boot_t0 is None, "没交班"
        ts = w.anim_t  # 环顾锚点（交班那一拍）
        fut = [g for g in w.anim._gaze if g.t > ts]
        assert len(fut) == 3 and [(g.x, g.y) for g in fut] == list(anim.SURVEY_TARGETS), (
            "环顾没排上"
        )
        print(f"  (2) 交班 + 环顾：锚点 {ts:.3f}s（自检终点 {end:.2f}s）")
    w.anim_t = t
    img = _crop_video(w.grab().toImage())
    cv = QImage(img.width(), img.height() + 36, QImage.Format_ARGB32)
    cv.fill(BG)
    p = QPainter(cv)
    p.drawImage(0, 0, img)
    p.setFont(QFont("", 13))
    p.setPen(SUB)
    if t < end:
        cap = "自检播完中 —— 下一篇就是它自己的时间"
    elif t < ts + lead:
        cap = "交班：站定一下（第一眼 0.35 秒后）"
    elif t < ts + lead + 2 * dwell:
        cap = "环顾：左看一眼、右看一眼"
    else:
        cap = "收回正中 —— 交给随机漂移"
    p.drawText(12, img.height() + 24, cap)
    p.end()
    cv.save(str(tmpdir / f"{i:04d}.png"))
assert ts is not None, "视频段里没触发交班"

# (3) 四格关键帧（面板区 1.5 倍放大）+ 实测数字
plan = (
    ("k2", round(ts + 0.15, 6), "站定"),
    ("k3", round(ts + lead + ease + 0.2, 6), "左看"),
    ("k4", round(ts + lead + dwell + ease + 0.2, 6), "右看"),
    ("k5", round(ts + lead + 2 * dwell + ease + 0.25, 6), "回中"),
)
snaps = {"k1": img_k1}
for key, tt, label in plan:
    snaps[key] = look(w, tt)
    f = w.anim.frame_at(tt)
    print(f"  ({label}) t-ts={tt - ts:+.2f}s 视线 ({f.gx:+d},{f.gy:+d}) 拉高 {f.stretch:.3f}")

reg = w._face_region().adjusted(-8, -8, 8, 8)
boxes = {}
for key in ("k2", "k3", "k4", "k5"):
    boxes[key] = lit_bbox(snaps[key], SCAN)
    b = boxes[key]
    cx = (b[0] + b[2]) / 2.0
    print(f"  {key}：亮像素质心 x {cx:.1f} / 脸高 {b[3] - b[1]} / 外接框 {b}")
x2 = (boxes["k2"][0] + boxes["k2"][2]) / 2.0
x3 = (boxes["k3"][0] + boxes["k3"][2]) / 2.0
x4 = (boxes["k4"][0] + boxes["k4"][2]) / 2.0
x5 = (boxes["k5"][0] + boxes["k5"][2]) / 2.0
h2 = boxes["k2"][3] - boxes["k2"][1]
h3 = boxes["k3"][3] - boxes["k3"][1]
h5 = boxes["k5"][3] - boxes["k5"][1]
assert x4 - x3 >= 12, f"左到右没扫开：{x4 - x3:.1f}px"
assert h3 - h5 >= 4, f"边缘探头没拉高：左 {h3} vs 回中 {h5}"
for key in ("k3", "k4", "k5"):
    b = boxes[key]
    box = QRect(b[0], b[1], b[2] - b[0] + 1, b[3] - b[1] + 1)
    assert reg.contains(box), f"{key} 的脸冒出重绘区：{box} vs {reg}"
print(f"  左右横扫 {x4 - x3:.1f}px；探头拉高（左 {h3} vs 回中 {h5}）；关键帧都在重绘区里")

# (4) 帧带（六格）
f_gaze = {key: w.anim.frame_at(tt) for key, tt, _ in plan}
panels = [
    _tile(
        _crop_panel(snaps["k1"]),
        f"[1] 自检滚完（t-环顾 {k1_t - ts:+.2f}s）",
        "终端行到齐 —— 下一刻它有自己的收尾",
    ),
    _tile(
        _crop_panel(snaps["k2"]),
        f"[2] 交班 + 站定（{plan[0][1] - ts:+.2f}s）",
        "自检让位；第一眼在 0.35 秒后",
    ),
    _tile(
        _crop_panel(snaps["k3"]),
        f"[3] 看左边（{plan[1][1] - ts:+.2f}s）",
        f"视线 ({f_gaze['k3'].gx:+d},{f_gaze['k3'].gy:+d}) —— 探头拉高（好奇）",
    ),
    _tile(
        _crop_panel(snaps["k4"]),
        f"[4] 看右边（{plan[2][1] - ts:+.2f}s）",
        f"视线 ({f_gaze['k4'].gx:+d},{f_gaze['k4'].gy:+d}) —— 左右各看一眼",
    ),
    _tile(
        _crop_panel(snaps["k5"]),
        f"[5] 回正中（{plan[3][1] - ts:+.2f}s）",
        "收回正中 —— 之后交给随机漂移",
    ),
]
card_lines = [
    "\u2022 触发：boot 交班那一刻（播完 / 点跳过都看）—— 一次开机看一次",
    "\u2022 形状：站定 0.35s -> 左 1.4s -> 右 1.4s -> 回中（整段 3.7 秒）",
    "\u2022 目标：横到满幅（含抬头 2px）—— 复用既有凝视盒与缓动，半点新几何不加",
    "\u2022 不掷随机数；之后光标 / 打字 / 思考 / 搬运照常抢占（只是三条普通指令）",
    "\u2022 动画关 / 睡着不排（醒来那一下走哈欠那条边）；收完回正中再交给漂移",
    f"\u2022 实测：横扫 {x4 - x3:.1f}px；探头拉高 左 {h3} vs 回中 {h5}",
]
grid_panel_size = _crop_panel(snaps["k1"]).size()
panels.append(
    _tile(
        _card(card_lines, (grid_panel_size.width(), grid_panel_size.height())),
        "[6] 判据数字卡",
        "同口径：tests/test_survey.py",
    )
)
_grid(
    "上电环顾「自检播完，先看一圈」：站定 -> 左看一眼 -> 右看一眼 -> 回正中",
    "真窗口离屏抓帧；交班走 _anim_tick 真链路；面板区 1.5 倍最近邻放大（seed 7）",
    panels,
    3,
    OUT / "survey-strip.png",
)
print(f"  帧带: {OUT / 'survey-strip.png'}")

# (5) 短视频（12fps，循环 3 遍）
if shutil.which("ffmpeg"):
    mp4 = OUT / "survey-demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-stream_loop",
            "2",  # 输入侧选项，必须在 -i 前面
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
    print(f"  短视频: {mp4}（{n} 帧 / {stop_t - start:.1f} 秒，循环 3 次）")
else:
    print("  注意：没找到 ffmpeg —— 只出了帧带（短视频没生成，别当它出过了）")
shutil.rmtree(tmpdir, ignore_errors=True)

w.close()

for name in ("survey-strip.png", "survey-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}"
            f"  ({p.stat().st_size} bytes)"
        )
