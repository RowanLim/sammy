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
# ⚠️ 必须钉死用系统 python3：Nex 的 PATH 上那个 `python3` 是 **Hermes 自己的 3.11 venv**，
# 拿它去建 venv 会建歪（而且它的 pip 装的东西全落在 Hermes 的环境里）。
PYTHON="${PYTHON:-/usr/bin/python3}"

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
run ssh -o BatchMode=yes "$NEX" 'uname -sm; /usr/bin/python3 --version; echo "DISPLAY=${DISPLAY:-（无）}"'

say
say "── 2/5 建目录 + 同步代码（不带本机专属产物）──"
# 刻意排除：.venv/dist/build（本机架构的产物）、data/backups（私人数据，单独决定带不带）
# **vendor 也要排除**：那是目标机上生成的（解 .deb 出来的原生库），
#   不排除的话 --delete 会把它当"多余文件"删掉，每跑一次就重下重解一遍。
# .git 也排除：那台上要版本管理的话应该自己 clone，不该拷一份历史过去
run ssh -o BatchMode=yes "$NEX" "mkdir -p '$DEST'"
run rsync -a --delete \
    --exclude '.venv' --exclude 'dist' --exclude 'build' \
    --exclude 'data' --exclude 'backups' --exclude '.tmp' \
    --exclude 'vendor' \
    --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    "$HERE/" "$NEX:$DEST/"

say
say "── 3/5 建虚拟环境 + 装依赖（PySide6 几百 MB）──"
# Ubuntu 的 ensurepip 往往是单独的 python3.x-venv 包，没装就建不出 venv（报 ensurepip is not available）。
# **不为了这个去要 sudo 装系统包** —— 退回 --without-pip + 官方 get-pip.py，
# 让一切落在项目自己的目录里（也符合"别在他机器别处留东西"的约定）。
# 已建好的 .venv 不重建：重跑脚本不该等于重装几百 MB。
VENV_SETUP="if [ -x .venv/bin/python ]; then echo '  .venv 已存在 → 跳过（要重建先 rm -rf .venv）'; else rm -rf .venv; ( '$PYTHON' -m venv .venv 2>/dev/null || { echo '  ensurepip 缺失 → 退回 --without-pip + get-pip.py（不需要 sudo）'; '$PYTHON' -m venv --without-pip .venv && curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python -q; } ); fi"
run ssh -o BatchMode=yes "$NEX" \
    "cd '$DEST' && $VENV_SETUP && .venv/bin/pip -q install -r requirements.txt && echo -n '  venv python: ' && .venv/bin/python --version"

say
say "── 3.5/5 补齐 Qt 在 X11 上要的原生库（不用 sudo）──"
# 实测坑：Qt 6.5+ 载入 xcb 平台插件需要 libxcb-cursor0，Ubuntu 精简装没有 →
# 「Could not load the Qt platform plugin "xcb"」直接核心转储。
# 装系统包要 sudo，所以改成：把 .deb 下下来解到项目自己的 vendor/lib，
# 用 LD_LIBRARY_PATH 指过去（run.sh 会自己认这个目录）。零 sudo、删掉 vendor/ 就干净。
NATIVE_LIB="$DEST/vendor/lib/usr/lib/x86_64-linux-gnu"
run ssh -o BatchMode=yes "$NEX" \
    "cd '$DEST' && if [ -f '$NATIVE_LIB/libxcb-cursor.so.0' ]; then echo '  libxcb-cursor 已在 vendor/ 里 → 跳过'; else mkdir -p vendor/deb vendor/lib && cd vendor/deb && apt-get download libxcb-cursor0 >/dev/null 2>&1 && dpkg-deb -x libxcb-cursor0*.deb ../lib && echo '  已解到 vendor/lib'; fi"
# 验一遍：libqxcb.so 不该再有 "not found"（补一个库就以为完事，是最容易翻车的）
run ssh -o BatchMode=yes "$NEX" \
    "cd '$DEST' && n=\$(LD_LIBRARY_PATH='$NATIVE_LIB' ldd .venv/lib/python3*/site-packages/PySide6/Qt/plugins/platforms/libqxcb.so 2>&1 | grep -c 'not found'); if [ \"\$n\" -gt 0 ]; then echo \"  ❌ libqxcb.so 还缺 \$n 个库，xcb 起不来\"; exit 1; else echo '  ✅ libqxcb.so 依赖齐了'; fi"

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

say "  ── 再试真实图形界面（这一步才抓得到缺原生库那类问题）──"
# 离屏渲染过了 ≠ 真窗口能开：xcb 插件缺库只有开真窗口才暴露 —— 这次就是这么抓到的。
run ssh -o BatchMode=yes "$NEX" \
    "cd '$DEST' && export DISPLAY=\${DISPLAY:-:1}; ./run.sh --selftest /tmp/sammy-window-check.png 2>&1 | tail -12 || echo '  ⚠️ 真实窗口没开起来 —— 看上面报错（多半还是缺某块原生库）'"

say
if [ "$DO_IT" -eq 1 ]; then
    say "✅ 装好了。等小屏插上、Nex 重启过（nvidia 驱动版本不一致，重启才生效）之后："
    say "   ssh $NEX"
    say "   cd $DEST && DISPLAY=:1 ./run.sh --screens      # 看新屏是第几号"
    say "   cd $DEST && DISPLAY=:1 ./run.sh --kiosk --display <号>"
else
    say "演练结束 —— 上面就是要执行的全部动作。确认没问题就加 --yes 重跑。"
fi
