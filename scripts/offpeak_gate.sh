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
else
  echo "$out"
fi
