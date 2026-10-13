#!/usr/bin/env python3
"""打字凝视素材 ——「看着你写」：你在输入框敲字，它低头看着输入框。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- typing-strip.png  6 格（脸部 2× 最近邻放大 + 琥珀幽灵）：还没读到你 → 转过来中 →
                     落在输入框上 → 一直在写就一直看 → 停手后回去发呆 → 判据数字卡
- typing-demo.mp4   一次完整的「写起来 → 看着你写 → 停手 → 溜号」（整窗 1×，12fps）：
                     字在输入框里一个一个冒，脸跟着看下去，停手后慢慢溜号

用法:
    .venv/bin/python scripts/typing_preview.py

纪律（和其他素材脚本一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_typing.py 同一个）；
- 「打字」走**真信号链**：往真输入框 setText，textChanged → _on_typing → 动画层 ——
  素材不是摆拍，是这条链真跑出来的；
- 琥珀幽灵 = 同种子孪生（**没在读你写的它**）的脸：只涂「两边不一样」的月牙边，
  重叠处保持原样；检测一律按 faces.LIT 常量（别写死颜色 —— 配色改白之后，按旧色
  写死检测的脚本重跑会量到 0，DEVLOG 有记）；
- 放大一律最近邻；ffmpeg 不在就只出帧带并说明（不静默降级）；
- 顺手把「视线差几像素 / 质心差几像素 / 停手后什么时候溜号」几个数打出来。
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

from sammy import anim, faces, layout
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_typing.py 一家的种子（窗口里的随机都钉死）
T0 = 8.0  # 第一个键在时间轴上的位置
ZOOM = 2  # 帧带放大倍数（脸的内容不高，2× 才看得清那几像素的视线）
CROP = QRect(165, 0, 470, 240)  # 脸的裁剪区（scale 1.0 的真实像素）
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：孪生（没在读你写的它）站过的地方

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window(*, blink: bool = False) -> SammyWindow:
    """稳态窗口：普通脸、种子钉死、光标准入关掉 —— 只留「有没有在读你写」一个变量。

    帧带把眨眼请出去（blink=False 时 600 秒才眨一次）：打字会停掉漂移的随机
    消费，两边的眨眼时间表会各走各的，眨眼会污染幽灵对账（和 test_nod 量几何
    时同一个做法）；短视频保留眨眼（blink=True），动起来没人盯着那一帧。
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
    win.set_expression(2)  # 普通脸：画面里动的只有视线
    win.finish_typing()
    win.sammy_line = ""
    win.my_line = ""
    win.look_on = False  # 光标不参与（盯的是打字这一件事）
    win.anim_t = T0 - 0.4
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
    """把孪生（没在读你写的它）的脸用琥珀色勾出来 —— 只涂「两边不一样」的边。

    视线差开之后，边缘会露出一圈月牙（琥珀 = 它不看你写字时脸在哪儿）；
    两边完全重合时（还没敲字那一刻）琥珀一点都不会出现 —— 那条「0」就是证据。
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


def _crop2x(img: QImage) -> QImage:
    out = img.copy(CROP)
    return out.scaled(
        out.width() * ZOOM, out.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation
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


def _card(lines: list[str]) -> QImage:
    img = QImage(CROP.width() * ZOOM, CROP.height() * ZOOM, QImage.Format_ARGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setPen(TITLE)
    p.setFont(QFont("", 15))
    p.drawText(18, 34, "判据数字卡（与 tests/test_typing.py 同口径）")
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
a = make_window()  # 「在读你写」的它
b = make_window()  # 孪生：永远不喂

FEEDS = {8.0: "你", 9.0: "你好", 10.0: "你好呀"}


def advance(upto: float, feeds: dict) -> None:
    """一起走到 τ>=upto；路上到点的按键喂给 a 的真输入框（走真信号链）。"""
    while a.anim_t < upto - 1e-9:
        step(a)
        step(b)
        for kt in [k for k in sorted(feeds) if a.anim_t >= k - 1e-9]:
            a.input.setText(feeds.pop(kt))


frames: list[tuple[str, QImage]] = []
crescents: dict[str, int] = {}
panel_nums: dict[str, tuple[float, int, int]] = {}


def grab_panel(label: str, note: str) -> None:
    """抓一拍：两窗同帧（同种子）、算幽灵与前后的数字。"""
    ia = a.grab().toImage()
    ib = b.grab().toImage()
    fa = a.anim.frame_at(a.anim_t)
    fb = b.anim.frame_at(b.anim_t)
    _xa0, ya0, _xa1, _ya1, _na, cxa, cya = _lit_stats(ia, CROP)
    _xb0, yb0, _xb1, _yb1, _nb, cxb, cyb = _lit_stats(ib, CROP)
    ca, cb = ia.copy(CROP), ib.copy(CROP)
    ghosted, n = _ghost(ca, cb)
    crescents[label] = n
    panel_nums[label] = (cxa - cxb, cya - cyb, ya0 - yb0)
    sub = (
        f"{note} · 视线 ({fa.gx:+d},{fa.gy:+d}) vs ({fb.gx:+d},{fb.gy:+d}) · "
        f"质心Δ ({cxa - cxb:+.1f},{cya - cyb:+.1f})px · 顶沿Δ {ya0 - yb0:+d}px"
    )
    frames.append((label, _tile(_crop2x(ghosted), f"{label} · τ={a.anim_t:.2f}s", sub)))


advance(7.95, FEEDS)
grab_panel("（①）还没读到你", "还没敲字：两边一模一样 —— 琥珀 0")
advance(8.42, FEEDS)
grab_panel("（②）它转了过来（半路）", "第一个键刚落下：视线正从别处收回来")
advance(8.99, FEEDS)
grab_panel("（③）落在输入框上", "看定输入框（正下方）")
advance(13.9, FEEDS)
grab_panel(
    "（④）写完最后一句，它还守着", "最后一个键在 τ=10.00 —— 保持窗口（到 τ=14.0）里它一直看着"
)

# ⑤ 停手后溜号：走出保持窗口，等它离开输入框那一帧
leave = None
while a.anim_t < 25.0:
    fa = step(a)
    step(b)
    if a.anim_t > 14.05 and (fa.gx, fa.gy) != (0, anim.TYPING_GAZE_Y):
        leave = a.anim_t
        break
assert leave is not None, "停手后一直没溜号？"
advance(leave + 4.35, {})
grab_panel(
    "（⑤）停手后：回去发呆", f"τ={leave:.2f}s 它离开输入框、回自己的漂移；琥珀 = 没在读你写的它"
)

print("  琥珀月牙像素（五个时刻，按顺序）:", list(crescents.values()))
print(
    "  ①→⑤ 质心Δ（A 相对 B）：",
    [f"({panel_nums[k][0]:+.1f},{panel_nums[k][1]:+.1f})" for k in panel_nums],
)
print(f"  停手溜号时刻: τ={leave:.2f}s（最后一个键在 τ=10.00s；保持窗口到 τ=14.0）")
a.close()
b.close()

card_lines = [
    "• 触发：你在输入框里敲字（真信号链 setText → textChanged → 动画层）",
    f"• 转向：和光标凝视共用凝视盒（±10/±6）与 {anim.GAZE_EASE:.2f} 秒缓动；光标刚指过时让路",
    f"• 保持：手不停就一直守着；停手 TYPING_HOLD_S={anim.TYPING_HOLD_S:.0f} 秒后回去发呆",
    "• 闸门：睡着 / 动画关不喂；空文本（发送 / 删光）不算「在写」；写字时不叹气、不栽头",
    "• 实测（双胞胎，种子 7）：③ A 看定输入框 (0,+6)；B 在别处 —— 质心位移 "
    f"{panel_nums['（③）落在输入框上'][0]:+.1f}, {panel_nums['（③）落在输入框上'][1]:+.1f}px",
    f"• ⑤：最后一下键 τ=10.00 · τ={leave:.2f}s 离开输入框（保持 + 漂移间隔）",
    "• 琥珀月牙 = 没在读你写的它站过的地方；①（还没敲字）处为 0 —— 两边一模一样",
]
frames.append(("（⑥）判据数字卡", _card(card_lines)))

_grid(
    "打字凝视「看着你写」：你在输入框敲字，它把视线收回来落到输入框上",
    "双胞胎实测（同种子：在「读你写」的它 vs 没读的它）· 2× 最近邻放大 · 与真机同一段绘制代码",
    [img for _, img in frames],
    3,
    OUT / "typing-strip.png",
)
print(f"  帧带: {OUT / 'typing-strip.png'}")


# ── 短视频：写起来 → 看着你写 → 停手 → 溜号（整窗 1×，12fps）────
fps = 12
START = T0 - 0.7
FEED_LIST = [(8.0, "你"), (9.0, "你好"), (10.0, "你好呀"), (11.0, "你好呀。")]


def video_walk(w, save_dir: Path | None = None) -> tuple[float, int]:
    """12fps 网格从 START 走：找到溜号时刻、走到溜号后 1.6 秒；给目录就落帧。"""
    feeds = list(FEED_LIST)
    leave_t = None
    n = 0
    i = 0
    while True:
        t = round(START + i / fps, 6)
        if t > 26.0:
            raise AssertionError("短视频里它一直没溜号？")
        w.anim_t = t
        while feeds and t >= feeds[0][0] - 1e-9:
            w.input.setText(feeds.pop(0)[1])
        f = w.anim.frame_at(t)
        if leave_t is None and t > 14.05 and (f.gx, f.gy) != (0, anim.TYPING_GAZE_Y):
            leave_t = t
        if save_dir is not None:
            w.grab().toImage().save(str(save_dir / f"{i:04d}.png"))
            n += 1
        if leave_t is not None and t >= leave_t + 1.6:
            break
        i += 1
    return leave_t, n


scratch = make_window(blink=True)  # 第一遍：只为定「溜号」时刻（不落帧）
leave_v, _ = video_walk(scratch)
scratch.close()

tmpdir = ROOT / ".tmp" / "_typing_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
wv = make_window(blink=True)
leave_v2, nfr = video_walk(wv, tmpdir)
wv.close()
assert leave_v2 == leave_v, "两跑的溜号时刻不一致（素材该是确定性的）"

if shutil.which("ffmpeg"):
    mp4 = OUT / "typing-demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
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
    print(f"  短视频: {mp4}（{nfr} 帧 / {(nfr - 1) / fps:.1f} 秒）")
else:
    print("  ⚠️ 没找到 ffmpeg —— 只出了帧带（短视频没生成，别当它出过了）")
shutil.rmtree(tmpdir, ignore_errors=True)

for name in ("typing-strip.png", "typing-demo.mp4"):
    p = OUT / name
    if p.is_file():
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        print(f"  sha256 {name}: {h}  ({p.stat().st_size} bytes)")
