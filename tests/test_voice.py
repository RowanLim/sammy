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
    edge_args,
    enabled_from_env,
    linux_command,
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


def test_linux_uses_spd_say_and_waits():
    """spd-say 必须带 -w：不等它念完，进程立刻退出、话会被截断。"""
    cmd = linux_command("你好")
    assert cmd[0] == "spd-say"
    assert "-w" in cmd
    assert cmd[-1] == "你好"


def test_linux_espeak_rate_is_words_per_minute():
    """两家的语速参数**语义不同** —— 照抄会念成外星语速度。

    `say -r` / `espeak-ng -s` 收的是词/分钟；`spd-say -r` 收的是 -100..100 的相对值。
    """
    cmd = linux_command("你好", rate=175, engine="espeak-ng")
    assert cmd[0] == "espeak-ng"
    assert cmd[cmd.index("-s") + 1] == "175"


def test_linux_backend_falls_back_to_espeak(monkeypatch):
    """没装 speech-dispatcher 的机器上要能退回 espeak-ng，而不是直接哑掉。"""
    from sammy import voice

    monkeypatch.setattr(voice.shutil, "which", lambda name: None)
    assert voice.LinuxSayBackend().engine == "espeak-ng"


def test_default_backend_matches_the_platform(monkeypatch):
    """上层不该知道自己在哪台机器上 —— 由这里按平台挑。

    ⚠️ 必须把 `config` 屏蔽掉：它现在会读项目 `.env`，而 .env 里**已经**写了
    `SAMMY_TTS=edge`（Rowan 定的音色）。不屏蔽的话测的就不是"平台默认"了 ——
    这类"测试被真实配置污染"的坑，和测试写死时间一样隐蔽。
    """
    from sammy import voice

    monkeypatch.setattr(voice, "config", lambda k, d="": d)  # 假装 .env 里什么都没有

    monkeypatch.setattr(voice.sys, "platform", "darwin")
    assert isinstance(voice.default_backend(), voice.MacSayBackend)

    monkeypatch.setattr(voice.sys, "platform", "linux")
    monkeypatch.setattr(voice.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert isinstance(voice.default_backend(), voice.LinuxSayBackend)

    monkeypatch.setattr(voice.sys, "platform", "win32")
    assert isinstance(voice.default_backend(), voice.NullBackend)


# ── edge-tts（神经网络音色）──────────────────────


def test_edge_args_use_a_percent_rate():
    """edge-tts 的语速是**百分比字符串**。

    三家语义完全不同：`say -r` / `espeak-ng -s` 是词/分钟，`spd-say -r` 是 -100..100，
    edge 是 `-10%`。照抄必错，所以这里钉死。
    """
    a = edge_args("你好", "zh-CN-XiaoxiaoNeural", "-10%")
    assert a == {"text": "你好", "voice": "zh-CN-XiaoxiaoNeural", "rate": "-10%"}
    assert "rate" not in edge_args("你好")  # 没指定就别传


def test_edge_defaults_to_a_chinese_voice():
    from sammy import voice

    assert "zh-CN" in voice.edge_args("你好")["voice"]


def test_player_command_matches_platform(monkeypatch):
    from sammy import voice

    monkeypatch.setattr(voice.sys, "platform", "darwin")
    assert voice.player_command("/x.mp3")[0] == "afplay"

    monkeypatch.setattr(voice.sys, "platform", "linux")
    monkeypatch.setattr(voice.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert voice.player_command("/x.mp3")[0] == "paplay"

    monkeypatch.setattr(voice.shutil, "which", lambda n: None)
    assert voice.player_command("/x.mp3")[0] == "ffplay"


def test_backend_can_be_chosen_by_env(monkeypatch):
    from sammy import voice

    monkeypatch.setenv("SAMMY_TTS", "edge")
    assert isinstance(voice.default_backend(), voice.EdgeTTSBackend)
    monkeypatch.setenv("SAMMY_TTS", "spd")
    assert isinstance(voice.default_backend(), voice.LinuxSayBackend)
    monkeypatch.setenv("SAMMY_TTS", "off")
    assert isinstance(voice.default_backend(), voice.NullBackend)


def test_default_stays_offline(monkeypatch):
    """没明确要求时**不该**把人说的话送上网络 —— 这事该由用户决定，不该默认。"""
    from sammy import voice

    monkeypatch.setattr(voice, "config", lambda k, d="": d)  # 屏蔽 .env
    monkeypatch.setattr(voice.sys, "platform", "darwin")
    assert isinstance(voice.default_backend(), voice.MacSayBackend)


def test_edge_speak_does_not_raise_on_network_failure(monkeypatch):
    """念不出来不该把对话带崩 —— 但也别装没事（会打一行日志）。"""
    from sammy import voice

    b = voice.EdgeTTSBackend(voice="zh-CN-XiaoxiaoNeural")
    monkeypatch.setattr(b, "synth", lambda text: (_ for _ in ()).throw(OSError("断网了")))
    b.speak("你好")  # 不抛异常就算过


def test_config_reads_env_first_then_dotenv(monkeypatch):
    """`.env` 里写了却读不到 = **配置静默失效**（踩过一次）。

    `.env` 是项目的配置入口，但 `models.load_env()` 只把 API key 那几项并进
    `os.environ`。所以读配置必须走 `config()`，不能直接读 `os.environ`。
    """
    from sammy import models, voice

    monkeypatch.delenv("SAMMY_TTS", raising=False)
    monkeypatch.setattr(models, "load_env", lambda: {"SAMMY_TTS": "edge"})
    assert voice.config("SAMMY_TTS") == "edge"

    monkeypatch.setenv("SAMMY_TTS", "spd")
    assert voice.config("SAMMY_TTS") == "spd"  # 进程环境变量优先（方便临时覆盖）

    assert voice.config("没有这个键", "兜底") == "兜底"


# ── 开关 ─────────────────────────────────────────


def test_voice_can_be_turned_off_by_env():
    assert enabled_from_env({}) is True
    assert enabled_from_env({"SAMMY_VOICE": "on"}) is True
    for off in ("off", "OFF", "0", "false", "no"):
        assert enabled_from_env({"SAMMY_VOICE": off}) is False, f"{off} 该被当成关闭"
