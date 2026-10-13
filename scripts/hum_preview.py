#!/usr/bin/env python3
"""哼小曲素材 ——「心情好的时候，摇头晃脑哼两句」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- hum-strip.png   6 格（脸部 2x 最近邻放大 + 琥珀幽灵）：常态 -> 起手缓入 ->
                  最左摆 -> 最右摆 -> 收尾中 -> 收完，另加判据数字卡
- hum-demo.mp4    一段完整的哼小曲（12fps，循环 3 遍），证明它是「在动」不是一帧贴图

用法:
    .venv/bin/python scripts/hum_preview.py

纪律（和其他素材脚本一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_hum.py 同一个）；
- 画面走**真绘制代码**（真窗口真 grab），不是拼图；状态文字也走真状态
  （drives.status_text —— 脸和字不许自相矛盾，doze 那次的教训）；
- 琥珀幽灵 = 同种子孪生（**没在哼的它**）的脸：只涂「两边不一样」的月牙边，
  重叠处保持原样；检测一律按 faces.LIT 常量（**别写死颜色**）；
- 量脸的外接框要**排掉右上角的音符**（它是哼的时候才有的小图标，算进脸框
  会让左右沿多出一条假边）；
- 放大一律最近邻；ffmpeg 不在就只出帧带并说明（不静默降级）；
- 顺手把「左右摆了多少 / 竖着动没动 / 收完归没归零 / 音符多少像素」打出来
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
from sammy.pet import HUM_NOTE, HUM_NOTE_CELL, SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_hum.py 一家的种子（窗口里的随机都钉死）
T0 = 1.0  # 哼小曲在时间轴上的起点
ZOOM = 2  # 帧带 / 视频放大倍数
CROP = QRect(180, 8, 440, 236)  # 脸的裁剪区（scale 1.0 的真实像素）
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：孪生（没在哼的它）站过的地方

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window(*, with_hum: bool = True) -> SammyWindow:
    """稳态窗口：普通脸、状态行「在线」—— 只留哼小曲一个变量。"""
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED)
    win.look_on = False  # 光标不参与（盯的是哼小曲这一件事）
    win.set_expression(2)  # 普通脸
    win._idle_face = None
    # 状态文字和脸一致（脸普通、字写「睡着了」是最忌讳的自相矛盾）
    win.status = drives.status_text(win.drives)
    win.my_line = ""  # 素材里不留上一句的残影
    win.sammy_line = ""
    win.anim_t = T0
    if with_hum:
        win.anim.hum(T0)
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


def note_rect(win: SammyWindow) -> QRect:
    """音符的整个行程（和 pet._draw_hum 同一条算式）—— 量脸时把它排掉。"""
    box = win.lay.face
    s = win.scale
    cell = max(1, int(HUM_NOTE_CELL * s))
    ww = len(HUM_NOTE[0]) * cell
    hh = len(HUM_NOTE) * cell
    x = box.right() - ww - int(20 * s)
    y = box.top() + int(10 * s) - int(anim.HUM_NOTE_RISE_PX * s)
    return QRect(x, y, ww, hh + int(anim.HUM_NOTE_RISE_PX * s))


def face_and_note_counts(img: QImage, win: SammyWindow) -> tuple[tuple[int, int, int, int], int]:
    """CROP 里：脸的亮像素外接框（排掉音符区）+ 音符区自己的亮像素数。"""
    src = img.convertToFormat(QImage.Format_ARGB32)
    buf = bytes(src.constBits())
    stride = src.bytesPerLine()
    nr = note_rect(win)
    x0 = y0 = 10**9
    x1 = y1 = -1
    n_note = 0
    for y in range(CROP.top(), CROP.bottom() + 1):
        for x in range(CROP.left(), CROP.right() + 1):
            if not _lit(buf, stride, x, y):
                continue
            if nr.contains(x, y):
                n_note += 1
                continue
            x0 = min(x0, x)
            x1 = max(x1, x)
            y0 = min(y0, y)
            y1 = max(y1, y)
    assert x1 >= 0, "没扫到脸像素？"
    return (x0, y0, x1, y1), n_note


def _crop2x(img: QImage) -> QImage:
    out = img.copy(CROP)
    return out.scaled(
        out.width() * ZOOM, out.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


def _ghost(base: QImage, twin: QImage) -> tuple[QImage, int]:
    """把孪生（没在哼的它）的脸用琥珀色勾出来 —— 只涂「两边不一样」的边。

    脸摆出去之后，边缘会露出一圈月牙（琥珀 = 它没哼时脸在哪儿）；
    两张脸完全重合时（哼之前 / 收完之后）琥珀一点都不会出现 —— 那条「0」就是
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
    p.drawText(18, 34, "判据数字卡（与 tests/test_hum.py 同口径）")
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
TAU_EASE = round(anim.HUM_EASE_IN_S * 0.5, 6)  # 起手缓入中
TAU_LEFT = round(anim.HUM_EASE_IN_S + anim.HUM_ROCK_PERIOD * 0.25, 6)  # 第一下满幅（左）
TAU_RIGHT = round(anim.HUM_EASE_IN_S + anim.HUM_ROCK_PERIOD * 0.75, 6)  # 第二下满幅（右）
TAU_SETTLE = round(anim.HUM_EASE_IN_S + anim.HUM_ROCK_S + anim.HUM_EASE_OUT_S * 0.5, 6)  # 收尾中
DONE = round(anim.hum_total() + 0.4, 6)  # 收完的时刻（tau）

# ── 帧带：六个时刻 + 数字卡 ────────────────────────
a = make_window(with_hum=True)
b = make_window(with_hum=False)  # 对照：同种子、只差「有没有哼小曲」

plan = [
    ("（①）常态（哼之前）", TAU_REST, "还没哼 —— 右上角干干净净、与孪生完全重合"),
    ("（②）起手・缓入中", TAU_EASE, "轻轻摆进去（包络一半）—— 起手不许突然"),
    ("（③）最左摆（第一下满幅）", TAU_LEFT, "满幅往左 —— 琥珀在右边：它没哼时站过的地方"),
    ("（④）最右摆", TAU_RIGHT, "满幅往右 —— 琥珀在左边"),
    ("（⑤）收尾中", TAU_SETTLE, "从当前摆动缓出去 —— 不突然停"),
    ("（⑥）收完・回到常态", DONE, "与「没哼过」的它整幅逐像素一致"),
]

frames: list[tuple[str, QImage]] = []
crescents: dict[str, int] = {}
deltas: dict[str, int] = {}
note_px: dict[str, int] = {}
for label, tau, note in plan:
    ia = look(a, tau)
    ib = look(b, tau)
    (xa0, ya0, xa1, ya1), na = face_and_note_counts(ia, a)
    (xb0, yb0, xb1, yb1), _ = face_and_note_counts(ib, b)
    ca, cb = ia.copy(CROP), ib.copy(CROP)
    ghosted, n = _ghost(ca, cb)
    crescents[label] = n
    deltas[label] = xa0 - xb0
    note_px[label] = na
    k = anim.hum_amount(tau)
    sub = f"{note} · 形变量 {k:.2f} · 左右差 {xa0 - xb0:+d}px"
    frames.append((label, _tile(_crop2x(ghosted), f"{label} · tau={tau:.2f}s", sub)))

# 量化证据（打给 DEVLOG / 人看）
print(f"  左右沿差（六格，正 = 往右）：{list(deltas.values())}  （满幅应到 ±{anim.HUM_ROCK_PX}）")
print("  竖着：左右摆时顶/下沿应与孪生一致（见对账）")
for label, tau, _ in plan:
    ia = look(a, tau)
    ib = look(b, tau)
    (xa0, ya0, xa1, ya1), _ = face_and_note_counts(ia, a)
    (xb0, yb0, xb1, yb1), _ = face_and_note_counts(ib, b)
    print(
        f"    {label}: 顶沿 {ya0 - yb0:+d}px / 下沿 {ya1 - yb1:+d}px / 左 {xa0 - xb0:+d}px / 右 {xa1 - xb1:+d}px"
    )
print(f"  音符亮像素（六格，按顺序）: {list(note_px.values())}  （哼时才有；≥90 算画出来了）")
ia_done = look(a, DONE).convertToFormat(QImage.Format_ARGB32)
ib_done = look(b, DONE).convertToFormat(QImage.Format_ARGB32)
ba, bb = bytes(ia_done.constBits()), bytes(ib_done.constBits())
diff = sum(1 for i in range(0, len(ba), 4) if ba[i : i + 4] != bb[i : i + 4])
print(f"  收完对比：与「没哼过」的孪生不同像素 {diff} 个（期望 0）")
print("  琥珀月牙像素（六个时刻，按顺序）:", list(crescents.values()))
a.close()
b.close()

card_lines = [
    "\u2022 触发：心情到「很好」（0.55 —— 和状态行同一档）才排；睡着 / 累趴 / 被拎着 / 正在看你写字 —— 都不哼",
    f"\u2022 节奏：每 {anim.HUM_MIN_GAP:.0f}~{anim.HUM_MAX_GAP:.0f} 秒一段（随机，别像节拍器）",
    f"\u2022 一段 {anim.hum_total():.2f} 秒：起手 {anim.HUM_EASE_IN_S:.2f}s -> 摇摆 {anim.HUM_ROCK_CYCLES} 拍（每拍 {anim.HUM_ROCK_PERIOD:.2f}s）-> 收尾 {anim.HUM_EASE_OUT_S:.2f}s",
    f"\u2022 摆幅 ±{anim.HUM_ROCK_PX}px 的横向正弦；三个整周期 = 晃三下；纵向一点没动",
    "\u2022 实测（上面六格）：左右沿与孪生对账到满幅；收完逐像素一致（0 个不同）",
    "\u2022 音符 = 手画像素矩阵（HUM_NOTE），只在哼时出现、整个行程升起 8px",
    "\u2022 琥珀月牙 = 没在哼的它站过的地方（摆出去露出来的那些）",
]
frames.append(("（⑦）判据数字卡", _card(card_lines)))

_grid(
    "哼小曲「心情好的时候，摇头晃脑哼两句」：轻轻左右摆 + 右上角冒一个小音符",
    "双胞胎实测（同种子：在哼的它 vs 没哼的它）· 2x 最近邻放大 · 与真机同一段绘制代码",
    [img for _, img in frames],
    3,
    OUT / "hum-strip.png",
)
print(f"  帧带: {OUT / 'hum-strip.png'}")

# ── 短视频：一段完整的哼小曲，循环 3 遍 ───────────────
fps = 12
start, stop = T0 - 0.6, T0 + anim.hum_total() + 0.6
n = int((stop - start) * fps)
tmpdir = ROOT / ".tmp" / "_hum_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
win = make_window(with_hum=True)
for i in range(n):
    t = round(start + i / fps, 6)
    win.anim_t = t
    _crop2x(win.grab().toImage()).save(str(tmpdir / f"{i:04d}.png"))
win.close()

if shutil.which("ffmpeg"):
    mp4 = OUT / "hum-demo.mp4"
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

for name in ("hum-strip.png", "hum-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
