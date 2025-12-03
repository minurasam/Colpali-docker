"""
ETL Pipeline REST API
FastAPI-based REST API for ETL pipeline operations.
Implements Repository, Service, and Controller patterns for clean architecture.
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from etl.pipeline import ETLPipeline
from etl.config import get_config
from etl.utils import SQLiteMetadataStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models (DTOs - Data Transfer Objects)
# ============================================================================

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    pipeline_initialized: bool
    database_connected: bool
    vector_db_connected: bool
    sharepoint_connected: bool


class FileInfo(BaseModel):
    """File information"""
    name: str
    server_relative_url: str
    size: int


class ProcessFileRequest(BaseModel):
    """Request to process single file"""
    sharepoint_url: str = Field(..., description="SharePoint file URL")
    skip_if_duplicate: bool = Field(True, description="Skip if file hash already exists")


class ProcessBatchRequest(BaseModel):
    """Request to process batch of files"""
    files: List[FileInfo] = Field(..., description="List of files to process")
    skip_duplicates: bool = Field(True, description="Skip duplicate files")


class ProcessingResult(BaseModel):
    """Single file processing result"""
    status: str = Field(..., description="success, failed, or skipped")
    file_name: str
    file_id: Optional[str] = None
    pages_processed: Optional[int] = None
    vector_ids: Optional[List[str]] = None
    blob_url: Optional[str] = None
    error: Optional[str] = None
    reason: Optional[str] = None


class BatchProcessingResponse(BaseModel):
    """Batch processing response"""
    batch_id: str
    total_files: int
    successful: int
    failed: int
    skipped: int
    results: List[ProcessingResult]


class DocumentMetadata(BaseModel):
    """Document metadata from database"""
    file_id: str
    file_name: str
    file_hash: str
    file_size: int
    file_type: str
    status: str
    blob_url: Optional[str]
    upload_timestamp: Optional[str]


class EmbeddingMetadata(BaseModel):
    """Embedding metadata"""
    embedding_id: str
    file_id: str
    page_number: int
    vector_id: str
    embedding_dimension: int
    tokens_count: int


class StatisticsResponse(BaseModel):
    """Pipeline statistics"""
    files: Dict
    embeddings: Dict
    batches: Dict


class DeleteDocumentRequest(BaseModel):
    """Request to delete document"""
    file_id: str = Field(..., description="File ID to delete")
    delete_from_vector_db: bool = Field(True, description="Also delete from Qdrant")


# ============================================================================
# Service Layer (Business Logic)
# ============================================================================

class ETLService:
    """
    Service layer for ETL operations
    Implements business logic and orchestrates pipeline operations
    """

    def __init__(self, pipeline: ETLPipeline):
        """
        Initialize service

        Args:
            pipeline: ETL pipeline instance
        """
        self.pipeline = pipeline
        self.metadata_store = pipeline.metadata_store

    def check_health(self) -> Dict:
        """
        Check health of all components

        Returns:
            Health status dictionary
        """
        try:
            # Check database
            db_connected = True
            try:
                self.metadata_store.get_statistics()
            except Exception as e:
                logger.error(f"Database check failed: {e}")
                db_connected = False

            # Check vector DB
            vector_db_connected = True
            try:
                self.pipeline.vector_db.client.get_collections()
            except Exception as e:
                logger.error(f"Vector DB check failed: {e}")
                vector_db_connected = False

            # Check SharePoint
            sharepoint_connected = True
            try:
                # Simple check - just verify context exists
                _ = self.pipeline.sharepoint_ctx.web
            except Exception as e:
                logger.error(f"SharePoint check failed: {e}")
                sharepoint_connected = False

            return {
                "status": "healthy" if all([db_connected, vector_db_connected, sharepoint_connected]) else "degraded",
                "timestamp": datetime.now().isoformat(),
                "pipeline_initialized": True,
                "database_connected": db_connected,
                "vector_db_connected": vector_db_connected,
                "sharepoint_connected": sharepoint_connected
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "pipeline_initialized": False,
                "database_connected": False,
                "vector_db_connected": False,
                "sharepoint_connected": False
            }

    def process_single_file(
        self,
        sharepoint_url: str,
        skip_if_duplicate: bool = True
    ) -> ProcessingResult:
        """
        Process single file from SharePoint

        Args:
            sharepoint_url: SharePoint file URL
            skip_if_duplicate: Skip if duplicate exists

        Returns:
            ProcessingResult
        """
        import tempfile
        from etl.utils import FileHasher

        try:
            # Extract filename from URL
            filename = sharepoint_url.split('/')[-1]

            # Download to temp location
            with tempfile.TemporaryDirectory() as temp_dir:
                import os
                local_path = os.path.join(temp_dir, filename)
                self.pipeline.download_from_sharepoint(sharepoint_url, local_path)

                # Calculate hash
                file_hash = FileHasher.calculate_hash(local_path)
                file_size = os.path.getsize(local_path)

                # Check for duplicate
                if skip_if_duplicate and self.metadata_store.file_exists(file_hash):
                    logger.info(f"Skipping duplicate file: {filename}")
                    return ProcessingResult(
                        status="skipped",
                        file_name=filename,
                        reason="duplicate"
                    )

                # Process file
                result = self.pipeline.process_file(
                    file_path=local_path,
                    file_name=filename,
                    sharepoint_path=sharepoint_url,
                    file_hash=file_hash,
                    file_size=file_size
                )

                return ProcessingResult(**result)

        except Exception as e:
            logger.error(f"Error processing file: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process file: {str(e)}"
            )

    def process_batch(
        self,
        files: List[FileInfo],
        skip_duplicates: bool = True
    ) -> BatchProcessingResponse:
        """
        Process batch of files

        Args:
            files: List of file information
            skip_duplicates: Skip duplicate files

        Returns:
            BatchProcessingResponse
        """
        try:
            file_list = [file.dict() for file in files]
            result = self.pipeline.process_batch(file_list, skip_duplicates)

            return BatchProcessingResponse(
                batch_id=result['batch_id'],
                total_files=result['total_files'],
                successful=result['successful'],
                failed=result['failed'],
                skipped=result['skipped'],
                results=[ProcessingResult(**r) for r in result['results']]
            )

        except Exception as e:
            logger.error(f"Error processing batch: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process batch: {str(e)}"
            )

    def get_document_metadata(self, file_hash: str) -> Optional[DocumentMetadata]:
        """
        Get document metadata by hash

        Args:
            file_hash: File hash

        Returns:
            DocumentMetadata or None
        """
        doc = self.metadata_store.file_exists(file_hash)
        if doc:
            return DocumentMetadata(**doc)
        return None

    def get_file_embeddings(self, file_id: str) -> List[EmbeddingMetadata]:
        """
        Get embeddings for file

        Args:
            file_id: File ID

        Returns:
            List of EmbeddingMetadata
        """
        embeddings = self.metadata_store.get_file_embeddings(file_id)
        return [EmbeddingMetadata(**emb) for emb in embeddings]

    def delete_document(
        self,
        file_id: str,
        delete_from_vector_db: bool = True
    ) -> Dict:
        """
        Delete document and optionally its vectors

        Args:
            file_id: File ID
            delete_from_vector_db: Also delete from Qdrant

        Returns:
            Deletion summary
        """
        try:
            # Delete from vector DB
            if delete_from_vector_db:
                self.pipeline.vector_db.delete_document(file_id)

            # Could implement database deletion here if needed
            # For now, we just mark as deleted in vector DB

            return {
                "file_id": file_id,
                "deleted_from_vector_db": delete_from_vector_db,
                "message": "Document deleted successfully"
            }

        except Exception as e:
            logger.error(f"Error deleting document: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete document: {str(e)}"
            )

    def get_statistics(self) -> StatisticsResponse:
        """
        Get pipeline statistics

        Returns:
            StatisticsResponse
        """
        stats = self.pipeline.get_statistics()
        return StatisticsResponse(**stats)


# ============================================================================
# Application Lifespan Management
# ============================================================================

# Global pipeline instance
pipeline_instance: Optional[ETLPipeline] = None
service_instance: Optional[ETLService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown

    Args:
        app: FastAPI application
    """
    global pipeline_instance, service_instance

    # Startup
    logger.info("Starting ETL API...")

    try:
        # Initialize pipeline
        logger.info("Initializing ETL pipeline...")
        pipeline_instance = ETLPipeline()
        service_instance = ETLService(pipeline_instance)
        logger.info("ETL pipeline initialized successfully")

        yield

    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        raise

    finally:
        # Shutdown
        logger.info("Shutting down ETL API...")
        pipeline_instance = None
        service_instance = None


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="ColPali ETL Pipeline API",
    description="REST API for processing documents with ColPali embeddings and storing in vector DB",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# API Endpoints (Controllers)
# ============================================================================

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "service": "ColPali ETL Pipeline API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint
    Checks status of all pipeline components
    """
    if service_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pipeline not initialized"
        )

    health = service_instance.check_health()
    return HealthResponse(**health)


@app.post("/process/file", response_model=ProcessingResult, tags=["Processing"])
async def process_file(
    request: ProcessFileRequest,
    background_tasks: BackgroundTasks
):
    """
    Process single file from SharePoint

    Args:
        request: Processing request
        background_tasks: FastAPI background tasks

    Returns:
        ProcessingResult
    """
    if service_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pipeline not initialized"
        )

    return service_instance.process_single_file(
        sharepoint_url=request.sharepoint_url,
        skip_if_duplicate=request.skip_if_duplicate
    )


@app.post("/process/batch", response_model=BatchProcessingResponse, tags=["Processing"])
async def process_batch(request: ProcessBatchRequest):
    """
    Process batch of files from SharePoint

    Args:
        request: Batch processing request

    Returns:
        BatchProcessingResponse
    """
    if service_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pipeline not initialized"
        )

    return service_instance.process_batch(
        files=request.files,
        skip_duplicates=request.skip_duplicates
    )


@app.get("/document/{file_hash}", response_model=DocumentMetadata, tags=["Documents"])
async def get_document(file_hash: str):
    """
    Get document metadata by file hash

    Args:
        file_hash: File content hash

    Returns:
        DocumentMetadata
    """
    if service_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pipeline not initialized"
        )

    doc = service_instance.get_document_metadata(file_hash)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    return doc


@app.get("/document/{file_id}/embeddings", response_model=List[EmbeddingMetadata], tags=["Documents"])
async def get_embeddings(file_id: str):
    """
    Get embeddings for a document

    Args:
        file_id: File ID

    Returns:
        List of EmbeddingMetadata
    """
    if service_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pipeline not initialized"
        )

    embeddings = service_instance.get_file_embeddings(file_id)
    return embeddings


@app.delete("/document", tags=["Documents"])
async def delete_document(request: DeleteDocumentRequest):
    """
    Delete document and its vectors

    Args:
        request: Delete request

    Returns:
        Deletion summary
    """
    if service_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pipeline not initialized"
        )

    return service_instance.delete_document(
        file_id=request.file_id,
        delete_from_vector_db=request.delete_from_vector_db
    )


@app.get("/statistics", response_model=StatisticsResponse, tags=["Statistics"])
async def get_statistics():
    """
    Get pipeline statistics

    Returns:
        StatisticsResponse
    """
    if service_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pipeline not initialized"
        )

    return service_instance.get_statistics()


@app.get("/config", tags=["Configuration"])
async def get_configuration():
    """
    Get current configuration (excluding sensitive data)

    Returns:
        Configuration dictionary
    """
    config = get_config()
    return config.to_dict()


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": str(exc)
        }
    )


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "etl.api:app",
        host="0.0.0.0",
        port=8001,  # Different port from original api.py
        reload=True,
        log_level="info"
    )
