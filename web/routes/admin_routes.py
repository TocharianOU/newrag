"""Admin routes for user and organization management"""

import os
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
import bcrypt

from src.database import DatabaseManager, AuthManager, User, Organization, Role
from src.config import config
from web.dependencies.auth_deps import get_current_user, db_session, get_db_manager
from web.routes.auth_routes import DEFAULT_ROLE

router = APIRouter(prefix="/admin", tags=["Admin"])


# ============================================================================
# Request/Response Models
# ============================================================================

class UserListResponse(BaseModel):
    """User list item response"""
    id: int
    username: str
    email: str
    org_id: Optional[int]
    org_name: Optional[str]
    roles: List[dict]
    is_active: bool
    is_superuser: bool
    created_at: str
    last_login: Optional[str]


class UserDetailResponse(BaseModel):
    """Detailed user response"""
    id: int
    username: str
    email: str
    org_id: Optional[int]
    roles: List[dict]
    permissions: List[str]
    is_active: bool
    is_superuser: bool
    created_at: str
    last_login: Optional[str]


class CreateUserRequest(BaseModel):
    """Create user request"""
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    org_id: int
    role_codes: List[str] = []
    is_active: bool = True
    is_superuser: bool = False


class UpdateUserRequest(BaseModel):
    """Update user request"""
    email: Optional[EmailStr] = None
    org_id: Optional[int] = None
    role_codes: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    """Reset password request"""
    new_password: str = Field(..., min_length=8, max_length=72)


class OrganizationResponse(BaseModel):
    """Organization response"""
    id: int
    name: str
    description: Optional[str]
    member_count: int
    document_count: int
    created_at: str


class OrganizationDetailResponse(BaseModel):
    """Detailed organization response"""
    id: int
    name: str
    description: Optional[str]
    members: List[UserListResponse]
    created_at: str


class CreateOrganizationRequest(BaseModel):
    """Create organization request"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    """Update organization request"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Paginated response wrapper"""
    items: List[dict]
    total: int
    page: int
    per_page: int
    total_pages: int


# ============================================================================
# Helper Functions
# ============================================================================

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency to ensure user is admin"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')


# ============================================================================
# User Management Routes
# ============================================================================

@router.get("/users", response_model=PaginatedResponse)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    org_id: Optional[int] = None,
    role_code: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    List all users with pagination and filters
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    users, total = auth_manager.list_users_paginated(
        page=page,
        per_page=per_page,
        search=search,
        org_id=org_id,
        role_code=role_code,
        is_active=is_active
    )
    
    # Get organization names
    org_cache = {}
    for user in users:
        if user.org_id and user.org_id not in org_cache:
            org = auth_manager.get_organization(user.org_id)
            org_cache[user.org_id] = org.name if org else None
    
    items = []
    for user in users:
        items.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'org_id': user.org_id,
            'org_name': org_cache.get(user.org_id),
            'roles': [{'code': r.code, 'name': r.name} for r in user.roles],
            'is_active': user.is_active,
            'is_superuser': user.is_superuser,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'last_login': user.last_login.isoformat() if user.last_login else None
        })
    
    total_pages = (total + per_page - 1) // per_page
    
    return {
        'items': items,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    }


@router.get("/users/{user_id}", response_model=UserDetailResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    Get user details
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    user = auth_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    permissions = auth_manager.get_user_permissions(user_id)
    
    return UserDetailResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        org_id=user.org_id,
        roles=[{'code': r.code, 'name': r.name} for r in user.roles],
        permissions=permissions,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at.isoformat() if user.created_at else '',
        last_login=user.last_login.isoformat() if user.last_login else None
    )


@router.post("/users", response_model=UserDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    Create a new user (admin only)
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    # Check if username already exists
    existing_user = auth_manager.get_user_by_username(request.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists"
        )
    
    # Check if email already exists
    existing_email = auth_manager.get_user_by_email(request.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists"
        )
    
    # Check if organization exists
    org = auth_manager.get_organization(request.org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    # Use default role if none provided
    role_codes = request.role_codes if request.role_codes else [DEFAULT_ROLE]
    
    # Hash password
    password_hash = hash_password(request.password)
    
    # Create user
    user = auth_manager.create_user_by_admin(
        username=request.username,
        email=request.email,
        password_hash=password_hash,
        org_id=request.org_id,
        role_codes=role_codes,
        is_active=request.is_active,
        is_superuser=request.is_superuser
    )
    
    permissions = auth_manager.get_user_permissions(user.id)
    
    return UserDetailResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        org_id=user.org_id,
        roles=[{'code': r.code, 'name': r.name} for r in user.roles],
        permissions=permissions,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at.isoformat() if user.created_at else '',
        last_login=user.last_login.isoformat() if user.last_login else None
    )


@router.put("/users/{user_id}", response_model=UserDetailResponse)
async def update_user(
    user_id: int,
    request: UpdateUserRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    Update user information (admin only)
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    # Check if user exists
    user = auth_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check if email is being changed and already exists
    if request.email and request.email != user.email:
        existing_email = auth_manager.get_user_by_email(request.email)
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already exists"
            )
    
    # Check if organization exists
    if request.org_id is not None:
        org = auth_manager.get_organization(request.org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found"
            )
    
    # Update user
    updated_user = auth_manager.update_user_by_admin(
        user_id=user_id,
        email=request.email,
        org_id=request.org_id,
        role_codes=request.role_codes,
        is_active=request.is_active,
        is_superuser=request.is_superuser
    )
    
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    permissions = auth_manager.get_user_permissions(updated_user.id)
    
    return UserDetailResponse(
        id=updated_user.id,
        username=updated_user.username,
        email=updated_user.email,
        org_id=updated_user.org_id,
        roles=[{'code': r.code, 'name': r.name} for r in updated_user.roles],
        permissions=permissions,
        is_active=updated_user.is_active,
        is_superuser=updated_user.is_superuser,
        created_at=updated_user.created_at.isoformat() if updated_user.created_at else '',
        last_login=updated_user.last_login.isoformat() if updated_user.last_login else None
    )


@router.delete("/users/{user_id}")
async def disable_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    Disable user (soft delete)
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    # Check if user exists
    user = auth_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Cannot disable self
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable your own account"
        )
    
    # Disable user
    auth_manager.update_user_by_admin(
        user_id=user_id,
        is_active=False
    )
    
    return {"message": "User disabled successfully"}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    request: ResetPasswordRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    Reset user password (admin only)
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    # Check if user exists
    user = auth_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Hash new password
    password_hash = hash_password(request.new_password)
    
    # Update password
    auth_manager.update_user_by_admin(
        user_id=user_id,
        password_hash=password_hash
    )
    
    return {"message": "Password reset successfully"}


# ============================================================================
# Organization Management Routes
# ============================================================================

@router.get("/organizations", response_model=List[OrganizationResponse])
async def list_organizations(
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    List all organizations
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    orgs = auth_manager.list_organizations()
    
    # Count members and documents for each org
    result = []
    for org in orgs:
        members = auth_manager.get_organization_members(org.id)
        document_count = db_manager.count_documents_by_org(org.id)
        
        result.append({
            'id': org.id,
            'name': org.name,
            'description': org.description,
            'member_count': len(members),
            'document_count': document_count,
            'created_at': org.created_at.isoformat() if org.created_at else ''
        })
    
    return result


@router.get("/organizations/{org_id}", response_model=OrganizationDetailResponse)
async def get_organization(
    org_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    Get organization details with members
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    org = auth_manager.get_organization(org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    members = auth_manager.get_organization_members(org_id)
    
    member_list = []
    for user in members:
        member_list.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'org_id': user.org_id,
            'org_name': org.name,
            'roles': [{'code': r.code, 'name': r.name} for r in user.roles],
            'is_active': user.is_active,
            'is_superuser': user.is_superuser,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'last_login': user.last_login.isoformat() if user.last_login else None
        })
    
    return {
        'id': org.id,
        'name': org.name,
        'description': org.description,
        'members': member_list,
        'created_at': org.created_at.isoformat() if org.created_at else ''
    }


@router.post("/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    request: CreateOrganizationRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    Create a new organization
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    # Create organization
    org = auth_manager.create_organization(
        name=request.name,
        description=request.description
    )
    
    return {
        'id': org.id,
        'name': org.name,
        'description': org.description,
        'member_count': 0,
        'document_count': 0,
        'created_at': org.created_at.isoformat() if org.created_at else ''
    }


@router.put("/organizations/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: int,
    request: UpdateOrganizationRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    Update organization
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    org = auth_manager.update_organization(
        org_id=org_id,
        name=request.name,
        description=request.description
    )
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    members = auth_manager.get_organization_members(org_id)
    
    return {
        'id': org.id,
        'name': org.name,
        'description': org.description,
        'member_count': len(members),
        'document_count': 0,
        'created_at': org.created_at.isoformat() if org.created_at else ''
    }


@router.delete("/organizations/{org_id}")
async def delete_organization(
    org_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    Delete organization (only if no users or documents)
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    success = auth_manager.delete_organization(org_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete organization with users or documents"
        )
    
    return {"message": "Organization deleted successfully"}


# ============================================================================
# Role Management Routes
# ============================================================================

@router.get("/roles")
async def list_roles(
    current_user: User = Depends(require_admin),
    db: Session = Depends(db_session)
):
    """
    List all available roles
    
    Requires admin privileges.
    """
    db_manager = get_db_manager()
    auth_manager = AuthManager(db_manager.engine)
    
    roles = auth_manager.list_all_roles()
    
    return [
        {
            'id': role.id,
            'name': role.name,
            'code': role.code,
            'description': role.description,
            'is_system': role.is_system
        }
        for role in roles
    ]



