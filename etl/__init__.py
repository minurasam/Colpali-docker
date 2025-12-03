"""
ETL Pipeline Package for ColPali Document Processing

This package provides a complete ETL pipeline for:
- Downloading documents from SharePoint
- Embedding documents with ColPali vision model
- Uploading embeddings to Qdrant vector database
- Tracking file metadata in SQLite/Azure SQL

Main Components:
- config: Configuration management
- utils: File operations, hashing, metadata store
- pipeline: ETL orchestration and batch processing
- api: REST API endpoints
"""

__version__ = "1.0.0"
__author__ = "FortiMind Team"

from etl.config import get_config, reload_config, ETLConfig
from etl.pipeline import ETLPipeline
from etl.utils import SQLiteMetadataStore, BlobStorageHelper, FileHasher

__all__ = [
    # Configuration
    "get_config",
    "reload_config",
    "ETLConfig",

    # Pipeline
    "ETLPipeline",

    # Utilities
    "SQLiteMetadataStore",
    "BlobStorageHelper",
    "FileHasher",
]
