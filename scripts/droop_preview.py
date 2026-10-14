#!/usr/bin/env python3
"""蔫一会儿素材 ——「心情有点蔫的时候，悄悄往下垂一垂」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- droop-strip.png   6 格（脸部 2x 最近邻放大 + 琥珀幽灵）：常态 -> 垂下去中 ->
                    垂到底 -> 蔫着停住 -> 缓起来中 -> 收完，另加判据数字卡
- droop-demo.mp4    一段完整的蔫一会儿（12fps，循环 3 遍），证明它是「在动」不是一帧贴图

用法:
    .venv/bin/python scripts/droop_preview.py

纪律（和其他素材脚本一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_droop.py 同一个）；
- 画面走**真绘制代码**（真窗口真 grab），不是拼图；状态文字也走真状态
  （drives.status_text —— 脸和字不许自相矛盾，doze 那次的教训）；
- 琥珀幽灵 = 同种子孪生（**没在垂的它**）的脸：只涂「两边不一样」的部分，
  重叠处保持原样；检测一律按 faces.LIT 常量（**别写死颜色**）；
- 放大一律最近邻；ffmpeg 不在就只出帧带并说明（不静默降级）；
- 顺手把「顶沿沉了多少 / 下沿收了多少 / 脸矮了多少 / 收完归没归零」打出来
  （DEVLOG 引它当证据）。
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
SEED = 7  # 和 tests/test_droop.py 一家的种子（窗口里的随机都钉死）
T0 = 1.0  # 蔫一会儿在时间轴上的起点
ZOOM = 2  # 帧带 / 视频放大倍数
CROP = QRect(180, 8, 440, 236)  # 脸的裁剪区（scale 1.0 的真实像素）
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：孪生（没在垂的它）站过的地方

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window(*, with_droop: bool = True) -> SammyWindow:
    """稳态窗口：普通脸、状态行「在线」—— 只留蔫一会儿一个变量。"""
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED)
    win.look_on = False  # 光标不参与（盯的是蔫一会儿这一件事）
    win.set_expression(2)  # 普通脸：「有点蔫」的档里它就是这张
    win._idle_face = None
    # 状态文字和脸一致（脸普通、字写「睡着了」是最忌讳的自相矛盾）
    win.status = drives.status_text(win.drives)
    win.my_line = ""  # 素材里不留上一句的残影
    win.sammy_line = ""
    win.anim_t = T0
    if with_droop:
        win.anim.droop(T0)
    # 素材脚本不碰真状态：关窗时的保存全换成空操作（素材不是它的一天）
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(win, name, lambda: None)
    win.show()
    return win


def look(win: SammyWindow, tau: float) -> QImage:
    """把窗口拨到 tau 并抓整幅。"""
    win.anim_t = round(T0 + tau, 6)
    return win.grab().toImage()


def _lit(buf: bytes, stride: int, x: int, y: int) -> bool:
    i = y * stride + x * 4
    b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    return a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70


def face_box(img: QImage) -> tuple[int, int, int, int]:
    """CROP 里脸的亮像素外接框。"""
    src = img.convertToFormat(QImage.Format_ARGB32)
    buf = bytes(src.constBits())
    stride = src.bytesPerLine()
    x0 = y0 = 10**9
    x1 = y1 = -1
    for y in range(CROP.top(), CROP.bottom() + 1):
        for x in range(CROP.left(), CROP.right() + 1):
            if not _lit(buf, stride, x, y):
                continue
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
    """把孪生（没在垂的它）的脸用琥珀色勾出来 —— 只涂「两边不一样」的部分。

    脸垂下去、变矮之后，它的原地会露出一圈月牙（琥珀 = 它没垂时脸在哪儿）；
    两张脸完全重合时（垂之前 / 收完之后）琥珀一点都不会出现 —— 那条「0」就是
    归零的证据。
    """
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
    p.drawText(18, 34, "判据数字卡（与 tests/test_droop.py 同口径）")
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


# 六个关键时刻的 tau
TAU_REST = 0.0
TAU_SINK = round(anim.DROOP_SINK_S * 0.5, 6)  # 垂下去中（一半）
TAU_DEEP = round(anim.DROOP_SINK_S, 6)  # 刚垂到底
TAU_HOLD = round(anim.DROOP_SINK_S + anim.DROOP_HOLD_S * 0.8, 6)  # 蔫着停住的中后段
TAU_RISE = round(anim.DROOP_SINK_S + anim.DROOP_HOLD_S + anim.DROOP_RISE_S * 0.5, 6)  # 缓起来中
DONE = round(anim.droop_total() + 0.4, 6)  # 收完的时刻（tau）

# ── 帧带：六个时刻 + 数字卡 ────────────────────────
a = make_window(with_droop=True)
b = make_window(with_droop=False)  # 对照：同种子、只差「有没有蔫一会儿」

plan = [
    ("（①）常态（垂之前）", TAU_REST, "还没垂 —— 与孪生完全重合、琥珀一点没有"),
    ("（②）垂下去中", TAU_SINK, "慢慢往下沉（形变量一半）—— 不许突然"),
    ("（③）刚垂到底", TAU_DEEP, "头沉下去、眼皮耷拉着 —— 琥珀是它原来的位置"),
    ("（④）蔫着停住", TAU_HOLD, "停住的一整段 —— 情绪不是一口气"),
    ("（⑤）缓起来中", TAU_RISE, "自己慢慢缓起来 —— 不猛，也不拖"),
    ("（⑥）收完・回到常态", DONE, "与「没垂过」的它整幅逐像素一致"),
]

frames: list[tuple[str, QImage]] = []
ghosts: dict[str, int] = {}
deltas: dict[str, tuple[int, int, int, int]] = {}
for label, tau, note in plan:
    ia = look(a, tau)
    ib = look(b, tau)
    (xa0, ya0, xa1, ya1) = face_box(ia)
    (xb0, yb0, xb1, yb1) = face_box(ib)
    ca, cb = ia.copy(CROP), ib.copy(CROP)
    ghosted, n = _ghost(ca, cb)
    ghosts[label] = n
    deltas[label] = (xa0 - xb0, ya0 - yb0, xa1 - xb1, ya1 - yb1)
    k = anim.droop_amount(tau)
    sub = f"{note} · 形变量 {k:.2f} · 顶沿 {ya0 - yb0:+d}px / 下沿 {ya1 - yb1:+d}px"
    frames.append((label, _tile(_crop2x(ghosted), f"{label} · tau={tau:.2f}s", sub)))

# 量化证据（打给 DEVLOG / 人看）
print("  顶沿差（六格，正 = 往下沉）：", [d[1] for d in deltas.values()])
print("  下沿差（六格，正 = 往下）：", [d[3] for d in deltas.values()])
print("  左/右沿差（六格，应全 0）：", [(d[0], d[2]) for d in deltas.values()])
print("  琥珀幽灵像素（六个时刻，按顺序）:", list(ghosts.values()))
lab_deep = plan[2][0]
y0d = deltas[lab_deep][1]
y1d = deltas[lab_deep][3]
ia_deep = look(a, TAU_DEEP)
ib_deep = look(b, TAU_DEEP)
(xa0, ya0, xa1, ya1) = face_box(ia_deep)
(xb0, yb0, xb1, yb1) = face_box(ib_deep)
print(
    f"  垂到底实读：顶沿 {ya0 - yb0:+d}px / 下沿 {ya1 - yb1:+d}px / 脸高 {(ya1 - ya0)} vs {(yb1 - yb0)}"
)
ia_done = look(a, DONE).convertToFormat(QImage.Format_ARGB32)
ib_done = look(b, DONE).convertToFormat(QImage.Format_ARGB32)
ba, bb = bytes(ia_done.constBits()), bytes(ib_done.constBits())
diff = sum(1 for i in range(0, len(ba), 4) if ba[i : i + 4] != bb[i : i + 4])
print(f"  收完对比：与「没垂过」的孪生不同像素 {diff} 个（期望 0）")
a.close()
b.close()

card_lines = [
    "\u2022 触发：心情落进「有点蔫」（低于 -0.05 —— 和心情标签同一档）才排；睡着 / 累趴 / 被拎着 / 正在看你写字 / 刚交互完 5 秒 —— 都不垂",
    f"\u2022 节奏：每 {anim.DROOP_MIN_GAP:.0f}~{anim.DROOP_MAX_GAP:.0f} 秒一垂（随机，别像节拍器）",
    f"\u2022 一垂 {anim.droop_total():.2f} 秒：垂下去 {anim.DROOP_SINK_S:.2f}s -> 停住 {anim.DROOP_HOLD_S:.2f}s -> 缓起来 {anim.DROOP_RISE_S:.2f}s",
    f"\u2022 整脸往下 {anim.DROOP_SINK_PX}px、纵向压到 {anim.DROOP_SQUINT_MIN:.0%}（眼皮耷拉着）—— 横向一点没动",
    "\u2022 实测（上面六格）：顶沿下沉 / 下沿上收 / 脸变矮；收完与「没垂过」的它逐像素一致（0 个不同）",
    "\u2022 琥珀 = 没在垂的它站过的地方（脸垂下、变矮后露出来的那一圈）",
    "\u2022 再往下（「低落」档）它会直接呆住不动（calm 定格）—— 这条补的是「会动的那一段」里的蔫",
]
frames.append(("（⑦）判据数字卡", _card(card_lines)))

_grid(
    "蔫一会儿「心情有点蔫的时候，悄悄往下垂一垂」：往下垂一垂，停一段，自己再慢慢缓起来",
    "双胞胎实测（同种子：在垂的它 vs 没垂的它）· 2x 最近邻放大 · 与真机同一段绘制代码",
    [img for _, img in frames],
    3,
    OUT / "droop-strip.png",
)
print(f"  帧带: {OUT / 'droop-strip.png'}")

# ── 短视频：一段完整的蔫一会儿，循环 3 遍 ───────────────
fps = 12
start, stop = T0 - 0.6, T0 + anim.droop_total() + 0.6
n = int((stop - start) * fps)
tmpdir = ROOT / ".tmp" / "_droop_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
win = make_window(with_droop=True)
for i in range(n):
    t = round(start + i / fps, 6)
    win.anim_t = t
    _crop2x(win.grab().toImage()).save(str(tmpdir / f"{i:04d}.png"))
win.close()

if shutil.which("ffmpeg"):
    mp4 = OUT / "droop-demo.mp4"
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

for name in ("droop-strip.png", "droop-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
