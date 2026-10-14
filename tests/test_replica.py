"""「桌上的一天」（`src/sammy/replica.py`）的判据。

这块要钉的是两件事，都不是「数字对不对」而是「**规矩**守没守」：

1. **真实数据一字不改。** 替身有自己的目录，它的账写在 `data/replica/`。
   这条要是漏了，某天一个 bug 就能把 Rowan 的 drives.json / mood.json /
   聊天记录改掉 —— 那是他的东西，压测不许碰。
2. **时间真的推了。** 一天里那些**按小时**长的东西（精力掉、无聊涨、
   亲近淡、心情回归）必须真的走到位 —— 否则「这一天」只是把脚本念了一遍。

另外钉住一条**分工**：`replay.py` 走他的真实流水，`replica.py` 走合成脚本，
两者互不冒充（读源码确认没人偷偷 import 对方那条路）。
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import replica

ROOT = pathlib.Path(__file__).resolve().parent.parent


def make_real(tmp_path: pathlib.Path) -> pathlib.Path:
    """搭一个「真实数据目录」的替身（不是他的真目录）—— 判据只在沙箱里跑。"""
    real = tmp_path / "data"
    real.mkdir(parents=True, exist_ok=True)
    (real / "chat.jsonl").write_text(
        json.dumps({"t": 0.0, "role": "user", "text": "别动我"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (real / "drives.json").write_text(
        json.dumps(
            {"energy": 0.85, "boredom": 0.15, "closeness": 0.55, "last_update": 1792008368.0},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (real / "mood.json").write_text(
        json.dumps({"valence": 0.15, "updated": 1792008368.0, "notes": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return real


def snap(real: pathlib.Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(real.iterdir()) if p.is_file()}


# ── 隔离：他的数据一字不改 ────────────────────────


def test_a_day_leaves_the_real_data_untouched(tmp_path):
    """最要紧的一条：过完这一天，真实目录里每个文件逐字节没变。"""
    real = make_real(tmp_path)
    before = snap(real)
    rep = replica.Replica(real_dir=real)
    rep.run(days=1, seed=7)
    assert rep.real_untouched(before) == [], "替身动了真实数据目录"
    assert snap(real) == before, "真实文件被改了"


def test_the_replica_writes_into_its_own_dir(tmp_path):
    """替身的账（驱力/心情/记忆）全落在 `data/replica/` 里。"""
    real = make_real(tmp_path)
    before = snap(real)
    rep = replica.Replica(real_dir=real)
    rep.run(days=1, seed=7)
    sim = replica.sim_data_dir(real)
    assert sim.name == "replica"
    names = sorted(p.name for p in sim.iterdir())
    assert "drives.json" in names and "mood.json" in names
    assert set(snap(real)) == set(before), "真实目录顶层凭空长出了文件"
    assert json.loads((sim / "drives.json").read_text(encoding="utf-8"))["energy"] != 0.85


def test_sim_dir_lives_inside_the_project_data_dir(tmp_path):
    """替身目录必须在**项目 data/ 里面**（隔离约定：一个项目的东西不散到机器上去）。"""
    real = make_real(tmp_path)
    assert replica.sim_data_dir(real) == real / "replica"


# ── 时间真的推了 ──────────────────────────────────


def test_one_day_of_script_really_moves_the_drives(tmp_path):
    """一天过完，精力必须掉下去、无聊涨上来 —— 没推时间的话这两个数一动不动。"""
    real = make_real(tmp_path)
    rep = replica.Replica(real_dir=real)
    start_energy = rep.drives.energy
    out = rep.run(days=1, seed=7)
    assert out.hours >= 6.0, f"这一天只过了 {out.hours} 小时"
    assert out.energy_min < start_energy - 0.3, "精力几乎没掉 —— 没有把时间喂给驱力"
    assert out.states[-1]["boredom"] > 0.5, "没人理了半天，无聊还在低位"
    assert out.greets == 1 and out.pokes == 1


def test_a_night_apart_eventually_makes_it_sleep(tmp_path):
    """「隔夜」那条拍子必须真能把它熬睡着 —— 这是这一天存在的理由。"""
    real = make_real(tmp_path)
    rep = replica.Replica(real_dir=real)
    steps = [
        replica.Beat(gap_s=0.0, kind="greet", text="早"),
        replica.Beat(gap_s=8 * 3600.0, kind="idle"),
        replica.Beat(gap_s=8 * 3600.0, kind="idle"),
    ]
    script = replica.ActivityScript(beats=steps, seed=1)
    out = rep.run(days=1, script=script)
    assert out.slept_once, "两天里一次都没睡着 —— 时间没被喂进去"
    assert out.energy_min < 0.2
    assert out.sleep_hours > 0.0, "睡过就该有睡眠时长"
    assert any(s["asleep"] for s in out.states)


def test_being_talked_to_keeps_the_mood_up_and_boredom_down(tmp_path):
    """反过来那条：每隔一阵被搭理一次，无聊清零、亲近涨、心情往上走。

    ⚠️ 这条**不**断言「不会睡着」：醒着的消耗是 0.10/小时，而打招呼只回 +0.06 ——
    被搭理只是让它撑得久一点（20 小时 vs 8 小时），撑不了无限久。
    这是真实的行为（见 docs/），不是这里该改的东西：判据只钉「交互接上了」。
    """
    real = make_real(tmp_path)
    rep = replica.Replica(real_dir=real)
    start_mood = rep.mood.mood.valence
    steps = [replica.Beat(gap_s=0.0, kind="greet", text="在吗")]
    for _ in range(4):
        steps.append(replica.Beat(gap_s=2 * 3600.0, kind="greet", text="还在吗"))
    out = rep.run(days=1, script=replica.ActivityScript(beats=steps, seed=2))
    assert out.states[-1]["boredom"] < 0.3, "被搭理了无聊还在涨 —— 交互没接上"
    assert out.states[-1]["closeness"] > 0.7
    assert out.valence_max > start_mood, "被搭理了心情没往上走"
    assert out.greets == 5


# ── 脚本与账本 ────────────────────────────────────


def test_script_is_the_same_shape_every_run():
    """同一个种子 → 同一天（可复现才敢报数字）。"""
    a = replica.day_script(days=2, seed=11)
    b = replica.day_script(days=2, seed=11)
    assert [s.as_dict() for s in a.beats] == [s.as_dict() for s in b.beats]
    c = replica.day_script(days=2, seed=12)
    assert [s.as_dict() for s in a.beats] != [s.as_dict() for s in c.beats]


def test_long_gaps_are_capped():
    """脚本里的超长空档按 8 小时封顶 —— 再长也只是把精力压到底，曲线会平掉。"""
    script = replica.from_beats([{"gap_s": 30 * 3600.0, "kind": "idle"}])
    assert script.beats[0].gap_s == replica.MAX_GAP_S


def test_report_books_agree_with_the_timeline(tmp_path):
    real = make_real(tmp_path)
    rep = replica.Replica(real_dir=real)
    steps = [
        replica.Beat(gap_s=0.0, kind="greet", text="早"),
        replica.Beat(gap_s=3600.0, kind="idle"),
    ]
    out = rep.run(days=1, script=replica.ActivityScript(beats=steps, seed=3))
    assert out.hours == 1.0
    assert out.beats == 2 and out.greets == 1
    assert len(out.states) == 3, "开场一帧 + 每拍一帧"
    text = "\n".join(out.human_lines())
    assert "1.0 小时" in text and "这一天" in text


def test_a_negative_gap_is_healed_not_fatal(tmp_path):
    """一拍出事记一笔接着过 —— 负的间隔自愈成 0，不该把一整天的账弄没。"""
    real = make_real(tmp_path)
    rep = replica.Replica(real_dir=real)
    script = replica.ActivityScript(
        beats=[
            replica.Beat(gap_s=0.0, kind="greet", text="你好"),
            replica.Beat(gap_s=-5.0, kind="greet", text="负时间"),
        ],
        seed=4,
    )
    out = rep.run(days=1, script=script)
    assert out.crashes == 0, "负间隔该被自愈成 0，不该炸"
    assert out.hours == 0.0


# ── 分工：和 replay 不是一条路 ────────────────────


def test_replica_does_not_read_the_real_chat_log():
    """复刻走合成脚本；读他的真实流水是 replay.py 的活 —— 两件事不许混。"""
    src = (ROOT / "src" / "sammy" / "replica.py").read_text(encoding="utf-8")
    assert "chat.jsonl" not in src, "复刻不该去读他的聊天记录"
    assert "import replay" not in src and "from . import replay" not in src
    # 零散布的「真的调用了回放」写法（注释里提 replay.py 不算）
    assert "replay.replay(" not in src and "replay.steps_from" not in src


def test_soak_script_wires_the_day_in():
    """压测脚本里那段真接线：默认跑、能关、报告里带账本。"""
    src = (ROOT / "scripts" / "soak.py").read_text(encoding="utf-8")
    assert "--no-day" in src
    assert "day_section(args)" in src
    assert "replica=" in src, "报告里没带复刻账本"
    assert "def day_section" in src
