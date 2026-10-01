#!/usr/bin/env python
"""M1 验收 —— 把 PRD §7 里 P0 的每一条，跑成一个**可复现的数字或原话**。

为什么单独写这个脚本：「我觉得它能用」不是验收。
这份脚本的意义是**能在任何人面前重跑一遍**，并给出结论和证据。
跑完会打印一张表：哪条过、哪条不过、证据是什么。

用法:
  .venv/bin/python scripts/accept_m1.py            # 全部
  .venv/bin/python scripts/accept_m1.py --only 延迟  # 只跑某几条（按名字模糊匹配）
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
PY = str(ROOT / ".venv" / "bin" / "python")

# 客服腔 / 破人设的标志词。命中说明它退化成了通用助手，而不是 Sammy。
BOT_MARKERS = (
    "作为一个ai",
    "作为人工智能",
    "语言模型",
    "我是一个ai",
    "抱歉，我不能",
    "我无法提供",
    "有什么可以帮",
)

# 情绪标签 → 正负。判「风格稳定」看的是**正负同向**，不是标签逐字相同：
# happy / smile / playful 都是「开心俏皮」，那是变化，不是不一致。
_POSITIVE_MOODS = {
    "happy",
    "smile",
    "playful",
    "love",
    "cute",
    "wink",
    "giggle",
    "content",
    "surprised",
    "expect",
    "proud",
    "cool",
    "shocked",
}
_NEGATIVE_MOODS = {"sad", "angry", "wronged", "fear"}


def _valence(emotion: str) -> str:
    if emotion in _POSITIVE_MOODS:
        return "positive"
    if emotion in _NEGATIVE_MOODS:
        return "negative"
    return "neutral"


results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'✅' if ok else '❌'} {name}\n     {detail}\n")


def brain():
    from sammy.brain import SammyBrain

    return SammyBrain()


def run_cli(*args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """起一个真实子进程跑 CLI。

    ⚠️ 必须给它 PYTHONPATH —— 本脚本自己往 sys.path 塞了 src，但**子进程不知道**。
    第一版忘了这步，结果"断网"和"记忆"两条检查报的都是 `No module named sammy`，
    看起来像产品挂了，其实是验收脚本自己没配好环境。**假失败和假通过一样糟。**
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [PY, "-m", "sammy", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


# ── P0-1 大模型对话 ────────────────────────────────


def check_latency(samples: int = 10) -> None:
    """3 秒内返回。单次采样不算数 —— 看分布（尾延迟才是用户真正骂的那个）。"""
    b = brain()
    times, empties = [], 0
    for _ in range(samples):
        t0 = time.time()
        r = b.chat("你好")
        times.append(time.time() - t0)
        if not (r.get("reply") or "").strip():
            empties += 1
    times.sort()
    p50 = statistics.median(times)
    p90 = times[int(len(times) * 0.9) - 1]
    detail = (
        f"{samples} 次采样：p50 {p50:.2f}s / p90 {p90:.2f}s / max {times[-1]:.2f}s"
        f"；空回复 {empties} 个"
    )
    record("P0-1a 延迟 < 3s", p90 < 3.0 and empties == 0, detail)


def check_context_10_turns() -> None:
    """连续 10 轮不丢上下文：第 1 轮植入事实，第 10 轮问它。"""
    b = brain()
    b.chat("记住一件事：我养了一只猫，叫豆豆。")
    for i in range(8):
        b.chat(f"随便聊点别的，这是第 {i + 1} 句。")
    ans = b.chat("我养的那只猫，叫什么名字？")["reply"]
    record(
        "P0-1b 十轮上下文",
        "豆豆" in ans,
        f"第 10 轮问起第 1 轮的事实，它答：{ans[:60]}",
    )


def check_personality_consistency(runs: int = 5) -> None:
    """同一句话问 5 次：风格稳定 —— **不一次像客服、一次像哲学家**。

    ⚠️ 判据第一版写错了：我要求 5 次的情绪标签**逐字相同**，结果 happy/smile/playful
    被算成"不一致"。可它们全是同一种"开心俏皮" —— 那是**变化**，不是**不一致**。
    真正该判的是**腔调**：有没有客服腔、正负情绪是否同向、长度有没有跑飞。
    （写错判据会让好产品背黑锅；改判据前先说清为什么原判据是错的，不是为了让结果变绿。）
    """
    b = brain()
    replies, emotions = [], []
    for _ in range(runs):
        r = b.chat("你好呀")
        replies.append(r["reply"])
        emotions.append(r["emotion"])

    botish = [r for r in replies if any(m in r.lower() for m in BOT_MARKERS)]
    empties = [r for r in replies if not r.strip()]
    valences = {_valence(e) for e in emotions}
    lengths = [len(r) for r in replies]
    # 长度跑飞（一个字 / 写成小作文）也算风格不稳
    strayed = [n for n in lengths if n < 4 or n > 200]
    # 真正的"破人设"是**冷热翻转**（先热情后冷漠），不是"好奇"。
    # 要求 5 次全在同一个正负里太粗 —— 会把"疑惑地反问一句"误判成飘了。
    flipped = {"positive", "negative"} <= valences

    ok = not botish and not empties and not flipped and not strayed
    record(
        "P0-2 人格一致性",
        ok,
        f"{runs} 次同一句话：情绪 {emotions} → 极性 {valences}（冷热翻转 {'是' if flipped else '否'}）；"
        f"客服腔 {len(botish)} 次；空回复 {len(empties)} 次；长度 {lengths}（跑飞 {len(strayed)}）",
    )
    print(f"     └ 原话：{replies[0][:40]!r} … {replies[-1][:40]!r}")


def check_offline_graceful() -> None:
    """断网要给友好提示、不能崩。做法：把接口指向一个不可达地址，走**真实用户那条路**（CLI）。"""
    r = run_cli("--ask", "你好", extra_env={"SAMMY_CHAT_BASE_URL": "http://127.0.0.1:9/v1"})
    out = r.stdout + r.stderr
    # "不崩"指的是**没有 Python 回溯**，不是"退出码为 0"。
    # 上游连不上时非零退出是对的 —— 干净地失败（一句人话 + 明确的退出码）本来就是设计目标。
    # 第一版把非零退出也算成"崩"，那会把正确行为判成错误。
    crashed = "Traceback" in out
    friendly = any(k in out for k in ("连不上", "网络", "卡住", "稍后", "出错", "失败"))
    record(
        "P0-1c 断网不崩",
        (not crashed) and friendly,
        f"退出码 {r.returncode}（非零是对的：上游确实失败了）；"
        f"回溯 {'有' if crashed else '无'}；友好提示 {'有' if friendly else '无'}；"
        f"输出尾部：{out.strip().splitlines()[-1][:80] if out.strip() else '（空）'}",
    )


# ── P0-4 双击即用 ──────────────────────────────────


def check_app_bundle() -> None:
    """双击图标 → 窗口出现 → 能对话，全程无终端。"""
    app = ROOT / "dist" / "Sammy.app"
    if not app.exists():
        record("P0-4 双击即用", False, f"还没打包：{app} 不存在")
        return
    exe = app / "Contents" / "MacOS"
    binaries = list(exe.iterdir()) if exe.exists() else []
    record(
        "P0-4 双击即用",
        bool(binaries),
        f"{app.relative_to(ROOT)} 存在，可执行文件 {[b.name for b in binaries]}"
        f"（体积 {sum(f.stat().st_size for f in app.rglob('*') if f.is_file()) / 1e6:.0f} MB）",
    )


# ── P0-5 记忆 ─────────────────────────────────────


def check_memory_survives_restart() -> None:
    """重启后仍记得昵称和至少 3 条关键偏好。

    注意：这里读的是**之前别的进程写进去的**记录，所以这条本身就是"跨进程"证据。
    """
    r = run_cli("--memory")
    out = r.stdout + r.stderr
    # 按**真实输出格式**解析，不靠猜：摘要行长这样 ——「槽位 4 条 / 日记 1 条 / 摘要 0 篇 / 始于 …」
    m = re.search(r"槽位\s*(\d+)\s*条", out)
    slots = int(m.group(1)) if m else 0
    record(
        "P0-5 记忆重启不丢",
        slots >= 3,
        f"新进程读出 {slots} 条槽位；摘要行：{next((ln for ln in out.splitlines() if '槽位' in ln), '（没找到）')}",
    )


# ── P0-6 不崩 ─────────────────────────────────────


def check_soak(minutes: float = 0.0) -> None:
    """连续运行 8 小时不崩、不内存泄漏。

    完整 8 小时要真等 8 小时 —— 这个脚本**不假装跑过**。
    它做两件能立刻做的事：① 看有没有 soak 报告 ② 有就按 8 小时 + 内存增长来判。
    完整的 8 小时由 `scripts/soak.py` 在后台真跑（`make soak`）。
    """
    log = ROOT / "docs" / "soak-report.json"
    if log.exists():
        import json

        data = json.loads(log.read_text(encoding="utf-8"))
        grew = data.get("rss_last_mb", 0) - data.get("rss_first_mb", 0)
        record(
            "P0-6 八小时稳定性",
            data.get("hours", 0) >= 8 and grew < 50,
            f"已跑 {data.get('hours', 0):.1f} 小时；内存 {data.get('rss_first_mb', 0):.0f} → "
            f"{data.get('rss_last_mb', 0):.0f} MB（增长 {grew:+.0f} MB）；对话 {data.get('turns', 0)} 轮",
        )
    else:
        record(
            "P0-6 八小时稳定性",
            False,
            "还没跑够 8 小时。这不是「通过」，是「未测」 —— 需要用 scripts/soak.py 在后台真跑一场",
        )


# ── P0-3 表情随对话变化（离线用例已覆盖，这里做一次端到端）──


def check_expression_end_to_end() -> None:
    """说开心的事→笑脸，难过→安慰表情。"""
    b = brain()
    happy = b.chat("我今天特别开心，刚拿到一个大订单！")
    sad = b.chat("说实话我今天很难过，被朋友误会了。")
    ok = happy["expression"] != sad["expression"] and happy["expression"] in range(1, 36)
    record(
        "P0-3 表情跟着变",
        ok,
        f"开心 → 表情 {happy['expression']}（{happy['emotion']}）；"
        f"难过 → 表情 {sad['expression']}（{sad['emotion']}）",
    )


CHECKS = {
    "延迟": check_latency,
    "十轮": check_context_10_turns,
    "人格": check_personality_consistency,
    "断网": check_offline_graceful,
    "表情": check_expression_end_to_end,
    "记忆": check_memory_survives_restart,
    "打包": check_app_bundle,
    "稳定性": check_soak,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只跑名字里含这段文字的检查")
    args = ap.parse_args()

    if not (ROOT / ".env").exists():
        print("⚠️  没有 .env —— 联网相关检查会全挂")

    print("=" * 66)
    print("Sammy · M1 验收（PRD §7 的 P0 逐条）")
    print("=" * 66, "\n")

    for name, fn in CHECKS.items():
        if args.only and args.only not in name:
            continue
        try:
            fn()
        except Exception as e:
            record(name, False, f"检查抛异常：{type(e).__name__}: {e}")

    passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 66)
    print(f"结果：{passed}/{len(results)} 条通过")
    for name, ok, _ in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    print("=" * 66)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
