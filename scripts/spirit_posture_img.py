#!/usr/bin/env python3
"""劲头也管姿态：两根轴各管一种形变（自选小步·第二十九次）。

为什么出图：两根轴的区别是形状而不是数值 ——
「小一号」与「塌一点」在文字里看不出差别，画出来一眼分得清。
曲线上的数从 src/sammy/anim.py 的真函数读（spirit_posture / mood_shrink），不是手画的。

用法：.venv/bin/python scripts/spirit_posture_img.py
"""

import pathlib
import sys

ROOT = pathlib.Path("/Volumes/Mac mini/Max agent/Sammy")
sys.path.insert(0, str(ROOT / "src"))
from sammy import anim

parts = []


def add(s):
    parts.append(s)


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;")


add('<?xml version="1.0" encoding="UTF-8"?>')
add('<svg xmlns="http://www.w3.org/2000/svg" width="1180" height="700" viewBox="0 0 1180 700">')
add('<rect width="1180" height="700" fill="#0a120d" />')
add(
    '<text x="60" y="58" font-family="Helvetica" font-size="30" fill="#c8e6cf">两根轴，两种形变：心情管大小，劲头管挺不挺得住</text>'
)
add(
    '<text x="60" y="92" font-family="Helvetica" font-size="17" fill="#5f8a6c">曲线上的数从 anim.spirit_posture / anim.mood_shrink 真函数读出</text>'
)

PX0 = 120
PY0 = 600
PW = 980
PH = 430
VLO = -1.0
VHI = 1.0
YLO = 0.93
YHI = 1.035


def px(v):
    return PX0 + (v - VLO) / (VHI - VLO) * PW


def py(y):
    return PY0 - (y - YLO) / (YHI - YLO) * PH


add(
    f'<line x1="{px(VLO):.1f}" y1="{py(1.0):.1f}" x2="{px(VHI):.1f}" y2="{py(1.0):.1f}" stroke="#2a4a38" stroke-width="2" />'
)

add(
    f'<line x1="{px(VLO):.1f}" y1="{py(YLO):.1f}" x2="{px(VLO):.1f}" y2="{py(YHI):.1f}" stroke="#3a6a50" stroke-width="3" />'
)

N = 121
pts_s = []
pts_m = []
i = 0
while i < N:
    v = -1.0 + 2.0 * i / (N - 1.0)
    pts_s.append((px(v), py(anim.spirit_posture(v))))
    pts_m.append((px(v), py(anim.mood_shrink(v))))
    i = i + 1


def poly(pts, color):
    segs = []
    for p in pts:
        segs.append(f"{p[0]:.1f},{p[1]:.1f}")
    d = " ".join(segs)
    add(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="3.5" />')


poly(pts_s, "#6fb3d2")
poly(pts_m, "#e8c05a")


# 图例：两条线各是什么
add(
    '<text x="120" y="146" font-family="Helvetica" font-size="18" fill="#6fb3d2" text-anchor="start">蓝线 = 心情轴 mood_shrink：越低落整个人越小一号（宽高一起缩）</text>'
)
add(
    '<text x="120" y="168" font-family="Helvetica" font-size="18" fill="#e8c05a" text-anchor="start">金线 = 劲头轴 spirit_posture：越没劲整个人塌一点（只压纵向）</text>'
)
add(
    '<text x="120" y="196" font-family="Helvetica" font-size="16" fill="#5f8a6c" text-anchor="start">两线在 0 点都恒等于 1.0（不动）；高劲头那头只抬 2.5%，只有塌的一半</text>'
)
add("</svg>")

out = ROOT / "docs" / "8h-b2" / "spirit-posture.svg"
out.write_text(chr(10).join(parts), encoding="utf-8")
print("wrote", out)
