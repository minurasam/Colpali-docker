# SharePoint to Azure Blob Storage Integration

This guide explains how to set up and use the SharePoint to Azure Blob Storage file transfer functionality.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Azure AD App Registration](#azure-ad-app-registration)
4. [SharePoint Configuration](#sharepoint-configuration)
5. [Azure Blob Storage Setup](#azure-blob-storage-setup)
6. [Environment Configuration](#environment-configuration)
7. [Usage Examples](#usage-examples)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The `pipeline_utils.py` module provides functionality to transfer files from SharePoint document libraries to Azure Blob Storage. This is useful for:

- Migrating documents from SharePoint to cloud storage
- Creating automated backup pipelines
- Preprocessing documents before ingestion into the ColPali API
- Syncing SharePoint folders with blob storage

**Key Features:**
- Automatic authentication with SharePoint and Azure
- File filtering by extension
- Batch file transfer
- Progress logging
- Error handling and retry logic
- Virtual folder structure support in blob storage
- Temporary file cleanup

---

## Prerequisites

1. **Azure Subscription** with permissions to:
   - Create Azure AD App Registrations
   - Create and manage Azure Storage Accounts

2. **SharePoint Access** with permissions to:
   - Access the target SharePoint site
   - Read files from the document library

3. **Python Packages** (already in requirements.txt):
   ```
   azure-storage-blob
   Office365-REST-Python-Client
   python-dotenv
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Azure AD App Registration

To access SharePoint programmatically, you need to register an application in Azure AD.

### Step 1: Create App Registration

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** > **App registrations**
3. Click **New registration**
4. Configure:
   - **Name**: `SharePoint-Blob-Integration` (or any name)
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**: Leave blank
5. Click **Register**

### Step 2: Note Application (Client) ID

- Copy the **Application (client) ID** from the Overview page
- This is your `SHAREPOINT_CLIENT_ID`

### Step 3: Create Client Secret

1. In the app registration, go to **Certificates & secrets**
2. Click **New client secret**
3. Add description: `SharePoint Access`
4. Choose expiration period (recommend: 24 months)
5. Click **Add**
6. **IMPORTANT**: Copy the secret **Value** immediately (you won't see it again)
7. This is your `SHAREPOINT_CLIENT_SECRET`

### Step 4: Configure API Permissions

1. Go to **API permissions**
2. Click **Add a permission**
3. Select **SharePoint**
4. Choose **Application permissions** (not Delegated)
5. Add these permissions:
   - `Sites.Read.All` - Read items in all site collections
   - `Sites.ReadWrite.All` - Read and write items in all site collections (if you need write access)
6. Click **Add permissions**
7. Click **Grant admin consent for [Your Organization]**
8. Confirm the consent

---

## SharePoint Configuration

### Step 1: Grant App Permissions to SharePoint Site

You need to explicitly grant the app access to your SharePoint site.

1. Navigate to your SharePoint site in browser:
   ```
   https://yourtenant.sharepoint.com/sites/yoursite
   ```

2. Go to the app permission page by appending `/_layouts/15/appinv.aspx`:
   ```
   https://yourtenant.sharepoint.com/sites/yoursite/_layouts/15/appinv.aspx
   ```

3. In the **App Id** field, paste your Client ID and click **Lookup**
4. The app details should populate automatically
5. In the **Permission Request XML** field, paste:
   ```xml
   <AppPermissionRequests AllowAppOnlyPolicy="true">
     <AppPermissionRequest Scope="http://sharepoint/content/sitecollection" Right="Read"/>
   </AppPermissionRequests>
   ```

   For read/write access, use:
   ```xml
   <AppPermissionRequests AllowAppOnlyPolicy="true">
     <AppPermissionRequest Scope="http://sharepoint/content/sitecollection" Right="FullControl"/>
   </AppPermissionRequests>
   ```

6. Click **Create**
7. Click **Trust It**

### Step 2: Find Your SharePoint Folder Path

1. Navigate to the document library in SharePoint
2. Open the folder you want to sync
3. The folder path is typically:
   - For default library: `Shared Documents` or `Documents`
   - For subfolder: `Shared Documents/MyFolder/Subfolder`
   - For custom library: `CustomLibraryName/MyFolder`

---

## Azure Blob Storage Setup

### Step 1: Create Storage Account

1. Go to [Azure Portal](https://portal.azure.com)
2. Click **Create a resource** > **Storage account**
3. Configure:
   - **Resource group**: Choose or create new
   - **Storage account name**: `colpaliblobstorage` (must be globally unique)
   - **Region**: Choose your region
   - **Performance**: Standard
   - **Redundancy**: LRS (or choose based on needs)
4. Click **Review + Create** > **Create**

### Step 2: Create Container

1. Open the storage account
2. Go to **Containers** under Data storage
3. Click **+ Container**
4. Set:
   - **Name**: `documents` (or your preferred name)
   - **Public access level**: Private (recommended)
5. Click **Create**

### Step 3: Get Connection String

1. In the storage account, go to **Access keys**
2. Click **Show keys**
3. Copy **Connection string** under **key1**
4. This is your `AZURE_STORAGE_CONNECTION_STRING`

---

## Environment Configuration

### Step 1: Configure .env File

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### Step 2: Update .env with Your Values

Edit `.env` file:

```bash
# ================================================
# SharePoint Configuration
# ================================================
SHAREPOINT_SITE_URL=https://contoso.sharepoint.com/sites/mysite
SHAREPOINT_CLIENT_ID=12345678-1234-1234-1234-123456789abc
SHAREPOINT_CLIENT_SECRET=your-secret-value-here~1234567890
SHAREPOINT_FOLDER_PATH=Shared Documents/PDFs

# ================================================
# Azure Blob Storage Configuration
# ================================================
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=colpaliblobstorage;AccountKey=yourkey==;EndpointSuffix=core.windows.net
BLOB_CONTAINER_NAME=documents
BLOB_FOLDER_PREFIX=sharepoint-pdfs
```

---

## Usage Examples

### Example 1: Basic Usage - Transfer All Files

```python
from pipeline_utils import upload_sharepoint_to_blob
import os
from dotenv import load_dotenv

load_dotenv()

# Transfer all files from SharePoint to Blob
results = upload_sharepoint_to_blob(
    sharepoint_site_url=os.getenv("SHAREPOINT_SITE_URL"),
    sharepoint_folder_path=os.getenv("SHAREPOINT_FOLDER_PATH"),
    sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
    sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
    blob_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
    blob_container_name=os.getenv("BLOB_CONTAINER_NAME"),
)

# Print results
for result in results:
    if result['status'] == 'success':
        print(f"✓ {result['file_name']} -> {result['blob_url']}")
    else:
        print(f"✗ {result['file_name']}: {result.get('error', 'Unknown error')}")
```

### Example 2: Filter by File Extensions

```python
from pipeline_utils import upload_sharepoint_to_blob
import os
from dotenv import load_dotenv

load_dotenv()

# Only transfer PDF and DOCX files
results = upload_sharepoint_to_blob(
    sharepoint_site_url=os.getenv("SHAREPOINT_SITE_URL"),
    sharepoint_folder_path="Shared Documents/Reports",
    sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
    sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
    blob_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
    blob_container_name="documents",
    blob_folder_prefix="reports",
    file_extensions=['.pdf', '.docx']  # Only these file types
)
```

### Example 3: Using the Class Directly

```python
from pipeline_utils import SharePointToBlobUploader
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize uploader
uploader = SharePointToBlobUploader(
    sharepoint_site_url=os.getenv("SHAREPOINT_SITE_URL"),
    sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
    sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
    blob_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
    blob_container_name=os.getenv("BLOB_CONTAINER_NAME"),
)

# List files first
files = uploader.list_sharepoint_files(
    folder_path="Shared Documents/Invoices",
    file_extensions=['.pdf']
)

print(f"Found {len(files)} PDF files")
for file in files:
    print(f"  - {file['name']} ({file['size']} bytes)")

# Transfer files
results = uploader.transfer_files(
    sharepoint_folder_path="Shared Documents/Invoices",
    blob_folder_prefix="invoices/2024",
    file_extensions=['.pdf']
)
```

### Example 4: Command Line Usage

Run directly from command line:

```bash
# Set environment variables
export SHAREPOINT_SITE_URL="https://contoso.sharepoint.com/sites/mysite"
export SHAREPOINT_FOLDER_PATH="Shared Documents"
export SHAREPOINT_CLIENT_ID="your-client-id"
export SHAREPOINT_CLIENT_SECRET="your-secret"
export AZURE_STORAGE_CONNECTION_STRING="your-connection-string"
export BLOB_CONTAINER_NAME="documents"

# Run the script
python pipeline_utils.py
```

### Example 5: Integration with ColPali API

```python
from pipeline_utils import upload_sharepoint_to_blob
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Step 1: Transfer files from SharePoint to Blob
print("Transferring files from SharePoint to Blob Storage...")
results = upload_sharepoint_to_blob(
    sharepoint_site_url=os.getenv("SHAREPOINT_SITE_URL"),
    sharepoint_folder_path="Shared Documents/PDFs",
    sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
    sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
    blob_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
    blob_container_name="documents",
    file_extensions=['.pdf']
)

# Step 2: Process successful uploads with ColPali API
colpali_api_url = "http://localhost:8000"

for result in results:
    if result['status'] == 'success':
        blob_url = result['blob_url']

        # Download from blob and ingest to ColPali
        # (You would need to implement blob download logic here)
        print(f"Processing: {result['file_name']}")

        # Example: Download and ingest
        # response = requests.post(
        #     f"{colpali_api_url}/ingest/pdf",
        #     files={"file": downloaded_file},
        #     data={"document_id": result['file_name']}
        # )
```

---

## Troubleshooting

### Error: "Access Denied" or "Unauthorized"

**Cause**: App doesn't have permissions to SharePoint site

**Solution**:
1. Verify you've granted admin consent in Azure AD
2. Check you've added app permissions to the specific SharePoint site via `/_layouts/15/appinv.aspx`
3. Ensure Client ID and Secret are correct
4. Try using `Sites.ReadWrite.All` instead of `Sites.Read.All`

### Error: "Connection String Invalid"

**Cause**: Azure Storage connection string is incorrect

**Solution**:
1. Go to Azure Portal > Storage Account > Access Keys
2. Copy the full connection string (not just the key)
3. Ensure no extra spaces or newlines in the `.env` file

### Error: "Container Not Found"

**Cause**: Blob container doesn't exist

**Solution**:
1. The code automatically creates the container if it doesn't exist
2. Verify the storage account connection string is correct
3. Check that the storage account name in the connection string matches your account

### Error: "Folder Not Found" in SharePoint

**Cause**: SharePoint folder path is incorrect

**Solution**:
1. Check the exact folder path in SharePoint
2. Use format: `Shared Documents/FolderName/SubFolder`
3. Path is case-sensitive
4. Don't include leading or trailing slashes

### Files Not Transferring

**Debugging steps**:

```python
from pipeline_utils import SharePointToBlobUploader
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

uploader = SharePointToBlobUploader(...)

# List files first to verify connection
files = uploader.list_sharepoint_files("Shared Documents")
print(f"Found {len(files)} files")
for file in files:
    print(f"  {file['name']}")
```

### SSL Certificate Errors

**Solution**:
```python
import os
os.environ['REQUESTS_CA_BUNDLE'] = ''  # Disable SSL verification (not recommended for production)
```

---

## Security Best Practices

1. **Never commit `.env` file** to version control
2. **Use Azure Key Vault** for production secrets
3. **Rotate client secrets** regularly (before expiration)
4. **Use managed identities** when running on Azure services
5. **Limit app permissions** to minimum required (use `Sites.Read.All` instead of `Sites.FullControl.All`)
6. **Enable blob soft delete** for accidental deletion protection
7. **Use SAS tokens** for temporary blob access instead of connection strings

---

## Performance Tips

1. **Batch processing**: The transfer happens sequentially. For large numbers of files, consider parallel processing
2. **File filtering**: Use `file_extensions` parameter to avoid transferring unnecessary files
3. **Network location**: Run closer to SharePoint/Azure regions for faster transfers
4. **Temporary directory**: The code uses temp directories for downloads, which are automatically cleaned up

---

## Additional Resources

- [Azure AD App Registration Docs](https://docs.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
- [SharePoint App Permissions](https://docs.microsoft.com/en-us/sharepoint/dev/sp-add-ins/add-in-permissions-in-sharepoint)
- [Azure Blob Storage Python SDK](https://docs.microsoft.com/en-us/azure/storage/blobs/storage-quickstart-blobs-python)
- [Office365 Python Client](https://github.com/vgrem/Office365-REST-Python-Client)

---

## Support

For issues and questions:
- Check the logs for detailed error messages
- Verify all environment variables are correctly set
- Test connectivity to both SharePoint and Azure independently
- Review Azure AD app permissions and SharePoint site permissions
