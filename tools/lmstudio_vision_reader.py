#!/usr/bin/env python3

import os
import sys
import argparse
import base64
from pathlib import Path
from typing import Dict, List, Optional, Any
from openai import OpenAI
from PIL import Image


# Default prompt template
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


class LMStudioVisionReader:
    """Vision model reader that uses LM Studio API (supports Gemini, Qwen-VL, etc.)"""
    
    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        """
        Initialize vision reader with config
        
        Args:
            config_dict: Vision model configuration. If None, will load from config.yaml
        """
        if config_dict is None:
            # Load from config.yaml
            try:
                from src.config import config
                config_dict = config.vision_config
            except ImportError:
                # Fallback to defaults if config module not available
                config_dict = {
                    'api_url': 'http://localhost:1234/v1',
                    'api_key': 'lm-studio',
                    'model_name': 'google/gemma-3-27b',
                    'max_tokens': 2048,
                    'temperature': 0.0
                }
        
        self.base_url = config_dict.get('api_url', 'http://localhost:1234/v1')
        self.api_key = config_dict.get('api_key', 'lm-studio')
        self.model = config_dict.get('model_name', 'google/gemma-3-27b')
        self.default_max_tokens = config_dict.get('max_tokens', 2048)
        self.default_temperature = config_dict.get('temperature', 0.0)
        
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
    
    def encode_image(self, image_path: str) -> str:
        """Encode image to base64 string"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def read_image(
        self, 
        image_path: str, 
        prompt: str = DEFAULT_PROMPT, 
        max_tokens: Optional[int] = None, 
        temperature: Optional[float] = None
    ) -> str:
        """
        Read and analyze image using vision model
        
        Args:
            image_path: Path to image file
            prompt: Prompt for the vision model
            max_tokens: Maximum tokens to generate (uses config default if None)
            temperature: Sampling temperature (uses config default if None)
        
        Returns:
            Model's text response
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片不存在: {image_path}")
        
        # Use config defaults if not specified
        max_tokens = max_tokens or self.default_max_tokens
        temperature = temperature or self.default_temperature
        
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
    # Load defaults from config
    try:
        from src.config import config
        vision_cfg = config.vision_config
        default_model = vision_cfg.get('model_name', 'google/gemma-3-27b')
        default_url = vision_cfg.get('api_url', 'http://localhost:1234/v1')
        default_max_tokens = vision_cfg.get('max_tokens', 2048)
    except ImportError:
        default_model = 'google/gemma-3-27b'
        default_url = 'http://localhost:1234/v1'
        default_max_tokens = 2048
    
    parser = argparse.ArgumentParser(
        description="Vision model reader using LM Studio API (Gemini, Qwen-VL, etc.)"
    )
    parser.add_argument("image_path", type=str, help="Path to image file or directory")
    parser.add_argument("-p", "--prompt", type=str, default=DEFAULT_PROMPT, help="Prompt for vision model")
    parser.add_argument("-m", "--model", type=str, default=default_model, help=f"Model name (default from config: {default_model})")
    parser.add_argument("-u", "--url", type=str, default=default_url, help=f"API base URL (default from config: {default_url})")
    parser.add_argument("-t", "--max-tokens", type=int, default=default_max_tokens, help=f"Max tokens (default from config: {default_max_tokens})")
    parser.add_argument("-o", "--output", type=str, required=True, help="Output JSON file path")
    
    args = parser.parse_args()
    
    # Create reader with custom config if args provided
    config_dict = {
        'api_url': args.url,
        'model_name': args.model,
        'max_tokens': args.max_tokens
    }
    reader = LMStudioVisionReader(config_dict=config_dict)
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
