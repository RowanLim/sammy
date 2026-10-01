"""模型档位配置 —— 让 Sammy 的"脑子"可插拔。

为什么要分档（依据 docs/research/同类项目调研.md 的 Miru 架构）：
- **chat 档**：聊天 + 情绪标签。要的是**快**（谁也不想等 5 秒），所以用 lite 级模型。
- **agent 档**：调工具、多步推理、记忆整理。要的是**会想**，慢一点可以接受。
- 两个档位各配各的 key，互不影响。聊天不该被 agent 的负载拖慢，agent 也不该被 lite 的能力卡住。

所有档位都走 **OpenAI 兼容**接口 —— 这样换供应商（豆包 / DeepSeek / OpenAI / Kimi / 本地
llama.cpp）**只改 .env，不改一行代码**。
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

from .paths import env_file

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
# 配置文件位置：源码运行看仓库里的 .env，打包后看 ~/Library/Application Support/Sammy/.env。
# 打出来的 .app 不该依赖源码目录，更不该把凭证打进包里（见 paths.py）。
ENV_FILE = env_file()

# 档位定义：环境变量前缀 → (用途说明, 默认供应商)
TIERS: dict[str, dict] = {
    "CHAT": {
        "label": "聊天档",
        "why": "对话 + 情绪标签。要快，用 lite 级模型",
        "fallback_prefix": "DOUBAO",  # 兼容历史配置：没有 SAMMY_CHAT_* 时用旧的 DOUBAO_*
    },
    "AGENT": {
        "label": "代理档",
        "why": "调工具 / 多步推理 / 记忆整理。要会想",
        "fallback_prefix": None,
    },
}


def load_env() -> dict[str, str]:
    """读 .env；已存在的进程环境变量优先（方便临时覆盖）。"""
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    known = {
        f"SAMMY_{tier}_{suffix}" for tier in TIERS for suffix in ("API_KEY", "BASE_URL", "MODEL")
    }
    for k in known:
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


@dataclass
class ModelConfig:
    """一个档位的完整配置。"""

    tier: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    thinking: str = "off"
    extra: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        """能不能用：三样都得有。"""
        return bool(self.api_key and self.base_url and self.model)

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    @property
    def masked_key(self) -> str:
        """给人看的描述 —— **不泄露 key 内容**，连前后缀都不给。"""
        return f"已配置（长度 {len(self.api_key)}）" if self.api_key else "未配置"

    @property
    def label(self) -> str:
        return TIERS.get(self.tier, {}).get("label", self.tier)

    @classmethod
    def from_env(cls, tier: str, env: dict[str, str] | None = None) -> ModelConfig:
        tier = tier.upper()
        if tier not in TIERS:
            raise ValueError(f"未知档位 {tier}，可选：{list(TIERS)}")
        env = env if env is not None else load_env()

        def pick(suffix: str) -> str:
            v = env.get(f"SAMMY_{tier}_{suffix}", "")
            if not v:
                fb = TIERS[tier].get("fallback_prefix")
                if fb:
                    v = env.get(f"{fb}_{suffix}", "")
            return v.strip()

        return cls(
            tier=tier,
            api_key=pick("API_KEY"),
            base_url=pick("BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3",
            model=pick("MODEL"),
            thinking=env.get("SAMMY_THINKING", "off"),
        )


def describe_all(env: dict[str, str] | None = None) -> str:
    """`--models` 的输出：每个档位配了什么、能不能用。"""
    env = env if env is not None else load_env()
    lines = [f"配置文件: {ENV_FILE}", ""]
    for tier, meta in TIERS.items():
        cfg = ModelConfig.from_env(tier, env)
        mark = "✅" if cfg.ready else "⬜"
        lines.append(f"{mark} {tier:<6} {meta['label']}　{meta['why']}")
        lines.append(f"      接口  {cfg.base_url}")
        lines.append(f"      模型  {cfg.model or '（未设置）'}")
        lines.append(f"      凭证  {cfg.masked_key}")
        lines.append(f"      思考链 {cfg.thinking}")
        lines.append("")
    if not ModelConfig.from_env("AGENT", env).ready:
        lines.append("提示：AGENT 档还没配。配上之后 Sammy 才能真的调工具、多步推理。")
    return "\n".join(lines)


__all__ = ["ENV_FILE", "TIERS", "ModelConfig", "describe_all", "load_env"]
