#!/usr/bin/env python
"""仓库凭证审计 —— 每次发布/备份前跑一次。

比 `grep .env` 严格得多：那个会把 `.env.example` 也算进去，
**假警报会训练人忽略警报**，比没有检查更危险。

查四件事：
1. 当前树里有没有 `.env` 这类真凭证文件（精确匹配文件名）
2. **全历史**（所有分支 / 标签 / 悬空提交）里有没有出现过
3. 全历史快照里有没有任何文件内容命中凭证特征
4. `.gitignore` 是否仍然正确忽略本地凭证文件

用法: python3 scripts/audit_repo.py    （退出码非 0 = 有问题）
"""

from __future__ import annotations

import pathlib
import subprocess
import sys


def _root() -> pathlib.Path:
    """默认审计本仓库；也接受一个路径参数 —— 这样能用"故意埋了凭证的仓库"反向验证它真会报警。"""
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        return pathlib.Path(sys.argv[1]).resolve()
    return pathlib.Path(__file__).resolve().parent.parent


ROOT = _root()

# 真凭证文件名（**精确匹配文件名**，不是子串匹配）
SECRET_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "ADMIN-CREDENTIALS.txt",
}

# 凭证内容的特征。**故意不写死任何真实 key** —— 否则审计脚本自己就把 key 带进仓库了。
#
# ⚠️ 坑一（靠反向验证才发现）：`git grep -E` 是 POSIX ERE，**不支持 `\b` 词边界**，
# 写了 `\b` 的规则会静默失效 —— 检查一路"通过"，其实什么都没查。
# 所以正则一律不用 `\b`，也不用 `\s`，改用 POSIX 的 `[[:space:]]`。
#
# ⚠️ 坑二：**别匹配"任何地方的 UUID"**。第三方 README 里的图片资源 URL
# （user-attachments/assets/<uuid>）会成片误报 —— 假警报会训练人忽略警报。
# 正确做法是匹配**凭证赋值语句**的上下文。
SECRET_PATTERNS = [
    (
        r"(api[_-]?key|apikey|access[_-]?key|secret|token|password|passwd|key)"
        r"['\"]?[[:space:]]*[:=][[:space:]]*['\"][0-9a-f]{8}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "被赋值的 UUID 形式 key",
    ),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI 风格 key (sk-)"),
    (r"(ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "GitHub 细粒度 token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"Bearer +[A-Za-z0-9._~+/-]{30,}", "硬编码的 Bearer token"),
]

# 第三方抓取下来的文档不属于我们的代码，且天然塞满 URL —— 从内容扫描里排除。
# （路径写在这里是为了让排除行为是**显式可见**的，不是偷偷跳过。）
VENDORED_PATHS = ["docs/research/readmes"]

failures: list[str] = []


def run(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout


def check(name: str, ok: bool, detail: str = "") -> None:
    """ok=True 表示**健康**。语义写死在这里，调用方不许自己反转。"""
    print(f"  {'✅' if ok else '❌'} {name}" + (f" —— {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    print(f"仓库: {ROOT}\n")

    # 1. 当前树
    print("1) 当前版本")
    tracked = set(run("ls-files").splitlines())
    hit = sorted(tracked & SECRET_FILES)
    check("当前树里没有凭证文件", not hit, ", ".join(hit))
    check(".env.example 模板在（应提交）", ".env.example" in tracked, "模板丢了？")

    # 2. 全历史（所有 ref）
    print("\n2) 全历史（所有分支 / 标签 / 悬空对象）")
    ever = set()
    for line in run("log", "--all", "--name-only", "--pretty=format:").splitlines():
        if line.strip():
            ever.add(line.strip())
    hit = sorted(ever & SECRET_FILES)
    check("历史里从未出现过凭证文件", not hit, ", ".join(hit))

    # 3. 全历史内容扫描
    print("\n3) 全历史内容扫描（每个快照的每个文件）")
    print(f"   （已排除第三方文档：{', '.join(VENDORED_PATHS)}）")
    revs = run("rev-list", "--all").split()
    excludes = [f":!{p}/*" for p in VENDORED_PATHS]
    for pattern, label in SECRET_PATTERNS:
        if not revs:
            print(f"  （仓库还没有提交，跳过「{label}」）")
            continue
        # -i：大小写不敏感。踩过的坑：写 API_KEY 的赋值会被小写正则漏过去。
        r = subprocess.run(
            ["git", "grep", "-ilE", pattern, *revs, "--", *excludes],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        found = [ln for ln in r.stdout.splitlines() if ln.strip()]
        check(f"未命中「{label}」", not found, f"{len(found)} 处")

    # 4. 本地凭证仍被忽略
    print("\n4) 忽略规则")
    if (ROOT / ".env").exists():
        ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT).returncode == 0
        check("本地 .env 被 git 忽略", ignored)
        check("本地 .env 未被跟踪", ".env" not in tracked)
    else:
        print("  （本地还没有 .env，跳过）")

    print()
    if failures:
        print(f"❌ 审计未通过：{len(failures)} 项")
        for f in failures:
            print(f"   · {f}")
        print("   若确认是历史泄漏：用 git filter-repo 重写历史，并**作废那个凭证**（改 key）。")
        return 1
    print("✅ 审计通过：当前树与全历史都没有凭证")
    return 0


if __name__ == "__main__":
    sys.exit(main())
