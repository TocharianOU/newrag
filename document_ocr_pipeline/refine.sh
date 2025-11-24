#!/bin/bash
# VLM精炼快捷脚本

cd "$(dirname "$0")"
source .venv/bin/activate
python refine_with_vlm.py "$@"

