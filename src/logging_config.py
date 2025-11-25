"""Logging configuration with file output and rotation"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any

import structlog


def filter_vector_fields(logger, method_name, event_dict):
    """
    Structlog processor to filter out or truncate vector/embedding fields
    Prevents large vector arrays from filling up logs
    """
    # Fields to filter or truncate
    vector_field_names = [
        'embedding', 'embeddings', 'vector', 'vectors', 
        'content_vector', 'embedding_vector', 'dense_vector',
        'query_vector', 'document_embedding'
    ]
    
    for key, value in list(event_dict.items()):
        # Check if this is a vector field
        if key in vector_field_names:
            if isinstance(value, (list, tuple)):
                # Replace with metadata about the vector
                if value and isinstance(value[0], (list, tuple)):
                    # List of vectors
                    event_dict[key] = f"<{len(value)} vectors, dim={len(value[0])}>"
                elif value and isinstance(value[0], (int, float)):
                    # Single vector
                    event_dict[key] = f"<vector, dim={len(value)}>"
                else:
                    event_dict[key] = f"<vector data, len={len(value)}>"
        
        # Also check nested dicts
        elif isinstance(value, dict):
            for nested_key in list(value.keys()):
                if nested_key in vector_field_names and isinstance(value[nested_key], (list, tuple)):
                    nested_val = value[nested_key]
                    if nested_val and isinstance(nested_val[0], (list, tuple)):
                        value[nested_key] = f"<{len(nested_val)} vectors, dim={len(nested_val[0])}>"
                    elif nested_val and isinstance(nested_val[0], (int, float)):
                        value[nested_key] = f"<vector, dim={len(nested_val)}>"
                    else:
                        value[nested_key] = f"<vector data, len={len(nested_val)}>"
    
    return event_dict


def truncate_long_strings(logger, method_name, event_dict):
    """
    Truncate very long string values in logs to prevent bloat
    """
    max_string_length = 1000  # 最大字符串长度
    
    for key, value in list(event_dict.items()):
        if isinstance(value, str) and len(value) > max_string_length:
            event_dict[key] = value[:max_string_length] + f"... (truncated, total: {len(value)} chars)"
        elif isinstance(value, (list, tuple)) and len(value) > 100:
            # Truncate large lists (but not vectors - those are handled above)
            if key not in ['embedding', 'embeddings', 'vector', 'vectors']:
                event_dict[key] = f"<list with {len(value)} items>"
    
    return event_dict


def setup_logging(
    log_dir: Optional[str] = None,
    log_level: Optional[str] = None,
    log_config: Optional[Dict[str, Any]] = None
):
    """
    Setup logging with both console and file output
    
    Args:
        log_dir: Directory for log files (overrides config)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR) (overrides config)
        log_config: Full logging configuration dict from config.yaml
    """
    # Use config values if provided, otherwise use defaults
    if log_config is None:
        log_config = {}
    
    # Determine log directory
    if log_dir is None:
        log_dir = log_config.get('file_path', './logs/app.log')
        if '/' in log_dir:
            log_dir = str(Path(log_dir).parent)
        else:
            log_dir = 'logs'
    
    # Determine log level
    if log_level is None:
        log_level = log_config.get('level', 'INFO')
    
    # Convert string level to logging constant
    log_level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    numeric_level = log_level_map.get(log_level.upper(), logging.INFO)
    
    # Create logs directory
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True, parents=True)
    
    # Configure Python's logging
    log_file = log_path / "smartresume.log"
    error_log_file = log_path / "smartresume_errors.log"
    
    # Get rotation config from config.yaml
    max_file_size = log_config.get('max_file_size', 10 * 1024 * 1024)  # 10MB default
    backup_count = log_config.get('backup_count', 5)
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything at root level
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Console handler - respects configured log level
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler - everything (DEBUG and above), JSON format
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_file_size,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    
    # Error file handler - only ERROR and above
    error_handler = RotatingFileHandler(
        error_log_file,
        maxBytes=max_file_size,
        backupCount=max(3, backup_count - 2),  # Fewer backups for errors
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    root_logger.addHandler(error_handler)
    
    # Configure structlog
    log_format = log_config.get('format', 'json')
    
    # Common processors for all formats
    common_processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        # Custom processors to filter vector fields and truncate long strings
        filter_vector_fields,
        truncate_long_strings,
    ]
    
    # Choose final renderer based on format
    if log_format == 'json':
        processors = common_processors + [structlog.processors.JSONRenderer()]
    else:  # text format
        processors = common_processors + [structlog.dev.ConsoleRenderer()]
    
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    logger = structlog.get_logger(__name__)
    logger.info(
        "logging_configured",
        log_dir=str(log_path),
        console_level=log_level,
        file_level="DEBUG",
        format=log_format,
        max_file_size_mb=max_file_size / (1024 * 1024),
        backup_count=backup_count
    )
    
    return logger

