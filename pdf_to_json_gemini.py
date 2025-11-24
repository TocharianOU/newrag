#!/usr/bin/env python3
"""
PDF 转结构化 JSON 一体化脚本（使用 LM Studio）

完整流程：
1. PDF 转图片
2. OCR 提取文本和坐标
3. 使用 LM Studio VLM 精炼优化
4. 输出 [{}, {}] 格式的 JSON 列表

使用方法：
    python pdf_to_json_gemini.py input.pdf output.json
"""

import os
import sys
import json
import base64
import argparse
from pathlib import Path
from typing import List, Dict, Any
import tempfile
import shutil

# PDF 转图片依赖
try:
    from pdf2image import convert_from_path
    import cv2
    import numpy as np
    from PIL import Image
    from openai import OpenAI
except ImportError:
    print("❌ 缺少依赖库！请安装：")
    print("   pip install pdf2image opencv-python numpy Pillow openai")
    sys.exit(1)

# OCR 依赖
try:
    import easyocr
    HAS_OCR = True
except ImportError:
    print("⚠️  警告：未安装 EasyOCR，将跳过 OCR 阶段")
    HAS_OCR = False


class PDFToJSONProcessor:
    """PDF 转结构化 JSON 处理器（使用 LM Studio）"""
    
    # VLM 提示词模板
    VLM_PROMPT = """你是专业的技术文档分析专家。请仔细分析这张图片，提取所有信息并生成结构化 JSON。

【关键要求】：
1. 提取文档元数据（文档编号、版本、项目名称、公司名称等）
2. 提取设备信息（设备标签、名称、类型、规格等）
3. 识别并结构化所有表格数据
4. 修正 OCR 错误（如日期格式：15-58p-25 → 15-Sep-25）
5. 提取所有技术参数和备注
6. 生成搜索关键词

【输出 JSON 格式】（严格遵守）：
{
  "document_metadata": {
    "document_type": "文档类型（如 Process Datasheet）",
    "document_number": "文档编号",
    "revision": "版本号",
    "project_name": "项目名称",
    "plant": "工厂/设施名称",
    "equipment_tag": "设备标签",
    "page": "当前页码",
    "total_pages": "总页数"
  },
  "document_content": {
    "title": "文档标题",
    "equipment_name": "设备名称",
    "process_unit": "工艺单元",
    "project_phase": "项目阶段",
    "package_number": "包号",
    "area": "区域"
  },
  "revision_history": [
    {
      "revision": "版本号",
      "date": "日期（修正后）",
      "description": "描述",
      "prepared_by": "编制人",
      "checked_by": "审核人",
      "approved_by": "批准人"
    }
  ],
  "tables": [
    {
      "title": "表格标题",
      "headers": ["列名1", "列名2"],
      "rows": [["数据1", "数据2"]]
    }
  ],
  "technical_parameters": [
    {"parameter": "参数名", "value": "参数值", "unit": "单位"}
  ],
  "procedures": {
    "external_documentation": "外部文档要求",
    "review_acceptance_notes": ["审核接受说明"]
  },
  "keywords": ["关键词1", "关键词2"],
  "full_text_cleaned": "清洗后的完整文本",
  "extraction_notes": ["提取过程中的备注或不确定项"]
}

【重要提示】：
- 修正所有 OCR 错误
- 保持原始信息的准确性
- 表格数据必须完整提取
- 直接输出 JSON，不要任何解释
- 如果某个字段没有内容，使用空字符串 "" 或空数组 []
"""
    
    def __init__(self, lm_studio_url: str = "http://localhost:1234/v1", 
                 model_name: str = "google/gemma-3-27b"):
        """
        初始化处理器
        
        Args:
            lm_studio_url: LM Studio API 地址
            model_name: 模型名称
        """
        # 配置 LM Studio
        self.client = OpenAI(base_url=lm_studio_url, api_key="lm-studio")
        self.model_name = model_name
        
        # 初始化 OCR
        self.ocr_reader = None
        if HAS_OCR:
            try:
                print("🔧 初始化 OCR 引擎...")
                self.ocr_reader = easyocr.Reader(['en', 'ch_sim'], gpu=False)
                print("✓ OCR 引擎初始化成功")
            except Exception as e:
                print(f"⚠️  OCR 初始化失败: {e}")
                self.ocr_reader = None
        
        print(f"✓ LM Studio 已连接: {lm_studio_url}")
    
    def pdf_to_images(self, pdf_path: str, dpi: int = 300) -> List[Path]:
        """
        将 PDF 转换为图片
        
        Args:
            pdf_path: PDF 文件路径
            dpi: 图片分辨率
        
        Returns:
            图片文件路径列表
        """
        print(f"\n📄 正在转换 PDF: {os.path.basename(pdf_path)}")
        
        # 创建临时目录
        temp_dir = Path(tempfile.mkdtemp(prefix="pdf_images_"))
        
        try:
            # 转换 PDF
            images = convert_from_path(pdf_path, dpi=dpi, fmt='png')
            print(f"✓ PDF 共 {len(images)} 页")
            
            # 保存图片
            image_paths = []
            for i, image in enumerate(images, start=1):
                image_path = temp_dir / f"page_{i:03d}.png"
                image.save(image_path, 'PNG')
                image_paths.append(image_path)
                print(f"  [{i}/{len(images)}] {image_path.name}")
            
            return image_paths
            
        except Exception as e:
            print(f"❌ PDF 转换失败: {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
    
    def extract_text_with_ocr(self, image_path: str) -> Dict[str, Any]:
        """
        使用 OCR 提取文本和坐标
        
        Args:
            image_path: 图片路径
        
        Returns:
            OCR 结果
        """
        if not self.ocr_reader:
            return {
                "text_blocks": [],
                "full_text": "",
                "average_confidence": 0
            }
        
        print(f"  🔍 OCR 识别中...")
        
        # 读取图片
        image = cv2.imread(str(image_path))
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        # OCR 提取
        results = self.ocr_reader.readtext(image_rgb)
        
        # 格式化结果
        text_blocks = []
        full_text_parts = []
        
        for bbox, text, confidence in results:
            # 计算边界框
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            
            text_blocks.append({
                "text": text.strip(),
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
                "confidence": float(confidence),
                "center_y": float((y1 + y2) / 2),
                "center_x": float((x1 + x2) / 2)
            })
            full_text_parts.append(text.strip())
        
        # 按位置排序
        text_blocks.sort(key=lambda x: (x["center_y"], x["center_x"]))
        
        avg_confidence = sum(b["confidence"] for b in text_blocks) / len(text_blocks) if text_blocks else 0
        
        print(f"  ✓ OCR 完成：{len(text_blocks)} 个文本块，平均置信度 {avg_confidence*100:.1f}%")
        
        return {
            "text_blocks": text_blocks,
            "full_text": "\n".join(full_text_parts),
            "average_confidence": avg_confidence
        }
    
    def refine_with_vlm(self, image_path: str, ocr_data: Dict[str, Any], 
                       page_number: int, total_pages: int) -> Dict[str, Any]:
        """
        使用 LM Studio VLM 精炼优化
        
        Args:
            image_path: 图片路径
            ocr_data: OCR 数据
            page_number: 当前页码
            total_pages: 总页数
        
        Returns:
            精炼后的结构化数据
        """
        print(f"  🤖 VLM 分析中...")
        
        # 构建增强提示词
        prompt = self.VLM_PROMPT
        
        if ocr_data.get("full_text"):
            prompt += f"\n\n【OCR 提取的原始文本】：\n{ocr_data['full_text']}\n"
            prompt += f"【OCR 统计】：{len(ocr_data.get('text_blocks', []))} 个文本块，平均置信度 {ocr_data.get('average_confidence', 0)*100:.1f}%\n"
        
        prompt += f"\n【页面信息】：第 {page_number} 页，共 {total_pages} 页\n"
        
        try:
            # 编码图片
            with open(image_path, "rb") as f:
                base64_image = base64.b64encode(f.read()).decode('utf-8')
            
            # 调用 LM Studio
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}},
                        {"type": "text", "text": prompt}
                    ]
                }],
                max_tokens=8192,
                temperature=0.1,
                stream=False
            )
            
            content = response.choices[0].message.content
            
            # 提取 JSON
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                refined_data = json.loads(json_str)
                print(f"  ✓ VLM 分析完成")
                return refined_data
            else:
                raise ValueError("未找到有效的 JSON 输出")
        
        except Exception as e:
            print(f"  ⚠️  VLM 分析出错: {e}")
            return {
                "document_metadata": {},
                "document_content": {},
                "revision_history": [],
                "tables": [],
                "technical_parameters": [],
                "procedures": {},
                "keywords": [],
                "full_text_cleaned": ocr_data.get("full_text", ""),
                "extraction_notes": [f"VLM 分析失败: {str(e)}"]
            }
    
    def create_page_document(self, refined_data: Dict[str, Any], 
                            ocr_data: Dict[str, Any],
                            image_path: str,
                            page_number: int,
                            total_pages: int) -> Dict[str, Any]:
        """
        创建单页文档结构
        
        Args:
            refined_data: VLM 精炼后的数据
            ocr_data: OCR 数据
            image_path: 图片路径
            page_number: 页码
            total_pages: 总页数
        
        Returns:
            单页文档结构
        """
        doc_metadata = refined_data.get('document_metadata', {})
        doc_content = refined_data.get('document_content', {})
        
        return {
            # ===== 页面标识 =====
            "page_number": page_number,
            "total_pages": total_pages,
            "source_image": os.path.basename(image_path),
            
            # ===== 文档元数据 =====
            "document_id": doc_metadata.get('document_number', ''),
            "document_type": doc_metadata.get('document_type', ''),
            "revision": doc_metadata.get('revision', ''),
            
            # ===== 项目信息 =====
            "project": {
                "name": doc_metadata.get('project_name', ''),
                "plant": doc_metadata.get('plant', ''),
                "phase": doc_content.get('project_phase', '')
            },
            
            # ===== 设备信息 =====
            "equipment": {
                "tag": doc_metadata.get('equipment_tag', ''),
                "name": doc_content.get('equipment_name', ''),
                "title": doc_content.get('title', ''),
                "unit": doc_content.get('process_unit', ''),
                "area": doc_content.get('area', ''),
                "package": doc_content.get('package_number', '')
            },
            
            # ===== 文档内容 =====
            "content": {
                "full_text": refined_data.get('full_text_cleaned', ''),
                "full_text_raw": ocr_data.get('full_text', ''),
                "summary": doc_content.get('title', '')
            },
            
            # ===== 修订历史 =====
            "revision_history": refined_data.get('revision_history', []),
            
            # ===== 表格数据 =====
            "tables": refined_data.get('tables', []),
            
            # ===== 技术参数 =====
            "technical_parameters": refined_data.get('technical_parameters', []),
            
            # ===== 程序和流程 =====
            "procedures": refined_data.get('procedures', {}),
            
            # ===== 搜索关键词 =====
            "keywords": refined_data.get('keywords', []),
            
            # ===== OCR 元数据 =====
            "ocr_metadata": {
                "text_blocks_count": len(ocr_data.get('text_blocks', [])),
                "average_confidence": ocr_data.get('average_confidence', 0)
            },
            
            # ===== 文本块坐标（用于高亮） =====
            "text_blocks": [
                {
                    "text": block.get('text', ''),
                    "bbox": block.get('bbox', []),
                    "confidence": block.get('confidence', 0)
                }
                for block in ocr_data.get('text_blocks', [])
                if block.get('confidence', 0) > 0.3
            ],
            
            # ===== 提取注释 =====
            "extraction_notes": refined_data.get('extraction_notes', [])
        }
    
    def process_pdf(self, pdf_path: str, output_json_path: str) -> List[Dict[str, Any]]:
        """
        处理 PDF 文件，生成结构化 JSON
        
        Args:
            pdf_path: PDF 文件路径
            output_json_path: 输出 JSON 文件路径
        
        Returns:
            所有页面的文档列表
        """
        print("\n" + "="*80)
        print("🚀 PDF 转结构化 JSON 处理")
        print("="*80)
        
        # 1. PDF 转图片
        image_paths = self.pdf_to_images(pdf_path, dpi=300)
        total_pages = len(image_paths)
        
        # 2. 处理每一页
        all_pages_data = []
        
        for i, image_path in enumerate(image_paths, start=1):
            print(f"\n📄 处理第 {i}/{total_pages} 页...")
            
            try:
                # OCR 提取
                ocr_data = self.extract_text_with_ocr(str(image_path))
                
                # VLM 精炼
                refined_data = self.refine_with_vlm(
                    str(image_path), 
                    ocr_data, 
                    i, 
                    total_pages
                )
                
                # 创建页面文档
                page_doc = self.create_page_document(
                    refined_data, 
                    ocr_data, 
                    str(image_path),
                    i,
                    total_pages
                )
                
                all_pages_data.append(page_doc)
                print(f"  ✅ 第 {i} 页处理完成")
                
            except Exception as e:
                print(f"  ❌ 第 {i} 页处理失败: {e}")
                all_pages_data.append({
                    "page_number": i,
                    "total_pages": total_pages,
                    "error": str(e),
                    "document_id": "",
                    "content": {}
                })
        
        # 3. 保存 JSON
        print(f"\n💾 保存结果到: {output_json_path}")
        output_path = Path(output_json_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_pages_data, f, ensure_ascii=False, indent=2)
        
        # 4. 清理临时文件
        if image_paths:
            temp_dir = image_paths[0].parent
            print(f"🧹 清理临时文件: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        # 5. 打印统计
        print("\n" + "="*80)
        print("✅ 处理完成！")
        print("="*80)
        print(f"📊 统计信息：")
        print(f"  - 总页数: {total_pages}")
        print(f"  - 成功: {len([p for p in all_pages_data if 'error' not in p])}")
        print(f"  - 失败: {len([p for p in all_pages_data if 'error' in p])}")
        print(f"  - 输出: {output_path.absolute()}")
        
        return all_pages_data


def main():
    parser = argparse.ArgumentParser(description='PDF 转结构化 JSON（使用 LM Studio）')
    parser.add_argument('pdf_path', help='PDF 文件路径')
    parser.add_argument('output_json', help='输出 JSON 文件路径')
    
    args = parser.parse_args()
    
    # 检查输入文件
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"❌ 错误：文件不存在: {pdf_path}")
        sys.exit(1)
    
    if pdf_path.suffix.lower() != '.pdf':
        print(f"❌ 错误：不是 PDF 文件: {pdf_path}")
        sys.exit(1)
    
    try:
        # 初始化处理器
        processor = PDFToJSONProcessor()
        
        # 处理 PDF
        processor.process_pdf(str(pdf_path), args.output_json)
        
        print("\n🎉 完成！")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

