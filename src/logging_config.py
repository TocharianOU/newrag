"""Logging configuration with file output and rotation"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

import structlog


def setup_logging(log_dir: str = "logs", log_level: str = "INFO"):
    """
    Setup logging with both console and file output
    
    Args:
        log_dir: Directory for log files
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    # Create logs directory
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    # Configure Python's logging
    log_file = log_path / "smartresume.log"
    error_log_file = log_path / "smartresume_errors.log"
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Console handler - only INFO and above, simple format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler - everything, JSON format, 10MB rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    
    # Error file handler - only ERROR and above, JSON format
    error_handler = RotatingFileHandler(
        error_log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    root_logger.addHandler(error_handler)
    
    # Configure structlog
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
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    logger = structlog.get_logger(__name__)
    logger.info("logging_configured", log_dir=str(log_path), console_level="INFO", file_level="DEBUG")
    
    return logger

