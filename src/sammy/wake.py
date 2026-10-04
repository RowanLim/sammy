"""唤醒词 —— 离线听懂「嗨萨米 / Hi Sammy」。

**离线**是硬要求：唤醒词得一直在听，走云端等于把麦克风的音频一直往上传，
既费流量又费钱，而且断网就哑了。

## 两个模型，各管一种说法

| 说什么 | 模型 | 关键词怎么写 |
|:---|:---|:---|
| 「嗨萨米」「萨米」 | zipformer-wenetspeech-3.3M（**拼音**建模） | `h āi s à m ǐ @嗨萨米` |
| "Hi Sammy" | zipformer-gigaspeech-3.3M（**BPE** 建模） | `▁HI ▁SA M M Y` |

## 下面这些全是实测结论，别凭直觉改（每条都让"唤醒词不工作"过一轮）

1. **中文模型发不出英文词**。「Sammy」按英文写（`s a m m y`）**根本不触发**，
   换成 `s ā m i` / `s a m i` / 大写 `S A M M Y` 也都不触发。
   中文使用者说 Sammy 就是「萨米」(sà mǐ) —— **用中文音节写就认**。
2. **英文模型要按 BPE 片段切**。`▁HI ▁S A M M Y`（逐字母）**不触发**；
   正确的是 `▁HI ▁SA M M Y`（`▁SA` 是一个片段）。切错就是安静地不工作。
3. **关键词文件里不能有注释**。`#` 在这套格式里是**阈值标记**，
   注释行会被当关键词解析，报 `ValueError: stof: no conversion` ——
   一个和真正原因毫无关系的错，我第一次就卡在这儿。
   显示名里也不能有空格（`@嗨 Sammy` 同样报那个错），要写 `@嗨Sammy`。
4. **流式模型需要前文上下文**：一开头就是人声的短音频会**假阴性**。
   真机连续喂音频没这问题，但文件和测试必须补前置静音（见 `audio.pad_for_context`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .paths import project_root

SAMPLE_RATE = 16000

# 唤醒词模型放这儿（由 scripts/fetch_models.sh 下载，已 gitignore）
MODELS_DIR_NAME = "models"
ZH_MODEL = "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
EN_MODEL = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"

# 阈值调低会让厨房里的锅碗声也叫醒它 —— 想更灵，**加写法**，别降这个
DEFAULT_THRESHOLD = 0.25
DEFAULT_SCORE = 1.0


def models_dir() -> Path:
    return project_root() / MODELS_DIR_NAME


@dataclass(frozen=True)
class WakeModel:
    """一个唤醒模型 + 它的关键词表 + 它会认出来的词（用于显示）。"""

    name: str  # 内部名（zh / en）
    label: str  # 给人看的
    model_dir: Path
    keywords_file: Path
    phrases: tuple[str, ...]  # 命中的关键词长什么样 → 显示用

    @property
    def ready(self) -> bool:
        if not self.model_dir.is_dir() or not self.keywords_file.is_file():
            return False
        kinds = ("encoder", "decoder", "joiner")
        return (self.model_dir / "tokens.txt").is_file() and all(
            list(self.model_dir.glob(f"{kind}-*.int8.onnx")) for kind in kinds
        )


def default_models(assets: Path | None = None) -> list[WakeModel]:
    """默认装哪几个唤醒模型。文件不在就跳过（不是错误 —— 可能还没下）。"""
    m = models_dir()
    a = assets if assets is not None else project_root() / "assets" / "wake"
    return [
        WakeModel("zh", "嗨萨米（中文）", m / ZH_MODEL, a / "keywords.txt", ("嗨萨米", "萨米")),
        WakeModel(
            "en", "Hi Sammy（英文）", m / EN_MODEL, a / "keywords-en.txt", ("HI SAMMY", "SAMMY")
        ),
    ]


def keyword_lines(path: Path) -> list[str]:
    """读关键词表，并且**当场检查它有没有被污染**。

    这台机器上踩过的两个坑都在这里拦：注释行、显示名里的空格。
    两种都会让模型报 `stof: no conversion`，而且完全不提示真正原因。
    """
    if not path.is_file():
        raise FileNotFoundError(f"关键词表不存在：{path}")
    lines = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            raise ValueError(
                f"{path}:{i} 关键词表里不能写注释（`#` 在这套格式里是阈值标记）。"
                f"注释会被当关键词解析，然后报一个和真正原因毫无关系的 `stof: no conversion`。"
                f"要写说明请写在 assets/wake/README.md 里。"
            )
        if "@" in line and " " in line.split("@", 1)[1]:
            raise ValueError(
                f"{path}:{i} @ 后面的显示名不能有空格（`@嗨 Sammy` 会被拆成两个字段，"
                f"同样报 `stof: no conversion`）。要写 `@嗨Sammy`。"
            )
        lines.append(line)
    if not lines:
        raise ValueError(f"{path} 里一条关键词都没有")
    return lines


def _pick(model_dir: Path, kind: str) -> str:
    """挑具体用哪个 onnx —— 优先 int8（快一倍，准确率几乎一样）。"""
    for pat in (f"{kind}-*.int8.onnx", f"{kind}-*.onnx"):
        hits = sorted(model_dir.glob(pat))
        if hits:
            return str(hits[0])
    raise FileNotFoundError(f"{model_dir} 里找不到 {kind}-*.onnx")


@dataclass
class _Spotter:
    """一个模型 + 它的流。命中时返回关键词。"""

    model: WakeModel
    threshold: float = DEFAULT_THRESHOLD
    score: float = DEFAULT_SCORE
    _kws: object = field(default=None, repr=False)

    def build(self):
        import sherpa_onnx

        self._kws = sherpa_onnx.KeywordSpotter(
            tokens=str(self.model.model_dir / "tokens.txt"),
            encoder=_pick(self.model.model_dir, "encoder"),
            decoder=_pick(self.model.model_dir, "decoder"),
            joiner=_pick(self.model.model_dir, "joiner"),
            num_threads=2,
            keywords_file=str(self.model.keywords_file),
            keywords_score=self.score,
            keywords_threshold=self.threshold,
            num_trailing_blanks=1,
            provider="cpu",
        )
        keyword_lines(self.model.keywords_file)  # 先校验，给人看得懂的报错
        return self

    def new_stream(self):
        return self._kws.create_stream()

    def feed(self, stream, samples: np.ndarray) -> str | None:
        stream.accept_waveform(SAMPLE_RATE, samples)
        while self._kws.is_ready(stream):
            self._kws.decode_stream(stream)
            hit = self._kws.get_result(stream)
            if hit:
                self._kws.reset_stream(stream)
                return hit
        return None


class WakeSession:
    """一边喂音频一边听唤醒词。喂一块，返回这块里听到的词（可能为空）。"""

    def __init__(self, spotters: list[_Spotter]) -> None:
        self._pairs = [(s, s.new_stream()) for s in spotters]

    def feed(self, samples: np.ndarray) -> list[str]:
        hits = []
        for spotter, stream in self._pairs:
            hit = spotter.feed(stream, samples)
            if hit:
                hits.append(hit)
        return hits

    def finish(self) -> list[str]:
        """音频结束了（输入源到头）—— 把尾巴解完。"""
        hits = []
        for spotter, stream in self._pairs:
            stream.input_finished()
            while spotter._kws.is_ready(stream):
                spotter._kws.decode_stream(stream)
                hit = spotter._kws.get_result(stream)
                if hit:
                    hits.append(hit)
                    spotter._kws.reset_stream(stream)
        return hits


def strip_wake(
    text: str,
    phrases: tuple[str, ...] = ("嗨萨米", "萨米", "hi sammy", "hey sammy", "sammy"),
) -> str:
    """把开头那句唤醒词去掉，剩下的才是你真正要说的话。

    唤醒词会被识别进同一句里（"嗨萨米，你在干嘛"），
    整句丢给大脑的话它会对着自己的名字回答。

    识别结果里常夹空格和标点（"嗨，萨米，你在干嘛"），
    所以先按"去掉空格标点"的形态比对，再换算回原串的截断位置。
    """
    drop = " \t，,。.！!？?、~～"
    keep = [(i, ch) for i, ch in enumerate(text) if ch not in drop]
    flat = "".join(ch for _, ch in keep).lower()
    for p in sorted(phrases, key=len, reverse=True):
        key = "".join(ch for ch in p if ch not in drop).lower()
        if key and flat.startswith(key):
            cut = keep[len(key) - 1][0] + 1
            return text[cut:].strip(drop)
    return text.strip()


class WakeWord:
    """Sammy 的耳朵（只负责"叫我的名字"这一件事）。"""

    def __init__(self, models: list[WakeModel] | None = None, threshold: float = DEFAULT_THRESHOLD):
        self.models = models if models is not None else default_models()
        self.threshold = threshold
        self._spotters: list[_Spotter] = []
        self.skipped: list[WakeModel] = []

    @property
    def ready(self) -> bool:
        return bool([m for m in self.models if m.ready])

    def load(self) -> WakeWord:
        """加载能用的模型。缺模型的**跳过并记下来**，不整体失败 ——
        只有一个模型也要能唤醒（少一种说法总比完全不能唤醒好）。"""
        self._spotters = []
        self.skipped = []
        for m in self.models:
            if not m.ready:
                self.skipped.append(m)
                continue
            keyword_lines(m.keywords_file)  # 早失败，给人看得懂的原因
            self._spotters.append(_Spotter(m, self.threshold).build())
        return self

    def session(self) -> WakeSession:
        if not self._spotters:
            raise RuntimeError("一个唤醒模型都没加载。先下模型：./scripts/fetch_models.sh")
        return WakeSession(self._spotters)

    def detect(self, samples: np.ndarray) -> list[str]:
        """整段音频过一遍（文件回放用）。**调用方负责补前置静音**，
        见 audio.pad_for_context —— 不补会假阴性。"""
        s = self.session()
        hits = list(s.feed(samples))
        hits.extend(s.finish())
        return hits

    def describe(self) -> str:
        lines = ["唤醒词："]
        for m in self.models:
            if m in self.skipped:
                lines.append(f"  ✗ {m.label}（模型没下：{m.model_dir.name}）")
            else:
                lines.append(f"  ✓ {m.label} → {' / '.join(m.phrases)}")
        return "\n".join(lines)


__all__ = [
    "DEFAULT_SCORE",
    "DEFAULT_THRESHOLD",
    "EN_MODEL",
    "MODELS_DIR_NAME",
    "SAMPLE_RATE",
    "ZH_MODEL",
    "WakeModel",
    "WakeSession",
    "WakeWord",
    "default_models",
    "keyword_lines",
    "models_dir",
    "strip_wake",
]
