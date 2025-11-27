"""FastAPI web application for RAG Knowledge Base"""

import os
import shutil
import json
import subprocess
import sys
import threading
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
from src.logging_config import setup_logging
from src.task_manager import task_manager, TaskStatus, TaskStage

# Import routers from separate modules
from web.routes import document_router, cleanup_router
from web.handlers import extract_matched_bboxes_from_file

# Initialize logging with configuration from config.yaml
setup_logging(log_config=config.logging_config)
logger = structlog.get_logger(__name__)

# Concurrent processing control (limit to 3 documents processing at the same time)
processing_semaphore = threading.Semaphore(3)

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

# Include routers
app.include_router(document_router)
app.include_router(cleanup_router)

# Create upload and processed folders
upload_folder = Path(web_config.get('upload_folder', './uploads'))
upload_folder.mkdir(parents=True, exist_ok=True)

processed_folder = Path('web/static/processed_docs')
processed_folder.mkdir(parents=True, exist_ok=True)


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


def process_single_pdf(doc_id: int, pdf_path: Path, metadata: dict, ocr_engine: str, checksum: str, parent_task_id: Optional[int] = None):
    """Process a single PDF file"""
    try:
        # Update task status
        task_manager.update_task(
            doc_id,
            status=TaskStatus.RUNNING,
            stage=TaskStage.OCR_PROCESSING,
            progress_percentage=10,
            message=f"Processing {pdf_path.name}...",
            filename=pdf_path.name
        )
        db.update_document_progress(doc_id, 10, f"Starting OCR for {pdf_path.name}...")
        
        # Check for cancellation
        if not task_manager.wait_if_paused(doc_id):
            raise InterruptedError("Task was cancelled by user")
        
            # Run adaptive OCR pipeline
            adaptive_script = Path('document_ocr_pipeline/adaptive_ocr_pipeline.py')
            subprocess.run([
                sys.executable,
                str(adaptive_script),
            str(pdf_path),
                '--ocr-engine', ocr_engine
            ], check=True)
        
        # Check for cancellation after OCR
        if not task_manager.wait_if_paused(doc_id):
            raise InterruptedError("Task was cancelled by user")
        
        task_manager.update_task(
            doc_id,
            progress_percentage=50,
            message="OCR completed, processing pages..."
        )
        db.update_document_progress(doc_id, 50, "OCR completed, processing pages...")
        
        # Find the generated output directory
        temp_output_dir = Path(pdf_path.stem.replace(' ', '_') + "_adaptive")
        
        if not temp_output_dir.exists():
            raise RuntimeError(f"OCR output directory not found: {temp_output_dir}")
        
        # Check for cancellation before moving files
        if not task_manager.wait_if_paused(doc_id):
            raise InterruptedError("Task was cancelled by user")
        
        # Move to static folder with doc ID
        doc_output_dir = processed_folder / f"{doc_id}_{checksum[:8]}"
        if doc_output_dir.exists():
            shutil.rmtree(doc_output_dir)
        shutil.move(str(temp_output_dir), str(doc_output_dir))
        
        # Update progress: Loading pages data
        task_manager.update_task(
            doc_id,
            stage=TaskStage.VLM_EXTRACTION,
            progress_percentage=60,
            message="Loading pages data..."
        )
        db.update_document_progress(doc_id, 60, "Loading pages data...")
        
        # Load pages data
        complete_json = doc_output_dir / 'complete_adaptive_ocr.json'
        pages_data_list = []
        total_pages = 0
        
        if complete_json.exists():
            with open(complete_json, 'r', encoding='utf-8') as f:
                complete_data = json.load(f)
            
            total_pages = len(complete_data.get('pages', []))
            task_manager.update_task(
                doc_id,
                progress_percentage=65,
                message=f"Processing {total_pages} pages...",
                total_pages=total_pages,
                processed_pages=0
            )
            db.update_document_progress(doc_id, 65, f"Processing {total_pages} pages...", 
                                       processed_pages=0, total_pages=total_pages)
            
            # Build pages data
            for idx, page in enumerate(complete_data.get('pages', []), 1):
                # Check for cancellation/pause before each page
                if not task_manager.wait_if_paused(doc_id):
                    raise InterruptedError("Task was cancelled by user")
                
                page_num = page.get('page_number', idx)
                
                # Update progress per page
                page_progress = 65 + (20 * idx / total_pages)  # 65-85% for page processing
                task_manager.update_task(
                    doc_id,
                    progress_percentage=int(page_progress),
                    message=f"Processing page {idx}/{total_pages}...",
                    current_page=idx,
                    processed_pages=idx
                )
                db.update_document_progress(
                    doc_id, 
                    int(page_progress), 
                    f"Processing page {idx}/{total_pages}...",
                    processed_pages=idx,
                    total_pages=total_pages
                )
                
                # Get text count from statistics
                stats = page.get('statistics', {})
                text_count = stats.get('total_text_blocks', 0)
                
                # Get stage1 file paths
                stage1 = page.get('stage1_global', {})
                image_filename = stage1.get('image', f'page_{page_num:03d}_300dpi.png')
                visualized_filename = stage1.get('visualized', f'page_{page_num:03d}_global_visualized.png')
                ocr_json_filename = stage1.get('ocr_json', f'page_{page_num:03d}_global_ocr.json')
                
                # Try to extract components from VLM JSON if available
                components = []
                stage3 = page.get('stage3_vlm', {})
                vlm_json_filename = stage3.get('vlm_json')
                if vlm_json_filename:
                    vlm_json_path = doc_output_dir / vlm_json_filename
                    if vlm_json_path.exists():
                        try:
                            with open(vlm_json_path, 'r', encoding='utf-8') as vf:
                                vlm_data = json.load(vf)
                                # Try different possible locations for components
                                if 'components' in vlm_data:
                                    components = vlm_data['components']
                                elif 'domain_data' in vlm_data and isinstance(vlm_data['domain_data'], dict):
                                    if 'components' in vlm_data['domain_data']:
                                        components = vlm_data['domain_data']['components']
                                    elif 'equipment' in vlm_data['domain_data']:
                                        equipment = vlm_data['domain_data']['equipment']
                                        if isinstance(equipment, list):
                                            components = [e.get('id', '') for e in equipment if isinstance(e, dict) and 'id' in e]
                        except Exception as e:
                            logger.warning("failed_to_parse_vlm_json", error=str(e), file=vlm_json_filename)
                
                page_info = {
                    'page_num': page_num,
                    'image_path': f"/static/processed_docs/{doc_id}_{checksum[:8]}/{image_filename}",
                    'visualized_path': f"/static/processed_docs/{doc_id}_{checksum[:8]}/{visualized_filename}",
                    'ocr_json_path': f"/static/processed_docs/{doc_id}_{checksum[:8]}/{ocr_json_filename}",
                    'text_count': text_count,
                    'components': components[:20] if components else []
                }
                pages_data_list.append(page_info)
        
        # Check for cancellation before indexing
        if not task_manager.wait_if_paused(doc_id):
            raise InterruptedError("Task was cancelled by user")
        
        # Update progress: Indexing to Elasticsearch
        task_manager.update_task(
            doc_id,
            stage=TaskStage.INDEXING,
            progress_percentage=85,
            message="Indexing to Elasticsearch..."
        )
        db.update_document_progress(doc_id, 85, "Indexing to Elasticsearch...")
        
        # Add document identifiers to metadata for MinIO naming
        metadata['document_id'] = doc_id
        metadata['filename'] = pdf_path.name
        metadata['checksum'] = checksum
        
        # Process with vector store
        result = pipeline.process_file(str(pdf_path), metadata, processed_json_dir=str(doc_output_dir))
        
        # Check for cancellation after indexing
        if not task_manager.wait_if_paused(doc_id):
            raise InterruptedError("Task was cancelled by user")
        
        # Update progress: Finalizing
        task_manager.update_task(
            doc_id,
            stage=TaskStage.FINALIZING,
            progress_percentage=95,
            message="Finalizing..."
        )
        db.update_document_progress(doc_id, 95, "Finalizing...")
        
        # Update database with result
        if result.get('status') == 'completed':
            if not result.get('document_ids'):
                error_msg = 'Processing completed but no documents were indexed to Elasticsearch'
                logger.error("NO_DOCUMENTS_INDEXED", 
                           num_chunks=result.get('num_chunks', 0), doc_id=doc_id)
                task_manager.complete_task(doc_id, success=False, error_message=error_msg)
                db.update_document_status(doc_id, 'failed', error_message=error_msg)
            else:
                task_manager.complete_task(doc_id, success=True)
                db.update_document_status(
                    doc_id,
                    'completed',
                    num_chunks=result.get('num_chunks', 0),
                    es_document_ids=json.dumps(result.get('document_ids', [])),
                    pages_data=json.dumps(pages_data_list)
                )
                logger.info("document_processing_completed", doc_id=doc_id, 
                          num_chunks=result.get('num_chunks', 0))
        else:
            error_msg = result.get('error', 'Unknown error')
            task_manager.complete_task(doc_id, success=False, error_message=error_msg)
            db.update_document_status(doc_id, 'failed', error_message=error_msg)
        
    except InterruptedError:
        raise
    except Exception as e:
        logger.error("pdf_processing_failed", error=str(e), doc_id=doc_id, pdf=pdf_path.name)
        raise




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
        
        # Enrich results with pages_data and matched bboxes from database
        for result in results:
            metadata = result.get('metadata', {})
            checksum = metadata.get('checksum')
            
            if checksum:
                # Query database for document with this checksum
                doc = db.get_document_by_checksum(checksum)
                if doc and doc.pages_data:
                    try:
                        # Parse pages_data JSON and add to metadata
                        pages_data = json.loads(doc.pages_data) if isinstance(doc.pages_data, str) else doc.pages_data
                        metadata['pages_data'] = pages_data
                        metadata['ocr_engine'] = doc.ocr_engine
                        
                        # Extract matched bboxes for this result
                        matched_bboxes = extract_matched_bboxes_from_file(
                            doc_id=doc.id,
                            checksum=checksum,
                            page_number=metadata.get('page_number', 1),
                            query_text=request.query
                        )
                        result['matched_bboxes'] = matched_bboxes
                        
                    except json.JSONDecodeError:
                        logger.warning("failed_to_parse_pages_data", checksum=checksum)
        
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

