#!/bin/bash
# 文档提取快捷脚本

cd "$(dirname "$0")"
source .venv/bin/activate
python extract_document.py "$@"

