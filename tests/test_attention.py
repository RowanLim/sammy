"""主动心跳的测试。

这块的测试比功能代码更重要：**主动开口是唯一一种"做错了会让人卸载"的行为。**
所以每条闸门都要单独验，而且必须有一条验"它**能**开口" ——
一个永远不触发的规则引擎，和没有这个功能是一样的，但更难被发现。
"""

from __future__ import annotations

import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import attention
from sammy.attention import Attention, Gate, open_prompt


def at(hour: int, minute: int = 0, day: int = 1) -> float:
    """构造一个"当地时间"时间戳。用本地时间构造、本地时间读，避免时区坑。"""
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


def ready(**kw) -> Attention:
    """一个"其它条件都满足"的起始状态，方便单点测试某一条闸门。

    last_spoke 留 None（从没开口过）—— 别随手塞一个时间进去：
    第一版我塞了一个 9 点，结果测"8 点能不能开口"时那个时间点在**未来**，
    测试就挂在一个和它要验的东西毫无关系的地方。
    """
    a = Attention(last_spoke=None, spoken_today=0, day="2026-10-01")
    a.day = time.strftime("%Y-%m-%d", time.localtime(kw.get("now", at(14, 0))))
    return a


def test_a_future_last_spoke_does_not_lock_it_forever():
    """时钟倒退/跨时区会让 last_spoke 落在未来 —— 必须能自愈，不能永久锁死。

    （这是测跨午夜免打扰时撞出来的：一个未来时间点会算出负数，
    然后用"还剩 -75 分钟"这种理由把功能关掉。）
    """
    a = ready(now=at(14, 0))
    a.last_spoke = at(20, 0)  # 未来
    gate = a.decide(want_to_talk=0.99, silent_minutes=9999, now=at(14, 0))
    assert gate.ok, f"坏数据不该锁死功能：{gate.reason}"


# ── 每条闸门 ──────────────────────────────────────


def test_it_can_actually_speak_up():
    """最重要的一条：**规则引擎必须有可能触发**。

    一条永远返回 False 的规则也能让所有"不该说话"的测试通过 ——
    那种测试全是绿的，而功能等于没有。所以先证明它会开口。
    """
    a = ready(now=at(14, 0))
    gate = a.decide(want_to_talk=0.9, silent_minutes=120, now=at(14, 0))
    assert gate.ok, f"什么都满足却不开口：{gate.reason}"
    assert not gate.reason.startswith("免打扰")


def test_quiet_hours_at_night():
    a = ready(now=at(23, 30))
    gate = a.decide(want_to_talk=0.99, silent_minutes=600, now=at(23, 30))
    assert not gate.ok
    assert "免打扰" in gate.reason


def test_quiet_hours_wrap_past_midnight():
    """23:00–08:00 要跨午夜：凌晨 3 点当然也是免打扰。"""
    for hour in (23, 0, 3, 7):
        a = ready(now=at(hour, 30))
        gate = a.decide(want_to_talk=0.99, silent_minutes=600, now=at(hour, 30))
        assert not gate.ok, f"{hour} 点不该开口"
    for hour in (8, 12, 20):
        a = ready(now=at(hour, 30))
        gate = a.decide(want_to_talk=0.99, silent_minutes=600, now=at(hour, 30))
        assert gate.ok, f"{hour} 点应该可以开口，却被拦：{gate.reason}"


def test_does_not_interrupt_soon_after_a_chat():
    """刚聊过就别再凑上来 —— 这是最容易惹人烦的一条。"""
    a = ready(now=at(14, 0))
    gate = a.decide(want_to_talk=0.99, silent_minutes=10, now=at(14, 0))
    assert not gate.ok
    assert "刚聊过" in gate.reason


def test_grace_period_right_after_startup():
    a = ready(now=at(14, 0))
    gate = a.decide(want_to_talk=0.99, silent_minutes=600, now=at(14, 0), started_at=at(14, 0))
    assert not gate.ok
    assert "刚启动" in gate.reason


def test_does_not_speak_twice_in_a_row():
    """它自己刚开口过，不能马上又来一句。

    这是写界面接线时才发现的设计漏洞：MIN_GAP 原来只算「用户多久没理我」，
    **没算「我多久前刚开口」** —— 于是用户一句话没说，它能在几分钟里连说三句，
    正好撞上"会被卸载"的那条线。
    """
    a = ready(now=at(14, 0))
    a.note_spoke(now=at(14, 0))
    gate = a.decide(want_to_talk=0.99, silent_minutes=9999, now=at(14, 10))
    assert not gate.ok, "自己刚说完就又说一句，这是骚扰"
    assert "刚开口" in gate.reason

    # 等够了就来
    gate2 = a.decide(want_to_talk=0.99, silent_minutes=9999, now=at(15, 0))
    assert gate2.ok, f"过了间隔该能开口：{gate2.reason}"


def test_daily_cap():
    a = ready(now=at(14, 0))
    for _ in range(attention.MAX_PER_DAY):
        a.note_spoke(now=at(14, 0))
    gate = a.decide(want_to_talk=0.99, silent_minutes=600, now=at(16, 0))
    assert not gate.ok
    assert "今天" in gate.reason


def test_does_not_speak_when_it_does_not_feel_like_it():
    """驱力说"不想说"，就不许说 —— 这是"它有自己状态"的体现。"""
    a = ready(now=at(14, 0))
    gate = a.decide(want_to_talk=0.1, silent_minutes=600, now=at(14, 0))
    assert not gate.ok
    assert "不想说" in gate.reason


def test_hard_gates_win_over_soft_urge():
    """免打扰优先级最高：哪怕它特别想说话、也安静了很久，深夜照样不许。"""
    a = ready(now=at(2, 0))
    gate = a.decide(want_to_talk=1.0, silent_minutes=9999, now=at(2, 0))
    assert not gate.ok


# ── 记账与跨天 ────────────────────────────────────


def test_only_really_speaking_costs_quota():
    """判断通过、但生成失败，不该消耗今天的机会。"""
    a = ready(now=at(14, 0))
    a.decide(want_to_talk=0.9, silent_minutes=600, now=at(14, 0))
    assert a.spoken_today == 0
    a.note_spoke(now=at(14, 0))
    assert a.spoken_today == 1


def test_quota_resets_next_day():
    a = ready(now=at(14, 0))
    for _ in range(attention.MAX_PER_DAY):
        a.note_spoke(now=at(14, 0))
    gate = a.decide(want_to_talk=0.99, silent_minutes=600, now=at(14, 0, day=2))
    assert gate.ok, "跨天了配额该重置"


def test_restarting_does_not_reset_the_quota(tmp_path):
    """**关掉再打开就能重置的限制，不叫限制。**"""
    p = tmp_path / "attention.json"
    a = Attention.load(p)
    a.note_spoke(now=at(14, 0))
    a.note_spoke(now=at(14, 0))
    a.save(p)

    again = Attention.load(p)
    assert again.spoken_today == 2, "重启后忘了今天说过几次，配额就形同虚设"
    assert again.last_spoke is not None, "重启后忘了刚聊过，会立刻又来烦人"


def test_corrupt_state_file_does_not_crash(tmp_path):
    p = tmp_path / "attention.json"
    p.write_text("{ 坏掉的 json", encoding="utf-8")
    assert Attention.load(p) is not None


def test_state_file_lives_inside_the_project():
    """状态在项目文件夹里（Rowan 的隔离要求）—— 完整检查见 test_isolation.py。"""
    from sammy.paths import project_root

    assert str(attention.STATE_FILE).startswith(str(project_root()))


# ── 说什么 ────────────────────────────────────────


@pytest.mark.parametrize(
    "closeness,boredom,expect_word",
    [
        (0.1, 0.1, "想念"),  # 疏远了 -> 想你
        (0.8, 0.9, "俏皮"),  # 很熟又无聊 -> 找聊
        (0.8, 0.1, "关心"),  # 正常 -> 关心一句
    ],
)
def test_open_prompt_picks_a_topic_by_state(closeness, boredom, expect_word):
    prompt = open_prompt(want_to_talk=0.8, closeness=closeness, boredom=boredom)
    assert expect_word in prompt


def test_open_prompt_forbids_customer_service_voice():
    """主动消息最容易退化成"需要我帮你做点什么吗" —— 在提示词里直接禁掉。"""
    prompt = open_prompt(want_to_talk=0.8, closeness=0.8, boredom=0.8)
    assert "需要帮忙吗" in prompt  # 出现在禁止项里
    assert "20 字" in prompt  # 有长度约束


def test_gate_is_truthy_when_ok():
    assert Gate(True, "ok")
    assert not Gate(False, "nope")
