"""高峰/空闲时段判定 —— 这几条是**花钱的规矩**，错一分钟就是双倍价，所以钉死。

Rowan 2026-10-12：高峰 = 周一至周五（不含法定节假日）9-12、14-18；其余（含周末与
节假日全天）空闲。「以后在高峰时段以外 自主处理 Sammy 的事情」。

边界是重点：12:00 整、18:00 整、09:00 整、14:00 整 —— 含头不含尾，
错一个就多花一倍钱或者少干一段活。种子假期用 2026 年真实表（元旦 1/1-1/3）。
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import offpeak

# 2026 年的真实种子（holiday-cn 抓下来的那一份，挑几天代表性的）
CAL = {
    "off": {"2026-01-01", "2026-01-02", "2026-01-03"},  # 元旦（周四~周六）
    "year": 2026,
    "known": True,
    "source": "cache",
}


def at(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


# ── 工作日：高峰是 9-12 与 14-18，含头不含尾 ──────────────────


@pytest.mark.parametrize(
    "when,peak",
    [
        ("2026-10-12T08:59", False),  # 周一，上班前
        ("2026-10-12T09:00", True),  # 含头
        ("2026-10-12T11:59", True),
        ("2026-10-12T12:00", False),  # 不含尾 → 午休空闲
        ("2026-10-12T13:59", False),
        ("2026-10-12T14:00", True),  # 含头
        ("2026-10-12T17:59", True),
        ("2026-10-12T18:00", False),  # 不含尾 → 下班后空闲
        ("2026-10-12T23:59", False),
        ("2026-10-12T00:00", False),
    ],
)
def test_weekday_boundaries(when, peak):
    assert offpeak.is_peak(at(when), CAL)[0] is peak, when


def test_reason_is_human_readable():
    """理由要能直接贴给人看 —— 出问题时一眼知道为什么。"""
    assert "高峰" in offpeak.is_peak(at("2026-10-12T10:00"), CAL)[1]
    assert "周末" in offpeak.is_peak(at("2026-10-17T10:00"), CAL)[1]
    assert "节假日" in offpeak.is_peak(at("2026-01-01T10:00"), CAL)[1]


# ── 周末与节假日：全天空闲 ────────────────────────────────


@pytest.mark.parametrize("when", ["2026-10-17T10:00", "2026-10-18T15:00", "2026-10-17T09:00"])
def test_weekend_is_always_offpeak(when):
    """周末就算落在 9-12/14-18 也是空闲 —— 规矩明说「包括周末」。"""
    assert offpeak.is_peak(at(when), CAL)[0] is False


@pytest.mark.parametrize("when", ["2026-01-01T10:00", "2026-01-02T15:00"])
def test_holiday_is_always_offpeak(when):
    """元旦是周四/周五，落在高峰时段里也必须算空闲。"""
    assert offpeak.is_peak(at(when), CAL)[0] is False


def test_thursday_holiday_would_otherwise_be_peak():
    """反证：同一天的同一时刻，不放假就是高峰。确保上一条不是碰巧。"""
    assert offpeak.is_peak(at("2026-01-08T10:00"), CAL)[0] is True  # 下一个周四


# ── 下一个空闲窗口 ───────────────────────────────────────


def test_next_offpeak_from_mid_morning_is_lunch_break():
    got = offpeak.next_offpeak(at("2026-10-12T10:30"), CAL)
    assert got == at("2026-10-12T12:00"), "10:30 挨着的高峰，下一个空闲是 12:00"


def test_next_offpeak_from_afternoon_is_evening():
    got = offpeak.next_offpeak(at("2026-10-12T16:10"), CAL)
    assert got == at("2026-10-12T18:00")


def test_next_offpeak_when_already_offpeak_is_now():
    now = at("2026-10-12T12:30")
    assert offpeak.next_offpeak(now, CAL) == now


def test_next_offpeak_skips_to_monday_from_friday_night():
    """周五 17:30 之后……其实是当晚 18:00 就空闲了（别把简单事想复杂）。"""
    assert offpeak.next_offpeak(at("2026-10-16T17:30"), CAL) == at("2026-10-16T18:00")


# ── 表拿不到的时候：按周末判，并且**说明** ──────────────────


def test_unknown_calendar_falls_back_to_weekday_rule_and_says_so():
    unknown = {"off": set(), "year": 2027, "known": False, "source": ""}
    peak, _ = offpeak.is_peak(at("2027-03-10T10:00"), unknown)  # 周三
    assert peak is True  # 按工作日算高峰
    _, why2 = offpeak.is_peak(at("2027-03-13T10:00"), unknown)  # 周六
    assert "没拿到" in why2, "表不在的时候要说明，不能装知道"
    assert "周末" in why2


# ── 缓存与联网 ──────────────────────────────────────────


def test_load_calendar_reads_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(offpeak, "CACHE", tmp_path)
    (tmp_path / "holidays-2026.json").write_text(
        '{"year":2026,"off":["2026-01-01"]}', encoding="utf-8"
    )
    cal = offpeak.load_calendar(2026)
    assert cal["known"] is True and cal["source"] == "cache"
    assert "2026-01-01" in cal["off"]


def test_load_calendar_no_fetch_no_cache_is_honest(tmp_path, monkeypatch):
    """既没缓存又不许联网 → 必须老实说不知道（known=False），不能瞎判。"""
    monkeypatch.setattr(offpeak, "CACHE", tmp_path)
    cal = offpeak.load_calendar(2099, allow_fetch=False)
    assert cal["known"] is False and not cal["off"]


def test_real_2026_cache_is_in_place():
    """本机现成这一份要真的在（cron 靠它不联网也能判）。"""
    cal = offpeak.load_calendar(2026, allow_fetch=False)
    assert cal["known"] is True, "data/holidays-2026.json 不在 —— 跑一次 scripts/offpeak.py 生成"
    assert len(cal["off"]) >= 20, f"2026 年就 {len(cal['off'])} 天假？表不对"


# ── CLI ────────────────────────────────────────────────


def test_cli_exit_code_peak(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["offpeak.py", "--at", "2026-10-12T10:30", "--no-fetch"])
    rc = offpeak.main()
    out = capsys.readouterr().out
    assert rc == 1 and "PEAK" in out and "12:00" in out, "高峰要非零退出 + 指出下一个空闲窗口"


def test_cli_exit_code_offpeak(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["offpeak.py", "--at", "2026-10-12T20:00", "--no-fetch"])
    rc = offpeak.main()
    assert rc == 0 and "OFF-PEAK" in capsys.readouterr().out


def test_cli_quiet_stays_silent_when_offpeak(capsys, monkeypatch):
    """给定时任务用：空闲时一声不吭，别往消息流里灌东西。"""
    monkeypatch.setattr(
        sys, "argv", ["offpeak.py", "--at", "2026-10-12T20:00", "--no-fetch", "--quiet"]
    )
    rc = offpeak.main()
    assert rc == 0
    assert capsys.readouterr().out == ""
