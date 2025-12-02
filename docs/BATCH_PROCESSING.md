# Batch Processing & Duplicate Detection Guide

This guide explains how to use the advanced batch processing and duplicate detection features in the SharePoint to Blob pipeline.

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [How It Works](#how-it-works)
4. [File Tracking Database](#file-tracking-database)
5. [Duplicate Detection Strategy](#duplicate-detection-strategy)
6. [Usage Examples](#usage-examples)
7. [Resume Failed Transfers](#resume-failed-transfers)
8. [Monitoring & Statistics](#monitoring--statistics)
9. [Best Practices](#best-practices)

---

## Overview

The batch processing system provides production-ready file transfer capabilities with:

- **Content-based duplicate detection** using SHA-256 hashing
- **SQLite tracking database** for maintaining transfer history
- **Resume capability** for failed transfers
- **Batch processing** for handling large numbers of files
- **Detailed statistics** and monitoring

---

## Key Features

### 1. Duplicate Detection

**Problem**: Uploading the same file multiple times wastes bandwidth and storage.

**Solution**: Content-based hashing (SHA-256)
- Files with identical content have the same hash
- Detects duplicates even if filename changes
- Example: `report_v1.pdf` renamed to `report_final.pdf` → detected as duplicate

### 2. Batch Processing with Resume

**Problem**: Processing thousands of files can be interrupted by network issues, crashes, or timeouts.

**Solution**: SQLite tracking database
- Tracks status of each file (pending, processing, completed, failed)
- Resume from where you left off
- Retry failed files automatically

### 3. Multi-Level Tracking

Each file is tracked with:
- **File hash** (SHA-256 of content)
- **Processing status** (pending → processing → completed/failed)
- **Timestamps** (when created, modified, processed)
- **Blob URLs** and metadata
- **Error messages** and retry count

---

## How It Works

### Step-by-Step Flow

```
1. List files in SharePoint
   ↓
2. For each file:
   ↓
3. Download to temp directory
   ↓
4. Calculate content hash (SHA-256)
   ↓
5. Check if hash exists in database
   ↓
6. If duplicate → Skip (log existing blob URL)
   If new → Continue
   ↓
7. Update status to 'processing'
   ↓
8. Upload to Azure Blob Storage
   ↓
9. Update status to 'completed'
   ↓
10. Clean up temp file
```

### Error Handling

```
If upload fails:
  ↓
1. Update status to 'failed'
2. Increment retry count
3. Store error message
4. Continue with next file
  ↓
Later:
  ↓
5. Retry failed files (up to max retries)
6. Permanent failures are logged
```

---

## File Tracking Database

### Database Schema

```sql
CREATE TABLE file_tracking (
    file_id TEXT PRIMARY KEY,           -- Unique identifier
    file_name TEXT NOT NULL,            -- Original filename
    file_path TEXT NOT NULL,            -- SharePoint path
    file_hash TEXT NOT NULL UNIQUE,     -- SHA-256 hash (duplicate detection)
    file_size INTEGER,                  -- Size in bytes
    last_modified TEXT,                 -- Last modified timestamp
    processing_timestamp TEXT,          -- When processing started
    completion_timestamp TEXT,          -- When completed
    status TEXT DEFAULT 'pending',      -- pending/processing/completed/failed
    blob_url TEXT,                      -- Azure Blob URL
    blob_name TEXT,                     -- Name in blob storage
    vector_ids TEXT,                    -- Vector DB IDs (JSON array)
    error_message TEXT,                 -- Error if failed
    retry_count INTEGER DEFAULT 0,      -- Number of retries
    metadata TEXT                       -- Additional metadata (JSON)
);
```

### Status States

| Status | Description | Can Retry? |
|--------|-------------|------------|
| `pending` | Not yet processed | N/A |
| `processing` | Currently being processed | No |
| `completed` | Successfully transferred | No |
| `failed` | Transfer failed | Yes (up to max retries) |

---

## Duplicate Detection Strategy

### Multi-Level Approach

#### 1. Content Hash (Primary Method)
```python
# SHA-256 hash of file content
file_hash = tracker.calculate_file_hash("document.pdf")
# Result: "a3d5e8f2..." (64 characters)
```

**Pros:**
- Most reliable - same content = same hash
- Detects duplicates regardless of filename
- Catches renamed files

**Cons:**
- Requires downloading file first
- Computationally expensive for large files

#### 2. Quick Pre-Filter (Optional - Future Enhancement)

Before downloading, check:
- Filename + path
- File size
- Last modified timestamp

**Use case**: Skip obvious duplicates before expensive download.

### Example Scenarios

```python
# Scenario 1: Exact duplicate
Original:  "report.pdf" (hash: abc123...)
Duplicate: "report.pdf" (hash: abc123...)
Result:    ✓ Detected as duplicate

# Scenario 2: Renamed file
Original:  "report_v1.pdf" (hash: abc123...)
Renamed:   "report_final.pdf" (hash: abc123...)
Result:    ✓ Detected as duplicate (same content)

# Scenario 3: Modified content
Original:  "report.pdf" (hash: abc123...)
Modified:  "report.pdf" (hash: xyz789...)
Result:    ✗ Not a duplicate (different content)

# Scenario 4: Different files, same name
File A:    "invoice.pdf" (hash: aaa111...)
File B:    "invoice.pdf" (hash: bbb222...)
Result:    ✗ Not a duplicate (different content)
```

---

## Usage Examples

### Example 1: Basic Transfer with Duplicate Detection

```python
from pipeline_utils import SharePointToBlobUploader
import os
from dotenv import load_dotenv

load_dotenv()

uploader = SharePointToBlobUploader(
    sharepoint_site_url=os.getenv("SHAREPOINT_SITE_URL"),
    sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
    sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
    blob_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
    blob_container_name=os.getenv("BLOB_CONTAINER_NAME"),
    enable_tracking=True,  # Enable duplicate detection
    tracking_db_path="file_tracking.db"
)

# Transfer files
results = uploader.transfer_files(
    sharepoint_folder_path="Shared Documents/PDFs",
    blob_folder_prefix="documents",
    file_extensions=[".pdf"],
    skip_duplicates=True  # Skip duplicates
)

# Check results
for result in results:
    if result['status'] == 'skipped':
        print(f"⊘ Skipped duplicate: {result['file_name']}")
        print(f"  Existing blob: {result['existing_blob_url']}")
    elif result['status'] == 'success':
        print(f"✓ Uploaded: {result['file_name']}")
    elif result['status'] == 'failed':
        print(f"✗ Failed: {result['file_name']} - {result['error']}")
```

### Example 2: Batch Processing

```python
# Process in batches of 10 files
batch_result = uploader.process_batch(
    sharepoint_folder_path="Shared Documents/Reports",
    blob_folder_prefix="reports",
    file_extensions=[".pdf", ".docx"],
    batch_size=10,  # Process 10 at a time
    resume_failed=True  # Retry failed files
)

print(f"Total files: {batch_result['total_files']}")
print(f"Processed: {batch_result['files_processed']}")
```

### Example 3: Check for Duplicate Before Upload

```python
from pipeline_utils import FileTracker

tracker = FileTracker("file_tracking.db")

# Calculate hash of local file
file_hash = tracker.calculate_file_hash("local_document.pdf")

# Check if it's a duplicate
existing = tracker.file_exists(file_hash)

if existing:
    print(f"⚠ This file is a duplicate!")
    print(f"Original: {existing['file_name']}")
    print(f"Blob URL: {existing['blob_url']}")
else:
    print("✓ This file is unique")
```

### Example 4: Retry Failed Transfers

```python
# Retry all failed files (up to 3 retries each)
retry_results = uploader.retry_failed_files(
    sharepoint_folder_path="Shared Documents/PDFs",
    blob_folder_prefix="documents",
    max_retries=3
)

for result in retry_results:
    print(f"{result['file_name']}: {result['status']}")
```

---

## Resume Failed Transfers

### Automatic Resume

If a batch process is interrupted:

```python
# First run - processes 50 files, 5 fail, network interruption at file 30
uploader.transfer_files(...)
# Database state:
#   - 25 files: completed
#   - 5 files: failed
#   - 20 files: processing (stuck)

# Second run - automatically resumes
uploader.process_batch(...)
# What happens:
#   1. Resets 'processing' files to 'pending'
#   2. Retries failed files (if resume_failed=True)
#   3. Continues from where it left off
```

### Manual Retry

```python
# Get list of failed files
from pipeline_utils import FileTracker

tracker = FileTracker("file_tracking.db")
failed = tracker.get_failed_files(max_retries=3)

print(f"Found {len(failed)} failed files")
for file in failed:
    print(f"  - {file['file_name']} (retries: {file['retry_count']})")
    print(f"    Error: {file['error_message']}")

# Retry them
uploader.retry_failed_files(...)
```

---

## Monitoring & Statistics

### Get Overall Statistics

```python
stats = uploader.get_tracking_stats()

print(f"Total files: {stats['total']}")
for status, info in stats['by_status'].items():
    print(f"{status}: {info['count']} files ({info['total_size']/1024/1024:.2f} MB)")
```

**Example Output:**
```
Total files: 150
completed: 120 files (450.5 MB)
failed: 5 files (12.3 MB)
pending: 25 files (78.9 MB)
```

### Get Pending Files

```python
pending = tracker.get_pending_files(limit=10)

print(f"Next {len(pending)} files to process:")
for file in pending:
    print(f"  - {file['file_name']} ({file['file_size']/1024:.1f} KB)")
```

### Get Failed Files

```python
failed = tracker.get_failed_files(max_retries=3)

for file in failed:
    print(f"\nFile: {file['file_name']}")
    print(f"  Retries: {file['retry_count']}")
    print(f"  Error: {file['error_message']}")
    print(f"  Last attempt: {file['processing_timestamp']}")
```

---

## Best Practices

### 1. Enable Tracking for Production

```python
# ✓ Good - tracking enabled
uploader = SharePointToBlobUploader(
    ...,
    enable_tracking=True,
    tracking_db_path="production_tracking.db"
)

# ✗ Bad - no tracking (can't resume failures)
uploader = SharePointToBlobUploader(
    ...,
    enable_tracking=False
)
```

### 2. Use Batch Processing for Large Jobs

```python
# ✓ Good - process in batches
uploader.process_batch(
    batch_size=10,  # 10 files at a time
    resume_failed=True
)

# ✗ Bad - process all at once (no resume capability)
uploader.transfer_files(...)  # If it crashes at file 500, start from 0
```

### 3. Monitor Progress

```python
# Check statistics periodically
stats = uploader.get_tracking_stats()

# Calculate progress
total = stats['total']
completed = stats['by_status'].get('completed', {}).get('count', 0)
failed = stats['by_status'].get('failed', {}).get('count', 0)
pending = stats['by_status'].get('pending', {}).get('count', 0)

progress = (completed / total * 100) if total > 0 else 0

print(f"Progress: {progress:.1f}%")
print(f"Completed: {completed}, Failed: {failed}, Pending: {pending}")
```

### 4. Handle Permanent Failures

```python
# Files that failed after max retries
failed = tracker.get_failed_files(max_retries=3)

# Log these for manual review
import json
with open('failed_files.json', 'w') as f:
    json.dump(failed, f, indent=2)

print(f"⚠ {len(failed)} files need manual attention")
```

### 5. Backup Tracking Database

```python
import shutil
from datetime import datetime

# Periodic backup
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy(
    "file_tracking.db",
    f"backups/file_tracking_{timestamp}.db"
)
```

### 6. Clean Up Old Records (Optional)

```python
# After successful completion, optionally archive old records
import sqlite3

conn = sqlite3.connect("file_tracking.db")
cursor = conn.cursor()

# Archive completed files older than 30 days
cursor.execute("""
    DELETE FROM file_tracking
    WHERE status = 'completed'
    AND completion_timestamp < date('now', '-30 days')
""")

conn.commit()
conn.close()
```

---

## Performance Considerations

### Hash Calculation Performance

```python
# SHA-256 is fast but not instant
# For a 10MB PDF: ~50-100ms
# For a 100MB file: ~500ms-1s

# Optimization: Read in chunks (already implemented)
file_hash = tracker.calculate_file_hash(file_path)
```

### Database Query Performance

```python
# Indexes are automatically created for:
# - file_hash (duplicate lookups)
# - status (getting pending/failed files)
# - file_name (searching)

# For 10,000+ files, consider:
# 1. Periodic database vacuum
# 2. Archiving old completed records
# 3. Using PostgreSQL instead of SQLite
```

---

## Troubleshooting

### Issue: Database Locked

**Symptom**: `sqlite3.OperationalError: database is locked`

**Cause**: Multiple processes accessing database simultaneously

**Solution**:
```python
# Use different database per process
uploader = SharePointToBlobUploader(
    ...,
    tracking_db_path=f"file_tracking_process_{os.getpid()}.db"
)
```

### Issue: Files Stuck in 'Processing'

**Symptom**: Files never complete after crash

**Solution**:
```python
# Reset stuck files
tracker.reset_processing_files()
```

### Issue: Database Growing Too Large

**Symptom**: `file_tracking.db` is several GB

**Solution**:
```python
# Archive or delete old completed records
# See "Clean Up Old Records" in Best Practices
```

---

## Integration with Vector Databases

The tracking database includes a `vector_ids` field for storing vector database IDs:

```python
# After uploading to blob and generating embeddings
uploader.tracker.update_status(
    file_hash=file_hash,
    status="completed",
    blob_url=blob_url,
    vector_ids=["vec_123", "vec_124", "vec_125"]  # IDs from Qdrant/Pinecone
)

# Later: Delete vectors for a specific file
file_record = tracker.file_exists(file_hash)
vector_ids = json.loads(file_record['vector_ids'])

# Delete from vector DB
for vector_id in vector_ids:
    qdrant_client.delete(vector_id)
```

---

## Summary

The batch processing system provides:

✓ **Duplicate Detection**: Content-based hashing prevents re-uploading
✓ **Resume Capability**: Never lose progress due to failures
✓ **Detailed Tracking**: Know exactly what succeeded, failed, or is pending
✓ **Production Ready**: Handles errors gracefully, retries automatically
✓ **Scalable**: Process thousands of files efficiently

For complete examples, see [batch_processing_example.py](batch_processing_example.py).
