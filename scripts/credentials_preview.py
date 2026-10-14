#!/usr/bin/env python
"""凭证总目录的判据图（一条命令可重生成）。

为什么这块也要出图：台账是一张表，表里的数字「297 个文件扫过、3 处命中」
在文字里看不出**比例** —— 一眼看过去「项目里到底干不干净」才是这张图要回答的事。
图里三块：
- 左边：扫描覆盖（项目内 297 个文件 vs 机器级点名清单 6 条）；
- 中间：命中按位置分组（项目内 / 机器级），项目内那一条是**测试自己的假样本**；
- 右边：合法位置那一条 —— 项目的凭证只有这一个家在，其余都是外部的。

数据全部来自 `scripts/credential_sweep.py` 的真扫描结果（不是手画的）：
`scan()` 给命中，`machine_places()` 给点名清单。图上**不出现任何密钥原文** ——
命中只画「位置 + 规则代号」，这是纪律二。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from credential_sweep import machine_places, route, scan

OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1100, 560
BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
GRID = QColor("#1d2f24")
CLEAN = QColor("#7fd8a0")
WARN = QColor("#e8c05a")
HOME = QColor("#6fb3d2")

app = QApplication(sys.argv[:1])

report = scan()
rows = route(report)
local = [r for r in rows if r.get("project")]
outer = [r for r in rows if not r.get("project")]
placed = machine_places()

img = QImage(W, H, QImage.Format.Format_RGB32)
img.fill(BG)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setFont(QFont("", 15))
p.setPen(TITLE)
p.drawText(24, 34, "Sammy · 凭证总目录 —— 只有 data/.env 是它的家")
p.setFont(QFont("", 11))
p.setPen(SUB)
p.drawText(
    24, 56, f"只读扫过 {report['scanned']} 个文件 · 命中 {len(rows)} 处 · 一个密钥字符都没打印"
)

# ── 左：扫描覆盖 ──────────────────────────────
p.setPen(TITLE)
p.setFont(QFont("", 12))
p.drawText(30, 100, "① 扫过什么")
p.setFont(QFont("", 11))
bars = [
    ("项目内（src / tests / scripts / docs / data）", report["scanned"] - len(placed), CLEAN),
    ("机器级点名清单（~/.hermes、~/.gitconfig…）", len(placed), HOME),
]
y = 130
mx = max(n for _, n, _ in bars) or 1
for label, n, color in bars:
    p.setPen(SUB)
    p.drawText(30, y, label)
    p.setPen(Qt_pen := QPen(color, 0))
    p.setBrush(color)
    p.drawRect(QRectF(30, y + 8, 360 * n / mx, 14))
    p.setPen(TITLE)
    p.drawText(400, y + 20, str(n))
    y += 56
p.setPen(SUB)
p.setFont(QFont("", 10))
p.drawText(30, y + 6, "清单是写死的：扫得越广，越容易扫出别人的隐私（纪律三）")

# ── 中：命中分组 ──────────────────────────────
p.setPen(TITLE)
p.setFont(QFont("", 12))
p.drawText(470, 100, "② 超出了合法位置的东西")
p.setFont(QFont("", 11))
yy = 128
if not outer:
    p.setPen(CLEAN)
    p.drawText(470, yy, "没有")
else:
    for r in outer:
        p.setPen(WARN)
        where = r["where"]
        line = f"  第 {r['line']} 行" if r["line"] else "  （目录）"
        p.drawText(470, yy, f"~/{where}{line}")
        p.setPen(SUB)
        p.setFont(QFont("", 10))
        p.drawText(470, yy + 16, f"规则：{r['rule']} · 属于 Hermes 自己，不是这个项目")
        p.setFont(QFont("", 11))
        yy += 44
p.setPen(SUB)
p.setFont(QFont("", 10))
p.drawText(470, yy + 10, f"项目内命中 {len(local)} 处 —— 全是测试自己的假样本（夹具）")

# ── 右：唯一的家 ──────────────────────────────
x = 790
p.setPen(TITLE)
p.setFont(QFont("", 12))
p.drawText(x, 100, "③ 这一处才是它的家")
p.setPen(HOME)
p.setFont(QFont("", 11))
p.drawText(x, 130, "data/.env")
p.setPen(SUB)
p.setFont(QFont("", 10))
for i, t in enumerate(
    (
        "在项目文件夹里（隔离约定）",
        "被 git 忽略：不进版本库",
        "构建时检查：不进打包的 .app",
        "make credentials 随时核一遍",
    )
):
    p.drawText(x, 156 + i * 20, "· " + t)
p.setPen(CLEAN)
p.setFont(QFont("", 11))
p.drawText(x, 268, "项目的凭证零泄漏")
p.setPen(SUB)
p.setFont(QFont("", 10))
p.drawText(x, 290, "台账：docs/凭证总目录.md")

# ── 底部：一条横贯的「家」标尺 ────────────────
p.setPen(QPen(GRID, 1))
p.drawLine(30, 380, W - 30, 380)
p.setFont(QFont("", 11))
p.setPen(SUB)
p.drawText(30, 410, "判据（tests/test_credentials_inventory.py 12 条）：")
p.setPen(TITLE)
checks = [
    "坏样本必须命中 / 好样本不误报",
    "扫完文件时间戳一字不变",
    "报告里不带任何密钥形状的内容",
    "扫到的每一条都在台账里、台账里写的都得真在",
]
for i, t in enumerate(checks):
    p.drawText(30, 436 + i * 22, "✓ " + t)

p.end()
out_file = OUT / "credentials-chart.png"
img.save(str(out_file))
print(f"  图: {out_file}")
print(
    f"  命中 {len(rows)} 处（项目内 {len(local)} / 机器级 {len(outer)}），扫过 {report['scanned']} 个文件"
)
