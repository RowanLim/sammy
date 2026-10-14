#!/usr/bin/env python3
"""表情总表 v1.1 生成器：把 v1 的正文按 v1.1 的「已定」口径标注一遍。

为什么要写成脚本而不是手改一份 v1.1：
    DECISIONS 待执行清单第 1 项要的是「把第 1 条选定的 17 个标出来、第 4 条选定的 8 个动画标注、
    第 2/3/5/6/7 条写进表头已定说明」。手改的副本会立刻和 v1 分家 —— 参考仓库改一条参数、
    我们改一条选型，两边就对不上账，而这种文档漂移是没人会发现的（表格不会报错）。
    所以：**v1 只读、逐字节原样带过来**，只做三类机器可查的改动 ——
      ① 7 张表的表头单元格加一列「v1.1」；② 每行那一列填一个可机器校验的标记；③ 顶部/尾部各加一段。
    改完由 tests/test_faces_spec.py 逐条对账：表格结构没被改坏、标记和 docs/DECISIONS.md 一致、
    v1 的每一行都还在。文档里说的话，测试能证明。

用法:
    .venv/bin/python scripts/faces_spec_v11.py            # 生成 docs/表情总表_v1.1.md
    .venv/bin/python scripts/faces_spec_v11.py --check    # 只对账，不写盘（CI 用）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import itertools

ROOT = Path(__file__).resolve().parent.parent
V1 = ROOT / "docs" / "表情总表_v1.md"
V11 = ROOT / "docs" / "表情总表_v1.1.md"

HEADER = "v1.1"

# ── DECISIONS §二 第 1 条的选定集合（17 个 = 12 情绪 + 5 系统态）──
# 情绪名字面量按 v1 表 A 的写法（英文名 + 中文），别在这里改措辞 —— 改措辞就改不中行了。
FIRST_BATCH_EMOTIONS = (
    "Normal",
    "Happy",
    "Glee",
    "Sad",
    "Angry",
    "Surprised",
    "Sleepy",
    "Squint",
    "Worried",
    "Annoyed",
    "Skeptic",
    "Focused",
)
# 系统态 5 条不落在表 A（它们是 §9 补位表的 E3/E4/E5/E6/E9），表 A 里按「第二批」标。
SECOND_BATCH_EMOTIONS = (
    "Furious",
    "Frustrated",
    "Unimpressed",
    "Suspicious",
    "Scared",
    "Awe",
)
# DECISIONS §二 第 4 条：42 个屏幕动画先上这 8 个（表 C 的名字列写法）
FIRST_BATCH_ANIMS = (
    "thinking",
    "battery",
    "alarm",
    "wifi",
    "wait",
    "ok",
    "heart",
    "love",
)

# ── §9 表 E（12 条补位）的处置：系统态 5 条进首发；其余 7 条按性质分流 ──
# 这张表是「分批下达」的工具，不是删减 —— 每条都写明为什么现在做/不做。
TABLE_E = {
    "E1": "首发",
    "E2": "首批（同唤醒链路）",
    "E3": "首发（系统态）",
    "E4": "首发（系统态）",
    "E5": "首发（系统态）",
    "E6": "首发（系统态）",
    "E7": "首批（同唤醒链路）",
    "E8": "等硬件（触摸/惯性传感器）",
    "E9": "首发（系统态）",
    "E10": "首批（接 xiaozhi 状态机即可）",
    "E11": "首批（升级流程落地时）",
    "E12": "首批（ASR 低置信通路）",
}

# ── 按表标题给每张表配「怎么标」──
# mode=first_batch：行里点名在选定集合内 → 首发，否则 → 第二批
# mode=table_e：按行首 # 查 TABLE_E
TABLE_PLANS = (
    ("## 1. 表 A", "emotion", "explicit", None),
    ("## 2. 表 A2", "emotion", "inherit", None),
    ("## 6. 表 C", "anim", "explicit", None),
    ("## 7. 表 D", None, "pending", None),
    ("## 9. 表 E", None, "table_e", None),
)

MARK_FIRST = "✅ 首发"
MARK_SECOND = "第二批"
MARK_TODO = "硬件到位后定"
MARK_KEEP = "留机制，不列首发"


def _cells(line: str) -> list[str]:
    """把一行 markdown 表格行拆成单元格（保留原有前后空白）。"""
    return line.strip().strip("|").split("|")


def _rebuild(cells: list[str]) -> str:
    return "|" + "|".join(cells) + "|"


def _is_sep(cells: list[str]) -> bool:
    body = "".join(cells).strip()
    return "-" in body and set(body) <= set("-: ")


def _is_numbered_row(cells: list[str]) -> bool:
    return cells[0].strip().isdigit()


def _name_cell(cells: list[str]) -> str:
    return cells[1].strip()


def mark_for_emotion(name_cell: str) -> str:
    for en in FIRST_BATCH_EMOTIONS:
        if name_cell.startswith(en + " "):
            return MARK_FIRST
    for en in SECOND_BATCH_EMOTIONS:
        if name_cell.startswith(en + " "):
            return MARK_SECOND
    raise SystemExit("表 A 这行认不出来是谁：" + name_cell)


def mark_for_anim(name_cell: str) -> str:
    head = name_cell.split(" ")[0].strip()
    if head in FIRST_BATCH_ANIMS:
        return MARK_FIRST
    return MARK_SECOND


# 按谁的名字认人：情绪表查情绪名，动画表查动画名。
# 上一版靠「行首是不是数字」猜 —— 表 A 的行首是序号、表 C 的行首是英文名，
# 条件是反的，于是表 C 的第一行被拿去查情绪表，直接报「认不出来」。
# 表里点名，比猜稳。
MARKER = {
    "emotion": mark_for_emotion,
    "anim": mark_for_anim,
}


def process_table(block: list[str], who: str | None, mode: str, arg: str | None) -> list[str]:
    """给一张表的表头补列、给数据行补标记。block 是连续的行（含表头与分隔行）。"""
    out: list[str] = []
    done_header = False
    for line in block:
        if not line.strip().startswith("|"):
            out.append(line)
            continue
        cells = _cells(line)
        if _is_sep(cells):
            if done_header:
                out.append(_rebuild([*cells, "---"]))
            else:
                out.append(line)
            continue
        if not done_header:
            cells = [*cells, "**" + HEADER + "**"]
            out.append(_rebuild(cells))
            done_header = True
            continue
        name = _name_cell(cells)
        if mode == "explicit":
            if who is None:
                raise SystemExit("这张表没登记按谁认人：" + name)
            mark = MARKER[who](name)
        elif mode == "table_e":
            key = cells[0].strip()
            if key not in TABLE_E:
                raise SystemExit("表 E 出现了没登记的编号：" + key)
            mark = TABLE_E[key]
        elif mode == "pending":
            mark = MARK_TODO
        elif mode == "inherit":
            mark = MARK_KEEP
        else:
            raise SystemExit("未知的标注方式：" + mode)
        out.append(_rebuild([*cells, mark]))
    return out


def build() -> str:
    src = V1.read_text(encoding="utf-8")
    lines = src.splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    bounds = [*heads, len(lines)]
    sections: list[tuple[str, list[str]]] = []
    for a, b in itertools.pairwise(bounds):
        sections.append((lines[a], lines[a:b]))
    if not sections or sections[0][0].startswith("## "):  # noqa: SIM108
        # 第 0 段（## 之前）单独留着
        pre = lines[: bounds[0]]
    else:
        pre = []

    plans = {title: (who, mode, arg) for title, who, mode, arg in TABLE_PLANS}
    out: list[str] = []
    for i, ln in enumerate(pre):
        if i == 0:
            out.append(ln.replace("Sammy 表情总表 v1", "Sammy 表情总表 v1.1", 1))
        else:
            out.append(ln)

    for _idx, (title, body) in enumerate(sections):
        plan = None
        for key, (who, mode, arg) in plans.items():
            if title.startswith(key):
                plan = (who, mode, arg)
                break
        if plan is None:
            out.extend(body)
            continue
        # 把该节里的表格块整体处理；其余行原样
        j = 0
        while j < len(body):
            if body[j].strip().startswith("|"):
                k = j
                while k < len(body) and body[k].strip().startswith("|"):
                    k += 1
                out.extend(process_table(body[j:k], plan[0], plan[1], plan[2]))
                j = k
            else:
                out.append(body[j])
                j += 1

    text = "\n".join(out) + "\n"
    text = text.replace(
        "- 版本：v1.0 · 2026-10-13 · 整理：Max（本机 Hermes）· 交办：Nex（转 Rowan 拍板）",
        "- 版本：**v1.1** · 2026-10-14 19:05 · 整理：Max（本机 Hermes）· 依据：`docs/DECISIONS.md`（Rowan 2026-10-14 授权 Max 自行取决）\n"
        "- v1.0 存档：`docs/表情总表_v1.md`（**只读**：v1.1 由 `scripts/faces_spec_v11.py` 从它逐字节生成，改 v1 的表格跑一下生成器即可，别手改 v1.1）",
        1,
    )
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只对账不写盘")
    args = ap.parse_args(argv)
    text = build()
    if args.check:
        cur = V11.read_text(encoding="utf-8") if V11.exists() else ""
        if cur != text:
            print("v1.1 与生成器产出不一致 —— 跑一次生成器", file=sys.stderr)
            return 1
        print("v1.1 与生成器产出一致")
        return 0
    V11.write_text(text, encoding="utf-8")
    print(f"写出 {V11}：{len(text)} 字符 / {text.count(chr(10)) + 1} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
