#!/usr/bin/env bash
# 定时任务的闸门：现在是高峰就喊一声（stdout 会被塞进 agent 的上下文），
# 空闲就什么都不输出（agent 照常干活）。
#
# 为什么要有它：cron 表达式管不了法定节假日，也容易和"含头不含尾"的边界打架。
# 与其把时段规则抄两遍，不如每块开跑前问一句 scripts/offpeak.py（单一来源）。
#
# 用法（在 cron job 的 script 字段里）: /Volumes/Mac mini/Max agent/Sammy/scripts/offpeak_gate.sh
set -uo pipefail
ROOT="/Volumes/Mac mini/Max agent/Sammy"
cd "$ROOT" || exit 0
# --quiet：空闲时一声不吭；高峰时打印 PEAK 一行并以 1 退出（退出码不重要，stdout 才重要）
".venv/bin/python" scripts/offpeak.py --quiet || true
