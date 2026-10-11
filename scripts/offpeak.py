#!/usr/bin/env python3
"""高峰 / 空闲时段判定 —— Rowan 2026-10-12 定的规矩：

> 空闲时段价格为高峰时段价格的一半。北京时间周一至周五（不含中国法定节假日）
> 9:00 - 12:00、14:00 - 18:00 为高峰时段；其余时段，包括周末及中国法定节假日
> 全天均为空闲时段。
>
> ——「以后在高峰时段以外 自主处理 Sammy 的事情」

所以这个脚本是**给自主推进把关用的**：开跑前先问一句"现在是高峰吗"，
是高峰就什么都别做（贵一倍），等下一个空闲窗口。

判定的两条纪律：

1. **按字面走**：高峰 = 周一至周五 且 不是法定节假日 且 落在 9-12 / 14-18。
   周末全天、节假日全天，一律空闲 —— 哪怕那天是"调休上班日"（调休日按周末算，
   因为规矩写的是"包括周末"，不写"除调休外"）。**有疑义时宁可按便宜的那头算。**
2. **不联网也能判**：节假日表在 `data/holidays-<年>.json` 里缓存；
   没缓存才去拉（holiday-cn 项目，走 ghfast 镜像）；拉不到就按周末规则判**并说明**，
   绝不假装知道自己不知道的事。

用法：
    python scripts/offpeak.py                 # 现在是不是高峰 + 下一个空闲窗口
    python scripts/offpeak.py --at 2026-10-12T10:30   # 指定时刻（推演/自测）
    python scripts/offpeak.py --quiet         # 只在"是高峰"时输出（给脚本用）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "data"
# 高峰时段（北京时间，含头不含尾）
PEAK_RANGES = ((9, 0, 12, 0), (14, 0, 18, 0))
# 节假日表：holiday-cn（官方口径，含调休）；直连拉不动时走 ghfast
HOLIDAY_URL = "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json"
MIRROR = "https://ghfast.top/"


def _fetch_year(year: int) -> dict | None:
    """拉某一年的节假日表；失败返回 None（绝不抛）。"""
    for url in (HOLIDAY_URL.format(year=year), MIRROR + HOLIDAY_URL.format(year=year)):
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            off = sorted(d["date"] for d in raw["days"] if d["isOffDay"])
            return {"year": year, "off": off, "source": url}
        except Exception:
            continue
    return None


def load_calendar(year: int, *, allow_fetch: bool = True) -> dict:
    """返回 {off: {日期}, year, known: bool}。优先读缓存，读不到才联网。"""
    path = CACHE / f"holidays-{year}.json"
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {"off": set(raw.get("off", [])), "year": year, "known": True, "source": "cache"}
        except Exception:
            pass
    if allow_fetch:
        raw = _fetch_year(year)
        if raw is not None:
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
            return {"off": set(raw["off"]), "year": year, "known": True, "source": raw["source"]}
    return {"off": set(), "year": year, "known": False, "source": ""}


def is_peak(when: dt.datetime, cal: dict) -> tuple[bool, str]:
    """(是不是高峰, 为什么)。日历不全时按周末规则判，理由里说清楚。"""
    d = when.date()
    iso = d.isoformat()
    tail = "" if cal.get("known", True) else "（节假日表没拿到，按周末规则判的）"
    if iso in cal.get("off", set()):
        return False, f"法定节假日（{iso} 放假）"
    if d.weekday() >= 5:
        return False, f"周末{tail}"
    for h0, m0, h1, m1 in PEAK_RANGES:
        if (h0, m0) <= (when.hour, when.minute) < (h1, m1):
            return True, f"高峰时段（{h0}:00-{h1}:00）"
    return False, f"非高峰（工作日午休/早晚）{tail}"


def next_offpeak(start: dt.datetime, cal: dict, *, limit_days: int = 8) -> dt.datetime:
    """下一个空闲时刻（整分）。高峰里就找下一个窗口起点，空闲就返回当下。"""
    t = start.replace(second=0, microsecond=0)
    for _ in range(limit_days * 24 * 60):
        if not is_peak(t, cal)[0]:
            return t
        t += dt.timedelta(minutes=1)
    return t  # 理论上到不了这里


def main() -> int:
    ap = argparse.ArgumentParser(description="查现在是不是高峰时段")
    ap.add_argument("--at", help="指定时刻，ISO 格式（如 2026-10-12T10:30）")
    ap.add_argument("--quiet", action="store_true", help="只在是高峰时输出一行")
    ap.add_argument("--no-fetch", action="store_true", help="不联网，只用缓存")
    args = ap.parse_args()

    when = dt.datetime.fromisoformat(args.at) if args.at else dt.datetime.now()
    cal = load_calendar(when.year, allow_fetch=not args.no_fetch)
    peak, why = is_peak(when, cal)
    if peak:
        nxt = next_offpeak(when, cal)
        print(f"PEAK · {why} · 现在别干活，{nxt:%m-%d %H:%M} 起是空闲（还有 {nxt - when}）")
        return 1
    if not args.quiet:
        src = (
            "缓存" if cal["source"] == "cache" else ("联网" if cal["known"] else "无表（按周末判）")
        )
        print(f"OFF-PEAK · {why} · 可以干活 · 节假日表：{src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
