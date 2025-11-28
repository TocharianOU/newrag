# SmartResume RAG Knowledge Base

这是一个基于 AI 的智能知识库系统，支持多种文档格式（PDF, DOCX, PPTX, Excel, 图片等）的解析、OCR 识别和向量检索。

## 核心功能

- **多格式支持**: PDF, Word, PowerPoint, Excel, Images
- **智能 OCR**: 集成 PaddleOCR 和 VLM (Vision Language Model) 进行高精度文字识别
- **结构化提取**: 自动识别表格、元器件、键值对数据
- **混合检索**: 结合向量检索 (Vector Search) 和关键词检索 (BM25)
- **Elasticsearch**: 使用 ES 存储元数据和向量索引

## 快速开始

```bash
# 启动 Web 服务
uv run python web/app.py
```


