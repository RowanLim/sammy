#!/usr/bin/env python3
"""欢迎回来素材 ——「你回来啦：光标静了十分钟，再动起来的第一下」。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- welcome-strip.png  六格（脸部 2x 最近邻放大）：你还没回来（与对照重合）
                     -> 你碰了鼠标（抬起来半路）-> 它看见你了（顶着）
                     -> 慢慢放回去 -> 收完（与对照逐像素一致）+ 判据数字卡
- welcome-demo.mp4   从「你还没回来」到「放回去」的连续段（12fps，循环 3 遍）

用法:
    .venv/bin/python scripts/welcome_preview.py

纪律（和 dozeoff_preview 一套）：
- 一条命令全部重生成；窗口随机钉种子（seed=7，与 tests/test_welcome.py 同一个）；
- 画面走**真绘制代码**（真窗口真 grab），触发走**真链路**（假光标喂
  _poll_cursor -> _note_presence —— 和真机上「你碰了鼠标」同一条），不是摆拍；
- 对照 = 同种子、同喂法、只有「不会抬头」一个差别的孪生（welcome 空转）——
  琥珀 = 对照占着、它让出来的地方；天蓝 = 它新占的地方；
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SAMMY_CRT"] = "on"  # 生产观感：扫描线 / 辉光 / 暗角都在
os.environ["SAMMY_ANIM"] = "on"
os.environ["SAMMY_BOOT"] = "off"

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import anim, faces, layout
from sammy.pet import SammyWindow

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 800, 480
SEED = 7  # 和 tests/test_welcome.py 一家的种子（窗口里的随机都钉死）
T0 = 12.0  # 「你碰了鼠标」那一刻在时间轴上的目标时刻
CROP = QRect(146, 2, 508, 238)  # 脸的裁剪区（盖上抬行程，有断言）
SCAN = QRect(120, 0, 580, 238)  # 找脸部亮像素的范围（避开状态行与关闭钮）
ZOOM = 2  # 帧带 / 视频放大倍数
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
AMB = QColor(232, 192, 90)  # 琥珀：对照占着、它让出来的地方
SKY = QColor(90, 167, 200)  # 天蓝：它新占的地方

app = QApplication(sys.argv[:1])
layout.load_fonts()


def make_window() -> SammyWindow:
    """稳态窗口：只留「你回来」一个变量（光标走假光标，全在脚本控制里）。"""
    win = SammyWindow(autoconnect=False)
    for tm in (win.timer, win.anim_timer, win.heart, win.night):
        tm.stop()
    win.resize(W, H)
    win.scale = 1.0
    win._relayout()
    win.anim = anim.Animator(seed=SEED, blink_gap=(600.0, 600.0))
    win.set_expression(2)  # 普通脸：画面里动的只有欢迎（和底层呼吸 / 漂移）
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
    p.drawText(18, 34, "判据数字卡（与 tests/test_welcome.py 同口径）")
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


# ── 主流程：真链路（假光标 -> _poll_cursor -> _note_presence -> welcome）──
a = make_window()
b = make_window()
cur_a = FakeCursor(a)
cur_b = FakeCursor(b)
a._cursor_now = cur_a
b._cursor_now = cur_b

# 对照的它：同种子、同喂法，唯独不会抬头（welcome 空转）
b.anim.welcome = lambda at: None  # type: ignore[method-assign]

# (0) 热身 + 建立光标参照（两窗同一步数，保持随机流对称）
a.anim_t = b.anim_t = round(T0 - 3.0, 6)
cur_a.dx = cur_b.dx = -400.0
a._anim_tick()
b._anim_tick()

# 「你走了」：把最近一次「你还在」的信号往回拨十分钟
a._presence_at = a.anim_t - (anim.WELCOME_AWAY_S + 1.0)
b._presence_at = b.anim_t - (anim.WELCOME_AWAY_S + 1.0)
a._anim_tick()
b._anim_tick()
assert a._away and b._away, "前提不成立：没安上「你走了」"

# 「你回来了」：对到整点附近，光标动了 40 像素 -> 这一步里触发
a.anim_t = b.anim_t = round(T0 - anim.ANIM_DT, 6)
cur_a.dx = cur_b.dx = -360.0
a._anim_tick()
b._anim_tick()
t_fire = a.anim_t
assert a.anim._welcome_at == t_fire, "真链路没触发「欢迎回来」"
assert b.anim._welcome_at == -99.0, "对照不该触发"
assert not a._away and not b._away, "回来后「你走了」该被消费"
print(
    f"  触发：光标静了十分钟后动了 40px（真链路，_poll_cursor -> _note_presence）；"
    f"T0={t_fire:.3f}，整段 {anim.welcome_total():.2f}s"
)


def _clean_at(win: SammyWindow, tt: float, tries: int = 40) -> float:
    """从 tt 起找一个不眨眼的时刻（量上抬与拉高要干净的脸）。"""
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


# (1) 你还没回来：与对照逐像素重合
t1 = _clean_at(a, t_fire - 0.4)
snaps = {"f1": _snap_pair(t1)}
print(
    f"  (1) 你还没回来：与对照逐像素重合？琥珀 {snaps['f1'][2]} / 天蓝 {snaps['f1'][3]}（期望 0/0）"
)

# (2)-(4) 抬起中 / 顶着 / 放回去（干净帧）
plan = {
    "f2": round(t_fire + 0.09, 6),  # 抬起来半路
    "f3": round(t_fire + anim.WELCOME_RISE_S + anim.WELCOME_HOLD_S / 2, 6),  # 顶着
    "f4": round(t_fire + anim.WELCOME_RISE_S + anim.WELCOME_HOLD_S + anim.WELCOME_SETTLE_S / 2, 6),
    "f5": round(t_fire + anim.welcome_total() + 0.3, 6),  # 收完（与对照应逐像素一致）
}
for key, tt in plan.items():
    tt = _clean_at(a, tt)
    snaps[key] = _snap_pair(tt)

# 关键量：顶沿 / 下沿 / 脸高（顶着那一帧 vs 对照）
tt, _g, _na, _ns, ia, ib = snaps["f3"]
x0a, y0a, x1a, y1a = lit_bbox(ia, SCAN)
x0b, y0b, x1b, y1b = lit_bbox(ib, SCAN)
print(
    f"  顶着（T0+{tt - t_fire:.2f}s）：顶沿 {y0a - y0b:+d} / 下沿 {y1a - y1b:+d} / "
    f"脸高 {y1a - y0a} vs {y1b - y0b} / 左 {x0a - x0b:+d} 右 {x1a - x1b:+d}"
)
assert y0b - y0a >= 5, "顶沿没抬起来 —— 素材白做"
assert abs(y1a - y1b) <= 3, "下沿不该明显跨"
assert (y1a - y0a) - (y1b - y0b) >= 4, "脸没被拉高"
assert abs(x0a - x0b) <= 2 and abs(x1a - x1b) <= 2, "横向不该动"

# 关键帧落在重绘区里（CRT 开 + 辉光有一圈毛边，留 8px 容差）
region = a._face_region().adjusted(-8, -8, 8, 8)
deformed = QRect(x0a, y0a, x1a - x0a + 1, y1a - y0a + 1)
assert region.contains(deformed), f"抬起来时脸 {deformed} 冒出重绘区 {region}"
print(f"  关键帧落在重绘区内：{deformed} / 区域 {region}")

# 收完：与对照整幅逐像素一致
_tt5, _g5, _n5a, _n5s, ia5, ib5 = snaps["f5"]
ba = bytes(ia5.constBits())
bb = bytes(ib5.constBits())
diff = sum(1 for i in range(0, len(ba), 4) if ba[i : i + 4] != bb[i : i + 4])
assert diff == 0, f"收完还有 {diff} 个像素对不上"
print(f"  收完（T0+{snaps['f5'][0] - t_fire:.2f}s）：与对照不同像素 {diff} 个（期望 0）")

keys = ("f1", "f2", "f3", "f4", "f5")
print("  五格幽灵（琥珀 / 天蓝）：" + " / ".join(f"{k} {snaps[k][2]}/{snaps[k][3]}" for k in keys))

frames = [
    ("[1] 你还没回来", "f1", "光标静了十分钟 —— 与对照完全重合（它不知道你要回来）"),
    ("[2] 你碰了鼠标：抬起来", "f2", "脸开始往上走 —— 半路（天蓝 = 新占的地方）"),
    ("[3] 它看见你了（顶着）", "f3", "上抬 + 拉高都到满 —— 顶沿让出的琥珀在上边"),
    ("[4] 慢慢放回去", "f4", "比抬起来慢：劲头落下有个尾巴"),
    ("[5] 收完：就是平常的它", "f5", "与「不会抬头的它」整幅逐像素一致"),
]
panels = []
for label, key, note in frames:
    tt, g, n_amb, n_sky, _ia, _ib = snaps[key]
    sub = f"{note}（琥珀 {n_amb}、天蓝 {n_sky}）"
    panels.append(_tile(_crop2x(g), f"{label}（tau={tt - t_fire:+.2f}s）", sub))

card_lines = [
    "\u2022 触发：光标静 10 分钟（和休息提醒同一把尺子）之后第一次动 —— 真链路",
    "\u2022 形状：抬起来 0.18s -> 顶住 0.30s -> 放回去 0.55s（共 1.03 秒）",
    "\u2022 幅度：上抬 5px + 纵向拉高 6%（顶着时顶沿约 -10px、横向 0）",
    "\u2022 闸门：睡着 / 开局 / 退场 / 动画关不演；打字与戳算「你还在」",
    "\u2022 收完与对照 0 像素差；不占随机流（同种子孪生对账靠它）",
]
panels.append(_tile(_card(card_lines), "(6) 判据数字卡", "同口径：tests/test_welcome.py"))

_grid(
    "欢迎回来「你回来啦」：光标静了十分钟，再动起来的第一下",
    "双胞胎实测（同种子、同喂法：会抬头的它 vs 不会抬头的它）；2x 最近邻放大；与真机同一段绘制代码",
    panels,
    3,
    OUT / "welcome-strip.png",
)
print(f"  帧带: {OUT / 'welcome-strip.png'}")

# ── 短视频：从「你还没回来」到「放回去」（12fps，循环 3 遍）──
fps = 12
start, stop = round(t_fire - 0.9, 6), round(t_fire + 2.0, 6)
n = int((stop - start) * fps) + 1
tmpdir = ROOT / ".tmp" / "_welcome_frames"
shutil.rmtree(tmpdir, ignore_errors=True)
tmpdir.mkdir(parents=True)
for i in range(n):
    t = round(start + i / fps, 6)
    _crop2x(look(a, t)).save(str(tmpdir / f"{i:04d}.png"))

if shutil.which("ffmpeg"):
    mp4 = OUT / "welcome-demo.mp4"
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

for name in ("welcome-strip.png", "welcome-demo.mp4"):
    p = OUT / name
    if p.is_file():
        print(
            f"  sha256 {name}: {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  ({p.stat().st_size} bytes)"
        )
