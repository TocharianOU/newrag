"""MinIO storage manager for document files"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from io import BytesIO

import structlog
from minio import Minio
from minio.error import S3Error

from src.config import config

logger = structlog.get_logger(__name__)


class MinIOStorage:
    """MinIO storage manager for uploading and managing document files"""
    
    def __init__(self, minio_config: Optional[Dict[str, Any]] = None):
        """
        Initialize MinIO storage manager
        
        Args:
            minio_config: MinIO configuration dict (uses global config if None)
        """
        self.config = minio_config or config.minio_config
        self.enabled = self.config.get('enabled', False)
        
        if not self.enabled:
            logger.info("MinIO storage is disabled in configuration")
            self.client = None
            return
        
        # Initialize MinIO client
        try:
            self.client = Minio(
                endpoint=self.config.get('endpoint', 'localhost:9000'),
                access_key=self.config.get('access_key', 'minioadmin'),
                secret_key=self.config.get('secret_key', 'minioadmin'),
                secure=self.config.get('secure', False)
            )
            
            self.bucket_name = self.config.get('bucket_name', 'rag-bucket')
            self.public_url = self.config.get('public_url', 'http://localhost:9000')
            
            # Ensure bucket exists
            self._ensure_bucket_exists()
            
            logger.info("✅ MinIO storage initialized", 
                       endpoint=self.config.get('endpoint'),
                       bucket=self.bucket_name)
            
        except Exception as e:
            logger.error("Failed to initialize MinIO client", error=str(e))
            self.client = None
            self.enabled = False
    
    def _ensure_bucket_exists(self):
        """Ensure the bucket exists, create if it doesn't"""
        if not self.client:
            return
        
        try:
            if not self.client.bucket_exists(bucket_name=self.bucket_name):
                logger.info(f"Creating bucket: {self.bucket_name}")
                self.client.make_bucket(bucket_name=self.bucket_name)
                logger.info(f"✅ Bucket created: {self.bucket_name}")
        except S3Error as e:
            logger.error("Failed to create bucket", error=str(e), bucket=self.bucket_name)
            raise
    
    def upload_file(self, local_path: Path, object_name: str, 
                   content_type: Optional[str] = None) -> Optional[str]:
        """
        Upload a file to MinIO
        
        Args:
            local_path: Local file path
            object_name: Object name in MinIO (path/filename)
            content_type: Content type (auto-detect if None)
            
        Returns:
            Public URL of uploaded file, or None if failed/disabled
        """
        if not self.enabled or not self.client:
            return None
        
        if not local_path.exists():
            logger.warning("File not found, skipping upload", file=str(local_path))
            return None
        
        try:
            # Auto-detect content type if not provided
            if content_type is None:
                content_type = self._get_content_type(local_path)
            
            # Upload file
            with open(local_path, 'rb') as f:
                file_data = f.read()
                self.client.put_object(
                    bucket_name=self.bucket_name,
                    object_name=object_name,
                    data=BytesIO(file_data),
                    length=len(file_data),
                    content_type=content_type
                )
            
            # Generate public URL
            url = f"{self.public_url}/{self.bucket_name}/{object_name}"
            
            logger.debug("File uploaded to MinIO",
                        local_path=str(local_path),
                        object_name=object_name,
                        size=len(file_data),
                        url=url)
            
            return url
            
        except Exception as e:
            logger.error("Failed to upload file to MinIO",
                        error=str(e),
                        file=str(local_path),
                        object_name=object_name)
            return None
    
    def upload_directory(self, local_dir: Path, prefix: str) -> Dict[str, str]:
        """
        Upload all files in a directory to MinIO
        
        Args:
            local_dir: Local directory path
            prefix: Object name prefix (e.g., "doc_123/")
            
        Returns:
            Dict mapping local filenames to MinIO URLs
        """
        if not self.enabled or not self.client:
            return {}
        
        if not local_dir.exists() or not local_dir.is_dir():
            logger.warning("Directory not found", dir=str(local_dir))
            return {}
        
        uploaded_files = {}
        upload_patterns = self.config.get('upload_files', ['*'])
        
        logger.info("Starting directory upload to MinIO",
                   dir=str(local_dir),
                   prefix=prefix)
        
        for pattern in upload_patterns:
            for file_path in local_dir.glob(pattern):
                if file_path.is_file():
                    # Generate object name: prefix + filename
                    object_name = f"{prefix}/{file_path.name}"
                    url = self.upload_file(file_path, object_name)
                    
                    if url:
                        uploaded_files[file_path.name] = url
        
        logger.info(f"✅ Uploaded {len(uploaded_files)} files to MinIO",
                   dir=str(local_dir),
                   count=len(uploaded_files))
        
        return uploaded_files
    
    def get_public_url(self, object_name: str) -> str:
        """
        Get public URL for an object
        
        Args:
            object_name: Object name in MinIO
            
        Returns:
            Public URL
        """
        return f"{self.public_url}/{self.bucket_name}/{object_name}"
    
    def generate_presigned_url(self, object_name: str, 
                              expires_in_days: int = 7) -> Optional[str]:
        """
        Generate a presigned URL for temporary access
        
        Args:
            object_name: Object name in MinIO
            expires_in_days: Expiration time in days
            
        Returns:
            Presigned URL or None if failed/disabled
        """
        if not self.enabled or not self.client:
            return None
        
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                expires=timedelta(days=expires_in_days)
            )
            return url
        except Exception as e:
            logger.error("Failed to generate presigned URL",
                        error=str(e),
                        object_name=object_name)
            return None
    
    def delete_object(self, object_name: str) -> bool:
        """
        Delete an object from MinIO
        
        Args:
            object_name: Object name to delete
            
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled or not self.client:
            return False
        
        try:
            self.client.remove_object(
                bucket_name=self.bucket_name,
                object_name=object_name
            )
            logger.debug("Object deleted from MinIO", object_name=object_name)
            return True
        except Exception as e:
            logger.error("Failed to delete object from MinIO",
                        error=str(e),
                        object_name=object_name)
            return False
    
    def delete_directory(self, prefix: str) -> int:
        """
        Delete all objects with a given prefix (directory)
        
        Args:
            prefix: Object name prefix
            
        Returns:
            Number of objects deleted
        """
        if not self.enabled or not self.client:
            return 0
        
        try:
            objects = self.client.list_objects(
                bucket_name=self.bucket_name,
                prefix=prefix,
                recursive=True
            )
            
            deleted_count = 0
            for obj in objects:
                if self.delete_object(obj.object_name):
                    deleted_count += 1
            
            logger.info(f"Deleted {deleted_count} objects from MinIO", prefix=prefix)
            return deleted_count
            
        except Exception as e:
            logger.error("Failed to delete directory from MinIO",
                        error=str(e),
                        prefix=prefix)
            return 0
    
    def list_objects(self, prefix: str = "") -> List[str]:
        """
        List objects in MinIO with optional prefix
        
        Args:
            prefix: Object name prefix filter
            
        Returns:
            List of object names
        """
        if not self.enabled or not self.client:
            return []
        
        try:
            objects = self.client.list_objects(
                bucket_name=self.bucket_name,
                prefix=prefix,
                recursive=True
            )
            return [obj.object_name for obj in objects]
        except Exception as e:
            logger.error("Failed to list objects from MinIO",
                        error=str(e),
                        prefix=prefix)
            return []
    
    @staticmethod
    def _get_content_type(file_path: Path) -> str:
        """Determine content type from file extension"""
        content_types = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.pdf': 'application/pdf',
            '.json': 'application/json',
            '.txt': 'text/plain',
            '.html': 'text/html',
            '.xml': 'application/xml',
        }
        
        suffix = file_path.suffix.lower()
        return content_types.get(suffix, 'application/octet-stream')


# Global MinIO storage instance
minio_storage = MinIOStorage()

