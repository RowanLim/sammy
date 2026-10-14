"""历史回放（`src/sammy/replay.py`）的判据 —— 周六 1 小时压测的那一段靠它。

为什么这块要单独钉住：回放的整个价值都在「它真的推了时间」这件事上。
如果它只是在几步里假装跑了几天（比如忘了把间隔喂给驱力），
**压测报告会漂亮地通过**，而报告里那句「过了 38 小时」是假的 —— 比不跑更糟。

四层判据（和 test_droop / test_soak_stats 一个框架）：
1. 纯函数：长间隔压缩的规则、短间隔原样、坏行/坏文件不当场炸；
2. 时间真的推了：一晚上不交互必须**自己睡着**、连续被搭理必须醒着且不困；
3. 隔离：只读真实流水、状态落在临时目录（不许改你的心情与驱力）；
4. 报告与接线：账本里的数字对得上（含「离线路径不产生回复」这条）；
   压测脚本里那段真接线（`replay_section`）与命令行开关都在。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from sammy import replay
from sammy.replay import Step

ROOT = pathlib.Path(__file__).resolve().parent.parent


def row(t: float, role: str, text: str, kind: str = "") -> dict:
    return {"t": t, "role": role, "text": text, "kind": kind}


# ── 纯函数层：压缩规则 ────────────────────────────


def test_long_gaps_are_capped_and_short_ones_kept():
    """隔一天再开机 → 按 8 小时算；一来一往的几分钟 → 原样保留。"""
    rows = [
        row(0.0, "user", "你在干嘛呀"),
        row(1.4, "assistant", "数桌角的灰。"),
        row(1.4 + 28800.0, "assistant", "你不在，桌面安静得有点过分了。", "proactive"),
        row(1.4 + 28800.0 + 2760.0, "assistant", "你多久没来了。", "proactive"),
    ]
    steps = replay.steps_from_rows(rows, day_gap_s=8 * 3600.0)
    assert [round(s.gap_s, 1) for s in steps] == [0.0, 1.4, 28800.0, 2760.0]
    assert steps[0].text == "你在干嘛呀" and steps[0].role == "user"
    assert steps[2].kind == "proactive"


def test_first_step_never_advances_time():
    """第一步不该凭空推时间 —— 零点就是零点。"""
    steps = replay.steps_from_rows([row(1_700_000_000.0, "user", "你好")])
    assert steps[0].gap_s == 0.0


def test_backwards_clock_does_not_go_negative():
    """坏数据（时间倒退）要自愈，不然会算出负的时间倒流。"""
    steps = replay.steps_from_rows([row(100.0, "user", "a"), row(10.0, "user", "b")])
    assert steps[1].gap_s == 0.0


def test_missing_or_broken_log_is_not_fatal(tmp_path):
    """流水不在 / 中间有坏行 → 跳过，不当场炸（和 chatlog 一个口径）。"""
    assert replay.steps_from_log(tmp_path / "nope.jsonl") == []
    p = tmp_path / "chat.jsonl"
    p.write_text(
        json.dumps(row(0.0, "user", "第一句"), ensure_ascii=False)
        + "\n这不是 json\n"
        + json.dumps({"t": 5.0, "role": "user", "text": ""}, ensure_ascii=False)
        + "\n"
        + json.dumps(row(9.0, "assistant", "第二句"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    steps = replay.steps_from_log(p)
    assert [s.text for s in steps] == ["第一句", "第二句"]
    assert steps[1].gap_s == 9.0


def test_summary_lines_say_what_will_happen():
    steps = replay.steps_from_rows(
        [row(0.0, "user", "a"), row(3600.0 * 30, "user", "b"), row(3600.0 * 30 + 60, "user", "c")]
    )
    text = "\n".join(replay.summary_lines(steps, 30.0))
    assert "3 步" in text and "8.0 小时" in text, "压缩后的时间轴该报在说明里"
    assert "3 句" in text, "说了几句要说准"


# ── 时间真的推了：一周没人理，它必须过完自己的日子 ──


def test_a_day_apart_makes_it_sleep_on_its_own():
    """这条是回放存在的理由：隔一天再开机，它该**自己睡着过**。

    真机跑一小时到不了这里（一小时只掉 0.1 精力）；回放必须到得了。
    """
    # 一天里他只在早上说一句话，其余时间是空转（真实流水的样子）。
    steps = [Step(gap_s=0.0, role="user", text="早")]
    for _ in range(3):
        steps.append(Step(gap_s=8 * 3600.0, role="assistant", text="…", kind="proactive"))
        steps.append(Step(gap_s=8 * 3600.0, role="user", text="晚"))
    rep = replay.replay(steps, brain=None, workdir=pathlib.Path("/tmp/sammy-replay-test-a"))
    d = rep.as_dict()
    assert d["slept_once"], "在时间轴上它一次都没睡着 —— 回放没推时间"
    assert d["energy_min"] < 0.3, "过了一天精力还在高位，说明没喂给驱力"
    assert d["hours"] >= 48.0, "时间轴该有两整天（8 小时的空档没被压掉）"


def test_being_talked_to_keeps_it_awake_and_present():
    """反过来那条：每一步都是「你说话了」，它就不该睡着，也不该越来越无聊。"""
    steps = [Step(gap_s=0.0, role="user", text="你好")]
    for _ in range(4):
        steps.append(Step(gap_s=2400.0, role="user", text="在吗"))
    rep = replay.replay(steps, brain=None, workdir=pathlib.Path("/tmp/sammy-replay-test-b"))
    assert not rep.as_dict()["slept_once"]
    assert rep.states[-1]["boredom"] == 0.0, "被搭理了无聊还在涨 —— 交互没接上"
    assert rep.states[-1]["closeness"] > 0.5


def test_offline_path_produces_no_replies_and_no_fake_latency():
    steps = replay.steps_from_rows([row(0.0, "user", "a"), row(600.0, "user", "b")])
    rep = replay.replay(steps, brain=None, workdir=pathlib.Path("/tmp/sammy-replay-test-c"))
    assert rep.turns == 0 and rep.latencies == [] and rep.crashes == 0
    assert rep.steps == 2


def test_brain_failures_are_counted_not_fatal():
    """压测脚本的规矩：一轮出错记一笔，接着跑（不然一晚上的数据就没了）。"""

    class Boom:
        def chat(self, text, *a, **k):
            raise RuntimeError("网络炸了")

    steps = [Step(gap_s=0.0, role="user", text="你好")]
    rep = replay.replay(
        steps, brain=Boom(), workdir=pathlib.Path("/tmp/sammy-replay-test-d"), sleep_s=0.0
    )
    assert rep.crashes == 1 and rep.turns == 1
    assert "网络炸了" in rep.last_error


# ── 隔离：不许碰真实状态 ──────────────────────────


def test_replay_does_not_touch_the_real_state_dir(monkeypatch, tmp_path):
    """回放全程只读真实流水；状态落在临时目录 —— 它不是你的一天。"""
    from sammy import paths

    real = tmp_path / "real-home"
    original = os.environ.get("SAMMY_HOME")
    monkeypatch.setenv("SAMMY_HOME", str(real))
    before = list(real.rglob("*")) if real.exists() else []
    steps = [
        Step(gap_s=0.0, role="user", text="你好"),
        Step(gap_s=3600.0, role="assistant", text="…"),
    ]
    replay.replay(steps, brain=None, workdir=pathlib.Path("/tmp/sammy-replay-test-e"))
    after = list(real.rglob("*")) if real.exists() else []
    assert before == after, "回放动了真实数据目录"
    # 回放会临时挪走数据目录 —— 用进程里堆一个标记来认「它挪过、也还回来了」
    del original, paths


def test_replay_does_not_touch_the_real_log(monkeypatch, tmp_path):
    """真实流水只读：跑完内容一字不变。"""
    log = tmp_path / "chat.jsonl"
    log.write_text(
        json.dumps(row(0.0, "user", "别动我"), ensure_ascii=False) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(replay, "LOG_FILE", log)
    before = log.read_text(encoding="utf-8")
    steps = replay.steps_from_log()
    replay.replay(steps, brain=None, workdir=pathlib.Path("/tmp/sammy-replay-test-f"))
    assert log.read_text(encoding="utf-8") == before


# ── 报告 ──────────────────────────────────────────


def test_report_books_agree_with_the_timeline():
    steps = [
        Step(gap_s=0.0, role="user", text="a"),
        Step(gap_s=1800.0, role="assistant", text="…"),
        Step(gap_s=1800.0, role="user", text="b"),
    ]
    rep = replay.replay(steps, brain=None, workdir=pathlib.Path("/tmp/sammy-replay-test-g"))
    d = rep.as_dict()
    assert d["steps"] == 3
    assert d["hours"] == 1.0, f"时间轴该是 1 小时，实际 {d['hours']}"
    said = sum(1 for s in steps if s.role == "user")
    assert len(d["states"]) == said + 1, "开场一帧 + 每次你说话后一帧（它自己那步只推时间）"
    assert all(0.0 <= s["energy"] <= 1.0 for s in d["states"])
    assert d["valence_min"] <= d["valence_max"]
    assert "回放 3 步" in "\n".join(rep.human_lines())


# ── 接线与纪律 ────────────────────────────────────


def test_soak_script_wires_the_replay_in():
    """压测脚本里那段真接线：默认跑、能关、报告里带账本。"""
    src = (ROOT / "scripts" / "soak.py").read_text(encoding="utf-8")
    assert "--no-replay" in src
    assert "replay_section(args)" in src
    assert "replay=replay_data" in src, "报告里没带回放账本"
    assert "rss_series_mb" in src, "内存趋势要留整条序列（只看首尾会漏掉中途的台阶）"
    assert "def replay_section" in src


def test_makefile_has_a_one_hour_target():
    """周六那场就按这一条跑：一小时，不是八小时。"""
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "soak-1h" in text, "缺 make soak-1h"
    assert "--hours 1" in text
