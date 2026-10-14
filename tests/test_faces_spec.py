"""表情总表 v1.1 的判据 —— 表里标的东西 = docs/DECISIONS.md 里定的东西。

为什么要有这份判据，而不是「生成器能跑就行」：
    生成器是**机器写文档**。机器写错时不会有人发现 —— 表格不会报错，
    多一行少一行、标错一格，看的人都当它是表里本来就那么写的。
    所以这里把三件事钉死：

    1. v1 一行不丢：v1.1 的每一行正文都能在 v1 里找到，行数一致；
    2. 标记对得上 DECISIONS：首发 12 情绪、第二批 6 情绪、首发 8 动画，
       三条集合都从 DECISIONS.md 里**读出来**对账，不是把名字抄在测试里；
    3. 生成是确定的：同样的 v1 跑两遍逐字节一致，且 --check 认得自己。

最后一条最重要：第一行数据被当成分隔行吞掉、整表错位一行那个坑，
表现是「跑得通、但全错位」—— 靠眼睛看不出来，只有逐行对账能抓住。
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
V1 = DOCS / "表情总表_v1.md"
V11 = DOCS / "表情总表_v1.1.md"
DECISIONS = DOCS / "DECISIONS.md"
GEN = ROOT / "scripts" / "faces_spec_v11.py"


def _load():
    spec = importlib.util.spec_from_file_location("faces_spec_v11", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN_MOD = _load()
MARK_FIRST = GEN_MOD.MARK_FIRST
MARK_SECOND = GEN_MOD.MARK_SECOND


def _live_text() -> str:
    return GEN_MOD.build()


def _cells(line: str) -> list[str]:
    return line.strip().strip("|").split("|")


def _is_sep_cells(cells: list[str]) -> bool:
    body = "".join(cells).strip()
    return "-" in body and set(body) <= set("-: ")


def _table_rows(section_prefix: str) -> list[list[str]]:
    """取某一节里那张表的数据行，跳过表头与分隔行。"""
    lines = _live_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(section_prefix))
    end = next(
        (i for i, ln in enumerate(lines) if i > start and ln.startswith("## ")),
        len(lines),
    )
    out: list[list[str]] = []
    seen_header = False
    for ln in lines[start:end]:
        if not ln.startswith("|"):
            continue
        cells = _cells(ln)
        if _is_sep_cells(cells):
            continue
        if not seen_header:
            seen_header = True
            continue
        out.append(cells)
    return out


def _decisions_line(pattern: str) -> set[str]:
    """从 DECISIONS.md 的表格行里读出一串斜杠分隔的名字。

    读不到就报错 —— 不许静默退回空集合，那样判据会「通过」得毫无意义。
    DECISIONS 是 markdown 表格，名字段后面还跟着理由列，所以每条都自带
    自己的右边界（换行、<br>、或表格竖线）。
    """
    text = DECISIONS.read_text(encoding="utf-8")
    m = re.search(pattern, text)
    assert m, "DECISIONS.md 里找不到这一行：" + pattern
    return {x.strip() for x in m.group(1).split("/") if x.strip()}


def _decisions_first_batch_emotions() -> set[str]:
    return _decisions_line(r"情绪：([^\n<]+)")


def _decisions_second_batch_emotions() -> set[str]:
    return _decisions_line(r"第二批 6 个：([^\n|]+)")


def _decisions_first_batch_anims() -> set[str]:
    return _decisions_line(r"先上 8 个\**：([^\n|]+)")


# ---- 1. v1 一行不丢 ----


def test_v1_is_untouched():
    """v1 是只读底档：行数与首行都不许被生成器改过。"""
    lines = V1.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Sammy 表情总表 v1"
    assert len(lines) == 308


def _second_cells(lines: list[str]) -> list[str]:
    """每张表第二列（名字列）的字面量序列。"""
    out = []
    for ln in lines:
        if not ln.startswith("|"):
            continue
        cells = _cells(ln)
        if len(cells) >= 2:
            out.append(cells[1].strip())
    return out


def test_every_v1_row_survives_into_v11():
    """错位那个坑的杀手判据：v1 的每一行都要在 v1.1 里，且不多出无名行。

    第一行数据被当分隔行吞掉的毛病在这里必然现形 ——
    被吞的那行会跟 v1 对不上账。
    """
    v1_rows = _second_cells(V1.read_text(encoding="utf-8").splitlines())
    out_rows = _second_cells(_live_text().splitlines())
    assert len(v1_rows) == len(out_rows)
    missing = [x for x in v1_rows if x not in out_rows]
    assert missing == [], "v1.1 丢了这些行：" + repr(missing)
    extra = [x for x in out_rows if x not in v1_rows]
    assert extra == [], "v1.1 多出这些行：" + repr(extra)


def test_only_the_header_and_the_two_version_lines_change():
    """除标题行与两行版本说明外，非表格正文逐字节原样带过来。"""
    v1 = V1.read_text(encoding="utf-8").splitlines()[1:]
    v11 = _live_text().splitlines()[1:]
    # 版本行是被「替换」的：v1 那行 v1.0 换成了 v1.1 两行（多的那行是存档说明）。
    # 两边都排除掉版本行，才是「除表头与版本外原样带过来」的那个断言。
    v1 = [ln for ln in v1 if not ln.startswith("|") and not ln.startswith("- 版本：")]
    v11 = [
        ln
        for ln in v11
        if not ln.startswith("|")
        and not ln.startswith("- 版本：")
        and not ln.startswith("- v1.0 存档：")
    ]
    assert v1 == v11


# ---- 2. 每张表都补了一列，且列数一致 ----

PLANNED_SECTIONS = [
    "## 1. 表 A ★",
    "## 2. 表 A2",
    "## 6. 表 C",
    "## 7. 表 D",
    "## 9. 表 E",
]

UNPLANNED_SECTIONS = [
    "## 4. 表 B：",
    "## 5. 表 B2",
    "## 8. 手势触发表",
]


def _section_block(prefix: str) -> list[str]:
    lines = _live_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(prefix))
    end = next(
        (i for i, ln in enumerate(lines) if i > start and ln.startswith("## ")),
        len(lines),
    )
    return lines[start:end]


@pytest.mark.parametrize("prefix", PLANNED_SECTIONS)
def test_each_table_gets_a_v11_column(prefix):
    block = [ln for ln in _section_block(prefix) if ln.startswith("|")]
    assert block, prefix + " 里没有表"
    header = _cells(block[0])
    assert header[-1].strip() == "**v1.1**"
    widths = {len(_cells(ln)) for ln in block}
    assert widths == {len(header)}, prefix + " 列数不齐：" + repr(widths)


@pytest.mark.parametrize("prefix", UNPLANNED_SECTIONS)
def test_tables_without_plans_are_left_alone(prefix):
    """没登记计划的表一字不动 —— 不该被硬塞一列。"""
    for ln in _section_block(prefix):
        assert "**v1.1**" not in ln, prefix + " 不该被改"


def test_planned_sections_are_exactly_the_registered_ones():
    """登记的表 = 真被改的表，两边都不许多不许少。"""
    registered = [t for t, _w, _m, _a in GEN_MOD.TABLE_PLANS]
    prefixes = tuple(registered)
    text = _live_text()
    hit = [ln for ln in text.splitlines() if ln.startswith(prefixes)]
    for t in registered:
        assert any(ln.startswith(t) for ln in hit), t + " 在 v1 里找不到（改了标题？）"


# ---- 3. 标记与 DECISIONS 对账 ----


def _mark_set(section, mark):
    rows = _table_rows(section)
    return {r[1].strip().split(" ")[0] for r in rows if r[-1].strip() == mark}


def test_emotion_marks_match_decisions():
    rows = _table_rows("## 1. 表 A ★")
    assert len(rows) == 18
    first = _mark_set("## 1. 表 A ★", MARK_FIRST)
    second = _mark_set("## 1. 表 A ★", MARK_SECOND)
    assert first == _decisions_first_batch_emotions()
    assert second == _decisions_second_batch_emotions()
    assert not (first & second)
    assert first | second == {r[1].strip().split(" ")[0] for r in rows}


def test_anim_marks_match_decisions():
    rows = _table_rows("## 6. 表 C")
    assert len(rows) == 42
    first = _mark_set("## 6. 表 C", MARK_FIRST)
    assert first == _decisions_first_batch_anims()
    assert len(first) == 8


def test_table_e_marks_cover_the_five_system_states():
    rows = _table_rows("## 9. 表 E")
    assert len(rows) == 12
    marks = {r[0].strip(): r[-1].strip() for r in rows}
    assert set(marks) == {"E" + str(i) for i in range(1, 13)}
    for key in ("E3", "E4", "E5", "E6", "E9"):
        assert "首发" in marks[key], key + " 该进首发 -- " + marks[key]


def test_headmove_table_is_marked_pending_not_faked():
    rows = _table_rows("## 7. 表 D")
    assert len(rows) == 10
    for r in rows:
        assert r[-1].strip() == GEN_MOD.MARK_TODO


def test_a2_audit_table_inherits_instead_of_naming_batches():
    rows = _table_rows("## 2. 表 A2")
    assert len(rows) == 25
    for r in rows:
        assert r[-1].strip() == GEN_MOD.MARK_KEEP


# ---- 4. 生成是确定的，两个坑留了回归判据 ----


def test_generation_is_deterministic():
    assert _live_text() == _live_text()


def test_committed_file_matches_the_generator():
    assert V11.exists(), "v1.1 还没生成"
    assert V11.read_text(encoding="utf-8") == _live_text(), "跑一次生成器"


def test_check_mode_agrees():
    r = subprocess.run(
        [sys.executable, str(GEN), "--check"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stderr


def test_sep_guard_rejects_text_rows():
    """坑一：第一格是普通文字的行，绝不能被当成分隔行。"""
    assert not GEN_MOD._is_sep(_cells("| 0 | heart 爱心 / heart | 指令 heart |"))
    assert not GEN_MOD._is_sep(_cells("| 1 | Normal 平静（默认） | 无 |"))
    assert GEN_MOD._is_sep(_cells("|---|---|"))
    assert GEN_MOD._is_sep(_cells("| :--- | ---: |"))


def test_dispatch_does_not_guess_from_the_row():
    """坑二：认人方式来自表登记，不许靠行首是不是数字猜。"""
    src = inspect.getsource(GEN_MOD.process_table)
    assert "MARKER[who]" in src
    assert "name[0].isdigit()" not in src


def test_every_explicit_table_registers_who_it_asks():
    """explicit 的表必须登记按谁认人，否则跑到一半才炸。"""
    for title, who, mode, _arg in GEN_MOD.TABLE_PLANS:
        if mode == "explicit":
            assert who in GEN_MOD.MARKER, title + " 没登记认人方式"


def test_marker_can_name_every_row_of_its_table():
    """登记的认人方式必须覆盖那张表的每一行，且整张表真能标完。"""
    for title, who, mode, _arg in GEN_MOD.TABLE_PLANS:
        if mode != "explicit":
            continue
        fn = GEN_MOD.MARKER[who]
        for r in _table_rows(title):
            fn(r[1].strip())


def test_the_three_first_batch_sets_have_the_decided_sizes():
    """DECISIONS 的三个数：12 情绪 + 6 情绪 + 8 动画。"""
    assert len(_decisions_first_batch_emotions()) == 12
    assert len(_decisions_second_batch_emotions()) == 6
    assert len(_decisions_first_batch_anims()) == 8
