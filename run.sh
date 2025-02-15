#!/bin/bash

# 检查是否安装 Python
if command -v python >/dev/null 2>&1; then
    echo "检测到 Python，正在执行 llama_manager.py ..."
    python llama_manager.py
else
    echo "错误：未检测到 Python，请安装 Python 后重试。"
    exit 1
fi

