#!/bin/bash
# Sammy 每日备份 —— 成功静默（只写日志），失败才出声。
# 由 Hermes 的定时任务调用：no_agent 模式，stdout 非空才会发消息给 Rowan。
#
# **一切都在项目文件夹里**（Rowan 的隔离要求）：脚本、产物、日志全在 <项目>/backups/。
# 项目路径从脚本位置自己推算 —— 不写死，将来整个文件夹搬走也不会坏。
set -uo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$PROJECT/backups"
LOG="$DEST/backup.log"
mkdir -p "$DEST"

stamp="$(date '+%Y-%m-%d %H:%M:%S')"

if [ ! -d "$PROJECT/scripts" ]; then
    echo "⚠️ Sammy 每日备份失败：找不到项目（$PROJECT）"
    echo "$stamp  失败: 项目目录不存在" >> "$LOG" 2>/dev/null
    exit 1
fi

out="$(cd "$PROJECT" && python3 scripts/backup.py 2>&1)"
code=$?

if [ $code -ne 0 ] || ! printf '%s' "$out" | grep -q "备份完成"; then
    echo "⚠️ Sammy 每日备份异常（exit $code）"
    printf '%s\n' "$out" | tail -12
    echo "$stamp  失败: exit=$code" >> "$LOG"
    exit 1
fi

# 成功：写日志，不打扰
size="$(du -sh "$DEST/$(date '+%Y-%m-%d')" 2>/dev/null | cut -f1)"
head="$(cd "$PROJECT" && git rev-parse --short HEAD 2>/dev/null)"
echo "$stamp  ok  $(date '+%Y-%m-%d')  HEAD=$head  大小=$size" >> "$LOG"

# 顺手推到内网 Gitea（Nex 那台）—— 这是**唯一的异地副本**（只有代码，没有记忆库）。
# Nex 离线不该影响本地备份，所以失败只记日志、不报错。
if (cd "$PROJECT" && git remote get-url origin >/dev/null 2>&1); then
    if (cd "$PROJECT" && GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15" \
            git push -q origin main --tags 2>/dev/null); then
        echo "$stamp  pushed -> origin ($head)" >> "$LOG"
    else
        echo "$stamp  push 失败（Nex 离线？）—— 本地备份已完成，不算失败" >> "$LOG"
    fi
fi

exit 0
