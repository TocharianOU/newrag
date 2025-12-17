"""Model management module for Embedding and Vision models"""

import base64
import time
from typing import Any, Dict, List, Optional

import structlog
from langchain_core.embeddings import Embeddings
from openai import OpenAI

from src.config import config

logger = structlog.get_logger(__name__)


class CustomOpenAIEmbeddings(Embeddings):
    """Custom OpenAI Embeddings implementation for LM Studio compatibility"""
    
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of documents"""
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=texts
            )
            return [data.embedding for data in response.data]
        except Exception as e:
            logger.error("embed_documents_failed", error=str(e), num_texts=len(texts))
            raise
    
    def embed_query(self, text: str) -> List[float]:
        """Embed a single query"""
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=[text]
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("embed_query_failed", error=str(e), text_length=len(text))
            raise


class EmbeddingModel:
    """Embedding model client with multiple provider support"""

    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        """
        Initialize embedding model
        
        Args:
            config_dict: Model configuration dictionary
        """
        self.config = config_dict or config.embedding_config
        self.provider = self.config.get('provider', 'lmstudio')
        self.api_url = self.config.get('api_url')
        self.api_key = self.config.get('api_key')
        self.model_name = self.config.get('model_name')
        self.dimensions = self.config.get('dimensions', 1536)
        self.batch_size = self.config.get('batch_size', 32)
        self.timeout = self.config.get('timeout', 30)
        
        self._init_client()
        
        logger.info("embedding_model_initialized", provider=self.provider, model=self.model_name)
    
    def _init_client(self):
        """Initialize embedding client based on provider"""
        if self.provider in ['lmstudio', 'openai', 'custom']:
            # Use custom OpenAI client for better LM Studio compatibility
            openai_client = OpenAI(
                base_url=self.api_url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
            self.embeddings = CustomOpenAIEmbeddings(
                client=openai_client,
                model=self.model_name
            )
        else:
            raise ValueError(f"Unsupported embedding provider: {self.provider}")
    
    def embed_text(self, text: str) -> List[float]:
        """
        Embed single text
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding vector
        """
        try:
            return self.embeddings.embed_query(text)
        except Exception as e:
            logger.error("embedding_failed", error=str(e), text_length=len(text))
            raise
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple texts in batch
        
        Args:
            texts: List of texts to embed
        
        Returns:
            List of embedding vectors
        """
        try:
            logger.info(
                "embedding_texts_started",
                num_texts=len(texts),
                batch_size=self.batch_size,
                text_types=[type(t).__name__ for t in texts[:3]]
            )
            
            # Validate all texts are strings
            for idx, text in enumerate(texts):
                if not isinstance(text, str):
                    logger.error(
                        "invalid_text_type",
                        text_index=idx,
                        text_type=type(text).__name__,
                        text_value=str(text)[:100]
                    )
                    raise TypeError(f"Text at index {idx} is not a string: {type(text)}")
            
            # Process in batches
            all_embeddings = []
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i:i + self.batch_size]
                
                logger.info(
                    "embedding_batch",
                    batch_num=i // self.batch_size + 1,
                    batch_size=len(batch),
                    first_text_preview=batch[0][:100] if batch else "N/A"
                )
                
                embeddings = self.embeddings.embed_documents(batch)
                all_embeddings.extend(embeddings)
                
                logger.info(
                    "batch_embedded_successfully",
                    batch_num=i // self.batch_size + 1,
                    batch_size=len(batch),
                    num_embeddings=len(embeddings)
                )
            
            return all_embeddings
        except Exception as e:
            logger.error(
                "batch_embedding_failed",
                error=str(e),
                error_type=type(e).__name__,
                num_texts=len(texts)
            )
            raise
    
    def get_langchain_embeddings(self):
        """Get LangChain compatible embeddings object"""
        return self.embeddings


class VisionModel:
    """Vision model client for image text extraction"""

    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        """
        Initialize vision model
        
        Args:
            config_dict: Model configuration dictionary
        """
        self.config = config_dict or config.vision_config
        self.enabled = self.config.get('enabled', True)
        
        if not self.enabled:
            logger.info("vision_model_disabled")
            return
        
        self.provider = self.config.get('provider', 'lmstudio')
        self.api_url = self.config.get('api_url')
        self.api_key = self.config.get('api_key')
        self.model_name = self.config.get('model_name')
        self.max_tokens = self.config.get('max_tokens', 4096)
        self.timeout = self.config.get('timeout', 60)
        
        self._init_client()
        
        logger.info("vision_model_initialized", provider=self.provider, model=self.model_name)
    
    def _init_client(self):
        """Initialize vision client"""
        if self.provider in ['lmstudio', 'openai', 'custom']:
            self.client = OpenAI(
                base_url=self.api_url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        else:
            raise ValueError(f"Unsupported vision provider: {self.provider}")
    
    def chat(self, prompt: str, images: List[str] = None) -> str:
        """
        General chat method with image support
        
        Args:
            prompt: Text prompt
            images: List of base64 encoded image strings
            
        Returns:
            Response text
        """
        if not self.enabled:
            return "Vision model is disabled"
            
        try:
            messages = []
            content = [{"type": "text", "text": prompt}]
            
            if images:
                for img_base64 in images:
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{img_base64}"
                        }
                    })
            
            messages.append({"role": "user", "content": content})
            
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=self.max_tokens,
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error("vision_chat_failed", error=str(e))
            raise

    def extract_text_from_image(
        self,
        image_path: str,
        prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract text from image using vision model
        
        Args:
            image_path: Path to image file
            prompt: Custom prompt for extraction
        
        Returns:
            Dictionary with extracted text and metadata
        """
        if not self.enabled:
            return {"text": "", "error": "Vision model is disabled"}
        
        try:
            # Read and encode image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            # Determine image format
            ext = image_path.lower().split('.')[-1]
            mime_type = f"image/{ext}" if ext in ['png', 'jpg', 'jpeg'] else "image/jpeg"
            
            # Default prompt for text extraction
            if prompt is None:
                prompt = (
                    "Extract all text content from this image. "
                    "Maintain the original structure and layout. "
                    "If the image contains tables, charts, or diagrams, describe them as well."
                )
            
            # Call vision model
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=self.max_tokens,
            )
            
            extracted_text = response.choices[0].message.content
            
            logger.info(
                "image_text_extracted",
                image_path=image_path,
                text_length=len(extracted_text)
            )
            
            return {
                "text": extracted_text,
                "confidence": 1.0,  # Vision models don't typically provide confidence scores
                "model": self.model_name,
                "timestamp": time.time()
            }
        
        except Exception as e:
            logger.error("image_extraction_failed", error=str(e), image_path=image_path)
            return {
                "text": "",
                "error": str(e),
                "timestamp": time.time()
            }
    
    def extract_text_from_images(
        self,
        image_paths: List[str],
        prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract text from multiple images
        
        Args:
            image_paths: List of image file paths
            prompt: Custom prompt for extraction
        
        Returns:
            List of extraction results
        """
        results = []
        for image_path in image_paths:
            result = self.extract_text_from_image(image_path, prompt)
            results.append(result)
        
        return results

