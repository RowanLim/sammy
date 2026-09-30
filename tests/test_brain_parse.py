"""情绪解析 —— 这里每个用例都对应一次真实踩过的坑。"""

import pytest

from sammy.brain import SammyBrain, _canon_emotion
from sammy.expressions import EMOTION_KEYS


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("happy\n今天天气真好", ("happy", "今天天气真好")),
        # 实测模型自创过这个词（不在允许列表里），不能把标签当正文念给用户
        ("sympathetic\n那就别硬扛了", ("wronged", "那就别硬扛了")),
        ("thinking: 让我想想", ("thinking", "让我想想")),
        ("smile：好呀", ("smile", "好呀")),
        ("**giggle**\n嘿嘿", ("giggle", "嘿嘿")),
        # 不给标签时，整段都是正文
        ("我在这儿呢", ("normal", "我在这儿呢")),
        ("", ("normal", "……")),
    ],
)
def test_parse_emotion_and_reply(raw, expected):
    assert SammyBrain._parse(raw) == expected


def test_emotion_keys_are_parsable():
    """允许列表里每个词都必须能被解析器认出来（否则提示词在骗模型）。"""
    for key in EMOTION_KEYS:
        assert _canon_emotion(key) == key


@pytest.mark.parametrize(
    "word,expected",
    [
        ("confused", "curious"),
        ("exhausted", "sleepy"),
        ("cheerful", "happy"),
        ("Sympathetic", "wronged"),  # 大小写不敏感
    ],
)
def test_synonyms_collapse(word, expected):
    assert _canon_emotion(word) == expected


def test_cjk_line_is_not_an_emotion_label():
    """踩过的坑：Python 里 '我在这儿呢'.isalpha() 是 True（CJK 算字母），
    不加 isascii() 的话整句中文会被当成情绪标签吃掉。"""
    assert _canon_emotion("我在这儿呢") is None
    assert _canon_emotion("我在这儿呢！") is None


def test_long_sentence_is_not_a_label():
    assert _canon_emotion("this is a whole english sentence") is None
