#!/usr/bin/env python3
"""困得点头素材 ——「困了的时候，一点一点地打盹」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- nod-strip.png   6 格（脸部 2× 最近邻放大 + 琥珀幽灵）：常态 → 沉下去中 →
                  沉到底(撑住) → 弹回来中 → 收完回常态 → 判据数字卡
- nod-demo.mp4    一下完整的点头（12fps，循环 3 遍），证明它是「在动」不是一帧贴图

用法:
    .venv/bin/python scripts/nod_preview.py

纪律（和其他素材脚本一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_nod.py 同一个）；
- 画面走**真绘制代码**（真窗口真 grab），不是拼图；「犯困」也走真状态文字
  （drives.status_text —— 脸和字不许自相矛盾，doze 那次的教训）；
- 琥珀幽灵 = 同种子孪生（**没在点头的它**）的脸：只涂「两边不一样」的月牙边，
  重叠处保持原样；检测一律按 faces.LIT 常量（**别写死颜色** —— 配色改白之后，
  按绿色写死检测的旧脚本重跑会量到 0，DEVLOG 有记）；
- 放大一律最近邻；ffmpeg 不在就只出帧带并说明（不静默降级）；
- 顺手把「顶沿沉几像素 / 脸矮多少 / 收完有没有归零」几个数打出来（DEVLOG 引它当证据）。
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

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import anim, drives, faces, layout
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_nod.py 一家的种子（窗口里的随机都钉死）
T0 = 1.0  # 点头在时间轴上的起点
ZOOM = 2  # 帧带 / 视频放大倍数（脸的内容不高，2× 才看得清那几像素的沉）
CROP = QRect(180, 8, 440, 236)  # 脸的裁剪区（scale 1.0 的真实像素）
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：孪生（没在点头的它）站过的地方

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window(*, with_nod: bool = True) -> SammyWindow:
    """稳态窗口：energy 0.25、犯困脸、状态行「有点困了」—— 只留点头一个变量。"""
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED)
    win.look_on = False  # 光标不参与（盯的是点头这一件事）
    win.drives.energy = 0.25
    win.set_expression(27)  # 犯困脸
    win._idle_face = None
    # 状态文字必须和脸一致（脸犯困、字写「在线」是最忌讳的自相矛盾）
    win.status = drives.status_text(win.drives)
    win.my_line = ""  # 素材里不留上一句的残影
    win.sammy_line = ""
    win.anim_t = T0
    if with_nod:
        win.anim.nod(T0)
    # 素材脚本不碰真状态：关窗时的保存全换成空操作（素材不是它的一天）
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(win, name, lambda: None)
    win.show()
    return win


def look(win: SammyWindow, tau: float) -> QImage:
    """把窗口拨到 τ 并抓整幅。"""
    win.anim_t = round(T0 + tau, 6)
    return win.grab().toImage()


def _lit(buf: bytes, stride: int, x: int, y: int) -> bool:
    i = y * stride + x * 4
    b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    return a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70


def face_box(img: QImage) -> tuple[int, int, int, int]:
    """face 区里「不透明亮像素」的外接框 —— 量「沉几像素、矮多少」用。"""
    src = img.convertToFormat(QImage.Format_ARGB32)
    buf = bytes(src.constBits())
    stride = src.bytesPerLine()
    x0 = y0 = 10**9
    x1 = y1 = -1
    for y in range(CROP.top(), CROP.bottom() + 1):
        for x in range(CROP.left(), CROP.right() + 1):
            if _lit(buf, stride, x, y):
                x0 = min(x0, x)
                x1 = max(x1, x)
                y0 = min(y0, y)
                y1 = max(y1, y)
    assert x1 >= 0, "没扫到脸像素？"
    return x0, y0, x1, y1


def _crop2x(img: QImage) -> QImage:
    out = img.copy(CROP)
    return out.scaled(
        out.width() * ZOOM, out.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


def _ghost(base: QImage, twin: QImage) -> tuple[QImage, int]:
    """把孪生（没在点头的它）的脸用琥珀色勾出来 —— 只涂「两边不一样」的边。

    脸矮下去 / 沉下去之后，边缘会露出一圈月牙（琥珀 = 它不点头时头在哪儿）；
    两张脸完全重合时（点头前 / 收完）琥珀一点都不会出现 —— 那条「0」就是归零的证据。
    返回 (画好幽灵的图, 月牙像素数)。
    """
    # 显式命名步：constBits() 的有效期跟着 QImage 对象走 —— 别让它挂在临时量上
    ab = base.convertToFormat(QImage.Format_ARGB32)
    tb = twin.convertToFormat(QImage.Format_ARGB32)
    out = ab
    as_ = bytes(ab.constBits())
    ts = bytes(tb.constBits())
    stride_a = ab.bytesPerLine()
    stride_t = tb.bytesPerLine()
    pen = QColor(AMB)
    pen.setAlpha(170)
    p = QPainter(out)
    p.setPen(pen)
    n = 0
    for y in range(out.height()):
        for x in range(out.width()):
            if _lit(ts, stride_t, x, y) and not _lit(as_, stride_a, x, y):
                p.drawPoint(x, y)
                n += 1
    p.end()
    return out, n


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
    p.drawText(18, 34, "判据数字卡（与 tests/test_nod.py 同口径）")
    p.setFont(QFont("", 12))
    y = 66
    for line in lines:
        p.setPen(TITLE if line.startswith("•") else SUB)
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


DONE = round(anim.nod_total() + 0.4, 6)  # 收完的时刻（τ）

# ── 帧带：五个时刻 + 数字卡 ────────────────────────
a = make_window(with_nod=True)
b = make_window(with_nod=False)  # 对照：同种子、只差「有没有点头」

plan = [
    ("（①）常态（点头前）", 0.0, "还没点 —— 也就这一刻琥珀为 0"),
    (
        "（②）沉下去中",
        round(anim.NOD_SAG_S * 0.5, 6),
        "顶沿开始沉、脸开始矮（琥珀 = 没点头的它在哪儿）",
    ),
    (
        "（③）沉到底（撑住）",
        round(anim.NOD_SAG_S + anim.NOD_HOLD_S * 0.5, 6),
        f"撑住那一下：压到 {anim.NOD_SQUINT_MIN:.0%} + 沉 {anim.NOD_SINK_PX}px",
    ),
    (
        "（④）弹回来中",
        round(anim.NOD_SAG_S + anim.NOD_HOLD_S + anim.NOD_SNAP_S * 0.5, 6),
        "往回弹 —— 比沉下去快得多（惊醒）",
    ),
    ("（⑤）收完 · 回到常态", DONE, "与「没点过头」的它整幅逐像素一致"),
]

frames: list[tuple[str, QImage]] = []
crescents: dict[str, int] = {}
for label, tau, note in plan:
    ia = look(a, tau)
    ib = look(b, tau)
    ya = face_box(ia)
    yb = face_box(ib)
    ca, cb = ia.copy(CROP), ib.copy(CROP)
    ghosted, n = _ghost(ca, cb)
    crescents[label] = n
    drop = ya[1] - yb[1]
    hdelta = (yb[3] - yb[1]) - (ya[3] - ya[1])
    sub = f"{note} · 顶沿 {drop:+d}px · 脸高 {hdelta:+d}px"
    frames.append((label, _tile(_crop2x(ghosted), f"{label} · τ={tau:.2f}s", sub)))

# 量化证据（打给 DEVLOG / 人看）
full_tau = round(anim.NOD_SAG_S + anim.NOD_HOLD_S * 0.5, 6)
xa0, ya0, xa1, ya1s = face_box(look(a, full_tau))
xb0, yb0, xb1, yb1s = face_box(look(b, full_tau))
print(f"  沉到底（τ={full_tau:.2f}s）：顶沿下沉 {ya0 - yb0}px；下沿 {ya1s - yb1s:+d}px；")
print(
    f"    脸高 {(yb1s - yb0)} → {(ya1s - ya0)}px（{((ya1s - ya0) / (yb1s - yb0) - 1) * 100:+.0f}%）；"
    f"宽度差 {(xa1 - xa0) - (xb1 - xb0)}px"
)
half = round(anim.NOD_SAG_S * 0.5, 6)
_, yh0, _, _ = face_box(look(a, half))
_, ybh0, _, _ = face_box(look(b, half))
print(f"  沉下去中（τ={half:.2f}s）：顶沿下沉 {yh0 - ybh0}px（渐进）")
ia_done = look(a, DONE).convertToFormat(QImage.Format_ARGB32)
ib_done = look(b, DONE).convertToFormat(QImage.Format_ARGB32)
ba, bb = bytes(ia_done.constBits()), bytes(ib_done.constBits())
diff = sum(1 for i in range(0, len(ba), 4) if ba[i : i + 4] != bb[i : i + 4])
print(f"  收完对比：与「没点过头」的孪生不同像素 {diff} 个（期望 0）")
print("  琥珀月牙像素（五个时刻，按顺序）:", list(crescents.values()))
a.close()
b.close()

card_lines = [
    "• 触发：犯困（energy 低于驱力的犯困线）且没在忙（睡着 / 刚聊完 5 秒 / 思考中 / 动画关都不点）",
    f"• 节奏：每 {anim.NOD_MIN_GAP:.0f}~{anim.NOD_MAX_GAP:.0f} 秒一下（随机，别像节拍器）",
    f"• 一下 {anim.nod_total():.2f} 秒：沉 {anim.NOD_SAG_S:.2f}s → 撑住 {anim.NOD_HOLD_S:.2f}s → 弹回 {anim.NOD_SNAP_S:.2f}s",
    f"• 幅度：压到 {anim.NOD_SQUINT_MIN:.2f}（眼皮掉下来）+ 下沉 {anim.NOD_SINK_PX}px（头一点）",
    f"• 实测（上面五格）：顶沿沉 {ya0 - yb0}px · 脸高 {(ya1s - ya0)} vs {(yb1s - yb0)}px · 宽度不动",
    f"• 收完：与孪生整幅逐像素一致（{diff} 个不同像素）",
    "• 琥珀月牙 = 没点头的它站过的地方（矮下去 / 沉下去露出的那些）",
]
frames.append(("（⑥）判据数字卡", _card(card_lines)))

_grid(
    "困得点头「困了的时候，一点一点地打盹」：脸缓缓沉下去、眼皮掉下来、撑住一下、猛地弹回来",
    "双胞胎实测（同种子：点头的它 vs 没点头的它）· 2× 最近邻放大 · 与真机同一段绘制代码",
    [img for _, img in frames],
    3,
    OUT / "nod-strip.png",
)
print(f"  帧带: {OUT / 'nod-strip.png'}")

# ── 短视频：一下完整的点头，循环 3 遍 ───────────────
fps = 12
start, stop = T0 - 0.6, T0 + anim.nod_total() + 0.6
n = int((stop - start) * fps)
tmpdir = ROOT / ".tmp" / "_nod_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
win = make_window(with_nod=True)
for i in range(n):
    t = round(start + i / fps, 6)
    win.anim_t = t
    _crop2x(win.grab().toImage()).save(str(tmpdir / f"{i:04d}.png"))
win.close()

if shutil.which("ffmpeg"):
    mp4 = OUT / "nod-demo.mp4"
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

for name in ("nod-strip.png", "nod-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
