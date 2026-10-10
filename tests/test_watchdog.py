"""看门狗（T4）的判据：崩了必须自动拉起；每次崩溃必须留痕；该收手时必须收手。

全部离线：不真开窗口、不真等退避（sleep、时钟、每次运行的结局都可注入）。
另有四条**真子进程**用例（真拉起 python、真发信号）—— 加起来几秒钟。
理由很简单：不真的拉起一次进程、不真的把信号发出去，
就不知道看门狗到底行不行。
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from sammy import watchdog
from sammy.watchdog import RunOutcome, Watchdog, status_report

ROOT = Path(__file__).resolve().parents[1]


def outcome(code=None, *, duration=1.0, output=(), error=None, signo=None):
    """造一次假的「运行结局」：code 为正常退出码，signo 为信号编号，其余走默认"""
    rc = -signo if signo is not None else code
    return RunOutcome(returncode=rc, duration=duration, output=list(output), error=error)


class Harness:
    """脚本化「孩子怎么死」，并记账每一次退避等待。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.spawns = []
        self.slept = []

    def spawn(self, argv):
        self.spawns.append(list(argv))
        if not self.outcomes:
            raise AssertionError("结局脚本用完了 —— 看门狗多拉了一次？")
        return self.outcomes.pop(0)

    def sleep(self, secs):
        self.slept.append(secs)


def make_wd(tmp_path, outcomes, **kw):
    h = Harness(outcomes)
    params = {
        "crash_dir": tmp_path / "crashes",
        "status_file": tmp_path / "watchdog.json",
        "spawn": h.spawn,
        "sleep": h.sleep,
        "install_signals": False,
    }
    params.update(kw)
    return Watchdog(["python", "-m", "sammy"], **params), h


def read_status(tmp_path):
    return json.loads((tmp_path / "watchdog.json").read_text(encoding="utf-8"))


def crash_files(tmp_path):
    return sorted((tmp_path / "crashes").glob("crash-*.txt"))


# ── 正常路：退出码 0 = 你关了它，看门狗跟着下班 ─────────────────────────


def test_clean_exit_no_restart(tmp_path):
    wd, h = make_wd(tmp_path, [outcome(0)])
    assert wd.run() == 0
    assert len(h.spawns) == 1
    assert h.slept == []
    assert crash_files(tmp_path) == []
    assert read_status(tmp_path)["state"] == "exited"


# ── 崩了：拉起 + 留痕 ──────────────────────────────────────────────────


def test_crash_restarts_once_then_clean(tmp_path):
    wd, h = make_wd(tmp_path, [outcome(1, output=["冒烟了"]), outcome(0)])
    assert wd.run() == 0
    assert len(h.spawns) == 2
    assert h.slept == [watchdog.BACKOFF_BASE_S]


def test_crash_report_content(tmp_path):
    wd, _h = make_wd(
        tmp_path,
        [outcome(7, duration=2.5, output=["第一行", "第二行"]), outcome(0)],
    )
    assert wd.run() == 0
    text = crash_files(tmp_path)[0].read_text(encoding="utf-8")
    assert "退出码 7" in text
    assert "连续第 1 次" in text
    assert "2.5 秒" in text
    assert "第二行" in text
    assert "自动拉起" in text
    assert "Python" in text  # 环境行：日志要能回答「哪台机器、什么版本崩的」


def test_signal_crash_restarts(tmp_path):
    wd, h = make_wd(tmp_path, [outcome(signo=signal.SIGSEGV), outcome(0)])
    assert wd.run() == 0
    assert len(h.spawns) == 2
    text = crash_files(tmp_path)[0].read_text(encoding="utf-8")
    assert "SIGSEGV" in text


# ── 不该复活的两类：有人让它停 ─────────────────────────────────────────


def test_intentional_signal_stops(tmp_path):
    # 被 TERM 停 = 有人在让它停，不是崩溃 —— 不许复活（否则和停脚本打架）
    wd, h = make_wd(tmp_path, [outcome(signo=signal.SIGTERM)])
    assert wd.run() == 0
    assert len(h.spawns) == 1
    assert crash_files(tmp_path) == []
    st = read_status(tmp_path)
    assert st["state"] == "stopped"
    assert "SIGTERM" in st["note"]


def test_stop_requested_before_first_spawn(tmp_path):
    wd, h = make_wd(tmp_path, [outcome(0)])
    wd._on_signal(signal.SIGINT)
    assert wd.run() == 0
    assert h.spawns == []
    assert read_status(tmp_path)["state"] == "stopped"


# ── 崩溃循环：退避 + 放弃 ──────────────────────────────────────────────


def test_give_up_after_max_rapid(tmp_path):
    wd, h = make_wd(tmp_path, [outcome(1)] * 5)
    assert wd.run() == 4
    assert len(h.spawns) == 5
    assert h.slept == [3.0, 6.0, 12.0, 24.0]
    assert len(crash_files(tmp_path)) == 5
    assert read_status(tmp_path)["state"] == "gave_up"


def test_backoff_caps_at_max(tmp_path):
    wd, h = make_wd(tmp_path, [outcome(1)] * 8, backoff_base=1.0, backoff_max=5.0, max_rapid=8)
    assert wd.run() == 4
    assert h.slept == [1.0, 2.0, 4.0, 5.0, 5.0, 5.0, 5.0]


def test_healthy_run_resets_backoff(tmp_path):
    # 活得够久（不低于 healthy_run_s）再崩 = 新问题，退避从 3 秒重来
    wd, h = make_wd(tmp_path, [outcome(1, duration=700), outcome(1, duration=700), outcome(0)])
    assert wd.run() == 0
    assert h.slept == [3.0, 3.0]


def test_rapid_count_grows(tmp_path):
    wd, h = make_wd(
        tmp_path,
        [outcome(1, duration=700), outcome(1, duration=1), outcome(1, duration=1), outcome(0)],
    )
    assert wd.run() == 0
    assert h.slept == [3.0, 6.0, 12.0]


def test_spawn_failure_reported_and_gives_up(tmp_path):
    # 连起都起不来（比如 run.sh 被删了）也要留痕，并且最终收手
    wd, _h = make_wd(tmp_path, [outcome(None, duration=0.0, error="FileNotFoundError: run.sh")] * 5)
    assert wd.run() == 4
    text = crash_files(tmp_path)[-1].read_text(encoding="utf-8")
    assert "起都起不来" in text
    assert "FileNotFoundError" in text
    assert "不再拉起" in text


# ── 文件命名与保留策略 ─────────────────────────────────────────────────


def test_crash_files_same_second_get_sequence(tmp_path):
    ts = 1_760_000_000.0
    wd, _h = make_wd(tmp_path, [outcome(1), outcome(1), outcome(0)], now=lambda: ts)
    assert wd.run() == 0
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(ts))
    names = [p.name for p in crash_files(tmp_path)]
    assert names == [f"crash-{stamp}-01.txt", f"crash-{stamp}-02.txt"]


def test_prune_keeps_newest(tmp_path):
    ts = 1_760_000_000.0
    wd, _h = make_wd(tmp_path, [outcome(1)] * 5, keep_crashes=3, now=lambda: ts)
    assert wd.run() == 4
    names = [p.name for p in crash_files(tmp_path)]
    assert len(names) == 3
    assert names[0].endswith("-03.txt")
    assert names[-1].endswith("-05.txt")


# ── 状态文件：现在在盯着、刚才崩过、拉起了几回 ─────────────────────────


def test_status_lifecycle(tmp_path):
    state_file = tmp_path / "watchdog.json"
    snapshots = []
    queue = [outcome(1), outcome(0)]

    def spawn(argv):
        snapshots.append(("spawn", json.loads(state_file.read_text(encoding="utf-8"))))
        return queue.pop(0)

    def sleep(secs):
        snapshots.append(("sleep", json.loads(state_file.read_text(encoding="utf-8"))))

    wd = Watchdog(
        ["python", "-m", "sammy"],
        crash_dir=tmp_path / "crashes",
        status_file=state_file,
        spawn=spawn,
        sleep=sleep,
        install_signals=False,
    )
    assert wd.run() == 0
    assert [k for k, _ in snapshots] == ["spawn", "sleep", "spawn"]
    _, s0 = snapshots[0]
    assert s0["state"] == "running" and s0["restarts"] == 0
    _, s1 = snapshots[1]
    assert s1["state"] == "restarting" and s1["restarts"] == 1
    assert str(s1["last_crash"]["file"]).startswith("crash-")
    _, s2 = snapshots[2]
    assert s2["state"] == "running" and s2["restarts"] == 1
    assert "拉起" in s2["note"]


# ── 崩溃日志的凭证打码（尽力而为）──────────────────────────────────────


def test_redact_scrubs_likely_secrets():
    text = (
        "错误里混进了 sk-abcdef1234567890 和 "
        'api_key = "abcd1234efgh5678" 还有 Bearer eyJhbGciOiJIUzI1NiIs 这些东西'
    )
    out = watchdog.redact(text)
    assert "sk-abcdef1234567890" not in out
    assert "abcd1234efgh5678" not in out
    assert "eyJhbGciOiJIUzI1NiIs" not in out
    assert "sk-***" in out
    assert "api_key" in out  # 字段名留着 —— 排查时知道「是 key 出的事」就够了
    assert watchdog.redact("普通的一行，没有秘密") == "普通的一行，没有秘密"


def test_report_truncates_tail(tmp_path):
    lines = [f"line {i}" for i in range(300)]
    wd, _h = make_wd(tmp_path, [outcome(1, output=lines), outcome(0)], report_lines=10)
    assert wd.run() == 0
    text = crash_files(tmp_path)[0].read_text(encoding="utf-8")
    assert "最后 10 行" in text
    assert "共 300 行" in text
    assert "line 299" in text
    assert "line 290" in text
    assert "line 289" not in text


# ── 真子进程：真的拉起 python、真的把信号发出去 ─────────────────────────


def _spawn_child(code: str) -> subprocess.Popen:
    """起一个真孩子（真 python、真信号），等它先在 stdout 打出 ready 再继续 ——
    先握手后发信号，测试里就没有竞态。"""
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "ready"
    return child


def test_terminate_escalates_int_to_term():
    # 孩子故意对 INT 不理不睬（Qt 主循环里的 Python 就是这个脾气）——
    # 看门狗必须升级到 TERM，而不是干等
    child = _spawn_child(
        "import signal, time; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "print('ready', flush=True); time.sleep(30)"
    )
    try:
        t0 = time.monotonic()
        chain = watchdog.terminate_child(child, signal.SIGINT, grace_s=0.5, kill_grace_s=0.5)
        assert chain == ["INT", "TERM"]
        assert child.wait(timeout=5) == -signal.SIGTERM
        assert time.monotonic() - t0 < 3
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_terminate_respects_quick_death():
    child = _spawn_child("import time; print('ready', flush=True); time.sleep(30)")
    try:
        chain = watchdog.terminate_child(child, signal.SIGTERM, grace_s=0.5, kill_grace_s=0.5)
        assert chain == ["TERM"]
        assert child.wait(timeout=5) == -signal.SIGTERM
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_real_child_crash_loop(tmp_path):
    """真子进程版本：真拉起 python、真的每次崩、真的写 5 份日志然后收手。"""
    script = tmp_path / "boom.py"
    script.write_text(
        "import sys\nsys.stderr.write('boom-立刻崩\\n')\nsys.exit(2)\n",
        encoding="utf-8",
    )
    slept = []
    wd = Watchdog(
        [sys.executable, str(script)],
        crash_dir=tmp_path / "crashes",
        status_file=tmp_path / "watchdog.json",
        sleep=slept.append,
        install_signals=False,
    )
    assert wd.run() == 4
    assert slept == [3.0, 6.0, 12.0, 24.0]
    files = crash_files(tmp_path)
    assert len(files) == 5
    text = files[-1].read_text(encoding="utf-8")
    assert "boom-立刻崩" in text
    assert "退出码 2" in text


# ── 盯什么：run.sh 优先、环境变量口子 ─────────────────────────────────


def test_child_command_resolution(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMMY_WATCHDOG_CHILD", raising=False)
    root = tmp_path / "root"
    root.mkdir()
    # 没有 run.sh → 退回当前解释器
    assert watchdog.child_command(["--kiosk"], root=root) == [
        sys.executable,
        "-m",
        "sammy",
        "--kiosk",
    ]
    # 有 run.sh → 优先用它（和用户自己跑是同一条路）
    (root / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    assert watchdog.child_command(["--kiosk"], root=root) == [str(root / "run.sh"), "--kiosk"]
    # 测试口子：SAMMY_WATCHDOG_CHILD 整条替换，额外参数照常带上
    monkeypatch.setenv("SAMMY_WATCHDOG_CHILD", shlex.join([sys.executable, "-c", "exit(0)"]))
    assert watchdog.child_command(["--kiosk"], root=root) == [
        sys.executable,
        "-c",
        "exit(0)",
        "--kiosk",
    ]


# ── 状态查看（--watchdog-status 的底）─────────────────────────────────


def test_status_report_never_ran(tmp_path):
    text = status_report(crash_dir=tmp_path / "crashes", status_file=tmp_path / "watchdog.json")
    assert "看门狗" in text
    assert "没跑过" in text
    assert "make watchdog" in text


def test_status_report_running(tmp_path, monkeypatch):
    st = {
        "state": "running",
        "pid": 4242,
        "restarts": 2,
        "crashes": 2,
        "started_at_ts": time.time() - 600,
        "updated_at": "2026-10-11 04:00:00",
        "note": "看护开始",
    }
    (tmp_path / "watchdog.json").write_text(json.dumps(st), encoding="utf-8")
    monkeypatch.setattr(watchdog, "_pid_alive", lambda pid: True)
    text = status_report(crash_dir=tmp_path / "crashes", status_file=tmp_path / "watchdog.json")
    assert "在盯着" in text
    assert "4242" in text
    assert "已拉起 2 次" in text
    monkeypatch.setattr(watchdog, "_pid_alive", lambda pid: False)
    text = status_report(crash_dir=tmp_path / "crashes", status_file=tmp_path / "watchdog.json")
    assert "已经不在了" in text


def test_status_report_lists_crashes(tmp_path):
    cd = tmp_path / "crashes"
    cd.mkdir()
    (cd / "crash-20261011-010101-01.txt").write_text("x", encoding="utf-8")
    (cd / "crash-20261011-020202-01.txt").write_text("x", encoding="utf-8")
    text = status_report(crash_dir=cd, status_file=tmp_path / "watchdog.json")
    assert "2 份" in text
    assert "020202" in text


# ── 命令行路径：main() 接上 --watchdog / --watchdog-status ────────────


def test_cli_watchdog_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SAMMY_HOME", str(tmp_path))
    from sammy.__main__ import main

    assert main(["--watchdog-status"]) == 0
    out = capsys.readouterr().out
    assert "看门狗" in out
    assert "没跑过" in out


def test_cli_watchdog_clean_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMMY_HOME", str(tmp_path))
    monkeypatch.setenv(
        "SAMMY_WATCHDOG_CHILD", shlex.join([sys.executable, "-c", "raise SystemExit(0)"])
    )
    from sammy.__main__ import main

    assert main(["--watchdog"]) == 0
    st = json.loads((tmp_path / "watchdog.json").read_text(encoding="utf-8"))
    assert st["state"] == "exited"


def test_cli_watchdog_stops_on_sigterm(tmp_path):
    """真命令：起一个真看门狗进程，TERM 它 —— 它要送走孩子、自己退 0 收工。"""
    env = dict(os.environ)
    env.update(
        SAMMY_HOME=str(tmp_path),
        PYTHONPATH=str(ROOT / "src"),
        SAMMY_WATCHDOG_CHILD=shlex.join([sys.executable, "-c", "import time; time.sleep(30)"]),
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "sammy", "--watchdog"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        status_path = tmp_path / "watchdog.json"
        st = {}
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                st = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                st = {}
            if st.get("state") == "running":
                break
            time.sleep(0.1)
        assert st.get("state") == "running"
        time.sleep(0.8)  # 让孩子真的被拉起来
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
        fin = json.loads(status_path.read_text(encoding="utf-8"))
        assert fin["state"] == "stopped"
        assert crash_files(tmp_path) == []
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
