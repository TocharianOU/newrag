# AIOps RAG Knowledge Base

面向 IT 运维和安全场景的智能知识库系统，基于 LangChain 和 Elasticsearch 构建。

## 功能特点

- 🚀 **多格式支持**: PDF、Word、Excel、图片、文本等多种文档格式
- 🤖 **智能模型**: 支持 Embedding 和 Vision 模型，可配置多种 Provider
- 🔍 **混合检索**: 向量检索 + BM25 关键词检索
- 📦 **批量处理**: 支持单文件、批量上传、ZIP 压缩包
- 🌐 **Web 界面**: 现代化的拖拽上传和搜索界面
- 📊 **统计分析**: 知识库统计和可视化
- 🏷️ **元数据管理**: 丰富的元数据字段，支持分类、标签、来源系统等
- 🔧 **易于配置**: YAML 配置文件，支持环境变量覆盖

## 快速开始

### 环境要求

- Python >= 3.9
- Elasticsearch >= 8.0
- uv (Python 包管理器)

### 安装步骤

1. **克隆项目**

```bash
git clone <repository-url>
cd rag_knowledge_base
```

2. **安装依赖**

```bash
# 使用 uv 安装依赖
uv sync
```

3. **配置 Elasticsearch**

确保 Elasticsearch 已启动并安装 IK 中文分词插件：

```bash
# 安装 IK 分词插件
elasticsearch-plugin install https://github.com/medcl/elasticsearch-analysis-ik/releases/download/v8.x.x/elasticsearch-analysis-ik-8.x.x.zip
```

4. **配置应用**

复制配置文件并修改：

```bash
cp .env.example .env
# 编辑 .env 填入你的配置
```

主要配置项（`config.yaml`）：

- **Embedding 模型**: 配置本地 LM Studio 或 OpenAI API
- **Vision 模型**: 用于图片文档识别
- **Elasticsearch**: 连接信息和索引配置
- **Web 服务**: 端口和上传设置

5. **初始化索引**

```bash
python scripts/init_index.py
```

6. **启动 Web 服务**

```bash
python web/app.py
```

访问 http://localhost:8000

## 使用方式

### 方式 1: Web 界面

1. 打开浏览器访问 `http://localhost:8000`
2. 在 **Upload** 标签页上传文档
3. 在 **Search** 标签页搜索知识
4. 在 **Statistics** 标签页查看统计信息

### 方式 2: 命令行批量导入

```bash
# 导入单个文件
python scripts/ingest_documents.py document.pdf --category incident --tags "security,alert"

# 导入整个目录
python scripts/ingest_documents.py ./documents --recursive --category logs
```

### 方式 3: Python API

```python
from src.pipeline import ProcessingPipeline

# 初始化
pipeline = ProcessingPipeline()

# 处理文档
result = pipeline.process_file(
    "document.pdf",
    metadata={"category": "incident", "tags": ["security"]}
)

# 搜索
results = pipeline.search(
    query="如何处理安全告警",
    k=5,
    filters={"category": "incident"}
)
```

## 配置说明

### 模型配置

**Embedding 模型**（必需）:
```yaml
models:
  embedding:
    provider: lmstudio  # lmstudio / openai / custom
    api_url: http://localhost:1234/v1
    model_name: text-embedding-3-large
    dimensions: 1536
```

**Vision 模型**（可选，用于图片文档）:
```yaml
models:
  vision:
    enabled: true
    provider: lmstudio
    model_name: qwen/qwen3-vl-8b
```

### 文本切分

```yaml
text_splitting:
  chunk_size: 500  # 中文优化
  chunk_overlap: 50
  separators: ["\n\n", "\n", "。", "！", "？"]
```

### Elasticsearch

```yaml
elasticsearch:
  hosts: ["http://localhost:9200"]
  index_name: aiops_knowledge_base
  hybrid_search:
    enabled: true
    vector_weight: 0.7
    bm25_weight: 0.3
```

### 元数据字段

**基础字段**（自动提取）:
- filename, filepath, file_type
- created_at, updated_at, file_size
- checksum

**扩展字段**（用户可编辑）:
- author, category, tags
- version, department, description

**AIOps 专用字段**:
- severity (critical/high/medium/low/info)
- log_level (ERROR/WARN/INFO/DEBUG)
- event_type (incident/alert/log/document)
- source_system (prometheus/elk/splunk)

## API 文档

### 上传接口

**单文件上传**
```http
POST /upload
Content-Type: multipart/form-data

file: <file>
category: <string>
tags: <string>  # comma-separated
author: <string>
```

**批量上传**
```http
POST /upload_batch
Content-Type: multipart/form-data

files: <file[]>
category: <string>
tags: <string>
```

**ZIP 上传**
```http
POST /upload_zip
Content-Type: multipart/form-data

file: <zipfile>
category: <string>
```

### 搜索接口

```http
POST /search
Content-Type: application/json

{
  "query": "搜索关键词",
  "k": 5,
  "filters": {
    "category": "incident",
    "file_type": "pdf"
  },
  "use_hybrid": true
}
```

### 统计接口

```http
GET /stats

Response:
{
  "document_count": 1234,
  "index_size_bytes": 12345678,
  "categories": [...],
  "file_types": [...]
}
```

## 项目结构

```
rag_knowledge_base/
├── config.yaml              # 主配置文件
├── pyproject.toml          # uv 项目配置
├── README.md
├── src/                    # 核心模块
│   ├── config.py          # 配置加载
│   ├── models.py          # Embedding & Vision 模型
│   ├── document_processor.py  # 文档处理
│   ├── vector_store.py    # ES 向量存储
│   └── pipeline.py        # 处理流程
├── web/                    # Web 应用
│   ├── app.py            # FastAPI 后端
│   └── templates/
│       └── index.html    # 前端界面
├── schemas/
│   └── elasticsearch_mapping.json  # ES 索引映射
└── scripts/               # 工具脚本
    ├── init_index.py     # 初始化索引
    └── ingest_documents.py  # 批量导入
```

## 开发指南

### 安装开发依赖

```bash
uv sync --extra dev
```

### 运行测试

```bash
pytest tests/
```

### 代码格式化

```bash
black src/ web/
ruff check src/ web/
```

## 故障排查

### Elasticsearch 连接失败

1. 确认 ES 服务已启动：`curl http://localhost:9200`
2. 检查配置文件中的 hosts 配置
3. 确认防火墙和网络设置

### IK 分词器未安装

```bash
# 检查是否安装
curl http://localhost:9200/_cat/plugins

# 安装 IK 插件
elasticsearch-plugin install https://github.com/medcl/elasticsearch-analysis-ik/releases/...
```

### 模型连接失败

1. 确认 LM Studio 已启动并加载模型
2. 检查 API URL 和端口（默认 1234）
3. 测试 API：`curl http://localhost:1234/v1/models`

### 文档处理失败

1. 检查文件格式是否支持
2. 确认 Vision 模型已启用（图片文档）
3. 查看日志获取详细错误信息

## 性能优化

- **批量上传**: 使用批量接口而非单文件多次上传
- **文本切分**: 根据文档类型调整 chunk_size
- **向量维度**: 使用较小的 embedding 模型可提升速度
- **ES 配置**: 调整 refresh_interval 和 shard 数量

## 许可证

[添加许可证信息]

## 贡献指南

欢迎提交 Issue 和 Pull Request！

## 联系方式

[添加联系方式]

