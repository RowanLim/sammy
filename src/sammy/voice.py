"""Sammy 的声音 —— 输出这一侧（PRD P1-3）。

只做三件事：把要说的话**洗干净**、交给后端念出去、**绝不阻塞界面**。

为什么"洗干净"要单独写一段逻辑：
模型给的回复里会带表情符号和动作描写（"（歪头）"、"*笑*"）。
直接念出来就是"左括号歪头右括号" —— PRD P1-3 明确要求"不念表情符号"。
但清洗必须**保守**：宁可多念一个括号，也不能把用户真正想听的内容悄悄删掉。

为什么必须异步：
念一句话要好几秒。同步念的话，界面在这几秒里完全不能动 —— 那不是陪伴，是卡顿。

后端是可换的：现在是 macOS 自带的 `say`（零依赖、离线）。
将来上树莓派要换成 piper（离线、跨平台）—— 所以这里只依赖一个 `speak()` 接口。
"""

from __future__ import annotations

import contextlib
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .paths import data_dir

# ── 参数 ──────────────────────────────────────────

DEFAULT_VOICE = os.environ.get("SAMMY_VOICE_NAME", "Tingting")
DEFAULT_RATE = 175  # 语速（`say` 默认约 180；陪伴场景稍慢一点更自然）
# edge-tts 的默认音色：晓晓（微软神经网络中文女声，实测最自然的一档）
DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"


def config(key: str, default: str = "") -> str:
    """读一项配置：**进程环境变量优先，其次项目 .env**。

    为什么不能只看 `os.environ`：`.env` 才是项目的配置入口（凭证也在里面），
    而 `models.load_env()` 只把 API key 那几项并进环境变量。
    所以如果这里直接读 `os.environ`，写在 `.env` 里的 `SAMMY_TTS=edge`
    **会被静默忽略** —— "配置写了却不生效"是最难查的一类问题。
    """
    if os.environ.get(key):
        return os.environ[key]
    try:
        from .models import load_env

        return load_env().get(key, default)
    except Exception:  # .env 不在、格式坏了都不该让念不出声
        return default


# ── 清洗规则（保守优先）───────────────────────────

# emoji 与各种符号区段
_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # 各种表情/图形
    "\U0001f000-\U0001f2ff"
    "\u2600-\u27bf"  # 杂项符号
    "\ufe0f\u200d"  # 变体选择符 / 零宽连接
    "\U0001f1e6-\U0001f1ff"  # 区域指示符（国旗）
    "]+"
)

# 动作描写：*笑* / （歪头）/ (小声) —— 只删**短的**、且不含句读的
# 为什么要限制长度和标点：长括号里很可能是正经内容（比如"（其实是 3 月 14 号）"），
# 删掉就是丢信息。宁可多念一个括号。
_ACTION = re.compile(r"(?:\*[^*\n]{1,8}\*|[*]{1,2}(?=\S)[^*\n]{0,6}(?<=\S)[*]{1,2})")
_PAREN_ACTION = re.compile(r"[（(][^（）()，。！？；：,.!?;:]{1,6}[）)]")

# markdown 残留
_MARKDOWN = re.compile(r"(\*\*|__|`|^#{1,6}\s)", re.MULTILINE)


def prepare_speech(text: str) -> str:
    """把回复文本变成"能听懂的话"。**不改变原回复，只用于念出来。**"""
    if not text:
        return ""
    s = str(text)
    s = _MARKDOWN.sub("", s)
    s = _ACTION.sub("", s)
    s = _PAREN_ACTION.sub("", s)
    s = _EMOJI.sub("", s)
    # 省略号、破折号会被念成"点点点"之类，换成停顿更自然
    s = re.sub(r"[…]{2,}", "，", s)
    s = re.sub(r"[—–]{2,}", "，", s)
    s = re.sub(r"\s+", " ", s).strip()
    # 清洗完只剩标点就别念了
    if not re.search(r"[\w\u4e00-\u9fff]", s):
        return ""
    return s


# ── 念多长：陪伴场景"说太久"比"说少一点"更糟 ──────────

DEFAULT_VOICE_MAX = 28  # 念出来的字数上限（实测中文约 5 字/秒 → 28 字 ≈ 5 秒）

# 句末标点（中英）。用它切句，切完**保留标点** ——
# 这样拼回去等于原文的前缀（测试会钉这条，防止"念出来的不是原话"）。
_SENT_END = "。！？；!?;…"
_SENT_SPLIT = re.compile(rf"(?<=[{_SENT_END}])")
_CLAUSE = "，,、 "  # 第一句就超长时，退而求其次在这些地方断


def _cut_at_clause(text: str, limit: int) -> str:
    """在 limit 附近找个从句断点（逗号/顿号/空格），别把词从中间劈开。

    从后往前找**最近的一个**断点；实在没有才硬切到 limit。
    """
    window = text[: limit + 8]
    for i in range(len(window) - 1, 0, -1):
        if window[i] in _CLAUSE:
            return window[: i + 1]
    return text[:limit]


def abridge(text: str, max_chars: int = DEFAULT_VOICE_MAX, max_sentences: int = 1) -> str:
    """念出来的部分：最多 `max_sentences` 句，且总长尽量不超过 `max_chars`。

    为什么要截：实测中文语音约 **5 字/秒** —— 一条 107 字的回复要念 **22 秒**，
    而大脑只想 1.4 秒。**屏幕上有全文，耳朵只需要听到重点。**
    一直念下去不是陪伴，是背景噪音。

    默认"一句 / 28 字"是量出来的：约 3~6 秒，刚够说清楚一句话。
    `max_chars <= 0` 表示不截（念全文）—— 留这个口子是因为"念多长"是口味问题。

    保证：返回值**一定是原文的前缀**（不会改词、不会加词），空输入返回空。
    """
    if not text or max_chars <= 0:
        return text
    parts = [p for p in _SENT_SPLIT.split(text) if p.strip()]
    out = ""
    for i, p in enumerate(parts):
        if i >= max_sentences:
            break
        if i > 0 and len(out) + len(p) > max_chars:
            break
        out += p
        if len(out) >= max_chars:
            break
    if len(out) > max_chars:
        # 连第一句都超长（中间没有句末标点）→ 退到从句处断。
        # ⚠️ 这一步不能省：少了它，长句会被**整句念完**，上限等于没设。
        out = _cut_at_clause(out, max_chars)
    return out.strip()


# ── 后端 ──────────────────────────────────────────


class NullBackend:
    """不出声的后端 —— 测试用，也给"静音模式"用。"""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        """不出声的后端没什么可停的（但接口要在，调用方不用判断）。"""


class _RunningProc:
    """会念一会儿的后端：**记着正在放的那条进程**。

    为什么要记：新的一句来了要能把还在念的那句**掐掉**。
    不然连着发两条，它会把上一条慢慢念完 —— 那时候你已经聊到别处了。
    （队列那一层只能挤掉"还没开始念的"，念到一半的得靠这个。）
    """

    _proc: subprocess.Popen | None = None

    def _run(self, cmd: list[str], timeout: int) -> None:
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:  # 念不出来不该影响对话
            print(f"  ⚠️ 念不出来（{type(e).__name__}: {e}）")
            return
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        except Exception:
            pass
        finally:
            self._proc = None

    def stop(self) -> None:
        p = self._proc
        if p is not None and p.poll() is None:
            with contextlib.suppress(Exception):
                p.terminate()


class MacSayBackend(_RunningProc):
    """macOS 自带的 `say`：零依赖、离线、装了系统就有。"""

    def __init__(self, voice: str = DEFAULT_VOICE, rate: int = DEFAULT_RATE) -> None:
        self.voice = voice
        self.rate = rate

    def speak(self, text: str) -> None:
        self._run(["say", "-v", self.voice, "-r", str(self.rate), text], timeout=60)


def linux_command(text: str, rate: int = DEFAULT_RATE, engine: str = "spd-say") -> list[str]:
    """Linux 上怎么念 —— 纯函数，方便测（不依赖那台机器上有没有装）。

    ⚠️ **别把 macOS 那套参数照抄过来**：
    - `say -r` 收的是"词/分钟"；`spd-say -r` 收的是 -100..100 的相对值，**两回事**。
    - `espeak-ng -s` 收的才是词/分钟。
    参数语义不同还硬套，结果就是语速要么飞快要么慢得听不清。
    """
    if engine == "espeak-ng":
        return ["espeak-ng", "-s", str(rate), "--", text]
    # spd-say：默认语速，等它念完（-w）—— 不 wait 的话进程立刻退出、话被截断
    return ["spd-say", "-w", text]


class LinuxSayBackend(_RunningProc):
    """Linux 上的朗读：优先 `spd-say`（走 speech-dispatcher，音色好），退回 `espeak-ng`。

    实测 Nex（Ubuntu）上 speech-dispatcher 是 active、两个命令都在。
    """

    def __init__(self, rate: int = DEFAULT_RATE) -> None:
        self.rate = rate
        self.engine = "spd-say" if shutil.which("spd-say") else "espeak-ng"

    def speak(self, text: str) -> None:
        self._run(linux_command(text, self.rate, self.engine), timeout=60)


def edge_args(text: str, voice: str = "", rate: str = "") -> dict:
    """edge-tts 的参数（纯函数，方便测）。

    ⚠️ 它的语速参数是**百分比字符串**（`-10%`），既不是 `say` 的词/分钟，
    也不是 `spd-say` 的 -100..100 —— 三家语义各不相同，照抄必错。
    """
    args: dict = {"text": text, "voice": voice or DEFAULT_EDGE_VOICE}
    if rate:
        args["rate"] = rate
    return args


def player_command(path: str) -> list[str]:
    """用什么放音频（按平台挑，纯函数）。"""
    if sys.platform == "darwin":
        return ["afplay", path]
    if shutil.which("paplay"):
        return ["paplay", path]
    if shutil.which("aplay"):
        return ["aplay", "-q", path]
    return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]


class EdgeTTSBackend(_RunningProc):
    """微软 edge-tts 的神经网络中文音色（免费、不需要 key）。

    **为什么需要它**：Rowan 的原话是「这个语音好难听」。查下来 Mac 自带的
    中文嗓音按语言过滤只有一个（Meijia，台湾腔），Tingting 是老引擎 ——
    这不是调参能救的，是引擎差一代。

    **代价必须说清楚**：文本会经过微软的服务器（不能离线）。
    对陪聊场景这不算小事 —— 它说出口的话会经过第三方。
    所以要"最好听"选它，要"全离线"就退回 `say` / `spd-say`。
    """

    def __init__(self, voice: str = "", rate: str = "") -> None:
        self.voice = voice or config("SAMMY_TTS_VOICE", DEFAULT_EDGE_VOICE)
        self.rate = rate or config("SAMMY_TTS_RATE", "")

    def synth(self, text: str) -> Path:
        """合成到项目自己的 data/tts/ 里（不往机器别处写东西）。"""
        import asyncio

        import edge_tts

        out_dir = data_dir() / "tts"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "last.mp3"

        async def run() -> None:
            comm = edge_tts.Communicate(**edge_args(text, self.voice, self.rate))
            with out.open("wb") as f:
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])

        asyncio.run(run())
        return out

    def speak(self, text: str) -> None:
        try:
            path = self.synth(text)
        except Exception as e:
            # 念不出来不该影响对话；但也别装没事 —— 打一行日志比静默强
            print(f"  ⚠️ edge-tts 合成失败（{type(e).__name__}: {e}），这次不念了")
            return
        self._run(player_command(str(path)), timeout=120)


def default_backend():
    """按 `SAMMY_TTS` 挑后端，没设就按平台。

    可选值：`edge`（最好听，需联网）/ `say`（macOS 离线）/ `spd`（Linux 离线）/
    `off`（不念）。**默认不说网络** —— 要不要把说的话送出去，该由用户明确决定。
    """
    engine = (config("SAMMY_TTS") or "").strip().lower()
    if engine in {"off", "none", "null"}:
        return NullBackend()
    if engine == "edge":
        return EdgeTTSBackend()
    if engine == "say":
        return MacSayBackend()
    if engine == "spd":
        return LinuxSayBackend()
    if sys.platform == "darwin":
        return MacSayBackend()
    if sys.platform.startswith("linux"):
        return LinuxSayBackend()
    return NullBackend()


# ── 说话的人 ──────────────────────────────────────


def voice_max_from_env() -> int:
    """`SAMMY_VOICE_MAX`：念出来的字数上限。写 0 就是念全文。

    坏值不该让语音整个坏掉 —— 退回默认值，并且**说明**（静默回退最坑）。
    """
    raw = config("SAMMY_VOICE_MAX", str(DEFAULT_VOICE_MAX)) or str(DEFAULT_VOICE_MAX)
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        print(f"  ⚠️ SAMMY_VOICE_MAX 不是数字（{raw!r}），用默认 {DEFAULT_VOICE_MAX}")
        return DEFAULT_VOICE_MAX


class Speaker:
    """把要念的话排队念掉，**不阻塞调用方**。

    "后说的把还没念的挤掉"：如果你连着发三条，它不该把前两条也慢慢念完 ——
    那时候你已经聊到别处了。**念过时的回复，比不念还烦。**
    念到一半的那句也掐掉（`backend.stop()`）—— 队列只能挤掉还没开口的。
    """

    def __init__(self, backend=None, enabled: bool = True, max_chars: int | None = None):
        # 默认后端按平台挑（macOS: say / Linux: spd-say）—— 见 default_backend
        self.backend = backend if backend is not None else default_backend()
        self.enabled = enabled
        self.max_chars = voice_max_from_env() if max_chars is None else max_chars
        self._q: queue.Queue[str | None] = queue.Queue(maxsize=1)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.last_prepared: str = ""  # 清洗后的全文
        self.last_spoken: str = ""  # 真正念出去的部分（截短后）

    def say(self, text: str) -> str:
        """排一句。立刻返回 —— 界面不该为了等它念完而卡住。

        返回**真正要念的**文本（已清洗、已截短）；没启用就返回空串。
        """
        prepared = prepare_speech(text)
        self.last_prepared = prepared
        if not self.enabled or not prepared:
            return "" if not self.enabled else prepared

        spoken = abridge(prepared, max_chars=self.max_chars)
        self.last_spoken = spoken

        # 新的一句来了：先把还在念的那句掐掉
        with contextlib.suppress(Exception):
            self.backend.stop()

        with self._lock:
            # 挤掉还没念的那句（念过时的回复比不念更烦）
            with contextlib.suppress(queue.Empty):
                self._q.get_nowait()
            with contextlib.suppress(queue.Full):
                self._q.put_nowait(spoken)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        return spoken

    def _run(self) -> None:
        while True:
            try:
                item = self._q.get(timeout=30)
            except queue.Empty:
                return
            if item is None:
                return
            try:
                self.backend.speak(item)
            except Exception as e:
                print(f"  ⚠️ 念不出来（不影响对话）: {e}")

    def wait(self, timeout: float = 5.0) -> None:
        """测试用：等排队的都念完。"""
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def stop(self) -> None:
        """停下来。

        ⚠️ 必须先腾出位置：队列满的时候，"停止"标记根本塞不进去 ——
        那就等于停不下来（第一版就是这个毛病，被 ruff 的风格提示顺手撞出来的）。
        """
        with self._lock:
            with contextlib.suppress(queue.Empty):
                self._q.get_nowait()
            with contextlib.suppress(queue.Full):
                self._q.put_nowait(None)


def enabled_from_env(env: dict | None = None) -> bool:
    """`SAMMY_VOICE=off` 可以彻底静音（默认开）。"""
    raw = (env or {}).get("SAMMY_VOICE") if env is not None else config("SAMMY_VOICE", "on")
    return str(raw or "on").strip().lower() not in {"off", "0", "false", "no"}


__all__ = [
    "DEFAULT_EDGE_VOICE",
    "DEFAULT_RATE",
    "DEFAULT_VOICE",
    "DEFAULT_VOICE_MAX",
    "EdgeTTSBackend",
    "LinuxSayBackend",
    "MacSayBackend",
    "NullBackend",
    "Speaker",
    "abridge",
    "config",
    "default_backend",
    "edge_args",
    "enabled_from_env",
    "linux_command",
    "player_command",
    "prepare_speech",
    "voice_max_from_env",
]
