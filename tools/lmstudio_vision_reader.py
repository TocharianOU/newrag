#!/usr/bin/env python3

import os
import sys
import argparse
import base64
from pathlib import Path
from typing import List
from openai import OpenAI
from PIL import Image


# ==================== 在这里修改配置 ====================
# 如果您在 LM Studio 中有更好的 Prompt，请直接替换下面的 DEFAULT_PROMPT
DEFAULT_PROMPT = """请仔细观察这张图片，提取其中所有文字、符号、表格和技术信息。

输出JSON格式（严格遵守以下结构）：
{
  "text": "逐字逐句提取图片中的所有文字内容，按照从上到下、从左到右的顺序，保持原始排版",
  "document_info": {
    "document_type": "文档类型",
    "title": "完整标题",
    "drawing_number": "图号（如TR1D-HXG-31-8110-DAS-0016）",
    "project_name": "项目名称",
    "company": "公司名称",
    "revision": "版本号",
    "date": "日期"
  },
  "equipment": [
    {"tag": "设备标签", "name": "设备名称", "type": "设备类型", "specs": "规格参数"}
  ],
  "components": [
    {"id": "元器件编号", "type": "元器件类型", "value": "参数值"}
  ],
  "tables": [
    {
      "title": "表格标题或用途",
      "headers": ["列名1", "列名2", "..."],
      "rows": [
        ["第1行数据1", "第1行数据2", "..."],
        ["第2行数据1", "第2行数据2", "..."]
      ]
    }
  ],
  "nozzles": [
    {"mark": "接口标记", "description": "描述", "size": "尺寸", "rating": "等级"}
  ],
  "notes": ["备注1", "备注2"]
}

要求：
1. 必须精确提取，不要猜测或修正拼写
2. 图号、编号等必须完全一致
3. 所有表格数据必须完整提取
4. 直接输出JSON，不要```markdown```标记
5. 如果某个字段没有内容，使用空数组[]或空字符串""
6. 严禁编造不存在的信息"""

DEFAULT_MODEL = "google/gemma-3-27b"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_TEMPERATURE = 0.1  # 与 LM Studio 设置一致
# =======================================================


class LMStudioVisionReader:
    
    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL):
        self.client = OpenAI(base_url=base_url, api_key="lm-studio")
        self.model = model
    
    def encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def read_image(self, image_path: str, prompt: str = DEFAULT_PROMPT, max_tokens: int = DEFAULT_MAX_TOKENS, temperature: float = DEFAULT_TEMPERATURE) -> str:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片不存在: {image_path}")
        
        base64_image = self.encode_image(image_path)
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}},
                    {"type": "text", "text": prompt}
                ]
            }],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False
        )
        
        return response.choices[0].message.content
    
    def batch_read_images(self, image_paths: List[str], prompt: str, max_tokens: int, output_file: str) -> List[tuple]:
        results = []
        
        for i, image_path in enumerate(image_paths, 1):
            print(f"[{i}/{len(image_paths)}] {image_path}")
            
            try:
                output = self.read_image(image_path, prompt, max_tokens)
                results.append((image_path, output))
                
                with open(output_file, 'a', encoding='utf-8') as f:
                    f.write(output)
                    f.write("\n\n")
                    
            except Exception as e:
                error_msg = f"ERROR: {str(e)}"
                results.append((image_path, error_msg))
                with open(output_file, 'a', encoding='utf-8') as f:
                    f.write(error_msg)
                    f.write("\n\n")
        
        return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path", type=str)
    parser.add_argument("-p", "--prompt", type=str, default=DEFAULT_PROMPT)
    parser.add_argument("-m", "--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("-u", "--url", type=str, default=DEFAULT_BASE_URL)
    parser.add_argument("-t", "--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("-o", "--output", type=str, required=True)
    
    args = parser.parse_args()
    
    reader = LMStudioVisionReader(base_url=args.url, model=args.model)
    input_path = Path(args.image_path)
    
    if input_path.is_file():
        result = reader.read_image(str(input_path), args.prompt, args.max_tokens)
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
            
    elif input_path.is_dir():
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
        image_files = sorted([str(f) for f in input_path.iterdir() if f.suffix.lower() in image_extensions])
        
        if not image_files:
            print(f"没有找到图片文件: {input_path}")
            sys.exit(1)
        
        open(args.output, 'w').close()
        reader.batch_read_images(image_files, args.prompt, args.max_tokens, args.output)
    else:
        print(f"无效路径: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
