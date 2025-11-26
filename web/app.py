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
            
            elif file_ext == '.pdf':
                # Handle single PDF file
                process_single_pdf(doc_id, file_path, metadata, ocr_engine, checksum)
            
            elif file_ext == '.pptx':
                # Handle PPTX files - use process_pptx.py
                logger.info("processing_pptx_file", doc_id=doc_id, filename=file_path.name)
                
                task_manager.update_task(
                    doc_id,
                    status=TaskStatus.RUNNING,
                    stage=TaskStage.OCR_PROCESSING,
                    progress_percentage=10,
                    message=f"Processing PPTX: {file_path.name}...",
                    filename=file_path.name
                )
                db.update_document_progress(doc_id, 10, f"Starting PPTX processing for {file_path.name}...")
                
                # Check for cancellation
                if not task_manager.wait_if_paused(doc_id):
                    raise InterruptedError("Task was cancelled by user")
                
                # Create output directory for this document
                processed_folder = Path('web/static/processed_docs')
                doc_output_dir = processed_folder / f"{doc_id}_{checksum[:8]}"
                doc_output_dir.mkdir(parents=True, exist_ok=True)
                
                # Run process_pptx.py to extract text and images
                db.update_document_progress(doc_id, 20, "Extracting PPTX content...")
                
                pptx_script = Path('document_ocr_pipeline/process_pptx.py')
                result = subprocess.run([
                    sys.executable,
                    str(pptx_script),
                    str(file_path),
                    '-o', str(doc_output_dir),
                    '--ocr-engine', ocr_engine
                ], capture_output=True, text=True)
                
                if result.returncode != 0:
                    logger.error("pptx_processing_failed", error=result.stderr, doc_id=doc_id)
                    raise ValueError(f"PPTX processing failed: {result.stderr}")
                
                logger.info("pptx_extraction_completed", doc_id=doc_id)
                
                # Check for cancellation
                if not task_manager.wait_if_paused(doc_id):
                    raise InterruptedError("Task was cancelled by user")
                
                # Load the generated complete_adaptive_ocr.json
                complete_json_path = doc_output_dir / "complete_adaptive_ocr.json"
                if not complete_json_path.exists():
                    raise ValueError("PPTX processing did not generate complete_adaptive_ocr.json")
                
                with open(complete_json_path, 'r', encoding='utf-8') as f:
                    complete_data = json.load(f)
                
                # Build pages_data for database (similar to PDF processing)
                pages_data = []
                for page in complete_data.get('pages', []):
                    page_num = page['page_number']
                    stage1 = page.get('stage1_global', {})
                    stage2 = page.get('stage2_ocr', {})
                    stage3 = page.get('stage3_vlm', {})
                    
                    # Extract image filename from stage1
                    image_filename = stage1.get('image', f'page_{page_num:03d}_preview.png')
                    
                    # Build page data structure (使用 page_num 字段名与 PDF 保持一致)
                    page_data = {
                        'page_num': page_num,
                        'image_path': f"/static/processed_docs/{doc_id}_{checksum[:8]}/{image_filename}",
                        'visualized_path': f"/static/processed_docs/{doc_id}_{checksum[:8]}/page_{page_num:03d}_visualized.png",
                        'text_count': len(stage3.get('text_combined', '').split()),
                        'components': []  # PPTX 暂无组件提取
                    }
                    pages_data.append(page_data)
                
                # Update database with pages_data
                db.update_document_pages_data(doc_id, pages_data)
                logger.info("pptx_pages_data_saved", doc_id=doc_id, total_pages=len(pages_data))
                
                # Check for cancellation
                if not task_manager.wait_if_paused(doc_id):
                    raise InterruptedError("Task was cancelled by user")
                
                # Update progress
                db.update_document_progress(doc_id, 60, "Indexing to vector store...")
                task_manager.update_task(
                    doc_id,
                    stage=TaskStage.INDEXING,
                    progress_percentage=60,
                    message="Indexing to vector store..."
                )
                
                # Index to vector store using pipeline
                additional_metadata = {
                    'document_id': str(doc_id),
                    'checksum': checksum,
                    'pages_data': pages_data,
                    'source': str(file_path)
                }
                additional_metadata.update(metadata)
                
                pipeline.process_file(
                    file_path=str(file_path),
                    metadata=additional_metadata,
                    processed_json_dir=str(doc_output_dir)
                )
                
                logger.info("pptx_indexed", doc_id=doc_id)
                
                # Mark as completed
                db.update_document_status(doc_id, 'completed')
                db.update_document_progress(doc_id, 100, "Completed")
                task_manager.complete_task(doc_id, success=True)
                
                logger.info("pptx_processing_completed", doc_id=doc_id, filename=file_path.name)
            
            elif file_ext in ['.jpg', '.jpeg', '.png']:
                # Handle image files - use OCR pipeline (same as PDF but without page conversion)
                logger.info("processing_image_file", doc_id=doc_id, filename=file_path.name)
                
                task_manager.update_task(
                    doc_id,
                    status=TaskStatus.RUNNING,
                    stage=TaskStage.OCR_PROCESSING,
                    progress_percentage=10,
                    message=f"Running OCR on {file_path.name}...",
                    filename=file_path.name
                )
                db.update_document_progress(doc_id, 10, f"Starting OCR for {file_path.name}...")
                
                # Check for cancellation
                if not task_manager.wait_if_paused(doc_id):
                    raise InterruptedError("Task was cancelled by user")
                
                # Run OCR extraction directly on image (使用 extract_document.py)
                # 创建输出目录
                processed_folder = Path('web/static/processed_docs')
                doc_output_dir = processed_folder / f"{doc_id}_{checksum[:8]}"
                doc_output_dir.mkdir(parents=True, exist_ok=True)
                
                # 运行 extract_document.py 提取文本
                logger.info("running_ocr_extraction", doc_id=doc_id, image=file_path.name)
                ocr_json_path = doc_output_dir / "image_ocr.json"
                
                extract_script = Path('document_ocr_pipeline/extract_document.py')
                subprocess.run([
                    sys.executable,
                    str(extract_script),
                    str(file_path),
                    '--ocr-engine', ocr_engine,
                    '-o', str(ocr_json_path)
                ], check=True)
                
                logger.info("ocr_extraction_completed", doc_id=doc_id)
                
                # 生成可视化图片
                task_manager.update_task(
                    doc_id,
                    progress_percentage=40,
                    message="Creating visualization..."
                )
                db.update_document_progress(doc_id, 40, "Creating visualization...")
                
                visualize_script = Path('document_ocr_pipeline/visualize_extraction.py')
                vis_output_path = doc_output_dir / "image_visualized.png"
                subprocess.run([
                    sys.executable,
                    str(visualize_script),
                    str(file_path),
                    str(ocr_json_path),
                    '-o', str(vis_output_path)
                ], check=True)
                
                # 复制原始图片作为预览
                import shutil
                preview_path = doc_output_dir / "image_preview.png"
                shutil.copy(file_path, preview_path)
                
                # Check for cancellation
                if not task_manager.wait_if_paused(doc_id):
                    raise InterruptedError("Task was cancelled by user")
                
                # 更新进度：构建 pages_data
                task_manager.update_task(
                    doc_id,
                    stage=TaskStage.VLM_EXTRACTION,
                    progress_percentage=60,
                    message="Building searchable content...",
                    total_pages=1,
                    processed_pages=0
                )
                db.update_document_progress(doc_id, 60, "Building searchable content...", processed_pages=0, total_pages=1)
                
                # 读取 OCR 结果并构建 pages_data
                with open(ocr_json_path, 'r', encoding='utf-8') as f:
                    ocr_data = json.load(f)
                
                # 提取文本内容
                text_content = ocr_data.get('text', '')
                
                # 构建 pages_data（模拟 PDF 的单页结构）
                pages_data = [{
                    'page_number': 1,
                    'image_path': f"/static/processed_docs/{doc_id}_{checksum[:8]}/image_preview.png",
                    'visualized_path': f"/static/processed_docs/{doc_id}_{checksum[:8]}/image_visualized.png",
                    'ocr_json_path': str(ocr_json_path),
                    'text': text_content,
                    'text_blocks': ocr_data.get('text_blocks', []),
                    'extraction_method': 'ocr',
                    'ocr_engine': ocr_engine
                }]
                
                # 保存 pages_data
                pages_data_json = doc_output_dir / "complete_document.json"
                with open(pages_data_json, 'w', encoding='utf-8') as f:
                    json.dump({'pages': pages_data}, f, ensure_ascii=False, indent=2)
                
                task_manager.update_task(
                    doc_id,
                    processed_pages=1
                )
                db.update_document_progress(doc_id, 70, "Processing completed", processed_pages=1, total_pages=1)
                
                # Check for cancellation before indexing
                if not task_manager.wait_if_paused(doc_id):
                    raise InterruptedError("Task was cancelled by user")
                
                # 更新进度：索引到 Elasticsearch
                task_manager.update_task(
                    doc_id,
                    stage=TaskStage.INDEXING,
                    progress_percentage=80,
                    message="Indexing to Elasticsearch..."
                )
                db.update_document_progress(doc_id, 80, "Indexing to Elasticsearch...")
                
                # 添加文档标识到 metadata
                metadata['document_id'] = doc_id
                metadata['filename'] = file_path.name
                metadata['checksum'] = checksum
                
                # 使用 pipeline 索引（会读取 complete_document.json）
                result = pipeline.process_file(str(file_path), metadata, processed_json_dir=str(doc_output_dir))
                
                # Check for cancellation after indexing
                if not task_manager.wait_if_paused(doc_id):
                    raise InterruptedError("Task was cancelled by user")
                
                # 更新进度：完成
                task_manager.update_task(
                    doc_id,
                    stage=TaskStage.FINALIZING,
                    progress_percentage=95,
                    message="Finalizing..."
                )
                db.update_document_progress(doc_id, 95, "Finalizing...")
                
                # 更新数据库
                if result.get('status') == 'completed':
                    if not result.get('document_ids'):
                        error_msg = 'Image processing completed but no documents were indexed'
                        logger.error("no_documents_indexed", doc_id=doc_id)
                        task_manager.complete_task(doc_id, success=False, error_message=error_msg)
                        db.update_document_status(doc_id, 'failed', error_message=error_msg)
                    else:
                        task_manager.complete_task(doc_id, success=True)
                        db.update_document_status(
                            doc_id,
                            'completed',
                            num_chunks=result.get('num_chunks', 0),
                            pages_data=json.dumps(pages_data)
                        )
                        logger.info("image_processing_completed", doc_id=doc_id, num_chunks=result.get('num_chunks', 0))
                else:
                    error_msg = result.get('error', 'Unknown error during image processing')
                    task_manager.complete_task(doc_id, success=False, error_message=error_msg)
                    db.update_document_status(doc_id, 'failed', error_message=error_msg)
            
            else:
                raise ValueError(f"Unsupported file type: {file_ext}. Supported: PDF, ZIP, JPG, JPEG, PNG")
        
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


@app.get("/orphan-check")
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


@app.delete("/orphan-cleanup")
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


@app.post("/es-index/delete")
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


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


def check_required_services():
    """检查必需的服务（MinIO、Elasticsearch）是否可用"""
    import requests
    issues = []
    
    # 检查 MinIO
    if config.get('minio.enabled', False):
        minio_endpoint = config.get('minio.endpoint', 'localhost:9000')
        minio_url = f"http://{minio_endpoint}/minio/health/live"
        try:
            response = requests.get(minio_url, timeout=3)
            if response.status_code == 200:
                logger.info("✅ MinIO 连接正常", endpoint=minio_endpoint)
            else:
                issues.append(f"❌ MinIO 健康检查失败: HTTP {response.status_code}")
                issues.append(f"   端点: {minio_endpoint}")
        except requests.exceptions.ConnectionError:
            issues.append("❌ MinIO 未运行")
            issues.append(f"   请确保 MinIO 服务运行在: {minio_endpoint}")
            issues.append("   启动命令: ./start_minio.sh")
        except Exception as e:
            issues.append(f"❌ MinIO 连接失败: {str(e)}")
            issues.append(f"   端点: {minio_endpoint}")
    else:
        logger.warning("⚠️  MinIO 已禁用（minio.enabled=false），文件不会上传到对象存储")
    
    # 检查 Elasticsearch
    es_url = config.get('elasticsearch.url', 'http://localhost:9200')
    try:
        response = requests.get(f"{es_url}/_cluster/health", timeout=3)
        if response.status_code == 200:
            health_data = response.json()
            status = health_data.get('status', 'unknown')
            if status in ['green', 'yellow']:
                logger.info("✅ Elasticsearch 连接正常", status=status, url=es_url)
            else:
                issues.append(f"⚠️  Elasticsearch 状态异常: {status}")
        else:
            issues.append(f"❌ Elasticsearch 健康检查失败: HTTP {response.status_code}")
    except requests.exceptions.ConnectionError:
        issues.append("❌ Elasticsearch 未运行")
        issues.append(f"   URL: {es_url}")
        issues.append("   请确保 Elasticsearch 正在运行")
    except Exception as e:
        issues.append(f"❌ Elasticsearch 连接失败: {str(e)}")
        issues.append(f"   URL: {es_url}")
    
    return issues


if __name__ == "__main__":
    import uvicorn
    import sys
    
    # 检查必需服务
    logger.info("🔍 检查必需服务...")
    service_issues = check_required_services()
    
    if service_issues:
        logger.error("服务检查失败，无法启动应用")
        print("\n" + "="*70)
        print("⚠️  启动前检查失败")
        print("="*70)
        for issue in service_issues:
            print(issue)
        print("="*70)
        print("\n请先解决以上问题后再启动应用。\n")
        sys.exit(1)
    
    logger.info("✅ 所有必需服务检查通过")
    
    host = web_config.get('host', '0.0.0.0')
    port = web_config.get('port', 8000)
    
    logger.info("starting_web_server", host=host, port=port)
    print(f"\n🚀 服务启动成功！访问: http://localhost:{port}\n")
    
    uvicorn.run(app, host=host, port=port)

