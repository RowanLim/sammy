"""唤醒词 —— 不需要模型的那些规矩。

真模型的检测在 `test_wake_live.py`（要先跑 `scripts/fetch_models.sh`）。
这里钉的是**今晚踩出来的坑**：关键词表的格式陷阱、输入源替换、前置静音。
"""

from __future__ import annotations

import pathlib
import sys
import wave

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import audio, wake
from sammy.wake import WakeWord, default_models, keyword_lines

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── 关键词表的两个格式陷阱（都报同一个看不懂的错）──────────


def test_comment_line_in_keywords_is_rejected(tmp_path):
    """`#` 在这套格式里是**阈值标记**，不是注释符。

    写了注释，它会被当关键词解析，然后拿里面的英文去转数字，报
    `ValueError: stof: no conversion` —— 和真正原因毫无关系。
    我第一次就卡在这，还白查了一轮"显示名里的空格"。
    """
    f = tmp_path / "kw.txt"
    f.write_text("# 这是注释\nh āi s à m ǐ @嗨萨米\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不能写注释"):
        keyword_lines(f)


def test_space_in_display_name_is_rejected(tmp_path):
    """`@嗨 Sammy` 会被空格拆成两个字段，同样报 `stof: no conversion`。"""
    f = tmp_path / "kw.txt"
    f.write_text("h āi s à m ǐ @嗨 Sammy\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不能有空格"):
        keyword_lines(f)


def test_empty_keywords_is_rejected(tmp_path):
    f = tmp_path / "kw.txt"
    f.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="一条关键词都没有"):
        keyword_lines(f)


def test_shipped_keyword_files_are_clean():
    """仓库里那两份真表必须是干净的 —— 模型只有加载时才报错，
    等到那时候人已经坐在屏幕前等着喊它了。"""
    for m in default_models():
        lines = keyword_lines(m.keywords_file)
        assert lines, f"{m.keywords_file} 是空的"
        for line in lines:
            assert not line.startswith("#")
            if "@" in line:  # 英文模型的表没有 @ 显示名
                assert " " not in line.split("@", 1)[1]


def test_zh_keywords_use_chinese_syllables_not_english():
    """中文模型发不出英文词「Sammy」—— 实测 `s a m m y` 完全不触发。

    必须写成中文音节「萨米」(sà mǐ)。这条防的是"顺手把英文拼写挪过来"。
    """
    zh = next(m for m in default_models() if m.name == "zh")
    text = zh.keywords_file.read_text(encoding="utf-8")
    assert "s à m ǐ" in text, "中文唤醒词该按「萨米」的拼音写"
    assert "s a m m y" not in text, "别把英文拼写放进中文模型的关键词表（不触发）"


def test_en_keywords_use_the_right_bpe_pieces():
    """英文模型要按 BPE 片段切：`▁SA M M Y` 对，`▁S A M M Y` 不触发。

    （`▁` = BPE 的词首标记；tokens.txt 里有 `▁SA`，没有 `SAM`/`MY`。）
    """
    en = next(m for m in default_models() if m.name == "en")
    text = en.keywords_file.read_text(encoding="utf-8")
    assert "▁SA M M Y" in text
    assert "▁S A M M Y" not in text, "逐字母的写法实测不触发"


# ── 前置静音：流式模型要"前文" ─────────────────────────


def test_pad_for_context_pads_both_ends():
    """两头都要补：
    - 前面给流式编码器收敛（裸音频实测不命中）
    - 后面给解码器收尾（`num_trailing_blanks=1`，短词只补前面不命中）
    """
    s = np.ones(16000, dtype=np.float32)
    p = audio.pad_for_context(s, lead_ms=500, tail_ms=600)
    assert len(p) == 16000 + 8000 + 9600
    assert np.allclose(p[:8000], 0.0)
    assert np.allclose(p[8000:24000], 1.0)
    assert np.allclose(p[24000:], 0.0)


def test_pad_for_context_can_be_disabled():
    s = np.ones(10, dtype=np.float32)
    assert len(audio.pad_for_context(s, lead_ms=0, tail_ms=0)) == 10


def test_wav_source_pads_by_default(tmp_path):
    """文件回放必须两头补静音，否则**假阴性**（实测短词不加尾巴测不出来）。"""
    p = tmp_path / "t.wav"
    _write_wav(p, np.ones(16000, dtype=np.float32))
    frames = list(audio.WavSource(p, chunk_ms=100).frames())
    total = sum(len(f) for f in frames)
    assert total == 16000 + int(16000 * 0.8) + int(16000 * 0.6), "该补 800ms 前 + 600ms 后"


def test_wav_source_chunks_are_contiguous(tmp_path):
    p = tmp_path / "t.wav"
    data = np.arange(16000, dtype=np.float32) / 32768
    _write_wav(p, data)
    got = np.concatenate(list(audio.WavSource(p, chunk_ms=100, lead_ms=0, tail_ms=0).frames()))
    assert len(got) == 16000
    assert np.allclose(got.astype(np.float32), data, atol=1e-4)


def test_wav_source_can_loop(tmp_path):
    """模拟"一直在听"：同一段反复喂。"""
    p = tmp_path / "t.wav"
    _write_wav(p, np.ones(8000, dtype=np.float32))
    frames = list(audio.WavSource(p, chunk_ms=100, lead_ms=0, tail_ms=0, loops=3).frames())
    assert sum(len(f) for f in frames) == 8000 * 3


# ── 读文件的严格性：宁可在门口响亮地失败 ──────────────


def test_read_wav_rejects_wrong_sample_rate(tmp_path):
    p = tmp_path / "48k.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x00" * 4800)
    with pytest.raises(ValueError, match="得是 16000Hz 单声道"):
        audio.read_wav(p)


def test_read_wav_rejects_stereo(tmp_path):
    p = tmp_path / "st.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)
    with pytest.raises(ValueError, match="单声道"):
        audio.read_wav(p)


# ── 去掉开头的唤醒词 ──────────────────────────────


def test_strip_wake_removes_the_leading_wake_word():
    from sammy.wake import strip_wake

    assert strip_wake("嗨萨米，你在干嘛") == "你在干嘛"
    assert strip_wake("嗨萨米 今天天气怎么样") == "今天天气怎么样"


def test_strip_wake_tolerates_punctuation_and_spaces():
    """识别结果常夹标点 —— 不处理的话唤醒词会被当正文丢给大脑。"""
    from sammy.wake import strip_wake

    assert strip_wake("嗨，萨米，你在干嘛") == "你在干嘛"
    assert strip_wake("萨米！帮我看看几点") == "帮我看看几点"


def test_strip_wake_handles_english_case_insensitively():
    from sammy.wake import strip_wake

    assert strip_wake("Hi Sammy, what time is it") == "what time is it"


def test_strip_wake_leaves_plain_speech_alone():
    """没有唤醒词就别乱切 —— 切错了等于把用户的话吃掉一半。"""
    from sammy.wake import strip_wake

    assert strip_wake("今天天气不错") == "今天天气不错"
    assert strip_wake("萨琪玛很好吃") == "萨琪玛很好吃"  # 近似但不同，别误切
    assert strip_wake("") == ""


def test_strip_wake_does_not_eat_a_word_that_merely_starts_the_same():
    """「萨米」开头也算，但「萨琪玛」不能当成「萨米」+「琪玛」。"""
    from sammy.wake import strip_wake

    assert strip_wake("萨米特价") == "特价"  # 确实以「萨米」开头 → 该切
    assert strip_wake("萨琪玛很好吃") == "萨琪玛很好吃"  # 不是 → 不切


# ── 模型缺失不该整体崩 ───────────────────────────────


def test_missing_models_are_skipped_not_fatal():
    """只有中文模型也要能唤醒 —— 少一种说法好过完全不能唤醒。"""
    fake = [
        wake.WakeModel(
            "zh", "假中文", pathlib.Path("/nope/zh"), pathlib.Path("/nope/kw.txt"), ("嗨萨米",)
        ),
        wake.WakeModel(
            "en", "假英文", pathlib.Path("/nope/en"), pathlib.Path("/nope/kw.txt"), ("SAMMY",)
        ),
    ]
    w = WakeWord(models=fake)
    assert w.ready is False
    w.load()
    assert w.skipped == fake
    assert "✗" in w.describe()
    with pytest.raises(RuntimeError, match="fetch_models"):
        w.session()


def test_describe_shows_which_models_are_ready():
    w = WakeWord(models=default_models())
    w.load()
    d = w.describe()
    assert "嗨萨米" in d and "Hi Sammy" in d


# ── 输入源 ──────────────────────────────────────────


def test_list_input_devices_never_raises():
    """没有麦克风是**正常状态**，不是错误 —— 上层靠这个列表决定走哪条路。"""
    assert isinstance(audio.list_input_devices(), list)


def test_mic_source_explains_what_to_do_without_a_device():
    """没设备 / 没装库都要**说清楚下一步怎么办**，别让人对着沉默猜。"""
    if audio.list_input_devices():
        pytest.skip("这台机器有输入设备，测不到『没设备』那条分支")
    with pytest.raises(RuntimeError, match=r"sounddevice|USB 麦克风|voice-demo"):
        audio.MicSource()


def _write_wav(path: pathlib.Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
