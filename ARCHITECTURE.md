# ColPali ETL Pipeline - Architecture Document

## Overview

The ColPali ETL Pipeline is a production-ready system for processing documents with vision embeddings and storing them in a vector database with comprehensive metadata tracking.

## Core Principle: Metadata-First Architecture

The pipeline follows a **metadata-first** approach where:
1. Every file is tracked in SQL **before** processing begins
2. Status is updated at each stage of the pipeline
3. All operations are auditable and resumable
4. Duplicate detection happens early to avoid unnecessary processing

## Complete Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    COMPLETE ETL PIPELINE FLOW                        │
└─────────────────────────────────────────────────────────────────────┘

1. DOWNLOAD FROM SHAREPOINT
   ├─ Authenticate with Azure AD credentials
   ├─ Fetch file from SharePoint site
   └─ Save to temporary local storage

2. HASH & METADATA EXTRACTION
   ├─ Calculate SHA256 content hash
   ├─ Extract file metadata (size, type, modified date)
   └─ Check for duplicate (hash lookup in SQL)
      ├─ If duplicate exists → SKIP (status: skipped)
      └─ If new → CONTINUE

3. TRACK IN SQL DATABASE (Status: pending)
   ├─ Insert file record
   ├─ Store: file_id, file_name, file_hash, file_size
   ├─ Store: sharepoint_path, file_type
   └─ Set status = 'pending'

4. UPLOAD TO BLOB STORAGE (Status: uploaded)
   ├─ Generate unique blob name: {prefix}/{file_id}_{filename}
   ├─ Upload original file to Azure Blob Storage
   ├─ Get blob URL
   └─ Update SQL: blob_url, blob_name, status = 'uploaded'

5. LOAD DATA (Status: processing)
   ├─ Select appropriate processor (PDF/Image)
   ├─ PDF: Convert to images (using pdf2image)
   ├─ Image: Load and convert to RGB
   └─ Update SQL: status = 'processing'

6. PROCESS WITH COLPALI
   ├─ For each page/image:
   │  ├─ Preprocess image with ColPaliProcessor
   │  ├─ Generate embeddings with ColPali model
   │  ├─ Extract tokens (1030 patches per image)
   │  └─ Average pool to 128-dimensional vector
   └─ Collect all page embeddings

7. STORE IN QDRANT VECTOR DB
   ├─ For each page embedding:
   │  ├─ Generate unique vector_id
   │  ├─ Create PointStruct with:
   │  │  ├─ Vector: 128-dimensional embedding
   │  │  └─ Payload: document_id, filename, page_number, etc.
   │  └─ Upload to Qdrant collection
   └─ Collect all vector_ids

8. UPDATE SQL (Status: embedded)
   ├─ Update file record: status = 'embedded'
   ├─ For each page:
   │  └─ Insert embedding record:
   │     ├─ embedding_id, file_id, page_number
   │     ├─ vector_id, embedding_dimension, tokens_count
   │     └─ qdrant_uploaded = true
   └─ Complete batch tracking if applicable

┌─────────────────────────────────────────────────────────────────────┐
│                         ON ERROR                                     │
├─────────────────────────────────────────────────────────────────────┤
│ At any stage:                                                        │
│  ├─ Update SQL: status = 'failed'                                   │
│  ├─ Record error_message                                            │
│  ├─ Increment retry_count                                           │
│  └─ Return error details                                            │
└─────────────────────────────────────────────────────────────────────┘
```

## File Status Lifecycle

```
┌─────────┐
│  START  │
└────┬────┘
     │
     ▼
┌──────────┐     ┌──────────┐     ┌────────────┐     ┌──────────┐
│ pending  │────→│ uploaded │────→│ processing │────→│ embedded │
└────┬─────┘     └────┬─────┘     └─────┬──────┘     └──────────┘
     │                │                  │
     │                │                  │
     └────────────────┴──────────────────┘
                      │
                      ▼
                 ┌─────────┐
                 │ failed  │ (with retry_count)
                 └─────────┘
```

### Status Definitions

- **pending**: File metadata recorded, awaiting blob upload
- **uploaded**: Original file stored in Azure Blob Storage
- **processing**: Document being converted and embedded
- **embedded**: Embeddings successfully stored in Qdrant
- **failed**: Error occurred (with error_message and retry_count)

## Database Schema

### Files Table

```sql
CREATE TABLE files (
    -- Identity
    file_id TEXT PRIMARY KEY,           -- UUID
    file_name TEXT NOT NULL,            -- Original filename
    file_hash TEXT NOT NULL UNIQUE,     -- SHA256 content hash

    -- File Metadata
    file_size INTEGER,                  -- Size in bytes
    file_type TEXT,                     -- File extension (.pdf, .png, etc.)

    -- Source Information
    sharepoint_path TEXT,               -- SharePoint server relative URL
    sharepoint_modified TEXT,           -- Last modified in SharePoint

    -- Blob Storage
    blob_url TEXT,                      -- Azure Blob Storage URL
    blob_name TEXT,                     -- Blob name/path

    -- Processing Tracking
    download_timestamp TEXT,            -- When downloaded from SharePoint
    upload_timestamp TEXT,              -- When uploaded to blob
    status TEXT DEFAULT 'pending',      -- Current processing status
    error_message TEXT,                 -- Error details if failed
    retry_count INTEGER DEFAULT 0,      -- Number of retry attempts

    -- Additional Metadata
    metadata TEXT                       -- JSON string for extra data
);

-- Indexes
CREATE INDEX idx_file_hash ON files(file_hash);
CREATE INDEX idx_file_status ON files(status);
CREATE INDEX idx_file_type ON files(file_type);
```

### Embeddings Table

```sql
CREATE TABLE embeddings (
    -- Identity
    embedding_id TEXT PRIMARY KEY,      -- UUID
    file_id TEXT NOT NULL,              -- Foreign key to files table

    -- Embedding Metadata
    page_number INTEGER,                -- Page number (for PDFs)
    vector_id TEXT,                     -- ID in Qdrant vector DB
    embedding_dimension INTEGER,        -- Vector dimension (128 for ColPali)
    tokens_count INTEGER,               -- Number of tokens/patches

    -- Tracking
    processing_timestamp TEXT,          -- When embedding was generated
    qdrant_uploaded BOOLEAN DEFAULT 0,  -- Successfully stored in Qdrant

    FOREIGN KEY (file_id) REFERENCES files(file_id)
);

-- Indexes
CREATE INDEX idx_embedding_file_id ON embeddings(file_id);
CREATE INDEX idx_embedding_vector_id ON embeddings(vector_id);
```

### Processing Batches Table

```sql
CREATE TABLE processing_batches (
    -- Identity
    batch_id TEXT PRIMARY KEY,          -- UUID

    -- Timing
    batch_start_time TEXT,              -- Batch start timestamp
    batch_end_time TEXT,                -- Batch end timestamp

    -- Statistics
    total_files INTEGER,                -- Total files in batch
    successful_files INTEGER,           -- Successfully processed
    failed_files INTEGER,               -- Failed to process

    -- Status
    status TEXT,                        -- processing, completed, partial
    error_summary TEXT                  -- Summary of errors
);
```

## Component Architecture

### Layer Separation

```
┌─────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                   │
│  - REST endpoints                                        │
│  - Request/Response validation (Pydantic)                │
│  - HTTP error handling                                   │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                   Service Layer                          │
│  - Business logic (ETLService)                           │
│  - Orchestration                                         │
│  - Transaction management                                │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                  Pipeline Layer                          │
│  - ETL orchestration (ETLPipeline)                       │
│  - Component coordination                                │
│  - Error handling and retry logic                        │
└───┬──────┬──────┬──────┬──────┬──────┬──────────────────┘
    │      │      │      │      │      │
┌───▼──┐ ┌─▼───┐ ┌▼────┐ ┌▼────┐ ┌▼───┐ ┌▼──────────┐
│Share │ │ Doc │ │ColP │ │Blob │ │Qdr │ │  SQL      │
│Point │ │Proc │ │ ali │ │Stor │ │ant │ │  Store    │
│Client│ │     │ │Model│ │age  │ │ DB │ │           │
└──────┘ └─────┘ └─────┘ └─────┘ └────┘ └───────────┘
```

### Design Patterns

1. **Strategy Pattern** (Document Processors)
   - `DocumentProcessor` protocol defines interface
   - `PDFProcessor` and `ImageProcessor` implement strategies
   - `DocumentProcessorFactory` selects appropriate strategy

2. **Factory Pattern** (Processor Creation)
   - `DocumentProcessorFactory.get_processor(file_path)`
   - Returns appropriate processor based on file extension

3. **Singleton Pattern** (Model Loading)
   - `ColPaliEmbeddingGenerator` ensures single model instance
   - Model loaded once and reused for all embeddings
   - Saves memory and initialization time

4. **Repository Pattern** (Data Access)
   - `SQLiteMetadataStore` abstracts database operations
   - Easy migration to Azure SQL by swapping implementation
   - Clean separation of data access logic

5. **Service Layer Pattern** (Business Logic)
   - `ETLService` contains business rules
   - Controllers delegate to service
   - Testable business logic

6. **Dependency Injection**
   - Components receive dependencies via constructors
   - Loose coupling, easy testing
   - Example: `ETLPipeline(config)`, `ETLService(pipeline)`

## Data Flow Details

### Duplicate Detection

```
File Downloaded
    │
    ▼
Calculate SHA256 Hash
    │
    ▼
Query SQL: SELECT * FROM files WHERE file_hash = ?
    │
    ├─ Record Found ──→ SKIP (return status: skipped)
    │
    └─ Not Found ──→ CONTINUE to Step 3
```

### Batch Processing

```
Batch Request (N files)
    │
    ├─ Create batch record in SQL
    │
    ├─ For each file:
    │   ├─ Download from SharePoint
    │   ├─ Check duplicate
    │   ├─ If not duplicate:
    │   │   └─ Process through pipeline
    │   └─ If error:
    │       └─ Mark as failed, continue to next file
    │
    └─ Update batch record:
        ├─ total_files
        ├─ successful_files
        ├─ failed_files
        └─ status (completed/partial)
```

### Error Handling Strategy

1. **File-Level Isolation**
   - Errors in one file don't stop batch processing
   - Each file tracked independently

2. **Retry Mechanism**
   - Failed files tracked with `retry_count`
   - Can be retried up to configurable limit
   - Error messages stored for debugging

3. **Status Tracking**
   - Every stage updates SQL status
   - Easy to resume from failure point
   - Audit trail of all operations

## Scalability Considerations

### Current Implementation
- **Single-threaded**: Processes one file at a time
- **GPU Acceleration**: Uses CUDA if available
- **Temporary Storage**: Files cleaned up after processing
- **Connection Pooling**: Reuses SharePoint/Blob/Qdrant connections

### Future Enhancements
1. **Multi-threading**: Process multiple files in parallel
2. **Worker Queue**: Distributed processing with Celery/RQ
3. **Batch Optimization**: Process multiple pages simultaneously
4. **Caching**: Cache frequently accessed embeddings
5. **Horizontal Scaling**: Multiple worker instances

## Security Considerations

1. **Credentials Management**
   - All credentials in environment variables
   - Never logged or exposed in responses
   - SAS URLs time-limited

2. **SQL Injection Prevention**
   - Parameterized queries throughout
   - No string concatenation in SQL

3. **File Validation**
   - File type checking before processing
   - Size limits can be configured
   - Content hash verification

4. **Access Control**
   - API can be secured with authentication
   - SharePoint permissions respected
   - Blob Storage uses SAS tokens

## Monitoring and Observability

### Logging Levels
- **INFO**: Normal operations, status updates
- **ERROR**: Failures and exceptions
- **DEBUG**: Detailed processing information

### Key Metrics to Track
1. Files processed per hour
2. Average processing time per file
3. Success/failure rates
4. Duplicate detection rate
5. Qdrant upload success rate
6. Blob storage upload success rate

### Audit Trail
- Every file operation logged in SQL
- Batch processing tracked
- Error messages and retry counts recorded
- Timestamps at each stage

## Testing Strategy

### Unit Tests
- Configuration validation
- File hashing
- Document processors
- SQL operations

### Integration Tests
- SharePoint connection
- Blob storage operations
- Qdrant vector storage
- End-to-end pipeline

### Performance Tests
- Large file handling
- Batch processing throughput
- Concurrent request handling
- Memory usage under load

## Deployment

### Prerequisites
1. Python 3.8+
2. CUDA-capable GPU (optional, for acceleration)
3. Azure AD app registration
4. Azure Blob Storage account
5. Qdrant instance
6. SQLite or Azure SQL database

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Initialize database
python -c "from etl.utils import SQLiteMetadataStore; SQLiteMetadataStore()"

# Start API
python -m etl.api
```

### Production Considerations
- Use Azure SQL instead of SQLite
- Configure proper logging
- Set up monitoring and alerts
- Enable API authentication
- Use HTTPS for all connections
- Regular backup of SQL database

## Conclusion

This architecture provides:
- ✅ **Auditability**: Every operation tracked in SQL
- ✅ **Resumability**: Can resume from any failure point
- ✅ **Scalability**: Designed for future horizontal scaling
- ✅ **Maintainability**: Clean separation of concerns
- ✅ **Reliability**: Comprehensive error handling
- ✅ **Observability**: Full logging and monitoring support
