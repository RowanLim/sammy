#!/usr/bin/env python3
"""睡梦抽动素材 ——「睡着的时候，偶尔轻轻抽一下」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- twitch-strip.png   7 格（脸部 2× 最近邻放大 + 琥珀幽灵）：常态 → 抽上去中 →
                     抽到顶 → 松回来中 → 收完回常态 → 第二下换边 → 判据数字卡
- twitch-demo.mp4    一次完整的抽动（20fps，循环 3 遍），证明它是「在动」不是一帧贴图

用法:
    .venv/bin/python scripts/twitch_preview.py

纪律（和其他素材脚本一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_twitch.py 同一个）；
- 画面走**真绘制代码**（真窗口真 grab），不是拼图；「睡着」也走真状态文字
  （drives.status_text —— 脸和字不许自相矛盾，doze 那次的教训）；
- 琥珀幽灵 = 同种子孪生（**没在抽的它**）的脸：只涂「两边不一样」的月牙边，
  重叠处保持原样；检测一律按 faces.LIT 常量（别写死颜色）；放大一律最近邻；
- 抽动**不占随机流**（方向左右交替）—— 孪生因此能除了这一下之外逐像素对齐；
- ffmpeg 不在就只出帧带并说明（不静默降级）；几个数打出来给 DEVLOG 当证据。
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
from sammy.pet import SLEEP_EXPR, SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_twitch.py 一家的种子（窗口里的随机都钉死）
T0 = 1.0  # 第一下抽动在时间轴上的起点
T1 = 2.2  # 第二下（换边）的起点
ZOOM = 2  # 帧带 / 视频放大倍数（脸的形变只有几像素，2× 才看得清）
CROP = QRect(160, 6, 480, 226)  # 脸 + 两侧余量（下沿切干净：状态文字在 y240 之下，别量进来）
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：孪生（没在抽的它）站过的地方

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window(*, with_twitch: bool) -> SammyWindow:
    """稳态窗口：累趴（状态行「睡着了」）+ 睡脸 + 时间轴钉住 —— 只留抽动一个变量。

    不 set drives.asleep 标志：那样会挂出 Z（Z 有自己的 doze 素材），
    这里要的是「睡脸 + 干净的对照」；calm 看的是表情（SLEEP_EXPR）。
    """
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED)
    win.look_on = False  # 光标不参与（盯的是抽动这一件事）
    win.drives.energy = 0.05  # 累趴档：状态行「睡着了」与睡脸一致
    win.set_expression(SLEEP_EXPR)
    win._idle_face = None
    win.status = drives.status_text(win.drives)
    win.my_line = ""  # 素材里不留上一句的残影
    win.sammy_line = ""
    win.anim_t = T0
    if with_twitch:
        win.anim.twitch(T0)
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
    """CROP 区里「不透明亮像素」的外接框 —— 量「往哪边激灵、缩了多少」用。"""
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
    """把孪生（没在抽的它）的脸用琥珀色勾出来 —— 只涂「两边不一样」的边。"""
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
    p.drawText(18, 34, "判据数字卡（与 tests/test_twitch.py 同口径）")
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


DONE = round(anim.twitch_total() + 0.4, 6)  # 收完的时刻（τ）
PEAK = round(anim.TWITCH_JOLT_S + anim.TWITCH_HOLD_S / 2, 6)  # 抽到顶
T2PEAK = round((T1 - T0) + anim.TWITCH_JOLT_S + anim.TWITCH_HOLD_S / 2, 6)  # 第二下抽到顶

# ── 帧带：六个时刻 + 数字卡 ────────────────────────
a = make_window(with_twitch=True)
b = make_window(with_twitch=False)  # 对照：同种子、只差「有没有抽」

plan = [
    ("（①）常态（睡前 / 还没抽）", 0.0, "两边一模一样 —— 也就这一刻琥珀为 0"),
    ("（②）抽上去中", round(anim.TWITCH_JOLT_S * 0.5, 6), "快到只有几帧：肌肉一激灵是抽上去的事"),
    (
        "（③）抽到顶",
        PEAK,
        f"横向一激灵 {anim.TWITCH_SHIFT_PX}px + 纵向压到 {anim.TWITCH_DEFLATE:.0%}（轻轻一缩）",
    ),
    (
        "（④）松回来中",
        round(anim.TWITCH_JOLT_S + anim.TWITCH_HOLD_S + anim.TWITCH_SETTLE_S * 0.5, 6),
        "比抽上去慢得多 —— 像又睡过去了",
    ),
    ("（⑤）收完 · 回到常态", DONE, "与「没抽过」的它整幅逐像素一致"),
]

frames: list[tuple[str, QImage]] = []
crescents: dict[str, int] = {}
metric_peak: tuple[int, int, int, int, int, int] | None = None
for label, tau, note in plan:
    ia = look(a, tau)
    ib = look(b, tau)
    ya = face_box(ia)
    yb = face_box(ib)
    ca, cb = ia.copy(CROP), ib.copy(CROP)
    ghosted, n = _ghost(ca, cb)
    crescents[label] = n
    dx_l = ya[0] - yb[0]
    dx_r = ya[2] - yb[2]
    dy_t = ya[1] - yb[1]
    dy_b = ya[3] - yb[3]
    if abs(tau - PEAK) < 1e-9:
        metric_peak = (dx_l, dx_r, dy_t, dy_b, ya[3] - ya[1], yb[3] - yb[1])
    sub = f"{note} · 左缘 {dx_l:+d}px · 顶沿 {dy_t:+d}px"
    frames.append((label, _tile(_crop2x(ghosted), f"{label} · τ={tau:.3f}s", sub)))

# 第二下：换边（往右）
a.anim.twitch(T0 + (T1 - T0))
ia = look(a, T2PEAK)
ib = look(b, T2PEAK)
ya = face_box(ia)
yb = face_box(ib)
ca, cb = ia.copy(CROP), ib.copy(CROP)
ghosted, n = _ghost(ca, cb)
crescents["（⑥）第二下换边"] = n
frames.append(
    (
        "（⑥）第二下：换边（往右）",
        _tile(
            _crop2x(ghosted),
            f"（⑥）第二下 · τ={T2PEAK:.3f}s",
            f"方向一左一右交替 · 左缘 {ya[0] - yb[0]:+d}px · 顶沿 {ya[1] - yb[1]:+d}px",
        ),
    )
)

# 量化证据（打给 DEVLOG / 人看）
assert metric_peak is not None
dx_l, dx_r, dy_t, dy_b, h_a, h_b = metric_peak
print(
    f"  抽到顶（τ={PEAK:.3f}s）：左缘 {dx_l:+d}px / 右缘 {dx_r:+d}px（期望 ∓{anim.TWITCH_SHIFT_PX}）"
)
print(f"    顶沿 {dy_t:+d}px / 下沿 {dy_b:+d}px；脸高 {h_a} vs {h_b}px（{h_a - h_b:+d}）")
ia_done = look(a, DONE).convertToFormat(QImage.Format_ARGB32)
ib_done = look(b, DONE).convertToFormat(QImage.Format_ARGB32)
ba, bb = bytes(ia_done.constBits()), bytes(ib_done.constBits())
diff = sum(1 for i in range(0, len(ba), 4) if ba[i : i + 4] != bb[i : i + 4])
print(f"  收完对比：与「没抽过」的孪生不同像素 {diff} 个（期望 0）")
print("  琥珀月牙像素（按顺序）:", list(crescents.values()))
a.close()
b.close()

card_lines = [
    "• 触发：睡着（drives.asleep）+ 动画开；每 25~70 秒轻轻抽一下（随机，别像节拍器）",
    f"• 一下 {anim.twitch_total():.2f} 秒：抽 {anim.TWITCH_JOLT_S:.2f}s → 顶住 {anim.TWITCH_HOLD_S:.2f}s → 松 {anim.TWITCH_SETTLE_S:.2f}s",
    f"• 幅度：横向 ±{anim.TWITCH_SHIFT_PX}px（一左一右交替）+ 纵向压到 {anim.TWITCH_DEFLATE:.2f}（轻轻一缩）",
    f"• 实测（上面各格）：左缘 {dx_l:+d}px / 右缘 {dx_r:+d}px / 顶沿 {dy_t:+d}px / 下沿 {dy_b:+d}px",
    f"• 脸高 {h_a} vs {h_b}px（{-abs(h_a - h_b)}）；宽度不动；收完与孪生逐像素一致（{diff} 个不同像素）",
    "• ①⑤ 两格琥珀为 0 = 「睡前 / 收完两边一模一样」的证据",
    "• 琥珀月牙 = 没抽的它站过的地方（横向 / 纵向露出来的那一圈）",
]
frames.append(("（⑦）判据数字卡", _card(card_lines)))

_grid(
    "睡梦抽动「睡着的时候，偶尔轻轻抽一下」：横向一激灵、轻轻一缩，然后接着睡",
    "双胞胎实测（同种子：抽的它 vs 没抽的它）· 2× 最近邻放大 · 与真机同一段绘制代码",
    [img for _, img in frames],
    4,
    OUT / "twitch-strip.png",
)
print(f"  帧带: {OUT / 'twitch-strip.png'}")

# ── 短视频：一次完整的抽动，循环 3 遍 ───────────────
fps = 20
start, stop = T0 - 0.8, T0 + anim.twitch_total() + 0.8
n = int((stop - start) * fps)
tmpdir = ROOT / ".tmp" / "_twitch_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
win = make_window(with_twitch=True)
for i in range(n):
    t = round(start + i / fps, 6)
    win.anim_t = t
    _crop2x(win.grab().toImage()).save(str(tmpdir / f"{i:04d}.png"))
win.close()

if shutil.which("ffmpeg"):
    mp4 = OUT / "twitch-demo.mp4"
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

for name in ("twitch-strip.png", "twitch-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
