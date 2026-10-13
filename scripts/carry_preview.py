#!/usr/bin/env python3
"""搬运凝视素材 ——「被带去哪儿就看哪儿」：帧带 + 短视频，离屏真窗口逐帧抓。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- carry-strip.png   6 格：搬向右 / 搬向左 / 搬向上 / 斜向右下 / 放下后回自己的漂移 / 开关 off 对照
- carry-demo.mp4    一次完整搬运：抓住 → 往右 → 往左 → 往上 → 放下 → 回去发呆

用法:
    .venv/bin/python scripts/carry_preview.py

纪律：一条命令全部重生成；窗口随机全部钉种子（seed=7 与 tests/test_carry.py
同一个）；拖拽是合成的真鼠标事件（走窗口 mousePress / Move / Release 同一条
代码路径），画面走的仍是真绘制代码 —— 素材不是摆拍。放大一律最近邻（平滑会糊）。
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SAMMY_CRT"] = "on"  # 生产观感：扫描线 / 辉光 / 暗角都在
os.environ["SAMMY_BOOT"] = "on"  # 素材永远拍稳态：不开机
os.environ["SAMMY_ANIM"] = "on"

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QApplication

OUT = ROOT / "docs" / "8h-b2"
TMP = ROOT / ".tmp" / "carry"
FPS = 25
ZOOM = 2  # 整窗放大倍数
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
CUR = QColor(232, 192, 90, 235)  # 搬运标记：琥珀色（和脸的亮色区分开）
SEED = 7  # 和 tests/test_carry.py 同一个种子：图与判据对得上

_app = QApplication.instance() or QApplication([])

from sammy import anim, faces, layout
from sammy.pet import SammyWindow

layout.load_fonts()


class FakeGrab:
    """按在脸中心的假手：走真 mousePress / Move / Release 事件（同一条代码路径）。"""

    def __init__(self, win):
        self.win = win
        c = win.lay.face.center()
        s = win.scale
        self.local = QPointF(int(c.x() * s + win._offset[0]), int(c.y() * s + win._offset[1]))
        self.start = win.mapToGlobal(self.local.toPoint())
        self.ox = 0.0
        self.oy = 0.0
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            self.local,
            QPointF(self.start),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        win.mousePressEvent(ev)

    def move_to(self, ox: float, oy: float) -> None:
        """把「手」挪到相对起点的 (ox, oy)（屏幕像素）—— 窗口跟着走。"""
        self.ox, self.oy = ox, oy
        g = QPointF(self.start.x() + ox, self.start.y() + oy)
        local = QPointF(self.win.mapFromGlobal(g.toPoint()))
        ev = QMouseEvent(QEvent.Type.MouseMove, local, g, Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        self.win.mouseMoveEvent(ev)

    def release(self) -> None:
        g = QPointF(self.start.x() + self.ox, self.start.y() + self.oy)
        local = QPointF(self.win.mapFromGlobal(g.toPoint()))
        ev = QMouseEvent(
            QEvent.Type.MouseButtonRelease, local, g, Qt.LeftButton, Qt.NoButton, Qt.NoModifier
        )
        self.win.mouseReleaseEvent(ev)


def _fresh(look_on: bool = True):
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.anim = anim.Animator(seed=SEED)
    w.anim_t = 8.0
    w.set_expression(9)
    w.finish_typing()
    w.look_on = look_on
    # 素材脚本不碰真状态：关窗时的保存全换成空操作（素材不是它的一天）
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(w, name, lambda: None)
    return w


def _step(w) -> None:
    """推进一帧：喂光标 / 搬运（_anim_tick 里做）+ 把这一帧算出来（离屏没有事件循环）。"""
    w._anim_tick()
    w.anim.frame_at(w.anim_t)


def _carry(w, grab: FakeGrab, dx: float, dy: float, ticks: int = 40) -> None:
    """把窗口平移 (dx, dy)（屏幕像素），40 步走完（约 1.3 秒），每步推一帧。"""
    for i in range(ticks):
        k = (i + 1) / ticks
        grab.move_to(dx * k, dy * k)
        _step(w)


def _settle_clean(w, max_steps: int = 600):
    """走到一个「干净帧」（不眨眼、不弹跳）再抓 —— 眨到一半的脸会骗眼睛。"""
    for _ in range(max_steps):
        f = w.anim.frame_at(w.anim_t)
        if f.squash == 1.0 and f.pop == 1.0:
            return f
        _step(w)
    raise SystemExit("等不到干净帧")


def _is_lit(r: int, g: int, b: int) -> bool:
    """是不是「脸上亮着的像素」——判据从 faces.LIT 读（**别写死色相**：
    2026-10-12 前景由荧光绿改白，写死绿色的话这里会静默量到 0）。"""
    lr, lg, lb = faces.LIT.red(), faces.LIT.green(), faces.LIT.blue()
    return abs(r - lr) < 70 and abs(g - lg) < 70 and abs(b - lb) < 70


def _lit_stats(w):
    """(亮像素数, 质心 x, 质心 y) —— 和测试同一套口径（判据从 faces.LIT 读），用来报数。"""
    img = w.grab().toImage().convertToFormat(QImage.Format_RGB32)
    buf = bytes(img.constBits())
    stride = img.bytesPerLine()
    r = w.lay.face.adjusted(-10, -10, 10, 2)
    s = w.scale
    clip = QRect(
        int(r.x() * s) + w._offset[0],
        int(r.y() * s) + w._offset[1],
        int(r.width() * s) + 2,
        int(r.height() * s) + 2,
    ).intersected(QRect(0, 0, img.width(), img.height()))
    n = sx = sy = 0
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            b, g, rr = buf[i], buf[i + 1], buf[i + 2]
            if _is_lit(rr, g, b):
                n += 1
                sx += x
                sy += y
    assert n > 1500, "抓到的亮像素太少，区域搞错了？"
    return n, sx / n, sy / n


def _mark(img: QImage, w, ox: float, oy: float) -> None:
    """在 1x 抓图上画「从哪儿搬来的」：琥珀虚线幽灵框 + 箭头（一眼看出搬动方向）。"""
    if ox == 0.0 and oy == 0.0:
        return
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = w.scale
    panel = w.lay.panel
    ghost = QRectF(
        panel.x() * s + w._offset[0] - ox,
        panel.y() * s + w._offset[1] - oy,
        panel.width() * s,
        panel.height() * s,
    )
    pen = QPen(CUR, 3)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    rr = w.lay.panel_radius * s
    p.drawRoundedRect(ghost, rr, rr)
    a = ghost.center()
    b = QPointF(
        (panel.x() + panel.width() / 2) * s + w._offset[0],
        (panel.y() + panel.height() / 2) * s + w._offset[1],
    )
    p.setPen(QPen(CUR, 4))
    p.drawEllipse(a, 6, 6)
    p.drawLine(a, b)
    ang = math.atan2(b.y() - a.y(), b.x() - a.x())
    for da in (2.6, -2.6):
        p.drawLine(b, QPointF(b.x() + 26 * math.cos(ang + da), b.y() + 26 * math.sin(ang + da)))
    p.end()


def _grab2x_marked(w, ox: float, oy: float) -> QImage:
    img = w.grab().toImage()
    _mark(img, w, ox, oy)
    return img.scaled(
        img.width() * ZOOM, img.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


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


def _grid(title: str, subtitle: str, panels: list[QImage], cols: int, out: Path) -> str:
    pad, capt = 14, 48
    pw = max(p.width() for p in panels)
    ph = max(p.height() for p in panels)
    rows = (len(panels) + cols - 1) // cols
    W = pad + (pw + pad) * cols
    H = capt + pad + (ph + pad) * rows
    canvas = QImage(W, H, QImage.Format_ARGB32)
    canvas.fill(BG)
    p = QPainter(canvas)
    p.setFont(QFont("", 16))
    p.setPen(TITLE)
    p.drawText(pad, 26, title)
    p.setFont(QFont("", 12))
    p.setPen(SUB)
    p.drawText(pad, 44, subtitle)
    for i, panel in enumerate(panels):
        x = pad + (i % cols) * (pw + pad)
        y = capt + pad + (i // cols) * (ph + pad)
        p.drawImage(x, y, panel)
    p.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(out)):
        raise SystemExit("存不下来：" + str(out))
    return out.name + ": " + str(W) + "x" + str(H) + "，" + str(len(panels)) + " 格"


def build_strip() -> str:
    panels = []
    notes = []

    def one(title: str, sub_fmt, script, look_on: bool = True):
        w = _fresh(look_on=look_on)
        grab = FakeGrab(w)
        extra = script(w, grab)
        for _ in range(24):  # 让收尾的缓动走完再抓（火候要到「定格」）
            _step(w)
        f = _settle_clean(w)
        n, cx, cy = _lit_stats(w)
        panels.append(
            _tile(
                _grab2x_marked(w, grab.ox, grab.oy),
                title,
                sub_fmt.format(f=f, cx=cx, cy=cy, extra=extra),
            )
        )
        notes.append((title, f, (n, cx, cy), extra))
        w.close()

    def drag_right(w, grab):
        _carry(w, grab, 260.0, 0.0)
        grab.release()

    def drag_left(w, grab):
        _carry(w, grab, -260.0, 0.0)
        grab.release()

    def drag_up(w, grab):
        _carry(w, grab, 0.0, -160.0)
        grab.release()

    def drag_down_right(w, grab):
        _carry(w, grab, 220.0, 130.0)
        grab.release()

    one(
        "① 被搬向右 → 看向右",
        "窗口右移 260 屏幕像素 · 凝视 ({f.gx:+d}, {f.gy:+d}) · 亮像素质心 x={cx:.1f}",
        drag_right,
    )
    one(
        "② 被搬向左 → 看向左",
        "窗口左移 260 屏幕像素 · 凝视 ({f.gx:+d}, {f.gy:+d}) · 亮像素质心 x={cx:.1f}",
        drag_left,
    )
    one(
        "③ 被搬向上 → 抬头",
        "窗口上移 160 屏幕像素 · 凝视 ({f.gx:+d}, {f.gy:+d}) · 亮像素质心 y={cy:.1f}",
        drag_up,
    )
    one(
        "④ 斜向右下 → 斜着看",
        "窗口挪了 (220, 130) 屏幕像素 · 凝视 ({f.gx:+d}, {f.gy:+d})（方向不扭曲）",
        drag_down_right,
    )

    def wait_drift(w, grab):
        _carry(w, grab, 260.0, 0.0)
        grab.release()
        t0 = w.anim_t
        seen = False
        for _ in range(1500):
            _step(w)
            f = w.anim.frame_at(w.anim_t)
            if (f.gx, f.gy) == (anim.GAZE_MAX_X, 0):
                seen = True
            elif seen:
                for _ in range(12):
                    _step(w)
                return w.anim_t - t0
        raise SystemExit("等了 50 秒都没放开？")

    one(
        "⑤ 放下后 → 看住原方向，过会儿回自己的漂移",
        "放开 {extra:.1f} 秒后自己去了别处 · 凝视 ({f.gx:+d}, {f.gy:+d})",
        wait_drift,
    )
    one(
        "⑥ 开关拨到 off → 搬运不追（对照）",
        "同一个搬法，凝视 ({f.gx:+d}, {f.gy:+d})（照旧随机漂移，不追）",
        drag_right,
        look_on=False,
    )

    print("  数字（设备像素与亮像素质心）:")
    for title, f, (n, cx, cy), extra in notes:
        print(
            f"    {title}: gx={f.gx:+d} gy={f.gy:+d} px={n} cx={cx:.1f} cy={cy:.1f} extra={extra}"
        )
    return _grid(
        "搬运凝视「被带去哪儿就看哪儿」：拖动窗口 = 被搬走，脸看向行进方向，松手不泄气",
        "琥珀虚线 = 搬动前窗口的位置 · 开关 SAMMY_LOOK 设 off 可关（第⑥格） · 与真机同一段绘制代码",
        panels,
        3,
        OUT / "carry-strip.png",
    )


RELEASE_T = 6.7

PHASES = [
    (0.4, "按住它 —— 不动就不打扰（按住不等于被搬）"),
    (1.0, "往右搬 —— 脸看向走的方向（0.55 秒缓动，不瞬移）"),
    (3.4, "停下（手还按着）—— 它继续看着那个方向"),
    (4.0, "往左搬 —— 看向另一边"),
    (5.4, "往上搬 —— 抬头"),
    (6.7, "放下 —— 看住最后的方向，零头不泄"),
    (7.9, "过一会儿回去发自己的呆（随机漂移）"),
]


def _offset_at(t: float) -> tuple[float, float]:
    if t < 0.4:
        return 0.0, 0.0
    if t < 2.2:  # 1.8 秒往右 380
        k = (t - 0.4) / 1.8
        return 380.0 * k, 0.0
    if t < 3.4:
        return 380.0, 0.0
    if t < 5.4:  # 2.0 秒往左 560
        k = (t - 3.4) / 2.0
        return 380.0 - 560.0 * k, 0.0
    if t < 6.7:  # 1.3 秒往上 170
        k = (t - 5.4) / 1.3
        return -180.0, -170.0 * k
    return -180.0, -170.0


def _phase(t: float) -> str:
    out = PHASES[0][1]
    for at, text in PHASES:
        if t >= at:
            out = text
    return out


def build_video() -> str:
    frames = Path(tempfile.mkdtemp(prefix="carryv-", dir=str(TMP)))
    w = _fresh()
    grab = FakeGrab(w)
    idx = 0
    t = 0.0
    prev_off = (0.0, 0.0)
    released_at = None
    settled_val = None
    stable = 0
    last_val = None
    drift_at = None
    try:
        while t < RELEASE_T + 9.5:
            t = round(t + 1.0 / FPS, 6)
            if t <= RELEASE_T:
                ox, oy = _offset_at(t)
                if (ox, oy) != prev_off:
                    grab.move_to(ox, oy)
                prev_off = (ox, oy)
            # 一帧 = 视频里的 1/FPS 秒：动画时间跟着视频时间走。别用 ANIM_DT ——
            # 它会以 0.825 倍速慢放整段，时间轴与字幕对不上（素材踩过这个坑）。
            w.anim_t = round(8.0 + t, 6)
            f = w.anim.frame_at(w.anim_t)
            cur = (f.gx, f.gy)
            if t >= RELEASE_T and released_at is None:
                grab.release()
                released_at = t
            if released_at is not None and t >= released_at + 0.4:
                if settled_val is None:
                    if cur == last_val:
                        stable += 1
                        if stable >= 8:
                            settled_val = cur
                    else:
                        stable = 0
                elif cur != settled_val:
                    if drift_at is None:
                        drift_at = t
                    elif t >= drift_at + 0.9:
                        break
            img = _grab2x_marked(w, grab.ox, grab.oy)
            cv = QImage(880, 528 + 36, QImage.Format_ARGB32)
            cv.fill(BG)
            p = QPainter(cv)
            p.drawImage((880 - img.width()) // 2, (528 - img.height()) // 2, img)
            p.setFont(QFont("", 13))
            p.setPen(SUB)
            p.drawText(12, 528 + 24, _phase(t))
            p.end()
            if not cv.save(str(frames / (str(idx).zfill(5) + ".png"))):
                raise SystemExit("帧保存失败")
            idx += 1
            last_val = cur
    finally:
        w.close()

    out = OUT / "carry-demo.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            str(frames / "%05d.png"),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
    )
    kb = out.stat().st_size // 1024
    tail_note = "漂移时刻 t=" + (str(round(drift_at, 2)) if drift_at else "未截到")
    return (
        out.name
        + ": "
        + str(idx)
        + " 帧 / "
        + str(round(idx / FPS, 1))
        + " 秒 / "
        + str(kb)
        + " KB（"
        + tail_note
        + " 秒）"
    )


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    print("  搬运凝视素材：")
    for line in (build_strip(), build_video()):
        print("  ok " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
