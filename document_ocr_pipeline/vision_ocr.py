#!/usr/bin/env python3
"""
使用苹果 Vision Framework 进行 OCR（macOS/iOS）
性能最强，准确率最高，速度最快
"""
import sys
import json
from pathlib import Path

try:
    import Vision
    from Foundation import NSURL
    from Quartz import CIImage
    HAS_VISION = True
except ImportError:
    HAS_VISION = False
    print("❌ Vision Framework 仅在 macOS/iOS 上可用")
    print("   当前系统不支持，请使用 EasyOCR 或 PaddleOCR")


def vision_ocr(image_path: str):
    """使用 Apple Vision 进行 OCR"""
    if not HAS_VISION:
        raise RuntimeError("Vision Framework not available on this system")
    
    # 创建图片
    url = NSURL.fileURLWithPath_(str(image_path))
    
    # 创建文字识别请求
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(["zh-Hans", "en-US"])  # 中英混合
    request.setUsesLanguageCorrection_(True)
    
    # 创建请求处理器
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    
    # 执行请求
    success = handler.performRequests_error_([request], None)
    
    if not success:
        return []
    
    # 提取结果
    results = []
    for observation in request.results():
        text = observation.topCandidates_(1)[0].string()
        confidence = observation.confidence()
        bbox = observation.boundingBox()
        
        # 转换坐标（Vision 使用归一化坐标）
        results.append({
            "text": text,
            "confidence": float(confidence),
            "bbox_normalized": {
                "x": float(bbox.origin.x),
                "y": float(bbox.origin.y),
                "width": float(bbox.size.width),
                "height": float(bbox.size.height)
            }
        })
    
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python vision_ocr.py <image_path>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    
    try:
        results = vision_ocr(image_path)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

