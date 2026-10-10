"""心情系统：分档、推动、回归、下限、落盘。

为什么这些判据要写死：
- **下限**那条最要紧 —— 陪伴产品最容易在"你不理我"上翻车（变成情感绑架），
  所以"没人理也不许低于 FLOOR"和"低落时提示词里必须写『不要抱怨对方不理你』"都要钉住。
- **回归**那条防的是另一头：一件事不该把它的心情绑架一整天。
- 落盘是连续性本身：读不出来就当默认值，绝不能因为心情文件坏了连聊天都聊不了。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import mood as M

# ── 分档 ──────────────────────────────────────────


@pytest.mark.parametrize(
    "v,label",
    [(-0.5, "低落"), (-0.1, "有点蔫"), (0.1, "平静"), (0.4, "不错"), (0.8, "很好")],
)
def test_label_reads_like_human_words(v, label):
    assert M.label_of(v) == label


# ── 推动 ──────────────────────────────────────────


def test_positive_expression_lifts_the_mood():
    assert M.nudge_value(0.0, 21) > 0.0  # 爱心
    assert M.nudge_value(0.0, 6) < 0.0  # 伤心
    assert M.nudge_value(0.0, 2) == 0.0, "普通脸不该动心情"


def test_mood_is_clamped_both_ways():
    v = 0.95
    for _ in range(20):
        v = M.nudge_value(v, 21)
    assert v <= 1.0
    v = M.FLOOR + 0.01
    for _ in range(20):
        v = M.nudge_value(v, 6)
    assert v >= M.FLOOR, "再难过也不许突破下限"


def test_a_single_reply_only_nudges_it_partway():
    """一件事不该把心情定死 —— 推动量是小的。"""
    assert 0 < M.nudge_value(0.15, 21) - 0.15 < 0.3


# ── 回归基线 ──────────────────────────────────────


def test_decay_pulls_back_to_home():
    assert M.decayed(1.0, 0.0) == 1.0, "没过时间不该变"
    half = M.decayed(1.0, M.HALF_LIFE_H)
    want = M.HOME + (1.0 - M.HOME) * 0.5
    assert abs(half - want) < 1e-6, "一个半衰期应该只剩一半距离"
    assert abs(M.decayed(1.0, M.HALF_LIFE_H * 10) - M.HOME) < 0.01, "很久之后回到基线"


# ── 没人理的时候（最需要小心的一条）───────────────


def test_being_ignored_only_starts_mattering_after_a_while():
    assert M.alone_drift(0.3, 0.5) == 0.3, "刚安静一会儿不该有任何变化"
    assert M.alone_drift(0.3, M.ALONE_AFTER_H + 1) < 0.3


def test_being_ignored_never_bottom_out():
    """**防情感绑架**：连着几天没人理，也不许掉穿下限。"""
    v = M.alone_drift(0.3, 24 * 7)
    assert v >= M.FLOOR, "掉穿了下限 —— 它会变成抱怨机器"


# ── 提示词 ────────────────────────────────────────


def test_prompt_line_carries_the_mood():
    line = M.prompt_line(0.7)
    assert "很好" in line and "活泼" in line


def test_low_mood_must_not_guilt_trip_the_user():
    """心情差的时候，提示词里**必须**明确禁止"抱怨对方不理我"。"""
    line = M.prompt_line(-0.4, ["安静好一阵了"])
    assert "低落" in line
    assert "不要抱怨" in line, "少了这句，它就有机会说出让人想卸载的话"


def test_prompt_line_includes_recent_notes_but_not_all_of_them():
    line = M.prompt_line(0.1, ["事件一", "事件二", "事件三", "事件四"])
    assert "事件四" in line and "事件一" not in line, "提示词不该变成流水账"


# ── 默认表情 ──────────────────────────────────────


@pytest.mark.parametrize("v", [-1.0, -0.3, 0.0, 0.3, 1.0])
def test_idle_expression_is_always_a_valid_face(v):
    assert 1 <= M.idle_expression(v) <= 35


def test_idle_expression_follows_the_mood():
    assert M.idle_expression(0.8) != M.idle_expression(-0.4), "心情好和心情差不该同一张脸"


# ── 落盘 ──────────────────────────────────────────


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "mood.json"
    t = M.MoodTracker(path=path)
    t.nudge(21)
    t.poke()
    t.save()
    again = M.MoodTracker(path=path)
    assert again.mood.valence == pytest.approx(t.mood.valence)
    assert again.mood.notes, "最近发生的事也要留下来"


def test_missing_file_means_default_mood(tmp_path):
    t = M.MoodTracker(path=tmp_path / "没有这个文件.json")
    assert t.mood.valence == M.HOME


def test_corrupt_file_does_not_break_anything(tmp_path):
    """心情文件坏了 → 当默认值。**绝不能因为读不出心情就连聊天都聊不了。**"""
    path = tmp_path / "mood.json"
    path.write_text("{这不是 JSON", encoding="utf-8")
    t = M.MoodTracker(path=path)
    assert t.mood.valence == M.HOME
    t.save()  # 而且还能把它写回正常


def test_notes_are_capped(tmp_path):
    t = M.MoodTracker(path=tmp_path / "mood.json")
    for _ in range(20):
        t.nudge(21)
    assert len(t.mood.notes) <= M.MAX_NOTES


def test_write_failure_is_a_warning_not_a_crash(tmp_path, capsys):
    t = M.MoodTracker(path=tmp_path / "mood.json")
    t.path = pathlib.Path("/不会存在/mood.json")
    t.save()
    assert "心情存不下来" in capsys.readouterr().out


# ── tick ──────────────────────────────────────────


def test_tick_decays_and_moves_the_clock(tmp_path):
    t = M.MoodTracker(path=tmp_path / "mood.json", now=1000.0)
    t.mood.valence = 1.0
    t.mood.updated = 1000.0
    t.tick(now=1000.0 + M.HALF_LIFE_H * 3600)
    assert M.HOME < t.mood.valence < 1.0, "应该往基线走了一半"
    assert t.mood.updated == 1000.0 + M.HALF_LIFE_H * 3600


def test_tick_includes_being_alone(tmp_path):
    t = M.MoodTracker(path=tmp_path / "mood.json", now=0.0)
    t.mood.valence = 0.5
    t.mood.updated = 0.0
    t.tick(now=3600.0, hours_alone=10.0)
    assert t.mood.valence < 0.5


def test_describe_is_readable(tmp_path):
    t = M.MoodTracker(path=tmp_path / "mood.json")
    out = t.describe()
    assert "心情" in out and "空闲时会摆的脸" in out


def test_json_is_written_with_the_documented_shape(tmp_path):
    path = tmp_path / "mood.json"
    t = M.MoodTracker(path=path)
    t.save()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == {"valence", "updated", "notes"}
