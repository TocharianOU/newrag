"""FastAPI web application for RAG Knowledge Base"""

import os
import shutil
import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime

import structlog
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from src.config import config
from src.pipeline import ProcessingPipeline
from src.database import DatabaseManager

# Initialize logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="AIOps RAG Knowledge Base",
    description="AI-powered knowledge base for IT Operations and Security",
    version="0.1.0"
)

# CORS configuration
web_config = config.web_config
cors_config = web_config.get('cors', {})
if cors_config.get('enabled', True):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_config.get('allow_origins', ["*"]),
        allow_credentials=True,
        allow_methods=cors_config.get('allow_methods', ["*"]),
        allow_headers=cors_config.get('allow_headers', ["*"]),
    )

# Setup templates and static files
templates = Jinja2Templates(directory="web/templates")
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Initialize pipeline and database
pipeline = ProcessingPipeline()
db = DatabaseManager()

# Create upload folder
upload_folder = Path(web_config.get('upload_folder', './uploads'))
upload_folder.mkdir(parents=True, exist_ok=True)


# Pydantic models
class SearchRequest(BaseModel):
    query: str
    k: int = 5
    filters: Optional[dict] = None
    use_hybrid: bool = True


class SearchResponse(BaseModel):
    results: List[dict]
    total: int


class MetadataUpdate(BaseModel):
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    author: Optional[str] = None
    description: Optional[str] = None


# Routes
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render main page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    description: Optional[str] = Form(None)
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
            description=description
        )
        doc_id = doc.id
        
        # Update status to processing
        db.update_document_status(doc_id, 'processing')
        
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
        
        # Process file
        result = pipeline.process_file(str(file_path), metadata)
        
        # Update database with result
        if result.get('status') == 'completed':
            db.update_document_status(
                doc_id,
                'completed',
                num_chunks=result.get('num_chunks', 0),
                es_document_ids=json.dumps(result.get('document_ids', []))
            )
        else:
            db.update_document_status(
                doc_id,
                'failed',
                error_message=result.get('error', 'Unknown error')
            )
        
        # Clean up file
        if file_path and file_path.exists():
            os.remove(file_path)
        
        # Add document info to result
        result['document_id'] = doc_id
        result['checksum'] = checksum
        
        return JSONResponse(content=result)
    
    except Exception as e:
        logger.error("upload_failed", error=str(e))
        
        # Update database if record was created
        if doc_id:
            db.update_document_status(doc_id, 'failed', error_message=str(e))
        
        # Clean up file
        if file_path and file_path.exists():
            os.remove(file_path)
        
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload_batch")
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


@app.post("/upload_zip")
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


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """
    Search knowledge base
    """
    try:
        results = pipeline.search(
            query=request.query,
            k=request.k,
            filters=request.filters,
            use_hybrid=request.use_hybrid
        )
        
        return SearchResponse(results=results, total=len(results))
    
    except Exception as e:
        logger.error("search_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/component/{component_id}")
async def search_component(component_id: str, k: int = 10):
    """
    Search for pages containing specific component
    
    Args:
        component_id: Component ID (e.g., C1, V-2001, R100)
        k: Number of results to return
    
    Returns:
        List of pages containing the component
    """
    try:
        results = pipeline.search_component(
            component_id=component_id,
            k=k
        )
        
        return {
            "component_id": component_id,
            "results": results,
            "total": len(results)
        }
    
    except Exception as e:
        logger.error("component_search_failed", error=str(e), component_id=component_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_stats():
    """
    Get knowledge base statistics
    """
    try:
        # Get ES stats
        es_stats = pipeline.vector_store.get_stats()
        
        # Get database stats
        db_stats = db.get_stats()
        
        # Get ES index info
        es_client = pipeline.vector_store.es_client
        index_name = pipeline.vector_store.index_name
        
        # Check if index exists
        try:
            index_exists_response = es_client.indices.exists(index=index_name)
            # Handle both old and new ES client API responses
            if hasattr(index_exists_response, 'body'):
                index_exists = bool(index_exists_response.body)
            else:
                index_exists = bool(index_exists_response)
        except Exception:
            index_exists = False
        
        index_info = {
            'name': index_name,
            'exists': index_exists
        }
        
        if index_exists:
            index_info['status'] = 'green'  # Simplified, you can get real status from cluster health
            index_info['document_count'] = es_stats.get('document_count', 0)
        else:
            index_info['status'] = 'not_created'
            index_info['document_count'] = 0
        
        combined_stats = {
            **es_stats,
            'database': db_stats,
            'index': index_info
        }
        
        return JSONResponse(content=combined_stats)
    
    except Exception as e:
        logger.error("stats_retrieval_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/documents")
async def delete_documents(filters: dict):
    """
    Delete documents by metadata filter
    """
    try:
        count = pipeline.vector_store.delete_by_metadata(filters)
        return JSONResponse(content={"deleted_count": count})
    
    except Exception as e:
        logger.error("deletion_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents")
async def list_documents(limit: int = 50, offset: int = 0, status: Optional[str] = None):
    """List uploaded documents"""
    try:
        docs = db.list_documents(limit=limit, offset=offset, status=status)
        return JSONResponse(content={
            "documents": [doc.to_dict() for doc in docs],
            "total": len(docs)
        })
    except Exception as e:
        logger.error("list_documents_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: int):
    """Delete a specific document by ID"""
    try:
        success = db.delete_document(doc_id)
        if success:
            return JSONResponse(content={"status": "success", "message": f"Document {doc_id} deleted"})
        else:
            raise HTTPException(status_code=404, detail="Document not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_document_failed", error=str(e), doc_id=doc_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/documents")
async def delete_all_documents():
    """Delete all documents from database"""
    try:
        db.delete_all_documents()
        return JSONResponse(content={"status": "success", "message": "All documents deleted"})
    except Exception as e:
        logger.error("delete_all_documents_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    
    host = web_config.get('host', '0.0.0.0')
    port = web_config.get('port', 8000)
    
    logger.info("starting_web_server", host=host, port=port)
    
    uvicorn.run(app, host=host, port=port)

