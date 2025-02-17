#!/bin/bash
# 脚本：检测 Python、pip 及依赖包，缺失则安装后运行脚本

# 检查是否存在 python3 或 python
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "错误：未检测到 Python，请先安装 Python。"
    exit 1
fi

# 检查 pip（优先使用 pip3，如无则检测 pip）
if command -v pip3 >/dev/null 2>&1; then
    PIP=pip3
elif command -v pip >/dev/null 2>&1; then
    PIP=pip
else
    echo "检测到 Python，但未检测到 pip，正在尝试使用 ensurepip 安装 pip..."
    $PYTHON -m ensurepip --upgrade
    if [ $? -ne 0 ]; then
        echo "错误：pip 安装失败，请手动安装 pip。"
        exit 1
    fi
    if command -v pip3 >/dev/null 2>&1; then
        PIP=pip3
    else
        PIP=pip
    fi
fi

echo "使用的 Python: $PYTHON"
echo "使用的 pip: $PIP"

# 定义需要检查的依赖包列表
packages=("PyQt5" "requests")

# 检查并安装缺失的依赖包
for pkg in "${packages[@]}"; do
    echo "检测依赖包: $pkg"
    if ! $PIP show "$pkg" >/dev/null 2>&1; then
        echo "$pkg 未安装，正在安装..."
        $PIP install "$pkg"
        if [ $? -ne 0 ]; then
            echo "错误：安装 $pkg 失败。"
            exit 1
        fi
    else
        echo "$pkg 已安装。"
    fi
done

# 执行脚本
echo "检测到 Python，正在执行 llama_request_http.py ..."
$PYTHON llama_request_http.py

