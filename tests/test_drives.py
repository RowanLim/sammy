"""驱力系统测试。

这里测的不是"算得准不准"，而是**行为方向对不对**：
精力该降就降、无聊该涨就涨、被搭理该亲近、睡饱了该自己醒。
数字调参只改 drives.py 顶部的常量，方向错了才是 bug。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import drives
from sammy.drives import Drives, status_text
from sammy.expressions import EMOTIONS, EXPR_NAMES


def test_no_time_passed_changes_nothing():
    d = Drives()
    before = d.snapshot()
    d.tick(now=d.last_update)
    assert d.snapshot() == before


def test_awake_time_costs_energy_and_builds_boredom():
    d = Drives(energy=0.9, boredom=0.1)
    d.fast_forward(awake=2)
    assert d.energy < 0.9, "清醒要消耗精力"
    assert d.boredom > 0.1, "没人理它会变无聊"


def test_being_ignored_erodes_closeness():
    d = Drives(closeness=0.8)
    d.fast_forward(awake=8)
    assert d.closeness < 0.8, "长期没人理，关系该变淡"


def test_sleeping_shakes_off_boredom():
    """睡觉不只是"不长无聊"，而是把它解开 —— 睡醒该是精神好、想看点什么。"""
    d = Drives(energy=0.2, boredom=0.8)
    d.go_to_sleep()
    d.fast_forward(asleep=1)
    assert d.energy > 0.2, "睡着要回精力"
    assert d.boredom < 0.8, "睡着该把无聊解掉"


def test_waking_up_is_not_instantly_bored():
    """刚睡醒就"憋坏了"是不对的 —— 演示数据里发现的（睡得越久越无聊）。"""
    d = Drives(energy=0.3, boredom=1.0)
    d.go_to_sleep()
    d.fast_forward(asleep=8)
    assert d.energy > 0.9, "睡够了该充满电"
    assert d.boredom < 0.5, "睡一觉该把无聊也解开"
    assert status_text(d) != "有点无聊", "睡醒不该一脸无聊"


def test_sleeping_long_enough_wakes_it_up():
    """它不是在等用户叫它 —— 睡够了会自己醒。"""
    d = Drives(energy=0.3)
    d.go_to_sleep()
    d.fast_forward(asleep=6)
    assert not d.asleep, "睡饱了应该自己醒"
    assert d.energy > 0.85


def test_drives_never_leave_the_0_to_1_range():
    """边界值必须夹住 —— 否则界面会拿到荒谬的状态。"""
    d = Drives(energy=0.05, boredom=0.98, closeness=0.02)
    d.fast_forward(awake=48)
    for name in ("energy", "boredom", "closeness"):
        v = getattr(d, name)
        assert 0.0 <= v <= 1.0, f"{name}={v} 越界了"
    assert d.energy == 0.0, "48 小时不睡，精力该见底"

    d2 = Drives(energy=0.9, boredom=0.0, closeness=0.9)
    d2.fast_forward(asleep=48)
    for name in ("energy", "boredom", "closeness"):
        v = getattr(d2, name)
        assert 0.0 <= v <= 1.0, f"{name}={v} 越界了"


def test_interaction_reduces_boredom_and_raises_closeness():
    d = Drives(boredom=0.7, closeness=0.4)
    d.on_interaction()
    assert d.boredom < 0.7
    assert d.closeness > 0.4


def test_greeting_counts_more_than_a_poke():
    """用户主动打招呼，比随手戳一下更有分量 —— 这才像"关系"。

    ⚠️ 起始值必须离夹取边界足够远：默认 boredom=0.15 时，两种减幅都会把它砸到 0，
    比较就变成 0.0 < 0.0 —— **贴着边界做比较，量不出差异**。（这条第一版就栽在这。）
    """
    poke = Drives(closeness=0.4, boredom=0.9)
    greet = Drives(closeness=0.4, boredom=0.9)
    poke.on_interaction()
    greet.on_interaction(greeted=True)
    assert greet.closeness > poke.closeness
    assert greet.boredom < poke.boredom
    assert greet.boredom > 0, "别贴着地板比 —— 那说明这个测试量不出东西"


def test_interaction_wakes_it_unless_truly_exhausted():
    d = Drives(energy=0.05)
    d.go_to_sleep()
    d.on_interaction()
    assert d.asleep, "精力见底时，戳一下不该强行弄醒它"

    d2 = Drives(energy=0.25)
    d2.go_to_sleep()
    d2.on_interaction()
    assert not d2.asleep, "精神还行的话，被叫就该醒"


# ── 想不想说话（给"主动心跳"用）───────────────────


def test_want_to_talk_grows_with_boredom():
    low = Drives(boredom=0.1, closeness=0.6).want_to_talk
    high = Drives(boredom=0.8, closeness=0.6).want_to_talk
    assert high > low


def test_want_to_talk_grows_when_you_drift_apart():
    close = Drives(boredom=0.4, closeness=0.8).want_to_talk
    apart = Drives(boredom=0.4, closeness=0.1).want_to_talk
    assert apart > close, "关系变淡了，它该更想你"


def test_want_to_talk_is_a_probability():
    for boredom in (0.0, 0.5, 1.0):
        for closeness in (0.0, 0.5, 1.0):
            v = Drives(boredom=boredom, closeness=closeness).want_to_talk
            assert 0.0 <= v <= 1.0


# ── 表情 ─────────────────────────────────────────


def test_every_face_it_can_make_actually_exists():
    """防"魔数漂移"：表情编号重排后，这里必须立刻炸，而不是安静地摆错脸。"""
    states = [
        Drives(asleep=True),
        Drives(energy=0.05),
        Drives(energy=0.2),
        Drives(closeness=0.2, boredom=0.6),
        Drives(boredom=0.8),
        Drives(boredom=0.5),
        Drives(energy=0.9, boredom=0.05, closeness=0.9),
        Drives(energy=0.5, boredom=0.1, closeness=0.5),
    ]
    for s in states:
        face = s.expression()
        assert face in EXPR_NAMES, f"表情编号 {face} 不存在"


@pytest.mark.parametrize(
    "kwargs,expected_mood",
    [
        ({"asleep": True}, "sleep"),
        ({"energy": 0.05}, "sleep"),
        ({"energy": 0.2}, "sleepy"),
        ({"closeness": 0.2, "boredom": 0.6}, "expect"),
        ({"boredom": 0.8}, "bored"),
        ({"boredom": 0.5}, "curious"),
        ({"energy": 0.9, "boredom": 0.05, "closeness": 0.9}, "content"),
        ({"energy": 0.5, "boredom": 0.1, "closeness": 0.5}, "normal"),
    ],
)
def test_face_matches_the_intended_mood(kwargs, expected_mood):
    assert Drives(**kwargs).expression() == EMOTIONS[expected_mood]


def test_tired_and_bored_show_different_faces():
    """两条驱力必须能分辨 —— 否则"驱力系统"等于只做了一条。"""
    assert (
        Drives(energy=0.2, boredom=0.1).expression() != Drives(energy=0.9, boredom=0.8).expression()
    )


# ── 持久化 ───────────────────────────────────────


def test_save_and_load_round_trip(tmp_path):
    p = tmp_path / "drives.json"
    d = Drives(energy=0.42, boredom=0.66, closeness=0.31, asleep=True)
    d.save(p)
    back = Drives.load(p)
    assert (back.energy, back.boredom, back.closeness, back.asleep) == (
        0.42,
        0.66,
        0.31,
        True,
    )


def test_load_does_not_resurrect_a_fresh_sammy(tmp_path):
    """重启不该让它"满血复活" —— 否则人设是断的（这是持久化的全部意义）。"""
    p = tmp_path / "drives.json"
    Drives(energy=0.15, boredom=0.9, closeness=0.2).save(p)
    back = Drives.load(p)
    assert back.energy == 0.15 and back.boredom == 0.9


def test_missing_file_gives_defaults(tmp_path):
    d = Drives.load(tmp_path / "nope.json")
    assert 0 < d.energy <= 1


def test_corrupt_file_does_not_crash(tmp_path):
    p = tmp_path / "drives.json"
    p.write_text("{ 这不是 json", encoding="utf-8")
    assert Drives.load(p) is not None


def test_unknown_keys_in_file_are_ignored(tmp_path):
    """将来删掉某个字段时，旧的状态文件不该让程序起不来。"""
    p = tmp_path / "drives.json"
    p.write_text(json.dumps({"energy": 0.5, "某个删掉的字段": 1}), encoding="utf-8")
    assert Drives.load(p).energy == 0.5


def test_snapshot_is_json_serializable():
    snap = Drives().tick().snapshot()
    assert json.loads(json.dumps(snap))["face"] in EXPR_NAMES
    assert 0.0 <= snap["want_to_talk"] <= 1.0


def test_running_out_of_energy_makes_it_fall_asleep():
    """精力见底要**真的睡过去**，而不是一直挂着"困得不行"的状态。"""
    d = Drives(energy=0.15)
    d.fast_forward(awake=1)
    assert d.energy < 0.12
    assert d.asleep, "精力见底就该自己睡着"


def test_status_text_never_contradicts_the_face():
    """脸和话必须一致 —— 这**同一类矛盾踩过两次**（睡着/困得不行、想你了/普通），
    所以这里不只是断言一个特例，而是把"脸→话"的对应关系整条钉住。"""
    expected = {
        EMOTIONS["sleep"]: "睡着了",
        EMOTIONS["sleepy"]: "有点困了",
        EMOTIONS["expect"]: "想你了",
        EMOTIONS["bored"]: "有点无聊",
    }
    for kwargs in (
        {"asleep": True},
        {"energy": 0.05},
        {"energy": 0.2},
        {"closeness": 0.1, "boredom": 0.5},
        {"closeness": 0.05, "energy": 1.0},  # 睡醒后发现没人理它
        {"boredom": 0.8},
        {"energy": 0.9, "boredom": 0.0, "closeness": 0.9},
        {"energy": 0.5, "boredom": 0.1, "closeness": 0.5},
    ):
        d = Drives(**kwargs)
        face = d.expression()
        if face in expected:
            assert status_text(d) == expected[face], (
                f"{kwargs}：脸是「{face}」，话却说「{status_text(d)}」"
            )


def test_default_state_file_is_inside_the_project():
    """状态在项目文件夹里（Rowan 的隔离要求）—— 完整的隔离检查见 test_isolation.py。"""
    from sammy.paths import project_root

    assert str(drives.STATE_FILE).startswith(str(project_root()))


def test_fast_forward_refuses_two_modes_at_once():
    with pytest.raises(ValueError, match="一次只能推进"):
        Drives().fast_forward(awake=1, asleep=1)
