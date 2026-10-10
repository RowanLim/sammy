#!/usr/bin/env python
"""T4 看门狗演示 —— 三条真命令路径，全部落在项目 .tmp/ 里，不碰真实数据。

① 崩溃循环：假孩子每次立刻崩 → 看门狗按 3/6/12/24 秒退避拉起、写 5 份日志、放弃（退 4）
② 正常退出：假孩子退 0 → 看门狗跟着下班（退 0），不留崩溃日志
③ 真 Sammy：本尊离屏跑起来，TERM 看门狗 → 它把 Sammy 送走、不复活（退 0），无日志

用法：.venv/bin/python scripts/watchdog_demo.py
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / ".tmp" / "watchdog-demo"
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str) -> bool:
    print(f"  {'✅' if ok else '❌'} {name} —— {detail}")
    if not ok:
        FAILURES.append(name)
    return ok


def fresh(home: Path) -> Path:
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True, exist_ok=True)
    return home


def state_of(home: Path) -> str:
    try:
        raw = (home / "watchdog.json").read_text(encoding="utf-8")
        return str(json.loads(raw).get("state", ""))
    except (OSError, json.JSONDecodeError):
        return ""


def wait_for(pred, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.2)
    return False


def crash_logs(home: Path) -> list[Path]:
    return sorted((home / "crashes").glob("crash-*.txt")) if (home / "crashes").is_dir() else []


def run_watchdog(home: Path, child: list[str], timeout: float) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["SAMMY_HOME"] = str(home)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["SAMMY_WATCHDOG_CHILD"] = shlex.join(child)
    proc = subprocess.run(
        [sys.executable, "-m", "sammy", "--watchdog"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode not in (0, 4):
        print(f"  （看门狗意外退出 {proc.returncode}，stderr 摘录：）")
        print("  " + "\n  ".join((proc.stderr or "").strip().splitlines()[:6]))
    return proc


def case_crash_loop() -> None:
    print("① 崩溃循环（假孩子每次立刻崩）")
    home = fresh(DEMO / "home-crash")
    script = DEMO / "boom.py"
    script.write_text(
        "import sys\nsys.stderr.write('boom-演示用\\n')\nsys.exit(2)\n", encoding="utf-8"
    )
    t0 = time.monotonic()
    proc = run_watchdog(home, [sys.executable, str(script)], timeout=120)
    elapsed = time.monotonic() - t0
    check(
        "退出码 4（放弃拉起）",
        proc.returncode == 4,
        f"实际 {proc.returncode}，总耗时 {elapsed:.1f}s",
    )
    logs = crash_logs(home)
    check("崩溃日志 5 份", len(logs) == 5, f"实际 {len(logs)} 份")
    waits = [int(x) for x in re.findall(r"(\d+) 秒后自动拉起", proc.stdout)]
    check("退避序列 3/6/12/24", waits == [3, 6, 12, 24], f"实际 {waits}")
    text = logs[-1].read_text(encoding="utf-8") if logs else ""
    check(
        "日志里有崩因和现场输出",
        "退出码 2" in text and "boom-演示用" in text,
        "退出码 2 + 最后输出",
    )
    check("状态文件 = gave_up", state_of(home) == "gave_up", state_of(home))


def case_clean_exit() -> None:
    print("② 正常退出（假孩子退 0）")
    home = fresh(DEMO / "home-clean")
    proc = run_watchdog(home, [sys.executable, "-c", "raise SystemExit(0)"], timeout=30)
    check("退出码 0（跟着下班）", proc.returncode == 0, f"实际 {proc.returncode}")
    check("没有崩溃日志", not crash_logs(home), f"{len(crash_logs(home))} 份")
    check("状态文件 = exited", state_of(home) == "exited", state_of(home))


def case_real_sammy_sigterm() -> None:
    print("③ 真 Sammy 离屏运行，TERM 看门狗")
    home = fresh(DEMO / "home-real")
    env = dict(os.environ)
    env["SAMMY_HOME"] = str(home)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("SAMMY_WATCHDOG_CHILD", None)
    wd = subprocess.Popen(
        [sys.executable, "-m", "sammy", "--watchdog"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        started = wait_for(lambda: state_of(home) == "running", 15)
        check("看门狗进入 running", started, f"state={state_of(home)}")
        time.sleep(4)  # 让真 Sammy 把窗口建起来（离屏跑，屏幕上不出现东西）
        kids = subprocess.run(["pgrep", "-P", str(wd.pid)], capture_output=True, text=True)
        kid_count = len([x for x in kids.stdout.split() if x])
        check("真 Sammy 作为孩子被拉起", kid_count >= 1, f"直系子进程 {kid_count} 个")
        wd.send_signal(signal.SIGTERM)
        rc = wd.wait(timeout=20)
        check("看门狗退 0 收工", rc == 0, f"实际 {rc}")
        check("状态文件 = stopped", state_of(home) == "stopped", state_of(home))
        left = subprocess.run(["pgrep", "-P", str(wd.pid)], capture_output=True, text=True)
        check("没有留下孩子进程", not left.stdout.strip(), f"残留 {left.stdout.split() or '无'}")
        check("没有崩溃日志", not crash_logs(home), f"{len(crash_logs(home))} 份")
    finally:
        if wd.poll() is None:
            wd.kill()
            wd.wait(timeout=5)


def main() -> int:
    DEMO.mkdir(parents=True, exist_ok=True)
    print(f"演示目录：{DEMO}（.tmp/ 下：不进版本库、不碰真实数据）\n")
    case_crash_loop()
    print()
    case_clean_exit()
    print()
    case_real_sammy_sigterm()
    print()
    if FAILURES:
        print(f"❌ 有 {len(FAILURES)} 项没过：{FAILURES}")
        return 1
    print("✅ 三条路径全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
