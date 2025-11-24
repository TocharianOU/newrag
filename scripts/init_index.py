#!/usr/bin/env python3
"""
Initialize Elasticsearch index with proper mappings
"""

import json
import sys
from pathlib import Path

from elasticsearch import Elasticsearch

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.config import config


def main():
    """Initialize Elasticsearch index"""
    print("=== Elasticsearch Index Initialization ===\n")
    
    # Load ES config
    es_config = config.es_config
    hosts = es_config.get('hosts', ['http://localhost:9200'])
    index_name = es_config.get('index_name', 'aiops_knowledge_base')
    username = es_config.get('username', '')
    password = es_config.get('password', '')
    
    print(f"Connecting to Elasticsearch: {hosts[0]}")
    print(f"Index name: {index_name}\n")
    
    # Connect to Elasticsearch
    try:
        es = Elasticsearch(
            hosts,
            basic_auth=(username, password) if username else None,
            timeout=30
        )
        
        if not es.ping():
            print("❌ Failed to connect to Elasticsearch")
            return 1
        
        print("✅ Connected to Elasticsearch successfully\n")
    
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return 1
    
    # Load mapping from JSON file
    mapping_file = Path(__file__).parent.parent / "schemas" / "elasticsearch_mapping.json"
    
    try:
        with open(mapping_file, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
        
        print("✅ Loaded index mapping from file")
        
        # Validate vector dimensions match config
        embedding_config = config.embedding_config
        config_dims = embedding_config.get('dimensions', 1536)
        mapping_dims = mapping.get('mappings', {}).get('properties', {}).get('content_vector', {}).get('dims', 0)
        
        if config_dims != mapping_dims:
            print(f"\n⚠️  WARNING: Dimension mismatch detected!")
            print(f"  Config (config.yaml): {config_dims}")
            print(f"  Mapping (elasticsearch_mapping.json): {mapping_dims}")
            print(f"\n  This will cause indexing errors!")
            response = input("\nDo you want to update mapping to match config? (yes/no): ")
            
            if response.lower() in ['yes', 'y']:
                mapping['mappings']['properties']['content_vector']['dims'] = config_dims
                print(f"✅ Updated mapping dims to {config_dims}\n")
            else:
                print("❌ Please manually fix the dimension mismatch")
                return 1
        else:
            print(f"✅ Vector dimensions validated: {config_dims}\n")
    
    except Exception as e:
        print(f"❌ Failed to load mapping file: {e}")
        return 1
    
    # Check if index already exists
    if es.indices.exists(index=index_name):
        print(f"⚠️  Index '{index_name}' already exists")
        response = input("Do you want to delete and recreate it? (yes/no): ")
        
        if response.lower() in ['yes', 'y']:
            es.indices.delete(index=index_name)
            print(f"✅ Deleted existing index '{index_name}'\n")
        else:
            print("❌ Aborted")
            return 0
    
    # Create index with mapping
    try:
        es.indices.create(index=index_name, body=mapping)
        print(f"✅ Created index '{index_name}' successfully\n")
    
    except Exception as e:
        print(f"❌ Failed to create index: {e}")
        return 1
    
    # Verify index creation
    try:
        info = es.indices.get(index=index_name)
        settings = info[index_name]['settings']
        mappings = info[index_name]['mappings']
        
        print("📊 Index Information:")
        print(f"  - Shards: {settings['index']['number_of_shards']}")
        print(f"  - Replicas: {settings['index']['number_of_replicas']}")
        print(f"  - Fields: {len(mappings['properties'])}")
        print()
        
        # Check IK analyzer
        analysis = settings['index'].get('analysis', {})
        if 'ik_max_word_analyzer' in analysis.get('analyzer', {}):
            print("✅ IK Chinese analyzer configured")
        else:
            print("⚠️  IK analyzer not found. Please install elasticsearch-analysis-ik plugin:")
            print("   elasticsearch-plugin install https://github.com/medcl/elasticsearch-analysis-ik/releases/...")
        
        print()
        print("=" * 50)
        print("✅ Index initialization completed successfully!")
        print("=" * 50)
        
        return 0
    
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

