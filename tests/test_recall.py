"""回忆主动性 —— 「主动开口」有时要带上它想起的旧事。

为什么单开一个模块、为什么每条闸门都要单独测：
- 一个把"我全记得"挂嘴边的 Sammy 和念档案没区别。「刚说过的不提 /
  一天提不过两三次 / 不该提的别乱提」三条各挡一类翻车，必须能单独钉住；
- 和 attention 那边同一条铁律：**规则引擎必须真的能触发** ——
  一条永远返回 False 的规则也能把所有"不该提"的测试变绿，但功能等于没有。

全部离线：记忆用真 Memory（临时库），挑选随机用固定种子（random.Random）。
"""

from __future__ import annotations

import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import recall as R
from sammy.memory import Memory


def mk_mem(tmp_path) -> Memory:
    return Memory(tmp_path / "t.db")


def put(mem: Memory, text: str, *, kind: str = "event", ts: float | None = None) -> int:
    """往日记里塞一条**指定时间**的记录 —— ts 用来测"资格窗口"。"""
    ts = time.time() if ts is None else ts
    cur = mem.conn.execute(
        "INSERT INTO journal(ts, day, kind, text, tags) VALUES(?,?,?,?,?)",
        (ts, time.strftime("%Y-%m-%d", time.localtime(ts)), kind, text, "test"),
    )
    mem.conn.commit()
    return int(cur.lastrowid or -1)


def days_ago(n: float) -> float:
    return time.time() - n * 86400


def rng(seed: int) -> random.Random:
    return random.Random(seed)


# ── 能不能提（最重要的一条） ───────────────────────


def test_it_can_actually_recall(tmp_path):
    mem = mk_mem(tmp_path)
    put(mem, "约好周六一起看火箭发射", ts=days_ago(3))
    gate = R.Recaller().decide(mem, rng=rng(1))
    assert gate.ok, f"有像样的旧事却不提：{gate.reason}"
    assert gate.item is not None
    assert "火箭" in gate.item.text


def test_empty_memory_is_honest(tmp_path):
    gate = R.Recaller().decide(mk_mem(tmp_path))
    assert not gate.ok
    assert "没有" in gate.reason
    assert not gate  # Gate 的布尔值就是"能不能提"


def test_none_memory_does_not_crash():
    gate = R.Recaller().decide(None)
    assert not gate.ok


# ── 一天最多提几次 ─────────────────────────────────


def test_daily_cap(tmp_path):
    mem = mk_mem(tmp_path)
    for i in range(R.MAX_RECALLS_PER_DAY + 2):
        put(mem, f"第 {i} 件值得想起的小事", ts=days_ago(3 + i))
    r = R.Recaller()
    for seed in range(R.MAX_RECALLS_PER_DAY):
        g = r.decide(mem, rng=rng(seed))
        assert g.ok, g.reason
        r.note_recalled(g.item.id)
    g = r.decide(mem, rng=rng(99))
    assert not g.ok, "额度用完了还能提，就不叫上限"
    assert "提过" in g.reason


def test_daily_cap_rolls_over_at_midnight(tmp_path):
    mem = mk_mem(tmp_path)
    t0 = time.mktime((2026, 10, 10, 14, 0, 0, 0, 0, -1))
    put(mem, "很久以前的一件小事", ts=t0 - 10 * 86400)
    r = R.Recaller(day="2026-10-10", recalled_today=R.MAX_RECALLS_PER_DAY)
    g = r.decide(mem, now=t0 + 86400, rng=rng(1))
    assert g.ok, f"跨天该重新有额度：{g.reason}"


# ── 刚提过的/刚说过的，不提 ────────────────────────


def test_same_item_waits_out_its_cooldown(tmp_path):
    mem = mk_mem(tmp_path)
    put(mem, "第一件事", ts=days_ago(5))
    put(mem, "第二件事", ts=days_ago(6))
    r = R.Recaller()
    first = r.decide(mem, rng=rng(0))
    assert first.ok
    r.note_recalled(first.item.id)
    for seed in range(40):
        g = r.decide(mem, rng=rng(seed))
        assert g.ok, g.reason
        assert g.item.id != first.item.id, "刚提过的又提，就是在念档案"


def test_when_the_only_item_is_on_cooldown_nothing_is_recalled(tmp_path):
    mem = mk_mem(tmp_path)
    i = put(mem, "唯一的一件事", ts=days_ago(5))
    r = R.Recaller()
    r.recent_items[f"journal:{i}"] = time.time()
    g = r.decide(mem)
    assert not g.ok
    assert "刚提过" in g.reason


def test_cooldown_expires_after_a_week(tmp_path):
    mem = mk_mem(tmp_path)
    i = put(mem, "上上上周的老事", ts=days_ago(40))
    r = R.Recaller()
    r.recent_items[f"journal:{i}"] = days_ago(R.ITEM_COOLDOWN_DAYS + 1)
    g = r.decide(mem, rng=rng(3))
    assert g.ok and g.item.id == f"journal:{i}", "冷却过了就该能再提"


def test_future_cooldown_record_self_heals(tmp_path):
    """时钟倒退 / 跨时区会留下"未来"的冷却记录 —— 不许把功能永久锁死。"""
    mem = mk_mem(tmp_path)
    i = put(mem, "一条普通旧事", ts=days_ago(3))
    r = R.Recaller()
    r.recent_items[f"journal:{i}"] = time.time() + 86400
    g = r.decide(mem, rng=rng(1))
    assert g.ok, f"坏数据不该把功能锁死：{g.reason}"
    assert f"journal:{i}" not in r.recent_items, "未来记录应该被清掉（自愈）"


def test_what_you_just_talked_about_is_skipped(tmp_path):
    mem = mk_mem(tmp_path)
    put(mem, "你最近在折腾树莓派小车", ts=days_ago(4))
    g = R.Recaller().decide(mem, recent_text="我们刚聊过你在折腾树莓派小车这事", rng=rng(1))
    assert not g.ok, "刚聊过的事不该又'想起来'"


def test_chat_text_since_windows_by_time():
    now = time.time()
    msgs = [
        {"t": now - 72 * 3600, "text": "三天前说的话"},
        {"t": now - 2 * 3600, "text": "刚才说的话"},
    ]
    s = R.chat_text_since(msgs, now=now)
    assert "刚才说的话" in s
    assert "三天前说的话" not in s, "太老的聊天不算'刚说过'"


# ── 不该提的别乱提 ─────────────────────────────────


def test_private_and_technical_slots_are_never_topics(tmp_path):
    mem = mk_mem(tmp_path)
    mem.set_slot("residence", "XX 路 1 号")
    mem.set_slot("health", "腰不太好")
    mem.set_slot("machine", "Mac mini")
    mem.set_slot("sammy_code_location", "外置盘")
    mem.set_slot("api_key_note", "别问，存好了")
    assert R.candidates(mem) == []


def test_ordinary_slots_are_fine_topics(tmp_path):
    mem = mk_mem(tmp_path)
    mem.set_slot("current_project", "桌面机器人 Sammy")
    texts = [c.text for c in R.candidates(mem)]
    assert any("桌面机器人" in t for t in texts)


def test_credential_like_content_is_never_a_topic(tmp_path):
    mem = mk_mem(tmp_path)
    put(mem, "他把家里的 WiFi 密码记在抽屉里", ts=days_ago(3))
    mem.set_slot("note", "银行卡放在书房")
    assert R.candidates(mem) == []
    put(mem, "周末去河边钓了鱼", ts=days_ago(3))
    texts = [c.text for c in R.candidates(mem)]
    assert texts == ["周末去河边钓了鱼"]


# ── 资格窗口 ───────────────────────────────────────


def test_too_fresh_and_too_old_entries_are_not_recallable(tmp_path):
    mem = mk_mem(tmp_path)
    put(mem, "一小时前才发生的事", ts=time.time() - 3600)
    put(mem, "大半年前的老黄历", ts=days_ago(R.ELIGIBLE_BEFORE_DAYS + 20))
    assert R.candidates(mem) == []


def test_recent_event_in_window_is_recallable(tmp_path):
    mem = mk_mem(tmp_path)
    put(mem, "前两天说好的一个约定", ts=days_ago(2))
    assert len(R.candidates(mem)) == 1


def test_overlong_texts_are_not_topics(tmp_path):
    mem = mk_mem(tmp_path)
    put(mem, "很" * (R.MAX_TEXT_LEN + 10), ts=days_ago(3))
    assert R.candidates(mem) == []


# ── 挑选 ───────────────────────────────────────────


def test_identical_text_is_not_listed_twice(tmp_path):
    mem = mk_mem(tmp_path)
    put(mem, "同一件事被抽了两次", ts=days_ago(3))
    put(mem, "同一件事被抽了两次", ts=days_ago(3) + 60)
    assert len(R.candidates(mem)) == 1


def test_same_seed_same_choice(tmp_path):
    mem = mk_mem(tmp_path)
    for i in range(5):
        put(mem, f"候选第 {i} 条", ts=days_ago(3 + i))
    r = R.Recaller()
    a = r.decide(mem, rng=rng(7))
    b = r.decide(mem, rng=rng(7))
    assert a.item.id == b.item.id, "同一种子必须可复现，否则测试没法钉"


def test_pick_favors_heavier_kinds(tmp_path):
    mem = mk_mem(tmp_path)
    put(mem, "他明确让我记住的偏好", kind="explicit", ts=days_ago(3))
    put(mem, "某天的一段普通总结", kind="digest", ts=days_ago(4))
    r = R.Recaller()
    hits = {"explicit": 0, "digest": 0}
    for seed in range(200):
        g = r.decide(mem, rng=rng(seed))
        assert g.ok
        hits[g.item.kind] += 1
    assert hits["explicit"] > hits["digest"], f"明确让记的事该更常被想起：{hits}"


def test_item_ids_are_stable_across_calls(tmp_path):
    mem = mk_mem(tmp_path)
    mem.set_slot("name", "Rowan")
    a = [c.id for c in R.candidates(mem)]
    b = [c.id for c in R.candidates(mem)]
    assert a == b == ["slot:name"]


# ── 状态与落盘 ─────────────────────────────────────


def test_state_roundtrip(tmp_path):
    p = tmp_path / "recall.json"
    r = R.Recaller()
    r.note_recalled("journal:1")
    r.note_recalled("slot:name")
    r.save(p)
    r2 = R.Recaller.load(p)
    assert r2.recalled_today == 2
    assert set(r2.recent_items) == {"journal:1", "slot:name"}


def test_corrupt_state_reads_as_fresh(tmp_path):
    p = tmp_path / "recall.json"
    p.write_text("不是 JSON {{{", encoding="utf-8")
    r = R.Recaller.load(p)
    assert r.recalled_today == 0
    assert r.recent_items == {}


def test_missing_state_file_is_fresh(tmp_path):
    r = R.Recaller.load(tmp_path / "nope.json")
    assert r.recalled_today == 0


def test_ancient_cooldown_records_are_pruned(tmp_path):
    now = time.time()
    r = R.Recaller()
    r.recent_items = {"old": now - 30 * 86400, "fresh": now - 86400}
    r.note_recalled("new", now=now)
    assert "old" not in r.recent_items, "超过两倍冷却期的记录没用了，该清掉"
    assert "fresh" in r.recent_items


# ── 提示词 ─────────────────────────────────────────


def test_prompt_carries_the_item_and_the_discipline():
    p = R.recall_prompt("coffee_preference：喜欢喝美式")
    assert "喜欢喝美式" in p, "想起的事必须进指令，否则模型无从提起"
    assert "不是用户在跟你说话" in p
    assert "25 字" in p, "一句话的纪律要写死"
