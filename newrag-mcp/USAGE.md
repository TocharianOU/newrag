# SmartResume RAG Search MCP Server 使用指南

## 快速开始

### 1. 安装依赖
```bash
cd newrag-mcp
npm install
npm run build
```

### 2. 确保配置文件就绪
确保父目录有 `config.yaml` 文件，包含 embedding 和 Elasticsearch 配置。

### 3. 启动服务
```bash
./start.sh
# 或
npm start
```

## 在 Cursor/Claude Desktop 中配置

### Cursor 配置
在 Cursor 的 MCP 设置中添加：

```json
{
  "mcpServers": {
    "smartresume-rag-search": {
      "command": "node",
      "args": ["/Users/ablatazmat/Downloads/SmartResume/newrag-mcp/dist/index.js"],
      "env": {
        "ES_URL": "http://localhost:9200"
      }
    }
  }
}
```

### Claude Desktop 配置
在 `~/Library/Application Support/Claude/claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "smartresume-rag-search": {
      "command": "node",
      "args": ["/Users/ablatazmat/Downloads/SmartResume/newrag-mcp/dist/index.js"],
      "env": {
        "ES_URL": "http://localhost:9200"
      }
    }
  }
}
```

## 工具使用示例

### 1. 智能混合搜索 (hybrid_search)

**简单查询:**
```
请使用混合搜索查找: "如何配置 Kubernetes 集群"
```

大模型会自动调用：
```json
{
  "tool": "hybrid_search",
  "query": "如何配置 Kubernetes 集群",
  "size": 5
}
```

**指定索引和过滤:**
```
在 aiops_knowledge_base 索引中搜索 "日志分析" 相关内容，只显示相关度 > 0.7 的结果
```

大模型会调用：
```json
{
  "tool": "hybrid_search",
  "query": "日志分析",
  "index": "aiops_knowledge_base",
  "size": 10,
  "min_score": 0.7
}
```

### 2. 直接 ES API 调用 (execute_es_api)

**查看索引结构:**
```
显示 aiops_knowledge_base 索引的 mapping
```

大模型会调用：
```json
{
  "tool": "execute_es_api",
  "method": "GET",
  "path": "aiops_knowledge_base/_mapping"
}
```

**自定义查询:**
```
查找所有标题包含 "运维" 且类别为 "手册" 的文档
```

大模型会调用：
```json
{
  "tool": "execute_es_api",
  "method": "POST",
  "path": "aiops_knowledge_base/_search",
  "body": {
    "query": {
      "bool": {
        "must": [
          {"match": {"title": "运维"}},
          {"term": {"metadata.category.keyword": "手册"}}
        ]
      }
    }
  }
}
```

**聚合统计:**
```
统计各个类别的文档数量
```

大模型会调用：
```json
{
  "tool": "execute_es_api",
  "method": "POST",
  "path": "aiops_knowledge_base/_search",
  "body": {
    "size": 0,
    "aggs": {
      "category_count": {
        "terms": {
          "field": "metadata.category.keyword",
          "size": 20
        }
      }
    }
  }
}
```

## 工作原理

### 混合搜索流程

```
用户查询: "如何排查网络问题？"
    ↓
[1] MCP Server 接收查询
    ↓
[2] 调用 Embedding API (从 config.yaml 读取配置)
    POST http://localhost:1234/v1/embeddings
    {
      "model": "text-embedding-qwen3-embedding-4b",
      "input": "如何排查网络问题？"
    }
    ↓
[3] 获取向量 [0.123, -0.456, 0.789, ...]
    ↓
[4] 构建混合查询
    - 向量搜索 (cosine similarity)
    - BM25 关键词搜索
    - 按权重合并 (默认 7:3)
    ↓
[5] 执行 Elasticsearch 查询
    ↓
[6] 返回高亮结果给大模型
```

### 权重调整

在 `config.yaml` 中调整搜索权重：

```yaml
elasticsearch:
  hybrid_search:
    vector_weight: 0.7   # 向量搜索权重 (语义理解)
    bm25_weight: 0.3     # BM25 关键词权重 (精确匹配)
```

**建议配置:**
- **语义优先** (适合问答): vector_weight=0.8, bm25_weight=0.2
- **均衡模式** (默认): vector_weight=0.7, bm25_weight=0.3  
- **精确优先** (适合查找): vector_weight=0.5, bm25_weight=0.5

## 常见问题

### Q: 搜索结果相关度不高？
A: 调整 config.yaml 中的权重配置，或使用 min_score 参数过滤低相关度结果。

### Q: Embedding 生成失败？
A: 检查 LM Studio 是否运行，embedding 模型是否已加载。

### Q: 想要更精确的搜索？
A: 使用 execute_es_api 工具，自定义 bool query 和 filter。

### Q: 如何搜索特定字段？
A: 使用 execute_es_api，在 query 中指定字段：
```json
{
  "query": {
    "match": {
      "metadata.filename": "运维手册.pdf"
    }
  }
}
```

### Q: 如何查看所有可用索引？
A: 使用 execute_es_api：
```json
{
  "method": "GET",
  "path": "_cat/indices?format=json"
}
```

## 最佳实践

1. **优先使用 hybrid_search**: 对于自然语言查询，让系统自动处理 embedding
2. **复杂查询用 execute_es_api**: 需要精确控制时使用完整 ES API
3. **调整权重优化结果**: 根据实际效果微调 vector_weight 和 bm25_weight
4. **使用 min_score 过滤**: 避免返回无关结果
5. **充分利用高亮**: hybrid_search 会自动高亮匹配内容

## 性能提示

- hybrid_search 会调用 embedding API，首次查询可能较慢
- 建议 size 参数不超过 50，避免返回过多结果
- 大规模聚合查询建议使用 execute_es_api 直接访问 ES

## 调试

### 启用详细日志
```bash
NODE_ENV=development npm start
```

### 测试 Embedding API
```bash
curl -X POST http://localhost:1234/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer lm-studio" \
  -d '{
    "model": "text-embedding-qwen3-embedding-4b",
    "input": "测试文本"
  }'
```

### 测试 Elasticsearch
```bash
curl http://localhost:9200/aiops_knowledge_base/_search?pretty \
  -H "Content-Type: application/json" \
  -d '{"query": {"match_all": {}}, "size": 1}'
```

## 支持

如有问题，请检查：
1. config.yaml 配置是否正确
2. LM Studio 是否运行且模型已加载
3. Elasticsearch 是否可访问
4. 查看控制台错误日志

