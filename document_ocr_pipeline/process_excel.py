#!/usr/bin/env python3
"""
Excel (.xlsx) 混合处理管道
策略：
1. 视觉层 (Preview)：LibreOffice -> PDF -> 预览图 (所见即所得)
2. 数据层 (RAG/Search)：Pandas -> Markdown 表格 (用于文本问答)
3. 结构化层 (Precise)：Pandas -> Key-Value List (用于 ES 精准过滤)
"""

import sys
import json
import argparse
from pathlib import Path
import subprocess
import pandas as pd
import pdfplumber
import cv2
import numpy as np

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from document_ocr_pipeline.extract_document import DocumentExtractor
from document_ocr_pipeline.visualize_extraction import visualize_extraction

def df_to_markdown(df):
    """将 DataFrame 转换为 Markdown 表格"""
    # 处理空值
    df = df.fillna("")
    # 转换为字符串
    df = df.astype(str)
    # 替换换行符
    df = df.replace(r'\n', ' ', regex=True)
    return df.to_markdown(index=False)

def df_to_structured_kv(df, sheet_name):
    """将 DataFrame 转换为 ES Nested Key-Value 列表"""
    kv_list = []
    df = df.fillna("")
    
    # 遍历每行
    for _, row in df.iterrows():
        for col_name, val in row.items():
            # 跳过空值或空列名
            if not str(col_name).strip() or val == "":
                continue
                
            kv_list.append({
                "key": str(col_name).strip(),
                "value": str(val).strip(),
                "sheet_name": sheet_name
            })
    return kv_list

def process_excel(excel_path, output_dir, ocr_engine='paddle'):
    """
    完整处理 Excel 文件
    """
    print(f"🚀 开始处理 Excel: {excel_path}")
    print(f"📂 输出目录: {output_dir}")
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = Path(excel_path)
    
    # ==================== 步骤 1: 使用 Pandas 提取高精度数据 ====================
    print(f"\n{'='*70}")
    print(f"📊 步骤 1: Pandas 深度数据提取 (Markdown + Structured KV)")
    print(f"{'='*70}")
    
    sheets_data = {} # 存储每个 Sheet 的 Markdown 和 KV
    all_structured_kv = [] # 汇总所有 KV
    
    try:
        # 读取所有 Sheets
        # header=0 默认第一行是表头，这对大多数报表适用
        # 对于复杂多层表头，这里简化处理，取第一行非空行
        excel_file = pd.ExcelFile(excel_path)
        
        for sheet_name in excel_file.sheet_names:
            print(f"  📑 处理 Sheet: {sheet_name}")
            df = excel_file.parse(sheet_name)
            
            # 1. 生成 Markdown (用于 Text RAG)
            if not df.empty:
                md_table = df_to_markdown(df)
                
                # 2. 生成 Structured KV (用于 ES 精准搜索)
                kv_data = df_to_structured_kv(df, sheet_name)
                
                sheets_data[sheet_name] = {
                    "markdown": md_table,
                    "kv_data": kv_data,
                    "row_count": len(df)
                }
                all_structured_kv.extend(kv_data)
                print(f"    ✓ 提取 {len(df)} 行数据, {len(kv_data)} 个KV对")
            else:
                print("    ⚠️  空 Sheet，跳过")
                
    except Exception as e:
        print(f"  ❌ Pandas 读取失败: {e}")
        return None

    # ==================== 步骤 2: LibreOffice 转换 PDF (获取视觉布局) ====================
    print(f"\n{'='*70}")
    print(f"📄 步骤 2: 生成预览图 (LibreOffice)")
    print(f"{'='*70}")
    
    temp_pdf = output_dir / f"{excel_path.stem}_temp.pdf"
    
    try:
        print(f"  ⏳ 转换 Excel 为 PDF...")
        # Excel 转 PDF 可能需要调整纸张方向，但 LibreOffice 默认会自动适应
        subprocess.run([
            '/Applications/LibreOffice.app/Contents/MacOS/soffice',
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', str(output_dir),
            str(excel_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        generated_pdf = output_dir / f"{excel_path.stem}.pdf"
        if generated_pdf.exists() and generated_pdf != temp_pdf:
            generated_pdf.rename(temp_pdf)
            
        print(f"  ✓ PDF 已生成: {temp_pdf.name}")
        
    except Exception as e:
        print(f"  ❌ 预览图生成失败: {e}")
        # 如果没有预览图，我们至少还有 Pandas 数据，不应该完全中断
        temp_pdf = None

    # ==================== 步骤 3: 逐页处理 PDF 并合并 Pandas 数据 ====================
    # 策略：
    # 1. 优先使用 PDF 提取的文本作为"物理页面"的内容。
    # 2. 将 Pandas 提取的 Markdown 表格附在第一页 (或者根据 Sheet 顺序附在不同页，但难以精确对应)。
    #    为了稳妥，我们将所有 Sheet 的 Markdown 汇总到 Page 1 的 text 中，
    #    并将其余页面的 text 设为 PDF 提取内容 (通常是分页后的表格片段)。
    # 3. 最重要的是：将 structured_content 放入 metadata，供 ES 全局索引。
    
    pages_data = []
    total_pages = 0
    
    if temp_pdf and temp_pdf.exists():
        with pdfplumber.open(temp_pdf) as pdf:
            total_pages = len(pdf.pages)
            print(f"  📚 总页数: {total_pages}")
            
            for page_num, page in enumerate(pdf.pages, 1):
                print(f"\n处理第 {page_num}/{total_pages} 页...")
                
                # 3.1 生成预览图
                img = page.to_image(resolution=300)
                preview_image = f"page_{page_num:03d}_300dpi.png"
                preview_path = output_dir / preview_image
                cv2.imwrite(str(preview_path), cv2.cvtColor(np.array(img.original), cv2.COLOR_RGB2BGR))
                print(f"  🖼️  预览图: {preview_image}")
                
                # 3.2 提取 PDF 文本 (作为上下文)
                pdf_text = page.extract_text() or ""
                
                # 3.3 组合最终文本
                final_text = pdf_text
                
                # 第一页特权：附上所有 Sheets 的 Markdown 高精度表格
                if page_num == 1:
                    final_text += "\n\n【完整结构化数据 (Pandas Source)】\n"
                    for sheet_name, data in sheets_data.items():
                        final_text += f"\n### Sheet: {sheet_name}\n"
                        final_text += data["markdown"]
                        final_text += "\n"
                
                # 3.4 构建 Page Data
                pages_data.append({
                    "page_number": page_num,
                    "image_filename": preview_image,
                    "image_path": str(preview_path),
                    "content": {
                        "full_text_cleaned": final_text,
                        "full_text_raw": final_text
                    },
                    "ocr_data": {"text_blocks": []}, # 暂不启用 OCR 以节省时间，除非需要
                    "metadata": {
                        "extraction_method": "excel_hybrid_pandas_pdf",
                        "avg_ocr_confidence": 1.0
                    }
                })
    else:
        # 如果 PDF 生成失败，创建一个虚拟页面存放数据
        print("  ⚠️  PDF生成失败，创建纯数据虚拟页")
        final_text = "\n\n【完整结构化数据 (Pandas Source)】\n"
        for sheet_name, data in sheets_data.items():
            final_text += f"\n### Sheet: {sheet_name}\n"
            final_text += data["markdown"] + "\n"
            
        pages_data.append({
            "page_number": 1,
            "image_filename": "placeholder.png",
            "content": {
                "full_text_cleaned": final_text,
                "full_text_raw": final_text
            },
            "metadata": {"extraction_method": "excel_pandas_only"}
        })
        total_pages = 1

    # ==================== 步骤 4: 输出 JSON (包含 structured_content) ====================
    
    # 这里的 trick 是：ES 索引时，通常是把 pages_for_index 里的每一项作为一个 Document。
    # 我们需要把 structured_content 放到每一页的 metadata 里吗？
    # 不，这会造成冗余。但为了搜索方便，我们通常希望搜到"任意一页"。
    # 最佳实践：将 structured_content 放入 metadata，这样每一页都带有这个 KV 属性，
    # 用户搜 "name: Luke" 时，会返回所有页面（或第一页）。
    
    # 为了避免冗余太重，我们只在第一页放入 structured_content？
    # 或者让 vector_store.py 处理。
    # 这里我们先把 structured_content 放在顶层，由 document_processor 决定如何分配。
    
    output_data = {
        "pages": pages_data,
        "structured_content": all_structured_kv # 顶层携带 KV 数据
    }
    
    complete_doc_path = output_dir / "complete_document.json"
    with open(complete_doc_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        
    print(f"\n{'='*70}")
    print(f"✅ Excel 处理完成")
    print(f"📊 统计: {total_pages} 页, {len(all_structured_kv)} 个结构化KV对")
    print(f"📂 输出: {complete_doc_path}")
    print(f"{'='*70}")
    
    return output_data

def main():
    parser = argparse.ArgumentParser(description='Process Excel file')
    parser.add_argument('excel_file', help='Path to XLSX file')
    parser.add_argument('-o', '--output', help='Output directory', default=None)
    
    args = parser.parse_args()
    excel_path = Path(args.excel_file)
    
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = Path(f"{excel_path.stem}_excel_processed")
        
    try:
        process_excel(excel_path, output_dir)
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())


