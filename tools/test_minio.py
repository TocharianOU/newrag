#!/usr/bin/env python3
"""测试MinIO连接和基本操作"""

from minio import Minio
from minio.error import S3Error
import sys

def test_minio_connection():
    """测试MinIO连接"""
    
    # MinIO配置（根据你的实际情况调整）
    # MinIO API通常在9000端口，控制台在9001端口
    MINIO_ENDPOINT = "localhost:9000"  # API端口
    MINIO_ACCESS_KEY = "minioadmin"  # 默认值，请根据实际情况修改
    MINIO_SECRET_KEY = "minioadmin"  # 默认值，请根据实际情况修改
    BUCKET_NAME = "rag-bucket"
    
    print("🔗 Testing MinIO Connection...")
    print(f"   Endpoint: {MINIO_ENDPOINT}")
    print(f"   Bucket: {BUCKET_NAME}\n")
    
    try:
        # 创建MinIO客户端（secure=False表示不使用HTTPS）
        client = Minio(
            endpoint=MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False  # 本地开发环境不使用HTTPS
        )
        
        print("✅ MinIO client created successfully")
        
        # 检查bucket是否存在
        if client.bucket_exists(bucket_name=BUCKET_NAME):
            print(f"✅ Bucket '{BUCKET_NAME}' exists")
        else:
            print(f"⚠️  Bucket '{BUCKET_NAME}' does not exist, creating...")
            client.make_bucket(bucket_name=BUCKET_NAME)
            print(f"✅ Bucket '{BUCKET_NAME}' created successfully")
        
        # 列出bucket中的对象
        objects = list(client.list_objects(bucket_name=BUCKET_NAME, recursive=True))
        print(f"\n📊 Bucket contents: {len(objects)} objects")
        
        if objects:
            print("\nFirst 10 objects:")
            for obj in objects[:10]:
                print(f"  - {obj.object_name} ({obj.size} bytes)")
        
        # 测试上传一个小文件
        print("\n📤 Testing file upload...")
        test_content = b"Hello from SmartResume!"
        from io import BytesIO
        
        client.put_object(
            bucket_name=BUCKET_NAME,
            object_name="test/hello.txt",
            data=BytesIO(test_content),
            length=len(test_content),
            content_type="text/plain"
        )
        print("✅ Test file uploaded successfully")
        
        # 生成访问URL
        url = client.presigned_get_object(bucket_name=BUCKET_NAME, object_name="test/hello.txt")
        print(f"\n🔗 Access URL: {url}")
        
        # 删除测试文件
        client.remove_object(bucket_name=BUCKET_NAME, object_name="test/hello.txt")
        print("✅ Test file removed")
        
        print("\n" + "="*80)
        print("✅ MinIO connection test PASSED!")
        print("="*80)
        
        return True
        
    except S3Error as e:
        print(f"\n❌ MinIO S3 Error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = test_minio_connection()
    sys.exit(0 if success else 1)

