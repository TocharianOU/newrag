"""
Task Manager for Async Document Processing
Provides full control over background tasks including pause, resume, cancel
"""
import threading
import time
from typing import Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class TaskStatus(Enum):
    """Task status enumeration"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStage(Enum):
    """Task processing stages"""
    INITIALIZING = "initializing"
    EXTRACTING_ZIP = "extracting_zip"
    OCR_PROCESSING = "ocr_processing"
    VLM_EXTRACTION = "vlm_extraction"
    INDEXING = "indexing"
    FINALIZING = "finalizing"


@dataclass
class TaskProgress:
    """Detailed task progress information"""
    status: TaskStatus = TaskStatus.PENDING
    stage: TaskStage = TaskStage.INITIALIZING
    progress_percentage: int = 0
    message: str = ""
    
    # Page processing details
    total_pages: int = 0
    processed_pages: int = 0
    current_page: int = 0
    
    # Parent-child relationship for ZIP files
    parent_task_id: Optional[int] = None  # Parent task ID (for sub-tasks)
    child_task_ids: list = field(default_factory=list)  # Child task IDs (for ZIP files)
    is_zip_parent: bool = False  # True if this is a ZIP container task
    filename: str = ""  # Original filename
    total_files: int = 0  # Total files in ZIP (for parent tasks)
    processed_files: int = 0  # Processed files in ZIP (for parent tasks)
    
    # Stage timings
    stage_start_time: Optional[datetime] = None
    stage_end_time: Optional[datetime] = None
    
    # Detailed stage info
    stage_details: Dict[str, Any] = field(default_factory=dict)
    
    # Error info
    error_message: Optional[str] = None
    error_details: Optional[str] = None
    
    # Control flags (for internal use)
    _pause_requested: bool = False
    _cancel_requested: bool = False
    _resume_event: threading.Event = field(default_factory=threading.Event)
    
    def __post_init__(self):
        """Initialize resume event"""
        if not isinstance(self._resume_event, threading.Event):
            self._resume_event = threading.Event()
        # Start as resumed
        self._resume_event.set()
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "status": self.status.value,
            "stage": self.stage.value,
            "progress_percentage": self.progress_percentage,
            "message": self.message,
            "total_pages": self.total_pages,
            "processed_pages": self.processed_pages,
            "current_page": self.current_page,
            "stage_details": self.stage_details,
            "error_message": self.error_message,
            "error_details": self.error_details,
            "stage_start_time": self.stage_start_time.isoformat() if self.stage_start_time else None,
            "stage_end_time": self.stage_end_time.isoformat() if self.stage_end_time else None,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": self.child_task_ids,
            "is_zip_parent": self.is_zip_parent,
            "filename": self.filename,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
        }


class TaskManager:
    """
    Centralized task manager for document processing
    Provides full control over async tasks
    """
    
    def __init__(self):
        self._tasks: Dict[int, TaskProgress] = {}
        self._threads: Dict[int, threading.Thread] = {}
        self._lock = threading.Lock()
        logger.info("task_manager_initialized")
    
    def create_task(self, task_id: int) -> TaskProgress:
        """Create a new task with initial progress"""
        with self._lock:
            progress = TaskProgress(
                status=TaskStatus.PENDING,
                stage=TaskStage.INITIALIZING,
                message="Task created, waiting to start..."
            )
            self._tasks[task_id] = progress
            logger.info("task_created", task_id=task_id)
            return progress
    
    def get_task(self, task_id: int) -> Optional[TaskProgress]:
        """Get task progress by ID"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def update_task(
        self, 
        task_id: int, 
        status: Optional[TaskStatus] = None,
        stage: Optional[TaskStage] = None,
        progress_percentage: Optional[int] = None,
        message: Optional[str] = None,
        total_pages: Optional[int] = None,
        processed_pages: Optional[int] = None,
        current_page: Optional[int] = None,
        stage_details: Optional[dict] = None,
        error_message: Optional[str] = None,
        filename: Optional[str] = None,
        total_files: Optional[int] = None,
        processed_files: Optional[int] = None,
        is_zip_parent: Optional[bool] = None
    ):
        """Update task progress"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning("task_not_found", task_id=task_id)
                return
            
            # Update stage timing
            if stage and stage != task.stage:
                task.stage_end_time = datetime.now()
                task.stage = stage
                task.stage_start_time = datetime.now()
            
            if status is not None:
                task.status = status
            if progress_percentage is not None:
                task.progress_percentage = progress_percentage
            if message is not None:
                task.message = message
            if total_pages is not None:
                task.total_pages = total_pages
            if processed_pages is not None:
                task.processed_pages = processed_pages
            if current_page is not None:
                task.current_page = current_page
            if stage_details is not None:
                task.stage_details.update(stage_details)
            if error_message is not None:
                task.error_message = error_message
            if filename is not None:
                task.filename = filename
            if total_files is not None:
                task.total_files = total_files
            if processed_files is not None:
                task.processed_files = processed_files
            if is_zip_parent is not None:
                task.is_zip_parent = is_zip_parent
            
            logger.debug("task_updated", task_id=task_id, 
                        status=task.status.value, 
                        stage=task.stage.value,
                        progress=task.progress_percentage)
    
    def check_control_flags(self, task_id: int) -> tuple[bool, bool]:
        """
        Check if task should pause or cancel
        Returns: (should_pause, should_cancel)
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False, False
            
            should_cancel = task._cancel_requested
            should_pause = task._pause_requested and not should_cancel
            
            return should_pause, should_cancel
    
    def wait_if_paused(self, task_id: int, check_interval: float = 0.5) -> bool:
        """
        Wait if task is paused. Returns False if cancelled.
        This should be called periodically in the task execution loop.
        """
        task = self.get_task(task_id)
        if not task:
            return False
        
        # Check if cancelled
        if task._cancel_requested:
            return False
        
        # Wait for resume event if paused
        if task._pause_requested:
            # Update status to paused
            self.update_task(task_id, status=TaskStatus.PAUSED)
            logger.info("task_paused", task_id=task_id)
            
            # Wait for resume or cancel
            while task._pause_requested and not task._cancel_requested:
                time.sleep(check_interval)
                task = self.get_task(task_id)
                if not task:
                    return False
            
            # Check if cancelled during pause
            if task._cancel_requested:
                return False
            
            # Resume
            self.update_task(task_id, status=TaskStatus.RUNNING)
            logger.info("task_resumed", task_id=task_id)
        
        return True
    
    def pause_task(self, task_id: int) -> bool:
        """Request task to pause"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning("task_not_found", task_id=task_id)
                return False
            
            if task.status not in [TaskStatus.RUNNING, TaskStatus.PENDING]:
                logger.warning("task_cannot_pause", task_id=task_id, status=task.status.value)
                return False
            
            task._pause_requested = True
            task._resume_event.clear()
            logger.info("task_pause_requested", task_id=task_id)
            return True
    
    def resume_task(self, task_id: int) -> bool:
        """Resume a paused task"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning("task_not_found", task_id=task_id)
                return False
            
            if task.status != TaskStatus.PAUSED and not task._pause_requested:
                logger.warning("task_not_paused", task_id=task_id, status=task.status.value)
                return False
            
            task._pause_requested = False
            task._resume_event.set()
            task.status = TaskStatus.RUNNING
            logger.info("task_resumed", task_id=task_id)
            return True
    
    def cancel_task(self, task_id: int) -> bool:
        """Request task to cancel"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning("task_not_found", task_id=task_id)
                return False
            
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                logger.warning("task_already_finished", task_id=task_id, status=task.status.value)
                return False
            
            task._cancel_requested = True
            task._resume_event.set()  # Wake up if paused
            task.status = TaskStatus.CANCELLED
            task.message = "Cancellation requested..."
            logger.info("task_cancel_requested", task_id=task_id)
            return True
    
    def complete_task(self, task_id: int, success: bool = True, error_message: Optional[str] = None):
        """Mark task as completed or failed"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            
            if success:
                task.status = TaskStatus.COMPLETED
                task.progress_percentage = 100
                task.message = "Task completed successfully"
            else:
                task.status = TaskStatus.FAILED
                task.error_message = error_message or "Task failed"
                task.message = task.error_message
            
            task.stage_end_time = datetime.now()
            logger.info("task_finished", task_id=task_id, 
                       status=task.status.value,
                       error=error_message if not success else None)
    
    def register_thread(self, task_id: int, thread: threading.Thread):
        """Register thread for task tracking"""
        with self._lock:
            self._threads[task_id] = thread
    
    def add_child_task(self, parent_id: int, child_id: int):
        """Add a child task to parent task"""
        with self._lock:
            parent = self._tasks.get(parent_id)
            child = self._tasks.get(child_id)
            
            if parent and child:
                if child_id not in parent.child_task_ids:
                    parent.child_task_ids.append(child_id)
                child.parent_task_id = parent_id
                logger.info("child_task_added", parent_id=parent_id, child_id=child_id)
    
    def get_task_with_children(self, task_id: int) -> Optional[dict]:
        """Get task with all its children"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            
            result = task.to_dict()
            result['task_id'] = task_id
            
            # Add children if any
            if task.child_task_ids:
                result['children'] = []
                for child_id in task.child_task_ids:
                    child_task = self._tasks.get(child_id)
                    if child_task:
                        child_dict = child_task.to_dict()
                        child_dict['task_id'] = child_id
                        result['children'].append(child_dict)
            
            return result
    
    def list_tasks(self, status_filter: Optional[TaskStatus] = None) -> Dict[int, dict]:
        """List all tasks with optional status filter"""
        with self._lock:
            if status_filter:
                return {
                    task_id: task.to_dict() 
                    for task_id, task in self._tasks.items() 
                    if task.status == status_filter
                }
            return {task_id: task.to_dict() for task_id, task in self._tasks.items()}
    
    def cleanup_finished_tasks(self, keep_recent: int = 10):
        """Clean up old completed/failed tasks, keep only recent ones"""
        with self._lock:
            finished_tasks = [
                (task_id, task) 
                for task_id, task in self._tasks.items() 
                if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
            ]
            
            if len(finished_tasks) > keep_recent:
                # Sort by task_id (older tasks have smaller IDs)
                finished_tasks.sort(key=lambda x: x[0])
                
                # Remove oldest tasks
                for task_id, _ in finished_tasks[:-keep_recent]:
                    del self._tasks[task_id]
                    if task_id in self._threads:
                        del self._threads[task_id]
                    logger.info("task_cleaned_up", task_id=task_id)


# Global task manager instance
task_manager = TaskManager()

