#!/usr/bin/env bash
# 定时任务的闸门 —— 只在非高峰唤醒 agent，高峰**整个跳过**。
#
# ⚠️ 语义是照源码实读的（cron/scheduler.py:2255 + cron/scheduler_prompt.py:20）：
#   · 脚本**没有输出**        → 调度器直接跳过 AI 调用（连跑都不跑）
#   · 最后一行 {"wakeAgent": false} → 同样跳过
#   · 其它任何输出            → 正常唤醒 agent，且这段文字会塞进 prompt 当上下文
# 第一版装反了（非高峰不输出、高峰才输出）：非高峰全被跳过（两天零提交 ✗），
# 高峰反而跑起来烧 token（✗）。教训：**语义要从源码和执行记录里读，别从文档猜。**
#
# 现在：空闲 → 输出一行说明（唤醒，并告诉它"可以干活"）
#       高峰 → 只输出闸门 JSON（跳过，不烧 token、不发消息）
#
# 用法：cron job 的 script 字段填 ~/.hermes/scripts/sammy_offpeak_gate.sh（4 行转发，指到这里）
set -uo pipefail
ROOT="/Volumes/Mac mini/Max agent/Sammy"
cd "$ROOT" || exit 0

out=""
rc=0
if [ -n "${SAMMY_OFFPEAK_AT:-}" ]; then
  # 测试钩子：伪装成指定时刻（自测用，正式跑不设这个变量）
  out=$(".venv/bin/python" scripts/offpeak.py --at "$SAMMY_OFFPEAK_AT" 2>/dev/null)
  rc=$?
else
  out=$(".venv/bin/python" scripts/offpeak.py 2>/dev/null)
  rc=$?
fi
if [ "$rc" -eq 1 ]; then
  # 高峰：最后一行必须是这个 JSON，否则调度器照样唤醒 agent（那就白烧钱了）
  echo '{"wakeAgent": false}'
  exit 0
fi

# ── 每日 token 预算（2026-10-14 加：Rowan「token 消耗有点多了」）──
# 口径：读 ~/.hermes/cron/usage_audit.jsonl，按**本地日**累加 cron 用量；
# 到上限就整块跳过（和高峰一样：零 token、零消息）。
# 为什么需要它：一个块 ≈ 15~25M tokens（上下文每做一次工具调用就要重发一遍），
# 光靠"只跑非高峰"挡不住总量。1 亿 ≈ 5 个块/天 —— 要调就改这一个数。
BUDGET=100000000
today=$("${ROOT}/.venv/bin/python" - <<'PY'
import datetime as dt
import json
import pathlib

p = pathlib.Path.home() / ".hermes" / "cron" / "usage_audit.jsonl"
today, tot = dt.datetime.now().date(), 0
try:
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        t = dt.datetime.fromisoformat(r["ts"].replace("Z", "+00:00")).astimezone().date()
        if t == today:
            tot += r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)
except Exception:  # noqa: BLE001 - 读不到就当没超（宁可干活，别因记账坏了停工）
    pass
print(tot)
PY
)
if [ "${today:-0}" -ge "$BUDGET" ]; then
  echo "今日 cron 用量已达预算（$((today / 1000000))M / $((BUDGET / 1000000))M tokens）—— 本块跳过"
  echo '{"wakeAgent": false}'
  exit 0
fi

echo "$out · 今日已用 $((today / 1000000))M / 上限 $((BUDGET / 1000000))M"
