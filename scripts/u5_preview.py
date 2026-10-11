#!/usr/bin/env python3
"""U5 收尾素材：前后对比图 + 短视频（全部离屏真窗口抓帧，一条命令可重生成）。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- before-after.png       三个整窗：第二轮起点 / 现在（质感关） / 现在（质感开）
- before-after-zoom.png  文字区 2 倍放大：系统字 vs Sammy Pixel（看像素网格）
- ui-demo.mp4            约 15 秒体验片：思考点→逐字打字 / 凝视+好奇+淡化 / 质感开关

「之前」怎么来：在 .tmp/u5-base 检出 U1 的父提交（f4ff3f7），用
scripts/u5_baseline_shot.py 以当时那份代码离屏渲染 —— 不是拿新代码摆拍。

用法:
    .venv/bin/python scripts/u5_preview.py            # 全部重生成
    .venv/bin/python scripts/u5_preview.py --only video
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import anim, layout, screen as screen_mod, typewriter
from sammy.pet import SammyWindow

BASELINE_REF = "f4ff3f7"  # 第二轮 UI 的起点（U1 的父提交）
WT = ROOT / ".tmp" / "u5-base"  # 起点代码的 worktree（不进仓库）
OUT = ROOT / "docs" / "8h-b2"
TMP = ROOT / ".tmp" / "u5"

FPS = 25  # 正好对上 25 字/秒：打字机每帧落一个字
CW, CH = 880, 528  # 画面区：全窗 440×264 的 2 倍
CAP_H = 32  # 底部字幕条
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")

# 这一幕要和 u5_baseline_shot.py 的「之前」逐字一致（两边各写一遍，测试对账）。
REPLY = "先别硬撑，喝口水。绿萝我浇过水了，你歇会儿。"
MY = "今天好累啊，不想干活。"
STATUS = "在线 · 1.8s"

_app = QApplication.instance() or QApplication([])
layout.load_fonts()  # 和真机一致：先注册像素字体


def _resolver(w: int, h: int):
    """假装有这么大一块屏（kiosk 铺满逻辑照常走）—— 和报告素材同款。"""

    def resolve(want=None):
        return {
            "index": 9,
            "name": f"PREVIEW-{w}x{h}",
            "x": 0,
            "y": 0,
            "width": w,
            "height": h,
            "primary": False,
        }

    return resolve


def _stop(win) -> None:
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()


def _fresh(**kw) -> SammyWindow:
    win = SammyWindow(autoconnect=False, **kw)
    _stop(win)
    return win


def _no_blink(win) -> None:
    win.anim._blinks = []
    win.anim._next_at = 1e9


def _gaze_pin(win, x: int = 0, y: int = 0) -> None:
    """把凝视钉在一个点上：哨兵条目让 _ensure_gaze 不再往后排新目标。"""
    gaze = getattr(win.anim, "_gaze", None)
    if not gaze:
        return
    g = gaze[0].__class__
    win.anim._gaze = [g(t=0.0, x=x, y=y, fx=x, fy=y), g(t=1e9, x=x, y=y, fx=x, fy=y)]


def _stable(win, expr: int = 3, t: float = 1.0) -> None:
    """定妆照的稳态：淡化/弹跳走完、打字机拨到尾、微动冻住。"""
    win.resize(440, 264)
    win.anim_t = t
    win.set_expression(expr)
    win.my_line = MY
    win.sammy_line = REPLY
    win.finish_typing()
    win.status = STATUS
    _no_blink(win)
    _gaze_pin(win)
    win.update()
    _app.processEvents()


def build_stills() -> None:
    """「现在」的两张定妆照：质感关 / 质感开（内容完全一致）。"""
    for crt in ("off", "on"):
        os.environ["SAMMY_CRT"] = crt
        win = _fresh()
        try:
            _stable(win)
            out = TMP / f"after-window-{crt}.png"
            if not win.grab().save(str(out)):
                raise SystemExit("存不下来: " + str(out))
            print(f"  ok {out.name}")
        finally:
            win.close()
    os.environ["SAMMY_CRT"] = "on"


def _ensure_worktree() -> None:
    """worktree 必须正好钉在 BASELINE_REF 上 —— 否则「之前」就不是之前了。"""

    def head() -> str:
        try:
            out = subprocess.run(
                ["git", "-C", str(WT), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return out.stdout.strip()
        except Exception:
            return ""

    if head().startswith(BASELINE_REF):
        return
    if WT.is_dir():
        subprocess.run(["git", "worktree", "remove", "--force", str(WT)], cwd=ROOT, check=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(WT), BASELINE_REF], cwd=ROOT, check=True
    )


def build_baseline() -> None:
    """「第二轮开始前」的同一幕 —— 交给起点 worktree 用当时那份代码渲染。"""
    _ensure_worktree()
    env = dict(os.environ)
    env["SAMMY_SRC"] = str(WT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    for k in ("SAMMY_CRT", "SAMMY_ANIM", "PYTHONPATH"):
        env.pop(k, None)
    out = TMP / "before-window.png"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "u5_baseline_shot.py"), "--out", str(out)],
        cwd=ROOT,
        env=env,
        check=True,
    )


# ── 前后对比图 ─────────────────────────────────

LABEL_H = 42


def _panel(img: QImage, title: str, sub: str) -> QImage:
    panel = QImage(img.width(), img.height() + LABEL_H, QImage.Format_ARGB32)
    panel.fill(BG)
    p = QPainter(panel)
    p.drawImage(0, 0, img)
    p.setFont(QFont("", 13))
    p.setPen(TITLE)
    p.drawText(8, img.height() + 17, title)
    p.setFont(QFont("", 11))
    p.setPen(SUB)
    p.drawText(8, img.height() + 33, sub)
    p.end()
    return panel


def _grid(title: str, panels: list[QImage], cols: int, out: Path) -> str:
    pad, capt = 14, 34
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
    p.drawText(pad, 24, title)
    for i, panel in enumerate(panels):
        x = pad + (i % cols) * (pw + pad)
        y = capt + (i // cols) * (ph + pad)
        p.drawImage(x, y, panel)
    p.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(out)):
        raise SystemExit("存不下来: " + str(out))
    return f"{out.name}: {W}x{H}"


def _zoom(img: QImage, rect: tuple[int, int, int, int], k: int = 2) -> QImage:
    crop = img.copy(*rect)
    return crop.scaled(
        crop.width() * k, crop.height() * k, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


def build_compare() -> None:
    before = QImage(str(TMP / "before-window.png"))
    off = QImage(str(TMP / "after-window-off.png"))
    on = QImage(str(TMP / "after-window-on.png"))
    panels = [
        _panel(before, "第二轮开始前（f4ff3f7）", "系统字体 · 无质感层 · 脸只看正中"),
        _panel(
            off, "现在 · 质感层关（SAMMY_CRT=off）", "Sammy Pixel · 打字机 / 凝视 / 好奇 / 淡化都在"
        ),
        _panel(on, "现在 · 质感层开（默认）", "扫描线 + 辉光 + 暗角（锁在窗口像素网格上）"),
    ]
    print(
        "  ok",
        _grid("第二轮 UI 前后对比 —— 字 / 节奏 / 凝视 / 质感", panels, 3, OUT / "before-after.png"),
    )

    rel = (20, 128, 290, 96)  # 状态行 + 回复区的文字块（物理像素）
    zp = [
        _panel(_zoom(before, rel), "之前：系统字体", "笔画带抗锯齿，边缘是灰的"),
        _panel(
            _zoom(on, rel), "现在：Sammy Pixel（12px 设计 2 倍）", "笔画落在像素网格上，断口干净"
        ),
    ]
    print("  ok", _grid("文字区 2 倍放大（最近邻）", zp, 2, OUT / "before-after-zoom.png"))


# ── 短视频 ─────────────────────────────────────


def _canvas() -> QImage:
    img = QImage(CW, CH + CAP_H, QImage.Format_ARGB32)
    img.fill(BG)
    return img


def _cap(p: QPainter, text: str) -> None:
    p.setFont(QFont(layout.FAMILY, 24))
    p.setPen(TITLE)
    p.drawText(14, CH + 4, CW - 28, CAP_H - 8, Qt.AlignLeft | Qt.AlignVCenter, text)


def _frame_full(win, caption: str) -> QImage:
    big = win.grab().toImage().scaled(CW, CH, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    cv = _canvas()
    p = QPainter(cv)
    p.drawImage(0, 0, big)
    _cap(p, caption)
    p.end()
    return cv


def _frame_centered(win, caption: str) -> QImage:
    img = win.grab().toImage()
    cv = _canvas()
    p = QPainter(cv)
    if img.width() > CW or img.height() > CH:
        img = img.scaled(CW, CH, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p.drawImage((CW - img.width()) // 2, (CH - img.height()) // 2, img)
    _cap(p, caption)
    p.end()
    return cv


def build_video() -> None:
    frames = Path(tempfile.mkdtemp(prefix="u5v-", dir=str(TMP)))
    idx = 0

    def save(cv: QImage) -> None:
        nonlocal idx
        if not cv.save(str(frames / f"{idx:05d}.png")):
            raise SystemExit("帧保存失败")
        idx += 1

    # 场景一：思考点 → 逐字打字
    w1 = _fresh()
    try:
        w1.resize(440, 264)
        w1.anim = anim.Animator(seed=3)
        w1.anim_t = 1.0
        w1.set_expression(3)
        w1.my_line = MY
        w1.sammy_line = REPLY
        w1.status = "思考中"
        w1.thinking = True
        _gaze_pin(w1)
        cap1a = "① 等模型时：点在长（回复区大点 · 正文行小点）"
        n = int(1.6 * FPS)
        for i in range(n):
            w1.anim_t = 1.0 + i / FPS
            save(_frame_full(w1, cap1a))
        w1.thinking = False
        w1.status = STATUS
        cap1b = "① 话是打出来的：40 毫秒一字，标点后多停一拍"
        t1 = 1.0 + int(1.6 * FPS) / FPS
        n = int((typewriter.reveal_seconds(REPLY) + 1.2) * FPS)
        for i in range(n):
            w1.anim_t = t1 + i / FPS
            save(_frame_full(w1, cap1b))
    finally:
        w1.close()

    # 场景二：凝视漂移 + 好奇 + 换表情淡化（face-only 大脸，800×480 原位）
    screen_mod.resolve_screen = _resolver(800, 480)
    w2 = SammyWindow(kiosk=True, face_only=True, autoconnect=False)
    _stop(w2)
    try:
        print("  face-only 窗口:", w2.width(), "x", w2.height(), "scale", round(w2.scale, 2))
        w2.anim = anim.Animator(seed=7)
        w2.anim_t = 1.0
        w2.set_expression(3)
        w2.sammy_line = "嗯，我在看呢。"
        w2._hold_line()
        w2.finish_typing()
        g = type(w2.anim._gaze[0])
        w2.anim._gaze = [
            g(t=0.0, x=0, y=0, fx=0, fy=0),
            g(t=1.2, x=10, y=0, fx=0, fy=0),
            g(t=3.6, x=-10, y=1, fx=10, fy=0),
            g(t=6.0, x=10, y=-4, fx=-10, fy=1),
            g(t=1e9, x=10, y=-4, fx=10, fy=-4),
        ]
        cap2 = "② 脸会看：看向一处并定格 · 贴边时探头 · 换表情缓过去"
        n2 = int(8.0 * FPS)
        for i in range(n2):
            w2.anim_t = i / FPS
            if i == int(3.2 * FPS):
                w2.set_expression(4)
            if i == int(6.4 * FPS):
                w2.set_expression(3)
            save(_frame_centered(w2, cap2))
    finally:
        w2.close()

    # 场景三：质感层开关（内容一致的三个窗口：开 → 关 → 开）
    wOn = _fresh()
    wOff = None
    try:
        _stable(wOn)
        os.environ["SAMMY_CRT"] = "off"
        wOff = _fresh()
        _stable(wOff)
        os.environ["SAMMY_CRT"] = "on"
        cap3 = "③ 质感层：扫描线 / 辉光 / 暗角（默认开 · SAMMY_CRT=off 关）"
        t = 1.0
        for i in range(int(1.0 * FPS)):
            wOn.anim_t = t + i / FPS
            save(_frame_full(wOn, cap3))
        t += 1.0
        for i in range(int(1.0 * FPS)):
            wOff.anim_t = t + i / FPS
            save(_frame_full(wOff, cap3))
        t += 1.0
        for i in range(int(1.4 * FPS)):
            wOn.anim_t = t + i / FPS
            save(_frame_full(wOn, cap3))
    finally:
        wOn.close()
        if wOff is not None:
            wOff.close()

    out = OUT / "ui-demo.mp4"
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
    print(f"  ok {out.name}: {idx} 帧 / {idx / FPS:.1f} 秒 / {kb} KB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--only", default="all", choices=("all", "baseline", "stills", "compare", "video")
    )
    args = ap.parse_args()
    TMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.only in ("all", "baseline"):
        build_baseline()
    if args.only in ("all", "stills"):
        build_stills()
    if args.only in ("all", "compare"):
        build_compare()
    if args.only in ("all", "video"):
        build_video()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
