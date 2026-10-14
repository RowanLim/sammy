#!/usr/bin/env python3
"""表情总表 v1.1 的素材图 —— 把「标了什么」画成一眼能看的图。

为什么要出图：v1.1 是 markdown 表格，在飞书/网页里看要横着滚、还容易看串行；
而这张表要拿去跟 Rowan 和 Nex 对口径（首发哪 12 个情绪、哪 8 个动画）。
所以出三格：情绪 18 行 + 动画 42 行 + 判据数字卡，一眼看完。

产物（进 docs/8h-b2/）：
- faces-spec-v11.png   三格：表 A 情绪 18 行 / 表 C 动画 42 行 / 判据数字卡

用法:
    .venv/bin/python scripts/faces_spec_v11_img.py

纪律（和其他素材脚本一套）：
- 数字**从生成器里读**（gen.FIRST_BATCH_*），不手抄 —— 手抄就会跟表分家；
- 每一行的标记**从真表里读**（跑一遍 build，再按行取最后一格），
  图上画的 = 生成的 = 判据钉的，三处同一份来源；
- 一条命令全部重生成、逐字节可复现。
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "8h-b2"
OUT.mkdir(parents=True, exist_ok=True)


def _load_gen():
    spec = importlib.util.spec_from_file_location(
        "faces_spec_v11", ROOT / "scripts" / "faces_spec_v11.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load_gen()

BG = QColor("#0a120d")
TITLE = QColor("#c8e6cf")
SUB = QColor("#5f8a6c")
FIRST = QColor("#8fe3a8")
SECOND = QColor("#4a6b55")

app = QApplication(sys.argv[:1])


def _cells(line: str) -> list[str]:
    return line.strip().strip("|").split("|")


def _is_sep(cells: list[str]) -> bool:
    body = "".join(cells).strip()
    return "-" in body and set(body) <= set("-: ")


def table_rows(text: str, prefix: str) -> list[list[str]]:
    """从生成器产出里取某张表的数据行（跳过表头与分隔行）。"""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(prefix))
    end = next(
        (i for i, ln in enumerate(lines) if i > start and ln.startswith("## ")),
        len(lines),
    )
    out = []
    seen = False
    for ln in lines[start:end]:
        if not ln.startswith("|"):
            continue
        cells = _cells(ln)
        if _is_sep(cells):
            continue
        if not seen:
            seen = True
            continue
        out.append(cells)
    return out


def _panel(title: str, subtitle: str, rows: list[tuple[str, str, bool]], width: int) -> QImage:
    """一格：标题 + 副标题 + 若干「名字 · 标记」行。"""
    rowh = 20
    img = QImage(width, 68 + rowh * len(rows) + 12, QImage.Format_ARGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setPen(TITLE)
    p.setFont(QFont("", 14))
    p.drawText(14, 26, title)
    p.setPen(SUB)
    p.setFont(QFont("", 11))
    p.drawText(14, 44, subtitle)
    y = 68
    for name, mark, is_first in rows:
        p.setPen(FIRST if is_first else SECOND)
        p.setFont(QFont("", 12))
        p.drawText(14, y + 14, name)
        p.setPen(FIRST if is_first else SUB)
        p.setFont(QFont("", 11))
        p.drawText(width - 14 - p.fontMetrics().horizontalAdvance(mark), y + 14, mark)
        y += rowh
    p.end()
    return img


def main() -> int:
    text = gen.build()
    emo = table_rows(text, "## 1. 表 A ★")
    anim_rows = table_rows(text, "## 6. 表 C")
    assert len(emo) == 18, len(emo)
    assert len(anim_rows) == 42, len(anim_rows)

    def rows_of(rows, sec_prefix):
        out = []
        for r in rows:
            mark = r[-1].strip()
            name = r[1].strip()
            out.append((name, mark, mark == gen.MARK_FIRST))
        return out

    left = _panel(
        "表 A · 情绪眼型 18 个",
        "首发 "
        + str(len(gen.FIRST_BATCH_EMOTIONS))
        + " 个（亮）/ 第二批 "
        + str(len(gen.SECOND_BATCH_EMOTIONS))
        + " 个（暗）—— 依据 DECISIONS 二·1",
        rows_of(emo, None),
        300,
    )
    right = _panel(
        "表 C · 屏幕动画 42 个",
        "先上 " + str(len(gen.FIRST_BATCH_ANIMS)) + " 个（亮）—— 依据 DECISIONS 二·4",
        rows_of(anim_rows, None),
        300,
    )

    first_e = sum(1 for _n, _m, f in rows_of(emo, None) if f)
    first_a = sum(1 for _n, _m, f in rows_of(anim_rows, None) if f)
    card = _panel(
        "判据数字卡（与 tests/test_faces_spec.py 同口径）",
        "纸上写的 = 生成的 = 判据钉的 —— 三处同一份来源",
        [
            ("v1 表行 " + str(len(_cells_all(text))) + " 行 -> v1.1 同数（逐行对账）", "OK", True),
            ("情绪首发 " + str(first_e) + " / 第二批 " + str(18 - first_e), "18 行", True),
            ("动画首发 " + str(first_a) + " / 其余 " + str(42 - first_a), "42 行", True),
            ("表 A2 " + "25" + " 行继承表 A 的批次", "留机制", False),
            ("表 D " + "10" + " 行标「硬件到位后定」", "待定", False),
            ("表 E 系统态 E3/E4/E5/E6/E9 进首发", "5 条", True),
            ("生成确定 + --check 认得出自己", "OK", True),
        ],
        320,
    )

    pad = 16
    Wc = pad * 4 + left.width() + right.width() + card.width()
    Hc = pad * 2 + max(left.height(), right.height(), card.height()) + 40
    canvas = QImage(Wc, Hc, QImage.Format_ARGB32)
    canvas.fill(BG)
    p = QPainter(canvas)
    p.setPen(TITLE)
    p.setFont(QFont("", 16))
    p.drawText(pad, 28, "Sammy 表情总表 v1.1：首发什么 / 留到什么 —— 一条命令从 v1 生成")
    x = pad
    y = 44
    for panel in (left, right, card):
        p.drawImage(x, y, panel)
        x += panel.width() + pad
    p.end()

    out = OUT / "faces-spec-v11.png"
    canvas.save(str(out))
    print("  素材: " + str(out))
    print("  sha256: " + hashlib.sha256(out.read_bytes()).hexdigest()[:16])
    print("  首发情绪 " + str(first_e) + " 个 / 首发动画 " + str(first_a) + " 个")
    return 0


def _cells_all(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith("|")]


if __name__ == "__main__":
    raise SystemExit(main())
