#!/usr/bin/env python3
"""光标凝视素材 ——「它在看着你」：帧带 + 短视频，离屏真窗口逐帧抓。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- look-strip.png  6 格：光标在左 / 右 / 上 / 右下 / 停住后放开 / 关掉开关的对照
- look-demo.mp4   一次完整的「扫过去 → 看住 → 反方向再扫 → 停住 → 放开」

用法:
    .venv/bin/python scripts/look_preview.py

纪律：一条命令全部重生成；窗口随机全部钉种子（seed=7 与 tests/test_look.py
同一个）；光标是注入的假光标（脚本里可任意摆），画面走的仍是真绘制代码 ——
素材不是摆拍，是拿这行代码真渲染出来的。放大一律最近邻（平滑会糊）。
"""

from __future__ import annotations

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

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

OUT = ROOT / "docs" / "8h-b2"
TMP = ROOT / ".tmp" / "look"
FPS = 25
ZOOM = 2  # 整窗放大倍数
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
CUR = QColor(232, 192, 90, 235)  # 光标标记：琥珀色（和脸的绿区分开）
SEED = 7  # 和 tests/test_look.py 同一个种子：图与判据对得上

_app = QApplication.instance() or QApplication([])

from sammy import anim, layout
from sammy.pet import SammyWindow

layout.load_fonts()


class FakeCursor:
    """可摆的假光标：位置用「相对脸中心」的设备像素表示。"""

    def __init__(self, win):
        self.win = win
        self.dx = -200.0
        self.dy = 0.0

    def __call__(self):
        c = self.win.lay.face.center()
        s = self.win.scale
        lx = (c.x() + self.dx) * s + self.win._offset[0]
        ly = (c.y() + self.dy) * s + self.win._offset[1]
        return self.win.mapToGlobal(QPoint(round(lx), round(ly)))

    def window_point(self) -> QPoint:
        c = self.win.lay.face.center()
        s = self.win.scale
        return QPoint(
            round((c.x() + self.dx) * s + self.win._offset[0]),
            round((c.y() + self.dy) * s + self.win._offset[1]),
        )


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
    """推进一帧：喂光标（_anim_tick 里做）+ 把这一帧算出来（离屏没有事件循环）。"""
    w._anim_tick()
    w.anim.frame_at(w.anim_t)


def _sweep(w, cur, x0, y0, x1, y1, ticks: int = 36, hold: int = 30) -> None:
    """光标先放好建立参照，再平滑移过去（36 帧 = 1.2 秒），最后停住 30 帧。"""
    cur.dx, cur.dy = x0, y0
    _step(w)
    for i in range(ticks):
        k = (i + 1) / ticks
        cur.dx, cur.dy = x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
        _step(w)
    for _ in range(hold):
        _step(w)


def _settle_clean(w, max_steps: int = 600):
    """走到一个「干净帧」（不眨眼、不弹跳）再抓 —— 眨到一半的脸会骗眼睛。"""
    for _ in range(max_steps):
        f = w.anim.frame_at(w.anim_t)
        if f.squash == 1.0 and f.pop == 1.0:
            return f
        _step(w)
    raise SystemExit("等不到干净帧")


def _green_stats(w):
    """(绿像素数, 质心 x, 质心 y) —— 和测试同一套口径，用来报数。"""
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
            if g > 80 and g > 2 * rr and g > 2 * b:
                n += 1
                sx += x
                sy += y
    return n, (sx / n if n else 0.0), (sy / n if n else 0.0)


def _grab2x_marked(w, cur) -> QImage:
    """抓图 + 在光标位置画一个琥珀十字（验收时一眼看出「它在看哪」）。"""
    img = w.grab().toImage()
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(CUR, 2))
    pt = cur.window_point()
    p.drawEllipse(pt, 7, 7)
    p.drawLine(pt.x() - 11, pt.y(), pt.x() + 11, pt.y())
    p.drawLine(pt.x(), pt.y() - 11, pt.x(), pt.y() + 11)
    p.end()
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
        cur = FakeCursor(w)
        w._cursor_now = cur
        extra = script(w, cur)
        f = _settle_clean(w)
        n, cx, cy = _green_stats(w)
        panels.append(
            _tile(_grab2x_marked(w, cur), title, sub_fmt.format(f=f, cx=cx, cy=cy, extra=extra))
        )
        notes.append((title, f, (n, cx, cy), extra))
        w.close()

    one(
        "① 光标在左边 → 看向左",
        "凝视 ({f.gx:+d}, {f.gy:+d}) 设备像素 · 绿质心 x={cx:.1f}",
        lambda w, cur: _sweep(w, cur, 200.0, 0.0, -200.0, 0.0),
    )
    one(
        "② 光标在右边 → 看向右",
        "凝视 ({f.gx:+d}, {f.gy:+d}) 设备像素 · 绿质心 x={cx:.1f}",
        lambda w, cur: _sweep(w, cur, -200.0, 0.0, 200.0, 0.0),
    )
    one(
        "③ 光标在上方 → 抬头",
        "凝视 ({f.gx:+d}, {f.gy:+d}) 设备像素 · 绿质心 y={cy:.1f}",
        lambda w, cur: _sweep(w, cur, 0.0, 100.0, 0.0, -100.0),
    )
    one(
        "④ 光标在右下 → 斜着看",
        "凝视 ({f.gx:+d}, {f.gy:+d}) 设备像素（方向不扭曲）",
        lambda w, cur: _sweep(w, cur, -200.0, 0.0, 300.0, 180.0),
    )

    def wait_release(w, cur):
        _sweep(w, cur, -200.0, 0.0, 200.0, 0.0)  # 先看住右边
        t0 = w.anim_t
        for _ in range(1200):
            _step(w)
            f = w.anim.frame_at(w.anim_t)
            if (f.gx, f.gy) != (anim.GAZE_MAX_X, 0):
                for _ in range(12):
                    _step(w)
                return w.anim_t - t0
        raise SystemExit("等了 40 秒都没放开？")

    one(
        "⑤ 停住一会儿之后 → 回去发自己的呆",
        "放开用了 {extra:.1f} 秒 · 之后凝视 ({f.gx:+d}, {f.gy:+d})（随机漂移）",
        wait_release,
    )
    one(
        "⑥ 把开关拨到 off → 完全不理（对照）",
        "同一个光标走位，凝视 ({f.gx:+d}, {f.gy:+d})（照旧的随机漂移，不追）",
        lambda w, cur: _sweep(w, cur, -200.0, 0.0, 200.0, 0.0),
        look_on=False,
    )

    print("  数字（设备像素与绿质心）:")
    for title, f, (n, cx, cy), extra in notes:
        print(
            f"    {title}: gx={f.gx:+d} gy={f.gy:+d} px={n} cx={cx:.1f} cy={cy:.1f} extra={extra}"
        )
    return _grid(
        "光标凝视「它在看着你」：光标动就转过去看，停下 2.5 秒后回去发自己的呆",
        "琥珀十字 = 光标位置 · 开关 SAMMY_LOOK 设 off 可关（第⑥格） · 与真机同一段绘制代码",
        panels,
        3,
        OUT / "look-strip.png",
    )


PHASES = [
    (0.0, "光标往右扫 → 它转过去看（0.55 秒缓动，跟得比光标慢半拍）"),
    (1.0, "光标停住 → 它还看着（保持窗口 2.5 秒）"),
    (1.8, "光标往左扫 → 立刻改看左边"),
    (2.8, "停住……保持窗口过了就放开，回去发自己的呆（2.6~7.4 秒后）"),
]


def _phase(t: float) -> str:
    out = PHASES[0][1]
    for at, text in PHASES:
        if t >= at:
            out = text
    return out


def _cursor_at(t: float) -> tuple[float, float]:
    if t < 1.0:
        return -220.0 + 440.0 * (t / 1.0), 0.0
    if t < 1.8:
        return 220.0, 0.0
    if t < 2.8:
        return 220.0 - 440.0 * ((t - 1.8) / 1.0), 0.0
    return -220.0, 0.0


def build_video() -> str:
    frames = Path(tempfile.mkdtemp(prefix="lookv-", dir=str(TMP)))
    w = _fresh()
    cur = FakeCursor(w)
    w._cursor_now = cur
    idx = 0
    release_at = None
    try:
        cur.dx, cur.dy = _cursor_at(0.0)
        _step(w)
        for i in range(1, int(11.5 * FPS)):
            t = i / FPS
            cur.dx, cur.dy = _cursor_at(t)
            _step(w)
            f = w.anim.frame_at(w.anim_t)
            if release_at is None and t > 4.5 and abs(f.gx + anim.GAZE_MAX_X) + abs(f.gy) >= 2:
                release_at = t  # 看住左边之后，第一次明显改向就是放开
            img = _grab2x_marked(w, cur)
            cv = QImage(880, 528 + 36, QImage.Format_ARGB32)
            cv.fill(BG)
            p = QPainter(cv)
            p.drawImage((880 - img.width()) // 2, (528 - img.height()) // 2, img)
            p.setFont(QFont("", 13))
            p.setPen(SUB)
            tag = _phase(t)
            p.drawText(12, 528 + 24, tag)
            p.end()
            if not cv.save(str(frames / (str(idx).zfill(5) + ".png"))):
                raise SystemExit("帧保存失败")
            idx += 1
            if release_at is not None and t >= release_at + 0.6:
                break
    finally:
        w.close()

    out = OUT / "look-demo.mp4"
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
    return (
        out.name
        + ": "
        + str(idx)
        + " 帧 / "
        + str(round(idx / FPS, 1))
        + " 秒 / "
        + str(kb)
        + " KB（放开时刻 t="
        + (str(round(release_at, 2)) if release_at else "未截到")
        + " 秒）"
    )


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    print("  光标凝视素材：")
    for line in (build_strip(), build_video()):
        print("  ok " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
