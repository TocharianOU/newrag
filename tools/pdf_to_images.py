#!/usr/bin/env python3
"""
PDF to Images Converter
将 PDF 文件按页拆分为多个单独的图片文件

Usage:
    python tools/pdf_to_images.py input.pdf [output_dir] [--dpi 300] [--format png]
"""

import sys
from pathlib import Path
from typing import Optional
import argparse

try:
    from pdf2image import convert_from_path
    from PIL import Image
except ImportError:
    print("❌ 缺少依赖库！请先安装：")
    print("   uv add pdf2image Pillow")
    sys.exit(1)


def pdf_to_images(
    pdf_path: str,
    output_dir: Optional[str] = None,
    dpi: int = 300,
    image_format: str = 'png'
) -> list[Path]:
    """
    将 PDF 文件转换为图片
    
    Args:
        pdf_path: PDF 文件路径
        output_dir: 输出目录（默认为 PDF 同目录下的 {pdf_name}_images/）
        dpi: 图片分辨率（默认 300）
        image_format: 图片格式，支持 png/jpg/jpeg（默认 png）
    
    Returns:
        生成的图片文件路径列表
    """
    # 验证输入文件
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise FileNotFoundError(f"❌ PDF 文件不存在: {pdf_path}")
    
    if pdf_file.suffix.lower() != '.pdf':
        raise ValueError(f"❌ 不是 PDF 文件: {pdf_path}")
    
    # 确定输出目录
    if output_dir is None:
        output_dir = pdf_file.parent / f"{pdf_file.stem}_images"
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 验证图片格式
    image_format = image_format.lower()
    if image_format not in ['png', 'jpg', 'jpeg']:
        raise ValueError(f"❌ 不支持的图片格式: {image_format}")
    
    print(f"📄 正在处理: {pdf_file.name}")
    print(f"📂 输出目录: {output_dir}")
    print(f"🔍 分辨率: {dpi} DPI")
    print(f"🖼️  格式: {image_format.upper()}")
    print()
    
    # 转换 PDF 为图片
    try:
        print("⏳ 正在转换...")
        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            fmt=image_format
        )
        
        total_pages = len(images)
        print(f"✅ 成功读取 {total_pages} 页\n")
        
        # 保存每一页
        saved_files = []
        for i, image in enumerate(images, start=1):
            # 生成文件名：原文件名_page_001.png
            output_file = output_dir / f"{pdf_file.stem}_page_{i:03d}.{image_format}"
            
            # 保存图片
            if image_format in ['jpg', 'jpeg']:
                # JPEG 不支持透明通道，转换为 RGB
                if image.mode in ('RGBA', 'LA', 'P'):
                    image = image.convert('RGB')
                image.save(output_file, 'JPEG', quality=95)
            else:
                image.save(output_file, 'PNG')
            
            saved_files.append(output_file)
            
            # 获取图片尺寸
            width, height = image.size
            file_size = output_file.stat().st_size / 1024  # KB
            
            print(f"  [{i}/{total_pages}] {output_file.name}")
            print(f"       尺寸: {width}x{height} px  |  大小: {file_size:.1f} KB")
        
        print(f"\n🎉 转换完成！共生成 {len(saved_files)} 张图片")
        print(f"📁 保存位置: {output_dir.absolute()}")
        
        return saved_files
        
    except Exception as e:
        print(f"\n❌ 转换失败: {str(e)}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description='将 PDF 文件按页拆分为多个图片',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法（输出到 PDF 同目录）
  python tools/pdf_to_images.py document.pdf
  
  # 指定输出目录
  python tools/pdf_to_images.py document.pdf ./output
  
  # 自定义分辨率和格式
  python tools/pdf_to_images.py document.pdf --dpi 200 --format jpg
  
  # 高质量输出（更大文件）
  python tools/pdf_to_images.py document.pdf --dpi 600 --format png
        """
    )
    
    parser.add_argument(
        'pdf_path',
        help='PDF 文件路径'
    )
    parser.add_argument(
        'output_dir',
        nargs='?',
        default=None,
        help='输出目录（默认为 {pdf_name}_images/）'
    )
    parser.add_argument(
        '--dpi',
        type=int,
        default=300,
        help='图片分辨率 DPI（默认 300，推荐范围 150-600）'
    )
    parser.add_argument(
        '--format',
        choices=['png', 'jpg', 'jpeg'],
        default='png',
        help='输出图片格式（默认 png）'
    )
    
    args = parser.parse_args()
    
    try:
        pdf_to_images(
            pdf_path=args.pdf_path,
            output_dir=args.output_dir,
            dpi=args.dpi,
            image_format=args.format
        )
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()







