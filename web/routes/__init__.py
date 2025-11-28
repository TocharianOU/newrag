"""Routes package for FastAPI application"""

from .document_routes import router as document_router
from .cleanup_routes import router as cleanup_router

__all__ = ['document_router', 'cleanup_router']


