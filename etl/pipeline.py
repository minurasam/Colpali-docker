"""
ETL Pipeline for ColPali Document Processing
Handles downloading from SharePoint, embedding with ColPali, and uploading to Qdrant vector DB.
Uses Strategy and Factory design patterns for extensibility.
"""

import os
import uuid
import logging
import tempfile
from typing import List, Dict, Optional, Protocol
from pathlib import Path
from abc import ABC, abstractmethod
from dataclasses import dataclass

import torch
import numpy as np
from PIL import Image
from pdf2image import convert_from_path
from colpali_engine.models import ColPali, ColPaliProcessor
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.client_credential import ClientCredential

from etl.config import get_config, ETLConfig
from etl.utils import SQLiteMetadataStore, BlobStorageHelper, FileHasher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Document Processor Protocol (Strategy Pattern)
# ============================================================================

class DocumentProcessor(Protocol):
    """Protocol for document processing strategies"""

    def can_process(self, file_path: str) -> bool:
        """Check if processor can handle this file type"""
        ...

    def process(self, file_path: str) -> List[Image.Image]:
        """
        Process document and return list of images

        Args:
            file_path: Path to document

        Returns:
            List of PIL Images
        """
        ...


class PDFProcessor:
    """PDF document processor"""

    def can_process(self, file_path: str) -> bool:
        return file_path.lower().endswith('.pdf')

    def process(self, file_path: str, dpi: int = 200) -> List[Image.Image]:
        """Convert PDF to images"""
        logger.info(f"Converting PDF to images: {file_path}")
        pages = convert_from_path(file_path, dpi=dpi)
        logger.info(f"Extracted {len(pages)} pages from PDF")
        return pages


class ImageProcessor:
    """Image document processor"""

    SUPPORTED_FORMATS = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')

    def can_process(self, file_path: str) -> bool:
        return file_path.lower().endswith(self.SUPPORTED_FORMATS)

    def process(self, file_path: str) -> List[Image.Image]:
        """Load image"""
        logger.info(f"Loading image: {file_path}")
        image = Image.open(file_path)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        return [image]


# ============================================================================
# Document Processor Factory
# ============================================================================

class DocumentProcessorFactory:
    """Factory for creating document processors"""

    _processors: List[DocumentProcessor] = [
        PDFProcessor(),
        ImageProcessor()
    ]

    @classmethod
    def get_processor(cls, file_path: str) -> Optional[DocumentProcessor]:
        """
        Get appropriate processor for file

        Args:
            file_path: Path to file

        Returns:
            DocumentProcessor instance or None
        """
        for processor in cls._processors:
            if processor.can_process(file_path):
                return processor
        return None


# ============================================================================
# Embedding Generator
# ============================================================================

@dataclass
class EmbeddingResult:
    """Result of embedding generation"""
    page_number: int
    embedding: np.ndarray
    avg_embedding: np.ndarray
    tokens_count: int
    embedding_dimension: int


class ColPaliEmbeddingGenerator:
    """
    ColPali model wrapper for generating embeddings
    Implements Singleton pattern for model loading
    """

    _instance = None
    _model = None
    _processor = None
    _device = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize model (only once)"""
        if self._model is None:
            self._initialize_model()

    def _initialize_model(self):
        """Load ColPali model"""
        config = get_config()

        # Detect device
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self._device}")

        if self._device == "cuda":
            logger.info(f"GPU: {torch.cuda.get_device_name(0)}")

        # Load model
        logger.info(f"Loading ColPali model: {config.model.model_name}")
        self._model = ColPali.from_pretrained(
            config.model.model_name,
            torch_dtype=torch.float16 if config.model.use_fp16 and self._device == "cuda" else torch.float32,
            device_map=self._device
        )
        self._processor = ColPaliProcessor.from_pretrained(config.model.model_name)
        logger.info("ColPali model loaded successfully")

    def generate_embedding(self, image: Image.Image, page_number: int = 1) -> EmbeddingResult:
        """
        Generate embedding for image

        Args:
            image: PIL Image
            page_number: Page number (for multi-page docs)

        Returns:
            EmbeddingResult
        """
        logger.info(f"Generating embedding for page {page_number}")
        logger.info(f"  Image size: {image.size}")

        # Process image
        batch_images = self._processor.process_images([image]).to(self._device)

        # Generate embeddings
        with torch.no_grad():
            embeddings = self._model(**batch_images)

        embeddings_np = embeddings.cpu().numpy()[0]
        tokens_count = embeddings_np.shape[0]
        embedding_dim = embeddings_np.shape[1]

        # Log statistics
        logger.info(f"  Embedding shape: {embeddings_np.shape}")
        logger.info(f"  Tokens: {tokens_count}, Dimension: {embedding_dim}")
        logger.info(f"  Stats - Min: {embeddings_np.min():.4f}, Max: {embeddings_np.max():.4f}, "
                   f"Mean: {embeddings_np.mean():.4f}")

        # Average pool embeddings
        avg_embedding = embeddings_np.mean(axis=0)

        return EmbeddingResult(
            page_number=page_number,
            embedding=embeddings_np,
            avg_embedding=avg_embedding,
            tokens_count=tokens_count,
            embedding_dimension=embedding_dim
        )


# ============================================================================
# Vector Database Manager
# ============================================================================

class VectorDBManager:
    """Manages Qdrant vector database operations"""

    def __init__(self, config: Optional[ETLConfig] = None):
        """
        Initialize vector DB manager

        Args:
            config: ETL configuration
        """
        self.config = config or get_config()
        self.client = self._init_client()
        self._ensure_collection_exists()

    def _init_client(self) -> QdrantClient:
        """Initialize Qdrant client"""
        logger.info(f"Connecting to Qdrant at {self.config.qdrant.url}")
        return QdrantClient(
            url=self.config.qdrant.url,
            api_key=self.config.qdrant.api_key,
            timeout=30
        )

    def _ensure_collection_exists(self):
        """Create collection if it doesn't exist"""
        collections = self.client.get_collections().collections
        collection_exists = any(c.name == self.config.qdrant.collection_name for c in collections)

        if not collection_exists:
            logger.info(f"Creating collection: {self.config.qdrant.collection_name}")
            self.client.create_collection(
                collection_name=self.config.qdrant.collection_name,
                vectors_config=VectorParams(
                    size=self.config.qdrant.vector_dimension,
                    distance=Distance.COSINE
                )
            )
        else:
            logger.info(f"Collection '{self.config.qdrant.collection_name}' exists")

    def upsert_embeddings(
        self,
        embeddings: List[EmbeddingResult],
        document_id: str,
        filename: str,
        file_type: str
    ) -> List[str]:
        """
        Upload embeddings to Qdrant

        Args:
            embeddings: List of embedding results
            document_id: Document identifier
            filename: Original filename
            file_type: File extension

        Returns:
            List of vector IDs
        """
        points = []
        vector_ids = []

        for emb in embeddings:
            vector_id = str(uuid.uuid4())
            vector_ids.append(vector_id)

            point = PointStruct(
                id=vector_id,
                vector=emb.avg_embedding.tolist(),
                payload={
                    "document_id": document_id,
                    "filename": filename,
                    "file_type": file_type,
                    "page_number": emb.page_number,
                    "total_pages": len(embeddings),
                    "tokens_count": emb.tokens_count,
                    "embedding_dimension": emb.embedding_dimension
                }
            )
            points.append(point)

        logger.info(f"Uploading {len(points)} vectors to Qdrant...")
        self.client.upsert(
            collection_name=self.config.qdrant.collection_name,
            points=points
        )
        logger.info("Upload to Qdrant completed")

        return vector_ids

    def delete_document(self, document_id: str):
        """Delete all vectors for a document"""
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        self.client.delete(
            collection_name=self.config.qdrant.collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            )
        )
        logger.info(f"Deleted document {document_id} from Qdrant")


# ============================================================================
# Main ETL Pipeline
# ============================================================================

class ETLPipeline:
    """
    Main ETL Pipeline orchestrator
    Coordinates all components: SharePoint download, processing, embedding, and upload
    """

    def __init__(self, config: Optional[ETLConfig] = None):
        """
        Initialize ETL pipeline

        Args:
            config: ETL configuration
        """
        self.config = config or get_config()

        # Validate configuration
        is_valid, errors = self.config.validate_all()
        if not is_valid:
            raise ValueError(f"Configuration validation failed: {', '.join(errors)}")

        # Initialize components
        self.metadata_store = SQLiteMetadataStore(self.config.database.sqlite_path)
        self.blob_helper = BlobStorageHelper(self.config.blob_storage.container_sas_url)
        self.embedding_generator = ColPaliEmbeddingGenerator()
        self.vector_db = VectorDBManager(self.config)
        self.sharepoint_ctx = self._init_sharepoint()

        logger.info("ETL Pipeline initialized successfully")

    def _init_sharepoint(self) -> ClientContext:
        """Initialize SharePoint client"""
        credentials = ClientCredential(
            self.config.sharepoint.client_id,
            self.config.sharepoint.client_secret
        )
        ctx = ClientContext(self.config.sharepoint.site_url).with_credentials(credentials)
        logger.info(f"SharePoint connected: {self.config.sharepoint.site_url}")
        return ctx

    def download_from_sharepoint(self, server_relative_url: str, local_path: str) -> str:
        """
        Download file from SharePoint

        Args:
            server_relative_url: SharePoint file URL
            local_path: Local path to save

        Returns:
            Local file path
        """
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        with open(local_path, "wb") as local_file:
            file = (
                self.sharepoint_ctx.web.get_file_by_server_relative_url(server_relative_url)
                .download(local_file)
                .execute_query()
            )

        logger.info(f"Downloaded from SharePoint: {server_relative_url} -> {local_path}")
        return local_path

    def process_file(
        self,
        file_path: str,
        file_name: str,
        sharepoint_path: str,
        file_hash: str,
        file_size: int
    ) -> Dict:
        """
        Process a single file through the entire ETL pipeline

        Flow: Download → Hash/Metadata → Track in SQL → Upload to Blob →
              Load → Process → Embed → Store in Qdrant → Update SQL

        Args:
            file_path: Local path to file
            file_name: Original filename
            sharepoint_path: SharePoint URL
            file_hash: Content hash
            file_size: Size in bytes

        Returns:
            Processing result dictionary
        """
        file_id = str(uuid.uuid4())
        file_type = Path(file_name).suffix

        try:
            # STEP 1: Track file metadata in SQL (status: pending)
            logger.info(f"Step 1: Tracking file metadata in SQL - {file_name}")
            self.metadata_store.add_file(
                file_id=file_id,
                file_name=file_name,
                file_hash=file_hash,
                file_size=file_size,
                file_type=file_type,
                sharepoint_path=sharepoint_path
            )

            # STEP 2: Upload original file to blob storage
            logger.info(f"Step 2: Uploading file to blob storage - {file_name}")
            blob_name = f"{self.config.blob_storage.blob_folder_prefix}/{file_id}_{file_name}"
            blob_url = self.blob_helper.upload_file(file_path, blob_name)
            logger.info(f"Uploaded to blob: {blob_url}")

            # Update SQL with blob info (status: uploaded)
            self.metadata_store.update_file_status(
                file_hash=file_hash,
                status="uploaded",
                blob_url=blob_url,
                blob_name=blob_name
            )

            # STEP 3: Load and process document
            logger.info(f"Step 3: Processing document - {file_name}")
            processor = DocumentProcessorFactory.get_processor(file_path)
            if processor is None:
                raise ValueError(f"No processor found for file type: {file_type}")

            images = processor.process(file_path)
            logger.info(f"Processed {len(images)} page(s) from {file_name}")

            # Update status to processing
            self.metadata_store.update_file_status(
                file_hash=file_hash,
                status="processing"
            )

            # STEP 4: Generate ColPali embeddings
            logger.info(f"Step 4: Generating ColPali embeddings - {file_name}")
            embeddings = []
            for page_num, image in enumerate(images, 1):
                emb_result = self.embedding_generator.generate_embedding(image, page_num)
                embeddings.append(emb_result)

            # STEP 5: Store embeddings in Qdrant
            logger.info(f"Step 5: Storing embeddings in Qdrant - {file_name}")
            vector_ids = self.vector_db.upsert_embeddings(
                embeddings=embeddings,
                document_id=file_id,
                filename=file_name,
                file_type=file_type
            )

            # STEP 6: Update SQL with final status and embedding info
            logger.info(f"Step 6: Updating SQL with final status - {file_name}")
            self.metadata_store.update_file_status(
                file_hash=file_hash,
                status="embedded"
            )

            # Record embeddings in SQL
            for page_num, vector_id in enumerate(vector_ids, 1):
                self.metadata_store.add_embedding(
                    embedding_id=str(uuid.uuid4()),
                    file_id=file_id,
                    page_number=page_num,
                    vector_id=vector_id,
                    embedding_dimension=embeddings[0].embedding_dimension,
                    tokens_count=embeddings[0].tokens_count
                )

            logger.info(f"✓ Successfully completed pipeline for {file_name}")
            return {
                "status": "success",
                "file_id": file_id,
                "file_name": file_name,
                "pages_processed": len(embeddings),
                "vector_ids": vector_ids,
                "blob_url": blob_url
            }

        except Exception as e:
            logger.error(f"Error processing file {file_name}: {e}")
            self.metadata_store.update_file_status(
                file_hash=file_hash,
                status="failed",
                error_message=str(e)
            )
            return {
                "status": "failed",
                "file_name": file_name,
                "error": str(e)
            }

    def process_batch(
        self,
        file_list: List[Dict],
        skip_duplicates: bool = True
    ) -> Dict:
        """
        Process batch of files

        Args:
            file_list: List of file info dicts (name, server_relative_url, size)
            skip_duplicates: Skip files that already exist in DB

        Returns:
            Batch processing summary
        """
        batch_id = str(uuid.uuid4())
        self.metadata_store.create_batch(batch_id, len(file_list))

        results = []
        successful = 0
        failed = 0
        skipped = 0

        logger.info(f"Starting batch processing: {len(file_list)} files")

        with tempfile.TemporaryDirectory() as temp_dir:
            for file_info in file_list:
                file_name = file_info['name']
                server_relative_url = file_info['server_relative_url']
                file_size = file_info.get('size', 0)

                try:
                    # Download to temp location
                    local_path = os.path.join(temp_dir, file_name)
                    self.download_from_sharepoint(server_relative_url, local_path)

                    # Calculate hash
                    file_hash = FileHasher.calculate_hash(local_path)

                    # Check for duplicates
                    if skip_duplicates and self.metadata_store.file_exists(file_hash):
                        logger.info(f"Skipping duplicate: {file_name}")
                        skipped += 1
                        results.append({
                            "status": "skipped",
                            "file_name": file_name,
                            "reason": "duplicate"
                        })
                        continue

                    # Process file
                    result = self.process_file(
                        file_path=local_path,
                        file_name=file_name,
                        sharepoint_path=server_relative_url,
                        file_hash=file_hash,
                        file_size=file_size
                    )

                    if result['status'] == 'success':
                        successful += 1
                    else:
                        failed += 1

                    results.append(result)

                except Exception as e:
                    logger.error(f"Error processing {file_name}: {e}")
                    failed += 1
                    results.append({
                        "status": "failed",
                        "file_name": file_name,
                        "error": str(e)
                    })

        # Update batch status
        self.metadata_store.update_batch(
            batch_id=batch_id,
            successful_files=successful,
            failed_files=failed,
            status="completed" if failed == 0 else "partial"
        )

        logger.info(f"Batch processing completed: {successful} successful, {failed} failed, {skipped} skipped")

        return {
            "batch_id": batch_id,
            "total_files": len(file_list),
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "results": results
        }

    def get_statistics(self) -> Dict:
        """Get pipeline statistics"""
        return self.metadata_store.get_statistics()


if __name__ == "__main__":
    """Test pipeline initialization"""
    try:
        pipeline = ETLPipeline()
        logger.info("Pipeline initialized successfully")

        # Get statistics
        stats = pipeline.get_statistics()
        logger.info(f"Statistics: {stats}")

    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        import traceback
        traceback.print_exc()
