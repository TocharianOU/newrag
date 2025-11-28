#!/usr/bin/env python3
"""
自适应两阶段 OCR 流水线
1. 第一阶段：300 DPI 全局识别
2. 第二阶段：对低置信度区域局部放大（600 DPI）
3. 输出完整的多层次结果
"""
import sys
import os
import json
import subprocess
from pathlib import Path
import cv2
import numpy as np


class AdaptiveOCRPipeline:
    """自适应 OCR 处理流水线"""
    
    def __init__(self, ocr_engine='easy', confidence_threshold=0.7):
        """
        Args:
            ocr_engine: OCR 引擎 (vision/paddle/easy)
            confidence_threshold: 置信度阈值，低于此值的区域需要重新识别
        """
        self.ocr_engine = ocr_engine
        self.confidence_threshold = confidence_threshold
        
        # 脚本路径
        script_dir = Path("document_ocr_pipeline")
        self.extract_script = script_dir / "extract_document.py"
        self.visualize_script = script_dir / "visualize_extraction.py"
    
    def process_page(self, page, page_num, output_dir):
        """处理单个页面"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        print(f"{'='*80}")
        print(f"📄 Page {page_num} - Adaptive OCR Pipeline")
        print(f"{'='*80}")
        
        # ============ 阶段1：全局识别 (300 DPI) ============
        print(f"\n🔍 Stage 1: Global Recognition (300 DPI)")
        print("-" * 80)
        
        # 1.1 转换为 300 DPI 图片
        print(f"[1.1] Converting to 300 DPI...")
        img_300 = page.to_image(resolution=300)
        img_300_array = np.array(img_300.original)
        img_300_path = output_path / f"page_{page_num:03d}_300dpi.png"
        cv2.imwrite(str(img_300_path), cv2.cvtColor(img_300_array, cv2.COLOR_RGB2BGR),
                   [cv2.IMWRITE_PNG_COMPRESSION, 3])
        print(f"      ✓ Saved: {img_300_path.name}")
        
        # 1.2 全局 OCR
        print(f"[1.2] Running global OCR...")
        ocr_global_json = output_path / f"page_{page_num:03d}_global_ocr.json"
        subprocess.run([
            sys.executable,
            str(self.extract_script),
            str(img_300_path),
            "--ocr-engine", self.ocr_engine,
            "-o", str(ocr_global_json)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"      ✓ Saved: {ocr_global_json.name}")
        
        # 1.3 可视化全局结果
        print(f"[1.3] Creating global visualization...")
        vis_global_png = output_path / f"page_{page_num:03d}_global_visualized.png"
        subprocess.run([
            sys.executable,
            str(self.visualize_script),
            str(img_300_path),
            str(ocr_global_json),
            "-o", str(vis_global_png)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"      ✓ Saved: {vis_global_png.name}")
        
        # ============ 阶段2：分析低置信度区域 ============
        print(f"\n🎯 Stage 2: Analyzing Low-Confidence Regions")
        print("-" * 80)
        
        # 2.1 读取 OCR 结果
        with open(ocr_global_json, 'r', encoding='utf-8') as f:
            ocr_data = json.load(f)
        
        # 2.2 找出低置信度文本块
        low_conf_blocks = []
        for block in ocr_data.get('text_blocks', []):
            if block.get('confidence', 1.0) < self.confidence_threshold:
                low_conf_blocks.append(block)
        
        print(f"[2.1] Found {len(low_conf_blocks)} low-confidence regions (< {self.confidence_threshold})")
        
        if len(low_conf_blocks) == 0:
            print(f"      ✓ No refinement needed - all text has high confidence!")
            
            # 仍然需要 VLM 处理
            print(f"\n🤖 Stage 3: VLM Refinement (AI Understanding)")
            print("-" * 80)
            print(f"[3.1] Analyzing with VLM (this may take 10-30 seconds)...")
            
            script_dir = Path("document_ocr_pipeline")
            refine_script = script_dir / "refine_with_vlm.py"
            vlm_json_path = output_path / f"page_{page_num:03d}_vlm.json"
            
            subprocess.run([
                sys.executable,
                str(refine_script),
                str(img_300_path),
                str(ocr_global_json),
                "-o", str(vlm_json_path),
                "-p", str(page_num)
            ], check=True)
            
            print(f"      ✓ VLM analysis complete: {vlm_json_path.name}")
            
            return self._create_result_summary(page_num, output_path, has_regions=False,
                                              ocr_data=ocr_data, vlm_json=str(vlm_json_path.name))
        
        # 2.3 动态切分策略 - 合并邻近的低置信度区域
        regions = self._merge_nearby_regions(low_conf_blocks, img_300_array.shape)
        print(f"[2.2] Merged into {len(regions)} refinement regions")
        
        # ============ 阶段3：局部放大识别 (600 DPI) ============
        print(f"\n🔬 Stage 3: Refine Low-Confidence Regions (600 DPI)")
        print("-" * 80)
        
        # 3.1 转换为 600 DPI 图片（只用于切分）
        img_600 = page.to_image(resolution=600)
        img_600_array = np.array(img_600.original)
        
        region_results = []
        for i, region in enumerate(regions, 1):
            region_id = i
            print(f"\n[3.{i}] Processing region {region_id}/{len(regions)}...")
            
            # 计算 600 DPI 下的坐标（放大 2 倍）
            x1 = int(region['x1'] * 2)
            y1 = int(region['y1'] * 2)
            x2 = int(region['x2'] * 2)
            y2 = int(region['y2'] * 2)
            
            # 添加边距（10%）
            margin_x = int((x2 - x1) * 0.1)
            margin_y = int((y2 - y1) * 0.1)
            x1 = max(0, x1 - margin_x)
            y1 = max(0, y1 - margin_y)
            x2 = min(img_600_array.shape[1], x2 + margin_x)
            y2 = min(img_600_array.shape[0], y2 + margin_y)
            
            # 切分区域
            region_img = img_600_array[y1:y2, x1:x2]
            
            # 保存区域图片
            region_img_path = output_path / f"page_{page_num:03d}_region_{region_id:02d}_600dpi.png"
            cv2.imwrite(str(region_img_path), cv2.cvtColor(region_img, cv2.COLOR_RGB2BGR),
                       [cv2.IMWRITE_PNG_COMPRESSION, 3])
            
            # OCR 识别
            region_ocr_json = output_path / f"page_{page_num:03d}_region_{region_id:02d}_ocr.json"
            subprocess.run([
                sys.executable,
                str(self.extract_script),
                str(region_img_path),
                "--ocr-engine", self.ocr_engine,
                "-o", str(region_ocr_json)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 可视化
            region_vis_png = output_path / f"page_{page_num:03d}_region_{region_id:02d}_visualized.png"
            subprocess.run([
                sys.executable,
                str(self.visualize_script),
                str(region_img_path),
                str(region_ocr_json),
                "-o", str(region_vis_png)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 统计改进情况
            with open(region_ocr_json, 'r', encoding='utf-8') as f:
                region_data = json.load(f)
            
            avg_conf = region_data.get('average_confidence', 0)
            text_count = region_data.get('text_blocks_count', 0)
            
            print(f"      ✓ Region {region_id}: {text_count} blocks, avg confidence: {avg_conf*100:.1f}%")
            
            region_results.append({
                "region_id": region_id,
                "bbox_300dpi": [region['x1'], region['y1'], region['x2'], region['y2']],
                "bbox_600dpi": [x1, y1, x2, y2],
                "image": str(region_img_path.name),
                "ocr_json": str(region_ocr_json.name),
                "visualized": str(region_vis_png.name),
                "text_blocks": text_count,
                "avg_confidence": avg_conf
            })
        
        # ============ 阶段4：VLM 精炼 ============
        print(f"\n🤖 Stage 4: VLM Refinement (AI Understanding)")
        print("-" * 80)
        
        # 4.1 调用 VLM 处理
        print(f"[4.1] Analyzing with VLM (this may take 10-30 seconds)...")
        script_dir = Path("document_ocr_pipeline")
        refine_script = script_dir / "refine_with_vlm.py"
        vlm_json_path = output_path / f"page_{page_num:03d}_vlm.json"
        
        subprocess.run([
            sys.executable,
            str(refine_script),
            str(img_300_path),
            str(ocr_global_json),
            "-o", str(vlm_json_path),
            "-p", str(page_num)
        ], check=True)
        
        print(f"      ✓ VLM analysis complete: {vlm_json_path.name}")
        
        # ============ 生成汇总结果 ============
        print(f"\n📊 Generating Summary")
        print("-" * 80)
        
        return self._create_result_summary(page_num, output_path, 
                                          has_regions=True, 
                                          region_results=region_results,
                                          ocr_data=ocr_data,
                                          vlm_json=str(vlm_json_path.name))
    
    def _merge_nearby_regions(self, blocks, img_shape, merge_threshold=50):
        """合并邻近的低置信度区域"""
        if not blocks:
            return []
        
        height, width = img_shape[:2]
        regions = []
        
        # 简单策略：按密度划分区域
        # 将图片分成网格，统计每个网格的低置信度文本块数量
        grid_size = 4
        grid = [[[] for _ in range(grid_size)] for _ in range(grid_size)]
        
        for block in blocks:
            bbox = block.get('bbox', [0, 0, width, height])
            center_x = (bbox[0] + bbox[2]) / 2
            center_y = (bbox[1] + bbox[3]) / 2
            
            grid_x = min(int(center_x / width * grid_size), grid_size - 1)
            grid_y = min(int(center_y / height * grid_size), grid_size - 1)
            
            grid[grid_y][grid_x].append(block)
        
        # 找出有文本的网格，创建区域
        for i in range(grid_size):
            for j in range(grid_size):
                if len(grid[i][j]) > 0:
                    # 计算这个网格的边界
                    x1 = j * width // grid_size
                    y1 = i * height // grid_size
                    x2 = (j + 1) * width // grid_size
                    y2 = (i + 1) * height // grid_size
                    
                    regions.append({
                        'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                        'block_count': len(grid[i][j])
                    })
        
        return regions
    
    def _create_result_summary(self, page_num, output_path, has_regions=False, 
                               region_results=None, ocr_data=None, vlm_json=None):
        """创建页面处理结果摘要"""
        summary = {
            "page_number": page_num,
            "stage1_global": {
                "resolution": "300 DPI",
                "image": f"page_{page_num:03d}_300dpi.png",
                "ocr_json": f"page_{page_num:03d}_global_ocr.json",
                "visualized": f"page_{page_num:03d}_global_visualized.png",
            }
        }
        
        if has_regions and region_results:
            summary["stage2_refined_regions"] = region_results
            summary["total_refined_regions"] = len(region_results)
        else:
            summary["stage2_refined_regions"] = []
            summary["total_refined_regions"] = 0
        
        if ocr_data:
            summary["statistics"] = {
                "total_text_blocks": len(ocr_data.get('text_blocks', [])),
                "average_confidence": ocr_data.get('average_confidence', 0),
                "low_confidence_blocks": len([b for b in ocr_data.get('text_blocks', []) 
                                             if b.get('confidence', 1.0) < self.confidence_threshold])
            }
        
        if vlm_json:
            summary["stage3_vlm"] = {
                "vlm_json": vlm_json
            }
        
        # 保存页面摘要
        summary_path = output_path / f"page_{page_num:03d}_summary.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        print(f"      ✓ Saved summary: {summary_path.name}")
        
        return summary


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Adaptive two-stage OCR pipeline")
    parser.add_argument("pdf_file", help="Path to PDF file")
    parser.add_argument("--ocr-engine", choices=['vision', 'paddle', 'easy'], default='easy',
                       help="OCR engine: 'easy' (默认), 'paddle' (多方向-慢但准), 'vision' (多角度-快且准)")
    parser.add_argument("--confidence", type=float, default=0.7,
                       help="Confidence threshold for refinement (default: 0.7)")
    parser.add_argument("--output-dir", type=str, default=None,
                       help="Output directory (default: PDF_name_adaptive)")
    
    args = parser.parse_args()
    
    input_file = Path(args.pdf_file).resolve()
    if not input_file.exists():
        print(f"❌ Error: File not found: {input_file}")
        sys.exit(1)
    
    # 切换到项目根目录
    base_dir = Path(__file__).parent.parent
    os.chdir(base_dir)
    
    # 创建输出目录
    if args.output_dir:
        output_path = Path(args.output_dir)
    else:
    output_dir = input_file.stem.replace(' ', '_') + "_adaptive"
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print("="*80)
    print("🚀 Adaptive Two-Stage OCR Pipeline")
    print("="*80)
    print(f"Source: {input_file.name}")
    print(f"OCR Engine: {args.ocr_engine.upper()}")
    print(f"Confidence Threshold: {args.confidence}")
    print(f"Output: {output_path}/")
    print()
    
    # 检查依赖
    try:
        import pdfplumber
    except ImportError:
        print("❌ Missing pdfplumber. Install: pip install pdfplumber")
        sys.exit(1)
    
    # 初始化流水线
    pipeline = AdaptiveOCRPipeline(
        ocr_engine=args.ocr_engine,
        confidence_threshold=args.confidence
    )
    
    # 处理 PDF
    all_pages_summary = []
    
    with pdfplumber.open(input_file) as pdf:
        total_pages = len(pdf.pages)
        print(f"📚 Total pages: {total_pages}\n")
        
        for page_num, page in enumerate(pdf.pages, 1):
            summary = pipeline.process_page(page, page_num, output_path)
            all_pages_summary.append(summary)
            print()
    
    # 生成完整文档摘要
    print("="*80)
    print("📄 Generating Complete Document Summary")
    print("="*80)
    
    complete_summary = {
        "source_file": str(input_file),
        "total_pages": total_pages,
        "ocr_engine": args.ocr_engine,
        "confidence_threshold": args.confidence,
        "pages": all_pages_summary
    }
    
    complete_json = output_path / "complete_adaptive_ocr.json"
    with open(complete_json, 'w', encoding='utf-8') as f:
        json.dump(complete_summary, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Saved: {complete_json.name}")
    
    # 生成完整文档 JSON（VLM 精炼结果）
    print("\n📄 Generating Complete Document JSON (VLM Refined)")
    print("-" * 80)
    
    pages_array = []
    for page_data in all_pages_summary:
        page_num = page_data["page_number"]
        vlm_json_file = output_path / f"page_{page_num:03d}_vlm.json"
        
        if vlm_json_file.exists():
            with open(vlm_json_file, 'r', encoding='utf-8') as f:
                vlm_result = json.load(f)
                
                # 添加文档级元数据
                page_obj = vlm_result.copy()
                page_obj["source_file"] = str(input_file)
                page_obj["source_file_name"] = input_file.name
                page_obj["output_directory"] = str(output_path.resolve())
                page_obj["total_pages"] = total_pages
                page_obj["ocr_engine"] = args.ocr_engine
                page_obj["ocr_confidence_threshold"] = args.confidence
                
                pages_array.append(page_obj)
    
    complete_document_json = output_path / "complete_document.json"
    with open(complete_document_json, 'w', encoding='utf-8') as f:
        json.dump(pages_array, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Saved: {complete_document_json.name}")
    print()
    print("="*80)
    print("✅ Processing Complete!")
    print("="*80)
    print(f"📁 Output directory: {output_path.absolute()}")
    print(f"\n生成的文件结构：")
    print(f"  阶段1 - 全局识别 (300 DPI):")
    print(f"    - page_XXX_300dpi.png")
    print(f"    - page_XXX_global_ocr.json")
    print(f"    - page_XXX_global_visualized.png")
    print(f"  阶段2 - 局部精炼 (600 DPI):")
    print(f"    - page_XXX_region_NN_600dpi.png")
    print(f"    - page_XXX_region_NN_ocr.json")
    print(f"    - page_XXX_region_NN_visualized.png")
    print(f"  阶段3 - VLM 精炼:")
    print(f"    - page_XXX_vlm.json (AI 理解后的完整结构化 JSON)")
    print(f"  页面摘要:")
    print(f"    - page_XXX_summary.json")
    print(f"  完整文档:")
    print(f"    - complete_adaptive_ocr.json (OCR 技术摘要)")
    print(f"    - complete_document.json (最终结果 - JSON List 格式)")


if __name__ == "__main__":
    main()

