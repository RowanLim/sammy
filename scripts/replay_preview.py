#!/usr/bin/env python
"""历史回放的判据图（一条命令可重生成）。

为什么要有图：回放这件事的价值全在「时间真的推了」——
而这句话用文字说三遍也不如把驱力/心情两条曲线画出来看一眼：
一天不交互精力掉到睡着、被搭理了又涨回来，形状对了一看就知道。

图里三条通道（都是真的跑出来的 `ReplayReport`，不是手画的）：
- 精力（驱力）：一天不交互会掉到睡着线以下，然后用睡眠时间把自己充回来；
- 无聊（驱力）：没人理就涨、被搭理就掉到 0；
- 心情（底色）：没人理慢慢往下走（有下限，不会变成怨妇）。

口径：回放的时间台从真实时钟起步（理由见 replay.py 顶部），图上画的是
「回放里过了多少小时」。素材里用的是一段合成流水（模拟「几天里偶尔开机」
的真实形状），因为真实流水只有十几条、画不出形状。
"""

from __future__ import annotations

import pathlib
import sys
from itertools import pairwise

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from sammy import replay
from sammy.replay import Step

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1100, 560
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
GRID = QColor("#1d2f24")
ENERGY = QColor("#e8c05a")
BOREDOM = QColor("#6fb3d2")
MOOD = QColor("#d97fa6")
SLEEP = QColor("#3a5a44")

app = QApplication(sys.argv[:1])


def synthetic_days() -> list[Step]:
    """一段「几天里偶尔开机」的流水形状：每天你来一两句，中间大段没人理。

    时间点从真实的 8 小时封顶规则走（`steps_from_rows` 会压），
    所以这条序列跟真实流水走的是同一条路。
    """
    rows: list[dict] = []
    t = 0.0
    rows.append({"t": t, "role": "user", "text": "你在干嘛呀"})
    for _ in range(4):
        t += 3 * 3600.0  # 你走了三小时（一个白天）
        rows.append({"t": t, "role": "assistant", "text": "…", "kind": "proactive"})
        t += 5 * 3600.0  # 夜里到第二天早上
        rows.append({"t": t, "role": "assistant", "text": "…", "kind": "proactive"})
        t += 2 * 3600.0
        rows.append({"t": t, "role": "user", "text": "早"})
        t += 2 * 3600.0
        rows.append({"t": t, "role": "user", "text": "在忙"})
    return replay.steps_from_rows(rows)


def draw_chart(rep: replay.ReplayReport) -> QImage:
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pad_l, pad_t, pad_r, pad_b = 70, 78, 210, 56
    x0, y0 = pad_l, pad_t
    x1, y1 = W - pad_r, H - pad_b

    p.setPen(TITLE)
    p.setFont(QFont("", 17))
    p.drawText(pad_l, 32, "历史回放：把「过了几天」压成几十秒")
    p.setFont(QFont("", 12))
    p.setPen(SUB)
    real_lines = [
        f"回放 {rep.steps} 步 · 时间轴 {rep.hours:.1f} 小时",
        "同一套代码路径：时间喂给驱力与心情，",
        "不碰系统时钟、不写真实状态",
    ]
    y = 52
    for line in real_lines:
        p.drawText(pad_l, y, line)
        y += 17

    # 网格
    p.setPen(QPen(GRID, 1))
    for i in range(5):
        yy = y0 + (y1 - y0) * i / 4
        p.drawLine(x0, int(yy), x1, int(yy))

    states = rep.states
    total = max(1e-6, states[-1]["t"])
    for s in states:
        s["_x"] = x0 + (x1 - x0) * (s["t"] / total)

    # 睡着段：整段涂一条浅色带
    for a, b in pairwise(states):
        if a["asleep"]:
            p.fillRect(
                QRectF(a["_x"], y0, max(1.0, b["_x"] - a["_x"]), y1 - y0),
                SLEEP,
            )

    def curve(key: str, color: QColor, width: int) -> None:
        p.setPen(QPen(color, width))
        prev = None
        for s in states:
            pt = (s["_x"], y1 - (y1 - y0) * (s[key] + 0.5) / 1.5)
            if prev is not None:
                p.drawLine(int(prev[0]), int(prev[1]), int(pt[0]), int(pt[1]))
            prev = pt

    curve("energy", ENERGY, 3)
    curve("boredom", BOREDOM, 3)

    # 心情单独一条（范围 -0.5..0.5）
    p.setPen(QPen(MOOD, 2))
    prev = None
    for s in states:
        pt = (s["_x"], y1 - (y1 - y0) * (s["valence"] + 0.5))
        if prev is not None:
            p.drawLine(int(prev[0]), int(prev[1]), int(pt[0]), int(pt[1]))
        prev = pt

    # 图例
    p.setFont(QFont("", 12))
    ly = pad_t + 10
    for color, name in (
        (ENERGY, "精力（睡着线以下就睡过去）"),
        (BOREDOM, "无聊（没人理就涨）"),
        (MOOD, "心情（有下限）"),
    ):
        p.fillRect(QRectF(x1 + 22, ly - 9, 12, 12), color)
        p.setPen(TITLE)
        p.drawText(x1 + 42, ly + 1, name)
        ly += 26
    p.setPen(SUB)
    p.drawText(x1 + 22, ly + 16, "浅色带 = 时间轴")
    p.drawText(x1 + 22, ly + 34, "上它自己睡着了")

    # 轴
    p.setPen(QPen(SUB, 1))
    p.drawLine(x0, y0, x0, y1)
    p.drawLine(x0, y1, x1, y1)
    p.setFont(QFont("", 11))
    for i in range(5):
        h = total * i / 4
        xx = x0 + (x1 - x0) * i / 4
        p.drawText(int(xx) - 12, y1 + 20, f"{h:.0f}h")
    p.end()
    return img


steps = synthetic_days()
rep = replay.replay(steps, brain=None, workdir=pathlib.Path("/tmp/sammy-replay-chart"))
img = draw_chart(rep)
img.save(str(OUT / "replay-chart.png"))

d = rep.as_dict()
print(f"  时间轴 {d['hours']:.1f} 小时 · 帧 {len(d['states'])} 个")
print(f"  精力最低 {d['energy_min']:.2f} · 心情 {d['valence_min']:+.2f} ~ {d['valence_max']:+.2f}")
print(f"  时间轴上睡着过：{d['slept_once']} · 结束时{'睡着' if d['asleep_at_end'] else '醒着'}")
print(f"  图: {OUT / 'replay-chart.png'}")
