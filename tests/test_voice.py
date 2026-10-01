"""语音输出的测试（P1-3）。

三块重点：
1. **清洗要准**：表情符号不能念出来，但正经内容一个字都不能少。
2. **不能阻塞**：念一句话好几秒，界面绝不能被它卡住。
3. **念不出来不能影响对话**：语音是锦上添花，不是命脉。

全部用 NullBackend，不会真的出声 —— 半夜跑测试突然有人说话是很吓人的。
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy.voice import (
    NullBackend,
    Speaker,
    enabled_from_env,
    prepare_speech,
)

# ── 清洗 ─────────────────────────────────────────


def test_emoji_are_not_read_aloud():
    """PRD P1-3 明确要求：不念表情符号。"""
    out = prepare_speech("今天真开心😄🎉")
    assert "😄" not in out and "🎉" not in out
    assert "今天真开心" in out


def test_stage_directions_are_not_read_aloud():
    """（歪头）念出来就是"左括号歪头右括号"。"""
    assert "歪头" not in prepare_speech("（歪头）你回来啦")
    assert "你回来啦" in prepare_speech("（歪头）你回来啦")
    assert "笑" not in prepare_speech("*笑* 你真好")
    assert "你真好" in prepare_speech("*笑* 你真好")


def test_real_content_in_parentheses_is_kept():
    """长括号里多半是正经内容 —— 删掉就是丢信息。

    清洗必须**保守**：宁可多念一个括号，也不能把用户想听的内容悄悄删掉。
    """
    out = prepare_speech("我给你约了（其实是明天下午三点，别记错了）")
    assert "明天下午三点" in out


def test_markdown_is_stripped():
    out = prepare_speech("**重点**是这个")
    assert "*" not in out
    assert "重点" in out and "这个" in out


def test_long_ellipsis_becomes_a_pause():
    out = prepare_speech("我想想……嗯")
    assert "…" not in out
    assert "，" in out


def test_only_punctuation_means_nothing_to_say():
    for junk in ("😄", "。。。", "  ", "", "……"):
        assert prepare_speech(junk) == "", f"{junk!r} 不该被念"


def test_normal_sentence_is_untouched():
    line = "我是 Sammy，住在你桌面上的小家伙。"
    assert prepare_speech(line) == line


def test_cleaning_never_returns_none():
    assert prepare_speech(None) == ""  # type: ignore[arg-type]


# ── 不阻塞 ───────────────────────────────────────


def test_say_returns_immediately():
    """界面不能为了等它念完而卡住 —— 念一句话要好几秒。"""
    slow = NullBackend()
    speaker = Speaker(backend=slow)

    def slow_speak(text):
        time.sleep(1.0)
        slow.spoken.append(text)

    slow.speak = slow_speak  # type: ignore[method-assign]
    t0 = time.time()
    speaker.say("这一句会念一秒")
    elapsed = time.time() - t0
    assert elapsed < 0.3, f"say() 阻塞了 {elapsed:.2f}s —— 界面会卡住"
    speaker.wait(timeout=3)
    assert slow.spoken, "排队的该被念掉"


def test_a_pending_line_is_replaced_by_the_newest():
    """还没开念的那句会被最新的挤掉 —— **念过时的回复比不念更烦**。

    注意语义边界：**正在念的那句不会被打断**（半句话被打断更怪），
    被挤掉的是"排在队里、还没开始念"的那句。
    第一版测试没管这个区别，而假后端是瞬时的，于是它测的是"没有排队"的情形。
    """
    import threading

    class GatedBackend(NullBackend):
        def __init__(self):
            super().__init__()
            self.release = threading.Event()

        def speak(self, text):
            self.release.wait(timeout=3)  # 第一句卡在这儿
            super().speak(text)

    backend = GatedBackend()
    speaker = Speaker(backend=backend)
    speaker.say("第一句")
    time.sleep(0.2)  # 让 worker 把第一句取走（它开始念了）
    speaker.say("第二句")  # 排队中
    speaker.say("第三句")  # 把还在排队的第二句挤掉
    backend.release.set()
    speaker.wait(timeout=3)

    assert "第二句" not in backend.spoken, "还没开念的那句该被最新的挤掉"
    assert "第三句" in backend.spoken


def test_disabled_speaker_says_nothing():
    backend = NullBackend()
    speaker = Speaker(backend=backend, enabled=False)
    assert speaker.say("你听不到这句") == ""
    speaker.wait(timeout=2)
    assert not backend.spoken


def test_nothing_to_say_does_not_start_a_thread():
    backend = NullBackend()
    speaker = Speaker(backend=backend)
    assert speaker.say("😄") == ""
    speaker.wait(timeout=1)
    assert not backend.spoken


# ── 故障不影响对话 ───────────────────────────────


def test_a_broken_backend_does_not_raise():
    """语音是锦上添花，不是命脉 —— 念不出来绝不能让对话崩掉。"""
    backend = NullBackend()

    def boom(text):
        raise RuntimeError("声卡炸了")

    backend.speak = boom  # type: ignore[method-assign]
    speaker = Speaker(backend=backend)
    speaker.say("这句话念不出来了")
    speaker.wait(timeout=3)  # 不该抛异常


def test_say_reports_the_prepared_text():
    """返回清洗后的文本，方便排查"它到底念了什么"。"""
    speaker = Speaker(backend=NullBackend())
    assert speaker.say("你好😄") == "你好"
    assert speaker.last_prepared == "你好"


def test_stop_actually_stops_even_when_the_queue_is_full():
    """队列满时"停止"标记塞不进去 = 停不下来（第一版就有这个毛病）。"""
    speaker = Speaker(backend=NullBackend())
    speaker._q.put_nowait("占位：让队列处于满的状态")
    speaker.stop()
    assert speaker._q.get_nowait() is None, "停止标记该被塞进去（先腾位置再放）"


# ── 开关 ─────────────────────────────────────────


def test_voice_can_be_turned_off_by_env():
    assert enabled_from_env({}) is True
    assert enabled_from_env({"SAMMY_VOICE": "on"}) is True
    for off in ("off", "OFF", "0", "false", "no"):
        assert enabled_from_env({"SAMMY_VOICE": off}) is False, f"{off} 该被当成关闭"
