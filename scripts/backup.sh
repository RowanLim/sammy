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

# ── 记忆库推一份到 Nex（异地副本，Rowan 批准）─────────────
# 为什么必须推：记忆库是**不可再生的**（聊天一天天累积出来的），
# 而按隔离要求，备份和源现在在**同一块盘**上 —— 这块盘坏了就永远没了。
#
# 推的是 backup.py 用 SQLite backup API 取的**一致性快照**，不是直接拷正在写的库
# （直接拷可能拷到半个事务）。
#
# 明确不推 .env：凭证不该再复制到第三处；key 丢了去 DeepSeek 后台重建即可。
NEX="rowan@192.168.110.177"
NEX_DIR="sammy-memory"
SNAP="$DEST/$(date '+%Y-%m-%d')/sammy-memory.db"
if [ -f "$SNAP" ]; then
    if ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
            "$NEX" "mkdir -p ~/$NEX_DIR" 2>/dev/null \
        && scp -q -o BatchMode=yes -o ConnectTimeout=20 \
            "$SNAP" "$NEX:~/$NEX_DIR/sammy-$(date '+%Y-%m-%d').db" 2>/dev/null; then
        echo "$stamp  memory -> nex ($NEX_DIR/sammy-$(date '+%Y-%m-%d').db)" >> "$LOG"
        # 留 30 天滚动
        ssh -o BatchMode=yes -o ConnectTimeout=10 "$NEX" \
            "find ~/$NEX_DIR -name 'sammy-*.db' -mtime +30 -delete" 2>/dev/null || true
    else
        echo "$stamp  memory 推送失败（Nex 离线？）—— 本地备份不受影响" >> "$LOG"
    fi
fi

exit 0
