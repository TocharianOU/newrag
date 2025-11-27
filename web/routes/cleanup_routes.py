"""Data synchronization and cleanup routes"""

from pathlib import Path
from typing import List, Optional
import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from elasticsearch.helpers import scan
import shutil
from elasticsearch.helpers import scan
from src.database import DatabaseManager
from src.pipeline import ProcessingPipeline
from src.minio_storage import minio_storage

db = DatabaseManager()
pipeline = ProcessingPipeline()


logger = structlog.get_logger(__name__)

# Create router
router = APIRouter(prefix="", tags=["cleanup"])


# ============================================================
# 示例路由 - 你可以把其他清理相关的路由复制到这里
# ============================================================

@router.get("/data-sync-check")
async def check_data_synchronization():
    """
    检查 Database、Elasticsearch、MinIO 三者之间的数据同步状态
    返回不一致的记录和统计信息
    
    示例函数 - 其他清理路由可以复制到这里：
    - POST /cleanup-elasticsearch
    - POST /cleanup-minio
    - POST /cleanup-local-files
    - GET /orphan-check
    - DELETE /orphan-cleanup
    """
    try:
        from src.database import DatabaseManager
        from src.pipeline import ProcessingPipeline
        from src.minio_storage import minio_storage
        
        db = DatabaseManager()
        pipeline = ProcessingPipeline()
        
        sync_report = {
            "database_docs": 0,
            "elasticsearch_docs": 0,
            "minio_prefixes": 0,
            "local_folders": 0,
            "inconsistencies": [],
            "summary": {}
        }
        
        # 1. 从数据库获取所有文档
        db_docs = db.list_documents(limit=10000)
        sync_report["database_docs"] = len(db_docs)
        
        db_doc_ids = {str(doc.get('id')): doc for doc in db_docs}
        
        # 2. 从 Elasticsearch 获取所有不重复的 document_id
        es_client = pipeline.vector_store.es_client
        index_name = pipeline.vector_store.index_name
        
        es_document_ids = set()
        try:
            query = {"query": {"match_all": {}}}
            for hit in scan(es_client, index=index_name, query=query, _source=['metadata.document_id']):
                doc_id = hit['_source'].get('metadata', {}).get('document_id')
                if doc_id:
                    es_document_ids.add(str(doc_id))
            
            sync_report["elasticsearch_docs"] = len(es_document_ids)
        except Exception as es_error:
            logger.warning("es_scan_failed", error=str(es_error))
            sync_report["elasticsearch_docs"] = "ERROR"
        
        # 3. 检查本地 processed_docs 文件夹
        processed_folder = Path('web/static/processed_docs')
        local_folders = set()
        if processed_folder.exists():
            for folder in processed_folder.iterdir():
                if folder.is_dir():
                    local_folders.add(folder.name)
        
        sync_report["local_folders"] = len(local_folders)
        
        # 4. 检查 MinIO（如果启用）
        minio_prefixes = set()
        if minio_storage.enabled:
            try:
                all_objects = minio_storage.list_objects(prefix="")
                # 提取 prefix（第一层目录）
                for obj_name in all_objects:
                    prefix = obj_name.split('/')[0] if '/' in obj_name else obj_name
                    minio_prefixes.add(prefix)
                
                sync_report["minio_prefixes"] = len(minio_prefixes)
            except Exception as minio_error:
                logger.warning("minio_scan_failed", error=str(minio_error))
                sync_report["minio_prefixes"] = "ERROR"
        else:
            sync_report["minio_prefixes"] = "DISABLED"
        
        # 5. 查找不一致的数据
        # 5.1 Database 中有，但 ES 中没有
        for doc_id, doc in db_doc_ids.items():
            if doc_id not in es_document_ids:
                sync_report["inconsistencies"].append({
                    "type": "missing_in_es",
                    "doc_id": doc_id,
                    "filename": doc.get('filename'),
                    "checksum": doc.get('checksum', '')[:8]
                })
        
        # 5.2 ES 中有，但 Database 中没有
        for es_doc_id in es_document_ids:
            if es_doc_id not in db_doc_ids:
                sync_report["inconsistencies"].append({
                    "type": "orphan_in_es",
                    "doc_id": es_doc_id,
                    "message": "ES中存在但Database中不存在"
                })
        
        # 5.3 Database 中有，但本地文件夹不存在
        for doc_id, doc in db_doc_ids.items():
            checksum = doc.get('checksum', '')
            expected_folder = f"{doc_id}_{checksum[:8]}"
            if expected_folder not in local_folders:
                sync_report["inconsistencies"].append({
                    "type": "missing_local_files",
                    "doc_id": doc_id,
                    "filename": doc.get('filename'),
                    "expected_folder": expected_folder
                })
        
        # 6. 生成摘要
        sync_report["summary"] = {
            "total_inconsistencies": len(sync_report["inconsistencies"]),
            "missing_in_es": len([i for i in sync_report["inconsistencies"] if i["type"] == "missing_in_es"]),
            "orphan_in_es": len([i for i in sync_report["inconsistencies"] if i["type"] == "orphan_in_es"]),
            "missing_local_files": len([i for i in sync_report["inconsistencies"] if i["type"] == "missing_local_files"]),
            "sync_status": "SYNCED" if len(sync_report["inconsistencies"]) == 0 else "OUT_OF_SYNC"
        }
        
        logger.info("data_sync_check_completed", **sync_report["summary"])
        
        return JSONResponse(content=sync_report)
        
    except Exception as e:
        logger.error("data_sync_check_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup-elasticsearch")
async def cleanup_elasticsearch_orphans():
    """
    清理 Elasticsearch 中的孤岛数据
    删除所有在 ES 中存在但在 Database 中不存在的文档
    """
    try:
        from elasticsearch.helpers import scan
        
        # 1. 获取数据库中所有的 document_id
        db_docs = db.list_documents(limit=10000)
        valid_doc_ids = {str(doc.get('id')) for doc in db_docs}
        
        # 2. 扫描 ES，找出孤岛数据
        es_client = pipeline.vector_store.es_client
        index_name = pipeline.vector_store.index_name
        
        orphan_doc_ids = set()
        query = {"query": {"match_all": {}}}
        
        for hit in scan(es_client, index=index_name, query=query, _source=['metadata.document_id']):
            doc_id = hit['_source'].get('metadata', {}).get('document_id')
            if doc_id and str(doc_id) not in valid_doc_ids:
                orphan_doc_ids.add(str(doc_id))
        
        # 3. 删除孤岛数据
        deleted_count = 0
        for orphan_id in orphan_doc_ids:
            try:
                count = pipeline.vector_store.delete_by_metadata({"document_id": orphan_id})
                deleted_count += count
            except Exception as e:
                logger.warning("orphan_deletion_failed", doc_id=orphan_id, error=str(e))
        
        logger.info("es_orphans_cleaned", orphan_doc_ids=len(orphan_doc_ids), chunks_deleted=deleted_count)
        
        return JSONResponse(content={
            "status": "success",
            "message": f"Cleaned {deleted_count} orphan chunks from Elasticsearch",
            "orphan_documents": len(orphan_doc_ids),
            "chunks_deleted": deleted_count
        })
        
    except Exception as e:
        logger.error("cleanup_es_orphans_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup-minio")
async def cleanup_minio_orphans():
    """
    清理 MinIO 中的孤岛数据
    删除所有在 MinIO 中存在但在 Database 中不存在的文件夹
    """
    try:
        from src.minio_storage import minio_storage
        
        if not minio_storage.enabled:
            return JSONResponse(content={
                "status": "skipped",
                "message": "MinIO is disabled"
            })
        
        # 1. 获取数据库中所有文档的 MinIO prefix
        db_docs = db.list_documents(limit=10000)
        valid_prefixes = set()
        
        for doc in db_docs:
            doc_id = doc.get('id')
            checksum = doc.get('checksum', '')
            filename = doc.get('filename', '')
            
            if checksum and filename:
                filename_base = Path(filename).stem.replace(' ', '_').replace('/', '_')
                prefix = f"{filename_base}_{doc_id}_{checksum[:8]}"
                valid_prefixes.add(prefix)
        
        # 2. 获取 MinIO 中所有的 prefix
        all_objects = minio_storage.list_objects(prefix="")
        minio_prefixes = set()
        
        for obj_name in all_objects:
            prefix = obj_name.split('/')[0] if '/' in obj_name else obj_name
            minio_prefixes.add(prefix)
        
        # 3. 找出孤岛 prefix（在 MinIO 中但不在数据库中）
        orphan_prefixes = minio_prefixes - valid_prefixes
        
        # 4. 删除孤岛数据
        deleted_count = 0
        for orphan_prefix in orphan_prefixes:
            count = minio_storage.delete_directory(orphan_prefix)
            deleted_count += count
        
        logger.info("minio_orphans_cleaned", 
                   orphan_prefixes=len(orphan_prefixes), 
                   files_deleted=deleted_count)
        
        return JSONResponse(content={
            "status": "success",
            "message": f"Cleaned {deleted_count} orphan files from MinIO",
            "orphan_prefixes": len(orphan_prefixes),
            "files_deleted": deleted_count,
            "cleaned_prefixes": list(orphan_prefixes)
        })
        
    except Exception as e:
        logger.error("cleanup_minio_orphans_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup-local-files")
async def cleanup_local_orphan_files():
    """
    清理本地 processed_docs 中的孤岛文件夹
    删除所有在本地存在但在 Database 中不存在的文件夹
    """
    try:
        # 1. 获取数据库中所有文档的文件夹名
        db_docs = db.list_documents(limit=10000)
        valid_folders = set()
        
        for doc in db_docs:
            doc_id = doc.get('id')
            checksum = doc.get('checksum', '')
            if checksum:
                folder_name = f"{doc_id}_{checksum[:8]}"
                valid_folders.add(folder_name)
        
        # 2. 扫描本地文件夹
        processed_folder = Path('web/static/processed_docs')
        orphan_folders = []
        
        if processed_folder.exists():
            for folder in processed_folder.iterdir():
                if folder.is_dir() and folder.name not in valid_folders:
                    orphan_folders.append(folder)
        
        # 3. 删除孤岛文件夹
        import shutil
        deleted_count = 0
        
        for folder in orphan_folders:
            try:
                shutil.rmtree(folder)
                deleted_count += 1
            except Exception as e:
                logger.warning("folder_deletion_failed", folder=str(folder), error=str(e))
        
        logger.info("local_orphans_cleaned", 
                   orphan_folders=len(orphan_folders), 
                   deleted=deleted_count)
        
        return JSONResponse(content={
            "status": "success",
            "message": f"Cleaned {deleted_count} orphan folders from local storage",
            "orphan_folders_found": len(orphan_folders),
            "deleted": deleted_count
        })
        
    except Exception as e:
        logger.error("cleanup_local_orphans_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orphan-check")
async def check_orphan_documents():
    """
    Check for orphan documents in ES (documents without corresponding files)
    """
    try:
        orphans = []
        processed_folder_path = Path('web/static/processed_docs')
        
        # Get all documents from ES
        es_client = pipeline.vector_store.es_client
        index_name = pipeline.vector_store.index_name
        
        # Check if index exists
        if not es_client.indices.exists(index=index_name):
            return JSONResponse(content={
                "status": "no_index",
                "orphans": [],
                "total": 0
            })
        
        # Scan all documents in ES
        from elasticsearch.helpers import scan
        query = {"query": {"match_all": {}}}
        
        # Track unique document folders to avoid duplicate checks
        folders_checked = set()
        
        for hit in scan(es_client, index=index_name, query=query, _source=['metadata']):
            metadata = hit['_source'].get('metadata', {})
            doc_id = metadata.get('document_id')
            checksum = metadata.get('checksum', '')
            filename = metadata.get('filename', 'unknown')
            filepath = metadata.get('filepath', '')
            
            # Determine the folder path for this document
            if checksum:
                folder_key = f"{doc_id}_{checksum[:8]}"
                doc_folder = processed_folder_path / folder_key
            else:
                folder_key = str(doc_id)
                doc_folder = processed_folder_path / folder_key
            
            # Skip if we've already checked this folder
            if folder_key in folders_checked:
                continue
            
            folders_checked.add(folder_key)
            
            # Check if processed folder OR original file exists
            file_exists = doc_folder.exists()
            if not file_exists and filepath:
                # Also check original file path
                original_file = Path(filepath)
                file_exists = original_file.exists()
            
            if not file_exists:
                # This is an orphan - ES record exists but no files
                # Check if document exists in database
                db_doc = None
                try:
                    if doc_id and isinstance(doc_id, int):
                        db_doc = db.get_document(doc_id)
                    elif checksum:
                        db_doc = db.get_document_by_checksum(checksum)
                except:
                    pass
                
                orphans.append({
                    'es_id': hit['_id'],
                    'document_id': doc_id,
                    'checksum': checksum,
                    'filename': filename,
                    'filepath': filepath,
                    'expected_folder': str(doc_folder),
                    'metadata': metadata,
                    'in_database': bool(db_doc),
                    'file_exists': False
                })
        
        return JSONResponse(content={
            "status": "success",
            "orphans": orphans,
            "total": len(orphans)
        })
    
    except Exception as e:
        logger.error("orphan_check_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/orphan-cleanup")
async def cleanup_orphan_documents(document_ids: Optional[List[str]] = None):
    """
    Clean up orphan documents from ES
    If document_ids is provided, clean specific documents, otherwise clean all orphans
    """
    try:
        es_client = pipeline.vector_store.es_client
        index_name = pipeline.vector_store.index_name
        
        if not es_client.indices.exists(index=index_name):
            return JSONResponse(content={
                "status": "no_index",
                "deleted_count": 0
            })
        
        deleted_count = 0
        
        if document_ids:
            # Delete specific documents (by document_id from metadata)
            for doc_id_str in document_ids:
                try:
                    # Try to convert to int if it's a document ID
                    try:
                        doc_id_int = int(doc_id_str)
                        filter_dict = {"document_id": doc_id_int}
                    except (ValueError, TypeError):
                        # If not an int, treat as string (checksum or other identifier)
                        filter_dict = {"document_id": doc_id_str}
                    
                    count = pipeline.vector_store.delete_by_metadata(filter_dict)
                    deleted_count += count
                    logger.info("deleted_orphan_chunks", doc_id=doc_id_str, count=count)
                except Exception as e:
                    logger.warning("failed_to_delete_orphan", doc_id=doc_id_str, error=str(e))
        else:
            # Get all orphans and delete them
            orphan_check = await check_orphan_documents()
            orphan_data = json.loads(orphan_check.body.decode())
            
            for orphan in orphan_data.get('orphans', []):
                doc_id = orphan['document_id']
                try:
                    count = pipeline.vector_store.delete_by_metadata({"document_id": doc_id})
                    deleted_count += count
                except Exception as e:
                    logger.warning("failed_to_delete_orphan", doc_id=doc_id, error=str(e))
        
        return JSONResponse(content={
            "status": "success",
            "deleted_count": deleted_count
        })
    
    except Exception as e:
        logger.error("orphan_cleanup_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/es-index/delete")
async def delete_es_document_by_id(es_doc_id: str):
    """
    Delete a specific document from ES by its ES document ID
    """
    try:
        es_client = pipeline.vector_store.es_client
        index_name = pipeline.vector_store.index_name
        
        response = es_client.delete(index=index_name, id=es_doc_id)
        
        return JSONResponse(content={
            "status": "success",
            "es_id": es_doc_id,
            "result": response.get('result', 'deleted')
        })
    
    except Exception as e:
        logger.error("es_document_deletion_failed", es_id=es_doc_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# TODO: 把以下函数从 app.py 复制到这里
# ============================================================
# - cleanup_elasticsearch_orphans()
# - cleanup_minio_orphans()
# - cleanup_local_orphan_files()
# - check_orphan_documents()
# - cleanup_orphan_documents()
# - delete_es_document_by_id()

