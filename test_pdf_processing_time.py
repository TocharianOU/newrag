#!/usr/bin/env python3
"""
PDF 处理性能测试脚本
测试自适应OCR流水线的每个阶段耗时
"""
import sys
import time
from pathlib import Path
from datetime import datetime
import pdfplumber

# 添加路径
sys.path.insert(0, str(Path(__file__).parent / "document_ocr_pipeline"))
from adaptive_ocr_pipeline import AdaptiveOCRPipeline


class TimingReport:
    """时间记录报告器"""
    
    def __init__(self):
        self.records = []
        self.stage_times = {}
        self.current_stage = None
        self.stage_start = None
        
    def start_stage(self, stage_name: str):
        """开始一个阶段"""
        self.current_stage = stage_name
        self.stage_start = time.time()
        print(f"\n{'='*80}")
        print(f"⏱️  开始: {stage_name}")
        print(f"{'='*80}")
        
    def end_stage(self):
        """结束当前阶段"""
        if self.current_stage and self.stage_start:
            elapsed = time.time() - self.stage_start
            self.stage_times[self.current_stage] = elapsed
            print(f"\n✓ 完成: {self.current_stage}")
            print(f"  耗时: {elapsed:.2f} 秒 ({elapsed/60:.2f} 分钟)")
            self.current_stage = None
            self.stage_start = None
            
    def add_record(self, name: str, duration: float, details: str = ""):
        """添加一条记录"""
        self.records.append({
            'name': name,
            'duration': duration,
            'details': details
        })
        
    def print_summary(self):
        """打印汇总报告"""
        print("\n" + "="*80)
        print("📊 性能分析报告")
        print("="*80)
        
        total_time = sum(self.stage_times.values())
        
        print(f"\n⏱️  总耗时: {total_time:.2f} 秒 ({total_time/60:.2f} 分钟)")
        print("\n各阶段耗时详情:")
        print("-" * 80)
        
        for stage, duration in self.stage_times.items():
            percentage = (duration / total_time * 100) if total_time > 0 else 0
            bar_length = int(percentage / 2)
            bar = "█" * bar_length + "░" * (50 - bar_length)
            
            print(f"\n{stage}:")
            print(f"  {bar} {percentage:.1f}%")
            print(f"  耗时: {duration:.2f}秒 ({duration/60:.2f}分钟)")
        
        print("\n" + "="*80)
        print("💡 优化建议:")
        print("="*80)
        
        # 找出最耗时的阶段
        if self.stage_times:
            max_stage = max(self.stage_times.items(), key=lambda x: x[1])
            print(f"\n🔴 最耗时阶段: {max_stage[0]}")
            print(f"   占比: {max_stage[1]/total_time*100:.1f}%")
            print(f"   时间: {max_stage[1]:.2f}秒")
            
            if "VLM" in max_stage[0]:
                print("\n   建议优化:")
                print("   - 考虑使用更小的VLM模型（7B/14B代替30B）")
                print("   - 简化VLM的prompt")
                print("   - 使用本地量化模型（INT4/INT8）")
            elif "Region" in max_stage[0]:
                print("\n   建议优化:")
                print("   - 提高置信度阈值，减少需要重新识别的区域")
                print("   - 考虑并行处理多个区域")


def test_pdf_processing(pdf_path: str, output_dir: str = None, 
                         ocr_engine: str = 'easy', max_pages: int = None):
    """
    测试PDF处理性能
    
    Args:
        pdf_path: PDF文件路径
        output_dir: 输出目录
        ocr_engine: OCR引擎 (vision/easy/paddle)
        max_pages: 最大处理页数（None=处理所有页）
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"❌ PDF文件不存在: {pdf_path}")
        return
    
    # 确定输出目录
    if output_dir is None:
        output_dir = pdf_path.parent / f"{pdf_path.stem}_test_output"
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(exist_ok=True)
    
    # 初始化报告器
    report = TimingReport()
    
    print("="*80)
    print("🚀 PDF 处理性能测试")
    print("="*80)
    print(f"PDF文件: {pdf_path.name}")
    print(f"输出目录: {output_dir}")
    print(f"OCR引擎: {ocr_engine}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # 初始化流水线
    report.start_stage("初始化")
    pipeline = AdaptiveOCRPipeline(ocr_engine=ocr_engine, confidence_threshold=0.7)
    report.end_stage()
    
    # 打开PDF
    report.start_stage("打开PDF")
    start_time = time.time()
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if max_pages:
            total_pages = min(total_pages, max_pages)
        print(f"📄 PDF总页数: {len(pdf.pages)}")
        print(f"📄 将处理页数: {total_pages}")
        report.end_stage()
        
        # 逐页处理
        for i in range(total_pages):
            page_num = i + 1
            page = pdf.pages[i]
            
            stage_name = f"第 {page_num} 页处理"
            report.start_stage(stage_name)
            
            page_start = time.time()
            
            # 调用流水线处理
            try:
                result = pipeline.process_page(page, page_num, output_dir)
                
                page_elapsed = time.time() - page_start
                report.add_record(
                    f"Page {page_num}",
                    page_elapsed,
                    f"Regions: {result.get('total_refined_regions', 0)}"
                )
                
            except Exception as e:
                print(f"❌ 处理第 {page_num} 页时出错: {e}")
                import traceback
                traceback.print_exc()
            
            report.end_stage()
    
    # 打印汇总报告
    report.print_summary()
    
    print("\n" + "="*80)
    print(f"✅ 测试完成!")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"输出目录: {output_dir.absolute()}")
    print("="*80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="测试PDF处理性能")
    parser.add_argument("pdf", help="PDF文件路径")
    parser.add_argument("-o", "--output", help="输出目录")
    parser.add_argument("--ocr-engine", default="easy", 
                       choices=["vision", "easy", "paddle"],
                       help="OCR引擎 (默认: easy)")
    parser.add_argument("--max-pages", type=int, 
                       help="最大处理页数（用于快速测试）")
    
    args = parser.parse_args()
    
    test_pdf_processing(
        args.pdf,
        args.output,
        args.ocr_engine,
        args.max_pages
    )

