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


def extract_matched_bboxes_from_file(doc_id: int, checksum: str, page_number: int, query_text: str):
    """
    Extract matched bboxes from OCR JSON file for visualization
    
    Args:
        doc_id: Document ID
        checksum: Document checksum (first 8 chars used in folder name)
        page_number: Page number to extract bboxes from
        query_text: Query text to match against OCR text blocks
        
    Returns:
        List of matched bbox dicts with text, bbox, confidence, matched_words
    """
    import re
    
    try:
        # Build path to processed document folder
        doc_folder = processed_folder / f"{doc_id}_{checksum[:8]}"
        
        if not doc_folder.exists():
            logger.warning("doc_folder_not_found", doc_id=doc_id, folder=str(doc_folder))
            return []
        
        # Load OCR JSON file for the specific page
        ocr_json_file = doc_folder / f"page_{page_number:03d}_global_ocr.json"
        if not ocr_json_file.exists():
            logger.warning("ocr_json_not_found", page=page_number, file=str(ocr_json_file))
            return []
        
        with open(ocr_json_file, 'r', encoding='utf-8') as f:
            ocr_data = json.load(f)
        
        text_blocks = ocr_data.get('text_blocks', [])
        if not text_blocks:
            return []
        
        # Normalize query for matching
        query_normalized = re.sub(r'\s+', ' ', query_text.lower().strip())
        query_words = query_normalized.split()
        
        matched_bboxes = []
        
        # Match text blocks
        for idx, block in enumerate(text_blocks):
            text = block.get('text', '')
            bbox = block.get('bbox', [])
            confidence = block.get('confidence', 0.0)
            
            if not text or not bbox or len(bbox) != 4:
                continue
            
            text_normalized = text.lower()
            
            # Check if any query word is in this text block
            matched = False
            matched_words = []
            
            for word in query_words:
                if len(word) >= 2 and word in text_normalized:
                    matched = True
                    matched_words.append(word)
            
            # Also try partial matching for longer queries
            if not matched and len(query_normalized) >= 4:
                if query_normalized in text_normalized:
                    matched = True
                    matched_words.append(query_normalized)
            
            if matched:
                matched_bboxes.append({
                    'text': text,
                    'bbox': bbox,  # [x1, y1, x2, y2]
                    'confidence': confidence,
                    'matched_words': matched_words,
                    'block_index': idx
                })
        
        # Sort by confidence (highest first)
        matched_bboxes.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Limit to top 20 matches
        result = matched_bboxes[:20]
        logger.info("extracted_matched_bboxes", page=page_number, count=len(result), total_matches=len(matched_bboxes))
        return result
        
    except Exception as e:
        logger.error("failed_to_extract_bboxes", error=str(e), doc_id=doc_id, page=page_number)
        return []


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


def process_document_background(doc_id: int, file_path: Path, metadata: dict, ocr_engine: str, checksum: str):
    """Background task to process document with full control"""
    # Create task in task manager
    task_manager.create_task(doc_id)
    
    # Wait for processing slot (max 3 concurrent documents)
    with processing_semaphore:
        temp_extract_dir = None
        
        try:
            # Update task status
            task_manager.update_task(
                    doc_id,
                status=TaskStatus.RUNNING,
                stage=TaskStage.INITIALIZING,
                progress_percentage=0,
                message="Initializing document processing...",
                filename=file_path.name
            )
            db.update_document_progress(doc_id, 0, "Initializing...")
            logger.info("background_processing_started", doc_id=doc_id, filename=file_path.name)
            
            # Check for cancellation
            if not task_manager.wait_if_paused(doc_id):
                raise InterruptedError("Task was cancelled by user")
            
            # Determine file type and handle accordingly
            file_ext = file_path.suffix.lower()
            
            # Handle ZIP files - extract and process all PDFs
            if file_ext == '.zip':
                import zipfile
                
                task_manager.update_task(
                doc_id,
                    stage=TaskStage.EXTRACTING_ZIP,
                    progress_percentage=5,
                    message="Extracting ZIP archive...",
                    is_zip_parent=True
                )
                db.update_document_progress(doc_id, 5, "Extracting ZIP archive...")
                logger.info("extracting_zip", doc_id=doc_id, zip_file=file_path.name)
                
                # Create temporary extraction directory
                temp_extract_dir = upload_folder / f"temp_extract_{doc_id}_{checksum[:8]}"
                temp_extract_dir.mkdir(exist_ok=True)
                
                # Extract ZIP
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(temp_extract_dir)
                    
                    # Find all PDF files in extracted content, ignoring hidden files and __MACOSX
                    pdf_files = []
                    for p in temp_extract_dir.rglob('*'):
                        if p.is_file() and p.suffix.lower() == '.pdf':
                            # Check if any part of the path is hidden or __MACOSX
                            parts = p.relative_to(temp_extract_dir).parts
                            if not any(part.startswith('.') or part == '__MACOSX' for part in parts):
                                pdf_files.append(p)
                    
                    if not pdf_files:
                        raise ValueError("No PDF files found in ZIP archive")
                    
                    logger.info("found_pdfs_in_zip", count=len(pdf_files), doc_id=doc_id)
                    
                    # Update parent task with total files
                    task_manager.update_task(
                        doc_id,
                        total_files=len(pdf_files),
                        processed_files=0,
                        message=f"Found {len(pdf_files)} PDF files in ZIP"
                    )
                    
                    # Process each PDF as a sub-task
                    for idx, pdf_path in enumerate(pdf_files, 1):
                        # Check for cancellation
                        if not task_manager.wait_if_paused(doc_id):
                            raise InterruptedError("Task was cancelled by user")
                        
                        # Create sub-task (use negative IDs to avoid conflicts)
                        child_doc_id = -(doc_id * 1000 + idx)
                        child_checksum = f"{checksum}_{idx}"
                        
                        # Create child task
                        task_manager.create_task(child_doc_id)
                        task_manager.add_child_task(doc_id, child_doc_id)
                        
                        # Create database record for child
                        child_doc = db.create_document(
                            filename=pdf_path.name,
                            file_path=str(pdf_path),
                            file_type='pdf',
                            file_size=pdf_path.stat().st_size,
                            checksum=child_checksum,
                            category=metadata.get('category'),
                            tags=metadata.get('tags'),
                            author=metadata.get('author'),
                            description=f"From ZIP: {file_path.name}",
                            ocr_engine=ocr_engine
                        )
                        
                        # Update parent progress
                        parent_progress = 10 + (80 * (idx - 1) / len(pdf_files))
                        task_manager.update_task(
                            doc_id,
                            progress_percentage=int(parent_progress),
                            message=f"Processing file {idx}/{len(pdf_files)}: {pdf_path.name}",
                            processed_files=idx - 1
                        )
                        
                        # Process the PDF (use child_doc_id for task_manager, child_doc.id for database)
                        try:
                            process_single_pdf(
                                child_doc_id,  # Use negative ID for task manager
                                pdf_path,
                                metadata,
                                ocr_engine,
                                child_checksum,
                                parent_task_id=doc_id
                            )
                            
                            # Mark child as completed
                            task_manager.complete_task(child_doc_id, success=True)
                            db.update_document_status(child_doc.id, 'completed')  # Database uses positive ID
                            
                        except Exception as e:
                            logger.error("child_pdf_failed", error=str(e), child_id=child_doc_id, pdf=pdf_path.name)
                            task_manager.complete_task(child_doc_id, success=False, error_message=str(e))
                            db.update_document_status(child_doc.id, 'failed', error_message=str(e))
                        
                        # Update parent processed count
                        task_manager.update_task(
                            doc_id,
                            processed_files=idx
                        )
                    
                    # All PDFs processed
                    task_manager.complete_task(doc_id, success=True)
                    db.update_document_status(doc_id, 'completed')
                    logger.info("zip_processing_completed", doc_id=doc_id, total_files=len(pdf_files))
                    return
                    
                except zipfile.BadZipFile:
                    raise ValueError("Invalid or corrupted ZIP file")
            
            elif file_ext != '.pdf':
                raise ValueError(f"Unsupported file type: {file_ext}. Only PDF and ZIP files are supported.")
            
            # Handle single PDF file
            process_single_pdf(doc_id, file_path, metadata, ocr_engine, checksum)
    
        except InterruptedError as e:
            # Task was cancelled by user
            logger.info("task_cancelled", doc_id=doc_id, message=str(e))
            task_manager.complete_task(doc_id, success=False, error_message="Task cancelled by user")
            db.update_document_status(doc_id, 'cancelled', error_message=str(e))
        
        except subprocess.CalledProcessError as e:
            error_msg = f"OCR processing failed: {str(e)}"
            logger.error("adaptive_ocr_failed", error=str(e), doc_id=doc_id)
            task_manager.complete_task(doc_id, success=False, error_message=error_msg)
            db.update_document_status(doc_id, 'failed', error_message=error_msg)
        
        except (RuntimeError, ValueError) as e:
            error_msg = f"Elasticsearch operation failed: {str(e)}"
            logger.error("elasticsearch_operation_failed", error=str(e), 
                        error_type=type(e).__name__, doc_id=doc_id)
            task_manager.complete_task(doc_id, success=False, error_message=error_msg)
            db.update_document_status(doc_id, 'failed', error_message=error_msg)
        
        except Exception as e:
            error_msg = str(e)
            logger.error("background_processing_failed", error=error_msg, doc_id=doc_id)
            task_manager.complete_task(doc_id, success=False, error_message=error_msg)
            db.update_document_status(doc_id, 'failed', error_message=error_msg)
        finally:
            # Clean up temporary extraction directory
            if temp_extract_dir and temp_extract_dir.exists():
                try:
                    shutil.rmtree(temp_extract_dir)
                    logger.info("cleaned_up_temp_extract_dir", dir=str(temp_extract_dir))
                except Exception as e:
                    logger.warning("failed_to_cleanup_temp_dir", error=str(e), dir=str(temp_extract_dir))
            
            # Clean up uploaded file
            if file_path and file_path.exists():
                try:
                    os.remove(file_path)
                    logger.info("cleaned_up_uploaded_file", file=str(file_path))
                except Exception as e:
                    logger.warning("failed_to_cleanup_file", error=str(e), file=str(file_path))


@app.post("/upload")
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
        logger.info("starting_background_processing", doc_id=doc_id, filename=file.filename)
        
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


@app.get("/documents/{doc_id}/progress")
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


@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: int):
    """Delete a specific document by ID (both SQLite and ES)"""
    try:
        # 1. Get document info before deletion
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Cancel any running task for this document
        task_manager.cancel_task(doc_id)
        
        checksum = doc.checksum
        
        # 2. Delete from SQLite
        success = db.delete_document(doc_id)
        if not success:
            raise HTTPException(status_code=404, detail="Failed to delete from database")
        
        # 3. Delete from Elasticsearch by checksum (document_id)
        try:
            es_deleted = pipeline.vector_store.delete_by_metadata({"document_id": checksum})
            logger.info("document_deleted", doc_id=doc_id, checksum=checksum, es_deleted=es_deleted)
        except Exception as es_error:
            logger.warning("es_deletion_failed", error=str(es_error), checksum=checksum)
            # Continue even if ES deletion fails
        
        return JSONResponse(content={
            "status": "success", 
            "message": f"Document {doc_id} deleted",
            "es_deleted_count": es_deleted if 'es_deleted' in locals() else 0
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_document_failed", error=str(e), doc_id=doc_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/documents")
async def delete_all_documents():
    """Delete all documents from both SQLite and Elasticsearch"""
    try:
        # 1. Get all document checksums before deletion
        all_docs = db.list_documents(limit=10000)
        checksums = [doc['checksum'] for doc in all_docs if doc.get('checksum')]
        
        # 2. Delete from SQLite
        db.delete_all_documents()
        
        # 3. Delete from Elasticsearch (all documents)
        es_deleted_total = 0
        for checksum in checksums:
            try:
                count = pipeline.vector_store.delete_by_metadata({"document_id": checksum})
                es_deleted_total += count
            except Exception as es_error:
                logger.warning("es_deletion_failed", error=str(es_error), checksum=checksum)
        
        logger.info("all_documents_deleted", sqlite_count=len(checksums), es_deleted=es_deleted_total)
        
        return JSONResponse(content={
            "status": "success", 
            "message": "All documents deleted",
            "sqlite_deleted": len(checksums),
            "es_deleted": es_deleted_total
        })
    except Exception as e:
        logger.error("delete_all_documents_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks")
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


@app.get("/tasks/{task_id}")
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


@app.post("/tasks/{task_id}/pause")
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


@app.post("/tasks/{task_id}/resume")
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


@app.post("/tasks/{task_id}/cancel")
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


@app.post("/tasks/cleanup")
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

