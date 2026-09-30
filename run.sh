#!/bin/bash
# Sammy 启动器 —— 用项目自带的虚拟环境跑，不污染系统 Python
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo "❌ 找不到 .venv，先跑一次:"
    echo "   uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt"
    exit 1
fi

export PYTHONPATH=src
exec .venv/bin/python -m sammy "$@"
