#!/usr/bin/env python3
"""
PDF 快速模式性能测试脚本
测试快速模式（300 DPI OCR + VLM）的处理性能
"""
import sys
import time
from pathlib import Path
from datetime import datetime
import pdfplumber

# 添加路径
sys.path.insert(0, str(Path(__file__).parent / "document_ocr_pipeline"))
from adaptive_ocr_pipeline import AdaptiveOCRPipeline


class FastModeTimingReport:
    """快速模式时间记录报告器"""
    
    def __init__(self):
        self.page_times = []
        self.total_start = None
        
    def start_test(self):
        """开始测试"""
        self.total_start = time.time()
        
    def add_page_time(self, page_num: int, stage1_time: float, stage4_time: float, total_time: float):
        """添加页面耗时记录"""
        self.page_times.append({
            'page_num': page_num,
            'stage1_ocr': stage1_time,
            'stage4_vlm': stage4_time,
            'total': total_time
        })
        
    def print_summary(self):
        """打印汇总报告"""
        if not self.page_times:
            print("\n❌ 没有处理任何页面")
            return
            
        total_elapsed = time.time() - self.total_start if self.total_start else 0
        
        print("\n" + "="*80)
        print("📊 快速模式性能分析报告")
        print("="*80)
        
        # 总体统计
        total_pages = len(self.page_times)
        avg_per_page = sum(p['total'] for p in self.page_times) / total_pages
        total_stage1 = sum(p['stage1_ocr'] for p in self.page_times)
        total_stage4 = sum(p['stage4_vlm'] for p in self.page_times)
        
        print(f"\n⏱️  总耗时: {total_elapsed:.2f} 秒 ({total_elapsed/60:.2f} 分钟)")
        print(f"📄 处理页数: {total_pages}")
        print(f"⚡ 平均每页: {avg_per_page:.2f} 秒")
        
        # 阶段耗时分析
        print("\n" + "-" * 80)
        print("各阶段总耗时:")
        print("-" * 80)
        
        stage1_percent = (total_stage1 / total_elapsed * 100) if total_elapsed > 0 else 0
        stage4_percent = (total_stage4 / total_elapsed * 100) if total_elapsed > 0 else 0
        
        print(f"\n📥 Stage 1 (300 DPI 全局OCR):")
        print(f"   总耗时: {total_stage1:.2f}秒 ({total_stage1/60:.2f}分钟)")
        print(f"   占比: {stage1_percent:.1f}%")
        print(f"   平均: {total_stage1/total_pages:.2f}秒/页")
        
        print(f"\n🤖 Stage 4 (VLM 精炼):")
        print(f"   总耗时: {total_stage4:.2f}秒 ({total_stage4/60:.2f}分钟)")
        print(f"   占比: {stage4_percent:.1f}%")
        print(f"   平均: {total_stage4/total_pages:.2f}秒/页")
        
        # 每页详情
        print("\n" + "-" * 80)
        print("每页耗时详情:")
        print("-" * 80)
        print(f"{'页码':<8} {'OCR':<15} {'VLM':<15} {'总计':<15} {'进度':<10}")
        print("-" * 80)
        
        for i, page in enumerate(self.page_times):
            progress = f"{(i+1)/total_pages*100:.0f}%"
            print(f"Page {page['page_num']:<3} "
                  f"{page['stage1_ocr']:>6.2f}s ({page['stage1_ocr']/page['total']*100:>4.1f}%) "
                  f"{page['stage4_vlm']:>6.2f}s ({page['stage4_vlm']/page['total']*100:>4.1f}%) "
                  f"{page['total']:>6.2f}s         "
                  f"{progress:>6}")
        
        # 性能评估
        print("\n" + "="*80)
        print("💡 快速模式性能评估:")
        print("="*80)
        
        # 计算理论深度模式耗时（基于记忆中的数据）
        # 深度模式单页约125秒，其中Stage 3占67.3%（83秒）
        theoretical_deep_time = total_pages * 125
        time_saved = theoretical_deep_time - total_elapsed
        time_saved_percent = (time_saved / theoretical_deep_time * 100) if theoretical_deep_time > 0 else 0
        
        print(f"\n⚡ 快速模式实际耗时: {total_elapsed:.2f}秒 ({total_elapsed/60:.2f}分钟)")
        print(f"🐢 深度模式估计耗时: {theoretical_deep_time:.2f}秒 ({theoretical_deep_time/60:.2f}分钟)")
        print(f"✅ 节省时间: {time_saved:.2f}秒 ({time_saved/60:.2f}分钟)")
        print(f"📈 效率提升: {time_saved_percent:.1f}%")
        
        # 性能建议
        print("\n" + "-" * 80)
        print("优化建议:")
        print("-" * 80)
        
        if stage4_percent > 60:
            print("\n🔴 VLM 是主要瓶颈 (占比 {:.1f}%)".format(stage4_percent))
            print("   建议优化:")
            print("   - 考虑使用更小的VLM模型")
            print("   - 简化VLM的prompt")
            print("   - 使用本地量化模型（INT4/INT8）")
            print("   - 考虑批处理多个页面")
        
        if stage1_percent > 40:
            print("\n🟡 OCR 耗时较高 (占比 {:.1f}%)".format(stage1_percent))
            print("   建议优化:")
            print("   - 尝试不同的OCR引擎 (easy/vision/paddle)")
            print("   - 降低DPI到200（牺牲一点质量换速度）")
        
        print("\n" + "="*80)


def test_fast_mode(pdf_path: str, output_dir: str = None, 
                   ocr_engine: str = 'easy', max_pages: int = None):
    """
    测试快速模式性能
    
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
        output_dir = pdf_path.parent / f"{pdf_path.stem}_fast_mode_test"
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(exist_ok=True)
    
    # 初始化报告器
    report = FastModeTimingReport()
    
    print("="*80)
    print("🚀 PDF 快速模式性能测试")
    print("="*80)
    print(f"PDF文件: {pdf_path.name}")
    print(f"输出目录: {output_dir}")
    print(f"OCR引擎: {ocr_engine}")
    print(f"处理模式: ⚡ FAST (300 DPI OCR → VLM)")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # 初始化流水线（快速模式）
    print("\n初始化快速模式流水线...")
    pipeline = AdaptiveOCRPipeline(
        ocr_engine=ocr_engine, 
        confidence_threshold=0.7,
        processing_mode='fast'  # 关键：使用快速模式
    )
    print("✓ 流水线初始化完成\n")
    
    report.start_test()
    
    # 打开PDF
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if max_pages:
            total_pages = min(total_pages, max_pages)
        print(f"📄 PDF总页数: {len(pdf.pages)}")
        print(f"📄 将处理页数: {total_pages}")
        print()
        
        # 逐页处理
        for i in range(total_pages):
            page_num = i + 1
            page = pdf.pages[i]
            
            print(f"{'='*80}")
            print(f"⚡ 处理第 {page_num}/{total_pages} 页 (快速模式)")
            print(f"{'='*80}")
            
            page_start = time.time()
            
            # 调用流水线处理
            try:
                result = pipeline.process_page(page, page_num, output_dir)
                
                page_elapsed = time.time() - page_start
                
                # 提取各阶段耗时
                perf = result.get('performance', {})
                stage1_time = perf.get('stage1_global_ocr_seconds', 0)
                stage4_time = perf.get('stage4_vlm_seconds', 0)
                
                report.add_page_time(page_num, stage1_time, stage4_time, page_elapsed)
                
                print(f"\n✓ 第 {page_num} 页处理完成")
                print(f"  耗时: {page_elapsed:.2f}秒")
                print(f"  - OCR: {stage1_time:.2f}秒")
                print(f"  - VLM: {stage4_time:.2f}秒")
                
            except Exception as e:
                print(f"❌ 处理第 {page_num} 页时出错: {e}")
                import traceback
                traceback.print_exc()
            
            print()
    
    # 打印汇总报告
    report.print_summary()
    
    print("\n" + "="*80)
    print(f"✅ 快速模式测试完成!")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"输出目录: {output_dir.absolute()}")
    print("="*80)


def compare_modes():
    """打印快速模式vs深度模式对比说明"""
    print("\n" + "="*80)
    print("📊 快速模式 vs 深度模式对比")
    print("="*80)
    
    print("\n⚡ 快速模式 (FAST):")
    print("   阶段1: 300 DPI 全局OCR")
    print("   阶段2: ⚡ 跳过")
    print("   阶段3: ⚡ 跳过")
    print("   阶段4: VLM 精炼")
    print("   优点: 速度快，适合大批量处理")
    print("   预计: ~40秒/页")
    
    print("\n🔬 深度模式 (DEEP):")
    print("   阶段1: 300 DPI 全局OCR")
    print("   阶段2: 分析低置信度区域")
    print("   阶段3: 600 DPI 局部放大OCR")
    print("   阶段4: VLM 精炼")
    print("   优点: 精度高，适合重要文档")
    print("   预计: ~125秒/页")
    
    print("\n💡 使用建议:")
    print("   - 快速模式: 日常文档批量处理、预览扫描")
    print("   - 深度模式: 重要合同、精密图纸、复杂公式")
    print("="*80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="测试PDF快速模式性能",
        epilog="快速模式跳过区域放大处理，直接使用300 DPI OCR + VLM"
    )
    parser.add_argument("pdf", nargs='?', help="PDF文件路径")
    parser.add_argument("-o", "--output", help="输出目录")
    parser.add_argument("--ocr-engine", default="easy", 
                       choices=["vision", "easy", "paddle"],
                       help="OCR引擎 (默认: easy)")
    parser.add_argument("--max-pages", type=int, 
                       help="最大处理页数（用于快速测试）")
    parser.add_argument("--compare", action="store_true",
                       help="显示快速模式vs深度模式对比说明")
    
    args = parser.parse_args()
    
    # 如果没有提供PDF或者只是想看对比
    if args.compare or not args.pdf:
        compare_modes()
        if not args.pdf:
            print("\n💡 使用方法:")
            print(f"   python {Path(__file__).name} <PDF文件路径> [选项]")
            print(f"\n示例:")
            print(f"   python {Path(__file__).name} document.pdf")
            print(f"   python {Path(__file__).name} document.pdf --max-pages 1")
            print(f"   python {Path(__file__).name} document.pdf --ocr-engine vision")
            sys.exit(0)
    
    test_fast_mode(
        args.pdf,
        args.output,
        args.ocr_engine,
        args.max_pages
    )

