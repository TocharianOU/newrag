#!/bin/bash
# MinIO快速启动脚本

MINIO_DIR="$HOME/.minio"
DATA_DIR="$MINIO_DIR/data"

# 创建数据目录
mkdir -p "$DATA_DIR"

# 检查MinIO是否已安装
if ! command -v minio &> /dev/null; then
    echo "❌ MinIO未安装！"
    echo "📥 请运行以下命令安装："
    echo ""
    echo "  macOS: brew install minio/stable/minio"
    echo "  Linux: wget https://dl.min.io/server/minio/release/linux-amd64/minio && chmod +x minio && sudo mv minio /usr/local/bin/"
    echo ""
    exit 1
fi

echo "🚀 Starting MinIO..."
echo "📂 Data directory: $DATA_DIR"
echo "🌐 Console: http://localhost:9001"
echo "🔌 API: http://localhost:9000"
echo ""
echo "👤 Access Key: minioadmin"
echo "🔑 Secret Key: minioadmin"
echo ""

# 启动MinIO
MINIO_ROOT_USER=minioadmin \
MINIO_ROOT_PASSWORD=minioadmin \
minio server "$DATA_DIR" --console-address ":9001"
