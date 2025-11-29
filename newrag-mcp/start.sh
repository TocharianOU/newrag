#!/bin/bash

# NewRAG Search MCP Server 启动脚本
# 注意: 请确保在父目录配置好 config.yaml

echo "🚀 Starting NewRAG Search MCP Server..."
echo ""

# 检查配置文件
if [ ! -f "../config.yaml" ]; then
    echo "⚠️  Warning: config.yaml not found in parent directory"
    echo "   The server will start but embedding generation may fail"
    echo ""
fi

# 启动服务器
echo ""
echo "Starting server..."
echo ""

npm start

