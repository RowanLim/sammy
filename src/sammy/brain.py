"""Sammy 的大脑 —— 独立大脑，不依赖 Hermes。

设计要点：
- 独立跑豆包（火山引擎）OpenAI 兼容接口，.env 读凭证
- 一次调用同时产出「回复文本」和「情绪标签」，让表情跟得上对话
- 只用标准库 urllib，不引额外依赖
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from .expressions import EMOTION_KEYS, expression_for
from .models import ENV_FILE, ModelConfig
from .models import load_env as _load_env  # 测试与脚本用的名字，保持兼容
from .tools import call as call_tool
from .tools import schemas as tool_schemas

__all__ = ["SYSTEM_PROMPT", "SammyBrain", "_load_env"]


SYSTEM_PROMPT = """你是 Sammy，一只住在 Rowan 桌面上的小家伙。你不是一个通用的语音助手，你是他的伙伴。

你的性格：活泼、好奇、有点小得意。真诚但不谄媚 —— 你不会什么都夸，你觉得不对会直说。
你的说话方式：像朋友随口说话，默认 1-3 句，绝不长篇大论。不用「亲爱的」，不过度卖萌。
你的能力：你能给建议、能帮他理清问题、能陪他说话。遇到他问的事你答不上来，坦白说不知道，别编。

**输出格式（必须严格遵守，不要有多余文字）：**
第一行：只写一个情绪词，从下面列表里选最贴近你此刻心情的一个：
{emotions}
第二行开始：你真正要说的内容。

示例：
happy
今天这天气真好，出去遛两步？"""


# 模型可能自创的英文情绪词 → 最接近的合法情绪。
# 不指望穷举，只兜住实测出现过的和常见近义，剩下的走前缀匹配。
EMOTION_SYNONYMS: dict[str, str] = {
    "sympathetic": "wronged",
    "empathetic": "wronged",
    "concerned": "wronged",
    "worried": "wronged",
    "caring": "love",
    "affectionate": "love",
    "warm": "smile",
    "tender": "smile",
    "gentle": "smile",
    "friendly": "smile",
    "cheerful": "happy",
    "joyful": "happy",
    "excited": "happy",
    "glad": "happy",
    "amused": "giggle",
    "teasing": "wink",
    "mischievous": "playful",
    "thoughtful": "thinking",
    "confused": "curious",
    "puzzled": "curious",
    "curious": "curious",
    "hopeful": "expect",
    "eager": "expect",
    "calm": "normal",
    "neutral": "normal",
    "serious": "normal",
    "tired": "sleepy",
    "exhausted": "sleepy",
    "bored": "bored",
    "surprised": "surprised",
    "astonished": "shocked",
    "amazed": "shocked",
    "disappointed": "sad",
    "upset": "sad",
    "sorry": "sad",
    "annoyed": "angry",
    "frustrated": "angry",
    "awkward": "awkward",
    "embarrassed": "awkward",
    "proud": "proud",
    "smug": "proud",
    "confident": "cool",
    "chill": "cool",
    "quiet": "speechless",
    "silent": "speechless",
    "speechless": "speechless",
    "content": "content",
    "satisfied": "content",
    "happy": "happy",
    "cute": "cute",
    "shy": "cute",
    "pleading": "wronged",
}


def _canon_emotion(candidate: str) -> str | None:
    """把模型给的情绪词收敛到合法集合；认不出来返回 None（说明这行不是情绪标签）。"""
    word = (candidate or "").strip().strip("`*_-· \t\"'").lower()
    if not word or " " in word.strip():
        return None
    if word in EMOTION_KEYS:
        return word
    if word in EMOTION_SYNONYMS:
        return EMOTION_SYNONYMS[word]
    # 前缀 / 包含匹配，兜住 sympathetic-ish 这类变形
    for key in EMOTION_KEYS:
        if word.startswith(key[:4]) or key in word:
            return key
    # 纯 ASCII 短词 → 它确实想给个情绪，只是词不在表里，归到「普通」
    # 注意：必须限定 isascii()，否则 "我在这儿呢".isalpha() 也是 True（CJK 算字母），
    # 中文正文会被误当情绪标签吃掉。
    if word.isascii() and word.isalpha() and len(word) <= 20:
        return "normal"
    return None


class SammyBrain:
    """独立大脑：一次调用拿到 回复 + 情绪。"""

    def __init__(
        self,
        config: ModelConfig | None = None,
        timeout: int = 60,
        history_turns: int = 6,
        thinking: str | None = None,
        use_tools: bool = True,
    ):
        """不传 config 就用 CHAT 档（聊天要快）。要调工具时用 `SammyBrain.for_agent()`。"""
        self.config = config or ModelConfig.from_env("CHAT")
        self.tier = self.config.tier
        self.api_key = self.config.api_key
        self.base_url = self.config.base_url.rstrip("/")
        self.model = self.config.model
        self.timeout = timeout
        self.history_turns = history_turns
        # 有些模型默认「先想再答」，一次对话多花 3-5 秒。桌面陪伴要快，默认关掉；
        # 需要它认真想的时候把 SAMMY_THINKING 设成 on 开回来。
        self.thinking = thinking if thinking is not None else self.config.thinking
        # 联网思考：允许它调工具（搜网、抓网页、看时间）
        self.use_tools = use_tools
        self.history: list[dict[str, str]] = []
        if not self.api_key:
            raise RuntimeError(
                f"{self.tier} 档没配凭证 —— 在 {ENV_FILE} 里填 SAMMY_{self.tier}_API_KEY，"
                f"或设置同名环境变量。用 `./run.sh --models` 看各档位状态。"
            )

    @property
    def _thinking_payload(self) -> dict:
        """「关掉思考链」这个开关是**供应商特有的**，不能无脑发。

        踩过的坑：`thinking={"type":"disabled"}` 是火山引擎（豆包）的参数，
        DeepSeek / OpenAI 没这个字段，照发可能直接 400。
        所以按 base_url 自动判断，也允许用 SAMMY_THINKING_PARAM 显式覆盖
        （none = 什么都不发，ark = 发火山那套）。
        """
        if self.thinking != "off":
            return {}
        mode = _load_env().get("SAMMY_THINKING_PARAM", "").strip().lower()
        if mode == "none":
            return {}
        if mode == "ark" or "volces.com" in self.base_url:
            return {"thinking": {"type": "disabled"}}
        return {}

    @classmethod
    def for_agent(cls, **kwargs) -> SammyBrain:
        """代理档：调工具 / 多步推理 / 记忆整理用这个。"""
        return cls(config=ModelConfig.from_env("AGENT"), **kwargs)

    # ── 对外主入口 ──────────────────────────────────

    def chat(
        self,
        user_text: str,
        memory_context: str = "",
        on_event: Callable[[str], None] | None = None,
    ) -> dict:
        """返回 {'reply', 'emotion', 'expression', 'latency', 'tools_used'}

        memory_context: 由 Memory.context_block() 生成的记忆片段，塞进 system prompt。
        on_event: 每次决定调工具时回调一次工具名 —— 界面拿它显示"正在联网…"，
                  用户才知道它为什么慢了几秒。
        """
        started = time.time()
        raw, used = self._call(user_text, memory_context, on_event)
        latency = time.time() - started
        emotion, reply = self._parse(raw)

        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        if len(self.history) > self.history_turns * 2:
            self.history = self.history[-self.history_turns * 2 :]

        return {
            "reply": reply,
            "emotion": emotion,
            "expression": expression_for(emotion),
            "latency": latency,
            "tools_used": used,
        }

    # ── 内部 ────────────────────────────────────────

    def _call(
        self,
        user_text: str,
        memory_context: str = "",
        on_event: Callable[[str], None] | None = None,
    ) -> tuple[str, list[str]]:
        system = SYSTEM_PROMPT.format(emotions=" | ".join(EMOTION_KEYS))
        if memory_context:
            system += "\n\n以下是你记得的事，自然地用，别生硬地复述：\n" + memory_context
        messages = [{"role": "system", "content": system}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_text})

        if not self.use_tools:
            return self._post(messages, temperature=0.8), []
        return self._run_tools(messages, on_event)

    def _run_tools(
        self,
        messages: list[dict],
        on_event: Callable[[str], None] | None = None,
        max_rounds: int = 4,
    ) -> tuple[str, list[str]]:
        """联网思考的循环：模型要工具就给工具，最多来回 max_rounds 次。

        为什么要有上限：模型可能陷进"搜一次、再搜一次"的循环里，用户会一直等。
        轮数用尽就逼它给一个不带工具的答案 —— 宁可答得糙，不能把用户干等在那。
        """
        used: list[str] = []
        for _ in range(max_rounds):
            msg = self._post_message(messages, tools=tool_schemas())
            calls = msg.get("tool_calls") or []
            if not calls:
                return (msg.get("content") or ""), used

            messages.append(msg)  # assistant 的 tool_calls 必须原样回灌
            for c in calls:
                fn = c.get("function") or {}
                name = fn.get("name") or "?"
                used.append(name)
                if on_event:
                    on_event(name)
                result = call_tool(name, fn.get("arguments") or "{}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": c.get("id") or "",
                        "content": result,
                    }
                )

        final = self._post_message(messages)
        return (final.get("content") or ""), used

    def _post(self, messages: list[dict], temperature: float = 0.8) -> str:
        """只要文本的场景（记忆整理等）用这个。"""
        return self._post_message(messages, temperature=temperature).get("content") or ""

    def _post_message(
        self,
        messages: list[dict],
        temperature: float = 0.8,
        tools: list[dict] | None = None,
    ) -> dict:
        """统一的 HTTP 出口 —— 对话 / 记忆整理 / 工具循环共用。

        返回 message 对象（而不是只返回 content），因为工具循环需要拿到 tool_calls。
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        payload.update(self._thinking_payload)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            raise RuntimeError(f"大模型返回 HTTP {e.code}: {detail}") from e
        except Exception as e:
            raise RuntimeError(f"连不上大模型: {type(e).__name__}: {e}") from e

        msg = body["choices"][0].get("message") or {}
        return msg if isinstance(msg, dict) else {}

    # ── 记忆：抽取与夜里整理 ────────────────────────
    # 都走独立调用，**不插在对话延迟里**。抽取由后台线程跑。

    def extract_memories(self, user_text: str, reply: str, known_slots: dict[str, str]) -> dict:
        """从一轮对话里抽长期记忆 → {'slots': {...}, 'journal': [...]}"""
        from .memory import EXTRACT_PROMPT, parse_extraction

        desc = "\n".join(f"- {k}：{v}" for k, v in known_slots.items()) or "（暂无）"
        prompt = EXTRACT_PROMPT.format(slots=desc, user=user_text, reply=reply)
        try:
            raw = self._post([{"role": "user", "content": prompt}], temperature=0.2)
        except Exception as e:
            print(f"  ⚠️ 记忆抽取失败: {e}")
            return {"slots": {}, "journal": []}
        return parse_extraction(raw)

    def consolidate(self, day: str, entries: list[str], known_slots: dict[str, str]) -> dict:
        """夜里整理：把一天的事件压成摘要，顺带更新槽位。"""
        from .memory import CONSOLIDATE_PROMPT

        if not entries:
            return {"digest": "", "slots": {}}
        desc = "\n".join(f"- {k}：{v}" for k, v in known_slots.items()) or "（暂无）"
        prompt = CONSOLIDATE_PROMPT.format(
            day=day,
            slots=desc,
            entries="\n".join(f"- {e}" for e in entries),
        )
        try:
            raw = self._post([{"role": "user", "content": prompt}], temperature=0.3)
        except Exception as e:
            print(f"  ⚠️ 夜里整理失败: {e}")
            return {"digest": "", "slots": {}}

        from .memory import parse_digest

        return parse_digest(raw)

    @staticmethod
    def _parse(raw: str) -> tuple[str, str]:
        """解析「情绪 + 回复」。

        实测模型偶尔会自己发明情绪词（比如返回 sympathetic 而不是列表里的词），
        所以这里不能只看「是否严格命中」，得先认出「这是个情绪标签」，
        再尽力映射到最近的合法情绪 —— 否则标签会被当成正文念给用户听。
        """
        text = (raw or "").strip()
        if not text:
            return "normal", "……"

        lines = text.splitlines()
        first = lines[0].strip().strip("`*_-· \t")
        # 形如 "happy: 内容" / "happy|内容"
        head, sep, tail = first.partition("：")
        if not sep:
            head, sep, tail = first.partition(":")
        if sep and tail.strip():
            candidate, rest = head.strip(), tail.strip()
        else:
            candidate, rest = first, "\n".join(lines[1:]).strip()

        key = _canon_emotion(candidate)
        if key is None:
            # 第一行不是情绪标签：整段都是正文，兜底普通表情
            return "normal", text

        reply = rest.strip()
        if not reply:
            reply = "\n".join(lines[2:]).strip() if len(lines) > 1 else ""
        return key, (reply or "……")


__all__ = ["SYSTEM_PROMPT", "SammyBrain"]
