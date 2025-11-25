# SmartResume RAG 智能搜索 MCP 服务器

专为 SmartResume RAG 项目设计的 Elasticsearch 搜索服务，提供智能混合搜索（向量+BM25）和完整的 ES API 访问能力。

## ✨ 特性

### 🔍 智能混合搜索
- **自动向量化**: 查询文本自动转换为向量，无需手动处理 embedding
- **语义+关键词**: 结合向量搜索和 BM25 算法，提供最佳搜索结果
- **可配置权重**: 通过 config.yaml 调整向量和关键词搜索的权重比例
- **高亮显示**: 自动高亮匹配的文本片段

### 🛠️ 完整 ES API 访问
- 执行任意 Elasticsearch API 端点
- 支持自定义查询、聚合分析、索引管理
- 完全控制查询逻辑和参数

## 📦 安装

```bash
cd newrag-mcp
npm install
npm run build
```

## ⚙️ 配置

该服务从父目录的 `config.yaml` 自动加载配置。确保配置文件包含以下部分：

```yaml
models:
  embedding:
    provider: lmstudio
    api_url: http://localhost:1234/v1
    api_key: lm-studio
    model_name: text-embedding-qwen3-embedding-4b
    dimensions: 2560
    batch_size: 32
    timeout: 30

elasticsearch:
  hosts:
    - http://localhost:9200
  index_name: aiops_knowledge_base
  username: ""
  password: ""
  hybrid_search:
    enabled: true
    vector_weight: 0.7  # 向量搜索权重
    bm25_weight: 0.3    # BM25关键词权重
```

### 环境变量

```bash
# Elasticsearch 连接配置
ES_URL=http://localhost:9200
ES_USERNAME=           # 可选
ES_PASSWORD=           # 可选
ES_API_KEY=           # 可选

# MCP 传输模式
MCP_TRANSPORT=stdio   # 或 "http"
MCP_HTTP_HOST=localhost
MCP_HTTP_PORT=3000
```

## 🚀 使用方式

### Stdio 模式 (默认)

```bash
npm start
```

### HTTP 模式

```bash
MCP_TRANSPORT=http npm run start:http
```

访问健康检查：
```bash
curl http://localhost:3000/health
```

## 🔧 可用工具

### 1. hybrid_search - 智能混合搜索

自动执行向量+BM25混合搜索，大模型只需提供查询文本。

**参数:**
- `query` (必需): 搜索查询文本
- `index` (可选): 指定索引名称，默认使用配置文件中的索引
- `size` (可选): 返回结果数量，默认10条
- `min_score` (可选): 最低相关度分数阈值

**示例调用:**
```json
{
  "query": "如何配置 Elasticsearch 集群？",
  "size": 5,
  "min_score": 0.5
}
```

**自动处理步骤:**
1. 查询文本自动转换为向量 (调用配置的 embedding API)
2. 构建混合搜索查询 (向量 + BM25)
3. 执行搜索并返回高亮结果

### 2. execute_es_api - 执行 ES API

直接访问任意 Elasticsearch API 端点。

**参数:**
- `method` (必需): HTTP方法 (GET/POST/PUT/DELETE/HEAD)
- `path` (必需): API路径 (如 "_search", "my_index/_mapping")
- `params` (可选): URL查询参数
- `body` (可选): 请求体
- `headers` (可选): 自定义HTTP头

**示例调用:**

查看索引mapping:
```json
{
  "method": "GET",
  "path": "aiops_knowledge_base/_mapping"
}
```

执行自定义查询:
```json
{
  "method": "POST",
  "path": "aiops_knowledge_base/_search",
  "body": {
    "query": {
      "match": {
        "title": "运维手册"
      }
    },
    "size": 10
  }
}
```

聚合统计:
```json
{
  "method": "POST",
  "path": "aiops_knowledge_base/_search",
  "body": {
    "size": 0,
    "aggs": {
      "by_category": {
        "terms": {
          "field": "metadata.category.keyword"
        }
      }
    }
  }
}
```

## 📝 使用场景

### 场景1: 智能问答
使用 `hybrid_search` 工具，让大模型直接提供问题，系统自动完成向量化和混合搜索。

```
用户问题: "如何排查 Elasticsearch 内存溢出问题？"
→ hybrid_search 自动处理
→ 返回最相关的文档片段
```

### 场景2: 精确查询
需要精确控制查询逻辑时，使用 `execute_es_api` 工具。

```
需求: 查找所有告警级别为 critical 的文档
→ execute_es_api
→ 自定义 bool query + filter
```

### 场景3: 数据分析
使用 `execute_es_api` 执行聚合查询，分析文档分布、趋势等。

```
需求: 统计各类别文档数量
→ execute_es_api
→ terms aggregation
```

## 🔑 核心优势

1. **对大模型友好**: 
   - 混合搜索工具自动处理 embedding，大模型无需了解向量化细节
   - 只需提供查询文本，降低大模型的认知负担

2. **灵活性**: 
   - 保留完整 ES API 访问能力
   - 支持从简单搜索到复杂聚合的所有场景

3. **配置驱动**: 
   - 通过 config.yaml 统一管理所有配置
   - 支持动态调整搜索权重和参数

4. **自动化**: 
   - 自动从配置文件加载 embedding 模型设置
   - 自动生成向量并构建混合查询
   - 自动高亮匹配内容

## 📚 技术细节

### 混合搜索实现

```typescript
// 混合搜索查询结构
{
  bool: {
    should: [
      {
        script_score: {
          query: { match_all: {} },
          script: {
            source: "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
            params: { query_vector: [向量数据] }
          },
          boost: 0.7  // 向量权重
        }
      },
      {
        multi_match: {
          query: "查询文本",
          fields: ["content^2", "title^3", "metadata.*"],
          type: "best_fields",
          boost: 0.3  // BM25权重
        }
      }
    ]
  }
}
```

### Embedding 生成

```typescript
// 自动调用配置的 embedding API
POST {api_url}/embeddings
{
  "model": "text-embedding-qwen3-embedding-4b",
  "input": "查询文本"
}
```

## 🐛 故障排除

### 问题: config.yaml 未找到
确保 config.yaml 在以下位置之一:
- `../config.yaml` (父目录)
- `./config.yaml` (当前目录)
- `../../config.yaml` (上两级目录)

### 问题: Embedding 生成失败
检查:
1. LM Studio 是否运行在配置的端口
2. embedding 模型是否已加载
3. config.yaml 中的 api_url 和 model_name 是否正确

### 问题: 搜索结果不佳
调整 config.yaml 中的权重:
```yaml
hybrid_search:
  vector_weight: 0.8  # 提高语义搜索权重
  bm25_weight: 0.2    # 降低关键词权重
```

## 📄 许可证

Apache-2.0

## 🤝 贡献

这是 SmartResume RAG 项目的一部分，专门为智能文档检索设计。
