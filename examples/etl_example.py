"""
Example Usage of ColPali ETL Pipeline

This script demonstrates how to use the ETL pipeline to:
1. Download files from SharePoint
2. Process with ColPali embeddings
3. Upload to Azure Blob Storage
4. Store vectors in Qdrant
5. Track metadata in SQLite
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from etl import ETLPipeline, get_config
from etl.utils import SQLiteMetadataStore


def example_1_basic_pipeline():
    """Example 1: Initialize and check pipeline health"""
    print("\n" + "="*60)
    print("Example 1: Basic Pipeline Initialization")
    print("="*60)

    # Initialize pipeline
    pipeline = ETLPipeline()
    print("✓ Pipeline initialized successfully")

    # Get configuration
    config = get_config()
    print(f"\nConfiguration:")
    print(f"  SharePoint: {config.sharepoint.site_url}")
    print(f"  Drive Path: {config.sharepoint.drive_path}")
    print(f"  Blob Container: {config.blob_storage.blob_folder_prefix}")
    print(f"  Qdrant Collection: {config.qdrant.collection_name}")
    print(f"  Device: {config.model.device}")

    # Get statistics
    stats = pipeline.get_statistics()
    print(f"\nCurrent Statistics:")
    print(f"  Total files tracked: {stats['files']}")
    print(f"  Total embeddings: {stats['embeddings']['total']}")


def example_2_process_single_file():
    """Example 2: Process a single file from SharePoint"""
    print("\n" + "="*60)
    print("Example 2: Process Single File")
    print("="*60)

    pipeline = ETLPipeline()

    # Example SharePoint file
    sharepoint_file = {
        "name": "sample_document.pdf",
        "server_relative_url": "/sites/FortiMind/ETL_Documents/sample_document.pdf",
        "size": 1024000
    }

    print(f"\nProcessing file: {sharepoint_file['name']}")
    print(f"  SharePoint URL: {sharepoint_file['server_relative_url']}")

    # Note: This is a demonstration. In practice, you would:
    # 1. Download the file from SharePoint
    # 2. Calculate hash
    # 3. Call process_file

    # For this example, let's show how to check if file exists
    from etl.utils import FileHasher

    # Simulate file hash (in reality, calculate from downloaded file)
    # file_hash = FileHasher.calculate_hash(local_path)

    print("\nFile would be:")
    print("  1. Downloaded from SharePoint")
    print("  2. Converted to images (if PDF)")
    print("  3. Embedded with ColPali")
    print("  4. Uploaded to Blob Storage")
    print("  5. Vectors stored in Qdrant")
    print("  6. Metadata saved in SQLite")


def example_3_batch_processing():
    """Example 3: Batch processing multiple files"""
    print("\n" + "="*60)
    print("Example 3: Batch Processing")
    print("="*60)

    pipeline = ETLPipeline()

    # Example file list from SharePoint
    files_to_process = [
        {
            "name": "document1.pdf",
            "server_relative_url": "/sites/FortiMind/ETL_Documents/document1.pdf",
            "size": 1024000
        },
        {
            "name": "document2.pdf",
            "server_relative_url": "/sites/FortiMind/ETL_Documents/document2.pdf",
            "size": 2048000
        },
        {
            "name": "image1.png",
            "server_relative_url": "/sites/FortiMind/ETL_Documents/image1.png",
            "size": 512000
        }
    ]

    print(f"\nBatch processing {len(files_to_process)} files:")
    for i, file_info in enumerate(files_to_process, 1):
        print(f"  {i}. {file_info['name']} ({file_info['size'] / 1024:.1f} KB)")

    # Process batch (commented out for example)
    # result = pipeline.process_batch(
    #     file_list=files_to_process,
    #     skip_duplicates=True
    # )

    # print(f"\nResults:")
    # print(f"  Batch ID: {result['batch_id']}")
    # print(f"  Successful: {result['successful']}")
    # print(f"  Failed: {result['failed']}")
    # print(f"  Skipped: {result['skipped']}")


def example_4_query_metadata():
    """Example 4: Query metadata from database"""
    print("\n" + "="*60)
    print("Example 4: Query Metadata")
    print("="*60)

    store = SQLiteMetadataStore("etl_tracking.db")

    # Get statistics
    stats = store.get_statistics()

    print("\nDatabase Statistics:")
    print(f"\nFiles by Status:")
    for status, info in stats['files'].items():
        size_mb = info['total_size'] / 1024 / 1024
        print(f"  {status}: {info['count']} files ({size_mb:.2f} MB)")

    print(f"\nEmbeddings:")
    print(f"  Total: {stats['embeddings']['total']}")
    print(f"  Uploaded to Qdrant: {stats['embeddings']['uploaded']}")

    print(f"\nBatches:")
    print(f"  Total batches: {stats['batches']['total']}")
    print(f"  Successful files: {stats['batches']['successful_files']}")
    print(f"  Failed files: {stats['batches']['failed_files']}")


def example_5_duplicate_detection():
    """Example 5: Duplicate detection"""
    print("\n" + "="*60)
    print("Example 5: Duplicate Detection")
    print("="*60)

    store = SQLiteMetadataStore("etl_tracking.db")
    from etl.utils import FileHasher

    # Example: Check if file already processed
    # In reality, you'd calculate hash from actual file
    example_hash = "abc123def456789"

    existing = store.file_exists(example_hash)

    if existing:
        print(f"\n✓ File already processed:")
        print(f"  File ID: {existing['file_id']}")
        print(f"  File Name: {existing['file_name']}")
        print(f"  Status: {existing['status']}")
        print(f"  Blob URL: {existing.get('blob_url', 'N/A')}")
        print(f"  Processed: {existing.get('upload_timestamp', 'N/A')}")
    else:
        print(f"\n⊘ File not found in database")
        print("  This file would be processed as new")


def example_6_list_sharepoint_files():
    """Example 6: List files from SharePoint"""
    print("\n" + "="*60)
    print("Example 6: List SharePoint Files")
    print("="*60)

    from office365.sharepoint.client_context import ClientContext
    from office365.runtime.auth.client_credential import ClientCredential

    config = get_config()

    # Initialize SharePoint client
    credentials = ClientCredential(
        config.sharepoint.client_id,
        config.sharepoint.client_secret
    )
    ctx = ClientContext(config.sharepoint.site_url).with_credentials(credentials)

    print(f"\nConnecting to SharePoint:")
    print(f"  Site: {config.sharepoint.site_url}")
    print(f"  Path: {config.sharepoint.drive_path}")

    try:
        # List files in folder
        folder = ctx.web.get_folder_by_server_relative_url(config.sharepoint.drive_path)
        files = folder.files
        ctx.load(files)
        ctx.execute_query()

        print(f"\n✓ Found {len(files)} files:")
        for i, file in enumerate(files[:10], 1):  # Show first 10
            size_kb = file.properties.get("Length", 0) / 1024
            print(f"  {i}. {file.properties['Name']} ({size_kb:.1f} KB)")

        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more files")

    except Exception as e:
        print(f"\n✗ Error listing files: {e}")


def example_7_using_api():
    """Example 7: Using the REST API"""
    print("\n" + "="*60)
    print("Example 7: Using REST API")
    print("="*60)

    print("\n1. Start the API server:")
    print("   python -m etl.api")
    print("   or")
    print("   uvicorn etl.api:app --host 0.0.0.0 --port 8001")

    print("\n2. Check health:")
    print("   curl http://localhost:8001/health")

    print("\n3. Process single file:")
    print("""   curl -X POST "http://localhost:8001/process/file" \\
     -H "Content-Type: application/json" \\
     -d '{
       "sharepoint_url": "/sites/FortiMind/ETL_Documents/doc.pdf",
       "skip_if_duplicate": true
     }'""")

    print("\n4. Process batch:")
    print("""   curl -X POST "http://localhost:8001/process/batch" \\
     -H "Content-Type: application/json" \\
     -d '{
       "files": [
         {
           "name": "doc1.pdf",
           "server_relative_url": "/sites/FortiMind/ETL_Documents/doc1.pdf",
           "size": 1024000
         }
       ],
       "skip_duplicates": true
     }'""")

    print("\n5. Get statistics:")
    print("   curl http://localhost:8001/statistics")

    print("\n6. View API documentation:")
    print("   Open browser: http://localhost:8001/docs")


def main():
    """Run all examples"""
    print("\n" + "="*60)
    print("ColPali ETL Pipeline - Example Usage")
    print("="*60)

    examples = [
        ("Basic Pipeline Initialization", example_1_basic_pipeline),
        ("Process Single File", example_2_process_single_file),
        ("Batch Processing", example_3_batch_processing),
        ("Query Metadata", example_4_query_metadata),
        ("Duplicate Detection", example_5_duplicate_detection),
        ("List SharePoint Files", example_6_list_sharepoint_files),
        ("Using REST API", example_7_using_api),
    ]

    print("\nAvailable Examples:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"  {i}. {name}")

    print("\nRunning examples...\n")

    # Run safe examples (that don't require actual files)
    for name, func in [examples[0], examples[1], examples[2], examples[3], examples[4], examples[6]]:
        try:
            func()
        except Exception as e:
            print(f"\n✗ Example failed: {e}")

    print("\n" + "="*60)
    print("Examples completed!")
    print("="*60)


if __name__ == "__main__":
    main()
