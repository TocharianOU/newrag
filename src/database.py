"""SQLite database for document tracking"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

Base = declarative_base()


class Document(Base):
    """Document model for tracking uploaded documents"""
    __tablename__ = 'documents'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000))
    file_type = Column(String(50))
    file_size = Column(Integer)
    checksum = Column(String(64), unique=True)
    
    # Metadata
    category = Column(String(100))
    tags = Column(Text)  # Comma-separated
    author = Column(String(200))
    description = Column(Text)
    
    # Processing status
    status = Column(String(50), default='pending')  # pending, processing, completed, failed
    num_chunks = Column(Integer, default=0)
    error_message = Column(Text)
    
    # Progress tracking
    progress_percentage = Column(Integer, default=0)  # 0-100
    progress_message = Column(String(500))  # Current step description
    total_pages = Column(Integer, default=0)
    processed_pages = Column(Integer, default=0)
    
    # ES info
    es_document_ids = Column(Text)  # JSON string of document IDs
    
    # OCR Processing info
    ocr_engine = Column(String(20))  # easy, paddle, vision
    pages_data = Column(Text)  # JSON string of pages info (image paths, ocr data, etc.)
    
    # Timestamps
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)
    
    def to_dict(self):
        """Convert to dictionary"""
        import json
        return {
            'id': self.id,
            'filename': self.filename,
            'file_type': self.file_type,
            'file_size': self.file_size,
            'category': self.category,
            'tags': self.tags.split(',') if self.tags else [],
            'author': self.author,
            'status': self.status,
            'num_chunks': self.num_chunks,
            'error_message': self.error_message,
            'ocr_engine': self.ocr_engine,
            'pages_data': json.loads(self.pages_data) if self.pages_data else None,
            # Frontend expects created_at and updated_at
            'created_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'updated_at': self.processed_at.isoformat() if self.processed_at else None,
            'progress_percentage': self.progress_percentage or 0,
            'progress_message': self.progress_message or '',
            'total_pages': self.total_pages or 0,
            'processed_pages': self.processed_pages or 0
        }


class DatabaseManager:
    """Database manager for SQLite"""
    
    def __init__(self, db_path: str = "data/documents.db"):
        """Initialize database"""
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.engine = create_engine(f'sqlite:///{db_path}')
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def get_session(self) -> Session:
        """Get database session"""
        return self.SessionLocal()
    
    def create_document(
        self,
        filename: str,
        file_path: str,
        file_type: str,
        file_size: int,
        checksum: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        author: Optional[str] = None,
        description: Optional[str] = None,
        ocr_engine: Optional[str] = None
    ) -> Document:
        """Create new document record"""
        session = self.get_session()
        try:
            doc = Document(
                filename=filename,
                file_path=file_path,
                file_type=file_type,
                file_size=file_size,
                checksum=checksum,
                category=category,
                tags=','.join(tags) if tags else '',
                author=author,
                description=description,
                ocr_engine=ocr_engine,
                status='pending'
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
            return doc
        finally:
            session.close()
    
    def update_document_status(
        self,
        doc_id: int,
        status: str,
        num_chunks: Optional[int] = None,
        es_document_ids: Optional[str] = None,
        error_message: Optional[str] = None,
        pages_data: Optional[str] = None
    ):
        """Update document processing status"""
        session = self.get_session()
        try:
            doc = session.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = status
                if num_chunks is not None:
                    doc.num_chunks = num_chunks
                if es_document_ids:
                    doc.es_document_ids = es_document_ids
                if error_message:
                    doc.error_message = error_message
                if pages_data:
                    doc.pages_data = pages_data
                if status == 'completed':
                    doc.processed_at = datetime.utcnow()
                    doc.progress_percentage = 100
                session.commit()
        finally:
            session.close()
    
    def update_document_progress(
        self,
        doc_id: int,
        progress_percentage: int,
        progress_message: str,
        processed_pages: Optional[int] = None,
        total_pages: Optional[int] = None
    ):
        """Update document processing progress"""
        session = self.get_session()
        try:
            doc = session.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.progress_percentage = min(100, max(0, progress_percentage))
                doc.progress_message = progress_message
                if processed_pages is not None:
                    doc.processed_pages = processed_pages
                if total_pages is not None:
                    doc.total_pages = total_pages
                session.commit()
        finally:
            session.close()
    
    def update_document_pages_data(self, doc_id: int, pages_data: list):
        """Update document pages_data field and total_pages count"""
        import json
        session = self.get_session()
        try:
            doc = session.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.pages_data = json.dumps(pages_data)
                doc.total_pages = len(pages_data)  # 🔥 同时更新页数
                session.commit()
        finally:
            session.close()
    
    def get_document(self, doc_id: int) -> Optional[Document]:
        """Get document by ID"""
        session = self.get_session()
        try:
            return session.query(Document).filter(Document.id == doc_id).first()
        finally:
            session.close()
    
    def get_document_by_checksum(self, checksum: str) -> Optional[Document]:
        """Get document by checksum"""
        session = self.get_session()
        try:
            return session.query(Document).filter(Document.checksum == checksum).first()
        finally:
            session.close()
    
    def list_documents(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None
    ) -> List[Document]:
        """List documents"""
        session = self.get_session()
        try:
            query = session.query(Document)
            if status:
                query = query.filter(Document.status == status)
            return query.order_by(Document.uploaded_at.desc()).limit(limit).offset(offset).all()
        finally:
            session.close()
    
    def delete_document(self, doc_id: int) -> bool:
        """Delete document by ID"""
        session = self.get_session()
        try:
            doc = session.query(Document).filter(Document.id == doc_id).first()
            if doc:
                session.delete(doc)
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    def delete_all_documents(self):
        """Delete all documents"""
        session = self.get_session()
        try:
            session.query(Document).delete()
            session.commit()
        finally:
            session.close()
    
    def get_stats(self):
        """Get database statistics"""
        session = self.get_session()
        try:
            total = session.query(Document).count()
            completed = session.query(Document).filter(Document.status == 'completed').count()
            failed = session.query(Document).filter(Document.status == 'failed').count()
            processing = session.query(Document).filter(Document.status == 'processing').count()
            
            return {
                'total': total,
                'completed': completed,
                'failed': failed,
                'processing': processing
            }
        finally:
            session.close()

