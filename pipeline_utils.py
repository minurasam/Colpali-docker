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


class SharePointToBlobUploader:
   
    def __init__(
        self,
        sharepoint_site_url: str,
        sharepoint_client_id: str,
        sharepoint_client_secret: str,
        blob_connection_string: str,
        blob_container_name: str,
    ):
        """
        Initialize the SharePoint to Blob uploader.

        Args:
            sharepoint_site_url: SharePoint site URL (e.g., https://yourtenant.sharepoint.com/sites/yoursite)
            sharepoint_client_id: Azure AD App Client ID with SharePoint permissions
            sharepoint_client_secret: Azure AD App Client Secret
            blob_connection_string: Azure Storage Account connection string
            blob_container_name: Target blob container name
        """
        
        self.sharepoint_site_url = sharepoint_site_url
        self.sharepoint_client_id = sharepoint_client_id
        self.sharepoint_client_secret = sharepoint_client_secret
        self.blob_connection_string = blob_connection_string
        self.blob_container_name = blob_container_name

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
    ) -> List[Dict[str, str]]:
        """
        Transfer files from SharePoint folder to Azure Blob Storage.

        Args:
            sharepoint_folder_path: SharePoint folder path (e.g., "Shared Documents/MyFolder")
            blob_folder_prefix: Optional prefix for blob names (creates virtual folder structure)
            file_extensions: Optional list of file extensions to filter (e.g., ['.pdf', '.docx'])
            use_temp_dir: Use temporary directory for downloads (cleaned up automatically)
            delete_local_after_upload: Delete local files after successful upload

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
                try:
                    file_name = sp_file["name"]
                    server_relative_url = sp_file["server_relative_url"]

                    # Download from SharePoint
                    local_path = os.path.join(download_dir, file_name)
                    self.download_sharepoint_file(server_relative_url, local_path)

                    # Construct blob name with optional prefix
                    if blob_folder_prefix:
                        blob_name = f"{blob_folder_prefix.rstrip('/')}/{file_name}"
                    else:
                        blob_name = file_name

                    # Upload to Blob Storage
                    blob_url = self.upload_to_blob(local_path, blob_name)

                    # Record result
                    result = {
                        "file_name": file_name,
                        "sharepoint_url": server_relative_url,
                        "blob_name": blob_name,
                        "blob_url": blob_url,
                        "status": "success",
                        "size": sp_file["size"],
                    }
                    results.append(result)
                    logger.info(f"Successfully transferred: {file_name}")

                    # Delete local file if requested
                    if delete_local_after_upload and os.path.exists(local_path):
                        os.remove(local_path)

                except Exception as e:
                    logger.error(f"Failed to transfer file {sp_file.get('name', 'unknown')}: {e}")
                    results.append(
                        {
                            "file_name": sp_file.get("name", "unknown"),
                            "sharepoint_url": sp_file.get("server_relative_url", ""),
                            "status": "failed",
                            "error": str(e),
                        }
                    )

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
