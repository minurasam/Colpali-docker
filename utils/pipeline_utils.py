import os
import logging
from typing import List, Optional, Dict
import tempfile
import hashlib
import sqlite3
from datetime import datetime
import json

from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.client_credential import ClientCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import AzureError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FileTracker:
    """
    SQLite-based file tracking system for SharePoint to Blob sync.

    Tracks:
    - File hash (content-based duplicate detection)
    - Processing status (pending, completed, failed)
    - Timestamps (uploaded, modified)
    - Blob URLs and SharePoint metadata
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
                sharepoint_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                file_size INTEGER,
                sharepoint_modified TEXT,
                upload_timestamp TEXT,
                status TEXT DEFAULT 'pending',
                blob_url TEXT,
                blob_name TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
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
        sharepoint_path: str,
        file_hash: str,
        file_size: int,
        sharepoint_modified: str = None
    ) -> bool:
        """
        Add new file to tracking database.

        Args:
            file_id: Unique identifier for file
            file_name: Name of file
            sharepoint_path: SharePoint path/URL of file
            file_hash: Content hash
            file_size: Size in bytes
            sharepoint_modified: Last modified timestamp from SharePoint

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
                (file_id, file_name, sharepoint_path, file_hash, file_size, sharepoint_modified, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """, (file_id, file_name, sharepoint_path, file_hash, file_size, sharepoint_modified))

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
        error_message: str = None
    ):
        """
        Update file processing status.

        Args:
            file_hash: Hash of file
            status: New status (pending, completed, failed)
            blob_url: URL of uploaded blob
            blob_name: Name of blob in storage
            error_message: Error message if failed
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        timestamp = datetime.now().isoformat()

        update_fields = ["status = ?"]
        values = [status]

        if status == "completed":
            update_fields.append("upload_timestamp = ?")
            values.append(timestamp)

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



class SharePointToBlobUploader:
    """
    Simplified utility class to upload files from SharePoint to Azure Blob Storage
    with SQLite-based file tracking and duplicate detection.
    """

    def __init__(
        self,
        sharepoint_site_url: str,
        sharepoint_client_id: str,
        sharepoint_client_secret: str,
        blob_service_client: BlobServiceClient,
        blob_container_name: str,
        tracking_db_path: str = "file_tracking.db",
    ):
        """
        Initialize the SharePoint to Blob uploader.

        Args:
            sharepoint_site_url: SharePoint site URL
            sharepoint_client_id: Azure AD App Client ID with SharePoint permissions
            sharepoint_client_secret: Azure AD App Client Secret
            blob_service_client: Azure Blob Service Client (configured with SAS or connection string)
            blob_container_name: Target blob container name
            tracking_db_path: Path to SQLite tracking database
        """

        self.sharepoint_site_url = sharepoint_site_url
        self.sharepoint_client_id = sharepoint_client_id
        self.sharepoint_client_secret = sharepoint_client_secret
        self.blob_container_name = blob_container_name

        # Initialize file tracker
        self.tracker = FileTracker(tracking_db_path)

        # Initialize clients
        self._init_sharepoint_client()
        self.blob_service_client = blob_service_client
        self.container_client = self.blob_service_client.get_container_client(
            self.blob_container_name
        )

        # Verify container exists
        if self.container_client.exists():
            logger.info(f"Connected to container: {self.blob_container_name}")
        else:
            logger.warning(f"Container does not exist: {self.blob_container_name}")

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
                        sharepoint_path=server_relative_url,
                        file_hash=file_hash,
                        file_size=sp_file["size"],
                        sharepoint_modified=sp_file.get("time_modified")
                    )

                    # Construct blob name with optional prefix
                    if blob_folder_prefix:
                        blob_name = f"{blob_folder_prefix.rstrip('/')}/{file_name}"
                    else:
                        blob_name = file_name

                    # Upload to Blob Storage
                    blob_url = self.upload_to_blob(local_path, blob_name)

                    # Update tracking status to completed
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
                    if file_hash:
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

    def get_tracking_stats(self) -> Dict:
        """
        Get file tracking statistics.

        Returns:
            Dictionary with statistics by status
        """
        return self.tracker.get_statistics()


