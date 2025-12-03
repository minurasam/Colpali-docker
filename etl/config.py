"""
ETL Pipeline Configuration
Centralized configuration management using environment variables and dataclasses.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class SharePointConfig:
    """SharePoint connection configuration"""
    client_id: str = field(default_factory=lambda: os.getenv("CLIENT_ID"))
    client_secret: str = field(default_factory=lambda: os.getenv("CLIENT_SECRET"))
    site_url: str = field(default_factory=lambda: os.getenv("SITE_URL"))
    drive_path: str = field(default_factory=lambda: os.getenv("DRIVE_PATH", "/ETL_Documents"))

    def validate(self) -> bool:
        """Validate required fields"""
        return all([self.client_id, self.client_secret, self.site_url])


@dataclass
class BlobStorageConfig:
    """Azure Blob Storage configuration"""
    container_sas_url: str = field(default_factory=lambda: os.getenv("CONTAINER_SAS_URL"))
    blob_folder_prefix: str = field(default_factory=lambda: os.getenv("BLOB_FOLDER_PREFIX", "etl-documents"))

    def validate(self) -> bool:
        """Validate required fields"""
        return bool(self.container_sas_url)


@dataclass
class DatabaseConfig:
    """Database configuration (SQLite or Azure SQL)"""
    use_azure_sql: bool = field(default_factory=lambda: os.getenv("USE_AZURE_SQL", "false").lower() == "true")
    sqlite_path: str = field(default_factory=lambda: os.getenv("SQLITE_PATH", "etl_tracking.db"))
    azure_sql_connection_string: Optional[str] = field(
        default_factory=lambda: os.getenv("AZURE_SQL_CONNECTION_STRING")
    )

    def validate(self) -> bool:
        """Validate configuration based on database type"""
        if self.use_azure_sql:
            return bool(self.azure_sql_connection_string)
        return bool(self.sqlite_path)


@dataclass
class QdrantConfig:
    """Qdrant vector database configuration"""
    url: str = field(default_factory=lambda: os.getenv("QDRANT_URL"))
    api_key: str = field(default_factory=lambda: os.getenv("QDRANT_API_KEY"))
    collection_name: str = field(default_factory=lambda: os.getenv("COLLECTION_NAME", "colpali-documents"))
    vector_dimension: int = 128  # ColPali embedding dimension

    def validate(self) -> bool:
        """Validate required fields"""
        return all([self.url, self.api_key, self.collection_name])


@dataclass
class ModelConfig:
    """ColPali model configuration"""
    model_name: str = "vidore/colpali-v1.2"
    device: str = "cuda"  # Will be auto-detected
    use_fp16: bool = True
    dpi: int = 200  # PDF to image conversion DPI
    batch_size: int = 1  # Number of pages to process at once

    def __post_init__(self):
        """Auto-detect device after initialization"""
        import torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"


@dataclass
class ProcessingConfig:
    """File processing configuration"""
    supported_extensions: List[str] = field(
        default_factory=lambda: [".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"]
    )
    temp_dir: str = field(default_factory=lambda: os.getenv("TEMP_DIR", "./temp"))
    batch_size: int = field(default_factory=lambda: int(os.getenv("BATCH_SIZE", "10")))
    enable_duplicate_check: bool = True
    delete_after_upload: bool = True
    max_retries: int = 3
    retry_delay: int = 5  # seconds


@dataclass
class ETLConfig:
    """Main ETL configuration aggregating all sub-configs"""
    sharepoint: SharePointConfig = field(default_factory=SharePointConfig)
    blob_storage: BlobStorageConfig = field(default_factory=BlobStorageConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)

    def validate_all(self) -> tuple[bool, List[str]]:
        """
        Validate all configurations

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        if not self.sharepoint.validate():
            errors.append("SharePoint configuration incomplete")

        if not self.blob_storage.validate():
            errors.append("Blob Storage configuration incomplete")

        if not self.database.validate():
            errors.append("Database configuration incomplete")

        if not self.qdrant.validate():
            errors.append("Qdrant configuration incomplete")

        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        """Convert configuration to dictionary (excluding sensitive data)"""
        return {
            "sharepoint": {
                "site_url": self.sharepoint.site_url,
                "drive_path": self.sharepoint.drive_path,
            },
            "blob_storage": {
                "blob_folder_prefix": self.blob_storage.blob_folder_prefix,
            },
            "database": {
                "use_azure_sql": self.database.use_azure_sql,
                "sqlite_path": self.database.sqlite_path if not self.database.use_azure_sql else None,
            },
            "qdrant": {
                "collection_name": self.qdrant.collection_name,
                "vector_dimension": self.qdrant.vector_dimension,
            },
            "model": {
                "model_name": self.model.model_name,
                "device": self.model.device,
                "use_fp16": self.model.use_fp16,
            },
            "processing": {
                "supported_extensions": self.processing.supported_extensions,
                "batch_size": self.processing.batch_size,
                "enable_duplicate_check": self.processing.enable_duplicate_check,
            }
        }


# Singleton instance
_config_instance: Optional[ETLConfig] = None


def get_config() -> ETLConfig:
    """
    Get or create singleton configuration instance

    Returns:
        ETLConfig instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ETLConfig()
    return _config_instance


def reload_config() -> ETLConfig:
    """
    Force reload configuration from environment

    Returns:
        New ETLConfig instance
    """
    global _config_instance
    load_dotenv(override=True)
    _config_instance = ETLConfig()
    return _config_instance


if __name__ == "__main__":
    """Test configuration loading"""
    config = get_config()
    is_valid, errors = config.validate_all()

    print("ETL Configuration Validation")
    print("=" * 60)

    if is_valid:
        print("✓ Configuration is valid")
        print("\nConfiguration Summary:")
        import json
        print(json.dumps(config.to_dict(), indent=2))
    else:
        print("✗ Configuration validation failed:")
        for error in errors:
            print(f"  - {error}")
