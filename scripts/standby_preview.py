#!/usr/bin/env python3
"""待机省电素材 ——「你走了，屏幕慢慢暗下去；你回来，亮回来」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- standby-strip.png  六格（整窗 1x）：你还在（与对照重合）-> 你走了（暗下去半路）
                     -> 全暗（省电中，它还在呼吸）-> 你回来（亮回来半路 + 抬头）
                     -> 全亮（与对照逐像素一致）+ 判据数字卡
- standby-demo.mp4   从「你走了」到「亮回来」的连续段（30fps，循环 3 遍）

用法:
    .venv/bin/python scripts/standby_preview.py

纪律（和 welcome_preview 一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_standby.py 同一个）；
- 触发走**真链路**（光标静十分钟，_note_presence 安上「你走了」，_standby_step
  喂 away 电平），画面走**真绘制代码**（真窗口真 grab），不是摆拍；
- 对照 = 同种子、同喂法、只有「不会暗」一个差别的孪生（_standby_step 空转）——
  幽灵是**亮度版**：琥珀 = 对照比它亮（被蒙住的地方）、天蓝 = 它比对照亮（期望 0）；
- 检测按比例对账；ffmpeg 不在就只出帧带并说明；
- 顺手把「半程档位 / 暗到底用时 / 全暗比例 / 输入框是否也被蒙到 / 收尾差没差」
  打出来（DEVLOG 引它当证据）。
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

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import anim, layout, standby
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_standby.py 一家的种子（窗口里的随机都钉死）
T0 = 12.0  # 「你走了」那一刻在时间轴上的目标时刻
DT = anim.ANIM_DT  # 30fps 的帧长
FADE_N = math.ceil(standby.STANDBY_FADE_S / DT)  # 暗到全暗的帧数
RISE_N = math.ceil(standby.STANDBY_RISE_S / DT)  # 亮回来的帧数
HOLD_N = round(1.0 / DT)  # 全暗之后再看它呼吸一秒
TAIL_N = round(0.5 / DT)  # 亮回来之后再收半秒
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：对照（亮的）占着、它（暗的）让出来的地方
SKY = QColor(90, 167, 200)  # 天蓝：它比对照亮的地方（期望一直是 0）

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window() -> SammyWindow:
    """稳态窗口：只留「待机省电」一个变量（光标走假光标，全在脚本控制里）。"""
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win._sync_crt_layer()
    win._sync_dim_overlay()
    win.anim = anim.Animator(seed=SEED, blink_gap=(600.0, 600.0))
    win.set_expression(2)  # 普通脸：画面里动的只有呼吸 / 漂移
    win.finish_typing()
    win.my_line = ""
    win.sammy_line = ""
    win.anim_on = True
    win.look_on = True
    # 素材脚本不碰真状态：关窗时的保存全换成空操作
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(win, name, lambda: None)
    win.show()
    return win


class FakeCursor:
    """可拖动的假光标：位置用「相对脸中心」的设备像素表示（和真窗口同一套换算）。"""

    def __init__(self, win: SammyWindow):
        self.win = win
        self.dx = -400.0
        self.dy = 0.0

    def __call__(self):
        c = self.win.lay.face.center()
        s = self.win.scale
        lx = (c.x() + self.dx) * s + self.win._offset[0]
        ly = (c.y() + self.dy) * s + self.win._offset[1]
        return self.win.mapToGlobal(QPoint(round(lx), round(ly)))


def _bytes(img: QImage) -> tuple[bytes, int]:
    src = img.convertToFormat(QImage.Format_RGB32)
    return bytes(src.constBits()), src.bytesPerLine()


def _diff_pixels(ia: QImage, ib: QImage) -> int:
    ba, sa = _bytes(ia)
    bb, sb = _bytes(ib)
    assert ia.width() == ib.width() and ia.height() == ib.height()
    n = 0
    for y in range(ia.height()):
        ra, rb = y * sa, y * sb
        for x in range(ia.width()):
            i = x * 4
            if ba[ra + i : ra + i + 4] != bb[rb + i : rb + i + 4]:
                n += 1
    return n


def _ratio(dim: QImage, ref: QImage, clip: QRect, floor: int = 120) -> tuple[float, int]:
    """以对照（ref）为准挑亮像素，量 dim 里它们变暗的比例（期望 1 - DIM_MAX）。"""
    bd, sd = _bytes(dim)
    br, sr = _bytes(ref)
    vals = []
    for y in range(clip.top(), clip.bottom() + 1):
        for x in range(clip.left(), clip.right() + 1):
            i = x * 4
            rg = br[y * sr + i + 1]
            dg = bd[y * sd + i + 1]
            if rg >= floor:
                vals.append(dg / rg)
    assert len(vals) >= 100, f"亮像素太少（{len(vals)}）—— 区域选错了？"
    return sum(vals) / len(vals), len(vals)


def _ghost_bright(dim: QImage, ref: QImage, thresh: int = 24) -> tuple[QImage, int, int]:
    """亮度版幽灵：琥珀 = 对照比它亮（被蒙住的地方）；天蓝 = 它比对照亮（期望 0）。"""
    out = dim.convertToFormat(QImage.Format_RGB32)
    bd, sd = _bytes(dim)
    br, sr = _bytes(ref)
    p = QPainter(out)
    pen_a = QColor(AMB)
    pen_a.setAlpha(170)
    pen_s = QColor(SKY)
    pen_s.setAlpha(170)
    n_amb = n_sky = 0
    for y in range(out.height()):
        for x in range(out.width()):
            i = x * 4
            dg = bd[y * sd + i + 1]
            rg = br[y * sr + i + 1]
            if rg - dg >= thresh:
                p.setPen(pen_a)
                p.drawPoint(x, y)
                n_amb += 1
            elif dg - rg >= thresh:
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
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setPen(TITLE)
    p.setFont(QFont("", 15))
    p.drawText(18, 40, "判据数字卡（与 tests/test_standby.py 同口径）")
    p.setFont(QFont("", 12))
    y = 80
    for line in lines:
        p.setPen(TITLE if line.startswith("\u2022") else SUB)
        p.drawText(18, y, line)
        y += 26
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


# ── 主流程：真链路（光标静十分钟 -> _note_presence -> _standby_step）──
a = make_window()
b = make_window()
b._standby_step = lambda: None  # 对照：不会暗的它（唯一的差别）
cur_a = FakeCursor(a)
cur_b = FakeCursor(b)
a._cursor_now = cur_a
b._cursor_now = cur_b

# 热身 + 建立光标参照（两窗同一步数，保持随机流对称）
a.anim_t = b.anim_t = round(T0 - 3.0, 6)
cur_a.dx = cur_b.dx = -400.0
for _ in range(6):
    a._anim_tick()
    b._anim_tick()

# 「你走了」：把「最近一次有人碰鼠标」往回拨十分钟（真链路里由窗口自己安上）
a._presence_at = a.anim_t - (anim.WELCOME_AWAY_S + 1.0)
b._presence_at = b.anim_t - (anim.WELCOME_AWAY_S + 1.0)

frames: list[QImage] = []  # a 的整窗图（短视频）
shots: dict[str, tuple[QImage, QImage]] = {}  # 关键帧的（它, 对照）
lv_track: list[float] = []  # 每帧档位（对时间线对数用）


def tick_pair() -> tuple[QImage, QImage]:
    """走一帧，两个窗口都在这一帧里画一次（和真机事件循环对称 —— 帧数不对称
    的话，两边的凝视缓动进度会岔开，对账会量到假的差；m4 上实测踩过）。"""
    a._anim_tick()
    b._anim_tick()
    return a.grab().toImage().copy(), b.grab().toImage().copy()


ia, ib = tick_pair()
t_arm = a.anim_t
assert a._away and b._away, "前提不成立：没安上「你走了」"
assert a._dim_overlay.level() == 0.0, "刚走就暗了？它是慢慢沉的"
frames.append(ia)
shots["m1"] = (ia, ib)
lv_track.append(a._dim_overlay.level())
print(f"  触发：「你走了」在 T0={t_arm:.3f}（真链路，光标静了十分钟）")

for i in range(1, FADE_N + HOLD_N + 1):
    ia, ib = tick_pair()
    frames.append(ia)
    lv_track.append(a._dim_overlay.level())
    if i == round(FADE_N / 2):
        shots["m2"] = (ia, ib)
        print(f"  (2) 半程：档位 {a._dim_overlay.level():.4f}（期望约 0.5）")
    if i == FADE_N + HOLD_N:
        shots["m3"] = (ia, ib)
assert a._dim_overlay.level() == 1.0, "没暗到全暗"
n_full = lv_track.index(1.0)
print(
    f"  暗到全暗：第 {n_full} 帧（{n_full * DT:.2f}s，期望 {standby.STANDBY_FADE_S}s）；"
    f"再停 {HOLD_N * DT:.1f}s 看它呼吸"
)

# 「你回来了」：光标动了（真链路：欢迎回来 + 屏幕亮回来）
cur_a.dx = cur_b.dx = -360.0
ia, ib = tick_pair()
t_fire = a.anim_t
assert a.anim._welcome_at == t_fire, "真链路没触发「欢迎回来」"
frames.append(ia)
lv_track.append(a._dim_overlay.level())
print(f"  你回来了：T1={t_fire:.3f}（欢迎回来同拍；屏幕 {standby.STANDBY_RISE_S}s 亮回来）")

for i in range(1, RISE_N + TAIL_N + 1):
    ia, ib = tick_pair()
    frames.append(ia)
    lv_track.append(a._dim_overlay.level())
    if i == round(RISE_N / 2):
        shots["m4"] = (ia, ib)
        print(f"  (4) 亮回来半路：档位 {a._dim_overlay.level():.4f}（期望约 0.5）")
    if i == RISE_N + TAIL_N:
        shots["m5"] = (ia, ib)
assert a._dim_overlay.level() == 0.0, "没亮回来"
n_back = next(i for i in range(1 + FADE_N + HOLD_N, len(lv_track)) if lv_track[i] == 0.0) - (
    1 + FADE_N + HOLD_N
)
print(f"  亮回来用了 {n_back} 帧（{n_back * DT:.2f}s，期望 {standby.STANDBY_RISE_S}s）")

# ── 判据对账（数字都打出来当证据）──
ia1, ib1 = shots["m1"]
d1 = _diff_pixels(ia1, ib1)
assert d1 == 0, f"「你还没走」就跟对照对不上（{d1} 像素）"
print(f"  (1) 你还没走：与对照不同像素 {d1} 个（期望 0）")

ia3, ib3 = shots["m3"]
face_clip = QRect(a.lay.face.left() - 60, 4, a.lay.face.width() + 120, 236)
r_face, n_face = _ratio(ia3, ib3, face_clip)
inp = a.lay.input
r_in, n_in = _ratio(ia3, ib3, QRect(inp.left(), inp.top(), inp.width(), inp.height()))
want = 1.0 - standby.STANDBY_DIM_MAX
print(
    f"  (3) 全暗：脸部亮像素 {n_face} 个、比例 {r_face:.4f}（期望 {want}）；"
    f"输入框里的字 {n_in} 个、比例 {r_in:.4f}"
)
assert abs(r_face - want) <= 0.03, f"脸部比例对不上：{r_face}"
assert abs(r_in - want) <= 0.04, f"输入框比例对不上：{r_in}"

c0 = ia1.convertToFormat(QImage.Format_ARGB32).pixelColor(4, 4)
c3 = ia3.convertToFormat(QImage.Format_ARGB32).pixelColor(4, 4)
assert c0.getRgb() == c3.getRgb(), f"面板外被蒙层碰了：{c0.getRgb()} -> {c3.getRgb()}"
print(f"  (3) 面板外一角 (4,4)：{c3.getRgb()}（与暗之前一致）")

ia5, ib5 = shots["m5"]
d5 = _diff_pixels(ia5, ib5)
assert d5 == 0, f"「全亮」与对照对不上（{d5} 像素）"
print(f"  (5) 全亮：与对照不同像素 {d5} 个（期望 0）")

for key in ("m2", "m3", "m4"):
    ia, ib = shots[key]
    _g, n_amb, n_sky = _ghost_bright(ia, ib)
    print(f"  幽灵 {key}（琥珀 / 天蓝）：{n_amb} / {n_sky}")
    assert n_sky == 0, f"{key} 出现了「它比对照亮」的像素（{n_sky}）"

# ── 帧带 ──
frames_spec = [
    ("[1] 你还在（还没走）", "m1", "与「不会暗的它」逐像素重合 —— 它还不知道你要走"),
    ("[2] 你走了：暗下去半路", "m2", "约一半的档位（琥珀 = 对照还亮着、它被蒙住的地方）"),
    ("[3] 全暗（省电中）", "m3", "脸 / 状态行 / 输入框一起暗；它还在呼吸 —— 省电不是关机"),
    ("[4] 你回来：亮回来半路", "m4", "欢迎回来同拍抬头（屏幕比脸醒得还急）"),
    ("[5] 全亮", "m5", "与对照整幅逐像素一致（归位无残留）"),
]
panels = []
for label, key, note in frames_spec:
    ia, ib = shots[key]
    if key in ("m1", "m5"):
        img_panel, sub = ia, f"{note}（与对照差 0 像素）"
    else:
        ghost, n_amb, n_sky = _ghost_bright(ia, ib)
        img_panel, sub = ghost, f"{note}（琥珀 {n_amb}、天蓝 {n_sky}）"
    panels.append(_tile(img_panel, label, sub))

card_lines = [
    "\u2022 触发：光标静 10 分钟（和休息提醒 / 欢迎回来同一把尺子）后的「你走了」—— 真链路",
    "\u2022 暗下去 2.5s（慢，沉下去）；亮回来 1.1s（快 —— 屏幕比脸醒得还急）",
    "\u2022 最暗蒙 25% 的黑：脸 / 状态行 / 输入框的文字一起暗；扫描线与暗角照旧",
    f"\u2022 全暗时脸部亮像素比例 {r_face:.3f}（期望 {want}）；面板外一个像素不碰",
    "\u2022 收尾（全亮）与对照整幅逐像素一致；睡着不挡省电；被拎着不算离开",
]
panels.append(_tile(_card(card_lines), "(6) 判据数字卡", "同口径：tests/test_standby.py"))

_grid(
    "待机省电「你走了，屏幕慢慢暗下去；你回来，亮回来」",
    "双胞胎实测（同种子、同喂法：会省电的它 vs 不会省电的它）；与真机同一段绘制代码（CRT 开）；整窗 1x",
    panels,
    2,
    OUT / "standby-strip.png",
)
print(f"  帧带: {OUT / 'standby-strip.png'}")

# ── 短视频：从「你走了」到「亮回来」（30fps，循环 3 遍）──
fps = 30
tmpdir = ROOT / ".tmp" / "_standby_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
for i, img in enumerate(frames):
    img.save(str(tmpdir / f"{i:04d}.png"))
if shutil.which("ffmpeg"):
    mp4 = OUT / "standby-demo.mp4"
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
    print(f"  短视频: {mp4}（{len(frames)} 帧 / {len(frames) / fps:.1f} 秒，循环 3 次）")
else:
    print("  注意：没找到 ffmpeg —— 只出了帧带（短视频没生成，别当它出过了）")
shutil.rmtree(tmpdir, ignore_errors=True)

a.close()
b.close()

for name in ("standby-strip.png", "standby-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
