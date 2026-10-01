#!/bin/bash
# Sammy 启动器 —— 用项目自带的虚拟环境跑，不污染系统 Python
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo "❌ 找不到 .venv，先跑一次:"
    echo "   uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt"
    exit 1
fi

export PYTHONPATH=src

# 项目自带的原生库（vendor/lib）—— 给「系统缺 Qt 要的那几个 .so」兜底。
# 为什么要有这一层：Ubuntu 精简装缺 libxcb-cursor0 时，Qt 6.5+ 的 xcb 插件直接核心转储
# （报 Could not load the Qt platform plugin "xcb"），而装系统包要 sudo。
# 所以把 .so 解到项目自己目录里 —— 零 sudo、删掉 vendor/ 就干净。
# 只在 Linux 上生效（macOS 用 DYLD_LIBRARY_PATH，而且这目录在 Mac 上本来就不存在）。
if [ -d vendor/lib ]; then
    _libs=$(find "$PWD/vendor/lib" -name '*.so*' -printf '%h\n' 2>/dev/null | sort -u | paste -sd:)
    if [ -n "$_libs" ]; then
        export LD_LIBRARY_PATH="${_libs}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    fi
fi

exec .venv/bin/python -m sammy "$@"
