"""听懂你说什么 —— 离线的"你说完了没"（VAD）+ "说的是什么"（语音识别）。

**为什么这一环也要离线**：唤醒之后的对话内容比唤醒词**更私密**。
能不上云的就不上云。（大模型那一环必须联网，所以记忆里只留提炼过的东西 ——
PRD 那条"原始感知数据不进长期记忆"就是为这个定的。）

两个模型：
- **VAD**（`silero_vad.onnx`，652KB）：这段是不是人在说话 / 你说完了没
- **ASR**（`paraformer-zh-small`，74MB）：把语音转成文字

模型不在就**响亮地失败**，不静默降级成"什么都听不见" ——
后者会让人以为是自己说话的方式有问题。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio import SAMPLE_RATE, AudioSource
from .wake import models_dir

ASR_MODEL = "sherpa-onnx-paraformer-zh-small-2024-03-09"
VAD_MODEL = "silero_vad.onnx"

# 你说完之后的静音达到这么久就算说完了（太短会被换气打断，太长要等很久）
MIN_SILENCE_S = 0.35
# 短于这个的"人声"当噪声丢掉（敲键盘、碰桌子）
MIN_SPEECH_S = 0.25
# 一次最多攒多少秒（防止它一直录下去）
MAX_UTTERANCE_S = 20.0


def asr_dir() -> Path:
    return models_dir() / ASR_MODEL


def vad_file() -> Path:
    return models_dir() / VAD_MODEL


@dataclass
class Ears:
    """耳朵：VAD 切句 + 离线识别。"""

    num_threads: int = 2
    _rec: object = None  # OfflineRecognizer
    _vad_cfg: object = None

    @property
    def ready(self) -> bool:
        return (asr_dir() / "model.int8.onnx").is_file() and (asr_dir() / "tokens.txt").is_file()

    @property
    def vad_ready(self) -> bool:
        return vad_file().is_file()

    def load(self) -> Ears:
        import sherpa_onnx

        if not self.ready:
            raise FileNotFoundError(f"识别模型不在：{asr_dir()}。先跑 ./scripts/fetch_models.sh")
        self._rec = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=str(asr_dir() / "model.int8.onnx"),
            tokens=str(asr_dir() / "tokens.txt"),
            num_threads=self.num_threads,
            sample_rate=SAMPLE_RATE,
            provider="cpu",
        )
        if self.vad_ready:
            cfg = sherpa_onnx.VadModelConfig()
            cfg.silero_vad.model = str(vad_file())
            cfg.silero_vad.min_silence_duration = MIN_SILENCE_S
            cfg.silero_vad.min_speech_duration = MIN_SPEECH_S
            cfg.sample_rate = SAMPLE_RATE
            cfg.num_threads = self.num_threads
            self._vad_cfg = cfg
        return self

    def transcribe(self, samples: np.ndarray) -> str:
        """把一段音频转成文字（不切句，整段喂）。"""
        if self._rec is None:
            self.load()
        s = self._rec.create_stream()
        s.accept_waveform(SAMPLE_RATE, samples)
        self._rec.decode_stream(s)
        return str(s.result.text).strip()

    def segments(self, samples: np.ndarray) -> list[np.ndarray]:
        """用 VAD 切出"一段一段的人声"。没有 VAD 模型就把整段当一段。"""
        import sherpa_onnx

        if self._vad_cfg is None:
            self.load()
        if self._vad_cfg is None:
            return [samples]
        vad = sherpa_onnx.VoiceActivityDetector(self._vad_cfg, buffer_size_in_seconds=30)
        out: list[np.ndarray] = []
        step = SAMPLE_RATE // 10  # 100ms
        for i in range(0, len(samples), step):
            vad.accept_waveform(samples[i : i + step])
        vad.flush()
        while not vad.empty():
            seg = vad.front
            out.append(np.array(seg.samples, dtype=np.float32))
            vad.pop()
        return out

    def listen(self, source: AudioSource) -> str:
        """从输入源听到"一句话说完"，返回转写文字。

        真机上就是：一直听 → 听见人声 → 等它静下来 → 转写。
        用文件当输入源时，就是把这整段过一遍。
        """
        chunks: list[np.ndarray] = []
        total = 0
        for chunk in source.frames():
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_UTTERANCE_S * SAMPLE_RATE:
                break
        if not chunks:
            return ""
        samples = np.concatenate(chunks)
        segs = self.segments(samples)
        if not segs:
            return ""
        # 段落拼起来识别（短句分开识别容易丢字）
        return self.transcribe(np.concatenate(segs))

    def describe(self) -> str:
        lines = ["耳朵："]
        lines.append(f"  {'✓' if self.ready else '✗'} 识别 paraformer-zh-small（{asr_dir().name}）")
        lines.append(f"  {'✓' if self.vad_ready else '✗'} VAD silero_vad（{VAD_MODEL}）")
        return "\n".join(lines)


__all__ = [
    "ASR_MODEL",
    "MAX_UTTERANCE_S",
    "MIN_SILENCE_S",
    "MIN_SPEECH_S",
    "VAD_MODEL",
    "Ears",
    "asr_dir",
    "vad_file",
]
