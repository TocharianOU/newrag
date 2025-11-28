#!/usr/bin/env python3
"""
Excel (.xlsx) 智能处理管道
策略：LibreOffice -> PDF -> OCR+VLM (保留格式和公式渲染)
直接调用 process_pdf_vlm.py 处理转换后的 PDF
"""

import sys
import json
import argparse
from pathlib import Path
import subprocess

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils import get_soffice_command

def process_excel(excel_path, output_dir, ocr_engine='vision'):
    """
    通用处理：转 PDF 后调用 PDF 处理流程 (OCR + VLM)
    支持: Excel, ODS, ODP, PPT (Legacy)
    """
    print(f"🚀 开始处理文档: {excel_path}")
    print(f"📂 输出目录: {output_dir}")
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = Path(excel_path)
    
    # ==================== 步骤 1: 文档 -> PDF (LibreOffice) ====================
    print(f"\n{'='*70}")
    print(f"📄 步骤 1: 转换文档为 PDF (LibreOffice)")
    print(f"{'='*70}")
    
    pdf_output = output_dir / f"{excel_path.stem}.pdf"
    
    # 获取 LibreOffice 命令
    soffice_cmd = get_soffice_command()
    if not soffice_cmd:
        raise RuntimeError("未找到 LibreOffice (soffice)。请安装 LibreOffice 并确保 soffice 命令在 PATH 中。")

    try:
        cmd = [
            soffice_cmd,
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', str(output_dir),
            str(excel_path)
        ]
        
        print(f"  🔄 执行: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice 转换失败: {result.stderr}")
        
        if not pdf_output.exists():
            raise FileNotFoundError(f"PDF 文件未生成: {pdf_output}")
        
        print(f"  ✓ PDF 已生成: {pdf_output}")
        
    except Exception as e:
        print(f"  ❌ PDF 转换失败: {e}")
        raise
    
    # ==================== 步骤 2: 调用 PDF 处理流程 (OCR + VLM) ====================
    print(f"\n{'='*70}")
    print(f"📄 步骤 2: 处理 PDF (OCR + VLM)")
    print(f"{'='*70}")
    
    try:
        pdf_processor = Path(__file__).parent / 'process_pdf_vlm.py'
        
        cmd = [
            sys.executable,
            str(pdf_processor),
            str(pdf_output),
            '--output-dir', str(output_dir),
            '--ocr-engine', ocr_engine
        ]
        
        print(f"  🔄 执行: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        # 输出处理日志（无论成败）
        if result.stdout:
            print("  STDOUT:", result.stdout)
        if result.stderr:
            print("  STDERR:", result.stderr)
        
        if result.returncode != 0:
            raise RuntimeError(f"PDF 处理失败 (返回码: {result.returncode})\nSTDERR: {result.stderr}\nSTDOUT: {result.stdout}")
        
        print(f"  ✓ PDF 处理完成")
        
    except Exception as e:
        print(f"  ❌ PDF 处理失败: {e}")
        raise
    
    # ==================== 步骤 3: 验证输出 ====================
    complete_doc = output_dir / "complete_document.json"
    
    if not complete_doc.exists():
        raise FileNotFoundError(f"complete_document.json 未生成")
    
    print(f"\n{'='*70}")
    print(f"✅ Excel 处理完成!")
    print(f"{'='*70}")
    print(f"📁 输出目录: {output_dir}")
    print(f"📄 完整文档: {complete_doc}")
    
    return 0


def main():
    parser = argparse.ArgumentParser(description='通用文档智能处理 (Excel/ODS/ODP/PPT -> PDF -> VLM)')
    parser.add_argument('excel_file', help='文件路径 (.xlsx, .xls, .ods, .odp, .ppt)')
    parser.add_argument('-o', '--output', help='输出目录', default='output')
    parser.add_argument('--ocr-engine', choices=['paddle', 'easy', 'vision'], 
                        default='vision', help='OCR 引擎')
    
    args = parser.parse_args()
    
    excel_path = Path(args.excel_file)
    if not excel_path.exists():
        print(f"❌ 文件不存在: {excel_path}")
        return 1
    
    if excel_path.suffix.lower() not in ['.xlsx', '.xls', '.ods', '.odp', '.ppt']:
        print(f"❌ 不支持的文件格式: {excel_path.suffix}")
        return 1
    
    try:
        return process_excel(excel_path, args.output, args.ocr_engine)
    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
