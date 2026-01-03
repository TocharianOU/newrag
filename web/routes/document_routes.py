"""Document management routes"""

from pathlib import Path
from typing import Optional, List
import structlog
import hashlib
import zipfile
import os
import threading
from datetime import datetime
from fastapi import APIRouter, HTTPException, File, Form, UploadFile, Depends, Request
from fastapi.responses import JSONResponse
from src.task_manager import task_manager, TaskStatus
from src.database import DatabaseManager, User, AuthManager
import shutil
from src.pipeline import ProcessingPipeline
from src.config import config
from web.handlers.document_processor import process_document_background
from web.dependencies.auth_deps import get_current_user, require_permission

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
async def list_documents(
    limit: int = 50, 
    offset: int = 0, 
    status: Optional[str] = None, 
    include_archives: bool = False,
    current_user: Optional[User] = Depends(get_current_user)
):
    """
    List uploaded documents with permission filtering
    
    Supports version control: returns latest version of each document master.
    Requires authentication. Returns only documents the user has permission to see.
    """
    try:
        # 默认不显示 ZIP 压缩包本身，除非 include_archives=True
        exclude_types = None if include_archives else ['zip']
        
        # Apply permission filtering based on current user
        user_id = current_user.id if current_user else None
        org_id = current_user.org_id if current_user else None
        is_superuser = current_user.is_superuser if current_user else False
        
        # Try version control method first
        try:
            docs_combined = db.list_document_masters(
                org_id=org_id,
                user_id=user_id,
                limit=limit,
                offset=offset,
                status=status
            )
            
            # Filter by file type if needed
            if exclude_types:
                docs_combined = [
                    doc for doc in docs_combined 
                    if doc.get('file_type') not in exclude_types
                ]
            
            return JSONResponse(content={
                "documents": docs_combined,
                "total": len(docs_combined)
            })
        except Exception as version_err:
            # Fallback to old method for backward compatibility
            logger.warning("version_control_list_failed_fallback_to_legacy", 
                         error=str(version_err), user_id=user_id)
            
            docs = db.list_documents(
                limit=limit, 
                offset=offset, 
                status=status, 
                exclude_file_types=exclude_types,
                user_id=user_id,
                org_id=org_id,
                is_superuser=is_superuser
            )
            return JSONResponse(content={
                "documents": [doc.to_dict() for doc in docs],
                "total": len(docs)
            })
    except Exception as e:
        logger.error("list_documents_failed", error=str(e), user_id=user_id if current_user else None)
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
async def delete_document(
    doc_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    Delete a specific document completely from:
    - SQLite database
    - Elasticsearch index
    - MinIO storage (if enabled)
    - Local processed files
    - Original uploaded files
    - Child documents (if this is a ZIP parent)
    
    Requires authentication. Users can only delete their own documents unless they are superuser.
    """
    try:
        logger.info(f"Attempting to delete document {doc_id}", user_id=current_user.id)
        
        # 1. Try to find in DB - check both old Document and new DocumentVersion
        session = db.get_session()
        doc = None
        doc_version = None
        doc_master = None
        
        try:
            from src.database import Document, DocumentVersion, DocumentMaster
            
            # First try new version control tables
            doc_version = session.query(DocumentVersion).filter(DocumentVersion.id == doc_id).first()
            if doc_version:
                doc_master = session.query(DocumentMaster).filter(
                    DocumentMaster.id == doc_version.document_master_id
                ).first()
            
            # If not found, try old Document table (for backward compatibility)
            if not doc_version:
                doc = session.query(Document).filter(Document.id == doc_id).first()
        finally:
            session.close()
        
        # Check permissions
        if not current_user.is_superuser:
            if doc_master:
                # New version control: check master's owner
                if doc_master.owner_id and doc_master.owner_id != current_user.id:
                    raise HTTPException(
                        status_code=403,
                        detail="You can only delete your own documents"
                    )
            elif doc:
                # Old document: check doc's owner
                if doc.owner_id is not None and doc.owner_id != current_user.id:
                    raise HTTPException(
                        status_code=403,
                        detail="You can only delete your own documents"
                    )
        
        # Extract info for deletion
        if doc_version and doc_master:
            # New version control - delete entire document master and all versions
            checksum = doc_version.checksum
            filename = doc_master.filename_base
            file_path = doc_version.file_path
        elif doc:
            # Old document
            checksum = doc.checksum
            filename = doc.filename
            file_path = doc.file_path
        else:
            # Not found - still try to clean up by ID
            checksum = None
            filename = None
            file_path = None
        
        deletion_result = {
            "doc_id": doc_id,
            "filename": filename,
            "es_deleted": 0,
            "minio_deleted": 0,
            "local_files_deleted": False,
            "original_file_deleted": False,
            "child_docs_deleted": 0
        }
        
        # Cancel any running task for this document
        if doc or doc_version:
            task_manager.cancel_task(doc_id)
        
        # 1.5. If this is a ZIP parent, collect child task IDs and delete them first
        child_task_ids = []
        task = task_manager.get_task(doc_id)
        if task and task.child_task_ids:
            child_task_ids = list(task.child_task_ids)
            logger.info("found_child_tasks", parent_id=doc_id, child_ids=child_task_ids)
        
        # Delete all child documents first
        for child_id in child_task_ids:
                # ... (child deletion logic remains same) ...
            try:
                # Get child document info
                child_doc = db.get_document(child_id)
                if not child_doc:
                    logger.warning("child_doc_not_found_in_db", child_id=child_id)
                    # Still try to clean ES for child ID
                    try:
                        pipeline.vector_store.delete_by_metadata({"document_id": str(child_id)})
                    except:
                        pass
                    continue
                
                # Cancel child task
                task_manager.cancel_task(child_id)
                
                # Delete from ES
                try:
                    child_es_deleted = pipeline.vector_store.delete_by_metadata({"document_id": str(child_id)})
                    deletion_result["es_deleted"] += child_es_deleted
                except Exception as es_error:
                    logger.warning("child_es_deletion_failed", error=str(es_error), child_id=child_id)
                
                # Delete from MinIO
                try:
                    from src.minio_storage import minio_storage
                    if minio_storage.enabled and child_doc.checksum:
                        child_filename_base = Path(child_doc.filename).stem.replace(' ', '_').replace('/', '_')
                        child_minio_prefix = f"{child_filename_base}_{child_id}_{child_doc.checksum[:8]}"
                        child_minio_deleted = minio_storage.delete_directory(child_minio_prefix)
                        deletion_result["minio_deleted"] += child_minio_deleted
                except Exception as minio_error:
                    logger.warning("child_minio_deletion_failed", error=str(minio_error), child_id=child_id)
                
                # Delete local processed files
                try:
                    processed_folder = Path('web/static/processed_docs')
                    child_doc_folder = processed_folder / f"{child_id}_{child_doc.checksum[:8]}"
                    if child_doc_folder.exists():
                        import shutil
                        shutil.rmtree(child_doc_folder)
                except Exception as local_error:
                    logger.warning("child_local_deletion_failed", error=str(local_error), child_id=child_id)
                
                # Delete original file
                try:
                    if child_doc.file_path and Path(child_doc.file_path).exists():
                        Path(child_doc.file_path).unlink()
                except Exception as file_error:
                    logger.warning("child_original_file_deletion_failed", error=str(file_error), child_id=child_id)
                
                # Delete from database
                db.delete_document(child_id)
                deletion_result["child_docs_deleted"] += 1
                
            except Exception as child_error:
                logger.error("child_deletion_failed", error=str(child_error), child_id=child_id)
        
        # 2. Delete from Elasticsearch
        try:
            if doc_master:
                # Delete all versions from ES
                all_versions = db.get_version_history(doc_master.id)
                for v in all_versions:
                    try:
                        es_deleted = pipeline.vector_store.delete_by_metadata(
                            {"document_id": str(v.id)}
                        )
                        deletion_result["es_deleted"] += es_deleted
                    except Exception as e:
                        logger.warning("version_es_deletion_failed", version_id=v.id, error=str(e))
                logger.info("all_versions_es_deleted", master_id=doc_master.id, 
                          total_deleted=deletion_result["es_deleted"])
            else:
                # Delete old document from ES
                es_deleted = pipeline.vector_store.delete_by_metadata(
                    {"document_id": str(doc_id)},
                    fallback_filters={"checksum": checksum} if checksum else None
                )
                deletion_result["es_deleted"] += es_deleted
                logger.info("es_deleted", doc_id=doc_id, count=es_deleted)
        except Exception as es_error:
            logger.warning("es_deletion_failed", error=str(es_error), doc_id=doc_id)
        
        # 3. Delete from MinIO
        try:
            from src.minio_storage import minio_storage
            if minio_storage.enabled:
                if doc_master:
                    # Delete all versions from MinIO
                    all_versions = db.get_version_history(doc_master.id)
                    filename_base = Path(doc_master.filename_base).stem.replace(' ', '_').replace('/', '_')
                    for v in all_versions:
                        if v.checksum:
                            minio_prefix = f"{filename_base}_{v.id}_{v.checksum[:8]}"
                            minio_deleted = minio_storage.delete_directory(minio_prefix)
                            deletion_result["minio_deleted"] += minio_deleted
                elif filename and checksum:
                    # Delete old document from MinIO
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
            if doc_master:
                # Delete all versions' local files
                all_versions = db.get_version_history(doc_master.id)
                for v in all_versions:
                    if v.checksum:
                        version_folder = processed_folder / f"{v.id}_{v.checksum[:8]}"
                        if version_folder.exists():
                            import shutil
                            shutil.rmtree(version_folder)
                            deletion_result["local_files_deleted"] = True
            elif checksum:
                # Delete old document's local files
                doc_folder = processed_folder / f"{doc_id}_{checksum[:8]}"
                if doc_folder.exists():
                    import shutil
                    shutil.rmtree(doc_folder)
                    deletion_result["local_files_deleted"] = True
                    logger.info("local_files_deleted", doc_id=doc_id, path=str(doc_folder))
        except Exception as local_error:
            logger.warning("local_deletion_failed", error=str(local_error), doc_id=doc_id)
        
        # 5. Delete original uploaded file(s)
        try:
            if doc_master:
                # Delete all versions' original files
                all_versions = db.get_version_history(doc_master.id)
                for v in all_versions:
                    if v.file_path and Path(v.file_path).exists():
                        Path(v.file_path).unlink()
                        deletion_result["original_file_deleted"] = True
            elif file_path and Path(file_path).exists():
                # Delete old document's original file
                Path(file_path).unlink()
                deletion_result["original_file_deleted"] = True
                logger.info("original_file_deleted", doc_id=doc_id, path=file_path)
        except Exception as file_error:
            logger.warning("original_file_deletion_failed", error=str(file_error), doc_id=doc_id)
        
        # 6. Delete from SQLite
        if doc_master:
            # Delete entire document master and all versions
            success = db.delete_document_master(doc_master.id)
            if not success:
                logger.warning("db_delete_master_failed", master_id=doc_master.id)
            else:
                logger.info("document_master_and_versions_deleted", 
                          master_id=doc_master.id, 
                          group_id=doc_master.document_group_id)
        elif doc:
            # Delete old document
            success = db.delete_document(doc_id)
            if not success:
                logger.warning("db_delete_failed_or_already_gone", doc_id=doc_id)
        
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
            
            # Delete from Elasticsearch (使用正确的 document_id, with fallback for legacy data)
            try:
                count = pipeline.vector_store.delete_by_metadata(
                    {"document_id": str(doc_id)},
                    fallback_filters={"checksum": checksum} if checksum else None
                )
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
    current_user: User = Depends(get_current_user),
    organization_id: Optional[int] = Form(None),
    visibility: Optional[str] = Form('organization'),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    ocr_engine: Optional[str] = Form('easy'),
    processing_mode: Optional[str] = Form('fast')
):
    """
    Upload and process single file
    Requires authentication.
    """
    doc_id = None
    file_path = None
    
    try:
        # Determine organization ID
        if not organization_id:
            organization_id = current_user.org_id
        
        # Validate user can upload to this organization
        if not current_user.is_superuser and organization_id != current_user.org_id:
            raise HTTPException(
                status_code=403, 
                detail="You can only upload documents to your own organization"
            )
        
        # Validate visibility setting
        valid_visibility = ['private', 'organization', 'public']
        if visibility not in valid_visibility:
            visibility = 'organization'
        
        # Only superusers can create public documents
        if visibility == 'public' and not current_user.is_superuser:
            raise HTTPException(
                status_code=403,
                detail="Only administrators can create public documents"
            )
        
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
        
        logger.info("file_uploaded", filename=file.filename, size=file_size, user_id=current_user.id, org_id=organization_id)
        
        # Calculate checksum
        import hashlib
        with open(file_path, 'rb') as f:
            checksum = hashlib.sha256(f.read()).hexdigest()
        
        # ===== Version Control Logic =====
        # Check if a document with this filename already exists in the organization
        existing_master = db.get_document_master_by_filename(
            filename=file.filename,
            org_id=organization_id
        )
        
        is_new_version = False
        version_number = 1
        
        if existing_master:
            # Document with this filename exists
            latest_version = db.get_latest_version(existing_master.id)
            
            if latest_version and checksum == latest_version.checksum:
                # Exact same file content
                if file_path.exists():
                    os.remove(file_path)
                return JSONResponse(content={
                    "status": "duplicate",
                    "message": "文件内容完全相同",
                    "version": latest_version.version,
                    "document": latest_version.to_combined_dict(existing_master)
                })
            
            # Different content - create new version
            is_new_version = True
            version_number = latest_version.version + 1 if latest_version else 1
            
            logger.info("creating_new_version", 
                       filename=file.filename, 
                       version=version_number,
                       master_id=existing_master.id)
            
            # Create new version
            doc_version = db.create_document_version(
                document_master_id=existing_master.id,
                version=version_number,
                file_path=str(file_path),
                file_type=file_ext,
                file_size=file_size,
                checksum=checksum,
                ocr_engine=ocr_engine,
                uploaded_by_id=current_user.id,
                version_note=f"Version {version_number}"
            )
            doc_id = doc_version.id
            logger.info("new_version_created", 
                       doc_id=doc_id, 
                       version=version_number,
                       master_id=existing_master.id)
        else:
            # New document - create master + version 1
            logger.info("creating_new_document_master", filename=file.filename)
            
            # Create document master
            master = db.create_document_master(
                filename_base=file.filename,
                owner_id=current_user.id,
                org_id=organization_id,
                visibility=visibility,
                category=category,
                tags=tags.split(',') if tags else None,
                author=author,
                description=description
            )
            
            logger.info("document_master_created", 
                       master_id=master.id,
                       document_group_id=master.document_group_id)
            
            # Create version 1
            doc_version = db.create_document_version(
                document_master_id=master.id,
                version=1,
                file_path=str(file_path),
                file_type=file_ext,
                file_size=file_size,
                checksum=checksum,
                ocr_engine=ocr_engine,
                uploaded_by_id=current_user.id,
                version_note="Initial version"
            )
            doc_id = doc_version.id
            existing_master = master
            logger.info("initial_version_created", doc_id=doc_id)
        
        # Update status to processing
        db.update_document_version_status(doc_id, 'processing')
        logger.info("status_updated_to_processing", doc_id=doc_id, version=version_number)
        
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
            args=(doc_id, file_path, metadata, ocr_engine, checksum, processing_mode),
            daemon=True
        )
        
        # Register thread in task manager
        task_manager.register_thread(doc_id, thread)
        thread.start()
        
        # Return immediately with task info
        response_content = {
            'status': 'new_version' if is_new_version else 'created',
            'message': f'版本 {version_number} 已创建并开始处理' if is_new_version else 'Document uploaded and processing started',
            'document_id': doc_id,
            'checksum': checksum,
            'filename': file.filename,
            'version': version_number
        }
        
        if existing_master:
            response_content['document_group_id'] = existing_master.document_group_id
        
        return JSONResponse(content=response_content)
    
    except Exception as e:
        logger.error("upload_failed", error=str(e))
        
        # Update database if record was created
        if doc_id:
            try:
                db.update_document_version_status(doc_id, 'failed', error_message=str(e))
            except:
                # Fallback to old method for backward compatibility
                try:
                    db.update_document_status(doc_id, 'failed', error_message=str(e))
                except:
                    pass
        
        # Clean up file
        if file_path and file_path.exists():
            os.remove(file_path)
        
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/upload_batch")
async def upload_batch(
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    organization_id: Optional[int] = Form(None),
    visibility: Optional[str] = Form('organization'),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    ocr_engine: Optional[str] = Form('vision'),
    processing_mode: Optional[str] = Form('fast')
):
    """
    Upload and process multiple files asynchronously
    Requires authentication.
    """
    try:
        # Determine organization ID
        if not organization_id:
            organization_id = current_user.org_id
        
        # Validate user can upload to this organization
        if not current_user.is_superuser and organization_id != current_user.org_id:
            raise HTTPException(
                status_code=403, 
                detail="You can only upload documents to your own organization"
            )
        
        # Validate visibility setting
        valid_visibility = ['private', 'organization', 'public']
        if visibility not in valid_visibility:
            visibility = 'organization'
        
        # Only superusers can create public documents
        if visibility == 'public' and not current_user.is_superuser:
            raise HTTPException(
                status_code=403,
                detail="Only administrators can create public documents"
            )
        
        results = []
        logger.info("batch_upload_started", num_files=len(files), user_id=current_user.id, org_id=organization_id)
        
        for file in files:
            file_path = None
            try:
                # 1. Validate
                if not file.filename:
                    continue
                
                # Check file extension
                allowed_extensions = web_config.get('allowed_extensions', [])
                file_ext = Path(file.filename).suffix.lower().lstrip('.')
                
                if file_ext not in allowed_extensions:
                    results.append({
                        "filename": file.filename,
                        "status": "failed",
                        "error": f"File type not allowed. Allowed: {', '.join(allowed_extensions)}"
                    })
                    continue
                
                # 2. Save file
                file_path = upload_folder / file.filename
                with open(file_path, "wb") as f:
                    shutil.copyfileobj(file.file, f)
                
                file_size = file_path.stat().st_size
                
                # 3. Checksum
                with open(file_path, 'rb') as f:
                    checksum = hashlib.sha256(f.read()).hexdigest()
                
                # 4. Check Duplicate
                existing = db.get_document_by_checksum(checksum)
                if existing:
                    if file_path.exists():
                        os.remove(file_path)
                    results.append({
                        "filename": file.filename,
                        "status": "duplicate",
                        "document_id": existing.id,
                        "message": "File already exists"
                    })
                    continue
                
                # 5. Create DB Record with user and organization info
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
                    ocr_engine=ocr_engine,
                    owner_id=current_user.id,
                    org_id=organization_id,
                    visibility=visibility
                )
        
                # Update status to processing
                db.update_document_status(doc.id, 'processing')
                
                # 6. Prepare Metadata
                metadata = {}
                if category: metadata['category'] = category
                if tags: metadata['tags'] = tags.split(',')
                if author: metadata['author'] = author
                if description: metadata['description'] = description
                
                # 7. Start Background Task
                thread = threading.Thread(
                    target=process_document_background,
                    args=(doc.id, file_path, metadata, ocr_engine, checksum, processing_mode),
                    daemon=True
                )
                task_manager.register_thread(doc.id, thread)
                thread.start()
                
                results.append({
                    "filename": file.filename,
                    "status": "processing",
                    "document_id": doc.id,
                    "checksum": checksum
                })
                
                logger.info("batch_file_processing_started", doc_id=doc.id, filename=file.filename)
                
            except Exception as file_error:
                logger.error("batch_file_failed", filename=file.filename, error=str(file_error))
                # Clean up file if it exists and we failed before starting processing
                if file_path and file_path.exists() and "document_id" not in locals():
                    try:
                        os.remove(file_path)
                    except:
                        pass
                        
                results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "error": str(file_error)
                })
        
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
# - get_document_permissions()
# - update_document_permissions()


# ===== Version Control API Endpoints =====

@router.get("/documents/{group_id}/versions")
async def get_version_history(
    group_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get version history for a document by its group ID.
    Returns all versions ordered by version number (newest first).
    """
    try:
        # Get document master
        master = db.get_document_master_by_group_id(group_id)
        if not master:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Check permissions (simplified - should use permission system)
        if not current_user.is_superuser:
            if master.owner_id != current_user.id and master.org_id != current_user.org_id:
                raise HTTPException(status_code=403, detail="Access denied")
        
        # Get version history
        versions = db.get_version_history(master.id)
        
        # Convert to dict with user info
        version_list = []
        for v in versions:
            version_dict = v.to_dict()
            
            # Add uploader info
            if v.uploaded_by_id:
                uploader = auth_manager.get_user_by_id(v.uploaded_by_id)
                if uploader:
                    version_dict['uploaded_by'] = {
                        'id': uploader.id,
                        'username': uploader.username,
                        'email': uploader.email
                    }
            
            # Mark if this is the latest version
            version_dict['is_latest'] = (master.latest_version_id == v.id)
            
            version_list.append(version_dict)
        
        return JSONResponse(content={
            "document_group_id": group_id,
            "filename": master.filename_base,
            "versions": version_list,
            "total_versions": len(version_list)
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_version_history_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{group_id}/versions/{version_number}")
async def get_specific_version(
    group_id: str,
    version_number: int,
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific version of a document.
    """
    try:
        # Get document master
        master = db.get_document_master_by_group_id(group_id)
        if not master:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Check permissions
        if not current_user.is_superuser:
            if master.owner_id != current_user.id and master.org_id != current_user.org_id:
                raise HTTPException(status_code=403, detail="Access denied")
        
        # Get specific version
        version = db.get_document_version_by_number(master.id, version_number)
        if not version:
            raise HTTPException(status_code=404, detail=f"Version {version_number} not found")
        
        # Return combined view
        return JSONResponse(content=version.to_combined_dict(master))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_specific_version_failed", 
                    group_id=group_id, version=version_number, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{group_id}/versions/{version_number}/restore")
async def restore_version(
    group_id: str,
    version_number: int,
    current_user: User = Depends(get_current_user)
):
    """
    Restore a specific version by creating a new version that is a copy of it.
    This makes the specified version the latest version.
    """
    try:
        # Get document master
        master = db.get_document_master_by_group_id(group_id)
        if not master:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Check permissions (only owner or superuser can restore)
        if not current_user.is_superuser and master.owner_id != current_user.id:
            raise HTTPException(
                status_code=403, 
                detail="Only document owner can restore versions"
            )
        
        # Restore version
        new_version = db.restore_version(master.id, version_number)
        
        logger.info("version_restored", 
                   group_id=group_id, 
                   restored_from=version_number,
                   new_version=new_version.version,
                   user_id=current_user.id)
        
        return JSONResponse(content={
            "message": f"Version {version_number} restored successfully",
            "new_version": new_version.version,
            "document": new_version.to_combined_dict(master)
        })
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("restore_version_failed", 
                    group_id=group_id, version=version_number, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{group_id}/versions/{version_number}")
async def delete_version(
    group_id: str,
    version_number: int,
    hard_delete: bool = False,
    current_user: User = Depends(get_current_user)
):
    """
    Delete a specific version (soft delete by default).
    Cannot delete the only remaining version.
    """
    try:
        # Get document master
        master = db.get_document_master_by_group_id(group_id)
        if not master:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Check permissions
        if not current_user.is_superuser and master.owner_id != current_user.id:
            raise HTTPException(
                status_code=403, 
                detail="Only document owner can delete versions"
            )
        
        # Get all versions
        all_versions = db.get_version_history(master.id)
        if len(all_versions) <= 1:
            raise HTTPException(
                status_code=400, 
                detail="Cannot delete the only remaining version"
            )
        
        # Get the version to delete
        version = db.get_document_version_by_number(master.id, version_number)
        if not version:
            raise HTTPException(status_code=404, detail=f"Version {version_number} not found")
        
        # Delete version
        success = db.delete_document_version(version.id, soft_delete=not hard_delete)
        
        if success:
            logger.info("version_deleted", 
                       group_id=group_id, 
                       version=version_number,
                       hard_delete=hard_delete,
                       user_id=current_user.id)
            
            return JSONResponse(content={
                "message": f"Version {version_number} deleted successfully",
                "deleted_type": "hard" if hard_delete else "soft"
            })
        else:
            raise HTTPException(status_code=500, detail="Failed to delete version")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_version_failed", 
                    group_id=group_id, version=version_number, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/documents/{group_id}/metadata")
async def update_document_metadata(
    group_id: str,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    author: Optional[str] = None,
    description: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Update document master metadata (affects all versions).
    """
    try:
        # Get document master
        master = db.get_document_master_by_group_id(group_id)
        if not master:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Check permissions
        if not current_user.is_superuser and master.owner_id != current_user.id:
            raise HTTPException(
                status_code=403, 
                detail="Only document owner can update metadata"
            )
        
        # Parse tags
        tags_list = tags.split(',') if tags else None
        
        # Update metadata
        updated_master = db.update_document_master_metadata(
            document_master_id=master.id,
            category=category,
            tags=tags_list,
            author=author,
            description=description
        )
        
        logger.info("document_metadata_updated", 
                   group_id=group_id, 
                   user_id=current_user.id)
        
        return JSONResponse(content={
            "message": "Metadata updated successfully",
            "document": updated_master.to_dict()
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_metadata_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_id}/permissions")
async def get_document_permissions(
    doc_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    Get document permissions detail.
    Supports both legacy Document and new DocumentMaster/Version.
    """
    import json
    try:
        # Try to get as DocumentMaster first
        master = None
        document = None
        
        with db._db_lock:
            session = db.get_session()
            try:
                from src.database import DocumentMaster, DocumentVersion, Document
                
                # Check if it's a version ID (for backward compatibility)
                version = session.query(DocumentVersion).filter(DocumentVersion.id == doc_id).first()
                if version:
                    master = session.query(DocumentMaster).filter(
                        DocumentMaster.id == version.document_master_id
                    ).first()
                else:
                    # Try as DocumentMaster ID
                    master = session.query(DocumentMaster).filter(DocumentMaster.id == doc_id).first()
                
                # Fallback to legacy Document
                if not master:
                    document = session.query(Document).filter(Document.id == doc_id).first()
                
                if not master and not document:
                    raise HTTPException(status_code=404, detail="Document not found")
                
                # Build response
                if master:
                    # Parse shared users/roles
                    shared_users_ids = json.loads(master.shared_with_users) if master.shared_with_users else []
                    shared_roles_codes = json.loads(master.shared_with_roles) if master.shared_with_roles else []
                    
                    # Get shared users details
                    from src.database import User as DBUser
                    shared_users = []
                    if shared_users_ids:
                        users = session.query(DBUser).filter(DBUser.id.in_(shared_users_ids)).all()
                        shared_users = [
                            {
                                "id": u.id,
                                "username": u.username,
                                "email": u.email
                            } for u in users
                        ]
                    
                    # Get shared roles details
                    from src.database import Role
                    shared_roles = []
                    if shared_roles_codes:
                        roles = session.query(Role).filter(Role.code.in_(shared_roles_codes)).all()
                        shared_roles = [
                            {
                                "code": r.code,
                                "name": r.name
                            } for r in roles
                        ]
                    
                    # Get owner info
                    owner_info = None
                    if master.owner:
                        owner_info = {
                            "id": master.owner.id,
                            "username": master.owner.username,
                            "email": master.owner.email
                        }
                    
                    # Get org info
                    org_info = None
                    if master.organization:
                        org_info = {
                            "id": master.organization.id,
                            "name": master.organization.name
                        }
                    
                    return JSONResponse(content={
                        "id": master.id,
                        "filename": master.filename_base,
                        "visibility": master.visibility,
                        "owner": owner_info,
                        "organization": org_info,
                        "shared_users": shared_users,
                        "shared_roles": shared_roles
                    })
                else:
                    # Legacy document
                    shared_users_ids = json.loads(document.shared_with_users) if document.shared_with_users else []
                    shared_roles_codes = json.loads(document.shared_with_roles) if document.shared_with_roles else []
                    
                    from src.database import User as DBUser
                    shared_users = []
                    if shared_users_ids:
                        users = session.query(DBUser).filter(DBUser.id.in_(shared_users_ids)).all()
                        shared_users = [
                            {
                                "id": u.id,
                                "username": u.username,
                                "email": u.email
                            } for u in users
                        ]
                    
                    from src.database import Role
                    shared_roles = []
                    if shared_roles_codes:
                        roles = session.query(Role).filter(Role.code.in_(shared_roles_codes)).all()
                        shared_roles = [
                            {
                                "code": r.code,
                                "name": r.name
                            } for r in roles
                        ]
                    
                    owner_info = None
                    if document.owner:
                        owner_info = {
                            "id": document.owner.id,
                            "username": document.owner.username,
                            "email": document.owner.email
                        }
                    
                    org_info = None
                    if document.organization:
                        org_info = {
                            "id": document.organization.id,
                            "name": document.organization.name
                        }
                    
                    return JSONResponse(content={
                        "id": document.id,
                        "filename": document.filename,
                        "visibility": document.visibility,
                        "owner": owner_info,
                        "organization": org_info,
                        "shared_users": shared_users,
                        "shared_roles": shared_roles
                    })
                    
            finally:
                session.close()
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_permissions_failed", doc_id=doc_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/documents/{doc_id}/permissions")
async def update_document_permissions(
    doc_id: int,
    visibility: str = Form(...),
    shared_with_users: Optional[str] = Form("[]"),
    shared_with_roles: Optional[str] = Form("[]"),
    current_user: User = Depends(get_current_user)
):
    """
    Update document permissions.
    Supports both legacy Document and new DocumentMaster/Version.
    """
    import json
    try:
        # Parse JSON arrays
        shared_users_list = json.loads(shared_with_users) if shared_with_users else []
        shared_roles_list = json.loads(shared_with_roles) if shared_with_roles else []
        
        # Validate visibility
        if visibility not in ['public', 'organization', 'private']:
            raise HTTPException(status_code=400, detail="Invalid visibility value")
        
        with db._db_lock:
            session = db.get_session()
            try:
                from src.database import DocumentMaster, DocumentVersion, Document
                
                # Try to find as version first
                version = session.query(DocumentVersion).filter(DocumentVersion.id == doc_id).first()
                if version:
                    master = session.query(DocumentMaster).filter(
                        DocumentMaster.id == version.document_master_id
                    ).first()
                else:
                    master = session.query(DocumentMaster).filter(DocumentMaster.id == doc_id).first()
                
                # Fallback to legacy Document
                document = None
                if not master:
                    document = session.query(Document).filter(Document.id == doc_id).first()
                
                if not master and not document:
                    raise HTTPException(status_code=404, detail="Document not found")
                
                # Check permission to update
                target = master if master else document
                if not current_user.is_superuser and target.owner_id != current_user.id:
                    raise HTTPException(
                        status_code=403,
                        detail="Only document owner can update permissions"
                    )
                
                # Update permissions
                target.visibility = visibility
                target.shared_with_users = json.dumps(shared_users_list)
                target.shared_with_roles = json.dumps(shared_roles_list)
                target.updated_at = datetime.utcnow()
                
                session.commit()
                
                logger.info("permissions_updated",
                           doc_id=doc_id,
                           type="master" if master else "document",
                           user_id=current_user.id)
                
                return JSONResponse(content={
                    "message": "Permissions updated successfully"
                })
                
            except HTTPException:
                session.rollback()
                raise
            except Exception as e:
                session.rollback()
                raise e
            finally:
                session.close()
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_permissions_failed", doc_id=doc_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

