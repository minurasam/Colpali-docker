"""
ETL Utilities Module
Handles file operations, hashing, duplicate detection, and SQL metadata management.
"""

import os
import hashlib
import sqlite3
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from azure.storage.blob import BlobServiceClient, BlobClient
from azure.core.exceptions import AzureError

logger = logging.getLogger(__name__)


class FileHasher:
    """Utility class for file hashing operations"""

    @staticmethod
    def calculate_hash(file_path: str, algorithm: str = "sha256", chunk_size: int = 8192) -> str:
        """
        Calculate hash of file content

        Args:
            file_path: Path to file
            algorithm: Hash algorithm (md5, sha256, sha1)
            chunk_size: Size of chunks to read

        Returns:
            Hexadecimal hash string
        """
        hash_func = hashlib.new(algorithm)

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hash_func.update(chunk)

        return hash_func.hexdigest()

    @staticmethod
    def calculate_hash_from_bytes(data: bytes, algorithm: str = "sha256") -> str:
        """
        Calculate hash from bytes

        Args:
            data: Byte data
            algorithm: Hash algorithm

        Returns:
            Hexadecimal hash string
        """
        hash_func = hashlib.new(algorithm)
        hash_func.update(data)
        return hash_func.hexdigest()


class SQLiteMetadataStore:
    """
    SQLite-based metadata store for ETL tracking
    Handles file metadata, embeddings metadata, and processing status
    """

    def __init__(self, db_path: str = "etl_tracking.db"):
        """
        Initialize metadata store

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Create all required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Files table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
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
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                metadata TEXT
            )
        """)

        # Embeddings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                embedding_id TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                page_number INTEGER,
                vector_id TEXT,
                embedding_dimension INTEGER,
                tokens_count INTEGER,
                processing_timestamp TEXT,
                qdrant_uploaded BOOLEAN DEFAULT 0,
                FOREIGN KEY (file_id) REFERENCES files(file_id)
            )
        """)

        # Processing batches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processing_batches (
                batch_id TEXT PRIMARY KEY,
                batch_start_time TEXT,
                batch_end_time TEXT,
                total_files INTEGER,
                successful_files INTEGER,
                failed_files INTEGER,
                status TEXT,
                error_summary TEXT
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_hash ON files(file_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_status ON files(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_type ON files(file_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_embedding_file_id ON embeddings(file_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_embedding_vector_id ON embeddings(vector_id)")

        conn.commit()
        conn.close()
        logger.info(f"Metadata store initialized: {self.db_path}")

    def file_exists(self, file_hash: str) -> Optional[Dict]:
        """
        Check if file with hash exists

        Args:
            file_hash: File content hash

        Returns:
            File record if exists, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM files WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    def add_file(
        self,
        file_id: str,
        file_name: str,
        file_hash: str,
        file_size: int,
        file_type: str,
        sharepoint_path: str,
        sharepoint_modified: str = None,
        metadata: str = None
    ) -> bool:
        """
        Add new file to tracking

        Args:
            file_id: Unique file identifier
            file_name: Original filename
            file_hash: Content hash
            file_size: Size in bytes
            file_type: File extension
            sharepoint_path: SharePoint URL
            sharepoint_modified: Last modified timestamp
            metadata: Additional metadata as JSON string

        Returns:
            True if added, False if duplicate exists
        """
        # Check for duplicate
        existing = self.file_exists(file_hash)
        if existing:
            logger.info(f"Duplicate file detected: {file_name} (hash: {file_hash[:16]}...)")
            return False

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO files
                (file_id, file_name, file_hash, file_size, file_type,
                 sharepoint_path, sharepoint_modified, download_timestamp, metadata, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (file_id, file_name, file_hash, file_size, file_type,
                  sharepoint_path, sharepoint_modified, datetime.now().isoformat(), metadata))

            conn.commit()
            logger.info(f"Added file to tracking: {file_name}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"File already exists: {file_name}")
            return False
        finally:
            conn.close()

    def update_file_status(
        self,
        file_hash: str,
        status: str,
        blob_url: str = None,
        blob_name: str = None,
        error_message: str = None
    ):
        """
        Update file processing status

        Args:
            file_hash: File hash
            status: New status (pending, processing, embedded, failed)
            blob_url: Azure Blob URL
            blob_name: Blob name
            error_message: Error message if failed
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        update_fields = ["status = ?"]
        values = [status]

        if status == "embedded":
            update_fields.append("upload_timestamp = ?")
            values.append(datetime.now().isoformat())

        if blob_url:
            update_fields.append("blob_url = ?")
            values.append(blob_url)

        if blob_name:
            update_fields.append("blob_name = ?")
            values.append(blob_name)

        if error_message:
            update_fields.append("error_message = ?")
            values.append(error_message)
            update_fields.append("retry_count = retry_count + 1")

        values.append(file_hash)

        query = f"UPDATE files SET {', '.join(update_fields)} WHERE file_hash = ?"
        cursor.execute(query, values)

        conn.commit()
        conn.close()

    def add_embedding(
        self,
        embedding_id: str,
        file_id: str,
        page_number: int,
        vector_id: str,
        embedding_dimension: int,
        tokens_count: int
    ):
        """
        Add embedding record

        Args:
            embedding_id: Unique embedding identifier
            file_id: Reference to file
            page_number: Page number (for PDFs)
            vector_id: Qdrant vector ID
            embedding_dimension: Dimension of embedding vector
            tokens_count: Number of tokens/patches
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO embeddings
            (embedding_id, file_id, page_number, vector_id, embedding_dimension,
             tokens_count, processing_timestamp, qdrant_uploaded)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """, (embedding_id, file_id, page_number, vector_id, embedding_dimension,
              tokens_count, datetime.now().isoformat()))

        conn.commit()
        conn.close()

    def get_file_embeddings(self, file_id: str) -> List[Dict]:
        """
        Get all embeddings for a file

        Args:
            file_id: File identifier

        Returns:
            List of embedding records
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM embeddings WHERE file_id = ?", (file_id,))
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def create_batch(self, batch_id: str, total_files: int) -> None:
        """
        Create new processing batch

        Args:
            batch_id: Batch identifier
            total_files: Total files in batch
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO processing_batches
            (batch_id, batch_start_time, total_files, successful_files, failed_files, status)
            VALUES (?, ?, ?, 0, 0, 'processing')
        """, (batch_id, datetime.now().isoformat(), total_files))

        conn.commit()
        conn.close()

    def update_batch(
        self,
        batch_id: str,
        successful_files: int,
        failed_files: int,
        status: str,
        error_summary: str = None
    ):
        """
        Update batch processing status

        Args:
            batch_id: Batch identifier
            successful_files: Number of successful files
            failed_files: Number of failed files
            status: Batch status
            error_summary: Summary of errors
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE processing_batches
            SET batch_end_time = ?, successful_files = ?, failed_files = ?, status = ?, error_summary = ?
            WHERE batch_id = ?
        """, (datetime.now().isoformat(), successful_files, failed_files, status, error_summary, batch_id))

        conn.commit()
        conn.close()

    def get_statistics(self) -> Dict:
        """
        Get processing statistics

        Returns:
            Dictionary with statistics
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # File statistics
        cursor.execute("""
            SELECT
                status,
                COUNT(*) as count,
                SUM(file_size) as total_size
            FROM files
            GROUP BY status
        """)
        file_stats = {}
        for row in cursor.fetchall():
            status, count, total_size = row
            file_stats[status] = {
                "count": count,
                "total_size": total_size or 0
            }

        # Embedding statistics
        cursor.execute("""
            SELECT
                COUNT(*) as total_embeddings,
                SUM(qdrant_uploaded) as uploaded_count
            FROM embeddings
        """)
        emb_row = cursor.fetchone()

        # Batch statistics
        cursor.execute("""
            SELECT
                COUNT(*) as total_batches,
                SUM(successful_files) as total_successful,
                SUM(failed_files) as total_failed
            FROM processing_batches
        """)
        batch_row = cursor.fetchone()

        conn.close()

        return {
            "files": file_stats,
            "embeddings": {
                "total": emb_row[0] if emb_row else 0,
                "uploaded": emb_row[1] if emb_row else 0
            },
            "batches": {
                "total": batch_row[0] if batch_row else 0,
                "successful_files": batch_row[1] if batch_row else 0,
                "failed_files": batch_row[2] if batch_row else 0
            }
        }


class BlobStorageHelper:
    """Helper class for Azure Blob Storage operations"""

    def __init__(self, container_sas_url: str):
        """
        Initialize blob storage helper

        Args:
            container_sas_url: Full SAS URL to container
        """
        self.container_sas_url = container_sas_url
        self.sas_info = self._parse_sas_url(container_sas_url)
        self.blob_service_client = BlobServiceClient(
            account_url=self.sas_info['account_url'],
            credential=self.sas_info['sas_token']
        )
        self.container_client = self.blob_service_client.get_container_client(
            self.sas_info['container_name']
        )

    @staticmethod
    def _parse_sas_url(sas_url: str) -> Dict[str, str]:
        """Parse SAS URL to extract components"""
        parsed = urlparse(sas_url)
        return {
            "account_url": f"{parsed.scheme}://{parsed.netloc}",
            "container_name": parsed.path.lstrip('/').split('/')[0] if parsed.path else None,
            "sas_token": parsed.query
        }

    def upload_file(
        self,
        local_path: str,
        blob_name: str,
        overwrite: bool = True
    ) -> str:
        """
        Upload file to blob storage

        Args:
            local_path: Local file path
            blob_name: Blob name in storage
            overwrite: Whether to overwrite existing blob

        Returns:
            Blob URL
        """
        try:
            blob_client = self.container_client.get_blob_client(blob_name)

            with open(local_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=overwrite)

            return blob_client.url
        except AzureError as e:
            logger.error(f"Error uploading to blob: {e}")
            raise

    def download_file(self, blob_name: str, local_path: str) -> str:
        """
        Download file from blob storage

        Args:
            blob_name: Blob name in storage
            local_path: Local path to save file

        Returns:
            Local file path
        """
        try:
            blob_client = self.container_client.get_blob_client(blob_name)

            with open(local_path, "wb") as file:
                blob_data = blob_client.download_blob()
                file.write(blob_data.readall())

            return local_path
        except AzureError as e:
            logger.error(f"Error downloading from blob: {e}")
            raise

    def blob_exists(self, blob_name: str) -> bool:
        """
        Check if blob exists

        Args:
            blob_name: Blob name

        Returns:
            True if exists
        """
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            return blob_client.exists()
        except AzureError:
            return False


if __name__ == "__main__":
    """Test utilities"""
    # Test metadata store
    store = SQLiteMetadataStore("test_etl.db")

    # Test file operations
    test_file_id = "test-123"
    test_hash = "abc123def456"

    added = store.add_file(
        file_id=test_file_id,
        file_name="test.pdf",
        file_hash=test_hash,
        file_size=1024,
        file_type=".pdf",
        sharepoint_path="/test/test.pdf"
    )

    print(f"File added: {added}")

    # Check existence
    exists = store.file_exists(test_hash)
    print(f"File exists: {exists is not None}")

    # Get statistics
    stats = store.get_statistics()
    print(f"Statistics: {stats}")
