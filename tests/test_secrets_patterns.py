"""凭证规则本身也要有测试。

为什么值得单独写一个文件：**安全检查失效是静默的**。
规则写错了，它不会报错，只会一直说"通过" —— 那比没有检查更危险，因为它给你安全感。

这里对每条规则做两件事：
1. 拿**已知的坏样本**喂它，必须命中；
2. 拿**已知的好样本**喂它，必须不命中（假警报会训练人忽略警报）。

并且**两个引擎都要测**：审计脚本用 `git grep -E`（POSIX ERE），
暂存区检查用 Python `re` —— 两者语法不同，曾经因此静默失效过一次。

⚠️ 文件里的假凭证**必须拼出来，不能写成完整字面量**：
写全了会被我们自己那道暂存区检查拦下（实测拦过），也会被托管平台的密钥扫描当成真泄漏。
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
from audit_repo import SECRET_FILES, SECRET_PATTERNS
from check_staged_secrets import to_python_re


def _body(n: int) -> str:
    """拼出一串像 key 的字符。故意在运行时生成 —— 见文件头说明。"""
    return "A" * n


_UUID = "-".join(["deadbeef", "1234", "5678", "9abc", "def012345678"])

# 每条规则的 (坏样本, 好样本)。都是**假造**的，不是真凭证。
SAMPLES: dict[str, tuple[str, str]] = {
    "被赋值的 UUID 形式 key": (
        f'API_KEY = "{_UUID}"',
        f'image = "https://example.com/assets/{_UUID}"',  # 没关键词，不该报
    ),
    "OpenAI 风格 key (sk-)": (
        f'key = "sk-{_body(32)}"',
        'key = "sk-short"',  # 太短，不是 key 的样子
    ),
    "GitHub token": (
        f'token = "ghp_{_body(30)}"',
        'token = "ghp_short"',
    ),
    "GitHub 细粒度 token": (
        f'token = "github_pat_{_body(30)}"',
        'token = "github_pat_short"',
    ),
    "AWS Access Key": (
        f'aws_access_key_id = "AKIA{_body(16)}"',
        'aws_key = "AKIANOTREAL"',  # 长度不够
    ),
    "硬编码的 Bearer token": (
        'headers = {"Authorization": "Bearer ' + _body(40) + '"}',
        'headers = {"Authorization": "Bearer ${TOKEN}"}',
    ),
}


def test_every_pattern_has_a_sample():
    """加了新规则就必须同时给出坏样本和好样本 —— 否则这条规则等于没被验证过。"""
    labels = {label for _, label in SECRET_PATTERNS}
    assert labels == set(SAMPLES), f"规则与样本对不上：{labels ^ set(SAMPLES)}"


def test_samples_are_not_real_secrets():
    """守住"样本是假的"这件事：它们必须能被本仓库自己的审计规则解释为构造物。"""
    for label, (bad, _) in SAMPLES.items():
        assert _body(16) in bad or _UUID in bad, f"{label} 的坏样本看着不像构造的"


@pytest.mark.parametrize("pattern,label", SECRET_PATTERNS)
def test_pattern_catches_bad_sample_in_python(pattern, label):
    bad, _ = SAMPLES[label]
    assert re.search(to_python_re(pattern), bad, re.IGNORECASE), (
        f"规则「{label}」在 Python 里抓不到坏样本：{bad}"
    )


@pytest.mark.parametrize("pattern,label", SECRET_PATTERNS)
def test_pattern_ignores_good_sample_in_python(pattern, label):
    _, good = SAMPLES[label]
    assert not re.search(to_python_re(pattern), good, re.IGNORECASE), (
        f"规则「{label}」在 Python 里对好样本误报：{good}"
    )


def _grep_in_temp_repo(pattern: str, text: str, filename: str, tmp_path) -> str:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / filename).write_text(text + "\n", encoding="utf-8")
    # ⚠️ 必须 add：`git grep` 只搜**被跟踪**的文件。
    # 忘了这步，"搜不到任何东西" —— 静态检查类测试的老陷阱。
    subprocess.run(["git", "add", filename], cwd=repo, check=True)
    r = subprocess.run(
        ["git", "grep", "-ilE", pattern, "--", filename],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return r.stdout


@pytest.mark.parametrize("pattern,label", SECRET_PATTERNS)
def test_pattern_catches_bad_sample_in_git_grep(pattern, label, tmp_path):
    """审计脚本走 `git grep -E`（POSIX ERE）—— 和 Python re 不是一套语法，必须单独验。"""
    bad, _ = SAMPLES[label]
    assert _grep_in_temp_repo(pattern, bad, "leak.txt", tmp_path), (
        f"规则「{label}」在 git grep -E 里抓不到坏样本：{bad}"
    )


@pytest.mark.parametrize("pattern,label", SECRET_PATTERNS)
def test_pattern_ignores_good_sample_in_git_grep(pattern, label, tmp_path):
    _, good = SAMPLES[label]
    assert not _grep_in_temp_repo(pattern, good, "ok.txt", tmp_path), (
        f"规则「{label}」在 git grep -E 里对好样本误报：{good}"
    )


def test_no_pattern_uses_posix_class_unsupported_by_python():
    """Python re 不支持 POSIX 字符类 —— 谁把 [[:space:]] 直接塞进 Python 用法就在这被拦。"""
    for pattern, label in SECRET_PATTERNS:
        assert "[[:space:]]" not in to_python_re(pattern), f"{label} 没被转换，Python 里会失效"
    assert to_python_re("a[[:space:]]b") == r"a\sb"


def test_secret_file_names_are_exact_not_substring():
    """.env.example 是空模板，不该被当成凭证文件（这条曾经误报过）。"""
    assert ".env" in SECRET_FILES
    assert ".env.example" not in SECRET_FILES
