# SharePoint to Azure Blob Storage Sync

A simplified Python utility for syncing files from SharePoint to Azure Blob Storage with SQLite-based file tracking and duplicate detection.

## Features

- **SharePoint Integration**: Download files from SharePoint using Azure AD app credentials
- **Azure Blob Storage**: Upload files to Azure Blob Storage using SAS URLs
- **SQLite File Tracking**: Track all files in a local SQLite database for:
  - Duplicate detection (content-based using SHA256 hashing)
  - Upload status tracking (pending, completed, failed)
  - Metadata storage (file size, timestamps, blob URLs)
- **Automatic Duplicate Prevention**: Skip files that have already been uploaded based on content hash
- **File Type Filtering**: Filter by file extensions (e.g., .pdf, .docx, .xlsx)

## Architecture

```
SharePoint → Download → Hash Check → Upload to Blob → Update SQLite DB
                            ↓
                    (Skip if duplicate)
```

## Prerequisites

1. Azure AD App Registration with SharePoint permissions
2. Azure Blob Storage account with SAS URL
3. Python 3.7+

## Required Environment Variables

Create a `.env` file in the project root:

```env
# SharePoint Configuration
CLIENT_ID=your-azure-ad-client-id
CLIENT_SECRET=your-azure-ad-client-secret
SITE_URL=https://yourtenant.sharepoint.com/sites/yoursite
DRIVE_PATH=/Shared Documents/YourFolder

# Azure Blob Storage
CONTAINER_SAS_URL=https://account.blob.core.windows.net/container?sv=...
```

## Installation

Install required dependencies:

```bash
pip install -r requirements.txt
```

Required packages:
- `azure-storage-blob` - Azure Blob Storage SDK
- `Office365-REST-Python-Client` - SharePoint integration
- `python-dotenv` - Environment variable management
- `sqlite3` - (Built into Python, no installation needed)

## Usage

### Command Line

Run the sync script directly:

```bash
python utils/sync_sharepoint.py
```

Or:

```bash
python -m utils.sync_sharepoint
```

### Python API

```python
from utils.sharepoint_sync import SharePointBlobSync

# Initialize sync
sync = SharePointBlobSync(
    tracking_db_path="file_tracking.db"  # SQLite database path
)

# Sync files
results = sync.sync_files(
    file_extensions=[".pdf", ".docx", ".xlsx"],  # Filter by extensions
    skip_duplicates=True  # Skip files already in database
)

# Print results
for result in results:
    if result['status'] == 'success':
        print(f"Uploaded: {result['file_name']}")
    elif result['status'] == 'skipped':
        print(f"Skipped (duplicate): {result['file_name']}")
    else:
        print(f"Failed: {result['file_name']} - {result.get('error')}")

# Get statistics
stats = sync.get_stats()
print(f"Total files: {stats['total']}")
print(f"By status: {stats['by_status']}")
```

## SQLite Database Schema

The `file_tracking.db` SQLite database contains:

```sql
CREATE TABLE file_tracking (
    file_id TEXT PRIMARY KEY,              -- Unique file identifier
    file_name TEXT NOT NULL,               -- Original filename
    sharepoint_path TEXT NOT NULL,         -- SharePoint URL
    file_hash TEXT NOT NULL UNIQUE,        -- SHA256 content hash
    file_size INTEGER,                     -- File size in bytes
    sharepoint_modified TEXT,              -- Last modified in SharePoint
    upload_timestamp TEXT,                 -- When uploaded to blob
    status TEXT DEFAULT 'pending',         -- pending, completed, failed
    blob_url TEXT,                         -- Azure Blob URL
    blob_name TEXT,                        -- Blob name in storage
    error_message TEXT,                    -- Error if failed
    retry_count INTEGER DEFAULT 0          -- Number of retry attempts
);
```

### Viewing the Database

You can view the SQLite database using any SQLite client:

```bash
# Using sqlite3 command line
sqlite3 file_tracking.db

# Query examples
SELECT * FROM file_tracking WHERE status = 'completed';
SELECT COUNT(*) FROM file_tracking;
SELECT status, COUNT(*) FROM file_tracking GROUP BY status;
```

## How It Works

1. **Connect to SharePoint**: Uses Azure AD client credentials to authenticate
2. **List Files**: Retrieves files from specified SharePoint folder/drive
3. **Download**: Downloads each file to a temporary directory
4. **Hash Calculation**: Calculates SHA256 hash of file content
5. **Duplicate Check**: Queries SQLite database for existing hash
6. **Upload**: If not duplicate, uploads to Azure Blob Storage
7. **Track**: Records file metadata, blob URL, and status in SQLite
8. **Cleanup**: Removes temporary files after upload

## Duplicate Detection

Files are identified as duplicates based on **content hash** (SHA256), not filename:
- Same file with different names = duplicate (skipped)
- Different files with same name = both uploaded
- Modified file = new hash, uploaded as new file

## Migrating to Azure SQL

Currently uses SQLite for file tracking. To migrate to Azure SQL later:

1. Update the `FileTracker` class in [utils/pipeline_utils.py](utils/pipeline_utils.py)
2. Replace `sqlite3` with `pyodbc` or `sqlalchemy`
3. Update connection string from `.env`
4. Schema remains the same

Example Azure SQL connection:
```python
# In .env
AZURE_SQL_CONNECTION_STRING=Driver={ODBC Driver 17 for SQL Server};Server=tcp:...

# In code
import pyodbc
conn = pyodbc.connect(os.getenv('AZURE_SQL_CONNECTION_STRING'))
```

## File Structure

```
colpali-docker/
├── utils/
│   ├── pipeline_utils.py          # Core sync and tracking logic
│   ├── sharepoint_sync.py         # Main sync wrapper
│   └── sync_sharepoint.py         # Entry point script
├── file_tracking.db               # SQLite database (auto-created)
├── .env                           # Environment variables
├── requirements.txt               # Python dependencies
└── SHAREPOINT_SYNC_README.md     # This file
```

## Troubleshooting

### Authentication Errors
- Verify `CLIENT_ID` and `CLIENT_SECRET` are correct
- Ensure Azure AD app has SharePoint API permissions
- Check `SITE_URL` format: `https://tenant.sharepoint.com/sites/sitename`

### Blob Storage Errors
- Verify SAS URL is valid and not expired
- Check SAS token has write permissions (`sp=rwdlactfx`)
- Ensure container exists

### Database Locked
- Close any SQLite database viewers
- Only one process should write to SQLite at a time

### Files Not Syncing
- Check `DRIVE_PATH` is correct (e.g., `/Shared Documents` or `/ETL_Documents`)
- Verify file extensions match filter (case-insensitive)
- Check SharePoint permissions

## Performance Considerations

- Files are downloaded to temporary storage, then uploaded
- Large files may take time to hash and upload
- SQLite performs well for thousands of files
- For millions of files, consider migrating to Azure SQL

## Security Notes

- Never commit `.env` file to version control
- SAS URLs contain credentials - keep them secure
- SQLite database contains file metadata - protect accordingly
- Client secrets should be rotated regularly

## Future Enhancements

Planned for later implementation:
- Batch processing with configurable batch sizes
- Retry mechanism for failed uploads
- Azure SQL migration
- Delta sync (only new/modified files)
- Multi-threaded uploads
- Progress bars and detailed logging
- Email notifications on completion/failure
