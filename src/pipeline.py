"""Processing pipeline module"""

import asyncio
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

import structlog

from src.document_processor import DocumentProcessor
from src.vector_store import VectorStore

logger = structlog.get_logger(__name__)


class TaskStatus(str, Enum):
    """Task status enum"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingTask:
    """Processing task representation"""

    def __init__(self, task_id: str, file_path: str, metadata: Optional[Dict[str, Any]] = None):
        self.task_id = task_id
        self.file_path = file_path
        self.metadata = metadata or {}
        self.status = TaskStatus.PENDING
        self.error: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None


class ProcessingPipeline:
    """Document processing pipeline with async support"""

    def __init__(self):
        """Initialize processing pipeline"""
        self.processor = DocumentProcessor()
        self.vector_store = VectorStore()
        self.tasks: Dict[str, ProcessingTask] = {}
        
        logger.info("processing_pipeline_initialized")
    
    def create_task(
        self,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new processing task
        
        Args:
            file_path: Path to file to process
            metadata: Additional metadata
        
        Returns:
            Task ID
        """
        task_id = str(uuid4())
        task = ProcessingTask(task_id, file_path, metadata)
        self.tasks[task_id] = task
        
        logger.info("task_created", task_id=task_id, file_path=file_path)
        
        return task_id
    
    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get task status
        
        Args:
            task_id: Task ID
        
        Returns:
            Task status information
        """
        if task_id not in self.tasks:
            return {"error": "Task not found"}
        
        task = self.tasks[task_id]
        
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "file_path": task.file_path,
            "error": task.error,
            "result": task.result
        }
    
    def process_file(
        self,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None,
        processed_json_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process single file synchronously
        
        Args:
            file_path: Path to file
            metadata: Additional metadata
            processed_json_dir: Optional path to pre-processed JSON directory
        
        Returns:
            Processing result
        """
        try:
            logger.info("file_processing_started", file_path=file_path, has_metadata=bool(metadata))
            
            # Process document (will use pre-processed JSON if available)
            logger.info("📝 Processing document...", file_path=file_path, has_processed_json=bool(processed_json_dir))
            chunks = self.processor.process_document(file_path, metadata, processed_json_dir=processed_json_dir)
            logger.info("✅ Document processed successfully", num_chunks=len(chunks))
            
            if not chunks:
                logger.warning("no_chunks_generated", file_path=file_path)
                return {
                    "file_path": file_path,
                    "num_chunks": 0,
                    "document_ids": [],
                    "status": "completed",
                    "message": "No valid chunks generated from document"
                }
            
            # Add to vector store
            logger.info("🔄 Generating embeddings and writing to Elasticsearch...", num_chunks=len(chunks))
            doc_ids = self.vector_store.add_documents(chunks)
            
            # Verify ES write success
            if not doc_ids:
                error_msg = f"Failed to write {len(chunks)} chunks to Elasticsearch - no documents indexed"
                logger.error("❌ ES_WRITE_VERIFICATION_FAILED", 
                           num_chunks=len(chunks), 
                           num_indexed=0)
                raise RuntimeError(error_msg)
            elif len(doc_ids) < len(chunks):
                logger.warning("⚠️  PARTIAL_ES_WRITE", 
                              num_chunks=len(chunks), 
                              num_indexed=len(doc_ids),
                              success_rate=f"{len(doc_ids)/len(chunks)*100:.1f}%")
            
            logger.info("✅ Successfully written to Elasticsearch!", 
                       num_doc_ids=len(doc_ids), 
                       es_document_ids=doc_ids[:3] if doc_ids else [])
            
            result = {
                "file_path": file_path,
                "num_chunks": len(chunks),
                "document_ids": doc_ids,
                "status": "completed"
            }
            
            logger.info("=" * 80)
            logger.info(
                "🎉 FILE PROCESSING COMPLETED SUCCESSFULLY!",
                file_path=file_path,
                num_chunks=len(chunks),
                num_indexed=len(doc_ids),
                status="✅ COMPLETED"
            )
            logger.info("=" * 80)
            
            return result
        
        except Exception as e:
            logger.error("file_processing_failed", error=str(e), file_path=file_path)
            return {
                "file_path": file_path,
                "status": "failed",
                "error": str(e)
            }
    
    def process_zip(
        self,
        zip_path: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process ZIP file
        
        Args:
            zip_path: Path to ZIP file
            metadata: Additional metadata
        
        Returns:
            Processing result
        """
        try:
            logger.info("zip_processing_started", zip_path=zip_path)
            
            # Process ZIP
            chunks = self.processor.process_zip(zip_path, metadata=metadata)
            
            # Add to vector store
            doc_ids = self.vector_store.add_documents(chunks)
            
            # Get unique file count
            unique_files = len(set(c.metadata['filepath'] for c in chunks))
            
            result = {
                "zip_path": zip_path,
                "num_files": unique_files,
                "num_chunks": len(chunks),
                "document_ids": doc_ids,
                "status": "completed"
            }
            
            logger.info(
                "zip_processing_completed",
                zip_path=zip_path,
                num_files=unique_files,
                num_chunks=len(chunks)
            )
            
            return result
        
        except Exception as e:
            logger.error("zip_processing_failed", error=str(e), zip_path=zip_path)
            return {
                "zip_path": zip_path,
                "status": "failed",
                "error": str(e)
            }
    
    def process_batch(
        self,
        file_paths: List[str],
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Process multiple files in batch
        
        Args:
            file_paths: List of file paths
            metadata: Additional metadata
        
        Returns:
            List of processing results
        """
        results = []
        
        for file_path in file_paths:
            result = self.process_file(file_path, metadata)
            results.append(result)
        
        return results
    
    async def process_file_async(
        self,
        task_id: str
    ) -> Dict[str, Any]:
        """
        Process file asynchronously
        
        Args:
            task_id: Task ID
        
        Returns:
            Processing result
        """
        if task_id not in self.tasks:
            return {"error": "Task not found"}
        
        task = self.tasks[task_id]
        task.status = TaskStatus.PROCESSING
        
        try:
            # Run processing in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.process_file,
                task.file_path,
                task.metadata
            )
            
            task.status = TaskStatus.COMPLETED
            task.result = result
            
            return result
        
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            
            logger.error("async_processing_failed", error=str(e), task_id=task_id)
            
            return {
                "task_id": task_id,
                "status": "failed",
                "error": str(e)
            }
    
    def search(
        self,
        query: str,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        use_hybrid: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Search knowledge base
        
        Args:
            query: Search query
            k: Number of results
            filters: Metadata filters
            use_hybrid: Use hybrid search (vector + BM25)
        
        Returns:
            List of search results
        """
        try:
            if use_hybrid:
                results = self.vector_store.hybrid_search(
                    query=query,
                    k=k,
                    filter_dict=filters
                )
            else:
                docs = self.vector_store.similarity_search(
                    query=query,
                    k=k,
                    filter_dict=filters
                )
                results = [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": None
                    }
                    for doc in docs
                ]
            
            logger.info("search_completed", query=query, num_results=len(results))
            
            return results
        
        except Exception as e:
            logger.error("search_failed", error=str(e), query=query)
            raise
    
    def search_component(
        self,
        component_id: str,
        k: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for pages containing specific component
        
        Args:
            component_id: Component ID to search for
            k: Number of results
            filters: Metadata filters
        
        Returns:
            List of matching pages
        """
        try:
            results = self.vector_store.search_component(
                component_id=component_id,
                k=k,
                filter_dict=filters
            )
            
            logger.info(
                "component_search_completed",
                component_id=component_id,
                num_results=len(results)
            )
            
            return results
        
        except Exception as e:
            logger.error("component_search_failed", error=str(e), component_id=component_id)
            raise

