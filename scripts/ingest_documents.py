#!/usr/bin/env python3
"""
Batch ingest documents from directory
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.pipeline import ProcessingPipeline


def main():
    """Main function for batch document ingestion"""
    parser = argparse.ArgumentParser(
        description="Batch ingest documents into knowledge base"
    )
    parser.add_argument(
        "path",
        type=str,
        help="Path to file or directory to ingest"
    )
    parser.add_argument(
        "--category",
        type=str,
        help="Category for documents"
    )
    parser.add_argument(
        "--tags",
        type=str,
        help="Comma-separated tags"
    )
    parser.add_argument(
        "--author",
        type=str,
        help="Author name"
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively process subdirectories"
    )
    
    args = parser.parse_args()
    
    print("=== Document Ingestion ===\n")
    
    path = Path(args.path)
    
    if not path.exists():
        print(f"❌ Path not found: {path}")
        return 1
    
    # Prepare metadata
    metadata = {}
    if args.category:
        metadata['category'] = args.category
    if args.tags:
        metadata['tags'] = args.tags.split(',')
    if args.author:
        metadata['author'] = args.author
    
    # Initialize pipeline
    print("Initializing pipeline...")
    pipeline = ProcessingPipeline()
    print("✅ Pipeline initialized\n")
    
    # Collect files
    files_to_process = []
    
    if path.is_file():
        files_to_process.append(str(path))
    elif path.is_dir():
        pattern = "**/*" if args.recursive else "*"
        for ext in ['.pdf', '.docx', '.doc', '.txt', '.md', '.html', '.csv', '.xlsx']:
            files_to_process.extend([str(f) for f in path.glob(f"{pattern}{ext}")])
    
    if not files_to_process:
        print("⚠️  No files found to process")
        return 0
    
    print(f"Found {len(files_to_process)} files to process\n")
    
    # Process files
    success_count = 0
    fail_count = 0
    
    for i, file_path in enumerate(files_to_process, 1):
        print(f"[{i}/{len(files_to_process)}] Processing: {Path(file_path).name}...")
        
        try:
            result = pipeline.process_file(file_path, metadata)
            
            if result.get('status') == 'completed':
                print(f"  ✅ Success: {result['num_chunks']} chunks indexed")
                success_count += 1
            else:
                print(f"  ❌ Failed: {result.get('error', 'Unknown error')}")
                fail_count += 1
        
        except Exception as e:
            print(f"  ❌ Error: {e}")
            fail_count += 1
    
    print()
    print("=" * 50)
    print("📊 Ingestion Summary:")
    print(f"  - Total files: {len(files_to_process)}")
    print(f"  - Successfully processed: {success_count}")
    print(f"  - Failed: {fail_count}")
    print("=" * 50)
    
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

