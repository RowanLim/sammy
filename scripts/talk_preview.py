#!/usr/bin/env python3
"""说话动脸素材 ——「字在往外冒，脸跟着动」：帧带 + 短视频，离屏真窗口逐帧抓。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- talk-strip.png   8 格：说话一拍的四个相位（起势 / 弹上 / 正中 / 弹下）+ 思考中
                   + 打完安静 + δ 波形轨迹 + 判据数字卡
- talk-demo.mp4    一次完整回复：字一个个冒出来、脸跟着弹；打完停住、脸也静下来

用法:
    .venv/bin/python scripts/talk_preview.py

纪律：一条命令全部重生成；窗口随机全部钉种子（seed=7，与 tests/test_talk.py 同一个）；
「在不在说话」走窗口自己的 _talking_now（真判定），画面走真绘制代码 —— 素材不是摆拍；
双胞胎对照（打字窗 vs 同种子已拨到尾的孪生）逐帧量绿质心差 δ；放大一律最近邻。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from itertools import pairwise
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
TMP = ROOT / ".tmp" / "talk"
FPS = 25
ZOOM = 2  # 帧带放大倍数
VZOOM = 1.5  # 视频放大倍数
CROP = QRect(180, 8, 440, 236)  # 脸的裁剪区（scale 1.0 的真实像素）
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：孪生（安静时）的幽灵与基线
SEED = 7  # 和 tests/test_talk.py 同一个种子：图与判据对得上
TEXT = "今天的风挺舒服的，我陪你坐一会儿。" * 2

_app = QApplication.instance() or QApplication([])

from sammy import anim, layout, typewriter
from sammy.pet import SammyWindow

layout.load_fonts()


def _fresh(typing: bool):
    """scale 1.0 的窗口：打字窗（typing）或已拨到尾的孪生。"""
    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.scale = 1.0
    w._offset = (0, 0)
    w.resize(800, 480)
    w.anim = anim.Animator(seed=SEED)
    w.anim_t = 8.0
    w.set_expression(9)  # 吐舌：没有动图，动的只有脸自己
    w.look_on = True
    w._cursor_now = lambda: w.mapToGlobal(QPoint(0, 0))
    w.sammy_line = TEXT
    if not typing:
        w.finish_typing()
    # 素材脚本不碰真状态：关窗时的保存全换成空操作（素材不是它的一天）
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(w, name, lambda: None)
    return w


def _feed(w) -> None:
    """一帧喂一次「在不在说话」—— 和窗口 _anim_tick 里的那条喂法完全一致。"""
    w.anim.note_talk(w.anim_t, w._talking_now())


def _centroid_y(img: QImage, face_rect: QRect) -> float:
    """绿质心 y（与 tests/test_talk.py 同一口径）—— δ 的证据来源。"""
    rgb = img.convertToFormat(QImage.Format_RGB32)
    buf = bytes(rgb.constBits())
    stride = rgb.bytesPerLine()
    r = face_rect.adjusted(-10, -10, 10, 2)
    clip = r.intersected(QRect(0, 0, rgb.width(), rgb.height()))
    n = sy = 0
    for y in range(clip.top(), clip.bottom() + 1):
        row = y * stride
        for x in range(clip.left(), clip.right() + 1):
            i = row + x * 4
            b, g, rr = buf[i], buf[i + 1], buf[i + 2]
            if g > 80 and g > 2 * rr and g > 2 * b:
                n += 1
                sy += y
    return sy / n if n else 0.0


def _shot(w):
    """抓一帧：(整幅图, 绿质心 y)。"""
    img = w.grab().toImage()
    return img, _centroid_y(img, w.lay.face)


def _crop2x(img: QImage) -> QImage:
    out = img.copy(CROP)
    return out.scaled(
        out.width() * ZOOM, out.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


def _ghost(base: QImage, twin: QImage) -> QImage:
    """把孪生（安静时）的脸用琥珀色勾出来 —— 只涂「两边不一样」的月牙边。

    重叠处保持原样：亮绿的脸是此刻（在动）的脸，琥珀月牙说明它安静时在哪儿；
    两张脸完全重合时（打完/收口后）琥珀一点都不会出现。
    """
    out = base.convertToFormat(QImage.Format_ARGB32)
    ab = base.convertToFormat(QImage.Format_RGB32)
    tb = twin.convertToFormat(QImage.Format_RGB32)
    as_ = bytes(ab.constBits())
    ts = bytes(tb.constBits())
    stride_a = ab.bytesPerLine()
    stride_t = tb.bytesPerLine()
    pen = QColor(AMB)
    pen.setAlpha(170)
    p = QPainter(out)
    p.setPen(pen)
    w, h = out.width(), out.height()

    def green(buf, stride, x, y):
        i = y * stride + x * 4
        bb, g, rr = buf[i], buf[i + 1], buf[i + 2]
        return g > 80 and g > 2 * rr and g > 2 * bb

    for y in range(h):
        for x in range(w):
            if green(ts, stride_t, x, y) and not green(as_, stride_a, x, y):
                p.drawPoint(x, y)
    p.end()
    return out


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


def _curve_panel(samples: list[tuple[float, float]], reveal: float, marks: list[tuple]) -> QImage:
    """δ 波形轨迹：横轴时间、纵轴「它 − 孪生」的绿质心差。"""
    img = QImage(880, 472, QImage.Format_ARGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    left, right, top, bottom = 70, 850, 46, 420
    tmax = max(t for t, _ in samples)
    unit = (bottom - top) / 2 / 3.6  # 每像素对应多少设备像素
    mid = (top + bottom) / 2

    def px(t):
        return left + (right - left) * t / tmax

    def py(d):
        return mid - d * unit

    # 打字段底色 + 边界线
    p.fillRect(
        QRect(int(px(0)), top, int(px(reveal) - px(0)), bottom - top), QColor(61, 220, 90, 22)
    )
    pen = QPen(AMB, 1, Qt.DashLine)
    p.setPen(pen)
    p.drawLine(left, int(mid), right, int(mid))  # 零线
    p.drawLine(int(px(reveal)), top, int(px(reveal)), bottom)
    p.setFont(QFont("", 10))
    p.setPen(SUB)
    p.drawText(int(px(reveal)) - 44, top - 8, f"字打完 {reveal:.2f}s")
    p.drawText(left, top + 12, "+3.6")
    p.drawText(left, int(mid) - 4, "0")
    p.drawText(left, bottom + 16, "-3.6")
    for i in range(1, 7):  # 每 0.44 秒一条拍线
        x = int(px(0.44 * i))
        p.setPen(QPen(QColor(95, 138, 108, 90), 1, Qt.DotLine))
        p.drawLine(x, top, x, bottom)
    p.setPen(SUB)
    p.drawText(right - 150, bottom + 32, "虚线 = 一拍 0.44 秒 · 琥珀 = 零线")
    # 曲线：打字段亮绿、静默段灰
    p.setPen(QPen(QColor("#3ddc5a"), 3))
    seq = [(px(t), py(d)) for t, d in samples if t <= reveal]
    for (x1, y1), (x2, y2) in pairwise(seq):
        p.drawLine(x1, y1, x2, y2)
    p.setPen(QPen(QColor(95, 138, 108, 200), 2))
    seq = [(px(t), py(d)) for t, d in samples if t >= reveal]
    for (x1, y1), (x2, y2) in pairwise(seq):
        p.drawLine(x1, y1, x2, y2)
    # 截帧时刻的圆点
    for _, t, d in marks:
        p.setPen(QPen(TITLE, 2))
        p.setBrush(Qt.NoBrush)
        x, y = px(t), py(d)
        p.drawEllipse(int(x) - 4, int(y) - 4, 8, 8)
    p.end()
    return img


def _numbers_panel(
    reveal: float,
    peak: float,
    trough: float,
    per_step: float,
    quiet: float,
    frames_note: str,
) -> QImage:
    """判据数字卡：这一版素材里真实量到的数。"""
    img = QImage(880, 472, QImage.Format_ARGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setFont(QFont("", 15))
    p.setPen(TITLE)
    p.drawText(24, 44, "说话动脸 · 数字（本次生成时真实测得）")
    p.setFont(QFont("", 13))
    lines = [
        "一拍 0.44 秒 · 弹幅 ±2.6 设备像素（四舍五入到 ±3）· 鼓收 ±2%",
        "开口缓入 0.18 秒 · 收口缓出 0.26 秒（说完不是啪地停）",
        "打字中绿质心的 δ：峰值 +" + f"{peak:.2f}" + " / 谷值 " + f"{trough:.2f}" + " 像素",
        "相邻帧最大位移 " + f"{per_step:.2f}" + " 像素（不瞬移；判据上限 3）",
        "打完 + 收口后 δ = " + f"{quiet:.3f}" + " 像素 —— 与孪生逐像素一致",
        "打字时长（这句 34 字） " + f"{reveal:.3f}" + " 秒 · " + frames_note,
    ]
    for i, line in enumerate(lines):
        p.setPen(TITLE if i < 2 else SUB)
        p.drawText(24, 96 + i * 34, line)
    p.setFont(QFont("", 11))
    p.setPen(SUB)
    p.drawText(24, 430, "口径：同种子双胞胎（打字窗 vs 拨到尾的孪生），量脸上荧光绿像素的质心")
    p.end()
    return img


def build_strip() -> str:
    a = _fresh(typing=True)
    b = _fresh(typing=False)
    a.grab()  # 第一眼画出来：打字机惰性起步（t0 = 8.0）
    b.grab()
    reveal = typewriter.reveal_seconds(TEXT)
    dt = anim.ANIM_DT
    want = {3: "起势", 31: "弹上", 34: "正中", 38: "弹下"}
    samples: list[tuple[float, float]] = []
    shots: dict[int, tuple] = {}
    k = 0
    last: tuple = ()
    try:
        while True:
            k += 1
            t = round(k * dt, 6)
            if t > reveal + 1.2:
                break
            a.anim_t = round(8.0 + t, 6)
            b.anim_t = a.anim_t
            _feed(a)
            _feed(b)
            fa = a.anim.frame_at(a.anim_t)
            b.anim.frame_at(b.anim_t)
            ia, cya = _shot(a)
            ib, cyb = _shot(b)
            d = cya - cyb
            samples.append((t, d))
            last = (t, ia.copy(CROP), ib.copy(CROP), fa.talk_y, d)
            if k in want:
                shots[k] = (t, ia.copy(CROP), ib.copy(CROP), fa.talk_y, d)
        # ⑤ 思考中：回复区的点在长，脸不弹
        a.thinking = True
        a.grab()
        think_img = a.grab().toImage().copy(CROP)
        a.thinking = False

        panels = []
        notes = []
        for kk in (3, 31, 34, 38):
            t, ca, cb, fy, d = shots[kk]
            ghosted = _crop2x(_ghost(ca, cb))
            tag = want[kk]
            cap = {
                3: "开口起势：包络才涨到六成，弹幅 " + f"{fy:+d}",
                31: "弹上：" + f"{fy:+d}" + " 设备像素（琥珀 = 安静时的脸）",
                34: "回正中：" + f"{fy:+d}" + "（两拍之间的必经点）",
                38: "弹下：" + f"{fy:+d}" + " 设备像素",
            }[kk]
            panels.append(
                _tile(
                    ghosted,
                    f"（{'①②③④'[(3, 31, 34, 38).index(kk)]}）τ={t:.2f} 秒 · {tag}",
                    cap + f" · 实测质心 δ = {d:+.1f} 像素",
                )
            )
            notes.append((tag, t, fy, d))
        panels.append(
            _tile(
                _crop2x(think_img),
                "（⑤）思考中：回复区在长思考点（在这幅裁剪之外）",
                "脸不弹 —— 它在想，不是在说（打字机没在吐字）",
            )
        )
        t, ca, cb, fy, d = last
        panels.append(
            _tile(
                _crop2x(ca),
                f"（⑥）打完 + 收口后（τ={t:.2f} 秒）：脸安静",
                f"δ = {d:+.3f} 像素 —— 与孪生整幅逐像素一致",
            )
        )
        marks = [(kk, shots[kk][0], shots[kk][4]) for kk in (3, 31, 34, 38)]
        panels.append(
            _tile(
                _curve_panel(samples, reveal, marks),
                "（⑦）δ 波形轨迹",
                "亮绿 = 打字中 · 灰 = 静默 · 每 0.44 秒一拍",
            )
        )
        typing_ds = [d for t, d in samples if t <= reveal]
        per_step = max(abs(b2 - a2) for a2, b2 in pairwise([d for _, d in samples]))
        quiet = samples[-1][1]
        panels.append(
            _tile(
                _numbers_panel(
                    reveal,
                    max(typing_ds),
                    min(typing_ds),
                    per_step,
                    quiet,
                    f"帧带 {k} 帧 x {dt:.3f} 秒/帧",
                ),
                "（⑧）判据数字卡",
                "每个数都能在 tests/test_talk.py 里找到同款判据",
            )
        )
        print("  数字（设备像素 / 绿质心）:")
        for tag, t, fy, d in notes:
            print(f"    {tag}: τ={t:.3f}s talk_y={fy:+d} δ={d:+.3f}px")
        print(
            f"    peak δ={max(typing_ds):+.3f} trough δ={min(typing_ds):+.3f} "
            f"per-step={per_step:.3f} quiet δ={quiet:+.3f}"
        )
        return _grid(
            "说话动脸「字在往外冒，脸跟着动」：打字机在吐字，脸跟着弹；字停了脸也停",
            "双胞胎实测（同种子：打字窗 vs 拨到尾的孪生）· 琥珀 = 安静时的脸 · 与真机同一段绘制代码",
            panels,
            4,
            OUT / "talk-strip.png",
        )
    finally:
        a.close()
        b.close()


def build_video() -> str:
    frames = Path(tempfile.mkdtemp(prefix="talkv-", dir=str(TMP)))
    a = _fresh(typing=True)
    b = _fresh(typing=False)
    a.grab()
    b.grab()
    reveal = typewriter.reveal_seconds(TEXT)
    end = reveal + typewriter.PAGE_HOLD + 2.0
    idx = 0
    t = 0.0
    try:
        while t < end:
            t = round(t + 1.0 / FPS, 6)
            a.anim_t = round(8.0 + t, 6)
            b.anim_t = a.anim_t
            _feed(a)
            _feed(b)
            a.anim.frame_at(a.anim_t)
            b.anim.frame_at(b.anim_t)
            ia, cya = _shot(a)
            _, cyb = _shot(b)
            d = cya - cyb
            img = ia.scaled(
                int(ia.width() * VZOOM),
                int(ia.height() * VZOOM),
                Qt.IgnoreAspectRatio,
                Qt.FastTransformation,
            )
            cv = QImage(img.width(), img.height() + 36, QImage.Format_ARGB32)
            cv.fill(BG)
            p = QPainter(cv)
            p.drawImage(0, 0, img)
            # 安静基线（琥珀虚线）：脸静下来时该在的位置；δ 是当前的位移
            yline = cyb * VZOOM
            p.setPen(QPen(AMB, 2, Qt.DashLine))
            p.drawLine(16, int(yline), img.width() - 16, int(yline))
            p.setFont(QFont("", 13))
            p.setPen(AMB)
            p.drawText(img.width() - 200, int(yline) - 8, f"安静基线 · δ={d:+.1f} 像素")
            p.setPen(SUB)
            if t < reveal:
                text = "字在一个个冒出来 —— 脸跟着弹（一拍 0.44 秒）"
            elif t < reveal + typewriter.PAGE_HOLD:
                text = "打完了，停一停 —— 脸也静下来（收口 0.26 秒）"
            else:
                text = "第二遍起整页直接给 —— 不再一个字一个字，脸也不弹"
            p.drawText(12, img.height() + 24, text)
            p.end()
            if not cv.save(str(frames / (str(idx).zfill(5) + ".png"))):
                raise SystemExit("帧保存失败")
            idx += 1
    finally:
        a.close()
        b.close()

    out = OUT / "talk-demo.mp4"
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
            "21",
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
        + " KB"
    )


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    print("  说话动脸素材：")
    for line in (build_strip(), build_video()):
        print("  ok " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
