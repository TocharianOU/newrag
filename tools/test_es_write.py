import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.vector_store import VectorStore
from langchain.schema import Document

def test_es_write():
    print("🚀 Starting ES write test...")
    
    vs = VectorStore()
    
    # Construct a document with structured_content
    # This mimics what process_excel.py produces
    doc = Document(
        page_content="Test content for structured data",
        metadata={
            "filename": "test_excel.xlsx",
            "file_type": "xlsx",
            "structured_content": [
                {"key": "Name", "value": "Luke", "sheet_name": "Sheet1"},
                {"key": "Age", "value": "30", "sheet_name": "Sheet1"},
                {"key": "Role", "value": "Jedi", "sheet_name": "Sheet1"}
            ]
        }
    )
    
    print(f"📄 Preparing to index document with {len(doc.metadata['structured_content'])} KV pairs...")
    
    try:
        ids = vs.add_documents([doc])
        if ids:
            print(f"✅ Success! Document ID: {ids[0]}")
            
            # Verify retrieval
            import time
            import requests
            time.sleep(1) # Wait for refresh
            
            print("🔍 Verifying retrieval...")
            try:
                # Direct ES query to check nested field
                response = requests.get(
                    "http://localhost:9200/aiops_knowledge_base/_search",
                    json={
                        "query": {
                            "nested": {
                                "path": "metadata.structured_content",
                                "query": {
                                    "bool": {
                                        "must": [
                                            {"term": {"metadata.structured_content.key": "Name"}},
                                            {"match": {"metadata.structured_content.value": "Luke"}}
                                        ]
                                    }
                                }
                            }
                        }
                    },
                    headers={"Content-Type": "application/json"}
                )
                print(f"🔎 Search Result: {json.dumps(response.json(), indent=2)}")
            except Exception as e:
                print(f"❌ Search Verification Failed: {e}")
                
        else:
            print("❌ Failed: No IDs returned")
            
    except Exception as e:
        print(f"❌ Exception during write: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_es_write()



