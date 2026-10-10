"""记忆 —— 槽位 / 日记 / 夜间整理。

这里最重要的一条不变式：**事实要被改写，事件只能追加。**
"""

from datetime import date, datetime, timedelta

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
    # 注意键被归一化了（项目 → current_project）—— 这是**行为改好了**，
    # 老测试钉的是"不做归一化"的旧行为，所以要跟着改。
    assert parse_digest('{"digest":"今天聊了项目","slots":{"项目":"Sammy"}}') == {
        "digest": "今天聊了项目",
        "slots": {"current_project": "Sammy"},
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


def test_slot_keys_are_canonicalised():
    """key 必须归一化 —— 否则同一个事实会被当成「又多了一件事」重复记录。

    实测过：同一种事实，一次跑出来是 `name`、另一次是 `名字`。
    """
    from sammy.memory import canonical_key

    assert canonical_key("名字") == "name"
    assert canonical_key(" Name ") == "name"
    assert canonical_key("NAME") == "name"
    assert canonical_key("user_name") == "name"
    assert canonical_key("电脑型号") == "machine"
    assert canonical_key("正在开发的项目") == "current_project"


def test_unknown_keys_are_normalised_not_dropped():
    """未知 key 只做格式归一、不丢弃 —— 宁可多一条不常见的槽位，
    也不能把用户说过的事悄悄丢掉。"""
    from sammy.memory import canonical_key

    assert canonical_key("咖啡豆产地") == "咖啡豆产地"
    assert canonical_key("my  weird key") == "my_weird_key"
    assert canonical_key("  ") == ""


def test_synonyms_merge_on_write():
    """中文键和英文键指向同一件事时，应该合成一条，而不是两条。"""
    from sammy.memory import _clean_slots

    out = _clean_slots({"名字": "Rowan", "name": "Rowan", "昵称": "老罗"})
    assert out == {"name": "Rowan", "nickname": "老罗"}


def test_set_slot_is_the_single_place_that_canonicalises(tmp_path):
    """不管上层传什么写法，落库都该是规范名 —— 归一化只在一个地方做。"""
    mem = Memory(tmp_path / "m.db")
    mem.set_slot("名字", "Rowan")
    mem.set_slot("user_name", "Rowan")
    mem.set_slot("NAME", "Rowan")
    assert list(mem.slots().keys()) == ["name"]


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


def _clock_at(hour: int):
    """把 memory 模块里的「表」换成固定时刻。

    这条测试原来直接看真实时间：白天跑绿，**一过 23 点必挂**（第一次撞上是 23:51）。
    规则本身是故意的（深夜顺手把今天也整理掉），所以该修的是**测试**，不是产品 ——
    而"只在白天成立"的测试等于没测：它在最需要它守夜的那个时段是坏的。
    """

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 1, hour, 0, 0, tzinfo=tz)

    return _Clock


def test_needs_nightly_skips_today_before_23(memory, monkeypatch):
    """深夜之前，今天的记录不该被整理 ——
    否则当天刚整理完，之后新增的记录就永远轮不到（踩过的 bug）。"""
    from sammy import memory as mem_mod

    monkeypatch.setattr(mem_mod, "datetime", _clock_at(12))
    memory.add("今天刚发生的事")
    assert needs_nightly(memory) is None


def test_needs_nightly_takes_today_after_23(memory, monkeypatch):
    """23 点之后顺手把今天也整理掉 —— **这是故意的，别当 bug 修掉**。

    两条合起来才算把这条规则钉住：只验一边的话，
    把阈值删掉（永远整理今天）或改错（永远不整理今天）都能混过去。
    """
    from sammy import memory as mem_mod

    monkeypatch.setattr(mem_mod, "datetime", _clock_at(23))
    memory.add("今天刚发生的事")
    assert needs_nightly(memory) == date.today().isoformat()


def test_stats(memory):
    memory.set_slot("a", "1")
    memory.add("事件")
    st = memory.stats()
    assert st["slots"] == 1
    assert st["journal"] == 1
    assert st["since"] == date.today().isoformat()
    assert st["db"].endswith(".db")


def test_entries_between_takes_a_time_window(memory):
    """回忆主动性要的查询：按**绝对时间**取一段日记（新的在前）。"""
    import time as _t

    now = _t.time()
    memory.add("新的", kind="event")
    old_id = memory.add("旧的", kind="event")
    memory.conn.execute("UPDATE journal SET ts=? WHERE id=?", (now - 10 * 86400, old_id))
    memory.conn.commit()

    got = memory.entries_between(now - 5 * 86400, now + 1)
    assert [r["text"] for r in got] == ["新的"]

    memory.add("整理产物", kind="consolidate")
    got2 = memory.entries_between(now - 5 * 86400, now + 1, kinds=("consolidate",))
    assert [r["text"] for r in got2] == ["整理产物"]
