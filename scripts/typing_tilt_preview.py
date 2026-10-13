#!/usr/bin/env python3
"""好奇歪头素材 ——「你写的时候，歪着脑袋看你在写什么」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- typing-tilt-strip.png  7 格（脸部 2x 最近邻放大）：还没写 -> 写起来了（视线落到
                        输入框）-> 第一下歪到满（左）-> 收尾中 -> 第二下（换边，右）
                        -> 收完（与对照逐像素一致）+ 判据数字卡
- typing-tilt-demo.mp4   从「你开始写」到第一下歪完的连续段（12fps，循环 3 遍）

用法:
    .venv/bin/python scripts/typing_tilt_preview.py

纪律（和 tilt_preview 一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_typing_tilt.py 同一个）；
- 画面走**真绘制代码**（真窗口真 grab），排期也走**真链路**（写输入框 → textChanged
  → 动画层），不是拼图；
- 对照 = 同种子、同喂法、只有「不会歪」一个差别的孪生（tilt 空转）——
  琥珀 = 没歪的它站过的地方、天蓝 = 歪过去新占的地方；
- 检测一律按 faces.LIT 常量；放大一律最近邻；ffmpeg 不在就只出帧带并说明；
- 顺手把「两下之间的间隔 / 主轴角差 / 幽灵像素数 / 收完差没差」打出来
  （DEVLOG 引它当证据）。
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import sys
import time
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
SEED = 7  # 和 tests/test_typing_tilt.py 一家的种子（窗口里的随机都钉死）
T0 = 6.0  # 「你开始写字」在时间轴上的时刻
CROP = QRect(146, 2, 508, 248)  # 脸的裁剪区（盖住下看 + 满幅旋转的四个角，有断言）
SCAN = QRect(120, 0, 580, 238)  # 找脸部亮像素的范围（避开状态行与关闭钮）
ZOOM = 2  # 帧带 / 视频放大倍数
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：没歪的它站过的地方
SKY = QColor(90, 167, 200)  # 天蓝：歪过去新占的地方

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window() -> SammyWindow:
    """稳态窗口：普通脸、状态行「在线」—— 只留「写字会话」一个变量。"""
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED)
    win.look_on = False  # 光标不参与（盯的是写字这一件事）
    win.set_expression(2)  # 普通脸
    win._idle_face = None
    win.drives.asleep = False
    win.drives.energy = 0.8
    win.drives.boredom = 0.2
    win.drives.closeness = 0.5
    win.drives.last_update = time.time() + 10_000.0  # 冻结驱力漂移（素材不是它的一天）
    win.status = drives.status_text(win.drives)
    win.my_line = ""
    win.sammy_line = ""
    win.anim_t = T0
    # 素材脚本不碰真状态：关窗时的保存全换成空操作
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
    """clip 里所有亮像素的外接框 —— 下看 + 满幅旋转的四个角必须落在 CROP 里。"""
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
    """双色幽灵：琥珀 = 孪生站过而它没占的；天蓝 = 它新占的。"""
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
    p.drawText(18, 34, "判据数字卡（与 tests/test_typing_tilt.py 同口径）")
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


# ── 主流程：真排期推进 + 六格采样 ────────────────────
a = make_window()
b = make_window()


def _no_tilt(at: float) -> None:
    """对照的它：同种子、同喂法，唯独不会歪。"""


b.anim.tilt = _no_tilt


def _clean_at(tt: float, tries: int = 20) -> float:
    """从 tt 起找一个两边都不眨眼的时刻（量主轴角要干净的脸）。"""
    for _ in range(tries):
        if a.anim.frame_at(tt).squash == 1.0 and b.anim.frame_at(tt).squash == 1.0:
            return tt
        tt = round(tt + 0.05, 6)
    raise AssertionError("找不到干净采样时刻")


def _snap_pair(tt: float):
    """在已知干净的 tt 抓两边 + 双色幽灵 + 主轴角差。"""
    ia = look(a, tt)
    ib = look(b, tt)
    g, n_amb, n_sky = _ghost(ia.copy(CROP), ib.copy(CROP))
    da, _c, _n = moment_angle(ia, SCAN)
    db, _c2, _n2 = moment_angle(ib, SCAN)
    return tt, g, n_amb, n_sky, da - db, ia, ib


# (1) 还没写：喂之前先抓（两边逐像素重合）
t1 = _clean_at(T0 - 0.4)
snaps = {"f1": _snap_pair(t1)}
print(
    f"  (1) 还没写：主轴角差 {snaps['f1'][4]:+.2f} 度 · 琥珀 {snaps['f1'][2]} 天蓝 {snaps['f1'][3]}（期望全 0）"
)

# 写字会话：从 T0 起每 2 秒一个键（走真信号链），排期真推进。
# 采样「到点就抓」—— 歪头通道只记最近一下，走过了可就再也抓不到前面那一下了
wants: list[dict] = [{"key": "f2", "t": T0 + 0.9, "taken": False}]
live: dict = {}
fires: list[float] = []
last = a.anim._tilt_at
next_feed = T0
fed = 0
t = round(t1, 6)
while t <= T0 + 45.0:
    t = round(t + 0.02, 6)
    a.anim_t = b.anim_t = t
    if t >= next_feed - 1e-9:
        fed += 1
        a.input.setText(f"我在写第 {fed} 句")
        b.input.setText(f"我在写第 {fed} 句")
        next_feed = T0 + 2.0 * fed
    a.anim.frame_at(t)
    b.anim.frame_at(t)
    if a.anim._tilt_at != last:
        fires.append(a.anim._tilt_at)
        last = a.anim._tilt_at
        if len(fires) == 1:
            wants.append(
                {
                    "key": "f3",
                    "t": fires[0] + anim.TILT_RISE_S + anim.TILT_HOLD_S / 2,
                    "taken": False,
                }
            )
            wants.append(
                {
                    "key": "f4",
                    "t": fires[0] + anim.TILT_RISE_S + anim.TILT_HOLD_S + anim.TILT_FALL_S / 2,
                    "taken": False,
                }
            )
        elif len(fires) == 2:
            wants.append(
                {
                    "key": "f5",
                    "t": fires[1] + anim.TILT_RISE_S + anim.TILT_HOLD_S / 2,
                    "taken": False,
                }
            )
            wants.append({"key": "f6", "t": fires[1] + anim.tilt_total() + 0.4, "taken": False})
    for w in wants:
        if not w["taken"] and t >= w["t"] - 1e-9:
            fa = a.anim.frame_at(t)
            fb = b.anim.frame_at(t)
            if fa.squash == 1.0 and fb.squash == 1.0:
                w["taken"] = True
                live[w["key"]] = fa  # 当时的帧：歪头通道只记最近一下，事后重算不作数
                snaps[w["key"]] = _snap_pair(t)
            break  # 一帧最多采一个：下一格通常还在后头
    if (
        len(fires) >= 2
        and all(w["taken"] for w in wants)
        and t > fires[1] + anim.tilt_total() + 0.4
    ):
        break

assert len(fires) >= 2, f"排期没歪够两下：{fires}"
assert all(w["taken"] for w in wants), "有格子没采到"
T1, T2 = fires[0], fires[1]
print(f"  排期：第一下在 T0+{T1 - T0:.2f}s · 第二下与第一下隔 {T2 - T1:.2f}s（区间 12~24）")

# (2)..(6) 复核几个关键量
t2 = snaps["f2"][0]
assert live["f2"].gy == anim.TYPING_GAZE_Y, "格 2 的视线不在输入框"
t3 = snaps["f3"][0]
f3 = live["f3"]
assert f3.gy == anim.TYPING_GAZE_Y, "格 3 歪的时候不在看你写"
assert f3.tilt < 0, f"格 3 该左半边沉（t={t3}，tilt={f3.tilt}）"
x0, y0, x1, y1 = lit_bbox(snaps["f3"][5], SCAN)
assert CROP.adjusted(-4, -4, 4, 4).contains(QRect(x0, y0, x1 - x0, y1 - y0)), (
    f"满幅旋转的角跑到裁剪区外了: {(x0, y0, x1, y1)} vs {CROP}"
)
print(
    f"  满幅亮像素外接框：x {x0}..{x1} / y {y0}..{y1}"
    f"（裁剪区 {CROP.x()}..{CROP.right()} / {CROP.y()}..{CROP.bottom()}）"
)
assert live["f5"].tilt > 0, "格 5 该换边（右半边沉）"
t6 = snaps["f6"][0]
ia6, ib6 = snaps["f6"][5], snaps["f6"][6]
ba = bytes(ia6.constBits())
bb = bytes(ib6.constBits())
diff = sum(1 for i in range(0, len(ba), 4) if ba[i : i + 4] != bb[i : i + 4])
assert diff == 0, f"收完还有 {diff} 个像素对不上"
print(f"  收完对比：与「不会歪的它」不同像素 {diff} 个（期望 0）")

keys = ("f1", "f2", "f3", "f4", "f5", "f6")
print("  六格主轴角差：" + " / ".join(f"{k} {snaps[k][4]:+.2f}" for k in keys))
print("  六格幽灵（琥珀 / 天蓝）：" + " / ".join(f"{k} {snaps[k][2]}/{snaps[k][3]}" for k in keys))

frames = [
    ("[1] 还没写：四处看", "f1", "视线还在发呆 —— 与对照完全重合"),
    ("[2] 写起来了：看着你写", "f2", "视线收下去、落到输入框 —— 还没歪"),
    ("[3] 第一下・歪到满", "f3", "左半边沉 —— 琥珀 / 天蓝两圈月牙"),
    ("[4] 收尾中", "f4", "从当前角度缓回来 —— 不突然停"),
    ("[5] 第二下（换边）", "f5", "右半边沉 —— 方向一次一换"),
    ("[6] 收完・还在看你写", "f6", "与「不会歪的它」整幅逐像素一致"),
]
panels = []
for label, key, note in frames:
    tt, g, n_amb, n_sky, d, _ia, _ib = snaps[key]
    sub = f"{note} · 主轴角差 {d:+.2f} 度 · 琥珀 {n_amb} 天蓝 {n_sky}"
    panels.append(_tile(_crop2x(g), f"{label} · tau={tt - T0:+.2f}s", sub))

card_lines = [
    "\u2022 触发：你在输入框里写字（「看着你写」）—— 第一下 1.5~3 秒内就来",
    "\u2022 节奏：一直写就一直排 —— 本素材第二下隔了 %.1f 秒（区间 12~24 秒随机）" % (T2 - T1),
    "\u2022 形状：复用歪头那条（0.25 + 0.55 + 0.45 = 1.25 秒、±5 度、绕脸中心转）",
    "\u2022 让位：光标刚指过 / 停手 / 发送 —— 排期让位或者作废",
    "\u2022 琥珀 = 没歪的它站过的地方；天蓝 = 歪过去新占的地方",
    "\u2022 收完（格 6）：与「不会歪的它」整幅逐像素一致（0 个不同）",
    "\u2022 真脸主轴角差读数会啃掉一点边缘（阈值量法），方向与量级对上即算过",
]
panels.append(_tile(_card(card_lines), "(7) 判据数字卡", "同口径：tests/test_typing_tilt.py"))

_grid(
    "好奇歪头「你写的时候，歪着脑袋看你在写什么」：写字会话里轻转 5 度再回来",
    "双胞胎实测（同种子、同喂法：会歪的它 vs 不会歪的它）· 2x 最近邻放大 · 与真机同一段绘制代码",
    panels,
    3,
    OUT / "typing-tilt-strip.png",
)
print(f"  帧带: {OUT / 'typing-tilt-strip.png'}")

# ── 短视频：从「开始写」到第一下歪完（12fps，循环 3 遍）──
fps = 12
start, stop = T0, round(T1 + anim.tilt_total() + 1.2, 6)
n = int((stop - start) * fps) + 1
tmpdir = ROOT / ".tmp" / "_typing_tilt_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
for i in range(n):
    t = round(start + i / fps, 6)
    _crop2x(look(a, t)).save(str(tmpdir / f"{i:04d}.png"))

if shutil.which("ffmpeg"):
    mp4 = OUT / "typing-tilt-demo.mp4"
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

a.close()
b.close()

for name in ("typing-tilt-strip.png", "typing-tilt-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
