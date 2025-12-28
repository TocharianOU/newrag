"""Authentication dependency injection functions"""

from typing import Optional, Dict, Any, Generator
from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session, joinedload

from src.database import DatabaseManager, User

# Initialize database manager
_db_manager = None

def get_db_manager() -> DatabaseManager:
    """Get database manager singleton"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def db_session() -> Generator[Session, None, None]:
    """
    Database session dependency for FastAPI routes.
    
    Usage:
        @router.post("/items")
        async def create_item(db: Session = Depends(db_session)):
            # Use db session
            pass
    """
    db_manager = get_db_manager()
    session = db_manager.get_session()
    try:
        yield session
    finally:
        session.close()


def get_current_user(request: Request, db: Session = Depends(db_session)) -> User:
    """
    Get current authenticated user from request state and database.
    Raises 401 if user is not authenticated.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            return {"user_id": user.id}
    """
    user_data = getattr(request.state, 'user', None)
    
    if not user_data:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please login to access this resource."
        )
    
    # Get full User object from database with roles
    user = db.query(User).options(joinedload(User.roles)).filter(User.id == user_data['id']).first()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="User not found or inactive"
        )
    
    return user


def get_optional_user(request: Request, db: Session = Depends(db_session)) -> Optional[User]:
    """
    Get current user if authenticated, otherwise return None.
    Does not raise exception if user is not authenticated.
    
    Usage:
        @router.get("/public-or-private")
        async def flexible_route(user: Optional[User] = Depends(get_optional_user)):
            if user:
                return {"message": f"Hello {user.username}"}
            return {"message": "Hello guest"}
    """
    user_data = getattr(request.state, 'user', None)
    
    if not user_data:
        return None
    
    # Get full User object from database with roles
    user = db.query(User).options(joinedload(User.roles)).filter(User.id == user_data['id']).first()
    
    if not user or not user.is_active:
        return None
    
    return user


def require_permission(permission: str):
    """
    Dependency factory that checks if user has a specific permission.
    
    Args:
        permission: Permission code (e.g., "document:write")
    
    Usage:
        @router.post("/upload")
        async def upload(
            user: Dict = Depends(get_current_user),
            _perm: None = Depends(require_permission("document:write"))
        ):
            return {"status": "ok"}
    """
    def check_permission(user: User = Depends(get_current_user)) -> None:
        # Superusers have all permissions
        if user.is_superuser:
            return
        
        # Get user permissions from roles
        user_permissions = set()
        for role in user.roles:
            for perm in role.permissions:
                user_permissions.add(perm.code)
        
        # Check for exact permission or wildcard
        if permission in user_permissions or 'admin:all' in user_permissions:
            return
        
        # Check for resource-level wildcard (e.g., "document:*")
        resource = permission.split(':')[0] if ':' in permission else permission
        wildcard_perm = f"{resource}:*"
        if wildcard_perm in user_permissions:
            return
        
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied. Required permission: {permission}"
        )
    
    return check_permission


def require_role(role_code: str):
    """
    Dependency factory that checks if user has a specific role.
    
    Args:
        role_code: Role code (e.g., "admin", "editor")
    
    Usage:
        @router.get("/admin-only")
        async def admin_route(
            user: Dict = Depends(get_current_user),
            _role: None = Depends(require_role("admin"))
        ):
            return {"status": "admin access granted"}
    """
    def check_role(user: User = Depends(get_current_user)) -> None:
        # Superusers bypass role checks
        if user.is_superuser:
            return
        
        user_role_codes = [role.code for role in user.roles]
        
        if role_code not in user_role_codes:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {role_code}"
            )
    
    return check_role

