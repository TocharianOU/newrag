"""Document management routes"""

from pathlib import Path
from typing import Optional, List
import structlog
import hashlib
import zipfile
import os
import threading
from datetime import datetime
from fastapi import APIRouter, HTTPException, File, Form, UploadFile
from fastapi.responses import JSONResponse
from src.task_manager import task_manager, TaskStatus
from src.database import DatabaseManager
import shutil
from src.pipeline import ProcessingPipeline
from src.config import config
from web.handlers.document_processor import process_document_background

web_config = config.web_config
upload_folder = Path(web_config.get('upload_folder', './uploads'))
upload_folder.mkdir(parents=True, exist_ok=True)


db = DatabaseManager()
pipeline = ProcessingPipeline()

logger = structlog.get_logger(__name__)

# Create router
router = APIRouter(prefix="", tags=["documents"])


# ============================================================
# 示例路由 - 你可以把其他文档相关的路由复制到这里
# ============================================================

@router.get("/documents")
async def list_documents(limit: int = 50, offset: int = 0, status: Optional[str] = None):
    """
    List uploaded documents
    
    示例函数 - 其他文档路由可以复制到这里：
    - POST /upload
    - POST /upload_batch  
    - POST /upload_zip
    - GET /documents/{doc_id}/progress
    - DELETE /documents/{doc_id}
    - DELETE /documents (delete all)
    - GET /tasks
    - GET /tasks/{task_id}
    - POST /tasks/{task_id}/pause
    - POST /tasks/{task_id}/resume
    - POST /tasks/{task_id}/cancel
    - POST /tasks/cleanup
    - POST /documents/{doc_id}/cleanup-minio
    """
    try:
        docs = db.list_documents(limit=limit, offset=offset, status=status)
        return JSONResponse(content={
            "documents": [doc.to_dict() for doc in docs],
            "total": len(docs)
        })
    except Exception as e:
        logger.error("list_documents_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/documents/{doc_id}/progress")
async def get_document_progress(doc_id: int, include_children: bool = False):
    """Get processing progress for a document (enhanced with task manager)"""
    try:
        # Try to get from task manager first (for active tasks)
        if include_children:
            task_dict = task_manager.get_task_with_children(doc_id)
            if task_dict:
                # Also get database info
                doc = db.get_document(doc_id)
                if doc:
                    if not task_dict.get('filename'):
                        task_dict['filename'] = doc.filename
                    task_dict['doc_id'] = doc.id
                
                return JSONResponse(content=task_dict)
        else:
            task = task_manager.get_task(doc_id)
            if task:
                task_dict = task.to_dict()
                
                # Also get database info
                doc = db.get_document(doc_id)
                if doc:
                    task_dict['filename'] = doc.filename
                    task_dict['doc_id'] = doc.id
                
                return JSONResponse(content=task_dict)
        
        # Fall back to database for completed/old tasks
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        return JSONResponse(content={
            "doc_id": doc.id,
            "status": doc.status,
            "progress_percentage": doc.progress_percentage or 0,
            "message": doc.progress_message or "",
            "total_pages": doc.total_pages or 0,
            "processed_pages": doc.processed_pages or 0,
            "filename": doc.filename,
            "is_zip_parent": False,
            "child_task_ids": [],
            "total_files": 0,
            "processed_files": 0
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_progress_failed", error=str(e), doc_id=doc_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def list_tasks(status: Optional[str] = None):
    """List all tasks with optional status filter"""
    try:
        status_filter = None
        if status:
            try:
                status_filter = TaskStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        
        tasks = task_manager.list_tasks(status_filter)
        return JSONResponse(content={
            "tasks": tasks,
            "total": len(tasks)
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error("list_tasks_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def get_task(task_id: int):
    """Get detailed task information"""
    try:
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return JSONResponse(content=task.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_task_failed", error=str(e), task_id=task_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: int):
    """Pause a running task"""
    try:
        success = task_manager.pause_task(task_id)
        if not success:
            raise HTTPException(status_code=400, detail="Cannot pause task. Check task status.")
        
        return JSONResponse(content={
            "status": "success",
            "message": f"Task {task_id} pause requested",
            "task_id": task_id
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error("pause_task_failed", error=str(e), task_id=task_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: int):
    """Resume a paused task"""
    try:
        success = task_manager.resume_task(task_id)
        if not success:
            raise HTTPException(status_code=400, detail="Cannot resume task. Check task status.")
        
        return JSONResponse(content={
            "status": "success",
            "message": f"Task {task_id} resumed",
            "task_id": task_id
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error("resume_task_failed", error=str(e), task_id=task_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: int):
    """Cancel a task"""
    try:
        success = task_manager.cancel_task(task_id)
        if not success:
            raise HTTPException(status_code=400, detail="Cannot cancel task. Check task status.")
        
        return JSONResponse(content={
            "status": "success",
            "message": f"Task {task_id} cancellation requested",
            "task_id": task_id
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error("cancel_task_failed", error=str(e), task_id=task_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/cleanup")
async def cleanup_tasks(keep_recent: int = 10):
    """Cleanup old finished tasks"""
    try:
        task_manager.cleanup_finished_tasks(keep_recent)
        return JSONResponse(content={
            "status": "success",
            "message": f"Cleaned up old tasks, keeping {keep_recent} most recent"
        })
    except Exception as e:
        logger.error("cleanup_tasks_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{doc_id}/cleanup-minio")
async def cleanup_document_minio(doc_id: int):
    """
    清理单个文档的 MinIO 数据（不删除数据库记录）
    """
    try:
        # 获取文档信息
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        checksum = doc.checksum
        filename = doc.filename
        
        # 删除 MinIO 数据
        deleted_count = 0
        try:
            from src.minio_storage import minio_storage
            if minio_storage.enabled and checksum:
                filename_base = Path(filename).stem.replace(' ', '_').replace('/', '_')
                minio_prefix = f"{filename_base}_{doc_id}_{checksum[:8]}"
                
                deleted_count = minio_storage.delete_directory(minio_prefix)
                logger.info("minio_cleaned_for_document", doc_id=doc_id, prefix=minio_prefix, count=deleted_count)
        except Exception as minio_error:
            logger.warning("minio_cleanup_failed", error=str(minio_error), doc_id=doc_id)
        
        return JSONResponse(content={
            "status": "success",
            "message": f"MinIO data cleaned for document {doc_id}",
            "doc_id": doc_id,
            "files_deleted": deleted_count
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("cleanup_document_minio_failed", error=str(e), doc_id=doc_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: int):
    """
    Delete a specific document completely from:
    - SQLite database
    - Elasticsearch index
    - MinIO storage (if enabled)
    - Local processed files
    - Original uploaded files
    """
    try:
        # 1. Get document info before deletion
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Cancel any running task for this document
        task_manager.cancel_task(doc_id)
        
        checksum = doc.checksum
        filename = doc.filename
        file_path = doc.file_path
        
        deletion_result = {
            "doc_id": doc_id,
            "filename": filename,
            "es_deleted": 0,
            "minio_deleted": 0,
            "local_files_deleted": False,
            "original_file_deleted": False
        }
        
        # 2. Delete from Elasticsearch by document_id (正确方式！)
        try:
            es_deleted = pipeline.vector_store.delete_by_metadata({"document_id": str(doc_id)})
            deletion_result["es_deleted"] = es_deleted
            logger.info("es_deleted", doc_id=doc_id, count=es_deleted)
        except Exception as es_error:
            logger.warning("es_deletion_failed", error=str(es_error), doc_id=doc_id)
        
        # 3. Delete from MinIO (使用正确的 prefix 格式)
        try:
            from src.minio_storage import minio_storage
            if minio_storage.enabled:
                # 构建 MinIO prefix: {filename_base}_{doc_id}_{checksum[:8]}
                filename_base = Path(filename).stem.replace(' ', '_').replace('/', '_')
                minio_prefix = f"{filename_base}_{doc_id}_{checksum[:8]}"
                
                minio_deleted = minio_storage.delete_directory(minio_prefix)
                deletion_result["minio_deleted"] = minio_deleted
                logger.info("minio_deleted", doc_id=doc_id, prefix=minio_prefix, count=minio_deleted)
        except Exception as minio_error:
            logger.warning("minio_deletion_failed", error=str(minio_error), doc_id=doc_id)
        
        # 4. Delete local processed files
        try:
            processed_folder = Path('web/static/processed_docs')
            doc_folder = processed_folder / f"{doc_id}_{checksum[:8]}"
            if doc_folder.exists():
                import shutil
                shutil.rmtree(doc_folder)
                deletion_result["local_files_deleted"] = True
                logger.info("local_files_deleted", doc_id=doc_id, path=str(doc_folder))
        except Exception as local_error:
            logger.warning("local_deletion_failed", error=str(local_error), doc_id=doc_id)
        
        # 5. Delete original uploaded file
        try:
            if file_path and Path(file_path).exists():
                Path(file_path).unlink()
                deletion_result["original_file_deleted"] = True
                logger.info("original_file_deleted", doc_id=doc_id, path=file_path)
        except Exception as file_error:
            logger.warning("original_file_deletion_failed", error=str(file_error), doc_id=doc_id)
        
        # 6. Delete from SQLite (最后删除，确保其他清理完成)
        success = db.delete_document(doc_id)
        if not success:
            raise HTTPException(status_code=404, detail="Failed to delete from database")
        
        logger.info("document_completely_deleted", **deletion_result)
        
        return JSONResponse(content={
            "status": "success", 
            "message": f"Document {doc_id} completely deleted",
            **deletion_result
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_document_failed", error=str(e), doc_id=doc_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents")
async def delete_all_documents():
    """
    Delete ALL documents completely from:
    - SQLite database
    - Elasticsearch index
    - MinIO storage (if enabled)
    - Local processed files
    - Original uploaded files
    """
    try:
        # 1. Get all documents info before deletion
        all_docs = db.list_documents(limit=10000)
        
        deletion_result = {
            "total_docs": len(all_docs),
            "es_deleted": 0,
            "minio_deleted": 0,
            "local_folders_deleted": 0,
            "original_files_deleted": 0
        }
        
        # 2. Delete each document's data
        for doc in all_docs:
            doc_id = doc.get('id')
            checksum = doc.get('checksum', '')
            filename = doc.get('filename', '')
            file_path = doc.get('file_path', '')
            
            # Delete from Elasticsearch (使用正确的 document_id)
            try:
                count = pipeline.vector_store.delete_by_metadata({"document_id": str(doc_id)})
                deletion_result["es_deleted"] += count
            except Exception as es_error:
                logger.warning("es_deletion_failed", error=str(es_error), doc_id=doc_id)
            
            # Delete from MinIO
            try:
                from src.minio_storage import minio_storage
                if minio_storage.enabled and checksum:
                    filename_base = Path(filename).stem.replace(' ', '_').replace('/', '_')
                    minio_prefix = f"{filename_base}_{doc_id}_{checksum[:8]}"
                    count = minio_storage.delete_directory(minio_prefix)
                    deletion_result["minio_deleted"] += count
            except Exception as minio_error:
                logger.warning("minio_deletion_failed", error=str(minio_error), doc_id=doc_id)
            
            # Delete local processed files
            try:
                if checksum:
                    processed_folder = Path('web/static/processed_docs')
                    doc_folder = processed_folder / f"{doc_id}_{checksum[:8]}"
                    if doc_folder.exists():
                        import shutil
                        shutil.rmtree(doc_folder)
                        deletion_result["local_folders_deleted"] += 1
            except Exception as local_error:
                logger.warning("local_deletion_failed", error=str(local_error), doc_id=doc_id)
            
            # Delete original file
            try:
                if file_path and Path(file_path).exists():
                    Path(file_path).unlink()
                    deletion_result["original_files_deleted"] += 1
            except Exception as file_error:
                logger.warning("original_file_deletion_failed", error=str(file_error), doc_id=doc_id)
        
        # 3. Delete all from SQLite (最后删除)
        db.delete_all_documents()
        
        # 4. Cancel all tasks
        task_manager.tasks.clear()
        
        logger.info("all_documents_completely_deleted", **deletion_result)
        
        return JSONResponse(content={
            "status": "success", 
            "message": "All documents completely deleted",
            **deletion_result
        })
    except Exception as e:
        logger.error("delete_all_documents_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    ocr_engine: Optional[str] = Form('easy')
):
    """
    Upload and process single file
    """
    doc_id = None
    file_path = None
    
    try:
        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        
        # Check file extension
        allowed_extensions = web_config.get('allowed_extensions', [])
        file_ext = Path(file.filename).suffix.lower().lstrip('.')
        
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}"
            )
        
        # Save uploaded file
        file_path = upload_folder / file.filename
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        
        file_size = file_path.stat().st_size
        
        logger.info("file_uploaded", filename=file.filename, size=file_size)
        
        # Calculate checksum
        import hashlib
        with open(file_path, 'rb') as f:
            checksum = hashlib.sha256(f.read()).hexdigest()
        
        # Check if already exists
        existing = db.get_document_by_checksum(checksum)
        if existing:
            if file_path.exists():
                os.remove(file_path)
            return JSONResponse(content={
                "status": "duplicate",
                "message": "File already exists",
                "document": existing.to_dict()
            })
        
        # Create database record
        doc = db.create_document(
            filename=file.filename,
            file_path=str(file_path),
            file_type=file_ext,
            file_size=file_size,
            checksum=checksum,
            category=category,
            tags=tags.split(',') if tags else None,
            author=author,
            description=description,
            ocr_engine=ocr_engine
        )
        doc_id = doc.id
        logger.info("document_created", doc_id=doc_id, file_type=file_ext)
        
        # Update status to processing
        db.update_document_status(doc_id, 'processing')
        logger.info("status_updated_to_processing", doc_id=doc_id)
        
        # Prepare metadata
        metadata = {}
        if category:
            metadata['category'] = category
        if tags:
            metadata['tags'] = tags.split(',')
        if author:
            metadata['author'] = author
        if description:
            metadata['description'] = description
        
        # Start background processing
        logger.info("starting_background_processing", doc_id=doc_id, filename=file.filename, ocr_engine=ocr_engine, file_type=file_ext)
        
        # Start background thread
        thread = threading.Thread(
            target=process_document_background,
            args=(doc_id, file_path, metadata, ocr_engine, checksum),
            daemon=True
        )
        
        # Register thread in task manager
        task_manager.register_thread(doc_id, thread)
        thread.start()
        
        # Return immediately with task info
        return JSONResponse(content={
            'status': 'processing',
            'message': 'Document uploaded and processing started',
            'document_id': doc_id,
            'checksum': checksum,
            'filename': file.filename
        })
    
    except Exception as e:
        logger.error("upload_failed", error=str(e))
        
        # Update database if record was created
        if doc_id:
            db.update_document_status(doc_id, 'failed', error_message=str(e))
        
        # Clean up file
        if file_path and file_path.exists():
            os.remove(file_path)
        
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/upload_batch")
async def upload_batch(
    files: List[UploadFile] = File(...),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    author: Optional[str] = Form(None)
):
    """
    Upload and process multiple files
    """
    try:
        file_paths = []
        
        # Save all files
        for file in files:
            file_path = upload_folder / file.filename
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            file_paths.append(str(file_path))
        
        logger.info("batch_uploaded", num_files=len(files))
        
        # Prepare metadata
        metadata = {}
        if category:
            metadata['category'] = category
        if tags:
            metadata['tags'] = tags.split(',')
        if author:
            metadata['author'] = author
        
        # Process batch
        results = pipeline.process_batch(file_paths, metadata)
        
        # Clean up
        for file_path in file_paths:
            if Path(file_path).exists():
                os.remove(file_path)
        
        return JSONResponse(content={"results": results})
    
    except Exception as e:
        logger.error("batch_upload_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload_zip")
async def upload_zip(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    author: Optional[str] = Form(None)
):
    """
    Upload and process ZIP file
    """
    try:
        if not file.filename.endswith('.zip'):
            raise HTTPException(status_code=400, detail="File must be a ZIP archive")
        
        # Save ZIP file
        zip_path = upload_folder / file.filename
        with open(zip_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        
        logger.info("zip_uploaded", filename=file.filename)
        
        # Prepare metadata
        metadata = {}
        if category:
            metadata['category'] = category
        if tags:
            metadata['tags'] = tags.split(',')
        if author:
            metadata['author'] = author
        
        # Process ZIP
        result = pipeline.process_zip(str(zip_path), metadata)
        
        # Clean up
        if zip_path.exists():
            os.remove(zip_path)
        
        # Clean up extracted files
        extract_dir = upload_folder / f"extracted_{zip_path.stem}"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        
        return JSONResponse(content=result)
    
    except Exception as e:
        logger.error("zip_upload_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# - upload_file()
# - upload_batch()
# - upload_zip()
# - get_document_progress()
# - delete_document()
# - delete_all_documents()
# - cleanup_document_minio()
# - list_tasks()
# - get_task()
# - pause_task()
# - resume_task()
# - cancel_task()
# - cleanup_tasks()

