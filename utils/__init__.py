"""
SharePoint to Azure Blob Storage utilities.

This package provides tools for syncing files from SharePoint to Azure Blob Storage
with batch processing, duplicate detection, and file tracking capabilities.
"""

from .pipeline_utils import (
    FileTracker,
    SharePointToBlobUploader,
    upload_sharepoint_to_blob,
)

from .sharepoint_sync import (
    SharePointBlobSync,
    parse_sas_url,
)

__all__ = [
    "FileTracker",
    "SharePointToBlobUploader",
    "upload_sharepoint_to_blob",
    "SharePointBlobSync",
    "parse_sas_url",
]

__version__ = "1.0.0"
