"""记忆 —— 槽位 / 日记 / 夜间整理。

这里最重要的一条不变式：**事实要被改写，事件只能追加。**
"""

from datetime import date, timedelta

import pytest

from sammy.memory import (
    Memory,
    looks_explicit,
    needs_nightly,
    parse_digest,
    parse_extraction,
)

# ── 解析（离线健壮性） ────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"slots":{"a":"b"},"journal":["c"]}', {"slots": {"a": "b"}, "journal": ["c"]}),
        # 模型爱包代码块
        ('```json\n{"slots":{"a":"b"},"journal":[]}\n```', {"slots": {"a": "b"}, "journal": []}),
        # 也爱说废话
        (
            '好的，结果：{"slots":{},"journal":["他在做 Sammy"]} 完毕',
            {"slots": {}, "journal": ["他在做 Sammy"]},
        ),
        ("完全不是 JSON", {"slots": {}, "journal": []}),
        ("", {"slots": {}, "journal": []}),
        ('{"slots":null,"journal":null}', {"slots": {}, "journal": []}),
        ('{"slots":{"k":""},"journal":["","  "]}', {"slots": {}, "journal": []}),  # 空值丢弃
    ],
)
def test_parse_extraction_is_tolerant(raw, expected):
    assert parse_extraction(raw) == expected


def test_parse_extraction_drops_non_list_journal():
    assert parse_extraction('{"slots":{},"journal":"一句话"}') == {"slots": {}, "journal": []}


def test_parse_digest():
    assert parse_digest('{"digest":"今天聊了项目","slots":{"项目":"Sammy"}}') == {
        "digest": "今天聊了项目",
        "slots": {"项目": "Sammy"},
    }
    assert parse_digest("胡说") == {"digest": "", "slots": {}}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("帮我记住：我只喝美式", True),
        ("记住我明天要开会", True),
        ("以后都叫我 Rowan", True),
        ("今天天气不错", False),
        ("", False),
    ],
)
def test_looks_explicit(text, expected):
    assert looks_explicit(text) is expected


# ── 槽位：事实要被改写 ────────────────────────────


def test_slot_upsert_overwrites(memory):
    memory.set_slot("preferred_coffee", "美式")
    memory.set_slot("preferred_coffee", "美式，不加糖")
    assert memory.slots() == {"preferred_coffee": "美式，不加糖"}
    n = memory.conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
    assert n == 1, "同一件事应该只有一行，不能被追加成两行"


def test_slot_ignores_blank(memory):
    memory.set_slot("", "值")
    memory.set_slot("键", "  ")
    assert memory.slots() == {}


def test_drop_slot(memory):
    memory.set_slot("a", "1")
    memory.drop_slot("a")
    assert memory.slots() == {}


# ── 日记：事件只能追加 ────────────────────────────


def test_journal_appends_only(memory):
    memory.add("早上做了 A")
    memory.add("下午做了 B")
    assert memory.stats()["journal"] == 2
    assert [r["text"] for r in memory.recent(days=1)] == ["早上做了 A", "下午做了 B"]


def test_journal_ignores_blank(memory):
    assert memory.add("") == -1
    assert memory.stats()["journal"] == 0


def test_journal_day_filter(memory):
    today = date.today().isoformat()
    old = (date.today() - timedelta(days=10)).isoformat()
    memory.add("今天的事", day=today)
    memory.add("十天前的事", day=old)
    assert [r["text"] for r in memory.day_entries(today)] == ["今天的事"]
    assert [r["text"] for r in memory.day_entries(old)] == ["十天前的事"]


def test_digest_not_counted_as_event(memory):
    today = date.today().isoformat()
    memory.add("一条事件", day=today)
    memory.add("一段摘要", kind="digest", day=today)
    assert len(memory.day_entries(today)) == 1, "摘要不该混进当天事件里"


# ── 持久化（PRD P0-5：重启后仍在） ─────────────────


def test_survives_reopen(tmp_path):
    path = tmp_path / "m.db"
    mem = Memory(path)
    mem.set_slot("preferred_name", "Rowan")
    mem.add("他开始做 Sammy 了")
    mem.close()

    again = Memory(path)
    assert again.slots() == {"preferred_name": "Rowan"}
    assert again.stats()["journal"] == 1
    again.close()


# ── 提示词上下文 ──────────────────────────────────


def test_context_block_is_empty_when_nothing_known(memory):
    assert memory.context_block() == ""


def test_context_block_contains_slots_and_events(memory):
    memory.set_slot("preferred_name", "Rowan")
    memory.add("他想把 Sammy 做出来")
    block = memory.context_block()
    assert "Rowan" in block
    assert "Sammy" in block
    assert "preferred_name" in block


def test_context_block_respects_budget(memory):
    for i in range(200):
        memory.add(f"很长的第 {i} 条记录" * 5)
    block = memory.context_block(max_chars=300)
    assert len(block) <= 320, "记忆块必须受字数限制，不然会挤爆提示词"


def test_context_block_marks_explicit(memory):
    memory.add("帮我记住：只喝美式", kind="explicit")
    assert "★" in memory.context_block()


# ── 夜间整理 ──────────────────────────────────────


def test_needs_nightly_nothing_to_do(memory):
    assert needs_nightly(memory) is None


def test_needs_nightly_picks_unconsolidated_past_day(memory):
    """好几天没开机也要能补课 —— 挑最老的那天先理。"""
    d1 = (date.today() - timedelta(days=3)).isoformat()
    d2 = (date.today() - timedelta(days=1)).isoformat()
    memory.add("三天前的事", day=d1)
    memory.add("昨天的事", day=d2)
    assert needs_nightly(memory) == d1

    memory.add("三天前的摘要", kind="digest", day=d1)
    assert needs_nightly(memory) == d2


def test_needs_nightly_skips_today(memory):
    """今天的记录在深夜之前不该被整理 ——
    否则当天刚整理完，之后新增的记录就永远轮不到（踩过的 bug）。"""
    memory.add("今天刚发生的事")
    assert needs_nightly(memory) is None


def test_stats(memory):
    memory.set_slot("a", "1")
    memory.add("事件")
    st = memory.stats()
    assert st["slots"] == 1
    assert st["journal"] == 1
    assert st["since"] == date.today().isoformat()
    assert st["db"].endswith(".db")
