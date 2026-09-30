#!/usr/bin/env python3
"""拉取候选项目的 README（走 raw.githubusercontent，不占 API 限额）。

用法: python3 scripts/fetch_readmes.py
落到 docs/research/readmes/<owner>__<repo>.md
"""

from __future__ import annotations

import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "research" / "readmes"
OUT.mkdir(parents=True, exist_ok=True)

REPOS = [
    "78/xiaozhi-esp32",
    "xinnan-tech/xiaozhi-esp32-server",
    "huangjunsen0406/py-xiaozhi",
    "stack-chan/stack-chan",
    "DasterProkio/awesome-ai-companion",
    "kiyotakali/Miru",
    "BDFFZI/Alife",
    "PC2005-cloud/dsh-pet",
    "LYiHub/pub-local-jarvis",
    "legeling/awesome-codex-pet",
    "SlimeBoyOwO/LingChat",
    "Zao-chen/ZcChat",
]

BRANCHES = ["main", "master"]
NAMES = ["README.md", "README_CN.md", "README.zh-CN.md", "readme.md", "README.markdown"]


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "sammy-research"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def main() -> int:
    for full in REPOS:
        got = None
        used = ""
        for br in BRANCHES:
            for name in NAMES:
                url = f"https://raw.githubusercontent.com/{full}/{br}/{name}"
                txt = fetch(url)
                if txt and len(txt) > 200:
                    got, used = txt, f"{br}/{name}"
                    break
            if got:
                break

        safe = full.replace("/", "__")
        if not got:
            print(f"  ❌ {full}  —— 没拿到 README")
            continue
        (OUT / f"{safe}.md").write_text(got, encoding="utf-8")
        head = " ".join(got.replace("\n", " ").split())[:180]
        print(f"  ✅ {full}  [{used}]  {len(got):,} 字")
        print(f"       {head}")
        print()

    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
