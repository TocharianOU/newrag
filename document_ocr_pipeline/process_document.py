#!/usr/bin/env python3
"""
完整的文档处理流程：
1. PDF → 分页PNG
2. OCR提取 → page_xxx_ocr.json
3. VLM精炼 → page_xxx_vlm.json（每一页都处理）
4. 可视化 → page_xxx_visualized.png
5. 汇总 → complete_document.json
"""
import sys
import os
from pathlib import Path
import subprocess
import json

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Process PDF document with OCR and VLM")
    parser.add_argument("pdf_file", help="Path to PDF file")
    parser.add_argument("--ocr-engine", choices=['vision', 'paddle', 'easy'], default='easy',
                       help="OCR engine: 'easy' (EasyOCR, 默认), 'paddle' (PaddleOCR, 多方向), 'vision' (Apple Vision, 增强版-多角度)")
    args = parser.parse_args()
    
    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)
    
    input_file = Path(args.pdf_file).resolve()
    if not input_file.exists():
        print(f"Error: File not found: {input_file}")
        sys.exit(1)
    
    # Change to project root
    base_dir = Path(__file__).parent.parent
    os.chdir(base_dir)
    
    # Create output directory
    output_dir = input_file.stem.replace(' ', '_')
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Check dependencies
    try:
        import pdfplumber
        import cv2
        import numpy as np
    except ImportError as e:
        print(f"Error: Missing dependency: {e}")
        sys.exit(1)
    
    # Scripts
    script_dir = Path("document_ocr_pipeline")
    extract_script = script_dir / "extract_document.py"
    refine_script = script_dir / "refine_with_vlm.py"
    visualize_script = script_dir / "visualize_extraction.py"
    
    pages_data = []
    
    print("="*80)
    print("📄 Document Processing Pipeline")
    print("="*80)
    
    with pdfplumber.open(input_file) as pdf:
        total_pages = len(pdf.pages)
        print(f"Source: {input_file.name}")
        print(f"Total pages: {total_pages}\n")
        
        for page_num, page in enumerate(pdf.pages, 1):
            print(f"{'='*80}")
            print(f"Processing Page {page_num}/{total_pages}")
            print(f"{'='*80}")
            
            # Step 1: Convert to image (300 DPI for high quality OCR)
            print(f"[1/4] Converting page to image...")
            img = page.to_image(resolution=600)
            img_array = np.array(img.original)
            img_path = output_path / f"page_{page_num:03d}.png"
            # Use PNG compression for high quality while managing file size
            cv2.imwrite(str(img_path), cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR), 
                       [cv2.IMWRITE_PNG_COMPRESSION, 3])
            print(f"      ✓ Saved: {img_path.name}")
            
            # Step 2: OCR extraction
            print(f"[2/4] OCR extraction (using {args.ocr_engine.upper()})...")
            ocr_json_path = output_path / f"page_{page_num:03d}_ocr.json"
            subprocess.run([
                sys.executable,
                str(extract_script),
                str(img_path),
                "--ocr-engine", args.ocr_engine,
                "-o", str(ocr_json_path)
            ], check=True, stdout=subprocess.DEVNULL)
            print(f"      ✓ Saved: {ocr_json_path.name}")
            
            # Step 3: VLM refinement (每一页都处理！)
            print(f"[3/4] VLM analysis (this may take 10-20 seconds)...")
            vlm_json_path = output_path / f"page_{page_num:03d}_vlm.json"
            subprocess.run([
                sys.executable,
                str(refine_script),
                str(img_path),
                str(ocr_json_path),
                "-o", str(vlm_json_path),
                "-p", str(page_num)
            ], check=True)
            print(f"      ✓ Saved: {vlm_json_path.name}")
            
            # Step 4: Visualization
            print(f"[4/4] Creating visualization...")
            vis_img_path = output_path / f"page_{page_num:03d}_visualized.png"
            subprocess.run([
                sys.executable,
                str(visualize_script),
                str(img_path),
                str(ocr_json_path),
                "-o", str(vis_img_path)
            ], check=True, stdout=subprocess.DEVNULL)
            print(f"      ✓ Saved: {vis_img_path.name}")
            
            pages_data.append({
                "page": page_num,
                "image": str(img_path),
                "ocr_json": str(ocr_json_path),
                "vlm_json": str(vlm_json_path),
                "visualized_image": str(vis_img_path)
            })
            print()
    
    # Final: Create complete_document.json
    print(f"{'='*80}")
    print("Creating complete document JSON...")
    print(f"{'='*80}")
    
    pages_array = []
    for page_data in pages_data:
        vlm_json_file = Path(page_data["vlm_json"])
        if vlm_json_file.exists():
            with open(vlm_json_file, 'r', encoding='utf-8') as f:
                vlm_result = json.load(f)
                
                # 添加文档级元数据
                page_obj = vlm_result.copy()
                page_obj["source_file"] = str(input_file)
                page_obj["source_file_name"] = input_file.name
                page_obj["output_directory"] = str(output_path.resolve())
                page_obj["total_pages"] = len(pages_data)
                
                pages_array.append(page_obj)
    
    complete_json_path = output_path / "complete_document.json"
    with open(complete_json_path, "w", encoding="utf-8") as f:
        json.dump(pages_array, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Processing complete!")
    print(f"📁 Output directory: {output_path}")
    print(f"📄 Complete document: {complete_json_path.name}")
    print(f"📊 Total pages processed: {len(pages_array)}")
    print(f"\nGenerated files per page:")
    print(f"  - page_XXX.png (原始页面图片)")
    print(f"  - page_XXX_ocr.json (OCR原始结果)")
    print(f"  - page_XXX_vlm.json (VLM精炼结果 - 包含页面描述和理解)")
    print(f"  - page_XXX_visualized.png (标注可视化)")

if __name__ == "__main__":
    main()
