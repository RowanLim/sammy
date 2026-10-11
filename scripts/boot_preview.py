#!/usr/bin/env python3
"""开机自检序列素材 —— 上电扫掠 / 自检行 / 唤醒淡入，离屏真窗口逐帧抓。

产物（进 docs/8h-b2/，随仓库走，Gitea 网页上直接看）：
- boot-strip.png  8 格关键帧（整窗 2 倍放大 + 时间与阶段标签）
- boot-zoom.png   自检行区域 3 倍放大两格（看像素网格与光标）
- boot-demo.mp4   整段约 3.3 秒（25fps，880x528 画布 + 底部字幕条）

用法:
    .venv/bin/python scripts/boot_preview.py

纪律：一条命令全部重生成。窗口随机全部钉种子（seed=7），抓帧按时间
升序进行 —— 纯函数时间轴，同一份代码重跑出的帧是同一份。
放大一律最近邻（平滑缩放会糊掉像素网格与扫描线，验收素材恰恰要看这些）。
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
os.environ["SAMMY_BOOT"] = "on"
os.environ["SAMMY_ANIM"] = "on"

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from sammy import boot

OUT = ROOT / "docs" / "8h-b2"
TMP = ROOT / ".tmp" / "boot"
FPS = 25
ZOOM = 2  # 整窗放大倍数
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")

STRIP = (
    (0.06, "t=0.06s · 上电：中心一条亮线"),
    (0.30, "t=0.30s · 亮带向上下展开"),
    (0.50, "t=0.50s · 扫掠收尾，屏幕渐暗"),
    (0.80, "t=0.80s · 自检第一行出现"),
    (1.40, "t=1.40s · 一行一行往下走"),
    (2.00, "t=2.00s · 六行到齐"),
    (2.80, "t=2.80s · 唤醒：日志让位，画面淡入"),
    (3.10, "t=3.10s · 交班前最后一帧"),
)

_app = QApplication.instance() or QApplication([])

from sammy import layout

layout.load_fonts()


def _fresh():
    from sammy import anim
    from sammy.pet import SammyWindow

    w = SammyWindow(autoconnect=False)
    for tm in (w.timer, w.anim_timer, w.heart, w.night):
        tm.stop()
    w.anim = anim.Animator(seed=7)
    w.anim_t = 1.0
    w.set_expression(3)
    w.status = "在线 · 1.8s"
    w.sammy_line = "嗯…我醒着呢。"
    w.finish_typing()  # 素材里的句子永远是一整句（U3 的纪律）
    # 素材脚本不碰真状态：关窗时的保存全换成空操作（素材不是它的一天）
    for name in ("_save_drives", "_save_attention", "_save_care", "_save_recall"):
        setattr(w, name, lambda: None)
    return w


def _grab2x(w) -> QImage:
    img = w.grab().toImage()
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


def _sub_for(t: float) -> str:
    n = 6
    fr = boot.frame_at(t, n)
    if fr.phase == "power":
        return "阶段 上电 · 亮带展开 " + str(int(fr.power * 100)) + "%"
    if fr.phase == "log":
        return "阶段 自检 · 已出现 " + str(fr.lines) + " 行 · 光标" + ("亮" if fr.cursor else "灭")
    if fr.phase == "wake":
        return "阶段 唤醒 · 淡入 " + str(int(fr.wake * 100)) + "%"
    return "阶段 就绪"


def build_strip() -> str:
    w = _fresh()
    try:
        if not w.begin_boot():
            raise SystemExit("开机开关没打开（SAMMY_BOOT）——素材需要它开着")
        t0 = w._boot_t0
        panels = []
        for t, label in STRIP:
            w.anim_t = t0 + t
            panels.append(_tile(_grab2x(w), label, _sub_for(t)))
        return _grid(
            "开机自检序列：上电扫掠 / 自检行 / 唤醒淡入（整段 3.22 秒）",
            "点一下可跳过 · SAMMY_BOOT=off 可关 · 真启动才播（快照 / 自检不播）",
            panels,
            4,
            OUT / "boot-strip.png",
        )
    finally:
        w.close()


def build_zoom() -> str:
    w = _fresh()
    try:
        if not w.begin_boot():
            raise SystemExit("开机开关没打开")
        t0 = w._boot_t0
        lay = w.lay
        crop = QRect(
            int((lay.panel.left() + 30) * w.scale),
            int((lay.panel.center().y() - 120) * w.scale),
            int(370 * w.scale),
            int(240 * w.scale),
        )
        panels = []
        plan = ((1.75, "t=1.75s · 四行已现（光标灭）"), (2.10, "t=2.10s · 五行已现（光标亮）"))
        for t, label in plan:
            w.anim_t = t0 + t
            img = w.grab().toImage()
            part = img.copy(crop)
            big = part.scaled(
                part.width() * 3, part.height() * 3, Qt.IgnoreAspectRatio, Qt.FastTransformation
            )
            panels.append(_tile(big, label, "最近邻 3 倍：字形落在像素网格上"))
        return _grid(
            "自检行放大：每个字都是 Sammy Pixel，光标在末行后面亮灭",
            "同一段绘制代码在 face-only 小屏上也长这样",
            panels,
            2,
            OUT / "boot-zoom.png",
        )
    finally:
        w.close()


def build_video() -> str:
    frames = Path(tempfile.mkdtemp(prefix="bootv-", dir=str(TMP)))
    total = boot.total_seconds(6)
    n = int(total * FPS) + 2
    caps = {
        "power": "上电扫掠：一条亮线从中间展开（老 CRT 的栅格动作）",
        "log": "自检：记忆 / 表情 / 外挂工具 / 大脑，一行一行报",
        "wake": "唤醒：日志让位，正常画面整体淡入",
        "done": "就绪 —— 和稳态逐像素接上。点一下可跳过整段",
    }
    w = _fresh()
    idx = 0
    try:
        if not w.begin_boot():
            raise SystemExit("开机开关没打开")
        t0 = w._boot_t0
        for i in range(n):
            t = i / FPS
            if t >= total and w._boot_t0 is not None:
                w._finish_boot()  # 到点交班（和真跑一致：输入框回来）
            w.anim_t = t0 + t
            img = _grab2x(w)
            cv = QImage(880, 528 + 36, QImage.Format_ARGB32)
            cv.fill(BG)
            p = QPainter(cv)
            p.drawImage((880 - img.width()) // 2, (528 - img.height()) // 2, img)
            p.setFont(QFont("", 13))
            p.setPen(SUB)
            p.drawText(12, 528 + 24, caps[boot.frame_at(t, 6).phase])
            p.end()
            if not cv.save(str(frames / (str(idx).zfill(5) + ".png"))):
                raise SystemExit("帧保存失败")
            idx += 1
    finally:
        w.close()

    out = OUT / "boot-demo.mp4"
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
        + " KB"
    )


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    print("  开机素材：")
    for line in (build_strip(), build_zoom(), build_video()):
        print("  ok " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
