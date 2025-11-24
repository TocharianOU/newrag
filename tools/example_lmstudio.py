#!/usr/bin/env python3

from lmstudio_vision_reader import LMStudioVisionReader


# ==================== 在这里修改配置 ====================
IMAGE_PATH = "/Users/ablatazmat/Downloads/SmartResume/output_images/liebiao.png"
OUTPUT_FILE = "result.json"
# =======================================================

# 如果要修改 prompt 或模型，去 lmstudio_vision_reader.py 文件顶部修改


reader = LMStudioVisionReader()
result = reader.read_image(IMAGE_PATH)

with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(result)

print(f"完成: {OUTPUT_FILE}")
