#!/usr/bin/env python
"""「桌上的一天」的判据图（一条命令可重生成）。

为什么要有图：这一天跑得快（几十秒），但它在跑什么**看不见** ——
图和数字放在一起才说得清「替它过了一天」是什么意思。

图里两条通道（都是真的跑出来的 `DayReport`，不是手画的）：
- 精力（上）：你走开就往下掉，掉到底自己睡过去，睡着时又充回来；
- 心情 + 无聊（下）：没人理心情慢慢往下走（有下限），被搭理就回来。

左下那行是判据数字（起止精力 / 最低 / 睡过几次），右边是这一天的拍子
（你说话 / 戳它 / 没人理）—— 有它在，图上哪一段抖一下都对得上原因。

隔离：替身写在 `data/replica/`，真实 data/ 一字不动（跑完会自己核一遍）。
"""

from __future__ import annotations

import pathlib
import sys
from itertools import pairwise

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from sammy import replica

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1100, 560
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
GRID = QColor("#1d2f24")
ENERGY = QColor("#e8c05a")
MOOD = QColor("#d97fa6")
BOREDOM = QColor("#6fb3d2")
SLEEP = QColor("#3a5a44")
MARK = QColor("#7fd8a0")

app = QApplication(sys.argv[:1])


def draw_chart(rep) -> QImage:
    d = rep.as_dict()
    states = d["states"]
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(QFont("", 15))
    p.setPen(TITLE)
    p.drawText(24, 34, "Sammy · 桌上的一天（复刻）—— 真实 data/ 一字不动")
    p.setFont(QFont("", 11))
    p.setPen(SUB)
    p.drawText(24, 56, f"时间轴 {d['hours']:.1f} 小时 · {d['beats']} 拍 · 共 {len(states)} 帧")

    pad_l, pad_r, pad_t = 70, 300, 90
    x0, x1 = pad_l, W - pad_r
    top_y0, top_y1 = pad_t, pad_t + 240
    bot_y0, bot_y1 = pad_t + 290, H - 60
    pad_t = pad_t
    total = max(1e-6, states[-1]["t"])
    for s in states:
        s["_x"] = x0 + (x1 - x0) * (s["t"] / total)

    # 睡着段：一条浅色带（时间轴上）
    for a, b in pairwise(states):
        if a["asleep"]:
            p.fillRect(QRectF(a["_x"], top_y0, max(1.0, b["_x"] - a["_x"]), bot_y1 - top_y0), SLEEP)

    # 网格
    p.setPen(QPen(GRID, 1))
    for i in range(5):
        y = top_y0 + (top_y1 - top_y0) * i / 4
        p.drawLine(int(x0), int(y), int(x1), int(y))
        p.setPen(SUB)
        p.setFont(QFont("", 10))
        p.drawText(x0 - 58, int(y) + 4, f"{(1.0 - i * 0.25):.2f}")
        p.setPen(QPen(GRID, 1))
    p.setPen(SUB)
    p.drawText(x0 - 58, top_y0 - 10, "精力")

    def curve(y0, y1, key, color, width, scale=1.0, offset=0.0):
        p.setPen(QPen(color, width))
        prev = None
        for s in states:
            v = (s[key] + offset) / scale
            pt = (s["_x"], y1 - (y1 - y0) * max(0.0, min(1.0, v)))
            if prev is not None:
                p.drawLine(int(prev[0]), int(prev[1]), int(pt[0]), int(pt[1]))
            prev = pt

    # 精力（0..1）
    curve(top_y0, top_y1, "energy", ENERGY, 3)
    # 睡着线（ASLEEP_BELOW = 0.12）
    from sammy.drives import ASLEEP_BELOW

    y_sleep = top_y1 - (top_y1 - top_y0) * ASLEEP_BELOW
    dash = QPen(QColor("#c0616a"), 1)
    dash.setStyle(Qt.PenStyle.DashLine)
    p.setPen(dash)
    p.drawLine(int(x0), int(y_sleep), int(x1), int(y_sleep))
    p.setPen(QColor("#c0616a"))
    p.setFont(QFont("", 10))
    p.drawText(int(x0) + 6, int(y_sleep) - 4, f"睡着线 {ASLEEP_BELOW}")

    # 心情：-0.5..0.5 映射到下半格
    p.setPen(SUB)
    p.setFont(QFont("", 10))
    p.drawText(x0 - 58, bot_y0 - 10, "心情 / 无聊")
    curve(bot_y0, bot_y1, "valence", MOOD, 2, scale=1.0, offset=0.5)
    curve(bot_y0, bot_y1, "boredom", BOREDOM, 2)

    # 横轴
    p.setPen(QPen(SUB, 1))
    p.drawLine(x0, top_y0, x0, bot_y1)
    p.drawLine(x0, bot_y1, x1, bot_y1)
    p.setFont(QFont("", 10))
    for i in range(5):
        h = total * i / 4
        xx = x0 + (x1 - x0) * i / 4
        p.drawText(int(xx) - 10, bot_y1 + 18, f"{h:.1f}h")

    # 拍子标记（你说话 = 绿点，戳它 = 蓝点）
    for s in states:
        if s["kind"] == "greet":
            p.setPen(QPen(MARK, 2))
            p.drawEllipse(QRectF(s["_x"] - 4, top_y1 - 4, 8, 8))
        elif s["kind"] == "poke":
            p.setPen(QPen(BOREDOM, 2))
            p.drawEllipse(QRectF(s["_x"] - 4, top_y1 - 4, 8, 8))

    # 右侧：判据数字 + 图例
    p.setPen(TITLE)
    p.setFont(QFont("", 12))
    rows = [
        ("起 → 止 精力", f"{states[0]['energy']:.2f} → {states[-1]['energy']:.2f}"),
        ("最低精力", f"{d['energy_min']:.2f}"),
        ("心情区间", f"{d['valence_min']:+.2f} ~ {d['valence_max']:+.2f}"),
        (
            "睡着过",
            ("是" if d["slept_once"] else "否")
            + f"（{d['sleep_bouts']} 次 / {d['sleep_hours']:.2f}h）",
        ),
        ("你说话 / 戳它", f"{d['greets']} / {d['pokes']}"),
        ("崩 / 空", f"{d['crashes']} / 0"),
        ("真实数据动过", "没有（逐字节）" if not d.get("real_data_touched") else "有 ⚠️"),
    ]
    y = pad_t + 6
    for k, v in rows:
        p.setPen(SUB)
        p.setFont(QFont("", 11))
        p.drawText(x1 + 22, y, k)
        p.setPen(TITLE)
        p.setFont(QFont("", 12))
        p.drawText(x1 + 22, y + 17, v)
        y += 40

    p.setFont(QFont("", 11))
    ly = y + 6
    for color, name in (
        (ENERGY, "精力"),
        (MOOD, "心情"),
        (BOREDOM, "无聊"),
        (MARK, "你说话"),
        (SLEEP, "睡着的时间段"),
    ):
        p.fillRect(QRectF(x1 + 22, ly - 9, 12, 12), color)
        p.setPen(TITLE)
        p.drawText(x1 + 42, ly + 1, name)
        ly += 24
    p.end()
    return img


before = {p.name: p.read_bytes() for p in sorted(replica.data_dir().iterdir()) if p.is_file()}
rep = replica.Replica()
out = rep.run(days=1, seed=7)
out.real_data_touched = rep.real_untouched(before)
img = draw_chart(out)
out_file = OUT / "day-chart.png"
img.save(str(out_file))
for line in out.human_lines():
    print("  " + line)
print(f"  图: {out_file}")
