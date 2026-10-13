#!/usr/bin/env python3
"""摸摸头素材 ——「手停在脸上的时候，眯起眼呼噜一下」：帧带 + 短视频，离屏真窗口逐帧抓。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- petting-strip.png  6 格（脸区 2× 最近邻放大 + 琥珀幽灵 + 琥珀圈标光标）：
  ① 手刚停上（还没停够）② 正眯起来（半路）③ 摸住了（最眯 + 呼噜）
  ④ 呼噜换了半拍 ⑤ 手拿开、正睁开（顺带朝手看了一眼）⑥ 判据数字卡
- petting-demo.mp4   一次完整的「手伸过来 → 停够 → 眯眼呼噜 → 手拿开 → 睁开」
  整窗 1× 短片（带相位字幕条，光标用琥珀圈标出）

用法:
    .venv/bin/python scripts/petting_preview.py

纪律（和其他素材脚本一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7 —— 与 tests/test_petting.py 的
  渲染判据同一家）；
- 「被摸」走**生产链**：假光标停进脸框 → 窗口 _poll_cursor 喂 note_pet（同一行
  生产代码）；「手拿开」就是光标真的挪走 —— 它顺带朝手看一眼（光标凝视），
  这段如实出镜，不藏；
- 琥珀幽灵 = 同种子孪生（**没被摸的它**）的脸：只涂「两边不一样」的地方，
  重叠处保持原样；检测一律按 faces.LIT 常量（别写死颜色 —— 配色改白之后
  写死检测的脚本重跑会静默量到 0，DEVLOG 有记）；
- 放大一律最近邻；ffmpeg 不在就只出帧带并说明（不静默降级）；
- 顺手把「停够 / 眯满 / 睁开」几个时刻、脸高比、呼噜范围打出来。
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

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from sammy import anim, faces, layout
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_petting.py 的渲染判据一家
T0 = 8.0  # 起步时间轴
RELEASE_TAU = 2.4  # 「手拿开」的时刻（相对 τ）—— 帧带与短视频共用
CURSOR_ON = (6.0, 6.0)  # 停在脸上的位置（相对脸中心，设备像素）
CURSOR_AWAY = (-380.0, 0.0)
ZOOM = 2  # 帧带放大倍数（脸的内容不高，2× 才看得清那几像素的眯眼）
CROP = QRect(160, 4, 480, 234)  # 脸的裁剪区（scale 1.0 的真实像素）
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：孪生（没被摸的它）站过的地方
CUR = QColor(232, 192, 90, 235)  # 光标标记：琥珀色（和脸的亮色区分开）

app = QApplication(sys.argv[:1])
layout.load_fonts()


class FakeCursor:
    """可摆的假光标：位置用「相对脸中心」的设备像素表示。"""

    def __init__(self, win):
        self.win = win
        self.dx = -400.0
        self.dy = 0.0

    def __call__(self):
        return self.win.mapToGlobal(self.window_point())

    def window_point(self) -> QPoint:
        c = self.win.lay.face.center()
        s = self.win.scale
        return QPoint(
            round((c.x() + self.dx) * s + self.win._offset[0]),
            round((c.y() + self.dy) * s + self.win._offset[1]),
        )


def make_window(*, look_on: bool, blink: bool) -> SammyWindow:
    """稳态窗口：普通脸、种子钉死、时间轴从 T0 出发。

    look_on=False 的是孪生（没被摸的它）：不读光标、什么都不喂。
    blink=False 时 600 秒才眨一次（帧带把眨眼请出去：眯眼走 squash 通道，
    眨眼撞上就量不准）；短视频保留眨眼。
    """
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.scale = 1.0
    win._offset = (0, 0)
    win.resize(W, H)
    win._relayout()
    win.anim = (
        anim.Animator(seed=SEED) if blink else anim.Animator(seed=SEED, blink_gap=(600.0, 600.0))
    )
    win.set_expression(2)  # 普通脸：画面里动的只有摸摸头（和底层呼吸 / 漂移）
    win.finish_typing()
    win.sammy_line = ""
    win.my_line = ""
    win.look_on = look_on
    win.anim_t = T0
    # 素材脚本不碰真状态：关窗时的保存全换成空操作（素材不是它的一天）
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(win, name, lambda: None)
    win.show()
    return win


def step(w):
    """推进一帧：_anim_tick + 把这一帧算出来（离屏没有事件循环）。"""
    w._anim_tick()
    return w.anim.frame_at(w.anim_t)


def _lit(buf: bytes, stride: int, x: int, y: int) -> bool:
    i = y * stride + x * 4
    b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    return a >= 200 and abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70


def _lit_stats(img: QImage, rect: QRect) -> tuple[int, int, int, int, int, float, float]:
    """rect 里「不透明亮像素」的 (x0, y0, x1, y1, 个数, 质心x, 质心y)。"""
    src = img.convertToFormat(QImage.Format_ARGB32)
    buf = bytes(src.constBits())
    stride = src.bytesPerLine()
    x0 = y0 = 10**9
    x1 = y1 = -1
    n = 0
    sx = sy = 0.0
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            if _lit(buf, stride, x, y):
                x0 = min(x0, x)
                x1 = max(x1, x)
                y0 = min(y0, y)
                y1 = max(y1, y)
                n += 1
                sx += x
                sy += y
    assert n > 0, "没扫到脸像素？"
    return x0, y0, x1, y1, n, sx / n, sy / n


def _ghost(base: QImage, twin: QImage) -> tuple[QImage, int]:
    """把孪生（没被摸的它）的脸用琥珀色勾出来 —— 只涂「两边不一样」的地方。"""
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


def _mark(img: QImage, pt: QPoint) -> None:
    """在光标位置画一个琥珀圈 + 十字（验收时一眼看出「手在哪」）。"""
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(CUR, 2))
    p.drawEllipse(pt, 7, 7)
    p.drawLine(pt.x() - 11, pt.y(), pt.x() + 11, pt.y())
    p.drawLine(pt.x(), pt.y() - 11, pt.x(), pt.y() + 11)
    p.end()


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
    p.drawText(18, 34, "判据数字卡（与 tests/test_petting.py 同口径）")
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


# ── 帧带：五个时刻 + 数字卡 ────────────────────────
a = make_window(look_on=True, blink=False)  # 被摸的它（光标从开场就停在脸上）
b = make_window(look_on=False, blink=False)  # 孪生：没被摸的它
cura = FakeCursor(a)
a._cursor_now = cura
cura.dx, cura.dy = CURSOR_ON


def cursor_at(tau: float) -> tuple[float, float]:
    """光标轨迹（相对 τ）：停在脸上；RELEASE_TAU 起 0.25 秒挪走 = 手拿开。"""
    if tau < RELEASE_TAU:
        return CURSOR_ON
    k = min(1.0, (tau - RELEASE_TAU) / 0.25)
    return (
        CURSOR_ON[0] + (CURSOR_AWAY[0] - CURSOR_ON[0]) * k,
        CURSOR_ON[1] + (CURSOR_AWAY[1] - CURSOR_ON[1]) * k,
    )


rec: dict[str, float | None] = {"squint_start": None, "full": None, "open_done": None}
purr_lo, purr_hi = 10**9, -(10**9)
frames: list[tuple[str, QImage]] = []
crescents: dict[str, int] = {}
panel_nums: dict[str, tuple[int, int, float, int]] = {}


def advance(upto: float) -> None:
    """一起走到 τ>=upto；路上按 cursor_at 摆光标（生产链同一行喂法）。"""
    global purr_lo, purr_hi
    while a.anim_t < T0 + upto - 1e-9:
        cura.dx, cura.dy = cursor_at(a.anim_t - T0)
        fa = step(a)
        fb = step(b)
        tau = a.anim_t - T0
        if rec["squint_start"] is None and fa.squash < 1.0:
            rec["squint_start"] = tau
        full_squash = 1.0 - (1.0 - anim.PET_SQUINT_MIN)
        if rec["full"] is None and abs(fa.squash - full_squash) < 1e-12:
            rec["full"] = tau
        if rec["full"] is not None and tau < RELEASE_TAU:
            d = fa.dy - fb.dy
            purr_lo, purr_hi = min(purr_lo, d), max(purr_hi, d)
        if rec["open_done"] is None and tau > RELEASE_TAU + 0.2 and fa.squash == 1.0:
            rec["open_done"] = tau


def grab_panel(label: str, note: str) -> None:
    """抓一拍：两窗同帧（同种子）、算幽灵与前后的数字。"""
    ia = a.grab().toImage()
    ib = b.grab().toImage()
    fa = a.anim.frame_at(a.anim_t)
    fb = b.anim.frame_at(b.anim_t)
    _x0a, y0a, _x1a, y1a, _na, _cxa, _cya = _lit_stats(ia, CROP)
    _x0b, y0b, _x1b, y1b, _nb, _cxb, _cyb = _lit_stats(ib, CROP)
    ca, cb = ia.copy(CROP), ib.copy(CROP)
    ghosted, n = _ghost(ca, cb)
    crescents[label] = n
    ha, hb = y1a - y0a + 1, y1b - y0b + 1
    panel_nums[label] = (ha, hb, fa.squash, fa.dy - fb.dy)
    pt = cura.window_point() - CROP.topLeft()
    _mark(ghosted, pt)
    img = ghosted.scaled(
        CROP.width() * ZOOM, CROP.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )
    sub = (
        f"{note} · 脸高 {ha} vs {hb}px（×{ha / hb:.2f}）· squash {fa.squash:.2f}"
        f" · 呼噜Δ {fa.dy - fb.dy:+d}px · 琥珀 {n}px"
    )
    frames.append((label, _tile(img, f"{label} · τ={a.anim_t - T0:.2f}s", sub)))


advance(0.35)
grab_panel("（①）手刚停上", "还没停够 0.6 秒：它还没反应 —— 两边一模一样（琥珀 0）")
advance(0.78)
grab_panel("（②）正眯起来（半路）", "停够了：缓入 0.35 秒里，眼睛正慢慢眯上")
advance(1.30)
grab_panel("（③）摸住了", "眯到最深处（55%）+ 呼噜（0.9 秒一拍）")
advance(1.75)
grab_panel("（④）呼噜换了半拍", "轻轻一上一下 ±2px：和呼吸同幅、节奏更快 —— 读成「呼噜」")
advance(RELEASE_TAU + 0.33)
grab_panel("（⑤）手拿开：正睁开", "手挪走时它顺带朝手看了一眼（光标凝视）；眼睛正缓出 0.55 秒")
advance(RELEASE_TAU + 1.0)  # 再走一段：等它睁开完（睁开时刻要量到）

assert crescents["（①）手刚停上"] == 0, "① 应该两边一模一样（琥珀 0）"
assert crescents["（③）摸住了"] > 0, "③ 的琥珀月牙呢？"
assert rec["squint_start"] is not None and abs(rec["squint_start"] - anim.PET_DWELL_S) <= 0.1, (
    f"停够的时刻不对：{rec['squint_start']}"
)
assert (
    rec["full"] is not None and abs(rec["full"] - (anim.PET_DWELL_S + anim.PET_EASE_IN_S)) <= 0.1
), f"眯满的时刻不对：{rec['full']}"
assert rec["open_done"] is not None and RELEASE_TAU < rec["open_done"] <= RELEASE_TAU + 1.0, (
    f"睁开的时刻不对：{rec['open_done']}"
)
ratio3 = panel_nums["（③）摸住了"][0] / panel_nums["（③）摸住了"][1]
assert 0.45 <= ratio3 <= 0.65, f"③ 的脸高比 {ratio3:.2f} 不对"
assert purr_lo <= -1 and purr_hi >= 1, f"呼噜没摆起来：{purr_lo}..{purr_hi}"

print("  琥珀月牙像素（五个时刻，按顺序）:", list(crescents.values()))
print("  ① .. ⑤ 脸高与 squash:", dict(panel_nums))
print(
    f"  时刻（相对 τ）：停够 {rec['squint_start']:.2f}s · 眯满 {rec['full']:.2f}s · "
    f"睁开 {rec['open_done']:.2f}s（手拿开 τ={RELEASE_TAU}）"
)
print(f"  呼噜范围（眯满之后、手拿开之前）：{purr_lo:+d} .. {purr_hi:+d} px")
a.close()
b.close()

card_lines = [
    "• 触发：光标**停进脸框**、停够 PET_DWELL_S=0.6s 才算「在摸」（路过 / 划过去不算）",
    "• 反应：慢眯（PET_EASE_IN_S=0.35s → PET_SQUINT_MIN=55%）+ 呼噜（±2px、0.9 秒一拍）",
    "• 手拿开：从当前档位缓出（PET_EASE_OUT_S=0.55s）；素材里手真的挪走 —— 顺带朝手看一眼",
    f"• 实测（种子 {SEED}）：停够 τ={rec['squint_start']:.2f}s · 眯满 τ={rec['full']:.2f}s · "
    f"睁开 τ={rec['open_done']:.2f}s",
    f"• ③ 脸高 {panel_nums['（③）摸住了'][0]} vs {panel_nums['（③）摸住了'][1]}px"
    f"（×{ratio3:.2f}）—— 屏幕上的脸真的眯起来了",
    f"• 呼噜范围 {purr_lo:+d}..{purr_hi:+d}px；琥珀 = 没被摸的它站过的地方，① 为 0",
]
frames.append(("（⑥）判据数字卡", _card(card_lines)))

_grid(
    "摸摸头「手停在脸上的时候，眯起眼呼噜一下」：手停进脸框 → 停够 0.6s → 眯眼呼噜 → 手拿开 → 睁开",
    "双胞胎实测（同种子：被摸的它 vs 没被摸的它）· 2× 最近邻放大 · 琥珀圈 = 手（光标）位置",
    [img for _, img in frames],
    3,
    OUT / "petting-strip.png",
)
print(f"  帧带: {OUT / 'petting-strip.png'}")


# ── 短视频：手伸过来 → 停够 → 眯眼呼噜 → 手拿开 → 睁开（整窗 1×，10fps）────
FPS = 10
EVERY = 3  # 每 3 个 tick（0.033s）抓 1 帧 ≈ 10fps
ARRIVE_TAU = 0.7  # 手伸过来用时
LEAVE_TAU = 3.2  # 手开始挪走
LEAVE_S = 0.5  # 挪走用时
VIDEO_END = 4.3


def video_cursor_at(tau: float) -> tuple[float, float]:
    """短视频的光标轨迹：伸过来（0.7s）→ 停住 → 挪走（0.5s）。"""
    if tau < ARRIVE_TAU:
        k = tau / ARRIVE_TAU
        return (-300.0 + (CURSOR_ON[0] + 300.0) * k, CURSOR_ON[1] * k)
    if tau < LEAVE_TAU:
        return CURSOR_ON
    k = min(1.0, (tau - LEAVE_TAU) / LEAVE_S)
    return (CURSOR_ON[0] + (-360.0 - CURSOR_ON[0]) * k, CURSOR_ON[1] * (1.0 - k))


def video_phase(tau: float) -> str:
    if tau < ARRIVE_TAU:
        return "① 手伸过来 —— 它先看你手（光标凝视）"
    if tau < 0.79:
        return "② 手停住 —— 停够 0.6 秒才算「在摸」（路过不算）"
    if tau < 1.15:
        return "③ 停够 —— 正眯起眼（缓入 0.35 秒）"
    if tau < LEAVE_TAU:
        return "④ 摸住了：眯到 55% + 呼噜（±2px、0.9 秒一拍）"
    if tau < 3.62:
        return "⑤ 手拿开 —— 它朝手看一眼、慢慢睁开"
    return "⑥ 回到常态"


tmpdir = ROOT / ".tmp" / "_petting_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
wv = make_window(look_on=True, blink=True)
curv = FakeCursor(wv)
wv._cursor_now = curv
nfr = 0
try:
    curv.dx, curv.dy = video_cursor_at(0.0)
    step(wv)
    i = 0
    while (wv.anim_t - T0) < VIDEO_END:
        i += 1
        tau = i / 30.0
        curv.dx, curv.dy = video_cursor_at(tau)
        step(wv)
        if i % EVERY == 0:
            img = wv.grab().toImage()
            _mark(img, curv.window_point())
            cv = QImage(W, H + 36, QImage.Format_ARGB32)
            cv.fill(BG)
            p = QPainter(cv)
            p.drawImage(0, 0, img)
            p.setFont(QFont("", 13))
            p.setPen(SUB)
            p.drawText(12, H + 24, video_phase(tau))
            p.end()
            assert cv.save(str(tmpdir / (str(nfr).zfill(4) + ".png"))), "视频帧存不下来"
            nfr += 1
finally:
    wv.close()

if shutil.which("ffmpeg"):
    mp4 = OUT / "petting-demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(FPS),
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
    print(f"  短视频: {mp4}（{nfr} 帧 / 约 {nfr / FPS:.1f} 秒）")
else:
    print("  ⚠️ 没找到 ffmpeg —— 只出了帧带（短视频没生成，别当它出过了）")
shutil.rmtree(tmpdir, ignore_errors=True)

for name in ("petting-strip.png", "petting-demo.mp4"):
    p = OUT / name
    if p.is_file():
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        print(f"  sha256 {name}: {h}  ({p.stat().st_size} bytes)")
