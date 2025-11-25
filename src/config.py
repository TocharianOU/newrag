"""Configuration management module"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Configuration class for RAG Knowledge Base"""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration
        
        Args:
            config_path: Path to config.yaml file
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()
        self._apply_env_overrides()
    
    def _load_config(self):
        """Load configuration from YAML file"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)
    
    def _apply_env_overrides(self):
        """Apply environment variable overrides"""
        # Elasticsearch
        if os.getenv('ES_HOST'):
            self._config['elasticsearch']['hosts'] = [os.getenv('ES_HOST')]
        if os.getenv('ES_USERNAME'):
            self._config['elasticsearch']['username'] = os.getenv('ES_USERNAME')
        if os.getenv('ES_PASSWORD'):
            self._config['elasticsearch']['password'] = os.getenv('ES_PASSWORD')
        
        # Embedding model
        if os.getenv('EMBEDDING_API_URL'):
            self._config['models']['embedding']['api_url'] = os.getenv('EMBEDDING_API_URL')
        if os.getenv('EMBEDDING_API_KEY'):
            self._config['models']['embedding']['api_key'] = os.getenv('EMBEDDING_API_KEY')
        if os.getenv('EMBEDDING_MODEL'):
            self._config['models']['embedding']['model_name'] = os.getenv('EMBEDDING_MODEL')
        
        # Vision model
        if os.getenv('VISION_API_URL'):
            self._config['models']['vision']['api_url'] = os.getenv('VISION_API_URL')
        if os.getenv('VISION_API_KEY'):
            self._config['models']['vision']['api_key'] = os.getenv('VISION_API_KEY')
        if os.getenv('VISION_MODEL'):
            self._config['models']['vision']['model_name'] = os.getenv('VISION_MODEL')
        
        # Web config
        if os.getenv('WEB_HOST'):
            self._config['web']['host'] = os.getenv('WEB_HOST')
        if os.getenv('WEB_PORT'):
            self._config['web']['port'] = int(os.getenv('WEB_PORT'))
        if os.getenv('UPLOAD_FOLDER'):
            self._config['web']['upload_folder'] = os.getenv('UPLOAD_FOLDER')
        
        # Logging
        if os.getenv('LOG_LEVEL'):
            self._config['logging']['level'] = os.getenv('LOG_LEVEL')
        
        # MinIO - ensure minio section exists before applying overrides
        if 'minio' not in self._config:
            self._config['minio'] = {}
        
        if os.getenv('MINIO_ENABLED'):
            self._config['minio']['enabled'] = os.getenv('MINIO_ENABLED').lower() in ('true', '1', 'yes')
        if os.getenv('MINIO_ENDPOINT'):
            self._config['minio']['endpoint'] = os.getenv('MINIO_ENDPOINT')
        if os.getenv('MINIO_ACCESS_KEY'):
            self._config['minio']['access_key'] = os.getenv('MINIO_ACCESS_KEY')
        if os.getenv('MINIO_SECRET_KEY'):
            self._config['minio']['secret_key'] = os.getenv('MINIO_SECRET_KEY')
        if os.getenv('MINIO_BUCKET'):
            self._config['minio']['bucket_name'] = os.getenv('MINIO_BUCKET')
        if os.getenv('MINIO_SECURE'):
            self._config['minio']['secure'] = os.getenv('MINIO_SECURE').lower() in ('true', '1', 'yes')
        if os.getenv('MINIO_PUBLIC_URL'):
            self._config['minio']['public_url'] = os.getenv('MINIO_PUBLIC_URL')
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key
        
        Args:
            key: Configuration key (supports dot notation, e.g., 'models.embedding.api_url')
            default: Default value if key not found
        
        Returns:
            Configuration value
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    @property
    def embedding_config(self) -> Dict[str, Any]:
        """Get embedding model configuration"""
        return self.get('models.embedding', {})
    
    @property
    def vision_config(self) -> Dict[str, Any]:
        """Get vision model configuration"""
        return self.get('models.vision', {})
    
    @property
    def es_config(self) -> Dict[str, Any]:
        """Get Elasticsearch configuration"""
        return self.get('elasticsearch', {})
    
    @property
    def text_splitting_config(self) -> Dict[str, Any]:
        """Get text splitting configuration"""
        return self.get('text_splitting', {})
    
    @property
    def processing_config(self) -> Dict[str, Any]:
        """Get processing configuration"""
        return self.get('processing', {})
    
    @property
    def web_config(self) -> Dict[str, Any]:
        """Get web configuration"""
        return self.get('web', {})
    
    @property
    def metadata_config(self) -> Dict[str, Any]:
        """Get metadata configuration"""
        return self.get('metadata', {})
    
    @property
    def logging_config(self) -> Dict[str, Any]:
        """Get logging configuration"""
        return self.get('logging', {})
    
    @property
    def security_config(self) -> Dict[str, Any]:
        """Get security configuration"""
        return self.get('security', {})
    
    @property
    def minio_config(self) -> Dict[str, Any]:
        """Get MinIO configuration"""
        return self.get('minio', {})
    


# Global config instance
config = Config()

