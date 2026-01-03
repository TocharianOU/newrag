#!/usr/bin/env python3
"""
Migration script to update legacy documents with default permissions

This script:
1. Finds all documents without owner_id, org_id, or visibility
2. Sets them to public visibility (accessible by all users)
3. Optionally assigns them to a default organization
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database import DatabaseManager, Document
from src.config import config
import structlog

logger = structlog.get_logger(__name__)


def migrate_legacy_documents(
    default_visibility: str = 'public',
    assign_to_org: bool = False,
    default_org_id: int = None
):
    """
    Migrate legacy documents to have proper permission fields
    
    Args:
        default_visibility: Visibility setting for legacy documents (default: 'public')
        assign_to_org: Whether to assign documents to an organization
        default_org_id: Organization ID to assign to (if assign_to_org=True)
    """
    db = DatabaseManager()
    session = db.get_session()
    
    try:
        # Find all documents without owner_id (legacy documents)
        legacy_docs = session.query(Document).filter(
            Document.owner_id == None
        ).all()
        
        if not legacy_docs:
            logger.info("no_legacy_documents_found", message="All documents already have permissions set")
            print("✓ No legacy documents found. All documents already have permissions.")
            return 0
        
        logger.info("found_legacy_documents", count=len(legacy_docs))
        print(f"\n Found {len(legacy_docs)} legacy documents without proper permissions")
        print(f"📝 Will set visibility to: {default_visibility}")
        
        if assign_to_org and default_org_id:
            print(f"🏢 Will assign to organization ID: {default_org_id}")
        
        # Ask for confirmation
        response = input(f"\nProceed with migration? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print("Migration cancelled.")
            return 0
        
        updated_count = 0
        for doc in legacy_docs:
            # Always set visibility for legacy documents
            doc.visibility = default_visibility
            
            # Set org_id if requested and not set
            if assign_to_org and default_org_id and doc.org_id is None:
                doc.org_id = default_org_id
            
            # Note: We intentionally keep owner_id as None for truly legacy documents
            # This allows them to be managed by anyone (when visibility is public)
            
            updated_count += 1
            logger.info(
                "updated_document",
                doc_id=doc.id,
                filename=doc.filename,
                visibility=doc.visibility,
                org_id=doc.org_id
            )
        
        session.commit()
        
        print(f"\n✅ Successfully migrated {updated_count} documents")
        print(f"   - Visibility: {default_visibility}")
        if assign_to_org and default_org_id:
            print(f"   - Organization ID: {default_org_id}")
        
        # Show summary
        print("\n📊 Migration Summary:")
        print(f"   Total legacy documents: {len(legacy_docs)}")
        print(f"   Updated: {updated_count}")
        print(f"   Status: {'public' if default_visibility == 'public' else 'organization-restricted'}")
        
        return updated_count
        
    except Exception as e:
        session.rollback()
        logger.error("migration_failed", error=str(e))
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        session.close()


def list_legacy_documents():
    """List all legacy documents without showing migration"""
    db = DatabaseManager()
    session = db.get_session()
    
    try:
        # Find all documents without owner_id (legacy documents)
        legacy_docs = session.query(Document).filter(
            Document.owner_id == None
        ).all()
        
        if not legacy_docs:
            print("✓ No legacy documents found.")
            return
        
        print(f"\n📋 Found {len(legacy_docs)} legacy documents:\n")
        print(f"{'ID':<6} {'Filename':<40} {'Owner ID':<10} {'Org ID':<8} {'Visibility':<12}")
        print("-" * 80)
        
        for doc in legacy_docs:
            print(
                f"{doc.id:<6} "
                f"{doc.filename[:38]:<40} "
                f"{str(doc.owner_id) if doc.owner_id else 'None':<10} "
                f"{str(doc.org_id) if doc.org_id else 'None':<8} "
                f"{doc.visibility if doc.visibility else 'None':<12}"
            )
        
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Migrate legacy documents to have proper permissions"
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List legacy documents without migrating'
    )
    parser.add_argument(
        '--visibility',
        default='public',
        choices=['public', 'organization', 'private'],
        help='Default visibility for legacy documents (default: public)'
    )
    parser.add_argument(
        '--org-id',
        type=int,
        help='Organization ID to assign legacy documents to'
    )
    parser.add_argument(
        '--auto-confirm',
        action='store_true',
        help='Skip confirmation prompt'
    )
    
    args = parser.parse_args()
    
    if args.list:
        list_legacy_documents()
    else:
        print("🔄 Legacy Document Migration Tool")
        print("=" * 50)
        
        if args.auto_confirm:
            # For automated migrations
            migrate_legacy_documents(
                default_visibility=args.visibility,
                assign_to_org=bool(args.org_id),
                default_org_id=args.org_id
            )
        else:
            migrate_legacy_documents(
                default_visibility=args.visibility,
                assign_to_org=bool(args.org_id),
                default_org_id=args.org_id
            )

