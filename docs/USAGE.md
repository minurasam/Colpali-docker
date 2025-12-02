# SharePoint to Blob Sync - Usage Guide

Quick start guide for syncing files from FortiMind SharePoint to Azure Blob Storage.

## Quick Start

### 1. Configure Environment Variables

Copy your `.env` file and ensure these variables are set:

```bash
# SharePoint
TENANT_ID=your-tenant-id
CLIENT_ID=your-app-client-id
CLIENT_SECRET=your-app-secret
SITE_URL=https://codicetechcom.sharepoint.com/sites/FortiMind
DRIVE_PATH=Shared Documents
SITE_NAME=FortiMind

# Azure Blob Storage
CONTAINER_SAS_URL=https://yourstorageaccount.blob.core.windows.net/yourcontainer?sv=...

# Optional
BLOB_FOLDER_PREFIX=sharepoint-docs

# Qdrant (for ColPali integration)
QDRANT_URL=your-qdrant-url
QDRANT_API_KEY=your-api-key
COLLECTION_NAME=colpali_embeddings
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Sync

#### Option A: Simple Command Line

```bash
python sharepoint_sync.py
```

This will:
- Connect to your SharePoint site
- Sync PDF files from the configured drive path
- Upload to Azure Blob Storage using SAS URL
- Track duplicates automatically
- Show progress and statistics

#### Option B: Python Script (Custom)

```python
from sharepoint_sync import SharePointBlobSync

# Initialize
sync = SharePointBlobSync(enable_tracking=True)

# Sync all PDF files
results = sync.sync_files(
    file_extensions=[".pdf"],
    skip_duplicates=True
)

# Print results
for result in results:
    print(f"{result['file_name']}: {result['status']}")
```

---

## Common Use Cases

### Sync Specific File Types

```python
from sharepoint_sync import SharePointBlobSync

sync = SharePointBlobSync()

# Sync only PDFs
results = sync.sync_files(file_extensions=[".pdf"])

# Sync PDFs and Word documents
results = sync.sync_files(file_extensions=[".pdf", ".docx"])

# Sync all files
results = sync.sync_files()
```

### Batch Processing (Large Numbers of Files)

```python
sync = SharePointBlobSync()

# Process in batches of 10 files
batch_result = sync.batch_sync(
    batch_size=10,
    file_extensions=[".pdf"],
    resume_failed=True
)

print(f"Processed: {batch_result['files_processed']}/{batch_result['total_files']}")
```

### Check Statistics

```python
sync = SharePointBlobSync()

# Get statistics
stats = sync.get_stats()

print(f"Total files: {stats['total']}")
for status, info in stats['by_status'].items():
    print(f"{status}: {info['count']} files")
```

### Retry Failed Files

```python
sync = SharePointBlobSync()

# Retry files that failed (up to 3 attempts)
retry_results = sync.retry_failed(max_retries=3)

for result in retry_results:
    print(f"{result['file_name']}: {result['status']}")
```

### Check for Duplicates Before Upload

```python
from pipeline_utils import FileTracker

tracker = FileTracker("file_tracking.db")

# Check if a file would be a duplicate
file_hash = tracker.calculate_file_hash("local_file.pdf")
existing = tracker.file_exists(file_hash)

if existing:
    print(f"Duplicate! Already uploaded as: {existing['file_name']}")
    print(f"Blob URL: {existing['blob_url']}")
else:
    print("File is unique, safe to upload")
```

---

## Output Examples

### Successful Sync

```
============================================================
SharePoint to Azure Blob Storage Sync
============================================================

SharePoint Site: https://codicetechcom.sharepoint.com/sites/FortiMind
Drive Path: Shared Documents
Blob Container: documents
Blob Account: https://youraccount.blob.core.windows.net

------------------------------------------------------------
Syncing PDF files...
------------------------------------------------------------

📊 Sync Results:
   Total files processed: 25
   ✅ Successful: 20
   ⊘ Skipped (duplicates): 3
   ❌ Failed: 2

📄 File Details:
   ✅ report_2024.pdf: success
   ✅ invoice_001.pdf: success
   ⊘ contract.pdf: skipped
      → Already exists: https://youraccount.blob.core.windows.net/documents/contract.pdf
   ✅ presentation.pdf: success
   ❌ corrupted_file.pdf: failed

📈 Tracking Statistics:
   Total files tracked: 150
   completed: 120 files (450.5 MB)
   failed: 5 files (12.3 MB)
   pending: 25 files (78.9 MB)

============================================================
✅ Sync completed successfully!
============================================================
```

---

## Environment Variable Reference

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `TENANT_ID` | No | Azure AD Tenant ID | `12345678-1234-...` |
| `CLIENT_ID` | **Yes** | Azure AD App Client ID | `abcdef12-3456-...` |
| `CLIENT_SECRET` | **Yes** | Azure AD App Client Secret | `secretkey123~...` |
| `SITE_URL` | **Yes** | SharePoint site URL | `https://codicetechcom.sharepoint.com/sites/FortiMind` |
| `DRIVE_PATH` | No | SharePoint folder path | `Shared Documents` (default) |
| `SITE_NAME` | No | Site name | `FortiMind` |
| `CONTAINER_SAS_URL` | **Yes** | Azure Blob Container SAS URL | `https://account.blob.core.windows.net/container?sv=...` |
| `BLOB_FOLDER_PREFIX` | No | Prefix for blob names | `sharepoint-docs` |

---

## Troubleshooting

### Error: "Missing required environment variables"

**Solution**: Check your `.env` file. Ensure `CLIENT_ID`, `CLIENT_SECRET`, `SITE_URL`, and `CONTAINER_SAS_URL` are set.

```bash
# Check if .env file exists
ls -la .env

# View variables (be careful not to commit!)
cat .env
```

### Error: "Access Denied" or "Unauthorized"

**Solution**:
1. Verify Azure AD app has SharePoint permissions
2. Check Client ID and Secret are correct
3. Ensure SAS URL has read/write permissions
4. Check SAS URL hasn't expired

### Error: "Container Not Found"

**Solution**:
1. Check the SAS URL is correct
2. Verify the container name in the URL matches your container
3. Ensure the SAS token has container-level access

### Error: "Database is locked"

**Solution**:
1. Close any other processes accessing the database
2. Use a different database file per process:
   ```python
   sync = SharePointBlobSync(tracking_db_path=f"tracking_{os.getpid()}.db")
   ```

### Files Stuck in "Processing" Status

**Solution**:
```python
from pipeline_utils import FileTracker

tracker = FileTracker("file_tracking.db")
tracker.reset_processing_files()
print("✓ Reset stuck files")
```

---

## Integration with ColPali

After syncing files to Blob Storage, you can process them with ColPali:

```python
from sharepoint_sync import SharePointBlobSync
import requests

# Step 1: Sync files from SharePoint to Blob
sync = SharePointBlobSync()
results = sync.sync_files(file_extensions=[".pdf"])

# Step 2: Process successful uploads with ColPali API
colpali_api = "http://localhost:8000"

for result in results:
    if result['status'] == 'success':
        blob_url = result['blob_url']
        file_name = result['file_name']

        # Download from blob and send to ColPali
        # (You'll need to implement blob download)
        print(f"Processing {file_name} with ColPali...")

        # Update tracking with vector IDs after embedding
        if 'file_hash' in result:
            file_hash = result['file_hash'].replace('...', '')  # Get full hash
            sync.tracker.update_status(
                file_hash=file_hash,
                status="completed",
                vector_ids=["vec_123", "vec_124"]  # From ColPali/Qdrant
            )
```

---

## Advanced Usage

### Custom Sync Logic

```python
from sharepoint_sync import SharePointBlobSync

class CustomSync(SharePointBlobSync):
    def sync_with_preprocessing(self, file_extensions):
        """Custom sync with file preprocessing"""
        results = []

        # List files from SharePoint
        sp_files = self.uploader.list_sharepoint_files(
            self.drive_path,
            file_extensions
        )

        for file in sp_files:
            # Custom logic before upload
            if self.should_process(file):
                # Sync file
                result = self.uploader.transfer_files(...)
                results.append(result)

        return results

    def should_process(self, file_info):
        """Custom filtering logic"""
        # Skip files larger than 50MB
        if file_info['size'] > 50 * 1024 * 1024:
            return False

        # Skip files older than 30 days
        # ... add your logic

        return True

# Use custom sync
sync = CustomSync()
results = sync.sync_with_preprocessing([".pdf"])
```

### Parallel Processing (Advanced)

```python
from concurrent.futures import ThreadPoolExecutor
from sharepoint_sync import SharePointBlobSync

def sync_file_batch(batch_files):
    """Sync a batch of files"""
    sync = SharePointBlobSync(
        tracking_db_path=f"tracking_batch_{id(batch_files)}.db"
    )
    # Process batch...
    return results

# Split files into batches
batches = [files[i:i+10] for i in range(0, len(files), 10)]

# Process in parallel
with ThreadPoolExecutor(max_workers=3) as executor:
    results = executor.map(sync_file_batch, batches)
```

---

## Best Practices

1. **Always enable tracking** for production use
2. **Use batch processing** for large numbers of files
3. **Monitor statistics** regularly
4. **Backup tracking database** before major operations
5. **Set up logging** for production monitoring
6. **Use SAS URLs with minimal permissions** (only what's needed)
7. **Set SAS expiration dates** and rotate regularly

---

## Next Steps

- See [BATCH_PROCESSING.md](BATCH_PROCESSING.md) for detailed batch processing guide
- See [SHAREPOINT_BLOB_SETUP.md](SHAREPOINT_BLOB_SETUP.md) for Azure setup instructions
- Run `python batch_processing_example.py` for complete examples

---

## Support

For issues:
1. Check logs: `file_tracking.db` for status
2. Review error messages
3. Verify environment variables
4. Check Azure permissions (SharePoint + Blob Storage)
