"""休息提醒的测试。

这块最容易出的不是"不提醒"，而是**提醒得没道理**：
你刚坐下就催你起来、你人都不在还提醒、或者像健康助手一样说教。
所以测试的重点是"不该提醒的时候不提醒"。
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy.care import (
    ACTIVE_WINDOW_MINUTES,
    REMIND_AFTER_MINUTES,
    SNOOZE_MINUTES,
    Care,
    care_prompt,
)


def at(hour: int, minute: int = 0) -> float:
    """构造本地时间戳（构造和读取都用本地时间，避免时区坑）。"""
    return time.mktime((2026, 10, 1, hour, minute, 0, 0, 0, -1))


def tick_work(c: Care, start: float, minutes: int, step: int = 5) -> float:
    """模拟"连续用了 minutes 分钟"：每 step 分钟动一下。

    为什么必须喂**一串**活动事件，而不是"起点 + 终点"两个点：
    "离开超过 10 分钟就重新计时"是这块的核心规则 ——
    只给起点和终点，中间 40 分钟看起来就像你走了，会话会被正确地重置，
    于是测试测的是一个**不存在的情形**。
    （第一版就是这么写的，三条测试挂在那儿，全怪夹具，不怪功能。）
    """
    c.note_activity(now=start)
    t = start
    for m in range(step, minutes + 1, step):
        t = start + m * 60
        c.note_activity(now=t)
    return t


def working(minutes: int, start_hour: int = 10) -> Care:
    """一个"已经连续用了 N 分钟"的状态。"""
    c = Care()
    tick_work(c, at(start_hour), minutes)
    return c


# ── 该提醒 ────────────────────────────────────────


def test_reminds_after_a_long_session():
    c = working(REMIND_AFTER_MINUTES + 1)
    gate = c.due(now=c.last_activity)
    assert gate.ok, f"坐了 40 分钟还不提醒：{gate.reason}"
    assert "该起来动动" in gate.reason


def test_does_not_nag_a_fresh_session():
    """刚坐下就催 —— 这是最招人烦的一种。"""
    c = working(5)
    gate = c.due(now=c.last_activity)
    assert not gate.ok
    assert "才坐了" in gate.reason


def test_snooze_works_and_expires():
    c = working(REMIND_AFTER_MINUTES + 1)
    now = c.last_activity
    c.snooze(now=now)
    gate = c.due(now=now)
    assert not gate.ok, "推后之后不该立刻又提醒"
    assert "推后" in gate.reason

    later = tick_work(c, now, SNOOZE_MINUTES + 1)  # 你继续用了 31 分钟
    assert c.due(now=later).ok, "推后到期了就该提醒，不能一推就永远不提醒"


def test_quiet_hours_are_respected():
    """半夜三点提醒你起来动一动，那是最该被关掉的提醒。"""
    c = Care()
    tick_work(c, at(2, 0), REMIND_AFTER_MINUTES + 1)
    now = at(3, 0)
    c.last_activity = now  # 让它觉得"你还在"
    gate = c.due(now=now)
    assert not gate.ok
    assert "免打扰" in gate.reason


# ── 不该提醒 ──────────────────────────────────────


def test_no_reminder_when_you_are_away():
    """你人都不在，提醒什么？那不是「坐太久」，那是「没坐着」。"""
    c = working(REMIND_AFTER_MINUTES + 1)
    gone = c.last_activity + (ACTIVE_WINDOW_MINUTES + 1) * 60
    gate = c.due(now=gone)
    assert not gate.ok
    assert "不在" in gate.reason


def test_coming_back_restarts_the_clock():
    """断断续续用了一整天不算「连续坐了 40 分钟」—— 否则提醒站不住脚。"""
    c = Care()
    tick_work(c, at(10, 0), 30)  # 用了 30 分钟
    c.note_activity(now=at(11, 30))  # 离开 1 小时后回来
    assert c.session_minutes(now=at(11, 30)) < 1, "离开过就该重新计时"
    assert not c.due(now=at(11, 30)).ok


def test_session_minutes_is_zero_when_away():
    c = working(50)
    gone = c.last_activity + (ACTIVE_WINDOW_MINUTES + 2) * 60
    assert c.session_minutes(now=gone) == 0.0


def test_reminding_resets_the_clock():
    """提醒过一次就重新计时，不然它每分钟都会提醒你一次。"""
    c = working(REMIND_AFTER_MINUTES + 5)
    now = c.last_activity
    assert c.due(now=now).ok
    c.note_reminded(now=now)
    assert not c.due(now=now).ok, "刚提醒完又提醒"

    # 又连续坐了 40 分钟 —— 同样要给一串活动
    later = tick_work(c, now, REMIND_AFTER_MINUTES + 1)
    assert c.due(now=later).ok, "又坐了 40 分钟该再提醒一次"


def test_snooze_is_cleared_after_a_real_reminder():
    c = working(REMIND_AFTER_MINUTES + 1)
    now = c.last_activity
    c.snooze(now=now)
    c.note_reminded(now=now)
    assert c.snooze_until is None, "推后状态该跟着这次提醒一起结束"


# ── 持久化 ────────────────────────────────────────


def test_restarting_does_not_let_you_dodge_the_reminder(tmp_path):
    """重启不该让你躲过一次提醒 —— 否则「关掉再打开」就是万能免打扰。"""
    p = tmp_path / "care.json"
    c = working(REMIND_AFTER_MINUTES + 1)
    c.save(p)
    again = Care.load(p)
    assert again.session_start == c.session_start
    assert again.due(now=c.last_activity).ok


def test_corrupt_state_file_does_not_crash(tmp_path):
    p = tmp_path / "care.json"
    p.write_text("{ 坏 json", encoding="utf-8")
    assert Care.load(p) is not None


def test_state_file_lives_on_the_internal_disk():
    from sammy import care

    assert "Application Support/Sammy" in str(care.STATE_FILE)
    assert not str(care.STATE_FILE).startswith("/Volumes")


def test_quiet_hours_definition_is_shared_not_duplicated():
    """免打扰的定义只有一处 —— 两边各写一遍，早晚会不一致，而且没人会发现。"""
    from sammy import attention, care

    assert care.in_quiet_hours is attention.in_quiet_hours


# ── 怎么说 ────────────────────────────────────────


def test_prompt_forbids_health_lecturing():
    """说教腔的提醒一律不要 —— 提示词里直接禁掉。"""
    prompt = care_prompt(45)
    assert "45" in prompt
    assert "说教" in prompt  # 出现在禁止项里
    assert "25 字" in prompt


def test_prompt_says_it_is_proactive():
    """必须明确告诉模型「这是你主动开口」，否则它可能反问用户「你怎么了」。"""
    assert "主动" in care_prompt(45)
