#!/usr/bin/env python3
"""
PPTX 完整处理管道
生成与 PDF 流程一致的输出结构
"""

import sys
import json
import argparse
from pathlib import Path
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
import io
from PIL import Image
import subprocess

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from document_ocr_pipeline.extract_document import DocumentExtractor
from document_ocr_pipeline.visualize_extraction import visualize_extraction


def extract_slide_content(slide, slide_num, output_dir, ocr_engine='paddle'):
    """
    提取单页内容：文本 + 图片OCR + VLM组合
    """
    slide_data = {
        "page_number": slide_num,
        "statistics": {},
        "stage1_global": {},
        "stage3_vlm": {}
    }
    
    # ==================== 阶段 1: 文本直接提取 ====================
    print(f"\n  📝 阶段1: 提取文本内容（高优先级）...")
    
    extracted_text = {
        "title": "",
        "body": [],
        "notes": "",
        "tables": []
    }
    
    for shape in slide.shapes:
        if shape.has_text_frame:
            text = shape.text.strip()
            if text:
                if hasattr(shape, "is_placeholder") and shape.is_placeholder:
                    placeholder = shape.placeholder_format
                    if placeholder.type == 1:  # Title
                        extracted_text["title"] = text
                    else:
                        extracted_text["body"].append(text)
                else:
                    extracted_text["body"].append(text)
        
        if shape.has_table:
            table = shape.table
            table_data = []
            for row in table.rows:
                row_data = [cell.text for cell in row.cells]
                table_data.append(row_data)
            extracted_text["tables"].append(table_data)
    
    if slide.has_notes_slide:
        extracted_text["notes"] = slide.notes_slide.notes_text_frame.text
    
    # 保存文本提取结果
    text_json_path = output_dir / f"page_{slide_num:03d}_extracted_text.json"
    with open(text_json_path, 'w', encoding='utf-8') as f:
        json.dump(extracted_text, f, ensure_ascii=False, indent=2)
    
    print(f"    ✓ 标题: {extracted_text['title'][:50] if extracted_text['title'] else '无'}")
    print(f"    ✓ 文本段落: {len(extracted_text['body'])} 个")
    print(f"    ✓ 表格: {len(extracted_text['tables'])} 个")
    
    # ==================== 阶段 2: 处理图片（OCR） ====================
    print(f"  🖼️  阶段2: 处理图片内容...")
    
    images = []
    image_ocr_results = []
    
    for idx, shape in enumerate(slide.shapes, 1):
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            image = shape.image
            image_filename = f"page_{slide_num:03d}_img_{idx}.{image.ext}"
            image_path = output_dir / image_filename
            
            # 保存图片
            with open(image_path, "wb") as f:
                f.write(image.blob)
            
            with Image.open(io.BytesIO(image.blob)) as img:
                width, height = img.size
            
            images.append({
                "id": idx,
                "path": str(image_path),
                "format": image.ext,
                "size": [width, height]
            })
            
            print(f"    ✓ 图片 {idx}: {width}x{height} ({image.ext})")
            
            # 对图片运行 OCR
            ocr_json_path = output_dir / f"page_{slide_num:03d}_img_{idx}_ocr.json"
            try:
                extractor = DocumentExtractor(ocr_engine=ocr_engine)
                ocr_result = extractor.extract_from_image(str(image_path))
                
                with open(ocr_json_path, 'w', encoding='utf-8') as f:
                    json.dump(ocr_result, f, ensure_ascii=False, indent=2)
                
                # 生成可视化
                vis_path = output_dir / f"page_{slide_num:03d}_img_{idx}_visualized.png"
                visualize_extraction(str(image_path), str(ocr_json_path), str(vis_path))
                
                image_ocr_results.append({
                    "image_id": idx,
                    "ocr_json": str(ocr_json_path),
                    "visualized": str(vis_path),
                    "text_blocks_count": len(ocr_result.get('text_blocks', []))
                })
                
                print(f"      ✓ OCR: {len(ocr_result.get('text_blocks', []))} 个文本块")
            except Exception as e:
                print(f"      ✗ OCR失败: {e}")
    
    # ==================== 阶段 3: VLM 处理（带文本上下文） ====================
    print(f"  🤖 阶段3: VLM 综合分析...")
    
    # 构建 VLM 提示（包含已提取的文本）
    vlm_context = {
        "extracted_text": extracted_text,
        "images": images,
        "image_ocr_results": image_ocr_results
    }
    
    # 生成 VLM 输入提示
    vlm_prompt = f"""# 幻灯片第 {slide_num} 页综合分析

## 已提取的文本内容（高可信度，来自PPT原始数据）：

### 标题
{extracted_text['title'] or '无'}

### 正文内容
"""
    for i, body in enumerate(extracted_text['body'], 1):
        vlm_prompt += f"{i}. {body}\n"
    
    if extracted_text['tables']:
        vlm_prompt += "\n### 表格\n"
        for t_idx, table in enumerate(extracted_text['tables'], 1):
            vlm_prompt += f"表格 {t_idx}:\n"
            for row in table[:3]:
                vlm_prompt += f"  {' | '.join(row)}\n"
    
    if extracted_text['notes']:
        vlm_prompt += f"\n### 备注\n{extracted_text['notes']}\n"
    
    vlm_prompt += f"""

## 图片OCR结果（{len(image_ocr_results)} 张图片）：
"""
    for ocr_res in image_ocr_results:
        vlm_prompt += f"- 图片 {ocr_res['image_id']}: {ocr_res['text_blocks_count']} 个文本块\n"
    
    vlm_prompt += """

## VLM 任务：
请综合上述信息，生成完整的页面内容描述：
1. 确认并整合已提取的文本
2. 补充图片中的额外信息（图表、示意图、图标等）
3. 识别页面的整体类型和主题
4. 提取关键信息和结构

返回 JSON 格式。
"""
    
    vlm_prompt_path = output_dir / f"page_{slide_num:03d}_vlm_prompt.txt"
    with open(vlm_prompt_path, 'w', encoding='utf-8') as f:
        f.write(vlm_prompt)
    
    # 这里可以调用 VLM（如果有的话）
    # 暂时保存提示和上下文
    vlm_context_path = output_dir / f"page_{slide_num:03d}_vlm_context.json"
    with open(vlm_context_path, 'w', encoding='utf-8') as f:
        json.dump(vlm_context, f, ensure_ascii=False, indent=2)
    
    print(f"    ✓ VLM上下文和提示已保存")
    
    # ==================== 构建最终页面数据 ====================
    # 整合所有文本
    all_text = []
    if extracted_text['title']:
        all_text.append(extracted_text['title'])
    all_text.extend(extracted_text['body'])
    if extracted_text['notes']:
        all_text.append(f"备注: {extracted_text['notes']}")
    
    # 添加表格文本
    for table in extracted_text['tables']:
        for row in table:
            all_text.append(' | '.join(row))
    
    # 添加图片OCR文本（只保留高置信度）
    MIN_CONFIDENCE = 0.85
    for ocr_res in image_ocr_results:
        try:
            with open(ocr_res['ocr_json'], 'r', encoding='utf-8') as f:
                ocr_data = json.load(f)
                # 从 text_blocks 提取高置信度文本
                if ocr_data.get('text_blocks'):
                    high_confidence_blocks = [
                        block for block in ocr_data['text_blocks']
                        if block.get('confidence', 0) >= MIN_CONFIDENCE and block.get('text')
                    ]
                    if high_confidence_blocks:
                        image_texts = [block['text'] for block in high_confidence_blocks]
                        all_text.append(f"[图片 {ocr_res['image_id']}-高置信度] " + ' '.join(image_texts))
                    
                    # 记录过滤情况
                    low_conf_count = len(ocr_data['text_blocks']) - len(high_confidence_blocks)
                    if low_conf_count > 0:
                        print(f"      ℹ️  图片 {ocr_res['image_id']}: 过滤了 {low_conf_count} 个低置信度文本块")
        except Exception as e:
            print(f"      ⚠️  无法读取图片OCR结果: {e}")
    
    combined_text = '\n\n'.join(all_text)
    
    # 统计信息
    slide_data['statistics'] = {
        "total_text_blocks": len(all_text),
        "total_images": len(images),
        "has_title": bool(extracted_text['title']),
        "has_tables": len(extracted_text['tables']) > 0,
        "has_notes": bool(extracted_text['notes'])
    }
    
    # Stage1 信息（模拟 PDF 的结构）
    # 使用第一张提取的图片作为预览图（如果有的话）
    preview_image = f"page_{slide_num:03d}_preview.png"
    if images:
        # 使用第一张图片作为预览
        first_image_path = Path(images[0]['path'])
        preview_image = first_image_path.name
    
    slide_data['stage1_global'] = {
        "image": preview_image,
        "ocr_json": str(text_json_path),
        "text_source": "direct_extraction"
    }
    
    # Stage3 VLM 信息
    slide_data['stage3_vlm'] = {
        "vlm_prompt": str(vlm_prompt_path),
        "vlm_context": str(vlm_context_path),
        "text_combined": combined_text
    }
    
    return slide_data, combined_text


def process_pptx(pptx_path, output_dir, ocr_engine='paddle'):
    """
    完整处理 PPTX 文件
    生成与 adaptive_ocr_pipeline.py 相同的输出结构
    """
    print(f"🚀 开始处理 PPTX: {pptx_path}")
    print(f"📂 输出目录: {output_dir}")
    print(f"🔧 OCR引擎: {ocr_engine}")
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    prs = Presentation(pptx_path)
    total_slides = len(prs.slides)
    
    print(f"📄 总页数: {total_slides}")
    
    result = {
        "source_file": str(pptx_path),
        "file_type": "pptx",
        "total_pages": total_slides,
        "ocr_engine": ocr_engine,
        "pages": []
    }
    
    for slide_idx, slide in enumerate(prs.slides, 1):
        print(f"\n{'='*70}")
        print(f"📄 处理第 {slide_idx}/{total_slides} 页")
        print(f"{'='*70}")
        
        slide_data, combined_text = extract_slide_content(
            slide, slide_idx, output_dir, ocr_engine
        )
        
        result["pages"].append(slide_data)
        
        print(f"\n✅ 第 {slide_idx} 页完成")
        print(f"  - 文本块: {slide_data['statistics']['total_text_blocks']}")
        print(f"  - 图片: {slide_data['statistics']['total_images']}")
        print(f"  - 字符数: {len(combined_text)}")
    
    # 保存完整结果（与 PDF 的 complete_adaptive_ocr.json 格式一致）
    complete_json = output_dir / "complete_adaptive_ocr.json"
    with open(complete_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*70}")
    print(f"✅ 处理完成！")
    print(f"{'='*70}")
    print(f"📊 统计:")
    print(f"  - 总页数: {total_slides}")
    print(f"  - 输出文件: {complete_json}")
    print(f"  - 输出目录: {output_dir.absolute()}")
    
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PPTX 完整处理管道")
    parser.add_argument("input_file", help="输入 PPTX 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出目录（默认：pptx_output）")
    parser.add_argument("--ocr-engine", choices=['easy', 'paddle', 'vision'], 
                       default='paddle', help="OCR引擎选择")
    
    args = parser.parse_args()
    
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"❌ 文件不存在: {input_path}")
        sys.exit(1)
    
    if args.output:
        output_dir = Path(args.output)
    else:
        # 默认输出目录：文件名_adaptive
        output_dir = Path(input_path.stem.replace(' ', '_') + "_adaptive")
    
    try:
        result = process_pptx(input_path, output_dir, args.ocr_engine)
        print(f"\n🎉 成功！可以使用此输出目录集成到系统中。")
    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

