import os
import logging
from typing import List, Optional, Dict
from pathlib import Path
import tempfile
import hashlib
import sqlite3
from datetime import datetime
import json

from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.files.file import File
from azure.storage.blob import BlobServiceClient, ContainerClient
from azure.core.exceptions import AzureError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FileTracker:
    """
    SQLite-based file tracking system for batch processing and duplicate detection.

    Tracks:
    - File hash (content-based duplicate detection)
    - Processing status (pending, processing, completed, failed)
    - Timestamps (created, modified, processed)
    - Blob URLs and metadata
    """

    def __init__(self, db_path: str = "file_tracking.db"):
        """
        Initialize file tracking database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Create tracking table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_tracking (
                file_id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                file_size INTEGER,
                last_modified TEXT,
                processing_timestamp TEXT,
                completion_timestamp TEXT,
                status TEXT DEFAULT 'pending',
                blob_url TEXT,
                blob_name TEXT,
                vector_ids TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                metadata TEXT,
                UNIQUE(file_hash)
            )
        """)

        # Create indexes for faster lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_hash ON file_tracking(file_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON file_tracking(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_name ON file_tracking(file_name)")

        conn.commit()
        conn.close()
        logger.info(f"File tracking database initialized: {self.db_path}")

    def calculate_file_hash(self, file_path: str, algorithm: str = "sha256") -> str:
        """
        Calculate hash of file content.

        Args:
            file_path: Path to file
            algorithm: Hash algorithm (md5, sha256, sha1)

        Returns:
            Hexadecimal hash string
        """
        hash_func = hashlib.new(algorithm)

        with open(file_path, "rb") as f:
            # Read file in chunks to handle large files efficiently
            for chunk in iter(lambda: f.read(8192), b""):
                hash_func.update(chunk)

        return hash_func.hexdigest()

    def file_exists(self, file_hash: str) -> Optional[Dict]:
        """
        Check if file with this hash already exists in tracking DB.

        Args:
            file_hash: Hash of file content

        Returns:
            File record if exists, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM file_tracking WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def add_file(
        self,
        file_id: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        file_size: int,
        last_modified: str = None,
        metadata: Dict = None
    ) -> bool:
        """
        Add new file to tracking database.

        Args:
            file_id: Unique identifier for file
            file_name: Name of file
            file_path: Path/URL of file
            file_hash: Content hash
            file_size: Size in bytes
            last_modified: Last modified timestamp
            metadata: Additional metadata as dict

        Returns:
            True if added, False if duplicate hash exists
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
                INSERT INTO file_tracking
                (file_id, file_name, file_path, file_hash, file_size, last_modified, metadata, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (file_id, file_name, file_path, file_hash, file_size, last_modified,
                  json.dumps(metadata) if metadata else None))

            conn.commit()
            logger.info(f"Added file to tracking: {file_name} (hash: {file_hash[:16]}...)")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"File already exists in tracking: {file_name}")
            return False
        finally:
            conn.close()

    def update_status(
        self,
        file_hash: str,
        status: str,
        blob_url: str = None,
        blob_name: str = None,
        vector_ids: List[str] = None,
        error_message: str = None
    ):
        """
        Update file processing status.

        Args:
            file_hash: Hash of file
            status: New status (pending, processing, completed, failed)
            blob_url: URL of uploaded blob
            blob_name: Name of blob in storage
            vector_ids: List of vector IDs in vector database
            error_message: Error message if failed
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        timestamp = datetime.now().isoformat()

        update_fields = ["status = ?"]
        values = [status]

        if status == "processing":
            update_fields.append("processing_timestamp = ?")
            values.append(timestamp)
        elif status == "completed":
            update_fields.append("completion_timestamp = ?")
            values.append(timestamp)

        if blob_url:
            update_fields.append("blob_url = ?")
            values.append(blob_url)

        if blob_name:
            update_fields.append("blob_name = ?")
            values.append(blob_name)

        if vector_ids:
            update_fields.append("vector_ids = ?")
            values.append(json.dumps(vector_ids))

        if error_message:
            update_fields.append("error_message = ?")
            values.append(error_message)
            update_fields.append("retry_count = retry_count + 1")

        values.append(file_hash)

        query = f"UPDATE file_tracking SET {', '.join(update_fields)} WHERE file_hash = ?"
        cursor.execute(query, values)

        conn.commit()
        conn.close()

        logger.debug(f"Updated file status to '{status}' for hash: {file_hash[:16]}...")

    def get_pending_files(self, limit: int = None) -> List[Dict]:
        """
        Get files with pending status.

        Args:
            limit: Maximum number of files to return

        Returns:
            List of file records
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM file_tracking WHERE status = 'pending'"
        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def get_failed_files(self, max_retries: int = 3) -> List[Dict]:
        """
        Get failed files that haven't exceeded retry limit.

        Args:
            max_retries: Maximum number of retries allowed

        Returns:
            List of file records
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM file_tracking WHERE status = 'failed' AND retry_count < ?",
            (max_retries,)
        )
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def get_statistics(self) -> Dict:
        """
        Get processing statistics.

        Returns:
            Dictionary with counts by status
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                status,
                COUNT(*) as count,
                SUM(file_size) as total_size
            FROM file_tracking
            GROUP BY status
        """)

        stats = {
            "total": 0,
            "by_status": {}
        }

        for row in cursor.fetchall():
            status, count, total_size = row
            stats["by_status"][status] = {
                "count": count,
                "total_size": total_size or 0
            }
            stats["total"] += count

        conn.close()
        return stats

    def reset_processing_files(self):
        """Reset files stuck in 'processing' status back to 'pending'."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("UPDATE file_tracking SET status = 'pending' WHERE status = 'processing'")
        updated = cursor.rowcount

        conn.commit()
        conn.close()

        if updated > 0:
            logger.info(f"Reset {updated} files from 'processing' to 'pending'")


class SharePointToBlobUploader:
    """
    A utility class to upload files from SharePoint to Azure Blob Storage
    with batch processing and duplicate detection capabilities.
    """

    def __init__(
        self,
        sharepoint_site_url: str,
        sharepoint_client_id: str,
        sharepoint_client_secret: str,
        blob_connection_string: str,
        blob_container_name: str,
        enable_tracking: bool = True,
        tracking_db_path: str = "file_tracking.db",
    ):
        """
        Initialize the SharePoint to Blob uploader.

        Args:
            sharepoint_site_url: SharePoint site URL (e.g., https://yourtenant.sharepoint.com/sites/yoursite)
            sharepoint_client_id: Azure AD App Client ID with SharePoint permissions
            sharepoint_client_secret: Azure AD App Client Secret
            blob_connection_string: Azure Storage Account connection string
            blob_container_name: Target blob container name
            enable_tracking: Enable file tracking and duplicate detection
            tracking_db_path: Path to SQLite tracking database
        """

        self.sharepoint_site_url = sharepoint_site_url
        self.sharepoint_client_id = sharepoint_client_id
        self.sharepoint_client_secret = sharepoint_client_secret
        self.blob_connection_string = blob_connection_string
        self.blob_container_name = blob_container_name
        self.enable_tracking = enable_tracking

        # Initialize file tracker
        if self.enable_tracking:
            self.tracker = FileTracker(tracking_db_path)
        else:
            self.tracker = None

        # Initialize clients
        self._init_sharepoint_client()
        self._init_blob_client()

    def _init_sharepoint_client(self):
        # Initialize SharePoint client context
        try:
            credentials = ClientCredential(
                self.sharepoint_client_id, self.sharepoint_client_secret
            )
            self.sp_ctx = ClientContext(self.sharepoint_site_url).with_credentials(
                credentials
            )
            logger.info("SharePoint client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize SharePoint client: {e}")
            raise

    def _init_blob_client(self):
        """Initialize Azure Blob Storage client."""
        try:
            self.blob_service_client = BlobServiceClient.from_connection_string(
                self.blob_connection_string
            )
            self.container_client = self.blob_service_client.get_container_client(
                self.blob_container_name
            )

            # Create container if it doesn't exist
            if not self.container_client.exists():
                self.container_client.create_container()
                logger.info(f"Created container: {self.blob_container_name}")
            else:
                logger.info(f"Container exists: {self.blob_container_name}")

        except AzureError as e:
            logger.error(f"Failed to initialize Blob Storage client: {e}")
            raise

    def list_sharepoint_files(
        self, folder_path: str, file_extensions: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        """
        List files in a SharePoint folder.

        Args:
            folder_path: Relative path to SharePoint folder (e.g., "Shared Documents/MyFolder")
            file_extensions: Optional list of file extensions to filter (e.g., ['.pdf', '.docx'])

        Returns:
            List of dictionaries containing file information (name, url, server_relative_url)
        """
        try:
            folder = self.sp_ctx.web.get_folder_by_server_relative_url(folder_path)
            files = folder.files
            self.sp_ctx.load(files)
            self.sp_ctx.execute_query()

            file_list = []
            for file in files:
                file_info = {
                    "name": file.properties["Name"],
                    "server_relative_url": file.properties["ServerRelativeUrl"],
                    "size": file.properties["Length"],
                    "time_created": str(file.properties.get("TimeCreated", "")),
                    "time_modified": str(file.properties.get("TimeLastModified", "")),
                }

                # Filter by extension if specified
                if file_extensions:
                    _, ext = os.path.splitext(file_info["name"])
                    if ext.lower() in [e.lower() for e in file_extensions]:
                        file_list.append(file_info)
                else:
                    file_list.append(file_info)

            logger.info(f"Found {len(file_list)} files in SharePoint folder: {folder_path}")
            return file_list

        except Exception as e:
            logger.error(f"Error listing SharePoint files: {e}")
            raise

    def download_sharepoint_file(
        self, server_relative_url: str, local_path: str
    ) -> str:
        """
        Download a file from SharePoint to local storage.

        Args:
            server_relative_url: Server relative URL of the file
            local_path: Local path where file will be saved

        Returns:
            Path to the downloaded file
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            # Download file
            with open(local_path, "wb") as local_file:
                file = (
                    self.sp_ctx.web.get_file_by_server_relative_url(
                        server_relative_url
                    )
                    .download(local_file)
                    .execute_query()
                )

            logger.info(f"Downloaded file from SharePoint: {server_relative_url} -> {local_path}")
            return local_path

        except Exception as e:
            logger.error(f"Error downloading file from SharePoint: {e}")
            raise

    def upload_to_blob(
        self, local_file_path: str, blob_name: Optional[str] = None, overwrite: bool = True
    ) -> str:
        """
        Upload a local file to Azure Blob Storage.

        Args:
            local_file_path: Path to the local file
            blob_name: Name for the blob (if None, uses the file name)
            overwrite: Whether to overwrite existing blob

        Returns:
            URL of the uploaded blob
        """
        try:
            if blob_name is None:
                blob_name = os.path.basename(local_file_path)

            blob_client = self.container_client.get_blob_client(blob_name)

            with open(local_file_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=overwrite)

            blob_url = blob_client.url
            logger.info(f"Uploaded file to blob: {blob_name} -> {blob_url}")
            return blob_url

        except AzureError as e:
            logger.error(f"Error uploading file to blob: {e}")
            raise

    def transfer_files(
        self,
        sharepoint_folder_path: str,
        blob_folder_prefix: Optional[str] = None,
        file_extensions: Optional[List[str]] = None,
        use_temp_dir: bool = True,
        delete_local_after_upload: bool = True,
        skip_duplicates: bool = True,
    ) -> List[Dict[str, str]]:
        """
        Transfer files from SharePoint folder to Azure Blob Storage with duplicate detection.

        Args:
            sharepoint_folder_path: SharePoint folder path (e.g., "Shared Documents/MyFolder")
            blob_folder_prefix: Optional prefix for blob names (creates virtual folder structure)
            file_extensions: Optional list of file extensions to filter (e.g., ['.pdf', '.docx'])
            use_temp_dir: Use temporary directory for downloads (cleaned up automatically)
            delete_local_after_upload: Delete local files after successful upload
            skip_duplicates: Skip files that already exist (based on content hash)

        Returns:
            List of dictionaries with upload results
        """
        results = []

        try:
            # List files in SharePoint
            sp_files = self.list_sharepoint_files(sharepoint_folder_path, file_extensions)
            logger.info(f"Starting transfer of {len(sp_files)} files")

            # Create temp directory if needed
            temp_dir = None
            if use_temp_dir:
                temp_dir = tempfile.mkdtemp()
                download_dir = temp_dir
            else:
                download_dir = "./downloads"
                os.makedirs(download_dir, exist_ok=True)

            # Process each file
            for sp_file in sp_files:
                file_name = sp_file["name"]
                server_relative_url = sp_file["server_relative_url"]
                file_hash = None

                try:
                    # Download from SharePoint
                    local_path = os.path.join(download_dir, file_name)
                    self.download_sharepoint_file(server_relative_url, local_path)

                    # Calculate file hash for duplicate detection
                    if self.enable_tracking:
                        file_hash = self.tracker.calculate_file_hash(local_path)

                        # Check if file already exists
                        if skip_duplicates:
                            existing = self.tracker.file_exists(file_hash)
                            if existing:
                                logger.info(f"Skipping duplicate file: {file_name} (already processed as {existing['file_name']})")
                                results.append({
                                    "file_name": file_name,
                                    "sharepoint_url": server_relative_url,
                                    "status": "skipped",
                                    "reason": "duplicate",
                                    "existing_blob_url": existing.get("blob_url"),
                                    "file_hash": file_hash[:16] + "..."
                                })
                                # Delete local file
                                if os.path.exists(local_path):
                                    os.remove(local_path)
                                continue

                        # Add file to tracking database
                        file_id = f"{sharepoint_folder_path}/{file_name}"
                        self.tracker.add_file(
                            file_id=file_id,
                            file_name=file_name,
                            file_path=server_relative_url,
                            file_hash=file_hash,
                            file_size=sp_file["size"],
                            last_modified=sp_file.get("time_modified"),
                            metadata={
                                "sharepoint_folder": sharepoint_folder_path,
                                "time_created": sp_file.get("time_created")
                            }
                        )

                        # Update status to processing
                        self.tracker.update_status(file_hash, "processing")

                    # Construct blob name with optional prefix
                    if blob_folder_prefix:
                        blob_name = f"{blob_folder_prefix.rstrip('/')}/{file_name}"
                    else:
                        blob_name = file_name

                    # Upload to Blob Storage
                    blob_url = self.upload_to_blob(local_path, blob_name)

                    # Update tracking status to completed
                    if self.enable_tracking and file_hash:
                        self.tracker.update_status(
                            file_hash,
                            "completed",
                            blob_url=blob_url,
                            blob_name=blob_name
                        )

                    # Record result
                    result = {
                        "file_name": file_name,
                        "sharepoint_url": server_relative_url,
                        "blob_name": blob_name,
                        "blob_url": blob_url,
                        "status": "success",
                        "size": sp_file["size"],
                        "file_hash": file_hash[:16] + "..." if file_hash else None
                    }
                    results.append(result)
                    logger.info(f"Successfully transferred: {file_name}")

                    # Delete local file if requested
                    if delete_local_after_upload and os.path.exists(local_path):
                        os.remove(local_path)

                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Failed to transfer file {file_name}: {error_msg}")

                    # Update tracking status to failed
                    if self.enable_tracking and file_hash:
                        self.tracker.update_status(
                            file_hash,
                            "failed",
                            error_message=error_msg
                        )

                    results.append({
                        "file_name": file_name,
                        "sharepoint_url": server_relative_url,
                        "status": "failed",
                        "error": error_msg,
                    })

            # Cleanup temp directory
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
                logger.info("Cleaned up temporary directory")

            # Summary
            success_count = sum(1 for r in results if r["status"] == "success")
            logger.info(
                f"Transfer complete: {success_count}/{len(results)} files succeeded"
            )

            return results

        except Exception as e:
            logger.error(f"Error during file transfer: {e}")
            raise

    def process_batch(
        self,
        sharepoint_folder_path: str,
        blob_folder_prefix: Optional[str] = None,
        file_extensions: Optional[List[str]] = None,
        batch_size: int = 10,
        resume_failed: bool = True,
    ) -> Dict:
        """
        Process files in batches with resume capability.

        Args:
            sharepoint_folder_path: SharePoint folder path
            blob_folder_prefix: Optional prefix for blob names
            file_extensions: Optional list of file extensions to filter
            batch_size: Number of files to process per batch
            resume_failed: Retry previously failed files

        Returns:
            Dictionary with batch processing results and statistics
        """
        if not self.enable_tracking:
            raise ValueError("Batch processing requires tracking to be enabled")

        logger.info("Starting batch processing...")

        # Reset any files stuck in 'processing' status
        self.tracker.reset_processing_files()

        # Get pending files
        pending_files = self.tracker.get_pending_files()
        logger.info(f"Found {len(pending_files)} pending files")

        # Get failed files if resume is enabled
        failed_files = []
        if resume_failed:
            failed_files = self.tracker.get_failed_files()
            logger.info(f"Found {len(failed_files)} failed files to retry")

        # Combine pending and failed files
        all_files = pending_files + failed_files

        if not all_files:
            logger.info("No files to process")
            return {"status": "complete", "files_processed": 0}

        # Process in batches
        total_batches = (len(all_files) + batch_size - 1) // batch_size
        results = []

        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min((batch_num + 1) * batch_size, len(all_files))
            batch = all_files[start_idx:end_idx]

            logger.info(f"Processing batch {batch_num + 1}/{total_batches} ({len(batch)} files)")

            # Process batch using transfer_files
            batch_results = self.transfer_files(
                sharepoint_folder_path=sharepoint_folder_path,
                blob_folder_prefix=blob_folder_prefix,
                file_extensions=file_extensions,
                skip_duplicates=True,
            )

            results.extend(batch_results)

        # Get final statistics
        stats = self.get_tracking_stats()

        return {
            "status": "complete",
            "total_files": len(all_files),
            "files_processed": len(results),
            "statistics": stats,
            "results": results
        }

    def get_tracking_stats(self) -> Dict:
        """
        Get file tracking statistics.

        Returns:
            Dictionary with statistics by status
        """
        if not self.enable_tracking:
            return {"error": "Tracking not enabled"}

        return self.tracker.get_statistics()

    def retry_failed_files(
        self,
        sharepoint_folder_path: str,
        blob_folder_prefix: Optional[str] = None,
        max_retries: int = 3,
    ) -> List[Dict]:
        """
        Retry previously failed file transfers.

        Args:
            sharepoint_folder_path: SharePoint folder path
            blob_folder_prefix: Optional prefix for blob names
            max_retries: Maximum number of retries per file

        Returns:
            List of retry results
        """
        if not self.enable_tracking:
            raise ValueError("Retry functionality requires tracking to be enabled")

        failed_files = self.tracker.get_failed_files(max_retries=max_retries)

        if not failed_files:
            logger.info("No failed files to retry")
            return []

        logger.info(f"Retrying {len(failed_files)} failed files")

        # Extract file info and process
        results = []
        for failed_file in failed_files:
            try:
                logger.info(f"Retrying: {failed_file['file_name']}")

                # Download and upload using existing methods
                # This is a simplified retry - you may want to enhance this
                file_name = failed_file['file_name']
                server_relative_url = failed_file['file_path']

                # Use temp directory
                with tempfile.TemporaryDirectory() as temp_dir:
                    local_path = os.path.join(temp_dir, file_name)
                    self.download_sharepoint_file(server_relative_url, local_path)

                    # Calculate hash and update status
                    file_hash = self.tracker.calculate_file_hash(local_path)
                    self.tracker.update_status(file_hash, "processing")

                    # Construct blob name
                    if blob_folder_prefix:
                        blob_name = f"{blob_folder_prefix.rstrip('/')}/{file_name}"
                    else:
                        blob_name = file_name

                    # Upload
                    blob_url = self.upload_to_blob(local_path, blob_name)

                    # Update to completed
                    self.tracker.update_status(
                        file_hash,
                        "completed",
                        blob_url=blob_url,
                        blob_name=blob_name
                    )

                    results.append({
                        "file_name": file_name,
                        "status": "success",
                        "blob_url": blob_url
                    })

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Retry failed for {failed_file['file_name']}: {error_msg}")

                # Update failed status
                file_hash = failed_file['file_hash']
                self.tracker.update_status(
                    file_hash,
                    "failed",
                    error_message=error_msg
                )

                results.append({
                    "file_name": failed_file['file_name'],
                    "status": "failed",
                    "error": error_msg
                })

        return results


def upload_sharepoint_to_blob(
    sharepoint_site_url: str,
    sharepoint_folder_path: str,
    sharepoint_client_id: str,
    sharepoint_client_secret: str,
    blob_connection_string: str,
    blob_container_name: str,
    blob_folder_prefix: Optional[str] = None,
    file_extensions: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """
    Convenience function to upload files from SharePoint to Azure Blob Storage.

    Args:
        sharepoint_site_url: SharePoint site URL
        sharepoint_folder_path: SharePoint folder path to upload from
        sharepoint_client_id: Azure AD App Client ID
        sharepoint_client_secret: Azure AD App Client Secret
        blob_connection_string: Azure Storage connection string
        blob_container_name: Target blob container name
        blob_folder_prefix: Optional prefix for blob names
        file_extensions: Optional list of file extensions to filter (e.g., ['.pdf', '.docx'])

    Returns:
        List of upload results

    Example:
        ```python
        from pipeline_utils import upload_sharepoint_to_blob

        results = upload_sharepoint_to_blob(
            sharepoint_site_url="https://contoso.sharepoint.com/sites/mysite",
            sharepoint_folder_path="Shared Documents/PDFs",
            sharepoint_client_id="your-client-id",
            sharepoint_client_secret="your-client-secret",
            blob_connection_string="DefaultEndpointsProtocol=https;...",
            blob_container_name="documents",
            blob_folder_prefix="pdfs",
            file_extensions=['.pdf']
        )

        for result in results:
            if result['status'] == 'success':
                print(f"Uploaded: {result['file_name']} -> {result['blob_url']}")
            else:
                print(f"Failed: {result['file_name']} - {result.get('error', 'Unknown error')}")
        ```
    """
    uploader = SharePointToBlobUploader(
        sharepoint_site_url=sharepoint_site_url,
        sharepoint_client_id=sharepoint_client_id,
        sharepoint_client_secret=sharepoint_client_secret,
        blob_connection_string=blob_connection_string,
        blob_container_name=blob_container_name,
    )

    return uploader.transfer_files(
        sharepoint_folder_path=sharepoint_folder_path,
        blob_folder_prefix=blob_folder_prefix,
        file_extensions=file_extensions,
    )


if __name__ == "__main__":
    """
    Example usage with environment variables.

    Required environment variables:
    - SHAREPOINT_SITE_URL
    - SHAREPOINT_CLIENT_ID
    - SHAREPOINT_CLIENT_SECRET
    - SHAREPOINT_FOLDER_PATH
    - AZURE_STORAGE_CONNECTION_STRING
    - BLOB_CONTAINER_NAME
    """
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Example configuration
    results = upload_sharepoint_to_blob(
        sharepoint_site_url=os.getenv("SHAREPOINT_SITE_URL"),
        sharepoint_folder_path=os.getenv("SHAREPOINT_FOLDER_PATH", "Shared Documents"),
        sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
        sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
        blob_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
        blob_container_name=os.getenv("BLOB_CONTAINER_NAME", "documents"),
        blob_folder_prefix=os.getenv("BLOB_FOLDER_PREFIX"),
        file_extensions=[".pdf", ".docx", ".xlsx"],  # Optional: filter by extensions
    )

    # Print results
    print(f"\nTransfer Summary:")
    print(f"Total files: {len(results)}")
    print(f"Successful: {sum(1 for r in results if r['status'] == 'success')}")
    print(f"Failed: {sum(1 for r in results if r['status'] == 'failed')}")
