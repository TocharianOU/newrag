"""SQLite database for document tracking and authentication"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import threading
import json

from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship, joinedload

Base = declarative_base()


# Association tables for many-to-many relationships
user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True)
)

role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)


class Organization(Base):
    """Organization/Tenant model for multi-tenancy support"""
    __tablename__ = 'organizations'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    users = relationship('User', back_populates='organization', cascade='all, delete-orphan')
    documents = relationship('Document', back_populates='organization')


class User(Base):
    """User model for authentication"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    
    # Organization relationship
    org_id = Column(Integer, ForeignKey('organizations.id', ondelete='SET NULL'))
    organization = relationship('Organization', back_populates='users')
    
    # User status
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    
    # Relationships
    roles = relationship('Role', secondary=user_roles, back_populates='users')
    documents = relationship('Document', back_populates='owner')
    mcp_tokens = relationship('McpToken', back_populates='user', cascade='all, delete-orphan')
    refresh_tokens = relationship('RefreshToken', back_populates='user', cascade='all, delete-orphan')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'org_id': self.org_id,
            'is_active': self.is_active,
            'is_superuser': self.is_superuser,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'roles': [{'id': role.id, 'code': role.code, 'name': role.name} for role in self.roles]
        }


class Role(Base):
    """Role model for RBAC"""
    __tablename__ = 'roles'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text)
    
    # System role or organization-specific
    org_id = Column(Integer, ForeignKey('organizations.id', ondelete='CASCADE'))
    is_system = Column(Boolean, default=False)  # System roles apply globally
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    users = relationship('User', secondary=user_roles, back_populates='roles')
    permissions = relationship('Permission', secondary=role_permissions, back_populates='roles')


class Permission(Base):
    """Permission model for RBAC"""
    __tablename__ = 'permissions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False, index=True)  # e.g., "document:write"
    resource = Column(String(50), nullable=False)  # e.g., "document"
    action = Column(String(50), nullable=False)  # e.g., "write"
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    roles = relationship('Role', secondary=role_permissions, back_populates='permissions')


class McpToken(Base):
    """MCP long-lived token model"""
    __tablename__ = 'mcp_tokens'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    token_id = Column(String(100), unique=True, nullable=False, index=True)  # UUID
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(200), nullable=False)  # e.g., "Cursor Desktop"
    
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship('User', back_populates='mcp_tokens')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'token_id': self.token_id,
            'name': self.name,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_active': self.is_active,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class RefreshToken(Base):
    """Refresh token model for JWT authentication"""
    __tablename__ = 'refresh_tokens'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    token_id = Column(String(100), unique=True, nullable=False, index=True)  # UUID
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship('User', back_populates='refresh_tokens')


class Document(Base):
    """Document model for tracking uploaded documents"""
    __tablename__ = 'documents'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000))
    file_type = Column(String(50))
    file_size = Column(Integer)
    checksum = Column(String(64), unique=True)
    
    # Ownership and permissions
    owner_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    org_id = Column(Integer, ForeignKey('organizations.id', ondelete='SET NULL'))
    visibility = Column(String(20), default='private')  # private, org, public
    shared_with_users = Column(Text, default='[]')  # JSON array: [1, 2, 3]
    shared_with_roles = Column(Text, default='[]')  # JSON array: ["analyst", "editor"]
    
    # Metadata
    category = Column(String(100))
    tags = Column(Text)  # Comma-separated
    author = Column(String(200))
    description = Column(Text)
    
    # Processing status
    status = Column(String(50), default='pending')  # pending, queued, processing, completed, failed
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
    
    # Relationships
    owner = relationship('User', back_populates='documents')
    organization = relationship('Organization', back_populates='documents')
    
    def to_dict(self):
        """Convert to dictionary"""
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
            'processed_pages': self.processed_pages or 0,
            # Permission fields
            'owner_id': self.owner_id,
            'org_id': self.org_id,
            'visibility': self.visibility,
            'shared_with_users': json.loads(self.shared_with_users) if self.shared_with_users else [],
            'shared_with_roles': json.loads(self.shared_with_roles) if self.shared_with_roles else []
        }


class DatabaseManager:
    """Database manager for SQLite"""
    
    _db_lock = threading.Lock()  # Global lock for SQLite write operations
    
    def __init__(self, db_path: str = "data/documents.db", db_url: Optional[str] = None):
        """
        Initialize database
        
        Args:
            db_path: Path to SQLite database file (used if db_url not provided)
            db_url: Full database URL (e.g., postgresql://user:pass@localhost/dbname)
        """
        if db_url:
            # Use provided database URL (PostgreSQL, MySQL, etc.)
            self.engine = create_engine(
                db_url,
                echo=False,
                pool_size=20,
                pool_recycle=3600
            )
        else:
            # Use SQLite
            db_file = Path(db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f'sqlite:///{db_path}',
                connect_args={'check_same_thread': False},
                echo=False
            )
        
        # Create all tables
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def get_session(self) -> Session:
        """Get database session"""
        return self.SessionLocal()
    
    def apply_permission_filter(self, query, user_id: Optional[int] = None, 
                                org_id: Optional[int] = None, 
                                is_superuser: bool = False):
        """
        Apply permission filter to document query
        
        Permission logic:
        - Superuser: can see all documents
        - Regular user: can see:
          1. Public documents
          2. Organization documents (if same org_id)
          3. Documents they own
          4. Documents explicitly shared with them
        """
        if is_superuser:
            # Superuser sees everything
            return query
        
        if user_id is None:
            # Anonymous users only see public documents
            return query.filter(Document.visibility == 'public')
        
        # Build permission conditions
        from sqlalchemy import or_
        
        conditions = [
            Document.visibility == 'public',  # Public documents
            Document.owner_id == user_id,  # Documents owned by user
        ]
        
        # Add organization filter if user belongs to an organization
        if org_id:
            conditions.append(
                (Document.visibility == 'org') & (Document.org_id == org_id)
            )
        
        # Add shared with user filter (check if user_id in shared_with_users JSON)
        # SQLite JSON handling: shared_with_users is TEXT field containing JSON array
        conditions.append(
            Document.shared_with_users.like(f'%{user_id}%')
        )
        
        return query.filter(or_(*conditions))
    
    def check_document_permission(self, doc_id: int, user_id: Optional[int] = None,
                                 org_id: Optional[int] = None, 
                                 is_superuser: bool = False,
                                 required_action: str = 'read') -> bool:
        """
        Check if user has permission to access a specific document
        
        Args:
            doc_id: Document ID
            user_id: User ID
            org_id: Organization ID
            is_superuser: Is user a superuser
            required_action: 'read', 'write', or 'delete'
        
        Returns:
            True if user has permission, False otherwise
        """
        if is_superuser:
            return True
        
        session = self.get_session()
        try:
            doc = session.query(Document).filter(Document.id == doc_id).first()
            if not doc:
                return False
            
            # Check ownership for write/delete actions
            if required_action in ['write', 'delete']:
                return doc.owner_id == user_id or is_superuser
            
            # Check read permission
            if doc.visibility == 'public':
                return True
            
            if doc.owner_id == user_id:
                return True
            
            if doc.visibility == 'org' and doc.org_id == org_id:
                return True
            
            # Check if shared with user
            if doc.shared_with_users:
                shared_users = json.loads(doc.shared_with_users)
                if user_id in shared_users:
                    return True
            
            return False
            
        finally:
            session.close()
    
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
        ocr_engine: Optional[str] = None,
        owner_id: Optional[int] = None,
        org_id: Optional[int] = None,
        visibility: str = 'private'
    ) -> Document:
        """Create new document record"""
        with self._db_lock:
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
                    owner_id=owner_id,
                    org_id=org_id,
                    visibility=visibility,
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
        with self._db_lock:
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
        with self._db_lock:
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
        with self._db_lock:
            session = self.get_session()
            try:
                doc = session.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    doc.pages_data = json.dumps(pages_data)
                    doc.total_pages = len(pages_data)  # 🔥 同时更新页数
                    session.commit()
            finally:
                session.close()
    
    def get_document(self, doc_id: int, user_id: Optional[int] = None,
                    org_id: Optional[int] = None, is_superuser: bool = False) -> Optional[Document]:
        """
        Get document by ID with permission check
        
        Args:
            doc_id: Document ID
            user_id: Current user ID for permission check (None to skip check)
            org_id: Current user's organization ID
            is_superuser: Is user a superuser
        """
        session = self.get_session()
        try:
            query = session.query(Document).filter(Document.id == doc_id)
            
            # Apply permission filter if user_id is provided
            if user_id is not None or not is_superuser:
                query = self.apply_permission_filter(query, user_id, org_id, is_superuser)
            
            return query.first()
        finally:
            session.close()
    
    def get_document_by_checksum(self, checksum: str) -> Optional[Document]:
        """Get document by checksum"""
        session = self.get_session()
        try:
            return session.query(Document).filter(Document.checksum == checksum).first()
        finally:
            session.close()
    
    def get_documents_by_status(self, statuses: List[str]) -> List[Document]:
        """Get documents by a list of statuses"""
        session = self.get_session()
        try:
            return session.query(Document).filter(Document.status.in_(statuses)).all()
        finally:
            session.close()

    def list_documents(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        exclude_file_types: Optional[List[str]] = None,
        user_id: Optional[int] = None,
        org_id: Optional[int] = None,
        is_superuser: bool = False
    ) -> List[Document]:
        """
        List documents with permission filtering
        
        Args:
            limit: Maximum number of documents to return
            offset: Number of documents to skip
            status: Filter by document status
            exclude_file_types: File types to exclude
            user_id: Current user ID for permission filtering
            org_id: Current user's organization ID
            is_superuser: Is user a superuser
        """
        session = self.get_session()
        try:
            query = session.query(Document)
            
            # Apply permission filter
            query = self.apply_permission_filter(query, user_id, org_id, is_superuser)
            
            if status:
                query = query.filter(Document.status == status)
            if exclude_file_types:
                query = query.filter(Document.file_type.notin_(exclude_file_types))
            return query.order_by(Document.uploaded_at.desc()).limit(limit).offset(offset).all()
        finally:
            session.close()
    
    def delete_document(self, doc_id: int) -> bool:
        """Delete document by ID"""
        with self._db_lock:
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
        with self._db_lock:
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
            
            # Calculate total pages across all documents
            from sqlalchemy import func
            total_pages_result = session.query(func.sum(Document.total_pages)).scalar()
            total_pages = total_pages_result or 0
            
            return {
                'total': total,
                'completed': completed,
                'failed': failed,
                'processing': processing,
                'total_pages': total_pages
            }
        finally:
            session.close()


class AuthManager:
    """Manager for authentication-related operations"""
    
    def __init__(self, engine):
        """Initialize auth manager with database engine"""
        self.engine = engine
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._db_lock = threading.Lock()
    
    def get_session(self) -> Session:
        """Get database session"""
        return self.SessionLocal()
    
    # Organization methods
    def create_organization(self, name: str, description: Optional[str] = None) -> Organization:
        """Create new organization"""
        with self._db_lock:
            session = self.get_session()
            try:
                org = Organization(name=name, description=description)
                session.add(org)
                session.commit()
                session.refresh(org)
                return org
            finally:
                session.close()
    
    def get_organization(self, org_id: int) -> Optional[Organization]:
        """Get organization by ID"""
        session = self.get_session()
        try:
            return session.query(Organization).filter(Organization.id == org_id).first()
        finally:
            session.close()
    
    # User methods
    def create_user(
        self,
        username: str,
        email: str,
        password_hash: str,
        org_id: Optional[int] = None,
        is_superuser: bool = False
    ) -> User:
        """Create new user"""
        with self._db_lock:
            session = self.get_session()
            try:
                user = User(
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    org_id=org_id,
                    is_superuser=is_superuser
                )
                session.add(user)
                session.commit()
                session.refresh(user)
                return user
            finally:
                session.close()
    
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID with roles preloaded"""
        session = self.get_session()
        try:
            user = session.query(User).options(joinedload(User.roles)).filter(User.id == user_id).first()
            if user:
                # Force load roles to prevent DetachedInstanceError
                _ = user.roles
            return user
        finally:
            session.close()
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username with roles preloaded"""
        session = self.get_session()
        try:
            user = session.query(User).options(joinedload(User.roles)).filter(User.username == username).first()
            if user:
                # Force load roles to prevent DetachedInstanceError
                _ = user.roles
            return user
        finally:
            session.close()
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email with roles preloaded"""
        session = self.get_session()
        try:
            user = session.query(User).options(joinedload(User.roles)).filter(User.email == email).first()
            if user:
                # Force load roles to prevent DetachedInstanceError
                _ = user.roles
            return user
        finally:
            session.close()
    
    def update_user_last_login(self, user_id: int):
        """Update user's last login time"""
        with self._db_lock:
            session = self.get_session()
            try:
                user = session.query(User).filter(User.id == user_id).first()
                if user:
                    user.last_login = datetime.utcnow()
                    session.commit()
            finally:
                session.close()
    
    # Role methods
    def create_role(
        self,
        name: str,
        code: str,
        description: Optional[str] = None,
        org_id: Optional[int] = None,
        is_system: bool = False
    ) -> Role:
        """Create new role"""
        with self._db_lock:
            session = self.get_session()
            try:
                role = Role(
                    name=name,
                    code=code,
                    description=description,
                    org_id=org_id,
                    is_system=is_system
                )
                session.add(role)
                session.commit()
                session.refresh(role)
                return role
            finally:
                session.close()
    
    def get_role_by_code(self, code: str) -> Optional[Role]:
        """Get role by code"""
        session = self.get_session()
        try:
            return session.query(Role).filter(Role.code == code).first()
        finally:
            session.close()
    
    def assign_role_to_user(self, user_id: int, role_id: int):
        """Assign role to user"""
        with self._db_lock:
            session = self.get_session()
            try:
                user = session.query(User).filter(User.id == user_id).first()
                role = session.query(Role).filter(Role.id == role_id).first()
                if user and role and role not in user.roles:
                    user.roles.append(role)
                    session.commit()
            finally:
                session.close()
    
    # Permission methods
    def create_permission(
        self,
        code: str,
        resource: str,
        action: str,
        description: Optional[str] = None
    ) -> Permission:
        """Create new permission"""
        with self._db_lock:
            session = self.get_session()
            try:
                permission = Permission(
                    code=code,
                    resource=resource,
                    action=action,
                    description=description
                )
                session.add(permission)
                session.commit()
                session.refresh(permission)
                return permission
            finally:
                session.close()
    
    def get_permission_by_code(self, code: str) -> Optional[Permission]:
        """Get permission by code"""
        session = self.get_session()
        try:
            return session.query(Permission).filter(Permission.code == code).first()
        finally:
            session.close()
    
    def assign_permission_to_role(self, role_id: int, permission_id: int):
        """Assign permission to role"""
        with self._db_lock:
            session = self.get_session()
            try:
                role = session.query(Role).filter(Role.id == role_id).first()
                permission = session.query(Permission).filter(Permission.id == permission_id).first()
                if role and permission and permission not in role.permissions:
                    role.permissions.append(permission)
                    session.commit()
            finally:
                session.close()
    
    def get_user_permissions(self, user_id: int) -> List[str]:
        """Get all permission codes for a user"""
        session = self.get_session()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                return []
            
            permissions = set()
            for role in user.roles:
                for perm in role.permissions:
                    permissions.add(perm.code)
            
            return list(permissions)
        finally:
            session.close()

    def get_user_roles(self, user_id: int) -> List[str]:
        """Get all role codes for a user"""
        session = self.get_session()
        try:
            user = session.query(User).options(joinedload(User.roles)).filter(User.id == user_id).first()
            if not user:
                return []
            return [role.code for role in user.roles]
        finally:
            session.close()


class TokenManager:
    """Manager for token operations"""
    
    def __init__(self, engine):
        """Initialize token manager with database engine"""
        self.engine = engine
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._db_lock = threading.Lock()
    
    def get_session(self) -> Session:
        """Get database session"""
        return self.SessionLocal()
    
    # MCP Token methods
    def create_mcp_token(
        self,
        token_id: str,
        user_id: int,
        name: str,
        expires_at: datetime
    ) -> McpToken:
        """Create new MCP token"""
        with self._db_lock:
            session = self.get_session()
            try:
                token = McpToken(
                    token_id=token_id,
                    user_id=user_id,
                    name=name,
                    expires_at=expires_at
                )
                session.add(token)
                session.commit()
                session.refresh(token)
                return token
            finally:
                session.close()
    
    def get_mcp_token_by_token_id(self, token_id: str) -> Optional[McpToken]:
        """Get MCP token by token_id"""
        session = self.get_session()
        try:
            return session.query(McpToken).filter(McpToken.token_id == token_id).first()
        finally:
            session.close()
    
    def list_user_mcp_tokens(self, user_id: int) -> List[McpToken]:
        """List all MCP tokens for a user"""
        session = self.get_session()
        try:
            return session.query(McpToken).filter(
                McpToken.user_id == user_id
            ).order_by(McpToken.created_at.desc()).all()
        finally:
            session.close()
    
    def update_mcp_token_last_used(self, token_id: str):
        """Update MCP token's last used timestamp"""
        with self._db_lock:
            session = self.get_session()
            try:
                token = session.query(McpToken).filter(McpToken.token_id == token_id).first()
                if token:
                    token.last_used_at = datetime.utcnow()
                    session.commit()
            finally:
                session.close()
    
    def revoke_mcp_token(self, token_id: str) -> bool:
        """Revoke MCP token"""
        with self._db_lock:
            session = self.get_session()
            try:
                token = session.query(McpToken).filter(McpToken.token_id == token_id).first()
                if token:
                    token.is_active = False
                    session.commit()
                    return True
                return False
            finally:
                session.close()
    
    def delete_mcp_token(self, token_id: str) -> bool:
        """Delete MCP token"""
        with self._db_lock:
            session = self.get_session()
            try:
                token = session.query(McpToken).filter(McpToken.token_id == token_id).first()
                if token:
                    session.delete(token)
                    session.commit()
                    return True
                return False
            finally:
                session.close()
    
    # Refresh Token methods
    def create_refresh_token(
        self,
        token_id: str,
        user_id: int,
        expires_at: datetime
    ) -> RefreshToken:
        """Create new refresh token"""
        with self._db_lock:
            session = self.get_session()
            try:
                token = RefreshToken(
                    token_id=token_id,
                    user_id=user_id,
                    expires_at=expires_at
                )
                session.add(token)
                session.commit()
                session.refresh(token)
                return token
            finally:
                session.close()
    
    def get_refresh_token(self, token_id: str) -> Optional[RefreshToken]:
        """Get refresh token by token_id"""
        session = self.get_session()
        try:
            return session.query(RefreshToken).filter(
                RefreshToken.token_id == token_id
            ).first()
        finally:
            session.close()
    
    def revoke_refresh_token(self, token_id: str) -> bool:
        """Revoke refresh token"""
        with self._db_lock:
            session = self.get_session()
            try:
                token = session.query(RefreshToken).filter(RefreshToken.token_id == token_id).first()
                if token:
                    token.is_revoked = True
                    session.commit()
                    return True
                return False
            finally:
                session.close()
    
    def revoke_user_refresh_tokens(self, user_id: int):
        """Revoke all refresh tokens for a user"""
        with self._db_lock:
            session = self.get_session()
            try:
                tokens = session.query(RefreshToken).filter(
                    RefreshToken.user_id == user_id,
                    RefreshToken.is_revoked == False
                ).all()
                for token in tokens:
                    token.is_revoked = True
                session.commit()
            finally:
                session.close()
