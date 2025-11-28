#!/usr/bin/env python3
"""
Document text extraction using OCR and layout detection
Extract text from images/PDFs and save as structured JSON
"""
import os
import sys
import json
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import argparse

try:
    import easyocr
    HAS_EASYOCR = True
except ImportError:
    HAS_EASYOCR = False

try:
    from paddleocr import PaddleOCR
    HAS_PADDLEOCR = True
except ImportError:
    HAS_PADDLEOCR = False

try:
    import Vision
    from Foundation import NSURL
    from Quartz import CIImage
    import Cocoa
    HAS_VISION = True
except ImportError:
    HAS_VISION = False


class DocumentExtractor:
    """Extract text from documents with layout awareness"""
    
    def __init__(self, use_layout_detection: bool = False, ocr_engine: str = 'vision'):
        """
        Initialize document extractor
        
        Args:
            use_layout_detection: Whether to use layout detection for text ordering
            ocr_engine: OCR engine to use: 'vision' (Apple), 'paddle' (PaddleOCR), 'easy' (EasyOCR)
        """
        print("Initializing OCR provider...")
        
        # Apple Vision Framework (苹果设备最强 - 增强版：多角度识别)
        if ocr_engine == 'vision' and HAS_VISION:
            self.ocr_reader = None  # Vision 不需要初始化
            self.ocr_type = 'vision'
            print("✓ Apple Vision Framework initialized (增强版 - 支持多方向文字)")
        # PaddleOCR (针对电路图纸优化 - 使用最新 API)
        elif ocr_engine == 'paddle' and HAS_PADDLEOCR:
            self.ocr_reader = PaddleOCR(
                lang='ch',  # 中英混合
                use_textline_orientation=True,  # 启用文本方向检测（识别倒立文字）
                # det_limit_side_len=960,  # 默认值 960，速度最快
                det_db_thresh=0.3,  # 检测阈值
                det_db_box_thresh=0.5,  # 框阈值
                det_db_unclip_ratio=1.6,  # 框扩张系数（保留稍微大一点的框以优化大字）
            )
            self.ocr_type = 'paddle'
            print("✓ PaddleOCR initialized (中英混合 + 速度优先)")
        # EasyOCR (默认，最稳定)
        elif ocr_engine == 'easy' and HAS_EASYOCR:
            self.ocr_reader = easyocr.Reader(
                ['en', 'ch_sim'],  # 英文 + 简体中文
                gpu=False,
                quantize=True,  # 量化加速
            )
            self.ocr_type = 'easy'
            print("✓ EasyOCR initialized (中英混合)")
        else:
            # 自动回退
            if HAS_VISION:
                self.ocr_reader = None
                self.ocr_type = 'vision'
                print("✓ Apple Vision Framework initialized (fallback - 多角度识别)")
            elif HAS_EASYOCR:
                self.ocr_reader = easyocr.Reader(['en', 'ch_sim'], gpu=False, quantize=True)
                self.ocr_type = 'easy'
                print("✓ EasyOCR initialized (fallback)")
            elif HAS_PADDLEOCR:
                # 设置环境变量使用项目本地PaddleX模型
                import os
                paddlex_dir = get_project_root() / "models" / "paddlex"
                if paddlex_dir.exists():
                    os.environ['PADDLEX_HOME'] = str(paddlex_dir)
                
                self.ocr_reader = PaddleOCR(
                    lang='ch',
                    use_textline_orientation=True,
                    det_db_unclip_ratio=1.6
                )
                self.ocr_type = 'paddle'
                print("✓ PaddleOCR initialized (fallback + 速度优先)")
            else:
                raise ImportError("未找到可用的 OCR 引擎\n请安装: pip install easyocr 或 pip install paddleocr")
    
    def extract_from_image(self, image_path: str) -> Dict[str, Any]:
        """
        Extract text from image file
        
        Args:
            image_path: Path to image file
            
        Returns:
            Dict containing extracted text and metadata
        """
        print(f"\nProcessing image: {image_path}")
        
        # Read image
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Failed to read image: {image_path}")
        
        # Convert BGR to RGB
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        print("Running OCR...")
        # Extract text using OCR
        if self.ocr_type == 'vision':
            ocr_results = self._vision_ocr(image_path)
        elif self.ocr_type == 'paddle':
            ocr_results = self._paddle_ocr(image_rgb)
        else:
            ocr_results = self._easy_ocr(image_rgb)
        
        if not ocr_results:
            print("Warning: No text detected by OCR")
            return {
                "file": os.path.basename(image_path),
                "status": "no_text_detected",
                "text_blocks": [],
                "full_text": ""
            }
        
        print(f"OCR detected {len(ocr_results)} text regions")
        
        # Format OCR results (统一格式)
        text_blocks = []
        for item in ocr_results:
            try:
                bbox, text, confidence = item[0], item[1], item[2]
                
                # Calculate bbox
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                x1, x2 = min(xs), max(xs)
                y1, y2 = min(ys), max(ys)
                
                text_blocks.append({
                    "text": text.strip(),
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "confidence": float(confidence),
                    "center_x": float((x1 + x2) / 2),
                    "center_y": float((y1 + y2) / 2)
                })
            except Exception as e:
                print(f"Warning: Failed to process OCR item: {e}")
                continue
        
        # Sort text blocks by position
        print("Sorting text blocks by position...")
        sorted_blocks = self._sort_by_position(text_blocks)
        layout_regions = []
        
        # Build full text
        full_text = "\n".join([block["text"] for block in sorted_blocks])
        
        result = {
            "file": os.path.basename(image_path),
            "image_size": {
                "width": image.shape[1],
                "height": image.shape[0]
            },
            "status": "success",
            "text_blocks_count": len(sorted_blocks),
            "layout_regions_count": len(layout_regions),
            "text_blocks": sorted_blocks,
            "layout_regions": layout_regions if layout_regions else None,
            "full_text": full_text,
            "average_confidence": sum(b["confidence"] for b in sorted_blocks) / len(sorted_blocks) if sorted_blocks else 0
        }
        
        return result
    
    def extract_from_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Extract text from PDF file (page by page)
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of dicts, one per page
        """
        print(f"\nProcessing PDF: {pdf_path}")
        
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("PDFplumber is required for PDF processing. Install: pip install pdfplumber")
        
        results = []
        
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"PDF has {total_pages} pages")
            
            for page_num, page in enumerate(pdf.pages):
                print(f"\nProcessing page {page_num + 1}/{total_pages}...")
                
                # Convert page to image
                img = page.to_image()
                image_array = np.array(img.original)
                
                # Extract text using OCR
                if self.ocr_type == 'vision':
                    # Vision 需要文件路径，先保存临时图片
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                        import cv2
                        cv2.imwrite(tmp.name, cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR))
                        ocr_results = self._vision_ocr(tmp.name)
                elif self.ocr_type == 'paddle':
                    ocr_results = self._paddle_ocr(image_array)
                else:
                    ocr_results = self._easy_ocr(image_array)
                
                text_blocks = []
                for item in ocr_results:
                    try:
                        bbox, text, confidence = item[0], item[1], item[2]
                        
                        xs = [p[0] for p in bbox]
                        ys = [p[1] for p in bbox]
                        x1, x2 = min(xs), max(xs)
                        y1, y2 = min(ys), max(ys)
                        
                        text_blocks.append({
                            "text": text.strip(),
                            "bbox": [float(x1), float(y1), float(x2), float(y2)],
                            "confidence": float(confidence),
                            "center_x": float((x1 + x2) / 2),
                            "center_y": float((y1 + y2) / 2)
                        })
                    except:
                        continue
                
                # Sort text blocks
                sorted_blocks = self._sort_by_position(text_blocks)
                layout_regions = []
                
                full_text = "\n".join([block["text"] for block in sorted_blocks])
                
                page_result = {
                    "page_number": page_num + 1,
                    "status": "success",
                    "text_blocks_count": len(sorted_blocks),
                    "layout_regions_count": len(layout_regions),
                    "text_blocks": sorted_blocks,
                    "layout_regions": layout_regions if layout_regions else None,
                    "full_text": full_text,
                    "average_confidence": sum(b["confidence"] for b in sorted_blocks) / len(sorted_blocks) if sorted_blocks else 0
                }
                
                results.append(page_result)
        
        return results
    
    def _vision_ocr(self, image_path: str):
        """Apple Vision Framework 提取（苹果设备专用 - 增强版：支持多方向文字）"""
        if not HAS_VISION:
            raise RuntimeError("Apple Vision Framework 仅在 macOS/iOS 上可用")
        
        import cv2
        import tempfile
        
        # 读取原始图片
        img = cv2.imread(image_path)
        if img is None:
            print(f"Failed to read image: {image_path}")
            return []
        
        height, width = img.shape[:2]
        
        # 多角度识别策略（像 PaddleOCR 一样）
        all_results = {}  # 用字典存储，key 是文本内容，避免重复
        
        # 定义要测试的旋转角度
        rotation_angles = [0, 90, 180, 270]
        
        for angle in rotation_angles:
            # 旋转图片
            if angle == 0:
                rotated_img = img
                rotated_path = image_path
            else:
                # 旋转图片
                if angle == 90:
                    rotated_img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
                elif angle == 180:
                    rotated_img = cv2.rotate(img, cv2.ROTATE_180)
                elif angle == 270:
                    rotated_img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                
                # 保存临时旋转图片
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    cv2.imwrite(tmp.name, rotated_img)
                    rotated_path = tmp.name
            
            # 获取旋转后的图片尺寸
            rot_height, rot_width = rotated_img.shape[:2]
            
            # 创建图片 URL
            url = NSURL.fileURLWithPath_(str(rotated_path))
            
            # 创建文字识别请求（增强配置）
            request = Vision.VNRecognizeTextRequest.alloc().init()
            
            # 最高精度模式
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            
            # 多语言支持（中英混合）
            request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en-US", "en-GB"])
            
            # 启用语言校正
            request.setUsesLanguageCorrection_(True)
            
            # 启用自动语言检测
            request.setAutomaticallyDetectsLanguage_(True)
            
            # 设置最小文本高度（降低阈值以检测更小的文字）
            request.setMinimumTextHeight_(0.01)  # 默认 0.03，降低到 0.01
            
            # 创建请求处理器
            handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
            
            # 执行请求
            success, error = handler.performRequests_error_([request], None)
            
            if not success:
                if angle == 0:
                    print(f"Vision OCR failed at {angle}°: {error}")
                continue
            
            # 提取结果
            for observation in request.results():
                try:
                    text = observation.topCandidates_(1)[0].string()
                    confidence = observation.confidence()
                    bbox_norm = observation.boundingBox()
                    
                    # 转换归一化坐标为像素坐标（旋转后的坐标）
                    x_rot = bbox_norm.origin.x * rot_width
                    y_rot = (1 - bbox_norm.origin.y - bbox_norm.size.height) * rot_height
                    w_rot = bbox_norm.size.width * rot_width
                    h_rot = bbox_norm.size.height * rot_height
                    
                    # 将坐标转换回原始图片坐标系
                    if angle == 0:
                        x, y = x_rot, y_rot
                        w, h = w_rot, h_rot
                    elif angle == 90:
                        # 90度顺时针旋转的逆变换
                        x = y_rot
                        y = width - x_rot - w_rot
                        w, h = h_rot, w_rot
                    elif angle == 180:
                        x = width - x_rot - w_rot
                        y = height - y_rot - h_rot
                        w, h = w_rot, h_rot
                    elif angle == 270:
                        # 270度（90度逆时针）旋转的逆变换
                        x = height - y_rot - h_rot
                        y = x_rot
                        w, h = h_rot, w_rot
                    
                    # 转换为四个角点格式
                    bbox_points = [
                        [x, y],           # 左上
                        [x + w, y],       # 右上
                        [x + w, y + h],   # 右下
                        [x, y + h]        # 左下
                    ]
                    
                    # 使用文本内容作为 key，保留置信度最高的结果
                    text_key = text.strip()
                    if text_key:
                        if text_key not in all_results or confidence > all_results[text_key][2]:
                            all_results[text_key] = (bbox_points, text.strip(), float(confidence))
                    
                except Exception as e:
                    # 静默失败，不打印每个角度的错误
                    if angle == 0:
                        print(f"Warning: Failed to parse Vision result: {e}")
                    continue
            
            # 清理临时文件
            if angle != 0 and rotated_path != image_path:
                try:
                    import os
                    os.unlink(rotated_path)
                except:
                    pass
        
        # 转换为列表格式
        formatted = list(all_results.values())
        
        print(f"  Vision multi-angle OCR: detected {len(formatted)} unique text blocks")
        
        return formatted
    
    def _paddle_ocr(self, image):
        """PaddleOCR 提取（兼容最新版本 2024+）"""
        try:
            # 使用标准 predict 方法（新版本推荐）
            result = self.ocr_reader.predict(image)
        except AttributeError:
            # 如果 predict 不存在，尝试 ocr 方法
            try:
                result = self.ocr_reader.ocr(image)
            except:
                result = None
        
        formatted = []
        
        # 处理结果
        if result is None or not result:
            return formatted
        
        # result[0] 是 OCRResult 对象（类似字典）
        if isinstance(result, list) and len(result) > 0:
            ocr_result = result[0]
            
            # 新版 PaddleOCR (2024+) 输出格式：
            # - dt_polys: 检测到的多边形框
            # - rec_texts: 识别的文本列表
            # - rec_scores: 置信度列表
            if isinstance(ocr_result, dict):
                dt_polys = ocr_result.get('dt_polys', [])
                rec_texts = ocr_result.get('rec_texts', [])
                rec_scores = ocr_result.get('rec_scores', [])
                
                # 组合结果
                for i in range(min(len(dt_polys), len(rec_texts), len(rec_scores))):
                    try:
                        # 获取多边形框（numpy array 转为列表）
                        poly = dt_polys[i]
                        if hasattr(poly, 'tolist'):
                            bbox_points = poly.tolist()
                        else:
                            bbox_points = poly
                        
                        # 获取文本和置信度
                        text = str(rec_texts[i])
                        confidence = float(rec_scores[i])
                        
                        # 跳过空文本
                        if not text or not text.strip():
                            continue
                        
                        # 统一格式为 (bbox, text, confidence)
                        formatted.append((bbox_points, text.strip(), confidence))
                        
                    except Exception as e:
                        # 跳过解析失败的项
                        continue
                
            # 旧版格式：直接是列表 [[bbox, (text, score)], ...]
            elif isinstance(ocr_result, list):
                for line in ocr_result:
                    try:
                        if not line or len(line) < 2:
                            continue
                        
                        bbox_points = line[0]
                        text_info = line[1]
                        
                        if isinstance(text_info, (tuple, list)) and len(text_info) >= 2:
                            text = str(text_info[0])
                            confidence = float(text_info[1])
                        else:
                            text = str(text_info)
                            confidence = 1.0
                        
                        if not text or not text.strip():
                            continue
                        
                        formatted.append((bbox_points, text.strip(), confidence))
                        
                    except Exception as e:
                        continue
        
        return formatted
    
    def _easy_ocr(self, image):
        """EasyOCR 提取"""
        return self.ocr_reader.readtext(image)
    
    def _sort_by_position(self, text_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort text blocks by vertical then horizontal position"""
        return sorted(text_blocks, key=lambda x: (x["center_y"], x["center_x"]))
    
    def _sort_by_layout(self, text_blocks: List[Dict[str, Any]], 
                        layout_regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sort text blocks considering layout regions
        Similar to SmartResume's resort_page_text_with_layout
        """
        # Assign each text block to a layout region
        for text in text_blocks:
            tx_center = text["center_x"]
            ty_center = text["center_y"]
            assigned = False
            
            for idx, layout in enumerate(layout_regions):
                lx1, ly1, lx2, ly2 = layout["bbox"]
                if lx1 <= tx_center <= lx2 and ly1 <= ty_center <= ly2:
                    text["layout_idx"] = idx
                    text["layout_center_x"] = layout["center_x"]
                    text["layout_center_y"] = layout["center_y"]
                    assigned = True
                    break
            
            if not assigned:
                text["layout_idx"] = -1
                text["layout_center_x"] = tx_center
                text["layout_center_y"] = ty_center
        
        # Sort by layout region first, then by position within region
        sorted_blocks = sorted(
            text_blocks,
            key=lambda x: (
                x["layout_center_y"],
                x["layout_center_x"],
                x["center_y"],
                x["center_x"]
            )
        )
        
        # Clean up temporary fields
        for block in sorted_blocks:
            block.pop("layout_idx", None)
            block.pop("layout_center_x", None)
            block.pop("layout_center_y", None)
            block.pop("center_x", None)
            block.pop("center_y", None)
        
        return sorted_blocks
    
    def save_results(self, results: Any, output_path: str):
        """Save extraction results to JSON file"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        print(f"\nResults saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Extract text from documents using OCR and layout detection")
    parser.add_argument("input_file", help="Path to input file (image or PDF)")
    parser.add_argument("-o", "--output", help="Output JSON file path (default: input_file.json)")
    parser.add_argument("--ocr-engine", choices=['vision', 'paddle', 'easy'], default='vision',
                       help="OCR engine: 'vision' (Apple Vision, 默认), 'paddle' (PaddleOCR), 'easy' (EasyOCR)")
    parser.add_argument("--no-layout", action="store_true", help="Disable layout detection")
    parser.add_argument("--pretty", action="store_true", help="Pretty print the results to console")
    
    args = parser.parse_args()
    
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        return 1
    
    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix('.json')
    
    # Initialize extractor
    extractor = DocumentExtractor(use_layout_detection=not args.no_layout, ocr_engine=args.ocr_engine)
    
    # Extract based on file type
    file_ext = input_path.suffix.lower()
    
    try:
        if file_ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']:
            results = extractor.extract_from_image(str(input_path))
        elif file_ext == '.pdf':
            results = extractor.extract_from_pdf(str(input_path))
        else:
            print(f"Error: Unsupported file format: {file_ext}")
            print("Supported formats: .jpg, .jpeg, .png, .bmp, .tiff, .webp, .pdf")
            return 1
        
        # Save results
        extractor.save_results(results, str(output_path))
        
        # Pretty print if requested
        if args.pretty:
            print("\n" + "="*80)
            print("EXTRACTION RESULTS")
            print("="*80)
            
            if isinstance(results, list):
                # PDF results (multiple pages)
                for page_result in results:
                    print(f"\n--- Page {page_result['page_number']} ---")
                    print(f"Text blocks: {page_result['text_blocks_count']}")
                    print(f"Layout regions: {page_result['layout_regions_count']}")
                    print(f"Average confidence: {page_result['average_confidence']:.2%}")
                    print(f"\nFull text:\n{page_result['full_text']}")
            else:
                # Image results (single page)
                print(f"\nFile: {results['file']}")
                print(f"Status: {results['status']}")
                print(f"Text blocks: {results['text_blocks_count']}")
                print(f"Layout regions: {results.get('layout_regions_count', 0)}")
                print(f"Average confidence: {results['average_confidence']:.2%}")
                print(f"\nFull text:\n{results['full_text']}")
        
        print("\n✓ Extraction completed successfully!")
        return 0
        
    except Exception as e:
        print(f"\n✗ Error during extraction: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

