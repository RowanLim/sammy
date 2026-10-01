#!/bin/bash
# 把 Sammy 装到 Linux 那台（Nex）上跑 —— 这也正是树莓派移植（M4）的预演。
#
# Rowan 打算把小监视器插在 Linux 上（Mac 没口了）。Nex 实测：GNOME + Xorg 在 :1
# 上跑着、PySide6 可装、speech-dispatcher 是 active（所以它在那台上也能说话）。
#
# ⚠️⚠️ 这个脚本会**改动那台机器**：建目录、建 venv、装 PySide6（几百 MB）。
#     所以**默认只演练（dry-run）**，必须显式加 --yes 才真的动手。
#
# 用法:
#   scripts/port_to_linux.sh                 # 演练，什么都不改
#   scripts/port_to_linux.sh --yes           # 真装（代码 + 环境 + 记忆库）
#   scripts/port_to_linux.sh --yes --with-env  # 连 .env 一起带过去（凭证会多一份！）
#
# 默认**不带** .env：凭证多复制一份就多一个要管的地方。
# 需要新机器能聊天时，两个选择：① --with-env；② 在 DeepSeek 后台另建一把 key（推荐）。
set -uo pipefail

NEX="${NEX:-rowan@192.168.110.177}"
DEST="${DEST:-/home/rowan/sammy}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

DO_IT=0
WITH_ENV=0
for a in "$@"; do
    case "$a" in
        --yes) DO_IT=1 ;;
        --with-env) WITH_ENV=1 ;;
        *) echo "未知参数: $a"; exit 2 ;;
    esac
done

say() { printf '%s\n' "$*"; }
run() {
    if [ "$DO_IT" -eq 1 ]; then
        say "  \$ $*"
        "$@" || { say "  ❌ 上面这条失败了，停下"; exit 1; }
    else
        say "  [演练] $*"
    fi
}

say "目标机器：$NEX"
say "安装目录：$DEST"
say "来源：$HERE"
[ "$DO_IT" -eq 1 ] || say "（演练模式：不会改任何东西。要真装请加 --yes）"
say

say "── 1/5 先确认那台活着 ──"
run ssh -o BatchMode=yes -o ConnectTimeout=15 "$NEX" 'uname -sm; python3 --version; echo "DISPLAY=${DISPLAY:-（无）}"'

say
say "── 2/5 建目录 + 同步代码（不带本机专属产物）──"
# 刻意排除：.venv/dist/build（本机架构的产物）、data/backups（私人数据，单独决定带不带）
# .git 也排除：那台上要版本管理的话应该自己 clone，不该拷一份历史过去
run ssh -o BatchMode=yes "$NEX" "mkdir -p '$DEST'"
run rsync -a --delete \
    --exclude '.venv' --exclude 'dist' --exclude 'build' \
    --exclude 'data' --exclude 'backups' --exclude '.tmp' \
    --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    "$HERE/" "$NEX:$DEST/"

say
say "── 3/5 建虚拟环境 + 装依赖（PySide6 几百 MB）──"
run ssh -o BatchMode=yes "$NEX" \
    "cd '$DEST' && python3 -m venv .venv && .venv/bin/pip -q install -U pip && .venv/bin/pip -q install -r requirements.txt"

say
say "── 4/5 数据 ──"
# 记忆库一定要带：不然它到了新机器上是个失忆的陌生人
run ssh -o BatchMode=yes "$NEX" "mkdir -p '$DEST/data'"
run rsync -a "$HERE/data/sammy.db" "$HERE/data/drives.json" "$NEX:$DEST/data/" 2>/dev/null || true
if [ "$WITH_ENV" -eq 1 ]; then
    say "  （--with-env：把 .env 也带过去 —— 凭证就多一份了，记得两处都能吊销）"
    run rsync -a "$HERE/data/.env" "$NEX:$DEST/data/"
    run ssh -o BatchMode=yes "$NEX" "chmod 600 '$DEST/data/.env'"
else
    say "  跳过 .env（默认不带凭证）"
    say "  → 想让那台也能聊天：要么加 --with-env，要么（推荐）去 DeepSeek 后台另建一把 key，"
    say "     然后在那边跑： cd $DEST && .venv/bin/python scripts/set_key.py"
fi

say
say "── 5/5 冒烟测试：在 Linux 上离屏渲染一张脸 ──"
# 这一步的意义：证明「Qt 装好了 + 资源在包里能被读到」——
# 不然等屏幕插上去才发现是白屏，就白折腾一趟
run ssh -o BatchMode=yes "$NEX" \
    "cd '$DEST' && PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python -m sammy --snapshot /tmp/sammy-port-check.png && ls -l /tmp/sammy-port-check.png"

say
if [ "$DO_IT" -eq 1 ]; then
    say "✅ 装好了。等小屏插上、Nex 重启过（nvidia 驱动版本不一致，重启才生效）之后："
    say "   ssh $NEX"
    say "   cd $DEST && DISPLAY=:1 ./run.sh --screens      # 看新屏是第几号"
    say "   cd $DEST && DISPLAY=:1 ./run.sh --kiosk --display <号>"
else
    say "演练结束 —— 上面就是要执行的全部动作。确认没问题就加 --yes 重跑。"
fi
