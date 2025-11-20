#!/usr/bin/env python3
"""
Test script for ColPali API
Usage: python test_api.py <API_URL> <PDF_FILE>
Example: python test_api.py http://localhost:8000 sample.pdf
"""

import sys
import requests
import json
from pathlib import Path

def test_health(base_url):
    """Test health endpoint"""
    print("Testing /health endpoint...")
    response = requests.get(f"{base_url}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200

def test_ingest_pdf(base_url, pdf_path):
    """Test PDF ingestion"""
    print(f"\nTesting /ingest/pdf endpoint with {pdf_path}...")

    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        return None

    with open(pdf_path, 'rb') as f:
        files = {'file': (Path(pdf_path).name, f, 'application/pdf')}
        response = requests.post(f"{base_url}/ingest/pdf", files=files)

    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        return data['document_id']
    else:
        print(f"Error: {response.text}")
        return None

def test_ingest_image(base_url, image_path):
    """Test image ingestion"""
    print(f"\nTesting /ingest/image endpoint with {image_path}...")

    if not Path(image_path).exists():
        print(f"Error: File not found: {image_path}")
        return None

    # Determine content type
    ext = Path(image_path).suffix.lower()
    content_types = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.bmp': 'image/bmp',
        '.tiff': 'image/tiff',
        '.webp': 'image/webp'
    }
    content_type = content_types.get(ext, 'application/octet-stream')

    with open(image_path, 'rb') as f:
        files = {'file': (Path(image_path).name, f, content_type)}
        response = requests.post(f"{base_url}/ingest/image", files=files)

    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        return data['document_id']
    else:
        print(f"Error: {response.text}")
        return None

def test_list_documents(base_url):
    """Test listing documents"""
    print("\nTesting /documents endpoint...")
    response = requests.get(f"{base_url}/documents")
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        return data
    else:
        print(f"Error: {response.text}")
        return None

def test_stats(base_url):
    """Test stats endpoint"""
    print("\nTesting /stats endpoint...")
    response = requests.get(f"{base_url}/stats")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200

def test_delete_document(base_url, document_id):
    """Test document deletion"""
    print(f"\nTesting DELETE /document/{document_id} endpoint...")
    response = requests.delete(f"{base_url}/document/{document_id}")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_api.py <API_URL> [PDF_FILE|IMAGE_FILE]")
        print("Example: python test_api.py http://localhost:8000 sample.pdf")
        sys.exit(1)

    base_url = sys.argv[1].rstrip('/')
    file_path = sys.argv[2] if len(sys.argv) > 2 else None

    print("=" * 60)
    print("ColPali API Test Suite")
    print("=" * 60)
    print(f"API URL: {base_url}")

    # Test health
    if not test_health(base_url):
        print("\nHealth check failed! Exiting...")
        sys.exit(1)

    # Test ingestion if file provided
    document_id = None
    if file_path:
        ext = Path(file_path).suffix.lower()
        if ext == '.pdf':
            document_id = test_ingest_pdf(base_url, file_path)
        elif ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp']:
            document_id = test_ingest_image(base_url, file_path)
        else:
            print(f"\nUnsupported file type: {ext}")

    # Test listing documents
    test_list_documents(base_url)

    # Test stats
    test_stats(base_url)

    # Test deletion if we ingested a document
    if document_id:
        response = input(f"\nDelete document {document_id}? (y/n): ")
        if response.lower() == 'y':
            test_delete_document(base_url, document_id)
            # List documents again to confirm deletion
            test_list_documents(base_url)

    print("\n" + "=" * 60)
    print("Test suite completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
