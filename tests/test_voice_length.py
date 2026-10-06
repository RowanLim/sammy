"""念多长、什么时候闭嘴 —— 语音"体验"这一侧的判据。

为什么值得单独测：截短和打断属于**体验**，错了不会报错 ——
只会让人觉得"它话说一半"或者"它念个没完"。
所以钉死两条硬规矩：
1. **念出来的必须是原话的前缀**（不改词、不加词、不断在词中间混着改）；
2. **新的一句来了，正在念的那句要被掐掉**（队列只能挤掉还没开口的）。
"""

from __future__ import annotations

import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import voice

LONG = (
    "我趴在你桌面边上看着你呢。刚才那事儿我想了想 —— 你要是拿不准，"
    "就先做那个最简单的版本，做完给我看，我帮你挑毛病。"
    "别一上来就想把什么都做全，那样最容易卡住。"
)


def test_short_reply_is_spoken_whole():
    assert voice.abridge("嗯，我在。") == "嗯，我在。"


def test_long_reply_is_cut_to_one_sentence():
    got = voice.abridge(LONG)
    assert len(got) < len(LONG), "这么长必须截"
    assert got.endswith("。"), "要在句末断"
    assert got.count("。") == 1, "默认只念一句（陪伴场景不念长篇）"


def test_default_stays_short_enough_to_say_quickly():
    """默认上限是**量出来的**（中文约 5 字/秒）：一句 ≈ 5 秒。

    这条钉的是"别哪天悄悄变回念全文"：全文 107 字要念 22 秒。
    """
    got = voice.abridge(LONG)
    assert len(got) <= voice.DEFAULT_VOICE_MAX + 8, f"念太长了：{len(got)} 字"


def test_abridged_is_always_a_prefix_of_the_original():
    """这是核心不变量：**念的必须是原话的开头**，不能改词、不能重新组织。"""
    for text in (LONG, "短。", "一句超长没有标点的" * 30, "有，逗号，也有。句末！还有？问号"):
        got = voice.abridge(text)
        assert text.startswith(got), f"念出来的不是原文前缀：{got!r}"


def test_single_long_sentence_breaks_at_a_clause():
    """一句话超过上限时，在逗号/顿号处断，别从词中间劈开。"""
    text = "第一段说完了，第二段还没说完不过这一句特别特别长一直不停地写下去看看它到底会断在哪里"
    got = voice.abridge(text, max_chars=20)
    assert got == text[: len(got)]
    assert got.endswith(("，", "、")) or len(got) <= 20


def test_zero_means_speak_everything():
    """`SAMMY_VOICE_MAX=0` = 念全文（"念多长"是口味问题，得留口子）。"""
    assert voice.abridge(LONG, max_chars=0) == LONG


def test_empty_stays_empty():
    assert voice.abridge("") == ""


def test_speaker_speaks_only_the_abridged_part():
    backend = voice.NullBackend()
    sp = voice.Speaker(backend=backend, max_chars=40)
    spoken = sp.say(LONG)
    sp.wait(timeout=2)
    assert len(spoken) < len(LONG)
    assert sp.last_prepared == voice.prepare_speech(LONG), "清洗后的全文要留下（排查用）"
    assert sp.last_spoken == spoken
    assert backend.spoken and backend.spoken[0] == spoken, "念出去的必须是截短后的那句"


def test_new_line_cuts_off_what_is_playing():
    """念到一半的那句要被掐掉 —— 不然连着发两条，上一条会慢慢念完。"""

    class SlowBackend:
        def __init__(self):
            self.stop_calls = 0
            self.playing = threading.Event()
            self.release = threading.Event()

        def speak(self, text: str) -> None:
            self.playing.set()
            self.release.wait(timeout=5)

        def stop(self) -> None:
            self.stop_calls += 1
            self.release.set()

    backend = SlowBackend()
    sp = voice.Speaker(backend=backend, max_chars=40)
    sp.say("第一句先念着，念很久很久很久很久很久")
    assert backend.playing.wait(timeout=2), "第一句没开始念"
    sp.say("第二句来了")
    time.sleep(0.2)
    assert backend.stop_calls >= 1, "新的一句来了，正在念的那句没被掐掉"


def test_bad_voice_max_falls_back_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(voice, "config", lambda key, default="": "abc")
    got = voice.voice_max_from_env()
    assert got == voice.DEFAULT_VOICE_MAX, "坏值要退回默认，不能让语音整个坏掉"
    assert "SAMMY_VOICE_MAX" in capsys.readouterr().out, "回退了要说明（静默回退最坑）"


def test_voice_max_reads_the_env(monkeypatch):
    monkeypatch.setattr(voice, "config", lambda key, default="": "120")
    assert voice.voice_max_from_env() == 120
