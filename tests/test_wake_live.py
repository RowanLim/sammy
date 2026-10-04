"""唤醒词的真模型检测 —— 需要先跑 `./scripts/fetch_models.sh`。

**这层不能省。** 关键词写错了不会报错，只会**永远不触发**：
安静地什么都不做是最难查的失败方式。所以必须拿真音频验它真能听见，
而且要验**反例** —— 太灵敏等于厨房里的锅碗声也能叫醒它。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy.audio import pad_for_context, read_wav
from sammy.wake import WakeWord

pytestmark = pytest.mark.live  # 要几百 MB 的模型，不进提交时那套快测试

HERE = pathlib.Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def wake() -> WakeWord:
    w = WakeWord()
    if not w.ready:
        pytest.skip("唤醒模型没下，先跑 ./scripts/fetch_models.sh")
    return w.load()


def _detect(w: WakeWord, name: str) -> list[str]:
    samples = pad_for_context(read_wav(HERE / "audio" / name))
    return w.detect(samples)


@pytest.mark.parametrize(
    "name",
    [
        "wake-zh-1.wav",  # 嗨萨米
        "wake-zh-2.wav",  # 萨米
        "wake-zh-3.wav",  # 嗨萨米，你在干嘛（唤醒词在句首）
        "wake-en-1.wav",  # Hi Sammy
        "wake-en-2.wav",  # Sammy
    ],
)
def test_wake_words_are_detected(wake, name):
    assert _detect(wake, name), f"{name} 该被唤醒却没命中 —— 关键词表可能写错了"


@pytest.mark.parametrize(
    "name",
    [
        "neg-zh-1.wav",  # 今天天气不错我们出去走走吧
        "neg-zh-2.wav",  # 萨琪玛很好吃（近似但不同）
        "neg-en-1.wav",  # how are you doing today
    ],
)
def test_ordinary_speech_does_not_wake_it(wake, name):
    hits = _detect(wake, name)
    assert not hits, f"{name} 不该唤醒它，却命中了 {hits}（太灵敏 = 厨房锅碗声也叫醒它）"


def test_unpadded_clip_is_a_known_false_negative(wake):
    """钉住"流式模型需要前文"这条。

    裸音频（一开头就是人声）**测不出来**，但那不代表唤醒词坏了 ——
    真机上麦克风一直在喂音频，所以不会遇到这个。
    如果哪天这条开始失败，说明模型对上下文的要求变了：可以放宽
    `audio.pad_for_context` 的默认值，并把这条测试删掉。
    """
    raw = read_wav(HERE / "audio" / "wake-zh-1.wav")
    assert not wake.detect(raw), "裸音频现在能命中了 → pad_for_context 可以放宽了，改测试"
