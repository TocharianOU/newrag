#!/usr/bin/env python3
"""
Multi-organization data migration script

Ensures all users and documents are properly assigned to organizations.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import DatabaseManager, AuthManager, User, Document, Organization
from src.logging_config import setup_logging
import structlog

# Setup logging
setup_logging()
logger = structlog.get_logger(__name__)


def migrate_data():
    """Migrate existing data to multi-organization structure"""
    
    print("=" * 60)
    print("Multi-Organization Data Migration")
    print("=" * 60)
    print()
    
    # Initialize database
    db_path = "data/documents.db"
    if not Path(db_path).exists():
        print(f"❌ Database not found at {db_path}")
        return False
    
    db_manager = DatabaseManager(db_path=db_path)
    auth_manager = AuthManager(db_manager.engine)
    
    # Step 1: Get or create default organization
    print("Step 1: Checking default organization...")
    session = db_manager.get_session()
    try:
        default_org = session.query(Organization).filter(Organization.name == "Default Organization").first()
        
        if not default_org:
            print("   Creating default organization...")
            default_org = auth_manager.create_organization(
                name="Default Organization",
                description="Default organization for existing users and documents"
            )
            print(f"   ✓ Created default organization (ID: {default_org.id})")
        else:
            print(f"   ✓ Default organization exists (ID: {default_org.id})")
    finally:
        session.close()
    
    # Step 2: Assign users without organization to default organization
    print("\nStep 2: Checking users without organization...")
    session = db_manager.get_session()
    try:
        users_without_org = session.query(User).filter(User.org_id == None).all()
        
        if users_without_org:
            print(f"   Found {len(users_without_org)} users without organization")
            for user in users_without_org:
                user.org_id = default_org.id
                print(f"   → Assigned user '{user.username}' to default organization")
            session.commit()
            print(f"   ✓ Updated {len(users_without_org)} users")
        else:
            print("   ✓ All users already assigned to organizations")
    finally:
        session.close()
    
    # Step 3: Assign documents without owner to admin user
    print("\nStep 3: Checking documents without owner...")
    session = db_manager.get_session()
    try:
        # Get admin user
        admin_user = session.query(User).filter(User.username == "admin").first()
        
        if not admin_user:
            print("   ⚠ Warning: Admin user not found, skipping document owner assignment")
        else:
            docs_without_owner = session.query(Document).filter(Document.owner_id == None).all()
            
            if docs_without_owner:
                print(f"   Found {len(docs_without_owner)} documents without owner")
                for doc in docs_without_owner:
                    doc.owner_id = admin_user.id
                    doc.org_id = admin_user.org_id
                    doc.visibility = 'organization'  # Default to organization visibility
                    print(f"   → Assigned document '{doc.filename}' to admin user")
                session.commit()
                print(f"   ✓ Updated {len(docs_without_owner)} documents")
            else:
                print("   ✓ All documents already have owners")
    finally:
        session.close()
    
    # Step 4: Ensure all documents have organization
    print("\nStep 4: Checking documents without organization...")
    session = db_manager.get_session()
    try:
        docs_without_org = session.query(Document).filter(Document.org_id == None).all()
        
        if docs_without_org:
            print(f"   Found {len(docs_without_org)} documents without organization")
            for doc in docs_without_org:
                # If document has owner, use owner's organization
                if doc.owner_id:
                    owner = session.query(User).filter(User.id == doc.owner_id).first()
                    if owner and owner.org_id:
                        doc.org_id = owner.org_id
                        print(f"   → Assigned document '{doc.filename}' to owner's organization")
                    else:
                        doc.org_id = default_org.id
                        print(f"   → Assigned document '{doc.filename}' to default organization")
                else:
                    doc.org_id = default_org.id
                    print(f"   → Assigned document '{doc.filename}' to default organization")
            session.commit()
            print(f"   ✓ Updated {len(docs_without_org)} documents")
        else:
            print("   ✓ All documents already assigned to organizations")
    finally:
        session.close()
    
    # Step 5: Ensure all documents have visibility setting
    print("\nStep 5: Checking documents without visibility setting...")
    session = db_manager.get_session()
    try:
        docs_without_visibility = session.query(Document).filter(
            (Document.visibility == None) | (Document.visibility == '')
        ).all()
        
        if docs_without_visibility:
            print(f"   Found {len(docs_without_visibility)} documents without visibility setting")
            for doc in docs_without_visibility:
                doc.visibility = 'organization'  # Default to organization visibility
                print(f"   → Set document '{doc.filename}' visibility to 'organization'")
            session.commit()
            print(f"   ✓ Updated {len(docs_without_visibility)} documents")
        else:
            print("   ✓ All documents have visibility settings")
    finally:
        session.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("Migration Summary")
    print("=" * 60)
    
    session = db_manager.get_session()
    try:
        total_users = session.query(User).count()
        total_docs = session.query(Document).count()
        total_orgs = session.query(Organization).count()
        
        users_with_org = session.query(User).filter(User.org_id != None).count()
        docs_with_owner = session.query(Document).filter(Document.owner_id != None).count()
        docs_with_org = session.query(Document).filter(Document.org_id != None).count()
        
        print(f"\nOrganizations: {total_orgs}")
        print(f"Users: {total_users} (with org: {users_with_org})")
        print(f"Documents: {total_docs} (with owner: {docs_with_owner}, with org: {docs_with_org})")
        
        if users_with_org == total_users and docs_with_owner == total_docs and docs_with_org == total_docs:
            print("\n✅ Migration completed successfully!")
            return True
        else:
            print("\n⚠️  Migration completed with warnings")
            return True
    finally:
        session.close()


if __name__ == "__main__":
    try:
        success = migrate_data()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error("migration_failed", error=str(e), exc_info=True)
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)

