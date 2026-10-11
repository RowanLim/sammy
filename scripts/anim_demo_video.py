#!/usr/bin/env python3
"""把动图表情渲染成一段视频（离屏逐帧抓窗口，再用 ffmpeg 合成）。

为什么需要它：小屏那头可能锁屏/息屏（实测：会话锁着时整个屏都不刷新，
录出来 300 帧零变化），但**锁屏不代表功能没做**。
这个脚本绕开显示器 —— 直接在离屏画布上按时间推进 `anim_t` 抓帧，
走的是和真实窗口**同一段绘制代码**，所以看到的动效就是小屏上的动效。

用法:
    .venv/bin/python scripts/anim_demo_video.py                # 默认几个表情
    .venv/bin/python scripts/anim_demo_video.py --exprs 21 10 # 指定编号
    .venv/bin/python scripts/anim_demo_video.py --out x.mp4 --scale 2
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from sammy.expressions import name_of
from sammy.pet import SammyWindow

DEFAULT_EXPRS = [21, 10, 6, 1, 4, 2]  # 爱心 / 生气 / 伤心 / 睡眠 / 开心 / 普通
FPS = 30
SECONDS = 2.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exprs", type=int, nargs="*", default=DEFAULT_EXPRS)
    ap.add_argument("--out", default=str(ROOT / ".tmp" / "anim-demo.mp4"))
    ap.add_argument("--scale", type=int, default=2, help="放大倍数（像素画放大更好看）")
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])  # noqa: F841
    win = SammyWindow(autoconnect=False)
    win.resize(440, 264)
    win.show()

    tmp = Path(tempfile.mkdtemp(prefix="animframes-"))
    n, idx = int(FPS * SECONDS), 0
    try:
        for expr in args.exprs:
            win.anim_t = 0.0  # 先把时钟拨回片头：交叉淡化从这一段开头开始
            win.set_expression(expr)
            for i in range(n):
                win.anim_t = i / FPS
                win.grab().save(str(tmp / f"{idx:05d}.png"))
                idx += 1
            print(f"  ✅ 表情 {expr:>2} {name_of(expr):<4} → {n} 帧")

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            str(tmp / "%05d.png"),
            "-vf",
            f"scale=iw*{args.scale}:ih*{args.scale}:flags=neighbor",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            str(out),
        ]
        subprocess.run(cmd, check=True)
        size = out.stat().st_size // 1024
        print(f"\n  视频: {out}（{idx} 帧 / {idx / FPS:.1f}s / {size} KB）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
