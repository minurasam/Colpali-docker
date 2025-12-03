"""
SharePoint to Azure Blob Storage sync utility with SQLite file tracking.
Simplified version that focuses only on download from SharePoint and upload to Blob.
"""

import os
from typing import List, Dict, Optional
from dotenv import load_dotenv
from urllib.parse import urlparse
from pipeline_utils import SharePointToBlobUploader
from azure.storage.blob import BlobServiceClient
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def parse_sas_url(sas_url: str) -> Dict[str, str]:
    """
    Parse SAS URL to extract connection components.

    Args:
        sas_url: Full SAS URL (e.g., https://account.blob.core.windows.net/container?sv=...)

    Returns:
        Dictionary with account_url, container_name, and sas_token
    """
    parsed = urlparse(sas_url)

    # Extract account URL (scheme + netloc)
    account_url = f"{parsed.scheme}://{parsed.netloc}"

    # Extract container name from path
    container_name = parsed.path.lstrip('/').split('/')[0] if parsed.path else None

    # Extract SAS token (query string)
    sas_token = parsed.query

    return {
        "account_url": account_url,
        "container_name": container_name,
        "sas_token": sas_token,
        "full_url": sas_url
    }


class SharePointBlobSync:
    """
    Simplified SharePoint to Blob sync with SQLite file tracking.
    """

    def __init__(
        self,
        client_id: str = None,
        client_secret: str = None,
        site_url: str = None,
        drive_path: str = None,
        container_sas_url: str = None,
        tracking_db_path: str = "file_tracking.db"
    ):
        """
        Initialize sync with environment variables.

        Args:
            client_id: Azure AD App Client ID
            client_secret: Azure AD App Client Secret
            site_url: SharePoint site URL
            drive_path: SharePoint drive/folder path
            container_sas_url: Azure Blob Container SAS URL
            tracking_db_path: Path to SQLite tracking database
        """
        # Load from environment if not provided
        load_dotenv()

        self.client_id = client_id or os.getenv("CLIENT_ID")
        self.client_secret = client_secret or os.getenv("CLIENT_SECRET")
        self.site_url = site_url or os.getenv("SITE_URL")
        self.drive_path = drive_path or os.getenv("DRIVE_PATH", "Shared Documents")
        self.container_sas_url = container_sas_url or os.getenv("CONTAINER_SAS_URL")

        # Validate required fields
        if not all([self.client_id, self.client_secret, self.site_url, self.container_sas_url]):
            raise ValueError("Missing required environment variables. Check .env file.")

        # Parse SAS URL
        self.sas_info = parse_sas_url(self.container_sas_url)
        logger.info(f"Blob storage account: {self.sas_info['account_url']}")
        logger.info(f"Container: {self.sas_info['container_name']}")

        # Initialize blob client with SAS
        self.blob_service_client = BlobServiceClient(
            account_url=self.sas_info['account_url'],
            credential=self.sas_info['sas_token']
        )

        # Initialize SharePoint uploader
        self.uploader = SharePointToBlobUploader(
            sharepoint_site_url=self.site_url,
            sharepoint_client_id=self.client_id,
            sharepoint_client_secret=self.client_secret,
            blob_service_client=self.blob_service_client,
            blob_container_name=self.sas_info['container_name'],
            tracking_db_path=tracking_db_path
        )

        # Reference to tracker
        self.tracker = self.uploader.tracker

    def sync_files(
        self,
        file_extensions: Optional[List[str]] = None,
        blob_folder_prefix: Optional[str] = None,
        skip_duplicates: bool = True
    ) -> List[Dict]:
        """
        Sync files from SharePoint to Blob Storage.

        Args:
            file_extensions: List of file extensions to sync (e.g., ['.pdf', '.docx'])
            blob_folder_prefix: Optional prefix for blob names
            skip_duplicates: Skip duplicate files based on content hash

        Returns:
            List of sync results
        """
        logger.info(f"Starting sync from SharePoint: {self.site_url}/{self.drive_path}")
        logger.info(f"Target blob container: {self.sas_info['container_name']}")

        results = self.uploader.transfer_files(
            sharepoint_folder_path=self.drive_path,
            blob_folder_prefix=blob_folder_prefix or os.getenv("BLOB_FOLDER_PREFIX"),
            file_extensions=file_extensions,
            skip_duplicates=skip_duplicates
        )

        return results

    def get_stats(self) -> Dict:
        """Get sync statistics from SQLite database."""
        return self.tracker.get_statistics()


def main():
    """
    Main function for command-line usage.
    Syncs files from SharePoint to Azure Blob Storage with SQLite tracking.
    """
    # Load environment variables
    load_dotenv()

    # Check required variables
    required_vars = ["CLIENT_ID", "CLIENT_SECRET", "SITE_URL", "CONTAINER_SAS_URL"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print("Missing required environment variables:")
        for var in missing:
            print(f"   - {var}")
        print("\nPlease set these in your .env file")
        return

    print("\n" + "="*60)
    print("SharePoint to Azure Blob Storage Sync (SQLite Tracking)")
    print("="*60)

    try:
        # Initialize sync
        sync = SharePointBlobSync()

        print(f"\nSharePoint Site: {sync.site_url}")
        print(f"Drive Path: {sync.drive_path}")
        print(f"Blob Container: {sync.sas_info['container_name']}")
        print(f"Blob Account: {sync.sas_info['account_url']}")

        # Sync PDF files (you can change extensions as needed)
        print("\n" + "-"*60)
        print("Syncing files from SharePoint...")
        print("-"*60)

        results = sync.sync_files(
            file_extensions=[".pdf", ".docx", ".xlsx"],  # Customize as needed
            skip_duplicates=True
        )

        # Print results
        print(f"\nSync Results:")
        print(f"   Total files processed: {len(results)}")

        success = sum(1 for r in results if r['status'] == 'success')
        skipped = sum(1 for r in results if r['status'] == 'skipped')
        failed = sum(1 for r in results if r['status'] == 'failed')

        print(f"   Successful: {success}")
        print(f"   Skipped (duplicates): {skipped}")
        print(f"   Failed: {failed}")

        # Show details
        if results:
            print(f"\nFile Details:")
            for result in results[:10]:  # Show first 10
                status_icon = "[OK]" if result['status'] == 'success' else "[SKIP]" if result['status'] == 'skipped' else "[FAIL]"
                print(f"   {status_icon} {result['file_name']}: {result['status']}")
                if result['status'] == 'skipped' and 'existing_blob_url' in result:
                    print(f"      Already exists in blob storage")

            if len(results) > 10:
                print(f"   ... and {len(results) - 10} more files")

        # Get statistics from SQLite database
        print(f"\nDatabase Statistics:")
        stats = sync.get_stats()
        print(f"   Total files tracked: {stats['total']}")
        for status, info in stats.get('by_status', {}).items():
            size_mb = info['total_size'] / 1024 / 1024 if info['total_size'] else 0
            print(f"   {status}: {info['count']} files ({size_mb:.2f} MB)")

        print("\n" + "="*60)
        print("Sync completed successfully!")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\nError during sync: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
