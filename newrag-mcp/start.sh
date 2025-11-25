#!/bin/bash

# SmartResume RAG Search MCP Server 启动脚本

echo "🚀 Starting SmartResume RAG Search MCP Server..."
echo ""

# 检查配置文件
if [ ! -f "../config.yaml" ]; then
    echo "⚠️  Warning: config.yaml not found in parent directory"
    echo "   The server will start but embedding generation may fail"
    echo ""
fi

# 检查 Elasticsearch
ES_URL=${ES_URL:-http://localhost:9200}
echo "📡 Checking Elasticsearch connection at $ES_URL..."
if curl -s "$ES_URL" > /dev/null 2>&1; then
    echo "✓ Elasticsearch is running"
else
    echo "❌ Cannot connect to Elasticsearch at $ES_URL"
    echo "   Please start Elasticsearch or set ES_URL environment variable"
    exit 1
fi

# 设置环境变量
export ES_URL=${ES_URL:-http://localhost:9200}

# 启动服务器
echo ""
echo "Starting server in Stdio mode..."
echo "To use HTTP mode, run: MCP_TRANSPORT=http npm run start:http"
echo ""

npm start

