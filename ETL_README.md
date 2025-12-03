# ColPali ETL Pipeline

A production-ready ETL pipeline for processing documents with ColPali vision embeddings and storing them in a vector database.

## Architecture Overview

```
SharePoint → Download → Hash/Metadata → Track in SQL → Upload to Blob →
Load Data → Process → ColPali Embedding → Store in Qdrant → Update SQL
```

### Detailed Flow

1. **Download from SharePoint**: Fetch file from SharePoint to temp location
2. **Calculate Hash**: Generate SHA256 hash for duplicate detection
3. **Track Metadata in SQL**: Insert file record with status=`pending`
4. **Upload to Blob Storage**: Store original file in Azure Blob Storage, update status=`uploaded`
5. **Load and Process**: Convert PDF to images or load image file, update status=`processing`
6. **Generate Embeddings**: Process with ColPali vision model
7. **Store in Qdrant**: Upload embedding vectors to vector database
8. **Update SQL**: Mark as status=`embedded`, record embedding metadata

### File Status Lifecycle

```
pending → uploaded → processing → embedded
   ↓         ↓           ↓           ↓
                    failed (at any stage)
```

- **pending**: File metadata tracked, awaiting upload
- **uploaded**: File stored in blob storage
- **processing**: Document being processed and embedded
- **embedded**: Embeddings generated and stored in Qdrant
- **failed**: Error occurred (with retry_count tracking)

### Design Patterns Used

1. **Strategy Pattern**: Document processors (PDF, Image) implement a common interface
2. **Factory Pattern**: DocumentProcessorFactory creates appropriate processors
3. **Singleton Pattern**: ColPaliEmbeddingGenerator ensures single model instance
4. **Repository Pattern**: SQLiteMetadataStore abstracts data access
5. **Service Layer Pattern**: ETLService contains business logic
6. **Dependency Injection**: Components receive dependencies via constructors

## Project Structure

```
etl/
├── __init__.py           # Package initialization
├── config.py             # Configuration management
├── utils.py              # File operations, hashing, metadata store
├── pipeline.py           # ETL orchestration
└── api.py                # REST API endpoints
```

## Pipeline Flow Diagram

```
┌──────────────┐
│  SharePoint  │
└──────┬───────┘
       │ 1. Download file
       ▼
┌──────────────────────┐
│  Local Temp Storage  │
└──────┬───────────────┘
       │ 2. Calculate SHA256 hash
       ▼
┌──────────────────────┐
│   SQL Database       │◄────────────────┐
│  (Track Metadata)    │                 │
│  Status: pending     │                 │
└──────┬───────────────┘                 │
       │ 3. Record file info             │
       ▼                                 │
┌──────────────────────┐                 │
│  Azure Blob Storage  │                 │
│  (Store Original)    │                 │
└──────┬───────────────┘                 │
       │ 4. Upload file                  │
       │    Update: uploaded             │
       ▼                                 │
┌──────────────────────┐                 │
│  Document Processor  │                 │
│  (PDF→Images/Load)   │                 │
└──────┬───────────────┘                 │
       │ 5. Process document             │
       │    Update: processing           │
       ▼                                 │
┌──────────────────────┐                 │
│   ColPali Model      │                 │
│  (Generate Vectors)  │                 │
└──────┬───────────────┘                 │
       │ 6. Embed pages                  │
       ▼                                 │
┌──────────────────────┐                 │
│  Qdrant Vector DB    │                 │
│  (Store Embeddings)  │                 │
└──────┬───────────────┘                 │
       │ 7. Upload vectors               │
       │    Update: embedded             │
       └─────────────────────────────────┘
              8. Final metadata update
```

## Components

### 1. Configuration (`config.py`)

Centralized configuration using dataclasses and environment variables.

**Key Classes:**
- `SharePointConfig`: SharePoint connection settings
- `BlobStorageConfig`: Azure Blob Storage settings
- `DatabaseConfig`: SQLite/Azure SQL settings
- `QdrantConfig`: Vector database settings
- `ModelConfig`: ColPali model settings
- `ProcessingConfig`: File processing settings
- `ETLConfig`: Aggregates all configurations

**Usage:**
```python
from etl.config import get_config

config = get_config()
is_valid, errors = config.validate_all()
```

### 2. Utilities (`utils.py`)

Reusable utilities for file operations and metadata management.

**Key Classes:**

#### `FileHasher`
Static methods for file hashing:
```python
from etl.utils import FileHasher

file_hash = FileHasher.calculate_hash("document.pdf", algorithm="sha256")
```

#### `SQLiteMetadataStore`
Manages file and embedding metadata in SQLite:

**Tables:**
- `files`: File metadata and processing status
- `embeddings`: Embedding records linked to files
- `processing_batches`: Batch processing history

**Usage:**
```python
from etl.utils import SQLiteMetadataStore

store = SQLiteMetadataStore("etl_tracking.db")

# Check if file exists
existing = store.file_exists(file_hash)

# Add new file
store.add_file(
    file_id="uuid-123",
    file_name="document.pdf",
    file_hash=file_hash,
    file_size=1024000,
    file_type=".pdf",
    sharepoint_path="/site/doc.pdf"
)

# Update status
store.update_file_status(
    file_hash=file_hash,
    status="embedded",
    blob_url="https://..."
)

# Get statistics
stats = store.get_statistics()
```

#### `BlobStorageHelper`
Azure Blob Storage operations:
```python
from etl.utils import BlobStorageHelper

helper = BlobStorageHelper(container_sas_url)
blob_url = helper.upload_file("local.pdf", "path/to/blob.pdf")
helper.download_file("path/to/blob.pdf", "local.pdf")
exists = helper.blob_exists("path/to/blob.pdf")
```

### 3. Pipeline (`pipeline.py`)

Main ETL orchestration with clean architecture.

**Key Classes:**

#### Document Processors (Strategy Pattern)
- `PDFProcessor`: Converts PDF to images
- `ImageProcessor`: Loads and converts images
- `DocumentProcessorFactory`: Creates appropriate processor

#### `ColPaliEmbeddingGenerator` (Singleton)
Generates embeddings using ColPali model:
```python
from etl.pipeline import ColPaliEmbeddingGenerator

generator = ColPaliEmbeddingGenerator()
result = generator.generate_embedding(image, page_number=1)
# result.avg_embedding, result.tokens_count, result.embedding_dimension
```

#### `VectorDBManager`
Manages Qdrant vector database:
```python
from etl.pipeline import VectorDBManager

db_manager = VectorDBManager()
vector_ids = db_manager.upsert_embeddings(
    embeddings=embeddings_list,
    document_id="uuid-123",
    filename="doc.pdf",
    file_type=".pdf"
)
db_manager.delete_document("uuid-123")
```

#### `ETLPipeline`
Main orchestrator:
```python
from etl.pipeline import ETLPipeline

pipeline = ETLPipeline()

# Process single file
result = pipeline.process_file(
    file_path="local.pdf",
    file_name="document.pdf",
    sharepoint_path="/site/doc.pdf",
    file_hash=file_hash,
    file_size=1024000
)

# Process batch
batch_result = pipeline.process_batch(
    file_list=[
        {"name": "doc1.pdf", "server_relative_url": "/site/doc1.pdf", "size": 1024},
        {"name": "doc2.pdf", "server_relative_url": "/site/doc2.pdf", "size": 2048}
    ],
    skip_duplicates=True
)

# Get statistics
stats = pipeline.get_statistics()
```

### 4. API (`api.py`)

RESTful API with clean architecture (Service + Controller layers).

**Design:**
- **DTOs (Pydantic Models)**: Data validation and serialization
- **Service Layer**: Business logic (`ETLService`)
- **Controllers**: API endpoints
- **Dependency Injection**: Service receives pipeline instance

**Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Root endpoint |
| GET | `/health` | Health check |
| POST | `/process/file` | Process single file |
| POST | `/process/batch` | Process batch of files |
| GET | `/document/{file_hash}` | Get document metadata |
| GET | `/document/{file_id}/embeddings` | Get embeddings |
| DELETE | `/document` | Delete document |
| GET | `/statistics` | Get pipeline stats |
| GET | `/config` | Get configuration |

**Usage Examples:**

Start the API:
```bash
python -m etl.api
# or
uvicorn etl.api:app --host 0.0.0.0 --port 8001 --reload
```

Process single file:
```bash
curl -X POST "http://localhost:8001/process/file" \
  -H "Content-Type: application/json" \
  -d '{
    "sharepoint_url": "/sites/FortiMind/ETL_Documents/document.pdf",
    "skip_if_duplicate": true
  }'
```

Process batch:
```bash
curl -X POST "http://localhost:8001/process/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [
      {
        "name": "doc1.pdf",
        "server_relative_url": "/sites/FortiMind/ETL_Documents/doc1.pdf",
        "size": 1024000
      }
    ],
    "skip_duplicates": true
  }'
```

Get statistics:
```bash
curl "http://localhost:8001/statistics"
```

## Environment Variables

Create a `.env` file:

```env
# SharePoint Configuration
CLIENT_ID=your-azure-ad-client-id
CLIENT_SECRET=your-azure-ad-client-secret
SITE_URL=https://yourtenant.sharepoint.com/sites/yoursite
DRIVE_PATH=/ETL_Documents

# Azure Blob Storage
CONTAINER_SAS_URL=https://account.blob.core.windows.net/container?sv=...
BLOB_FOLDER_PREFIX=etl-documents

# Database (SQLite or Azure SQL)
USE_AZURE_SQL=false
SQLITE_PATH=etl_tracking.db
AZURE_SQL_CONNECTION_STRING=Driver={ODBC Driver 17 for SQL Server};Server=...

# Qdrant Vector Database
QDRANT_URL=https://vector.dev.fortimind.ai:6333
QDRANT_API_KEY=your-api-key
COLLECTION_NAME=colpali-documents

# Processing
BATCH_SIZE=10
TEMP_DIR=./temp
```

## Installation

Install dependencies:
```bash
pip install -r requirements.txt
```

Required packages:
- `torch` - PyTorch
- `transformers` - Hugging Face transformers
- `colpali-engine` - ColPali model
- `pillow` - Image processing
- `pdf2image` - PDF conversion
- `numpy` - Numerical operations
- `fastapi` - REST API framework
- `uvicorn` - ASGI server
- `pydantic` - Data validation
- `qdrant-client` - Vector database client
- `azure-storage-blob` - Azure Blob Storage
- `Office365-REST-Python-Client` - SharePoint integration
- `python-dotenv` - Environment variables

## Usage Examples

### Python API

#### Initialize Pipeline
```python
from etl import ETLPipeline

pipeline = ETLPipeline()
```

#### Process Files from SharePoint
```python
# List files from SharePoint
from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.client_credential import ClientCredential

# Get files (example)
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
    }
]

# Process batch
result = pipeline.process_batch(
    file_list=files_to_process,
    skip_duplicates=True
)

print(f"Batch ID: {result['batch_id']}")
print(f"Successful: {result['successful']}")
print(f"Failed: {result['failed']}")
print(f"Skipped: {result['skipped']}")

for file_result in result['results']:
    if file_result['status'] == 'success':
        print(f"✓ {file_result['file_name']}: {len(file_result['vector_ids'])} vectors")
    elif file_result['status'] == 'skipped':
        print(f"⊘ {file_result['file_name']}: {file_result['reason']}")
    else:
        print(f"✗ {file_result['file_name']}: {file_result['error']}")
```

#### Check Statistics
```python
stats = pipeline.get_statistics()

print("Files:")
for status, info in stats['files'].items():
    print(f"  {status}: {info['count']} files ({info['total_size'] / 1024 / 1024:.2f} MB)")

print(f"\nEmbeddings:")
print(f"  Total: {stats['embeddings']['total']}")
print(f"  Uploaded: {stats['embeddings']['uploaded']}")

print(f"\nBatches:")
print(f"  Total: {stats['batches']['total']}")
print(f"  Successful files: {stats['batches']['successful_files']}")
print(f"  Failed files: {stats['batches']['failed_files']}")
```

### REST API

See API documentation at: `http://localhost:8001/docs` (Swagger UI)

## Database Schema

### Files Table
```sql
CREATE TABLE files (
    file_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    file_size INTEGER,
    file_type TEXT,
    sharepoint_path TEXT,
    sharepoint_modified TEXT,
    blob_url TEXT,
    blob_name TEXT,
    download_timestamp TEXT,
    upload_timestamp TEXT,
    status TEXT DEFAULT 'pending',  -- pending, processing, embedded, failed
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    metadata TEXT
);
```

### Embeddings Table
```sql
CREATE TABLE embeddings (
    embedding_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    page_number INTEGER,
    vector_id TEXT,
    embedding_dimension INTEGER,
    tokens_count INTEGER,
    processing_timestamp TEXT,
    qdrant_uploaded BOOLEAN DEFAULT 0,
    FOREIGN KEY (file_id) REFERENCES files(file_id)
);
```

### Processing Batches Table
```sql
CREATE TABLE processing_batches (
    batch_id TEXT PRIMARY KEY,
    batch_start_time TEXT,
    batch_end_time TEXT,
    total_files INTEGER,
    successful_files INTEGER,
    failed_files INTEGER,
    status TEXT,
    error_summary TEXT
);
```

## Error Handling

The pipeline includes comprehensive error handling:

1. **File Level**: Individual file errors don't stop batch processing
2. **Retry Logic**: Failed files tracked with retry counts
3. **Status Tracking**: All operations logged in database
4. **Duplicate Detection**: Content-based (SHA256) deduplication

## Performance Considerations

- **GPU Acceleration**: Automatic CUDA detection for ColPali
- **Batch Processing**: Process multiple files in one batch
- **Temporary Storage**: Files downloaded to temp directory, cleaned up automatically
- **Connection Pooling**: Reuses SharePoint, Blob, and Qdrant connections
- **Singleton Model**: ColPali model loaded once and reused

## Migration to Azure SQL

Currently uses SQLite. To migrate to Azure SQL:

1. Set environment variable: `USE_AZURE_SQL=true`
2. Provide connection string: `AZURE_SQL_CONNECTION_STRING=...`
3. Update `utils.py` to use `pyodbc` instead of `sqlite3`
4. Schema remains identical

## Monitoring and Logging

All components use Python's `logging` module:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

Logs include:
- File download/upload operations
- Embedding generation progress
- Vector DB operations
- Error traces

## Testing

Test individual components:

```python
# Test configuration
python -m etl.config

# Test utilities
python -m etl.utils

# Test pipeline
python -m etl.pipeline
```

## Security Notes

- Never commit `.env` file
- SAS URLs contain credentials - keep secure
- Client secrets should be rotated regularly
- Database contains file metadata - protect accordingly
- Use HTTPS for API in production

## Future Enhancements

- [ ] Azure SQL support
- [ ] Multi-threaded batch processing
- [ ] Progress bars and detailed logging
- [ ] Email notifications
- [ ] Retry mechanism with exponential backoff
- [ ] Document versioning
- [ ] Full-text search integration
- [ ] Webhook support for real-time processing
- [ ] Admin dashboard

## Troubleshooting

### Pipeline Initialization Fails
- Check all environment variables are set
- Verify SharePoint credentials
- Ensure Qdrant is accessible
- Check Blob Storage SAS URL is valid

### Files Not Processing
- Verify file type is supported (.pdf, .png, .jpg, etc.)
- Check GPU memory for large PDFs
- Verify SharePoint permissions
- Check disk space for temporary files

### Vector Upload Fails
- Verify Qdrant URL and API key
- Check collection exists
- Ensure network connectivity
- Verify vector dimensions match (128)

## License

Internal use - FortiMind Team

## Support

For issues or questions, contact the development team.
