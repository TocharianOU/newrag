# SmartResume - AIOps 智能知识库系统

基于 RAG (Retrieval-Augmented Generation) 的智能文档处理与问答系统，专为 AIOps 和运维场景设计。支持 PDF、DOCX、PPTX、Excel 等多种格式的智能解析、OCR 识别和语义检索。

## ✨ 核心特性

- **多格式支持**: 深度解析 PDF, DOCX, PPTX, Excel, 图片等多种格式。
- **智能 OCR**: 集成两阶段自适应 OCR (300/600 DPI) 和 VLM (视觉大模型) 纠错，精准还原文档内容。
- **结构化提取**: 自动识别并提取表格 (Markdown)、图片内容和元数据。
- **语义检索**: 基于 Elasticsearch 的混合检索 (向量 + 关键词)，支持页面级索引。
- **可视化交互**: React 前端提供文档预览、红框关键词定位、置信度提示。
- **一键启动**: 统一的开发环境启动脚本，简化前后端联调。

## 🛠️ 环境要求

- **操作系统**: macOS (推荐), Linux, Windows (WSL2)
- **Python**: 3.10+
- **Node.js**: 18+ (前端开发)
- **外部依赖**:
  - **LibreOffice**: 必选。用于将 DOCX/PPTX/Excel 转换为 PDF 以保证格式精准。
    - **macOS**: `brew install --cask libreoffice`
    - **Ubuntu/Debian**: `sudo apt install libreoffice`
    - **Windows**: 下载安装包安装，并确保 `soffice.exe` 在系统 PATH 中。
  - **Elasticsearch**: 8.x (向量存储)
  - **MinIO**: (可选) 对象存储，用于存放大文件和图片
  - **LM Studio / OpenAI**: 提供 Embedding 和 VLM 模型服务

## 🚀 快速开始

### 1. 安装依赖

推荐使用 `uv` 进行 Python 依赖管理：

```bash
# 安装 uv (如果尚未安装)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装项目依赖
uv sync
```

前端依赖：

```bash
cd frontend
npm install
```

### 2. 配置文件

项目根目录下 `config.yaml` 包含了所有核心配置：

- **模型配置**: 设置 Embedding 和 VLM 模型的 API 地址 (默认兼容 LM Studio)。
- **Web 配置**: 设置前后端端口 (默认后端 8081, 前端 3001)。
- **Elasticsearch**: 设置 ES 连接地址。

### 3. 启动服务

使用统一启动脚本一键运行前后端：

```bash
# 在项目根目录执行
uv run python dev.py
```

启动成功后访问：
- **前端页面**: [http://localhost:3001](http://localhost:3001)
- **后端 API**: [http://localhost:8081](http://localhost:8081)

## 📂 项目结构

```
SmartResume/
├── config.yaml                 # 核心配置文件
├── dev.py                      # 一键启动脚本
├── document_ocr_pipeline/      # 文档处理核心流水线 (OCR, VLM)
│   ├── process_docx.py         # DOCX 处理逻辑 (XML + OCR)
│   ├── process_pdf_vlm.py      # PDF 处理逻辑 (OCR + VLM 修正)
│   ├── process_pptx.py         # PPTX 处理逻辑
│   └── adaptive_ocr_pipeline.py # 自适应 OCR 引擎
├── frontend/                   # React 前端项目
├── src/                        # 后端核心逻辑
│   ├── document_processor.py   # 文档加载与切分
│   ├── vector_store.py         # Elasticsearch 交互
│   └── models.py               # 模型接口封装
├── web/                        # FastAPI 后端应用
│   ├── app.py                  # 应用入口
│   └── handlers/               # 异步任务处理器
└── ...
```

## 📝 注意事项

- **LibreOffice 设置**: 如果系统无法自动找到 `soffice` 命令，可以通过设置环境变量 `SOFFICE_PATH` 来指定路径。
  ```bash
  export SOFFICE_PATH="/path/to/your/soffice"
  ```
- **DOCX 处理**: DOCX 文件会优先提取 XML 文本以保证准确性，同时生成 OCR 结果用于辅助定位插图文字。正文搜索准确，但正文可能无红框定位。
- **文件名编码**: 上传 ZIP 包时，系统会自动尝试修复中文文件名的编码问题。
- **端口冲突**: 如果端口被占用，请修改 `config.yaml` 中的 `web.port` 和 `web.frontend_port`。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
