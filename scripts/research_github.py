#!/usr/bin/env python3
"""GitHub 同类项目调研 —— 检索 + 去重 + 排序 + 落盘。

用法: python3 scripts/research_github.py [--query "..." ...]
结果写到 docs/research/repos.json，控制台打印摘要表。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "research"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_QUERIES = [
    "desktop pet ai companion",
    "ai desktop assistant avatar",
    "桌宠 ai",
    "esp32 ai chatbot voice",
    "robot face servo expression",
    "ai desk robot raspberry pi",
    "ai tamagotchi virtual pet llm",
    "llm chatbot memory persona",
]

API = "https://api.github.com/search/repositories"
UA = {"Accept": "application/vnd.github+json", "User-Agent": "sammy-research"}


def search(query: str, per_page: int = 25) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": per_page,
        }
    )
    req = urllib.request.Request(f"{API}?{params}", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:200]
        print(f"  ⚠️  「{query}」 HTTP {e.code}: {body}")
        return []
    except Exception as e:
        print(f"  ⚠️  「{query}」 {type(e).__name__}: {e}")
        return []
    return data.get("items", [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", action="append", default=None)
    ap.add_argument("--min-stars", type=int, default=150)
    args = ap.parse_args()

    queries = args.query or DEFAULT_QUERIES
    repos: dict[str, dict] = {}

    for q in queries:
        items = search(q)
        print(f"  「{q}」→ {len(items)} 条")
        for it in items:
            full = it["full_name"]
            rec = {
                "full_name": full,
                "stars": it.get("stargazers_count", 0),
                "desc": (it.get("description") or "").strip(),
                "lang": it.get("language"),
                "pushed": (it.get("pushed_at") or "")[:10],
                "topics": it.get("topics", []),
                "url": it.get("html_url"),
                "matched": [q],
                "archived": it.get("archived", False),
            }
            if full in repos:
                repos[full]["matched"].append(q)
            else:
                repos[full] = rec
        time.sleep(2)  # 搜索限额 10 次/分钟，留点余量

    # 与上一次结果合并，多批检索累积
    existing = OUT_DIR / "repos.json"
    if existing.exists():
        try:
            prev = json.loads(existing.read_text(encoding="utf-8"))
            for rec in prev.get("repos", []):
                repos.setdefault(rec["full_name"], rec)
            print(f"  （并入上次 {len(prev.get('repos', []))} 条）")
        except Exception as e:
            print(f"  ⚠️  读取上次结果失败: {e}")

    ranked = sorted(repos.values(), key=lambda r: -r["stars"])
    kept = [r for r in ranked if r["stars"] >= args.min_stars]

    (OUT_DIR / "repos.json").write_text(
        json.dumps({"queries": queries, "repos": ranked}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n{'星数':>7}  {'语言':<12} {'最近提交':<11} 仓库 / 简介")
    print("─" * 110)
    for r in kept:
        stars = f"{r['stars']:,}"
        lang = (r["lang"] or "-")[:11]
        desc = r["desc"][:58]
        flag = " 📦归档" if r["archived"] else ""
        print(f"{stars:>7}  {lang:<12} {r['pushed']:<11} {r['full_name']}{flag}  —  {desc}")

    print(
        f"\n共 {len(repos)} 个去重仓库，其中 ≥{args.min_stars} 星 {len(kept)} 个 → docs/research/repos.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
