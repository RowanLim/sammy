#!/usr/bin/env python
"""提交前扫暂存区 —— 比全历史审计快，卡在"还没提交"的那一刻。

复用 audit_repo.py 里的特征表，避免两处规则漂移。
只扫新增的行（`+` 开头），所以不会因为历史遗留问题反复报警。
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from audit_repo import SECRET_FILES, SECRET_PATTERNS

# .env 精确文件名；其余是"临时/本地"变体
BLOCKED_NAMES = SECRET_FILES


def to_python_re(pattern: str) -> str:
    """把 POSIX ERE 的字符类翻成 Python re 能懂的写法。

    ⚠️ 踩过的坑（第二次栽在同一类问题上）：
    `[[:space:]]` 是 **POSIX/git grep** 的语法，Python 的 `re` **不支持** ——
    它会把 `[[:space:]]` 当成"字符集合 [ : s p a c e ]"这种荒谬的东西（并抛
    FutureWarning: Possible nested set），规则于是静默失效。
    两套引擎语法不同，就不能假装它们是同一套。
    """
    return pattern.replace("[[:space:]]", r"\s")


def main() -> int:
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"], capture_output=True, text=True
    )
    staged = [n for n in r.stdout.split("\0") if n]

    bad = [n for n in staged if pathlib.PurePath(n).name in BLOCKED_NAMES]
    if bad:
        print("❌ 禁止提交这些凭证文件：")
        for n in bad:
            print(f"   · {n}")
        return 1

    diff = subprocess.run(["git", "diff", "--cached", "-U0"], capture_output=True, text=True).stdout
    added = [ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]

    hits: list[tuple[str, str]] = []
    for line in added:
        for pattern, label in SECRET_PATTERNS:
            if re.search(to_python_re(pattern), line, re.IGNORECASE):
                hits.append((label, line.strip()[:110]))
                break

    if hits:
        print("❌ 暂存的新增内容里疑似有凭证：")
        for label, line in hits:
            print(f"   · [{label}] {line}")
        print("   确认是误报的话，把它加进 scripts/audit_repo.py 的排除或用环境变量。")
        return 1

    print(f"✅ 暂存区干净（检查了 {len(staged)} 个文件 / {len(added)} 行新增）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
