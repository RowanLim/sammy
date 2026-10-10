"""T4 看门狗 —— 崩了自动拉起 + 崩溃日志留痕。

为什么需要它：Sammy 的目标形态是「长期开在桌面上」，而桌面应用总有崩的时候
（Qt 插件、显卡驱动、偶发内存问题……）。没有看门狗时，崩了就从桌面上消失，
而且崩因没有任何记录 —— 连它曾经崩过都不知道。这个模块只做两件事：
盯着进程、崩了留痕拉起。

三条设计决定（都写下来，方便以后再拍板）：
- **退出码 0 = 你主动关了它**（点 ✕ / 菜单退出）→ 看门狗跟着下班，不复活。
- **被 INT / TERM / HUP 停 = 有人让它停**（Ctrl+C、停脚本、kill）
  → 同样不复活。看门狗跟人抢进程是最烦人的失败模式，宁可少拉起。
- **连续快速崩溃到上限 → 放弃拉起**并留日志退出（码 4）：安装已坏（缺库之类）时，
  无限闪屏比不拉起还糟。活过 10 分钟算「恢复健康」，计数清零、退避重置。

退出码约定：0 = 正常收工（孩子正常退出 / 被请求停止）；4 = 连续崩溃、放弃拉起。

数据去向（隔离规矩）：崩溃日志 `data/crashes/crash-*.txt`，状态 `data/watchdog.json`，
都在项目目录里、都随 `data/` 被 git 忽略。跟随 `SAMMY_HOME` 环境变量。

测试口子（生产不用）：环境变量 `SAMMY_WATCHDOG_CHILD` 可整条替换被盯的命令
（集成测试用；到树莓派上要换启动脚本时也用它，额外参数照常带上）。
"""

from __future__ import annotations

import collections
import contextlib
import json
import os
import platform
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import paths

BACKOFF_BASE_S = 3.0  # 第一次崩溃后等 3 秒再拉
BACKOFF_MAX_S = 60.0  # 退避封顶
HEALTHY_RUN_S = 600.0  # 活过 10 分钟 = 恢复健康：退避和连续计数清零
MAX_RAPID_CRASHES = 5  # 连续快速崩到第 5 次：放弃
KEEP_CRASHES = 20  # 崩溃日志最多留 20 份
TAIL_LINES = 200  # 内存里滚动保留的输出行数
REPORT_TAIL_LINES = 80  # 写进崩溃日志的行数
STOP_GRACE_S = 3.0  # 收工时给孩子自己退出的宽限
STOP_KILL_GRACE_S = 3.0  # 升级到 TERM / KILL 的宽限
INTENTIONAL_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
GAVE_UP_CODE = 4


@dataclass
class RunOutcome:
    """一次「孩子运行」的结果。returncode=None 表示连起都没起来（error 里是原因）。"""

    returncode: int | None
    duration: float
    output: list[str]
    error: str | None = None


def signal_title(signo: int) -> str:
    """把 11 这种数字变成 SIGSEGV(11) 这种能看懂、也能搜的东西。"""
    try:
        name = signal.Signals(signo).name
    except ValueError:
        name = f"信号 {signo}"
    return f"{name}({signo})"


def child_command(extra: Sequence[str], *, root: Path | None = None) -> list[str]:
    """看门狗盯什么：默认 run.sh 加透传参数（和用户自己跑是同一条路）。

    没有 run.sh 时（比如打包成 .app 之后）就退回 python -m sammy 那条路。
    测试口子 SAMMY_WATCHDOG_CHILD 整条替换（额外参数照常带上）。
    """
    env_cmd = os.environ.get("SAMMY_WATCHDOG_CHILD", "").strip()
    if env_cmd:
        return [*shlex.split(env_cmd), *extra]
    root = root or paths.project_root()
    runner = root / "run.sh"
    if runner.is_file():
        return [str(runner), *extra]
    return [sys.executable, "-m", "sammy", *extra]


# ── 崩溃日志里的凭证打码（尽力而为，不是安全边界）──────────────────────
_REDACT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "sk-***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1***"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)"
            r"([\"']?\s*[:=]\s*[\"']?)([^\s\"',;)]{6,})"
        ),
        r"\1\2***",
    ),
]


def redact(text: str) -> str:
    """崩溃日志落盘前抹掉长得像凭证的东西。

    「尽力而为」写清楚：模式表就这几条，防的是手滑把 key 写进日志这种事故，
    不是拿去对抗有心人。真实防线还是「凭证都在 data/.env、data/ 不进版本库」。
    """
    for rx, sub in _REDACT_RULES:
        text = rx.sub(sub, text)
    return text


def terminate_child(
    proc: subprocess.Popen,
    signo: int,
    *,
    grace_s: float = STOP_GRACE_S,
    kill_grace_s: float = STOP_KILL_GRACE_S,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[str]:
    """礼貌地送走孩子：先原信号 → 宽限 → TERM → 宽限 → KILL，一级一级来。

    为什么要升级链：Qt 的主循环里 Python 信号处理经常轮不到执行
    （Ctrl+C 在 Qt 窗口上「没反应」是常见现象），光发 INT 可能等不来退出。
    返回升级链（如 ["INT", "TERM"]），写进日志方便事后判断它是不是不情愿走的。
    """
    chain: list[str] = []

    def send(s: signal.Signals) -> None:
        chain.append(s.name.removeprefix("SIG"))
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(s)

    def wait_dead(timeout: float) -> None:
        end = monotonic() + timeout
        while proc.poll() is None and monotonic() < end:
            sleep(0.05)

    send(signal.Signals(signo))
    wait_dead(grace_s)
    if proc.poll() is None:
        send(signal.SIGTERM)
        wait_dead(kill_grace_s)
    if proc.poll() is None:
        send(signal.SIGKILL)
        wait_dead(kill_grace_s)
    return chain


def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


class Watchdog:
    """盯着一个孩子进程：崩了拉起、留痕；该收手时收手。"""

    def __init__(
        self,
        child_argv: Sequence[str],
        *,
        crash_dir: Path | None = None,
        status_file: Path | None = None,
        spawn: Callable[[list[str]], RunOutcome] | None = None,
        sleep: Callable[[float], None] | None = None,
        now: Callable[[], float] | None = None,
        backoff_base: float = BACKOFF_BASE_S,
        backoff_max: float = BACKOFF_MAX_S,
        healthy_run_s: float = HEALTHY_RUN_S,
        max_rapid: int = MAX_RAPID_CRASHES,
        keep_crashes: int = KEEP_CRASHES,
        tail_lines: int = TAIL_LINES,
        report_lines: int = REPORT_TAIL_LINES,
        install_signals: bool = True,
        stop_grace_s: float = STOP_GRACE_S,
        stop_kill_grace_s: float = STOP_KILL_GRACE_S,
    ) -> None:
        self.child_argv = [str(a) for a in child_argv]
        self.crash_dir = Path(crash_dir) if crash_dir else paths.data_dir() / "crashes"
        self.status_file = Path(status_file) if status_file else paths.data_dir() / "watchdog.json"
        self._spawn_fn = spawn if spawn is not None else self._spawn_real
        self._sleep = sleep if sleep is not None else self._sleep_responsive
        self._now = now or time.time
        self.backoff_base = float(backoff_base)
        self.backoff_max = float(backoff_max)
        self.healthy_run_s = float(healthy_run_s)
        self.max_rapid = max(1, int(max_rapid))
        self.keep_crashes = max(1, int(keep_crashes))
        self.tail_lines = max(1, int(tail_lines))
        self.report_lines = max(1, int(report_lines))
        self.install_signals = install_signals
        self.stop_grace_s = float(stop_grace_s)
        self.stop_kill_grace_s = float(stop_kill_grace_s)
        self._stop_signal: int | None = None
        self._restarts = 0
        self._crashes = 0
        self._last_crash: dict | None = None
        self._started_at = float(self._now())

    # ── 收工信号（也供测试直接调用）──────────────────────────────────

    def _on_signal(self, signo: int, frame=None) -> None:
        if self._stop_signal is None:
            self._stop_signal = int(signo)
            print(f"\n收到 {signal_title(signo)} —— 收工中（不会再拉起）。", flush=True)

    def run(self) -> int:
        """进入看护循环。返回 0 = 正常收工；4 = 连续崩溃、放弃拉起。"""
        restore = self._install_handlers() if self.install_signals else None
        try:
            return self._run_loop()
        finally:
            if restore:
                for sig, handler in restore.items():
                    signal.signal(sig, handler)

    def _install_handlers(self) -> dict[signal.Signals, object] | None:
        if threading.current_thread() is not threading.main_thread():
            return None  # 信号只能装在主线程；装在别处会炸
        old: dict[signal.Signals, object] = {}
        for sig in INTENTIONAL_SIGNALS:
            old[sig] = signal.getsignal(sig)
            signal.signal(sig, self._on_signal)
        return old

    def _run_loop(self) -> int:
        print(f"🛡️ 看门狗：盯着 {self.child_argv[0]}（崩了自动拉起；日志进 {self.crash_dir}/）")
        print("   收工：Ctrl+C，或 kill 本进程 —— 会先把 Sammy 好好送走。")
        rapid = 0
        while True:
            if self._stop_signal is not None:
                self._write_status(
                    "stopped", note=f"收到 {signal_title(self._stop_signal)}，看门狗收工"
                )
                return 0
            note = "看护开始" if self._crashes == 0 else f"第 {self._crashes} 次崩溃后重新拉起"
            self._write_status("running", note=note)
            result = self._spawn_fn(self.child_argv)

            stop_reason = self._stop_reason(result)
            if stop_reason is not None:
                self._write_status("stopped", note=stop_reason)
                print(f"停：{stop_reason}。不拉起。")
                return 0
            if result.error is None and result.returncode == 0:
                self._write_status("exited", note="Sammy 正常退出")
                print("Sammy 正常退出。看门狗下班。")
                return 0

            # —— 这里是「崩了」：留痕、决定拉不拉 ——
            self._crashes += 1
            rapid = rapid + 1 if result.duration < self.healthy_run_s else 1
            give_up = rapid >= self.max_rapid
            delay = (
                None if give_up else min(self.backoff_base * (2 ** (rapid - 1)), self.backoff_max)
            )
            path = self._write_crash(result, rapid=rapid, delay=delay)
            self._prune_crashes()
            self._last_crash = {
                "file": path.name,
                "at": _fmt_ts(self._now()),
                "exit": self._describe(result),
            }
            if give_up:
                self._write_status(
                    "gave_up", note=f"连续 {rapid} 次快速崩溃，停止自动拉起（先看日志）"
                )
                print(f"❌ 连续 {rapid} 次迅速崩溃 —— 先停止拉起，避免无限闪屏。日志：{path}")
                return GAVE_UP_CODE
            self._restarts += 1
            self._write_status("restarting", note=f"第 {rapid} 次崩溃；{delay:.0f} 秒后拉起")
            print(f"⚠️ Sammy 崩了：{self._describe(result)}（第 {rapid} 次）。日志：{path}")
            print(f"   {delay:.0f} 秒后自动拉起。")
            self._sleep(delay)

    def _stop_reason(self, result: RunOutcome) -> str | None:
        if self._stop_signal is not None:
            return f"收到 {signal_title(self._stop_signal)}"
        rc = result.returncode
        if rc is not None and rc < 0 and -rc in INTENTIONAL_SIGNALS:
            return f"孩子被 {signal_title(-rc)} 停掉（属于「有人让它停」）"
        return None

    # ── 真拉起（生产路径）────────────────────────────────────────────

    def _spawn_real(self, argv: list[str]) -> RunOutcome:
        """真拉起：管道接住它的输出（实时转发到我们这边 + 留尾部给崩溃日志）。"""
        t0 = time.monotonic()
        tail: collections.deque[str] = collections.deque(maxlen=self.tail_lines)
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(paths.project_root()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            return RunOutcome(None, 0.0, [], f"{type(exc).__name__}: {exc}")

        def pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                tail.append(line)
                print(f"  │ {line}", flush=True)

        reader = threading.Thread(target=pump, name="sammy-child-output", daemon=True)
        reader.start()
        terminated = False
        while proc.poll() is None:
            if self._stop_signal is not None and not terminated:
                print(f"  收到 {signal_title(self._stop_signal)}，先把 Sammy 送走……", flush=True)
                chain = terminate_child(
                    proc,
                    self._stop_signal,
                    grace_s=self.stop_grace_s,
                    kill_grace_s=self.stop_kill_grace_s,
                )
                print(f"  （送走的方式：{' → '.join(chain)}）", flush=True)
                terminated = True
            time.sleep(0.1)
        reader.join(timeout=2.0)
        return RunOutcome(proc.returncode, time.monotonic() - t0, list(tail), None)

    def _sleep_responsive(self, secs: float) -> None:
        """退避等待期间保持对收工信号的灵敏 —— 不要傻睡一整分钟。"""
        end = time.monotonic() + secs
        while self._stop_signal is None:
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.25, left))

    # ── 留痕：崩溃日志 / 状态文件 ────────────────────────────────────

    def _describe(self, result: RunOutcome) -> str:
        if result.error is not None:
            return f"起都起不来：{result.error}"
        rc = result.returncode
        if rc is not None and rc < 0:
            return f"被 {signal_title(-rc)} 带走"
        return f"退出码 {rc}"

    def _write_crash(self, result: RunOutcome, *, rapid: int, delay: float | None) -> Path:
        self.crash_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self._now()))
        existing: list[int] = []
        for f in self.crash_dir.glob(f"crash-{stamp}-*.txt"):
            tail = f.stem.rsplit("-", 1)[-1]
            if tail.isdigit():
                existing.append(int(tail))
        seq = max(existing, default=0) + 1
        path = self.crash_dir / f"crash-{stamp}-{seq:02d}.txt"
        tail = list(result.output)[-self.report_lines :]
        lines = [
            "Sammy 崩溃日志",
            f"时间：{_fmt_ts(self._now())}",
            f"环境：Python {platform.python_version()} · {platform.platform()}",
            f"命令：{' '.join(self.child_argv)}",
            (
                f"结果：{self._describe(result)}"
                f"（这次活了 {result.duration:.1f} 秒 · 连续第 {rapid} 次崩溃）"
            ),
            "",
            f"—— 本次输出最后 {len(tail)} 行（共 {len(result.output)} 行）——",
        ]
        if tail:
            lines.extend(f"  {ln}" for ln in tail)
        else:
            lines.append("  （没有任何输出 —— 崩得比字都快）")
        lines.append("")
        if delay is not None:
            lines.append(f"接下来：{delay:.0f} 秒后自动拉起（看门狗继续盯着）")
        else:
            lines.append("接下来：不再拉起 —— 连续多次迅速崩溃，先看日志再手工启动")
        path.write_text(redact("\n".join(lines) + "\n"), encoding="utf-8")
        return path

    def _prune_crashes(self) -> int:
        files = sorted(self.crash_dir.glob("crash-*.txt"))
        extra = files[: max(0, len(files) - self.keep_crashes)]
        for p in extra:
            with contextlib.suppress(OSError):
                p.unlink()
        return len(extra)

    def _write_status(self, state: str, *, note: str) -> None:
        payload = {
            "state": state,
            "note": note,
            "pid": os.getpid(),
            "child": self.child_argv,
            "started_at": _fmt_ts(self._started_at),
            "started_at_ts": self._started_at,
            "updated_at": _fmt_ts(self._now()),
            "crashes": self._crashes,
            "restarts": self._restarts,
            "last_crash": self._last_crash,
        }
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.status_file.with_name(self.status_file.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.status_file)


# ── 状态查看 ───────────────────────────────────────────────────────────

STATE_WORDS = {
    "running": "在盯着",
    "restarting": "正在重新拉起",
    "exited": "上次正常退出（看门狗也下班了）",
    "stopped": "上次被停掉",
    "gave_up": "上次连续崩溃、已放弃拉起",
}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 进程在，只是不归我们管
    return True


def status_report(*, crash_dir: Path | None = None, status_file: Path | None = None) -> str:
    cd = Path(crash_dir) if crash_dir else paths.data_dir() / "crashes"
    sf = Path(status_file) if status_file else paths.data_dir() / "watchdog.json"
    crashes = sorted(cd.glob("crash-*.txt"))
    out = ["── 看门狗 ──"]
    if not sf.is_file():
        out.append("没跑过：还没有状态文件。要看护：make watchdog")
    else:
        st = None
        try:
            st = json.loads(sf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            out.append(f"状态文件读不出来（{exc}）—— 删掉重跑即可")
        if st is not None:
            state = str(st.get("state", "?"))
            word = STATE_WORDS.get(state, state)
            tail = ""
            if state == "running":
                pid = int(st.get("pid") or 0)
                tail = (
                    f"（pid {pid} 在跑）"
                    if _pid_alive(pid)
                    else f"（⚠️ 说在盯着，但 pid {pid} 已经不在了）"
                )
            line = (
                f"{word}{tail} · 已拉起 {int(st.get('restarts') or 0)} 次"
                f" · 崩过 {int(st.get('crashes') or 0)} 次"
            )
            if state in ("running", "restarting") and st.get("started_at_ts"):
                mins = max(0.0, (time.time() - float(st["started_at_ts"])) / 60.0)
                line += f" · 已看护 {mins:.0f} 分钟"
            out.append(line)
            if st.get("note"):
                out.append(f"  说明：{st['note']}")
            lc = st.get("last_crash") or {}
            if lc.get("file"):
                out.append(f"  最近一次崩溃：{lc.get('at', '?')}（{lc.get('exit', '?')}）")
                out.append(f"    日志：{cd / str(lc['file'])}")
            out.append(f"  状态更新：{st.get('updated_at', '?')}")
    out.append(f"崩溃日志：{len(crashes)} 份（保留最近 {KEEP_CRASHES} 份，在 {cd}/）")
    if crashes:
        out.append(f"  最新一份：{crashes[-1].name}")
    return "\n".join(out)
