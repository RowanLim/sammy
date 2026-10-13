#!/usr/bin/env python3
"""入睡的一下素材 ——「撑不住了：困到最后头一沉，睡过去」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- dozeoff-strip.png  六格（脸部 2x 最近邻放大）：还撑着（犯困的脸）-> 沉到一半
                     -> 沉到底（睡实了）-> 松回来中 -> 收完（与对照逐像素一致）
                     + 判据数字卡
- dozeoff-demo.mp4   从「还撑着」到「松回来」的连续段（12fps，循环 3 遍）：
                     眨眼一变，整脸开始往下沉 —— 睡着的过程

用法:
    .venv/bin/python scripts/dozeoff_preview.py

纪律（和 typing_tilt_preview 一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_dozeoff.py 同一个）；
- 画面走**真绘制代码**（真窗口真 grab），触发走**真链路**（`_tick` 里驱力跨过
  睡着线那一刻 —— 和真机同一条边），不是摆拍；
- 对照 = 同种子、同喂法、只有「不会沉下去」一个差别的孪生（dozeoff 空转）——
  琥珀 = 对照占着、它让出来的地方；天蓝 = 它压缩后新占的地方；
- 检测一律按 faces.LIT 常量；放大一律最近邻；ffmpeg 不在就只出帧带并说明；
- 顺手把「顶沿/下沿/脸高差 / 幽灵像素数 / 收完差没差 / 关键帧在不在重绘区」
  打出来（DEVLOG 引它当证据）。
"""

from __future__ import annotations

import hashlib
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

from sammy import anim, faces, layout
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_dozeoff.py 一家的种子（窗口里的随机都钉死）
T0 = 6.0  # 「睡着那一刻」在时间轴上的时刻（驱力跨线发生在这一步 _tick）
CROP = QRect(146, 2, 508, 238)  # 脸的裁剪区（盖住下沉 + 压合的行程，有断言）
SCAN = QRect(120, 0, 580, 238)  # 找脸部亮像素的范围（避开状态行与关闭钮）
ZOOM = 2  # 帧带 / 视频放大倍数
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：对照占着、它让出来的地方
SKY = QColor(90, 167, 200)  # 天蓝：它压缩后新占的地方

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window() -> SammyWindow:
    """稳态窗口：犯困的它（energy 压线、脸是犯困脸）—— 只留「睡着那一刻」一个变量。"""
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED)
    win.look_on = False  # 光标不参与（盯的是「睡着那一刻」这一件事）
    win.drives.energy = 0.13  # 犯困（< 0.30），但还没睡着（> 0.12）
    win.drives.boredom = 0.2
    win.drives.closeness = 0.5
    win.drives.asleep = False
    win.drives.last_update = time.time()  # 冻结漂移：睡着那一刻由脚本自己拨时间触发
    win.my_line = ""
    win.sammy_line = ""
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


def _crop2x(img: QImage) -> QImage:
    out = img.copy(CROP)
    return out.scaled(
        out.width() * ZOOM, out.height() * ZOOM, Qt.IgnoreAspectRatio, Qt.FastTransformation
    )


def _ghost(base: QImage, twin: QImage) -> tuple[QImage, int, int]:
    """双色幽灵：琥珀 = 对照占着而它没占的；天蓝 = 它新占的。"""
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
    p.drawText(18, 34, "判据数字卡（与 tests/test_dozeoff.py 同口径）")
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


# ── 主流程：真链路（驱力跨线 -> _tick -> dozeoff + 睡脸淡化）──
a = make_window()
b = make_window()

# (0) 先让脸变成「犯困的脸」：能量 0.13 已压线 —— 走 _tick 真链路
a.anim_t = b.anim_t = round(T0 - 1.2, 6)
a._tick()
b._tick()
assert a.expression == 27, f"睡前该是犯困的脸，实际 {a.expression}"

# 对照的它：同种子、同喂法，唯独不会沉下去（dozeoff 空转）
b.anim.dozeoff = lambda at: None  # type: ignore[method-assign]


def _clean_at(win: SammyWindow, tt: float, tries: int = 40) -> float:
    """从 tt 起找一个不眨眼的时刻（量下沉要干净的脸）。"""
    for _ in range(tries):
        if win.anim.frame_at(tt).squash == 1.0:
            return tt
        tt = round(tt + 0.05, 6)
    raise AssertionError("找不到干净采样时刻")


def _snap_pair(tt: float):
    """在已知干净的 tt 抓两边 + 双色幽灵。"""
    ia = look(a, tt)
    ib = look(b, tt)
    g, n_amb, n_sky = _ghost(ia.copy(CROP), ib.copy(CROP))
    return tt, g, n_amb, n_sky, ia, ib


# (1) 还撑着：犯困的脸（还没睡着）
t1 = _clean_at(a, T0 - 0.6)
snaps = {"f1": _snap_pair(t1)}
print(f"  (1) 还撑着：与对照逐像素重合？琥珀 {snaps['f1'][2]} / 天蓝 {snaps['f1'][3]}（期望 0/0）")

# 睡着那一刻：把 last_update 拨到 0.4 小时前 -> 这一步 _tick 里驱力跨线（真边）
a.drives.last_update = time.time() - 0.4 * 3600
b.drives.last_update = time.time() - 0.4 * 3600
a.anim_t = b.anim_t = round(T0, 6)
a._tick()
b._tick()
assert a.drives.asleep and b.drives.asleep, "前提不成立：这一步没睡着"
assert a.anim._dozeoff_at == T0, "睡着那一刻没触发「撑不住」"
assert b.anim._dozeoff_at == -99.0, "对照不该触发"
assert a.expression == 1 and b.expression == 1, "睡脸该在同一拍亮起来"
print(
    f"  触发：T0={T0} 由 _tick 真链路（驱力跨线）；dozeoff 窗口 T0 .. T0+{anim.dozeoff_total():.1f}"
)

PEAK = round(T0 + anim.DOZEOFF_SINK_S + anim.DOZEOFF_HOLD_S / 2, 6)  # 1.4
plan = {
    "f2": round(T0 + 0.55, 6),  # 沉到一半
    "f3": PEAK,  # 沉到底（睡实了）
    "f4": round(T0 + anim.DOZEOFF_SINK_S + anim.DOZEOFF_HOLD_S + anim.DOZEOFF_SETTLE_S / 2, 6),
    "f5": round(T0 + anim.dozeoff_total() + 0.3, 6),  # 收完（与对照应逐像素一致）
}
for key, tt in plan.items():
    tt = _clean_at(a, tt)
    snaps[key] = _snap_pair(tt)

# 关键量：顶沿 / 下沿 / 脸高（沉到底那一帧 vs 对照）
tt, _g, _na, _ns, ia, ib = snaps["f3"]
x0a, y0a, x1a, y1a = lit_bbox(ia, SCAN)
x0b, y0b, x1b, y1b = lit_bbox(ib, SCAN)
print(
    f"  沉到底（T0+{tt - T0:.2f}s）：顶沿 {y0a - y0b:+d} / 下沿 {y1a - y1b:+d} / "
    f"脸高 {y1a - y0a} vs {y1b - y0b} / 左 {x0a - x0b:+d} 右 {x1a - x1b:+d}"
)
assert y0a - y0b >= 30, "顶沿没沉下去 —— 素材白做"
assert y1b - y1a >= 20, "下沿没被压上来"
assert (y1b - y0b) - (y1a - y0a) >= 55, "脸没被压合"
assert abs(x0a - x0b) <= 2 and abs(x1a - x1b) <= 2, "横向不该动"

# 关键帧落在重绘区里（CRT 开 + 辉光有一圈毛边，留 8px 容差）
region = a._face_region().adjusted(-8, -8, 8, 8)
deformed = QRect(x0a, y0a, x1a - x0a + 1, y1a - y0a + 1)
assert region.contains(deformed), f"沉到底时脸 {deformed} 冒出重绘区 {region}"
print(f"  关键帧落在重绘区内：{deformed} / 区域 {region}")

# 收完：与对照整幅逐像素一致
_tt5, _g5, _n5a, _n5s, ia5, ib5 = snaps["f5"]
ba = bytes(ia5.constBits())
bb = bytes(ib5.constBits())
diff = sum(1 for i in range(0, len(ba), 4) if ba[i : i + 4] != bb[i : i + 4])
assert diff == 0, f"收完还有 {diff} 个像素对不上"
print(f"  收完（T0+{snaps['f5'][0] - T0:.2f}s）：与对照不同像素 {diff} 个（期望 0）")

keys = ("f1", "f2", "f3", "f4", "f5")
print("  五格幽灵（琥珀 / 天蓝）：" + " / ".join(f"{k} {snaps[k][2]}/{snaps[k][3]}" for k in keys))

frames = [
    ("[1] 还撑着：犯困的脸", "f1", "还没睡着（energy 压线）—— 与对照完全重合"),
    ("[2] 睡着了：撑不住中", "f2", "睡脸亮起来、整脸开始往下沉 —— 一半"),
    ("[3] 沉到底（睡实了）", "f3", "下沉与压合都到满 —— 琥珀 = 让出来的上/下缘"),
    ("[4] 慢慢松回来", "f4", "沉到底之后松回睡姿 —— 不突然弹回"),
    ("[5] 收完：就是睡着的它", "f5", "与「不会沉下去的它」整幅逐像素一致"),
]
panels = []
for label, key, note in frames:
    tt, g, n_amb, n_sky, _ia, _ib = snaps[key]
    sub = f"{note}（琥珀 {n_amb}、天蓝 {n_sky}）"
    panels.append(_tile(_crop2x(g), f"{label}（tau={tt - T0:+.2f}s）", sub))

card_lines = [
    "\u2022 触发：自己熬到睡着（驱力跨线那一刻，_tick 真链路）—— 一段睡觉一次",
    "\u2022 形状：沉下去 1.1s -> 屏住 0.6s -> 松回来 0.9s（共 2.6 秒）",
    "\u2022 深度：整脸下沉 6px + 压合到 45%（比点头更深、比眨眼更缓）",
    "\u2022 只加不改：calm 门内运行，醒着一眼都不许有；收完与对照 0 像素差",
    "\u2022 琥珀 = 对照占着、它让出来的地方；天蓝 = 它压缩后新占的地方",
    "\u2022 实测：顶沿 +44 / 下沿 -32 / 脸高 138 -> 62（本常数、seed 7）",
]
panels.append(_tile(_card(card_lines), "(6) 判据数字卡", "同口径：tests/test_dozeoff.py"))

_grid(
    "入睡的一下「撑不住了」：困到最后，头一沉，睡过去",
    "双胞胎实测（同种子、同喂法：会沉下去睡着的它 vs 不会沉只切脸的它）；2x 最近邻放大；与真机同一段绘制代码",
    panels,
    3,
    OUT / "dozeoff-strip.png",
)
print(f"  帧带: {OUT / 'dozeoff-strip.png'}")

# ── 短视频：从「还撑着」到「松回来」（12fps，循环 3 遍）──
fps = 12
start, stop = round(T0 - 0.7, 6), round(T0 + 3.0, 6)
n = int((stop - start) * fps) + 1
tmpdir = ROOT / ".tmp" / "_dozeoff_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
for i in range(n):
    t = round(start + i / fps, 6)
    _crop2x(look(a, t)).save(str(tmpdir / f"{i:04d}.png"))

if shutil.which("ffmpeg"):
    mp4 = OUT / "dozeoff-demo.mp4"
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
    print("  注意：没找到 ffmpeg —— 只出了帧带（短视频没生成，别当它出过了）")
shutil.rmtree(tmpdir, ignore_errors=True)

a.close()
b.close()

for name in ("dozeoff-strip.png", "dozeoff-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
