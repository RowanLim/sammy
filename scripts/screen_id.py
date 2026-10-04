#!/usr/bin/env python3
"""在指定屏幕上开一个全屏大红窗口 —— 用来确认「X 里的这个名字」对应「哪块实体屏」。

为什么需要它：X 的连接器名字（DP-1 / HDMI-0）和"哪块屏是我的小屏"之间
没有任何可靠的对应关系（那块小屏甚至报不出 EDID）。光看 xrandr 猜，
猜错就是把窗口开到主屏上 —— 实测已经错过一次。

用法（在那台机器上）:
  DISPLAY=:1 .venv/bin/python scripts/screen_id.py DP-1          # 显示 12 秒
  DISPLAY=:1 .venv/bin/python scripts/screen_id.py HDMI-0 20     # 显示 20 秒
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

# ⚠️ 必须先补上项目自带的原生库路径，否则 Qt 的 xcb 插件载不起来：
#    "Could not load the Qt platform plugin xcb" + 核心转储。
#    （走 run.sh 时它会自动加；直接调 .venv/bin/python 就得自己加 —— 我踩过一次。）
_libs = sorted({str(p.parent) for p in (_ROOT / "vendor" / "lib").rglob("*.so*")})
if _libs:
    _env = [*_libs, os.environ.get("LD_LIBRARY_PATH", "")]
    os.environ["LD_LIBRARY_PATH"] = ":".join(_env).strip(":")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from sammy import screen


class Big(QWidget):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#d81b1b"))  # 大红
        p.setPen(QColor("#ffffff"))
        p.setFont(QFont("Sans", max(24, self.height() // 6), QFont.Bold))
        p.drawText(self.rect(), Qt.AlignCenter, self.label)
        p.setFont(QFont("Sans", max(12, self.height() // 20)))
        p.drawText(
            self.rect().adjusted(0, 0, 0, -20),
            Qt.AlignHCenter | Qt.AlignBottom,
            "如果你在这块屏上看到这块红 —— 那它就是这个名字的屏",
        )


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "DP-1"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0

    app = QApplication(sys.argv[:1])
    try:
        s = screen.resolve_screen(name)
    except RuntimeError as e:
        print(f"❌ {e}")
        return 2
    print(f"在 {s['name']}（{s['width']}×{s['height']} @ {s['x']},{s['y']}）上显示 {secs:.0f} 秒")

    w = Big(s["name"])
    w.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    w.setGeometry(s["x"], s["y"], s["width"], s["height"])
    w.show()
    QTimer.singleShot(int(secs * 1000), app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
