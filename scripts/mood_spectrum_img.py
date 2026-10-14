#!/usr/bin/env python3
"""心情全谱的素材图：两根轴拼成一张 5 x 5 的表。

为什么出图：一张 5 x 5 的表在文字里看不出**形状** —— 哪些格子热、
哪些冷、中间那条平常横带在哪儿，一眼看过去才看得清。
格子里的字**从 src/sammy/mood.py 的真表读**（M.SPECTRUM），不是手画的 ——
图上画的 = 代码里的 = 判据钉的，三处同一份来源。

用法：.venv/bin/python scripts/mood_spectrum_img.py
"""

import pathlib
import sys

ROOT = pathlib.Path("/Volumes/Mac mini/Max agent/Sammy")
sys.path.insert(0, str(ROOT / "src"))
from sammy import mood as M

W, H = 1180, 740
x0, y0 = 190, 160
cw, ch = 186, 92
parts = []


def add(s):
    parts.append(s)


add('<?xml version="1.0" encoding="UTF-8"?>')
add('<svg xmlns="http://www.w3.org/2000/svg" width="1180" height="740" viewBox="0 0 1180 740">')
add('<rect width="1180" height="740" fill="#0a120d"/>')
add(
    '<text x="60" y="58" font-family="Helvetica" font-size="30" fill="#c8e6cf">Sammy 的心情全谱：两根轴合起来才是一个谱</text>'
)
add(
    '<text x="60" y="92" font-family="Helvetica" font-size="17" fill="#5f8a6c">列 = 过得好不好（valence）· 行 = 热不热闹（spirit）· 一格一个说人话的名字</text>'
)
MOOD = ("低落", "有点蔫", "平静", "不错", "很好")
SPIRIT = ("走神", "偏蔫", "平常", "偏活", "兴奋")
COLORS = ("#6fb3d2", "#7fd8a0", "#9fb8a8", "#e8c05a", "#f0a35e")
for c in range(5):
    x = x0 + c * cw
    add(
        f'<text x="{x + cw // 2}" y="140" font-family="Helvetica" font-size="18" fill="#c8e6cf" text-anchor="middle">{MOOD[c]}</text>'
    )
for r in range(5):
    y = y0 + (4 - r) * ch
    add(
        f'<text x="176" y="{y + ch // 2 + 6}" font-family="Helvetica" font-size="18" fill="#c8e6cf" text-anchor="end">{SPIRIT[r]}</text>'
    )
for r in range(5):
    for c in range(5):
        x = x0 + c * cw
        y = y0 + (4 - r) * ch
        col = COLORS[r]
        add(
            f'<rect x="{x + 4}" y="{y + 4}" width="{cw - 8}" height="{ch - 8}" rx="10" fill="#12211a" stroke="{col}" stroke-width="2"/>'
        )
        add(
            f'<text x="{x + cw // 2}" y="{y + ch // 2 + 7}" font-family="Helvetica" font-size="19" fill="{col}" text-anchor="middle">{M.SPECTRUM[r][c]}</text>'
        )
add("</svg>")
out = pathlib.Path(ROOT / "docs" / "8h-b2" / "mood-spectrum.svg")
out.write_text(chr(10).join(parts), encoding="utf-8")
print("wrote", out)
