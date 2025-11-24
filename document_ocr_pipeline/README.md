# 文档OCR+VLM精炼流水线

这个文件夹包含完整的文档OCR和VLM精炼系统，可以独立使用。

## 📦 文件清单

### Python脚本
- `extract_document.py` - OCR文本提取主程序
- `refine_with_vlm.py` - VLM模型精炼主程序
- `visualize_extraction.py` - 可视化标注工具

### 配置文件
- `requirements-extract.txt` - Python依赖包
- `es_mapping.json` - Elasticsearch索引映射
- `USAGE.txt` - 详细使用说明

### 快捷脚本
- `extract.sh` - OCR提取快捷脚本
- `refine.sh` - VLM精炼快捷脚本

### 文档
- `DOCUMENT_OCR_PIPELINE.md` - 系统架构和技术说明

## 🚀 快速开始

### 1. 安装依赖

```bash
cd document_ocr_pipeline

# 创建虚拟环境
uv venv .venv

# 安装依赖
uv pip install -r requirements-extract.txt
```

### 2. OCR提取

```bash
source .venv/bin/activate
python extract_document.py your_image.png --pretty
```

### 3. VLM精炼

确保LM Studio运行在 http://localhost:1234

```bash
python refine_with_vlm.py your_image.png your_image.json --pretty
```

### 4. 导入ES（可选）

```bash
# 创建索引
curl -X PUT "localhost:9200/documents" \
  -H "Content-Type: application/json" \
  -d @es_mapping.json

# 导入文档
curl -X POST "localhost:9200/documents/_doc" \
  -H "Content-Type: application/json" \
  -d @your_image_es.json
```

## 📖 详细说明

请查看：
- `USAGE.txt` - 完整使用指南
- `DOCUMENT_OCR_PIPELINE.md` - 技术架构说明

## 🎯 技术栈

- EasyOCR - 文字识别
- YOLOv10 - 布局检测
- LM Studio - VLM推理
- Elasticsearch - 文档检索（可选）

---

**注意：** 需要从父目录的 `.venv` 环境运行，或重新创建虚拟环境。



