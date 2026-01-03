#!/usr/bin/env python3
"""Test login for user luke"""

import requests
import json

# API endpoint (adjust if needed)
BASE_URL = "http://localhost:8000"

def test_login(username, password):
    """Test login with given credentials"""
    url = f"{BASE_URL}/auth/login"
    
    payload = {
        "username": username,
        "password": password
    }
    
    print(f"🔐 Testing login for user: {username}")
    print(f"📍 URL: {url}")
    print(f"📦 Payload: {json.dumps(payload, indent=2)}")
    print("-" * 80)
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        
        print(f"📊 Status Code: {response.status_code}")
        print(f"📄 Response:")
        print(json.dumps(response.json(), indent=2))
        
        if response.status_code == 200:
            print("\n✅ Login successful!")
            return True
        else:
            print(f"\n❌ Login failed: {response.json().get('detail', 'Unknown error')}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ Connection error: Is the server running?")
        print(f"   Make sure the server is running on {BASE_URL}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    print("="*80)
    print("🧪 Login Test Script")
    print("="*80)
    print()
    
    # Test luke login
    print("Test 1: User 'luke'")
    print("="*80)
    test_login("luke", "tocharian!")
    
    print("\n" + "="*80)
    print("\nTest 2: User 'admin' (for comparison)")
    print("="*80)
    test_login("admin", "admin")  # Assuming default admin password
    
    print("\n" + "="*80)
    print("✅ Tests complete")
    print("="*80)

