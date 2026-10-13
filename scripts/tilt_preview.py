#!/usr/bin/env python3
"""歪头素材 ——「被戳了，歪着脑袋看你（唔？）」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- tilt-strip.png   6 格（脸部 2x 最近邻放大 + 双色幽灵）：常态 -> 起手缓入 ->
                   歪到满（第一下）-> 收尾中 -> 第二下（换边）-> 收完，另加判据数字卡
- tilt-demo.mp4    两下完整的歪头（12fps，循环 3 遍），证明它是「在动」不是一帧贴图

用法:
    .venv/bin/python scripts/tilt_preview.py

纪律（和 hum_preview 一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_tilt.py 同一个）；
- 画面走**真绘制代码**（真窗口真 grab），不是拼图；状态文字也走真状态；
- 双色幽灵：琥珀 = 没歪的孪生站过的地方（twin 亮、歪的它不亮）；
  天蓝 = 歪过去新占的地方（歪的它亮、twin 不亮）；重叠处保持原样；
  检测一律按 faces.LIT 常量（别写死颜色）；
- 放大一律最近邻；ffmpeg 不在就只出帧带并说明（不静默降级）；
- 顺手把「主轴角 / 重心 / 两种幽灵的像素数 / 收完差没差」打出来（DEVLOG 引它当证据）。
"""

from __future__ import annotations

import hashlib
import math
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

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import anim, drives, faces, layout
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_tilt.py 一家的种子（窗口里的随机都钉死）
T0 = 1.0  # 第一下歪头在时间轴上的起点
GAP = 0.6  # 两下之间的空档
ZOOM = 2  # 帧带 / 视频放大倍数
CROP = QRect(146, 2, 508, 248)  # 脸的裁剪区（要盖住满幅旋转的四个角，脚本里有断言）
SCAN = QRect(120, 0, 580, 238)  # 找脸部亮像素的范围（状态行从 y=242 起、关闭钮在 x>=732 —— 都避开）
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：没歪的它站过的地方
SKY = QColor(90, 167, 200)  # 天蓝：歪过去新占的地方

app = QApplication(sys.argv[:1])
layout.load_fonts()

FULL = round(anim.tilt_total(), 6)
T1 = round(T0 + FULL + GAP, 6)  # 第二下（换边）的起点


def make_window() -> SammyWindow:
    """稳态窗口：普通脸、状态行「在线」—— 只留歪头一个变量。"""
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED)
    win.look_on = False  # 光标不参与（盯的是歪头这一件事）
    win.set_expression(2)  # 普通脸
    win._idle_face = None
    # 状态文字和脸一致（脸普通、字写「睡着了」是最忌讳的自相矛盾）
    win.status = drives.status_text(win.drives)
    win.my_line = ""  # 素材里不留上一句的残影
    win.sammy_line = ""
    win.anim_t = T0
    # 素材脚本不碰真状态：关窗时的保存全换成空操作（素材不是它的一天）
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(win, name, lambda: None)
    win.show()
    return win


def look(win: SammyWindow, t: float) -> QImage:
    """把窗口拨到 t 并抓整幅。"""
    win.anim_t = round(t, 6)
    return win.grab().toImage()


def _lit(buf: bytes, stride: int, x: int, y: int) -> bool:
    i = y * stride + x * 4
    b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    return a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70


def lit_bbox(img: QImage, clip: QRect) -> tuple[int, int, int, int]:
    """clip 里所有亮像素的外接框 —— 满幅旋转的四个角必须落在 CROP 里。"""
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


def moment_angle(img: QImage, clip: QRect) -> tuple[float, tuple[float, float], int]:
    """亮像素云的主轴角（度）、质心、像素数 —— 拿它量「真的在转」。"""
    src = img.convertToFormat(QImage.Format_ARGB32)
    buf = bytes(src.constBits())
    stride = src.bytesPerLine()
    pts = []
    for y in range(clip.top(), clip.bottom() + 1):
        for x in range(clip.left(), clip.right() + 1):
            if _lit(buf, stride, x, y):
                pts.append((x, y))
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    m20 = sum((p[0] - mx) ** 2 for p in pts) / n
    m02 = sum((p[1] - my) ** 2 for p in pts) / n
    m11 = sum((p[0] - mx) * (p[1] - my) for p in pts) / n
    ang = 0.5 * math.degrees(math.atan2(2 * m11, m20 - m02))
    return ang, (mx, my), n


def _crop2x(img: QImage) -> QImage:
    out = img.copy(CROP)
    return out.scaled(
        out.width() * ZOOM, out.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


def _ghost(base: QImage, twin: QImage) -> tuple[QImage, int, int]:
    """双色幽灵：琥珀 = 孪生站过而歪的它没占的；天蓝 = 歪的它新占的。"""
    ab = base.convertToFormat(QImage.Format_ARGB32)
    tb = twin.convertToFormat(QImage.Format_ARGB32)
    out = ab
    as_ = bytes(ab.constBits())
    ts = bytes(tb.constBits())
    stride_a = ab.bytesPerLine()
    stride_t = tb.bytesPerLine()
    pen_a = QColor(AMB)
    pen_a.setAlpha(170)
    pen_s = QColor(SKY)
    pen_s.setAlpha(170)
    p = QPainter(out)
    n_amb = n_sky = 0
    for y in range(out.height()):
        for x in range(out.width()):
            la = _lit(as_, stride_a, x, y)
            lt = _lit(ts, stride_t, x, y)
            if lt and not la:
                p.setPen(pen_a)
                p.drawPoint(x, y)
                n_amb += 1
            elif la and not lt:
                p.setPen(pen_s)
                p.drawPoint(x, y)
                n_sky += 1
    p.end()
    return out, n_amb, n_sky


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


def _card(lines: list[str]) -> QImage:
    img = QImage(CROP.width() * ZOOM, CROP.height() * ZOOM, QImage.Format_ARGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setPen(TITLE)
    p.setFont(QFont("", 15))
    p.drawText(18, 34, "判据数字卡（与 tests/test_tilt.py 同口径）")
    p.setFont(QFont("", 12))
    y = 66
    for line in lines:
        p.setPen(TITLE if line.startswith("\u2022") else SUB)
        p.drawText(18, y, line)
        y += 22
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


# ── 帧带：六个时刻 + 数字卡 ────────────────────────
a = make_window()
b = make_window()  # 对照：同种子、只差「有没有歪」
a.anim.tilt(T0)  # 第一下：左半边沉

plan = [
    ("(1) 常态（戳之前）", T0, "还没歪 —— 与孪生完全重合"),
    ("(2) 起手・缓入中", T0 + anim.TILT_RISE_S / 2, "轻轻歪进去（包络一半）—— 起手不许突然"),
    (
        "(3) 歪到满（第一下）",
        T0 + anim.TILT_RISE_S + anim.TILT_HOLD_S / 2,
        "左半边沉、右半边抬 —— 琥珀/天蓝是两圈月牙",
    ),
    (
        "(4) 收尾中",
        T0 + anim.TILT_RISE_S + anim.TILT_HOLD_S + anim.TILT_FALL_S / 2,
        "从当前角度缓回来 —— 不突然停",
    ),
]
plan2 = [
    (
        "(5) 第二下（换边）",
        T1 + anim.TILT_RISE_S + anim.TILT_HOLD_S / 2,
        "这次右半边沉 —— 方向一次一换",
    ),
    ("(6) 收完・回到常态", T1 + FULL + 0.4, "与「没歪过」的它整幅逐像素一致"),
]

frames: list[tuple[str, QImage]] = []
ghost_amb: dict[str, int] = {}
ghost_sky: dict[str, int] = {}
d_ang: dict[str, float] = {}
bbox_checked = False
for label, t, note in plan + plan2:
    if t >= T1 and a.anim._tilt_dir == -1:
        # 到这一步才排第二下（换边）—— 排早了 _tilt_at 被顶掉，第一下就没了
        a.anim.tilt(T1)
    ia = look(a, t)
    ib = look(b, t)
    if not bbox_checked and "满" in label:
        x0, y0, x1, y1 = lit_bbox(ia, SCAN)
        assert CROP.adjusted(-4, -4, 4, 4).contains(QRect(x0, y0, x1 - x0, y1 - y0)), (
            f"满幅旋转的角跑到裁剪区外了: {(x0, y0, x1, y1)} vs {CROP}"
        )
        bbox_checked = True
    ca, cb = ia.copy(CROP), ib.copy(CROP)
    ghosted, n_amb, n_sky = _ghost(ca, cb)
    ang_a, _c, _n = moment_angle(ia, SCAN)
    ang_b, _c2, _n2 = moment_angle(ib, SCAN)
    ghost_amb[label] = n_amb
    ghost_sky[label] = n_sky
    d_ang[label] = ang_a - ang_b
    sub = f"{note} · 主轴角差 {ang_a - ang_b:+.2f} 度 · 琥珀 {n_amb} 天蓝 {n_sky}"
    frames.append((label, _tile(_crop2x(ghosted), f"{label} · tau={t - T0:.2f}s", sub)))

# 量化证据（打给 DEVLOG / 人看）
print(f"  主轴角差（六格，负 = 第一下方向）：{[round(v, 2) for v in d_ang.values()]}")
print(f"  琥珀幽灵（没歪的它站过的地方）: {list(ghost_amb.values())}")
print(f"  天蓝幽灵（歪过去新占的地方）: {list(ghost_sky.values())}")
ia_end = look(a, T1 + FULL + 0.4).convertToFormat(QImage.Format_ARGB32)
ib_end = look(b, T1 + FULL + 0.4).convertToFormat(QImage.Format_ARGB32)
ba, bb = bytes(ia_end.constBits()), bytes(ib_end.constBits())
diff = sum(1 for i in range(0, len(ba), 4) if ba[i : i + 4] != bb[i : i + 4])
print(f"  收完对比：与「没歪过」的孪生不同像素 {diff} 个（期望 0）")
x0, y0, x1, y1 = lit_bbox(look(a, T0 + anim.TILT_RISE_S + anim.TILT_HOLD_S / 2), SCAN)
print(
    f"  满幅时脸部亮像素外接框：x {x0}..{x1} / y {y0}..{y1}（裁剪区 {CROP.x()}..{CROP.right()} / {CROP.y()}..{CROP.bottom()}）"
)
a.close()
b.close()

card_lines = [
    "\u2022 触发：醒着被戳（睡着被戳是叫醒的哈欠；累趴与动画关都不歪）",
    "\u2022 形状：歪过去 0.25 秒、停 0.55 秒、直回来 0.45 秒（整段 1.25 秒）",
    "\u2022 方向：一次一换 —— 第一下左半边沉、第二下右半边沉",
    "\u2022 标记点实测（tests）：绕脸中心转的就是 5 度（误差不超过 0.75px）",
    "\u2022 主轴角读数会啃掉一点边缘（阈值量法），故略小于标称值 —— 方向与量级都对上",
    "\u2022 琥珀幽灵 = 没歪的它站过的地方；天蓝幽灵 = 歪过去新占的地方",
    "\u2022 收完（格 6）：与「没歪过」的它整幅逐像素一致（0 个不同）",
]
frames.append(("(7) 判据数字卡", _card(card_lines)))

_grid(
    "歪头「被戳了，歪着脑袋看你（唔？）」：绕脸中心轻转 5 度，再直回来",
    "双胞胎实测（同种子：在歪的它 vs 没歪的它）· 2x 最近邻放大 · 与真机同一段绘制代码",
    [img for _, img in frames],
    3,
    OUT / "tilt-strip.png",
)
print(f"  帧带: {OUT / 'tilt-strip.png'}")

# ── 短视频：两下完整的歪头，循环 3 遍 ───────────────
fps = 12
start, stop = T0 - 0.5, T1 + FULL + 0.5
n = int((stop - start) * fps)
tmpdir = ROOT / ".tmp" / "_tilt_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
win = make_window()
win.anim.tilt(T0)
for i in range(n):
    t = round(start + i / fps, 6)
    if t >= T1 and win.anim._tilt_dir == -1:
        win.anim.tilt(T1)  # 到点了排第二下（换边）
    win.anim_t = t
    _crop2x(win.grab().toImage()).save(str(tmpdir / f"{i:04d}.png"))
win.close()

if shutil.which("ffmpeg"):
    mp4 = OUT / "tilt-demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-stream_loop",
            "2",  # 这是**输入侧**选项，必须在 -i 前面
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

for name in ("tilt-strip.png", "tilt-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
