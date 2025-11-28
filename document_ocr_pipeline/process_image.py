#!/usr/bin/env python3
"""
图片文档智能 OCR 处理脚本（支持 VLM 修正）
支持：PNG, JPG, JPEG 等图片格式
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, Tuple
import structlog

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import config

# 初始化日志
logger = structlog.get_logger(__name__)

# 尝试导入 VLM
HAS_VLM = False
try:
    from src.models import VisionModel
    HAS_VLM = True
except Exception as e:
    logger.warning(f"VLM not available: {e}")


def should_use_vlm_refinement(ocr_data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    判断是否需要 VLM 修正
    
    Args:
        ocr_data: OCR 原始结果
    
    Returns:
        (是否需要修正, 原因, 统计信息)
    """
    text_blocks = ocr_data.get('text_blocks', [])
    
    if not text_blocks:
        return False, "无文本内容", {}
    
    # 统计分析
    confidences = [b.get('confidence', 0) for b in text_blocks if b.get('confidence', 0) > 0]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    
    # 检测乱码字符
    all_text = ' '.join([b.get('text', '') for b in text_blocks])
    garbled_chars = sum(1 for c in all_text if ord(c) > 0x4E00 and c in '�□▪︎◆■●○◇')
    garbled_ratio = garbled_chars / len(all_text) if all_text else 0.0
    
    # 检测文件列表模式
    lines = [b.get('text', '').strip() for b in text_blocks if b.get('text', '').strip()]
    short_lines = sum(1 for line in lines if len(line) < 50)
    is_file_list = (
        short_lines > 5 and 
        short_lines / len(lines) > 0.6 if lines else False
    ) or any(ext in all_text.lower() for ext in ['.tar', '.dmg', '.pkg', '.gz', 'elasticsearch', 'docker'])
    
    # 检测多行短文本
    is_multi_short_lines = len(lines) >= 5 and short_lines / len(lines) > 0.7 if lines else False
    
    # 检测思维导图/关系图（树形符号密度）
    tree_symbols = sum(all_text.count(s) for s in ['├', '└', '│', '──', '─'])
    arrow_symbols = sum(all_text.count(s) for s in ['→', '←', '↓', '↑', '⇒', '⇐', '▶', '◀'])
    is_mindmap = (tree_symbols > 5 or arrow_symbols > 3) and len(text_blocks) > 8
    
    stats = {
        'avg_confidence': avg_confidence,
        'garbled_ratio': garbled_ratio,
        'is_file_list': is_file_list,
        'is_multi_short_lines': is_multi_short_lines,
        'is_mindmap': is_mindmap,
        'tree_symbols_count': tree_symbols,
        'arrow_symbols_count': arrow_symbols,
        'total_blocks': len(text_blocks),
        'total_chars': len(all_text)
    }
    
    # 宽松介入策略（60-80% 覆盖率）
    if avg_confidence < 0.8:  # 80% 以下就修正
        return True, f"识别质量可提升 (置信度 {avg_confidence:.2f})", stats
    elif garbled_ratio > 0.005:  # 0.5% 乱码即触发
        return True, f"检测到乱码 ({garbled_ratio:.1%})", stats
    elif stats.get('is_mindmap', False):  # 思维导图
        return True, "检测到思维导图/关系图", stats
    elif is_file_list or is_multi_short_lines:  # 特殊格式
        return True, "检测到列表结构", stats
    
    return False, "质量良好", stats


def refine_text_with_vlm(
    image_path: Path,
    ocr_text: str,
    vlm_model,
    confidence_info: Dict[str, Any] = None
) -> str:
    """
    使用 VLM 修正 OCR 文本
    
    Args:
        image_path: 图片路径
        ocr_text: OCR 原始文本
        vlm_model: VisionModel 实例
        confidence_info: 置信度信息
    
    Returns:
        修正后的文本
    """
    if not HAS_VLM or not vlm_model:
        return ocr_text
    
    try:
        # 构建质量提示信息
        quality_note = ""
        context_hint = ""
        
        if confidence_info:
            avg_conf = confidence_info.get('avg_confidence', 0)
            garbled_ratio = confidence_info.get('garbled_ratio', 0)
            is_file_list = confidence_info.get('is_file_list', False)
            
            if avg_conf < 0.5:
                quality_note = f"\n注意：OCR 识别质量较低（平均置信度 {avg_conf:.1%}），可能存在较多错误。"
            if garbled_ratio > 0.03:
                quality_note += f"\n注意：检测到 {garbled_ratio:.1%} 的乱码字符，请参考图片修正。"
            if is_file_list:
                context_hint = "这是一个文件列表"
        
        # 构建修正策略提示
        correction_level = ""
        content_type_hint = ""
        if confidence_info:
            avg_conf = confidence_info.get('avg_confidence', 0)
            is_mindmap = confidence_info.get('is_mindmap', False)
            is_file_list = confidence_info.get('is_file_list', False)
            
            if avg_conf < 0.5:
                correction_level = "【激进修正模式】识别质量很低，需要大幅修正错别字和结构格式"
            elif avg_conf < 0.7:
                correction_level = "【中等修正模式】适度修正明显的错别字，保留大部分原文和结构格式"
            else:
                correction_level = "【保守修正模式】仅修正明显错误，保留格式和边距，保留原有结构格式"
            
            # 内容类型提示
            if is_mindmap:
                content_type_hint = "\n⚠️ **这是思维导图/关系图**，必须保留所有层级关系、分支结构、箭头方向！"
            elif is_file_list:
                content_type_hint = "\n⚠️ **这是文件列表/目录**，必须保留层级缩进和符号！"
        
        prompt = f"""请根据图片和 OCR 识别结果，修正以下文本中的错误：

OCR 原始结果：
{ocr_text}

识别质量信息：
{quality_note}
{correction_level}
{content_type_hint}

修正要求：
1. **错别字修正**（必须参考图片）：
   - 容器监控/应用监控/数据库监控 等IT术语
   - 常见错误：客器→容器、申间→空间、V志→日志、禺→域
   - 专有名词：CyberArk、Kong、API Gateway、CMDB

2. **格式保留**（禁止修改）：
   - 树形符号：├ │ └ ── 
   - 箭头符号：→ ← ↓ ↑ ⇒ ▶
   - 缩进层级：必须与原文一致
   - 换行位置：保持原有布局

3. **结构修复**（思维导图/关系图重点）：
   - **补充丢失的层级符号**（/, -, |, ├, └）
   - **恢复父子关系**（如 A → B → C 的流向）
   - **保持分支结构**（多个子节点必须全部展示）
   - 合并被错误分割的词语

4. **禁止行为**：
   - 不要添加原图中没有的内容
   - 不要改变节点之间的连接关系
   - 不要合并应该分开的分支
   - 不要删除看似重复但实际存在的内容

{f'提示：{context_hint}' if context_hint else ''}

请直接返回修正后的文本内容，不要有其他解释。"""

        logger.info("🤖 调用 VLM 修正文本...",
                   image=str(image_path.name),
                   ocr_length=len(ocr_text),
                   avg_confidence=confidence_info.get('avg_confidence', 0) if confidence_info else 0)
        
        response = vlm_model.extract_text_from_image(str(image_path), prompt)
        refined_text = response.get('text', ocr_text)
        
        # 基本验证：防止 VLM 幻觉或截断
        if len(refined_text) < len(ocr_text) * 0.3 or len(refined_text) > len(ocr_text) * 5:
            logger.warning("⚠️  VLM 修正结果长度异常，使用原始 OCR",
                          original_len=len(ocr_text),
                          refined_len=len(refined_text))
            return ocr_text
        
        logger.info("✅ VLM 修正完成",
                   original_len=len(ocr_text),
                   refined_len=len(refined_text),
                   change_ratio=f"{(len(refined_text)/len(ocr_text)-1)*100:+.1f}%")
        
        return refined_text
        
    except Exception as e:
        logger.error(f"❌ VLM 修正失败: {e}", image_path=str(image_path))
        return ocr_text


def process_image(
    image_path: Path,
    output_dir: Path,
    ocr_engine: str = 'vision'
) -> Dict[str, Any]:
    """
    处理单个图片文件
    
    Args:
        image_path: 图片路径
        output_dir: 输出目录
        ocr_engine: OCR 引擎
    
    Returns:
        处理结果字典
    """
    from document_ocr_pipeline.extract_document import DocumentExtractor
    from document_ocr_pipeline.visualize_extraction import visualize_extraction
    
    logger.info("=" * 80)
    logger.info("🖼️  开始处理图片文档", image=image_path.name, ocr_engine=ocr_engine)
    logger.info("=" * 80)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # ===== 阶段 1: 全局 OCR =====
    logger.info("📍 阶段 1: 全局 OCR 识别")
    
    extractor = DocumentExtractor(ocr_engine=ocr_engine)
    ocr_json_path = output_dir / "image_ocr.json"
    
    logger.info(f"  🔍 使用 {ocr_engine.upper()} 引擎...")
    ocr_result = extractor.extract_from_image(str(image_path))
    
    with open(ocr_json_path, 'w', encoding='utf-8') as f:
        json.dump(ocr_result, f, ensure_ascii=False, indent=2)
    
    text_blocks = ocr_result.get('text_blocks', [])
    logger.info(f"  ✅ 识别到 {len(text_blocks)} 个文本块")
    
    # 提取原始文本
    original_text = ocr_result.get('text', '')
    if not original_text and text_blocks:
        original_text = '\n'.join([b.get('text', '') for b in text_blocks if b.get('text')])
    
    logger.info(f"  📝 提取文本: {len(original_text)} 字符")
    
    # ===== 阶段 2: VLM 智能修正 =====
    logger.info("📍 阶段 2: VLM 智能修正判断")
    
    need_vlm, reason, stats = should_use_vlm_refinement(ocr_result)
    
    logger.info(f"  🎯 质量分析:", **stats)
    logger.info(f"  {'✅' if need_vlm else '❌'} VLM 修正: {reason}")
    
    final_text = original_text
    vlm_refined = False
    
    if need_vlm and HAS_VLM:
        try:
            vlm_config = config.vision_config
            if vlm_config.get('enabled', False):
                vlm_model = VisionModel(vlm_config)
                
                confidence_info = {
                    'avg_confidence': stats['avg_confidence'],
                    'garbled_ratio': stats['garbled_ratio'],
                    'is_file_list': stats.get('is_file_list', False),
                    'is_mindmap': stats.get('is_mindmap', False)
                }
                
                final_text = refine_text_with_vlm(
                    image_path=image_path,
                    ocr_text=original_text,
                    vlm_model=vlm_model,
                    confidence_info=confidence_info
                )
                
                if final_text != original_text:
                    vlm_refined = True
                    logger.info("  ✅ VLM 修正完成",
                               original_len=len(original_text),
                               refined_len=len(final_text))
            else:
                logger.info("  ⚠️  VLM 未启用，跳过修正")
        except Exception as e:
            logger.error(f"  ❌ VLM 修正失败: {e}")
            final_text = original_text
    
    # ===== 阶段 3: 生成可视化 =====
    logger.info("📍 阶段 3: 生成 OCR 可视化")
    
    visualized_path = output_dir / "image_visualized.png"
    visualize_extraction(str(image_path), str(ocr_json_path), str(visualized_path))
    logger.info(f"  ✅ 可视化图片: {visualized_path.name}")
    
    # ===== 阶段 4: 生成统计信息 =====
    logger.info("📍 阶段 4: 生成元数据")
    
    # 计算平均置信度
    confidences = [b.get('confidence', 0) for b in text_blocks if b.get('confidence', 0) > 0]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    
    statistics = {
        "total_text_blocks": len(text_blocks),
        "avg_ocr_confidence": round(avg_confidence, 3),
        "vlm_refined": vlm_refined,
        "ocr_engine": ocr_engine
    }
    
    # ===== 阶段 5: 构建最终文档 =====
    logger.info("📍 阶段 5: 构建最终文档")
    
    # 复制原始图片作为预览 (统一命名为 page_001_300dpi.png)
    import shutil
    preview_path = output_dir / "page_001_300dpi.png"
    shutil.copy(image_path, preview_path)
    
    # 构建页面数据
    page_data = {
        "page_number": 1,
        "statistics": statistics,
        "stage1_global": {
            "image": preview_path.name,
            "ocr_json": ocr_json_path.name,
            "visualized": visualized_path.name,
            "text_source": "ocr" + ("_vlm_refined" if vlm_refined else "")
        },
        "stage2_vlm": {
            "text_combined": final_text,
            "vlm_refined": vlm_refined,
            "original_text_length": len(original_text),
            "final_text_length": len(final_text)
        } if vlm_refined else None
    }
    
    complete_doc = {
        "source_file": str(image_path),
        "file_type": image_path.suffix.lower().lstrip('.'),
        "total_pages": 1,
        "ocr_engine": ocr_engine,
        "pages": [page_data]
    }
    
    # 保存完整文档 JSON
    complete_json_path = output_dir / "complete_adaptive_ocr.json"
    with open(complete_json_path, 'w', encoding='utf-8') as f:
        json.dump(complete_doc, f, ensure_ascii=False, indent=2)
    
    logger.info(f"  ✅ 元数据: {complete_json_path.name}")
    
    # 保存可搜索文本（用于 ES 索引）
    pages_for_index = [{
        'page_number': 1,
        'text': final_text,
        'text_blocks': text_blocks,
        'extraction_method': 'ocr_vlm_refined' if vlm_refined else 'ocr',
        'ocr_engine': ocr_engine,
        'avg_ocr_confidence': avg_confidence
    }]
    
    complete_document_path = output_dir / "complete_document.json"
    with open(complete_document_path, 'w', encoding='utf-8') as f:
        json.dump({'pages': pages_for_index}, f, ensure_ascii=False, indent=2)
    
    logger.info(f"  ✅ 索引文档: {complete_document_path.name}")
    
    logger.info("=" * 80)
    logger.info("🎉 图片处理完成!")
    logger.info(f"  📊 统计: {len(text_blocks)} 个文本块, 平均置信度 {avg_confidence:.1%}")
    logger.info(f"  {'✅' if vlm_refined else '❌'} VLM 修正: {reason}")
    logger.info("=" * 80)
    
    return {
        "status": "success",
        "output_dir": str(output_dir),
        "ocr_json": str(ocr_json_path),
        "visualized": str(visualized_path),
        "complete_json": str(complete_json_path),
        "text_length": len(final_text),
        "text_blocks_count": len(text_blocks),
        "avg_confidence": avg_confidence,
        "vlm_refined": vlm_refined
    }


def main():
    parser = argparse.ArgumentParser(description='图片文档智能 OCR 处理（支持 VLM 修正）')
    parser.add_argument('image_path', type=str, help='图片文件路径')
    parser.add_argument('--ocr-engine', type=str, default='vision',
                       choices=['vision', 'paddle', 'easy'],
                       help='OCR 引擎选择 (默认: vision)')
    parser.add_argument('-o', '--output-dir', type=str, default=None,
                       help='输出目录（默认：图片名_processed）')
    
    args = parser.parse_args()
    
    image_path = Path(args.image_path)
    if not image_path.exists():
        print(f"❌ 图片不存在: {image_path}")
        sys.exit(1)
    
    # 确定输出目录
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = image_path.parent / f"{image_path.stem}_processed"
    
    try:
        result = process_image(image_path, output_dir, args.ocr_engine)
        print(f"\n✅ 处理成功!")
        print(f"📁 输出目录: {result['output_dir']}")
        print(f"📝 文本长度: {result['text_length']} 字符")
        print(f"📊 文本块数: {result['text_blocks_count']} 个")
        print(f"🎯 平均置信度: {result['avg_confidence']:.1%}")
        print(f"🤖 VLM 修正: {'✅ 已应用' if result['vlm_refined'] else '❌ 未使用'}")
        
    except Exception as e:
        logger.error(f"❌ 处理失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

