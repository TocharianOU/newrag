"""Document processing handlers"""

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import structlog
from src.task_manager import task_manager, TaskStatus, TaskStage
from src.database import DatabaseManager
from src.pipeline import ProcessingPipeline
from src.config import config

logger = structlog.get_logger(__name__)

# Initialize database and pipeline
db = DatabaseManager()
pipeline = ProcessingPipeline()

# Get upload folder from config
web_config = config.web_config
upload_folder = Path(web_config.get('upload_folder', './uploads'))

# Concurrent processing control (limit to 3 documents processing at the same time)
processing_semaphore = threading.Semaphore(3)


# ============================================================
# 示例函数 - 你可以把其他处理函数复制到这里
# ============================================================

def extract_matched_bboxes_from_file(doc_id: int, checksum: str, page_number: int, query_text: str):
    """
    Extract matched bboxes from OCR JSON file for visualization
    
    示例函数 - 其他处理函数可以复制到这里：
    - process_single_pdf()
    - process_document_background()
    
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
        processed_folder = Path('web/static/processed_docs')
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

def process_document_background(doc_id: int, file_path: Path, metadata: dict, ocr_engine: str, checksum: str):
    """Background task to process document with full control"""
    # Create task in task manager
    task_manager.create_task(doc_id)
    
    logger.info("🚀 process_document_background_called", doc_id=doc_id, filename=file_path.name, ocr_engine=ocr_engine, checksum=checksum[:8])
    
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
            logger.info("background_processing_started", doc_id=doc_id, filename=file_path.name, ocr_engine=ocr_engine)
            
            # Check for cancellation
            if not task_manager.wait_if_paused(doc_id):
                raise InterruptedError("Task was cancelled by user")
            
            # Determine file type and handle accordingly
            file_ext = file_path.suffix.lower()
            logger.info("📄 file_type_detected", doc_id=doc_id, file_ext=file_ext, ocr_engine=ocr_engine)
            
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
                
                # Index to vector store using pipeline (与 PDF/DOCX 保持一致的命名)
                metadata['document_id'] = doc_id
                metadata['filename'] = file_path.name  # 使用原始文件名
                metadata['checksum'] = checksum
                metadata['pages_data'] = pages_data
                metadata['source'] = str(file_path)
                
                pipeline.process_file(
                    file_path=str(file_path),
                    metadata=metadata,
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
                logger.info("🖼️ processing_image_file", doc_id=doc_id, filename=file_path.name, ocr_engine=ocr_engine)
                
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
                logger.info("🔍 running_ocr_extraction", doc_id=doc_id, image=file_path.name, ocr_engine=ocr_engine)
                ocr_json_path = doc_output_dir / "image_ocr.json"
                
                extract_script = Path('document_ocr_pipeline/extract_document.py')
                cmd = [
                    sys.executable,
                    str(extract_script),
                    str(file_path),
                    '--ocr-engine', ocr_engine,
                    '-o', str(ocr_json_path)
                ]
                logger.info("📝 extract_command", doc_id=doc_id, cmd=' '.join(cmd))
                
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                logger.info("✅ ocr_extraction_stdout", doc_id=doc_id, stdout=result.stdout[:500] if result.stdout else "")
                if result.stderr:
                    logger.warning("⚠️ ocr_extraction_stderr", doc_id=doc_id, stderr=result.stderr[:500])
                
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
                logger.info("📖 reading_ocr_results", doc_id=doc_id, json_path=str(ocr_json_path))
                with open(ocr_json_path, 'r', encoding='utf-8') as f:
                    ocr_data = json.load(f)
                
                # 提取文本内容
                text_content = ocr_data.get('text', '')
                text_blocks_count = len(ocr_data.get('text_blocks', []))
                logger.info("📝 ocr_results_loaded", doc_id=doc_id, text_length=len(text_content), text_blocks=text_blocks_count, ocr_engine=ocr_engine)
                
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
                logger.info("📋 pages_data_built", doc_id=doc_id, pages_count=len(pages_data))
                
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
                
                logger.info("🔄 starting_pipeline_indexing", doc_id=doc_id, metadata=metadata)
                
                # 使用 pipeline 索引（会读取 complete_document.json）
                result = pipeline.process_file(str(file_path), metadata, processed_json_dir=str(doc_output_dir))
                
                logger.info("✅ pipeline_result", doc_id=doc_id, status=result.get('status'), num_chunks=result.get('num_chunks', 0), document_ids=result.get('document_ids'))
                
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
                        logger.error("❌ no_documents_indexed", doc_id=doc_id)
                        task_manager.complete_task(doc_id, success=False, error_message=error_msg)
                        db.update_document_status(doc_id, 'failed', error_message=error_msg)
                    else:
                        logger.info("🎉 marking_as_completed", doc_id=doc_id, num_chunks=result.get('num_chunks', 0))
                        task_manager.complete_task(doc_id, success=True)
                        db.update_document_status(
                            doc_id,
                            'completed',
                            num_chunks=result.get('num_chunks', 0),
                            pages_data=json.dumps(pages_data)
                        )
                        logger.info("✅ image_processing_completed", doc_id=doc_id, num_chunks=result.get('num_chunks', 0))
                else:
                    error_msg = result.get('error', 'Unknown error during image processing')
                    logger.error("❌ pipeline_failed", doc_id=doc_id, error=error_msg)
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
            logger.error("❌ subprocess_failed", error=str(e), returncode=e.returncode, 
                        cmd=' '.join(e.cmd) if hasattr(e, 'cmd') else 'unknown',
                        stdout=e.stdout[:500] if hasattr(e, 'stdout') and e.stdout else '',
                        stderr=e.stderr[:500] if hasattr(e, 'stderr') and e.stderr else '',
                        doc_id=doc_id, ocr_engine=ocr_engine)
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


# ============================================================
# TODO: 把以下函数从 app.py 复制到这里
# ============================================================
# - process_single_pdf()
# - process_document_background()
#
# 注意：这两个函数很大，需要仔细复制全部代码

