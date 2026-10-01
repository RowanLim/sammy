"""模型档位配置 —— 分档、回落、凭证不泄露。

全部用注入的 env dict，不读真实 .env（那里面有真凭证，测试不该依赖它）。
"""

import pytest

from sammy.models import TIERS, ModelConfig, describe_all


def test_tiers_declared():
    assert set(TIERS) == {"CHAT", "AGENT"}
    for meta in TIERS.values():
        assert meta["label"] and meta["why"]


def test_chat_tier_uses_own_prefix():
    env = {
        "SAMMY_CHAT_API_KEY": "k" * 36,
        "SAMMY_CHAT_BASE_URL": "https://example.com/v1",
        "SAMMY_CHAT_MODEL": "fast-model",
    }
    cfg = ModelConfig.from_env("CHAT", env)
    assert cfg.ready
    assert cfg.model == "fast-model"
    assert cfg.endpoint == "https://example.com/v1/chat/completions"


def test_chat_tier_falls_back_to_legacy_doubao():
    """历史配置兼容：没写 SAMMY_CHAT_* 时回落到 DOUBAO_*，否则今天就跑不起来了。"""
    env = {
        "DOUBAO_API_KEY": "k" * 36,
        "DOUBAO_BASE_URL": "https://ark.example.com/api/v3",
        "DOUBAO_MODEL": "legacy-model",
    }
    cfg = ModelConfig.from_env("CHAT", env)
    assert cfg.ready
    assert cfg.model == "legacy-model"


def test_explicit_chat_wins_over_legacy():
    env = {
        "SAMMY_CHAT_API_KEY": "new",
        "SAMMY_CHAT_BASE_URL": "https://new.example.com/v1",
        "SAMMY_CHAT_MODEL": "new-model",
        "DOUBAO_API_KEY": "old",
        "DOUBAO_BASE_URL": "https://old.example.com",
        "DOUBAO_MODEL": "old-model",
    }
    cfg = ModelConfig.from_env("CHAT", env)
    assert cfg.model == "new-model"
    assert cfg.api_key == "new"


def test_agent_tier_has_no_legacy_fallback():
    """AGENT 档不该悄悄拿聊天档的 key —— 那会让"没配"看起来像"配好了"。"""
    env = {
        "DOUBAO_API_KEY": "k" * 36,
        "DOUBAO_BASE_URL": "https://ark.example.com/api/v3",
        "DOUBAO_MODEL": "lite",
    }
    cfg = ModelConfig.from_env("AGENT", env)
    assert not cfg.ready
    assert cfg.api_key == ""


def test_unknown_tier_rejected():
    with pytest.raises(ValueError):
        ModelConfig.from_env("NOPE", {})


def test_endpoint_has_no_double_slash():
    cfg = ModelConfig(tier="CHAT", api_key="k", base_url="https://x.com/v1/", model="m")
    assert cfg.endpoint == "https://x.com/v1/chat/completions"


def test_ready_requires_all_three():
    assert not ModelConfig(tier="CHAT", api_key="k").ready
    assert not ModelConfig(tier="CHAT", base_url="u").ready
    assert not ModelConfig(tier="CHAT", model="m").ready
    assert ModelConfig(tier="CHAT", api_key="k", base_url="u", model="m").ready


def test_masked_key_never_leaks_content():
    """凭证描述里不能出现 key 的任何内容 —— 它会被打印到终端和聊天里。"""
    secret = "abcdef0123456789abcd" * 2
    cfg = ModelConfig(tier="CHAT", api_key=secret, base_url="u", model="m")
    masked = cfg.masked_key
    assert secret not in masked
    assert secret[:4] not in masked
    assert secret[-4:] not in masked
    assert str(len(secret)) in masked


def test_describe_all_does_not_leak():
    env = {
        "SAMMY_CHAT_API_KEY": "supersecretkeyvalue1234567890",
        "SAMMY_CHAT_BASE_URL": "https://x.com/v1",
        "SAMMY_CHAT_MODEL": "m",
    }
    out = describe_all(env)
    assert "supersecretkeyvalue1234567890" not in out
    assert "CHAT" in out and "AGENT" in out
    assert "✅" in out and "⬜" in out
