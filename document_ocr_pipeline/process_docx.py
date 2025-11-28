#!/usr/bin/env python3
"""
DOCX 完整处理管道 (基于 PDFPlumber 重构版)
方案 B：DOCX -> PDF -> PDFPlumber 逐页提取
优势：
1. 精确的物理分页 (Page-aware)
2. 表格定位准确 (Table-aware)
3. Markdown 格式输出 (LLM-friendly)
4. 统一的 PDF 处理逻辑
"""

import sys
import json
import argparse
from pathlib import Path
import io
import subprocess
import shutil

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from document_ocr_pipeline.extract_document import DocumentExtractor
from document_ocr_pipeline.visualize_extraction import visualize_extraction

def extract_table_to_markdown(table):
    """
    将 pdfplumber 提取的表格转换为 Markdown 格式
    table: list of lists of strings
    """
    if not table:
        return ""
        
    # 清理单元格数据：去除 None，去除首尾空格，处理换行符
    cleaned_table = []
    for row in table:
        cleaned_row = []
        for cell in row:
            if cell is None:
                cleaned_cell = ""
            else:
                # 替换换行符为空格，避免破坏 Markdown 表格结构
                cleaned_cell = str(cell).strip().replace('\n', ' ')
            cleaned_row.append(cleaned_cell)
        cleaned_table.append(cleaned_row)
        
    if not cleaned_table:
        return ""
        
    markdown_lines = []
    
    # 1. 表头
    headers = cleaned_table[0]
    markdown_lines.append("| " + " | ".join(headers) + " |")
    
    # 2. 分隔线
    markdown_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    
    # 3. 数据行
    for row in cleaned_table[1:]:
        # 确保行长度一致
        padded_row = row + [""] * (len(headers) - len(row))
        markdown_lines.append("| " + " | ".join(padded_row[:len(headers)]) + " |")
        
    return "\n".join(markdown_lines)

def process_docx(docx_path, output_dir, ocr_engine='paddle'):
    """
    完整处理 DOCX 文件 (通过 PDF 中转)
    """
    print(f"🚀 开始处理 DOCX (方案B: PDF中转): {docx_path}")
    print(f"📂 输出目录: {output_dir}")
    print(f"🔧 OCR引擎: {ocr_engine}")
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    docx_path = Path(docx_path)
    
    # ==================== 步骤 1: LibreOffice 转换 DOCX -> PDF ====================
    print(f"\n{'='*70}")
    print(f"📄 步骤 1: 转换为 PDF (获取精准布局)")
    print(f"{'='*70}")
    
    temp_pdf = output_dir / f"{docx_path.stem}_temp.pdf"
    
    try:
        print(f"  ⏳ 转换 DOCX 为 PDF...")
        subprocess.run([
            '/Applications/LibreOffice.app/Contents/MacOS/soffice',
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', str(output_dir),
            str(docx_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # LibreOffice 输出的文件名处理
        generated_pdf = output_dir / f"{docx_path.stem}.pdf"
        if generated_pdf.exists() and generated_pdf != temp_pdf:
            generated_pdf.rename(temp_pdf)
        
        print(f"  ✓ PDF 已生成: {temp_pdf.name}")
        
    except FileNotFoundError:
        print("  ❌ 错误: 未找到 LibreOffice，无法进行转换")
        print("  请安装: brew install --cask libreoffice")
        return None
    except Exception as e:
        print(f"  ❌ 转换失败: {e}")
        return None

    # ==================== 步骤 2: 初始化 OCR 引擎 ====================
    print(f"\n{'='*70}")
    print(f"📄 步骤 2: 初始化引擎")
    print(f"{'='*70}")
    
    ocr_extractor = DocumentExtractor(use_layout_detection=False, ocr_engine=ocr_engine)
    print(f"  ✓ OCR 引擎就绪: {ocr_engine}")
    
    # ==================== 步骤 3: 逐页处理 PDF ====================
    import pdfplumber
    import cv2
    import numpy as np

    pages_data = []
    total_paragraphs = 0
    total_tables = 0
    
    print(f"\n{'='*70}")
    print(f"📄 步骤 3: 逐页提取内容 (文本 + 表格 + OCR)")
    print(f"{'='*70}")
        
    with pdfplumber.open(temp_pdf) as pdf:
        page_count = len(pdf.pages)
        print(f"  📚 总页数: {page_count}")
        
        for page_num, page in enumerate(pdf.pages, 1):
            print(f"\n处理第 {page_num}/{page_count} 页...")
            
            # ---------------- 3.1 生成预览图 (命名修正为 _300dpi.png 以兼容 PDF 流程) ----------------
            img = page.to_image(resolution=300)
            img_array = np.array(img.original)
            
            # 关键修正：将 preview.png 改为 300dpi.png，解决前端/大模型 404 问题
            preview_image = f"page_{page_num:03d}_300dpi.png"
            preview_path = output_dir / preview_image
            cv2.imwrite(str(preview_path), cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR))
            print(f"  🖼️  预览图: {preview_image}")
        
            # ---------------- 3.2 提取文本 (High Quality) ----------------
            # layout=True 尝试保持物理布局
            text_content = page.extract_text(layout=True) or ""
            para_count = len(text_content.split('\n')) if text_content else 0
            total_paragraphs += para_count
            print(f"  📝 文本提取: {len(text_content)} 字符")
            
            # ---------------- 3.3 提取表格 -> Markdown ----------------
            tables = page.extract_tables()
            table_md_list = []
            if tables:
                print(f"  📊 发现表格: {len(tables)} 个")
                total_tables += len(tables)
                for tbl in tables:
                    md = extract_table_to_markdown(tbl)
                    if md:
                        table_md_list.append(md)
    
            # ---------------- 3.4 组装页面文本 (Text + Tables) ----------------
            final_page_text = text_content
            
            if table_md_list:
                table_section = "\n\n【表格数据 (Markdown)】\n" + "\n\n".join(table_md_list)
                # 将表格追加到文本末尾 (或者根据位置插入，这里简化为追加)
                final_page_text += table_section
                print(f"    ✓ 已转换 {len(table_md_list)} 个表格为 Markdown")
                
            # ---------------- 3.5 OCR 补充 (针对图片/扫描件) ----------------
            # 只有当页面文本很少（可能是扫描件）时，才强制依赖 OCR 文本
            # 但为了保险，我们总是运行 OCR 以获取 bounding box 和应对复杂情况
            print(f"  🔍 运行 OCR...")
            try:
                ocr_result = ocr_extractor.extract_from_image(str(preview_path))
                
                # 保存 OCR JSON
                page_ocr_json = output_dir / f"page_{page_num:03d}_ocr.json"
                with open(page_ocr_json, 'w', encoding='utf-8') as f:
                    json.dump(ocr_result, f, ensure_ascii=False, indent=2)
                    
                # 生成可视化
                vis_path = output_dir / f"page_{page_num:03d}_visualized.png"
                visualize_extraction(str(preview_path), str(page_ocr_json), str(vis_path))
                
                # 提取 OCR 文本
                ocr_text_blocks = ocr_result.get('text_blocks', [])
                ocr_texts = [b.get('text', '') for b in ocr_text_blocks if b.get('text', '').strip()]
                ocr_full_text = "\n".join(ocr_texts)
                
                # 智能合并策略：
                # 如果直接提取的文本很少，说明可能是纯图，使用 OCR 文本作为主力
                if len(text_content) < 50 and len(ocr_full_text) > 50:
                    print("    ⚠️  页面文本极少，采用 OCR 结果为主")
                    final_page_text = f"{final_page_text}\n\n【OCR 识别内容】\n{ocr_full_text}"
                else:
                    # 否则作为补充
                    final_page_text += f"\n\n【视觉识别补充 (OCR)】\n{ocr_full_text}"
                    
                avg_confidence = 0.0
                if ocr_text_blocks:
                    confs = [b.get('confidence', 0) for b in ocr_text_blocks]
                    avg_confidence = sum(confs) / len(confs)
                    
            except Exception as e:
                print(f"  ❌ OCR 出错: {e}")
                ocr_text_blocks = []
                avg_confidence = 0.0

            # ---------------- 3.6 构建 Page Data ----------------
            page_data = {
                "page_number": page_num,
                "statistics": {
                    "total_characters": len(final_page_text),
                    "total_tables": len(tables),
                    "avg_ocr_confidence": round(avg_confidence, 3)
                },
                "stage1_global": {
                    "image": preview_image,
                    "text_source": "pdfplumber+ocr"
                },
                "stage3_vlm": {
                    "text_combined": final_page_text
                }
            }
            pages_data.append(page_data)

    # ==================== 步骤 4: 生成输出文件 ====================
    
    # 1. complete_adaptive_ocr.json (兼容旧格式)
    result = {
        "source_file": str(docx_path),
        "file_type": "docx",
        "total_pages": page_count,
        "ocr_engine": ocr_engine,
        "pages": pages_data,
        "statistics": {
            "total_paragraphs": total_paragraphs,
            "total_tables": total_tables
        }
    }
    
    complete_json = output_dir / "complete_adaptive_ocr.json"
    with open(complete_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # 2. complete_document.json (ES 索引格式)
    pages_for_index = []
    for page in pages_data:
        page_num = page['page_number']
        text_combined = page['stage3_vlm']['text_combined']
        image_filename = page['stage1_global']['image']
        
        pages_for_index.append({
            'page_number': page_num,
            'image_path': str(output_dir / image_filename),
            'image_filename': image_filename,
            'content': {
                'full_text_cleaned': text_combined,
                'full_text_raw': text_combined,
                'key_fields': [],
                'tables': [] # 结构化数据后续可扩展
            },
            'ocr_data': {
                'text_blocks': []
            },
            'metadata': {
                'extraction_method': 'docx_via_pdfplumber',
                'ocr_engine': ocr_engine,
                'avg_ocr_confidence': page['statistics']['avg_ocr_confidence'],
                'vlm_refined': False
            }
        })
        
    complete_document_path = output_dir / "complete_document.json"
    with open(complete_document_path, 'w', encoding='utf-8') as f:
        json.dump({'pages': pages_for_index}, f, ensure_ascii=False, indent=2)

    # 清理临时 PDF
    if temp_pdf.exists():
        temp_pdf.unlink()
        
    print(f"\n{'='*70}")
    print(f"✅ 处理完成 (方案B)")
    print(f"📊 统计: {page_count} 页, {total_tables} 个表格")
    print(f"📂 输出: {output_dir}")
    print(f"{'='*70}")
    
    return result

def main():
    parser = argparse.ArgumentParser(description='Process DOCX via PDF conversion')
    parser.add_argument('docx_file', help='Path to DOCX file')
    parser.add_argument('-o', '--output', help='Output directory', default=None)
    parser.add_argument('--ocr-engine', choices=['easy', 'paddle', 'vision'], 
                       default='paddle', help='OCR engine to use')
    
    args = parser.parse_args()
    
    docx_path = Path(args.docx_file)
    if not docx_path.exists():
        print(f"Error: File not found: {docx_path}")
        return 1
    
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = Path(f"{docx_path.stem}_docx_processed")
    
    try:
        process_docx(docx_path, output_dir, args.ocr_engine)
        return 0
    except Exception as e:
        print(f"❌ Fatal Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
