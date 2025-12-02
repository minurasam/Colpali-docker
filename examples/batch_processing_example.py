"""
Example usage of SharePoint to Blob batch processing with duplicate detection.

This script demonstrates:
1. Basic batch processing with tracking
2. Duplicate detection using content hashing
3. Resume capability for failed transfers
4. Statistics and monitoring
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from utils import SharePointToBlobUploader, FileTracker

# Load environment variables
load_dotenv()


def example_1_basic_batch_processing():
    """Example 1: Basic batch processing with duplicate detection"""
    print("\n" + "="*60)
    print("Example 1: Basic Batch Processing with Duplicate Detection")
    print("="*60)

    uploader = SharePointToBlobUploader(
        sharepoint_site_url=os.getenv("SHAREPOINT_SITE_URL"),
        sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
        sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
        blob_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
        blob_container_name=os.getenv("BLOB_CONTAINER_NAME"),
        enable_tracking=True,  # Enable tracking for duplicate detection
        tracking_db_path="file_tracking.db"
    )

    # Transfer files with duplicate detection
    results = uploader.transfer_files(
        sharepoint_folder_path=os.getenv("SHAREPOINT_FOLDER_PATH"),
        blob_folder_prefix=os.getenv("BLOB_FOLDER_PREFIX"),
        file_extensions=[".pdf", ".docx"],
        skip_duplicates=True  # Skip files that already exist
    )

    # Print results
    print(f"\nTransfer Results:")
    for result in results:
        status_icon = "✓" if result['status'] == 'success' else "✗" if result['status'] == 'failed' else "⊘"
        print(f"{status_icon} {result['file_name']}: {result['status']}")
        if result['status'] == 'skipped':
            print(f"  Reason: {result.get('reason')} (existing: {result.get('existing_blob_url')})")
        elif result['status'] == 'failed':
            print(f"  Error: {result.get('error')}")

    # Get statistics
    stats = uploader.get_tracking_stats()
    print(f"\n\nTracking Statistics:")
    print(f"Total files tracked: {stats['total']}")
    for status, info in stats['by_status'].items():
        print(f"  {status}: {info['count']} files ({info['total_size'] / 1024 / 1024:.2f} MB)")


def example_2_check_for_duplicates_before_upload():
    """Example 2: Check for duplicates before uploading"""
    print("\n" + "="*60)
    print("Example 2: Pre-check for Duplicates")
    print("="*60)

    tracker = FileTracker("file_tracking.db")

    # Example: Check if a file would be a duplicate
    test_file_path = "test_document.pdf"

    if os.path.exists(test_file_path):
        file_hash = tracker.calculate_file_hash(test_file_path)
        print(f"\nFile hash: {file_hash}")

        existing = tracker.file_exists(file_hash)
        if existing:
            print(f"⚠ This file is a duplicate!")
            print(f"  Original: {existing['file_name']}")
            print(f"  Blob URL: {existing['blob_url']}")
            print(f"  Uploaded: {existing['completion_timestamp']}")
        else:
            print("✓ This file is unique (not a duplicate)")
    else:
        print(f"Test file '{test_file_path}' not found. Skipping duplicate check example.")


def example_3_resume_failed_transfers():
    """Example 3: Resume failed transfers"""
    print("\n" + "="*60)
    print("Example 3: Resume Failed Transfers")
    print("="*60)

    uploader = SharePointToBlobUploader(
        sharepoint_site_url=os.getenv("SHAREPOINT_SITE_URL"),
        sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
        sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
        blob_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
        blob_container_name=os.getenv("BLOB_CONTAINER_NAME"),
        enable_tracking=True,
        tracking_db_path="file_tracking.db"
    )

    # Retry failed files (up to 3 retries)
    retry_results = uploader.retry_failed_files(
        sharepoint_folder_path=os.getenv("SHAREPOINT_FOLDER_PATH"),
        blob_folder_prefix=os.getenv("BLOB_FOLDER_PREFIX"),
        max_retries=3
    )

    if retry_results:
        print(f"\nRetried {len(retry_results)} files:")
        for result in retry_results:
            status_icon = "✓" if result['status'] == 'success' else "✗"
            print(f"{status_icon} {result['file_name']}: {result['status']}")
            if result['status'] == 'failed':
                print(f"  Error: {result.get('error')}")
    else:
        print("\n✓ No failed files to retry")


def example_4_process_in_batches():
    """Example 4: Process large number of files in batches"""
    print("\n" + "="*60)
    print("Example 4: Batch Processing with Resume")
    print("="*60)

    uploader = SharePointToBlobUploader(
        sharepoint_site_url=os.getenv("SHAREPOINT_SITE_URL"),
        sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
        sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
        blob_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
        blob_container_name=os.getenv("BLOB_CONTAINER_NAME"),
        enable_tracking=True,
        tracking_db_path="file_tracking.db"
    )

    # Process in batches of 10 files at a time
    # Automatically resumes failed files from previous runs
    batch_result = uploader.process_batch(
        sharepoint_folder_path=os.getenv("SHAREPOINT_FOLDER_PATH"),
        blob_folder_prefix=os.getenv("BLOB_FOLDER_PREFIX"),
        file_extensions=[".pdf"],
        batch_size=10,  # Process 10 files per batch
        resume_failed=True  # Retry failed files
    )

    print(f"\nBatch Processing Complete:")
    print(f"Status: {batch_result['status']}")
    print(f"Total files: {batch_result['total_files']}")
    print(f"Files processed: {batch_result['files_processed']}")

    print(f"\nStatistics:")
    stats = batch_result['statistics']
    for status, info in stats['by_status'].items():
        print(f"  {status}: {info['count']} files")


def example_5_monitoring_and_statistics():
    """Example 5: Monitor processing status and get statistics"""
    print("\n" + "="*60)
    print("Example 5: Monitoring and Statistics")
    print("="*60)

    tracker = FileTracker("file_tracking.db")

    # Get overall statistics
    stats = tracker.get_statistics()

    print(f"\nDatabase Statistics:")
    print(f"Total files tracked: {stats['total']}")
    print(f"\nBreakdown by status:")

    for status, info in stats['by_status'].items():
        count = info['count']
        size_mb = info['total_size'] / 1024 / 1024
        print(f"\n  {status.upper()}:")
        print(f"    Count: {count}")
        print(f"    Total Size: {size_mb:.2f} MB")

    # Get pending files
    pending = tracker.get_pending_files(limit=5)
    if pending:
        print(f"\n\nPending Files (showing first 5):")
        for file in pending:
            print(f"  - {file['file_name']} ({file['file_size'] / 1024:.1f} KB)")

    # Get failed files
    failed = tracker.get_failed_files(max_retries=3)
    if failed:
        print(f"\n\nFailed Files (retry < 3):")
        for file in failed:
            print(f"  - {file['file_name']} (retries: {file['retry_count']})")
            print(f"    Error: {file['error_message']}")


def example_6_reset_and_reprocess():
    """Example 6: Reset processing status and reprocess"""
    print("\n" + "="*60)
    print("Example 6: Reset and Reprocess")
    print("="*60)

    tracker = FileTracker("file_tracking.db")

    # Reset files stuck in 'processing' status
    # (useful if a previous run was interrupted)
    tracker.reset_processing_files()

    print("✓ Reset files stuck in 'processing' status")

    # Get counts
    pending = tracker.get_pending_files()
    print(f"\nFiles ready to process: {len(pending)}")


def run_all_examples():
    """Run all examples"""
    print("\n")
    print("="*60)
    print("SharePoint to Blob - Batch Processing Examples")
    print("="*60)

    try:
        # Run examples in order
        example_1_basic_batch_processing()
        example_2_check_for_duplicates_before_upload()
        example_3_resume_failed_transfers()
        example_4_process_in_batches()
        example_5_monitoring_and_statistics()
        example_6_reset_and_reprocess()

        print("\n" + "="*60)
        print("All examples completed!")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\n✗ Error running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Check if environment variables are set
    required_vars = [
        "SHAREPOINT_SITE_URL",
        "SHAREPOINT_CLIENT_ID",
        "SHAREPOINT_CLIENT_SECRET",
        "AZURE_STORAGE_CONNECTION_STRING",
        "BLOB_CONTAINER_NAME",
    ]

    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print("⚠ Warning: Missing environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\nPlease set these in your .env file before running.")
        print("Running examples that don't require SharePoint/Azure connection...\n")

        # Only run examples that work without connection
        example_5_monitoring_and_statistics()
        example_6_reset_and_reprocess()
    else:
        # Run all examples
        run_all_examples()
