"""音频输入 —— 麦克风，或者（在没有麦克风的机器上）一个音频文件。

**为什么要有"文件"这种输入源**：Rowan 的机器现在没有麦克风
（Mac 上只有向日葵的虚拟声卡；Nex 的粉色口上其实没插东西 —— 录出来是直流削顶噪声）。
"没麦克风"不该等于"什么都验不了"，所以输入源做成可替换的：
同一个接口，换实现不动上层代码。等话筒到位，只是换回 MicSource。

统一规格：**16 kHz / 单声道 / float32 [-1, 1]** —— 三个模型（KWS/VAD/ASR）都要这个。
"""

from __future__ import annotations

import array
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


def read_wav(path: str | Path, want_rate: int = SAMPLE_RATE) -> np.ndarray:
    """读一个 wav 成 float32 [-1,1] 单声道。

    只接受 16k 单声道：**不做重采样**。悄悄重采样会让"它怎么听不清"
    变成一个查不出来的问题 —— 宁可在这里响亮地失败。
    （要 16k 就用 `say --data-format=LEI16@16000` 或者 ffmpeg 先转。）
    """
    with wave.open(str(path)) as w:
        if w.getframerate() != want_rate or w.getnchannels() != 1:
            raise ValueError(
                f"{path} 得是 {want_rate}Hz 单声道，实际是 "
                f"{w.getframerate()}Hz {w.getnchannels()}声道。"
                f"先转一下：ffmpeg -i in.wav -ar {want_rate} -ac 1 out.wav"
            )
        a = array.array("h")
        a.frombytes(w.readframes(w.getnframes()))
    return np.frombuffer(a.tobytes(), dtype=np.int16).astype(np.float32) / 32768.0


def pad_for_context(samples: np.ndarray, lead_ms: int = 800, tail_ms: int = 600) -> np.ndarray:
    """两头都补一段静音。

    **这是实测踩出来的坑，两头各有原因**：

    - **前面**：唤醒模型是流式的，编码器需要一点"前文"才收敛。
      实测「小爱同学」1.26s 裸音频不命中，补 800ms 前置静音后命中。
    - **后面**：模型配了 `num_trailing_blanks=1`，**关键词后面得有个空白帧它才确认**。
      实测「萨米」「Hi Sammy」这种短词，只补前面不命中，尾巴也补上就命中。

    真机没这问题（麦克风一直在喂，前后都是连续音频），
    但**文件回放和测试必须两头都补** —— 否则会得出"唤醒词不工作"的错误结论。
    """
    parts = []
    if lead_ms > 0:
        parts.append(np.zeros(int(SAMPLE_RATE * lead_ms / 1000), dtype=np.float32))
    parts.append(samples.astype(np.float32, copy=False))
    if tail_ms > 0:
        parts.append(np.zeros(int(SAMPLE_RATE * tail_ms / 1000), dtype=np.float32))
    return np.concatenate(parts) if len(parts) > 1 else samples


class AudioSource:
    """输入源的共同接口：`frames()` 一块一块吐 16k 单声道 float32。"""

    sample_rate = SAMPLE_RATE

    def frames(self) -> Iterator[np.ndarray]:  # pragma: no cover - 接口
        raise NotImplementedError


@dataclass
class WavSource(AudioSource):
    """从文件读 —— 没有麦克风时的替代品（也是测试用的输入源）。"""

    path: Path
    chunk_ms: int = 100
    lead_ms: int = 800  # 见 pad_for_context 的说明（前面给编码器收敛）
    tail_ms: int = 600  # 后面给解码器收尾（num_trailing_blanks=1）
    loops: int = 1  # >1 可以反复喂同一段（模拟"一直在听"）

    def frames(self) -> Iterator[np.ndarray]:
        samples = pad_for_context(read_wav(self.path), self.lead_ms, self.tail_ms)
        step = int(SAMPLE_RATE * self.chunk_ms / 1000)
        for _ in range(max(1, self.loops)):
            for i in range(0, len(samples), step):
                yield samples[i : i + step]


def list_input_devices() -> list[dict]:
    """列出能录音的设备。

    没有 sounddevice（或系统里一个输入设备都没有）就返回空列表，
    **不抛异常** —— "没有麦克风"是一种正常状态，不是错误。
    """
    try:
        import sounddevice as sd
    except ImportError:
        return []
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            out.append(
                {
                    "index": i,
                    "name": d["name"],
                    "channels": d["max_input_channels"],
                    "default": i == sd.default.device[0],
                }
            )
    return out


class MicSource(AudioSource):
    """真麦克风。设备不在就抛一个**说清楚怎么办**的错，别让人对着沉默猜。"""

    def __init__(self, device: int | str | None = None, chunk_ms: int = 100) -> None:
        try:
            import sounddevice as sd
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("没装 sounddevice，先装：uv pip install sounddevice") from e

        self._sd = sd
        self.device = device
        self.chunk_ms = chunk_ms
        devices = list_input_devices()
        if not devices:
            raise RuntimeError(
                "这台机器上没有任何录音设备。可以：\n"
                "  · 接一个 USB 麦克风，或\n"
                "  · 用文件代替：--voice-demo <path.wav>"
            )

    def frames(self) -> Iterator[np.ndarray]:
        blocksize = int(SAMPLE_RATE * self.chunk_ms / 1000)
        with self._sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            device=self.device,
        ) as stream:
            while True:
                data, _ = stream.read(blocksize)
                yield data.reshape(-1)


__all__ = [
    "SAMPLE_RATE",
    "AudioSource",
    "MicSource",
    "WavSource",
    "list_input_devices",
    "pad_for_context",
    "read_wav",
]
