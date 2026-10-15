#!/usr/bin/env bash
# ⚠️ 注意：**cron 真正执行的不是这个文件**，而是 ~/.hermes/scripts/sammy_offpeak_gate.sh。
# 原因：外置盘 /Volumes/Mac mini 被 macOS TCC 挡住，后台进程（cron）读不到 —— 见那份文件头
# Nex 2026-10-13 的记录。本文件是**记录 + 参考实现**（可读、可测、跟着项目走）；
# 改闸门逻辑要改两份，或者在 ~/.hermes 那份里改完再同步回来（2026-10-15 踩过这个坑：
# 预算检查只加在这边 → cron 那版没有 → 超预算照样跑）。
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

# ── 每日预算闸门（2026-10-14 加，同日改成按「钱」算）──
# 口径：读 ~/.hermes/state.db 的 session_model_usage（含缓存命中与官方价快照），
# 按**本地日**累加 cron 会话的 estimated_cost_usd；到上限就整块跳过（零 token 零消息）。
#
# 为什么按钱不按 token：一个块"看上"烧 15~25M tokens，但其中 96%+ 是缓存命中
# （$0.003/M，比未命中便宜 50 倍）—— 真正一个块 ≈ $0.15~0.25。按 token 设限会吓自己，
# 按钱设限才是 Rowan 真正关心的那个数。历史参考：跑满的一天 ≈ $2.1。
BUDGET_USD=1.00   # 每天封顶（$）；≈ 7 个块。要调就改这一个数
spent=$(/usr/bin/python3 - <<'PY'
import datetime as dt
import pathlib
import sqlite3

p = pathlib.Path.home() / ".hermes" / "state.db"
today = dt.datetime.now().date()
tot = 0.0
try:
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    for sid, cost, last in db.execute("SELECT session_id, estimated_cost_usd, last_seen FROM session_model_usage"):
        if not (sid or "").startswith("cron_"):
            continue
        if dt.datetime.fromtimestamp(last or 0).date() == today:
            tot += float(cost or 0)
    db.close()
except Exception:  # noqa: BLE001 - 读不到就当没超（宁可干活，别因记账坏了停工）
    pass
print(f"{tot:.2f}")
PY
)
if /usr/bin/python3 -c "import sys; sys.exit(0 if float('${spent:-0}') >= float('${BUDGET_USD}') else 1)"; then
  echo "今日 cron 花费已达预算（\$${spent} / \$${BUDGET_USD}）—— 本块跳过"
  echo '{"wakeAgent": false}'
  exit 0
fi

echo "$out · 今日已花 \$${spent} / 上限 \$${BUDGET_USD}"
