#!/usr/bin/env python
"""P0-6 八小时稳定性压测 —— **真跑，不假装**。

PRD 的验收标准是"连续运行 8 小时不崩、不内存泄漏到卡死"。
这个脚本没有捷径：要么真等 8 小时，要么就承认没测。
所以它的设计目标是**可以安心跑一整夜**：

- 每一轮都重写报告文件 —— 中途被 kill、断电、重启，进度都不会丢
- 只调 brain.chat，**不写记忆库** —— 压测不该往你的真实记忆里灌垃圾
- 顺带记录：空回复、延迟漂移、异常。内存只看趋势（真泄漏会一直涨，不泄漏会走平）

用法:
  .venv/bin/python scripts/soak.py                  # 默认 8 小时
  .venv/bin/python scripts/soak.py --hours 0.2      # 12 分钟（先验证脚本本身）
  .venv/bin/python scripts/soak.py --interval 20    # 每轮间隔 20 秒
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
REPORT = ROOT / "docs" / "soak-report.json"

PROMPTS = [
    "你好",
    "今天过得怎么样",
    "给我讲个冷知识",
    "我有点累了",
    "推荐一首歌",
    "现在几点了",
    "帮我算一下 17 乘以 23",
    "你觉得广州的天气怎么样",
]


def rss_mb() -> float:
    """当前进程的常驻内存。用 ps 而不是 psutil —— 不想为一次压测加依赖。"""
    import os

    r = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(os.getpid())],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return int(r.stdout.strip()) / 1024.0  # ps 给的是 KB
    except ValueError:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--interval", type=float, default=30.0, help="每轮之间歇多少秒")
    ap.add_argument(
        "--report", default=str(REPORT), help="报告写到哪（默认 docs/soak-report.json）"
    )
    args = ap.parse_args()
    report_path = Path(args.report)

    from sammy.brain import SammyBrain

    print(f"压测开始：目标 {args.hours} 小时，每轮间隔 {args.interval}s")
    brain = SammyBrain()
    started = time.time()
    rss_first = rss_mb()
    latencies: list[float] = []
    turns = crashes = empties = 0
    report: dict = {}

    def save(last_error: str = "") -> None:
        report.update(
            hours=(time.time() - started) / 3600.0,
            turns=turns,
            crashes=crashes,
            empties=empties,
            rss_first_mb=round(rss_first, 1),
            rss_last_mb=round(rss_mb(), 1),
            latency_p50=round(statistics.median(latencies), 3) if latencies else 0,
            latency_p90=(
                round(sorted(latencies)[int(len(latencies) * 0.9) - 1], 3) if latencies else 0
            ),
            latency_max=round(max(latencies), 3) if latencies else 0,
            last_error=last_error,
            updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    while (time.time() - started) / 3600.0 < args.hours:
        turns += 1
        last_error = ""
        try:
            t0 = time.time()
            r = brain.chat(random.choice(PROMPTS))
            latencies.append(time.time() - t0)
            if not (r.get("reply") or "").strip():
                empties += 1
        except Exception as e:
            crashes += 1
            last_error = f"{type(e).__name__}: {e}"
        # **每轮都写报告** —— 文件很小，而"进度随时看得见"比省这点 IO 重要得多。
        # （原来 10 轮才写一次，于是刚启动那几分钟报告根本不存在，
        #   看上去就像"没在跑" —— 我自己都被骗过一次，还以为进程挂了。）
        save(last_error)
        if turns % 10 == 0 or crashes:
            h = (time.time() - started) / 3600.0
            print(
                f"  {h:5.2f}h | {turns:5d} 轮 | 崩 {crashes} | 空 {empties} | "
                f"内存 {rss_first:.0f}→{rss_mb():.0f} MB | "
                f"p50 {report.get('latency_p50', 0):.2f}s"
            )
        time.sleep(args.interval)

    save()
    print(f"\n压测结束。报告：{REPORT}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if crashes == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
