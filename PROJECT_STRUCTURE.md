# Project Structure

This document explains the organization of the ColPali Docker project with SharePoint to Blob Storage sync functionality.

## Directory Structure

```
colpali-docker/
├── .env                          # Environment variables (not in git)
├── .env.example                  # Environment template
├── .gitignore                    # Git ignore rules
├── README.md                     # Main project documentation
├── LICENSE                       # MIT License
├── requirements.txt              # Python dependencies
├── Dockerfile                    # Docker image configuration
├── docker-compose.yml            # Local development setup
├── docker-compose.cloud.yml      # Cloud deployment setup
│
├── api.py                        # Main ColPali FastAPI application
├── app.py                        # Alternative app entry point
├── test_api.py                   # API tests
├── sync_sharepoint.py            # Main entry point for SharePoint sync ⭐
│
├── utils/                        # Utility modules ⭐
│   ├── __init__.py              # Package initialization
│   ├── pipeline_utils.py        # Core sync utilities with tracking
│   └── sharepoint_sync.py       # SharePoint sync wrapper
│
├── examples/                     # Usage examples ⭐
│   └── batch_processing_example.py  # Batch processing examples
│
├── docs/                         # Documentation ⭐
│   ├── USAGE.md                 # Quick start guide
│   ├── BATCH_PROCESSING.md      # Batch processing details
│   ├── SHAREPOINT_BLOB_SETUP.md # Azure setup instructions
│   └── TESTING.md               # Testing guide
│
├── k8s/                          # Kubernetes manifests
│   ├── namespace.yaml
│   ├── colpali-deployment.yaml
│   ├── qdrant-deployment.yaml
│   └── ingress.yaml
│
├── embeddings/                   # Local embeddings storage
├── pdfs/                         # Local PDF storage
├── uploads/                      # API upload directory
└── qdrant_storage/               # Local Qdrant data
```

⭐ = New additions for SharePoint sync functionality

---

## Key Files Explained

### Root Directory

| File | Purpose |
|------|---------|
| `sync_sharepoint.py` | **Main entry point** - Run this to sync SharePoint to Blob |
| `api.py` | ColPali FastAPI server for document embedding |
| `requirements.txt` | All Python dependencies including SharePoint/Blob packages |
| `.env.example` | Template for environment variables |
| `Dockerfile` | Container image (Python 3.11-slim-bullseye) |

### utils/ Directory

**Core sync functionality**

| File | Purpose |
|------|---------|
| `__init__.py` | Package exports (FileTracker, SharePointToBlobUploader, etc.) |
| `pipeline_utils.py` | Main sync logic with:<br>• FileTracker (SQLite tracking)<br>• SharePointToBlobUploader (core uploader)<br>• Batch processing<br>• Duplicate detection |
| `sharepoint_sync.py` | Wrapper adapted for your environment variables:<br>• SharePointBlobSync class<br>• SAS URL parsing<br>• Simplified API |

### examples/ Directory

**Learn by example**

| File | Purpose |
|------|---------|
| `batch_processing_example.py` | Complete examples showing:<br>• Basic sync<br>• Duplicate detection<br>• Batch processing<br>• Retry failed files<br>• Statistics |

### docs/ Directory

**Comprehensive documentation**

| File | Purpose |
|------|---------|
| `USAGE.md` | **Start here!** Quick start guide |
| `BATCH_PROCESSING.md` | Technical deep dive into batch processing |
| `SHAREPOINT_BLOB_SETUP.md` | Azure AD and Blob Storage setup |
| `TESTING.md` | API testing guide |

---

## Usage Patterns

### 1. Quick Start (Command Line)

```bash
# Sync files from SharePoint to Blob
python sync_sharepoint.py
```

### 2. Python Script

```python
from utils import SharePointBlobSync

# Initialize
sync = SharePointBlobSync(enable_tracking=True)

# Sync PDF files
results = sync.sync_files(file_extensions=[".pdf"])
```

### 3. Advanced Batch Processing

```python
from utils import SharePointToBlobUploader

uploader = SharePointToBlobUploader(
    sharepoint_site_url="...",
    sharepoint_client_id="...",
    sharepoint_client_secret="...",
    blob_connection_string="...",
    blob_container_name="documents",
    enable_tracking=True
)

# Batch process with resume capability
batch_result = uploader.process_batch(
    sharepoint_folder_path="Shared Documents",
    batch_size=10,
    resume_failed=True
)
```

### 4. Run Examples

```bash
python examples/batch_processing_example.py
```

---

## Import Patterns

### From Root Directory Scripts

```python
# Import from utils package
from utils import (
    FileTracker,
    SharePointToBlobUploader,
    SharePointBlobSync
)
```

### From Examples Directory

```python
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import SharePointBlobSync
```

### From utils Package Itself

```python
# Within utils/ files, use relative imports
from .pipeline_utils import FileTracker
from .sharepoint_sync import SharePointBlobSync
```

---

## Data Storage

### File Tracking Database

```
file_tracking.db              # SQLite database (auto-created)
├── Tracks file status (pending/processing/completed/failed)
├── Stores content hashes for duplicate detection
├── Records blob URLs and vector IDs
└── Maintains retry counts and error messages
```

**Location**: Root directory (excluded from git)

### Qdrant Vector Storage

```
qdrant_storage/               # Local Qdrant data (for dev)
└── collections/
    └── colpali_embeddings/   # Vector embeddings
```

---

## Configuration Flow

### Environment Variables (.env)

```bash
# SharePoint
TENANT_ID=...
CLIENT_ID=...
CLIENT_SECRET=...
SITE_URL=https://codicetechcom.sharepoint.com/sites/FortiMind
DRIVE_PATH=Shared Documents

# Azure Blob
CONTAINER_SAS_URL=https://...

# Qdrant
QDRANT_URL=...
QDRANT_API_KEY=...
COLLECTION_NAME=colpali_embeddings
```

### Flow

```
.env file
    ↓
load_dotenv()
    ↓
SharePointBlobSync (reads env vars)
    ↓
SharePointToBlobUploader (core logic)
    ↓
FileTracker (database tracking)
```

---

## Development Workflow

### Local Development

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env with your credentials

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run sync
python sync_sharepoint.py

# 4. Check results
python -c "from utils import FileTracker; t = FileTracker(); print(t.get_statistics())"
```

### Docker Development

```bash
# Build image
docker build -t colpali-sync .

# Run with environment
docker run --env-file .env colpali-sync python sync_sharepoint.py
```

### Testing

```bash
# Test ColPali API
python test_api.py

# Test SharePoint sync
python examples/batch_processing_example.py
```

---

## Adding New Features

### Add a New Utility Function

1. Create function in `utils/pipeline_utils.py`
2. Export in `utils/__init__.py`
3. Document in relevant doc file
4. Add example in `examples/`

### Add New Documentation

1. Create markdown file in `docs/`
2. Link from main `README.md`
3. Update `PROJECT_STRUCTURE.md`

### Add New Example

1. Create script in `examples/`
2. Add sys.path manipulation for imports
3. Document in `docs/USAGE.md`

---

## Dependencies

### Core Packages

```
torch                        # PyTorch for ColPali
transformers                 # HuggingFace transformers
colpali-engine              # ColPali model
fastapi                     # API framework
qdrant-client               # Vector database client
```

### SharePoint/Blob Packages

```
Office365-REST-Python-Client  # SharePoint API
azure-storage-blob            # Azure Blob Storage
python-dotenv                 # Environment variables
```

### System Requirements

```
Python 3.11+
SQLite3 (included with Python)
poppler-utils (for PDF processing)
```

---

## Git Workflow

### Excluded from Git (.gitignore)

```
.env                        # Secrets
file_tracking.db           # Database
*.db                       # All databases
qdrant_storage/           # Vector data
uploads/                  # Uploaded files
pdfs/                    # PDF files
embeddings/              # Embeddings
__pycache__/             # Python cache
```

### Tracked in Git

```
.env.example              # Template
utils/                   # All utility code
examples/                # Example scripts
docs/                    # Documentation
requirements.txt         # Dependencies
Dockerfile              # Container config
```

---

## Performance Considerations

### File Tracking Database

- **Small projects** (<1000 files): No issues with SQLite
- **Medium projects** (1000-10000 files): Consider periodic cleanup
- **Large projects** (>10000 files): Consider PostgreSQL migration

### Batch Processing

- **Default batch size**: 10 files
- **Recommended for large jobs**: 50-100 files per batch
- **Parallel processing**: Possible with multiple database files

### Memory Usage

- **File hashing**: ~50-100ms per 10MB file
- **Temp storage**: Cleaned up automatically
- **Peak memory**: ~2x largest file size

---

## Troubleshooting

### Import Errors

```python
# Error: ModuleNotFoundError: No module named 'utils'
# Solution: Ensure you're running from project root
cd /path/to/colpali-docker
python sync_sharepoint.py
```

### Database Locked

```python
# Error: database is locked
# Solution: Use different database per process
sync = SharePointBlobSync(tracking_db_path=f"tracking_{os.getpid()}.db")
```

### Import from Examples

```python
# Always add sys.path manipulation in examples/
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

---

## Quick Reference

### Common Commands

```bash
# Sync files
python sync_sharepoint.py

# Run examples
python examples/batch_processing_example.py

# Check statistics
python -c "from utils import FileTracker; print(FileTracker().get_statistics())"

# Start ColPali API
python api.py

# Run with Docker
docker-compose up
```

### Common Imports

```python
# Main sync class
from utils import SharePointBlobSync

# Core utilities
from utils import SharePointToBlobUploader, FileTracker

# Convenience function
from utils import upload_sharepoint_to_blob
```

---

## Next Steps

1. **First time setup**: Read [docs/USAGE.md](docs/USAGE.md)
2. **Azure configuration**: Read [docs/SHAREPOINT_BLOB_SETUP.md](docs/SHAREPOINT_BLOB_SETUP.md)
3. **Advanced features**: Read [docs/BATCH_PROCESSING.md](docs/BATCH_PROCESSING.md)
4. **See examples**: Check [examples/batch_processing_example.py](examples/batch_processing_example.py)
5. **Start syncing**: Run `python sync_sharepoint.py`

---

## Support

For issues or questions:
1. Check documentation in `docs/`
2. Review examples in `examples/`
3. Verify environment variables in `.env`
4. Check logs and database status
