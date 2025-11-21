import os
import uuid
from typing import List, Optional
from pathlib import Path
import shutil

import torch
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from colpali_engine.models import ColPali, ColPaliProcessor
from pdf2image import convert_from_path
from PIL import Image
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="ColPali Document Embedding API",
    description="API for generating and storing document embeddings using ColPali",
    version="1.0.0"
)

# Global variables for model and clients
model = None
processor = None
qdrant_client = None
device = None

# Configuration
# For local Qdrant: QDRANT_HOST=qdrant, QDRANT_PORT=6333
# For Qdrant Cloud: QDRANT_URL=https://xxx.cloud.qdrant.io:6333, QDRANT_API_KEY=your-api-key
QDRANT_URL = os.getenv("QDRANT_URL", None)  # Full URL for Qdrant Cloud (e.g., https://xxx.cloud.qdrant.io:6333)
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)  # API key for Qdrant Cloud
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")  # For local Qdrant
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))  # For local Qdrant
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "colpali-test")
UPLOAD_DIR = Path("/app/uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Pydantic models
class EmbeddingResponse(BaseModel):
    document_id: str
    filename: str
    total_pages: int
    embedding_dimension: int
    tokens_per_page: int
    message: str

class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    qdrant_connected: bool
    device: str

class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    total_pages: int
    embedding_dimension: int

@app.on_event("startup")
async def startup_event():
    """Initialize model and connections on startup"""
    global model, processor, qdrant_client, device

    logger.info("Starting up ColPali API...")

    # Initialize device
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Using device: {device}")
    if device == "cuda":
        logger.info(f"GPU: {torch.cuda.get_device_name(0)}")

    # Load ColPali model
    try:
        logger.info("Loading ColPali model...")
        model_name = "vidore/colpali-v1.2"
        model = ColPali.from_pretrained(
            model_name,
            torch_dtype=torch.bfloat16 if device == "cuda" else torch.float32,
            device_map=device
        )
        processor = ColPaliProcessor.from_pretrained(model_name)
        logger.info("ColPali model loaded successfully!")
    except Exception as e:
        logger.error(f"Failed to load ColPali model: {e}")
        raise

    # Initialize Qdrant client with retry logic
    import time
    max_retries = 3
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            # Check if using Qdrant Cloud (URL and API key provided)
            if QDRANT_URL and QDRANT_API_KEY:
                logger.info(f"Connecting to Qdrant Cloud at {QDRANT_URL}...")
                qdrant_client = QdrantClient(
                    url=QDRANT_URL,
                    api_key=QDRANT_API_KEY,
                    timeout=30
                )
            else:
                # Use local Qdrant
                logger.info(f"Connecting to local Qdrant at {QDRANT_HOST}:{QDRANT_PORT}...")
                qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

            # Create collection if it doesn't exist
            collections = qdrant_client.get_collections().collections
            collection_exists = any(c.name == COLLECTION_NAME for c in collections)

            if not collection_exists:
                logger.info(f"Creating collection: {COLLECTION_NAME}")
                # ColPali generates embeddings with dimension 128 per token
                # We'll store the average pooled embedding for each page
                qdrant_client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=128, distance=Distance.COSINE)
                )
            else:
                logger.info(f"Collection '{COLLECTION_NAME}' already exists")
            logger.info("Qdrant connected successfully!")
            break  # Success, exit retry loop
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{max_retries} - Failed to connect to Qdrant: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                raise

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        model_loaded=model is not None,
        qdrant_connected=qdrant_client is not None,
        device=device
    )

@app.post("/ingest/pdf", response_model=EmbeddingResponse)
async def ingest_pdf(
    file: UploadFile = File(...),
    document_id: Optional[str] = None
):
    """
    Ingest a PDF document: convert to images, generate embeddings, and store in Qdrant
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Generate document ID if not provided
    if document_id is None:
        document_id = str(uuid.uuid4())

    # Save uploaded file
    file_path = UPLOAD_DIR / f"{document_id}_{file.filename}"
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"Saved file: {file_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    try:
        # Convert PDF to images
        logger.info(f"Converting PDF to images: {file_path}")
        pages = convert_from_path(str(file_path), dpi=200)
        logger.info(f"Extracted {len(pages)} pages")

        # Process each page and store embeddings
        points = []
        embedding_dim = None
        tokens_per_page = None

        for page_num, page_image in enumerate(pages, 1):
            logger.info(f"-" * 60)
            logger.info(f"PAGE {page_num} of {len(pages)}")
            logger.info(f"-" * 60)
            logger.info(f"  Image size: {page_image.size}")
            logger.info(f"  ⏳ Generating embeddings...")

            # Generate embeddings (same as app.py)
            batch_images = processor.process_images([page_image]).to(device)

            with torch.no_grad():
                embeddings = model(**batch_images)

            embeddings_np = embeddings.cpu().numpy()[0]
            tokens_per_page = embeddings_np.shape[0]

            # Display embedding info (same as app.py)
            logger.info(f"\n  EMBEDDING RESULTS:")
            logger.info(f"    Shape: {embeddings_np.shape}")
            logger.info(f"    Number of tokens/patches: {embeddings_np.shape[0]}")
            logger.info(f"    Embedding dimension: {embeddings_np.shape[1]}")
            logger.info(f"    Min value: {embeddings_np.min():.6f}")
            logger.info(f"    Max value: {embeddings_np.max():.6f}")
            logger.info(f"    Mean value: {embeddings_np.mean():.6f}")
            logger.info(f"    Std deviation: {embeddings_np.std():.6f}")

            # Average pool the embeddings (from multiple tokens to single vector)
            avg_embedding = embeddings_np.mean(axis=0)
            embedding_dim = avg_embedding.shape[0]
            logger.info(f"    Average pooled embedding dimension: {embedding_dim}")

            # Create point for Qdrant (use UUID for point ID)
            point_id = str(uuid.uuid4())
            point = PointStruct(
                id=point_id,
                vector=avg_embedding.tolist(),
                payload={
                    "document_id": document_id,
                    "filename": file.filename,
                    "page_number": page_num,
                    "total_pages": len(pages),
                    "file_type": "pdf",
                    "tokens_per_page": tokens_per_page,
                    "embedding_dimension": embedding_dim
                }
            )
            points.append(point)

        # Upload to Qdrant
        logger.info(f"Uploading {len(points)} embeddings to Qdrant...")
        qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )
        logger.info("Upload to Qdrant completed!")

        return EmbeddingResponse(
            document_id=document_id,
            filename=file.filename,
            total_pages=len(pages),
            embedding_dimension=embedding_dim,
            tokens_per_page=tokens_per_page,
            message=f"Successfully ingested PDF with {len(pages)} pages"
        )

    except Exception as e:
        logger.error(f"Error processing document: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")
    finally:
        # Clean up uploaded file
        if file_path.exists():
            file_path.unlink()

@app.post("/ingest/image", response_model=EmbeddingResponse)
async def ingest_image(
    file: UploadFile = File(...),
    document_id: Optional[str] = None
):
    """
    Ingest an image file: generate embeddings and store in Qdrant
    """
    allowed_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')
    if not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"Only image files are supported: {', '.join(allowed_extensions)}"
        )

    # Generate document ID if not provided
    if document_id is None:
        document_id = str(uuid.uuid4())

    # Save uploaded file
    file_path = UPLOAD_DIR / f"{document_id}_{file.filename}"
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"Saved file: {file_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    try:
        # Load image
        logger.info(f"Loading image: {file_path}")
        image = Image.open(file_path)

        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Generate embeddings
        logger.info("Generating embeddings...")
        batch_images = processor.process_images([image]).to(device)

        with torch.no_grad():
            embeddings = model(**batch_images)

        embeddings_np = embeddings.cpu().numpy()[0]
        tokens_per_page = embeddings_np.shape[0]

        # Average pool the embeddings
        avg_embedding = embeddings_np.mean(axis=0)
        embedding_dim = avg_embedding.shape[0]

        # Create point for Qdrant (use UUID for point ID)
        point_id = str(uuid.uuid4())
        point = PointStruct(
            id=point_id,
            vector=avg_embedding.tolist(),
            payload={
                "document_id": document_id,
                "filename": file.filename,
                "page_number": 1,
                "total_pages": 1,
                "file_type": "image",
                "tokens_per_page": tokens_per_page,
                "embedding_dimension": embedding_dim
            }
        )

        # Upload to Qdrant
        logger.info("Uploading embedding to Qdrant...")
        qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=[point]
        )
        logger.info("Upload to Qdrant completed!")

        return EmbeddingResponse(
            document_id=document_id,
            filename=file.filename,
            total_pages=1,
            embedding_dimension=embedding_dim,
            tokens_per_page=tokens_per_page,
            message="Successfully ingested image"
        )

    except Exception as e:
        logger.error(f"Error processing image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process image: {str(e)}")
    finally:
        # Clean up uploaded file
        if file_path.exists():
            file_path.unlink()

@app.delete("/document/{document_id}")
async def delete_document(document_id: str):
    """
    Delete all embeddings for a specific document
    """
    try:
        # Delete from Qdrant using filter
        qdrant_client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id)
                    )
                ]
            )
        )

        return {"message": f"Document {document_id} deleted successfully"}

    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")

@app.get("/documents", response_model=List[DocumentInfo])
async def list_documents():
    """
    List all unique documents in the collection
    """
    try:
        # Scroll through all points to get unique document IDs
        scroll_result = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=10000,
            with_payload=True,
            with_vectors=False
        )

        # Extract unique documents
        documents = {}
        for point in scroll_result[0]:
            doc_id = point.payload["document_id"]
            if doc_id not in documents:
                documents[doc_id] = DocumentInfo(
                    document_id=doc_id,
                    filename=point.payload["filename"],
                    total_pages=point.payload["total_pages"],
                    embedding_dimension=point.payload["embedding_dimension"]
                )

        return list(documents.values())

    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")

@app.get("/stats")
async def get_stats():
    """
    Get collection statistics
    """
    try:
        collection_info = qdrant_client.get_collection(collection_name=COLLECTION_NAME)

        return {
            "collection_name": COLLECTION_NAME,
            "total_vectors": collection_info.points_count,
            "vector_dimension": collection_info.config.params.vectors.size,
            "distance_metric": collection_info.config.params.vectors.distance.name
        }

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
