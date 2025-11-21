# Testing Guide - ColPali API

This guide covers both **Local Qdrant** and **Qdrant Cloud** configurations.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Local Qdrant Testing](#local-qdrant-testing)
3. [Qdrant Cloud Testing](#qdrant-cloud-testing)
4. [Testing with Postman](#testing-with-postman)
5. [Testing with cURL](#testing-with-curl)
6. [Testing with FastAPI Swagger UI](#testing-with-fastapi-swagger-ui)
7. [Verifying Qdrant Storage](#verifying-qdrant-storage)
8. [Monitoring Logs](#monitoring-logs)
9. [Troubleshooting](#troubleshooting)
10. [Cleanup](#cleanup)

---

## Quick Start

| Mode | Command |
|------|---------|
| **Local Qdrant** | `docker-compose up --build` |
| **Qdrant Cloud** | `docker-compose -f docker-compose.cloud.yml --env-file .env up --build` |

---

# Local Qdrant Testing

## Step 1: Start the Services

Navigate to the project directory and start Docker Compose:

```bash
cd colpali-docker
docker-compose up --build
```

**What happens:**
- Qdrant vector database starts on ports 6333 (HTTP) and 6334 (gRPC)
- ColPali API builds the Docker image (first time will take 10-15 minutes to download model)
- API starts on port 8000

**Wait for this message:**
```
colpali-api  | INFO:     Application startup complete.
colpali-api  | INFO:     Uvicorn running on http://0.0.0.0:8000
```

## Step 2: Verify Services

Open a new terminal and run:

```bash
# Check running containers
docker ps

# Check API health
curl http://localhost:8000/health

# Check Qdrant
curl http://localhost:6333
```

Expected health response:
```json
{
  "status": "healthy",
  "model_loaded": true,
  "qdrant_connected": true,
  "device": "cpu"
}
```

## Step 3: Access Web Interfaces

- **FastAPI Swagger UI**: http://localhost:8000/docs
- **FastAPI ReDoc**: http://localhost:8000/redoc
- **Qdrant Dashboard**: http://localhost:6333/dashboard

## Local Configuration

The local setup uses `docker-compose.yml` which includes:

```yaml
environment:
  - QDRANT_HOST=qdrant
  - QDRANT_PORT=6333
  - COLLECTION_NAME=colpali_embeddings
```

No additional configuration required.

---

# Qdrant Cloud Testing

## Step 1: Create `.env` File

Copy the example environment file:

```bash
cp .env.example .env
```

## Step 2: Configure Qdrant Cloud Credentials

Edit `.env` with your Qdrant Cloud credentials:

```env
# Qdrant Cloud Configuration
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your-api-key-here
COLLECTION_NAME=colpali-embeddings-128
```

**Where to get credentials:**
1. Log into [Qdrant Cloud](https://cloud.qdrant.io/)
2. Select your cluster
3. Copy the **Cluster URL**
4. Go to **API Keys** and create/copy your API key

**Important Notes:**
- ColPali generates **128-dimensional** embeddings
- Use a collection name that doesn't exist, or one configured for 128 dimensions
- If you get a dimension error, change `COLLECTION_NAME` to a new name

## Step 3: Start with Cloud Configuration

```bash
docker-compose -f docker-compose.cloud.yml --env-file .env up --build
```

Or run in background (detached mode):

```bash
docker-compose -f docker-compose.cloud.yml --env-file .env up --build -d
```

**Wait for this message:**
```
colpali-api  | INFO:     Application startup complete.
colpali-api  | INFO:     Uvicorn running on http://0.0.0.0:8000
```

## Step 4: Verify Cloud Connection

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "model_loaded": true,
  "qdrant_connected": true,
  "device": "cpu"
}
```

## Cloud Configuration Summary

| File | Purpose |
|------|---------|
| `.env` | Your Qdrant Cloud credentials |
| `docker-compose.cloud.yml` | Cloud-specific Docker setup (no local Qdrant) |

## Environment Variables Reference

| Variable | Description | Required |
|----------|-------------|----------|
| `QDRANT_URL` | Full URL to Qdrant Cloud (e.g., `https://xxx.cloud.qdrant.io:6333`) | Yes |
| `QDRANT_API_KEY` | API key from Qdrant Cloud dashboard | Yes |
| `COLLECTION_NAME` | Name of the vector collection | Optional (default: `colpali_embeddings`) |

---

# Testing with Postman

Works the same for both Local and Cloud setups.

## Import the Collection

1. Open Postman
2. Click **Import** (top left)
3. Select **File** > Choose `ColPali-API.postman_collection.json`
4. The collection will appear in your Collections tab

## Collection Structure

| Request | Method | Endpoint | Description |
|---------|--------|----------|-------------|
| Health Check | GET | `/health` | Verify API is running |
| List Documents | GET | `/documents` | See all ingested documents |
| Ingest PDF | POST | `/ingest/pdf` | Upload PDF file |
| Ingest Image | POST | `/ingest/image` | Upload image file |
| Delete Document | DELETE | `/document/{id}` | Remove document by ID |

## Variables

The collection uses these variables:
- `base_url`: `http://localhost:8000` (default)
- `document_id`: Set manually for delete operations

## Testing Workflow

### 1. Health Check
- Select "Health Check" request
- Click **Send**
- Verify response shows `"status": "healthy"`

### 2. Upload a PDF
- Select "Ingest PDF" request
- Go to **Body** tab
- Click on the `file` field and select a PDF from your computer
- (Optional) Enable `document_id` field and provide custom ID
- Click **Send**
- **Save the `document_id`** from the response

Example response:
```json
{
  "document_id": "abc123-def456",
  "filename": "sample.pdf",
  "total_pages": 5,
  "embedding_dimension": 128,
  "tokens_per_page": 1024,
  "message": "Successfully ingested PDF with 5 pages"
}
```

### 3. Upload an Image
- Select "Ingest Image" request
- Go to **Body** tab
- Click on the `file` field and select an image (PNG, JPG, etc.)
- Click **Send**

### 4. List Documents
- Select "List Documents" request
- Click **Send**
- See all ingested documents

### 5. Delete Document
- Select "Delete Document" request
- Manually edit URL: `http://localhost:8000/document/YOUR_DOCUMENT_ID`
- Click **Send**

---

# Testing with cURL

Works the same for both Local and Cloud setups.

### Health Check
```bash
curl http://localhost:8000/health
```

### Upload PDF
```bash
curl -X POST http://localhost:8000/ingest/pdf \
  -F "file=@path/to/your/document.pdf"
```

### Upload Image
```bash
curl -X POST http://localhost:8000/ingest/image \
  -F "file=@path/to/your/image.png"
```

### List Documents
```bash
curl http://localhost:8000/documents
```

### Delete Document
```bash
curl -X DELETE http://localhost:8000/document/YOUR_DOCUMENT_ID
```

---

# Testing with FastAPI Swagger UI

Works the same for both Local and Cloud setups.

1. Navigate to http://localhost:8000/docs
2. You'll see an interactive API documentation
3. Click on any endpoint to expand it
4. Click **Try it out**
5. Fill in parameters or upload files
6. Click **Execute**
7. View the response below

**Advantages:**
- No additional tools needed
- Interactive documentation
- Test directly in browser
- See request/response schemas

---

# Verifying Qdrant Storage

## Local Qdrant

### Via Dashboard
1. Go to http://localhost:6333/dashboard
2. Click on **Collections**
3. Select `colpali_embeddings`
4. View stored vectors and payloads

### Via API
```bash
# Get collection info
curl http://localhost:6333/collections/colpali_embeddings

# Scroll through vectors
curl -X POST http://localhost:6333/collections/colpali_embeddings/points/scroll \
  -H "Content-Type: application/json" \
  -d '{"limit": 10, "with_payload": true, "with_vector": false}'
```

## Qdrant Cloud

### Via Dashboard
1. Log into your Qdrant Cloud account
2. Navigate to your cluster
3. Open the Dashboard
4. Select your collection (e.g., `colpali-embeddings-128`)
5. View stored vectors and payloads

### Via API
```bash
# Get collection info
curl "https://your-cluster.cloud.qdrant.io:6333/collections/colpali-embeddings-128" \
  -H "api-key: YOUR_API_KEY"

# Scroll through vectors
curl -X POST "https://your-cluster.cloud.qdrant.io:6333/collections/colpali-embeddings-128/points/scroll" \
  -H "Content-Type: application/json" \
  -H "api-key: YOUR_API_KEY" \
  -d '{"limit": 10, "with_payload": true, "with_vector": false}'
```

---

# Monitoring Logs

## Local Setup

```bash
# View all logs
docker-compose logs -f

# View only API logs
docker-compose logs -f colpali-api

# View only Qdrant logs
docker-compose logs -f qdrant
```

## Cloud Setup

```bash
# View API logs
docker-compose -f docker-compose.cloud.yml logs -f colpali-api
```

---

# Troubleshooting

## Common Issues (Both Local and Cloud)

### API not starting
```bash
# Check logs
docker-compose logs colpali-api

# Common issues:
# - Model download in progress (wait 10-15 min first time)
# - GPU not available (will fall back to CPU)
# - Port 8000 already in use
```

### Out of memory
```bash
# Check Docker resources
docker stats

# Increase Docker Desktop memory limit:
# Settings > Resources > Memory > Increase to 16GB+
```

### GPU not detected
```bash
# Check NVIDIA Docker runtime
docker run --rm --gpus all nvidia/cuda:11.8.0-runtime-ubuntu22.04 nvidia-smi

# If fails, ensure nvidia-docker2 is installed
```

## Local-Specific Issues

### Qdrant connection failed
```bash
# Restart Qdrant
docker-compose restart qdrant

# Check if Qdrant is accessible
curl http://localhost:6333
```

## Cloud-Specific Issues

### DNS resolution failed

Error: `Name or service not known`

**Solution:** The `docker-compose.cloud.yml` includes DNS configuration:
```yaml
dns:
  - 8.8.8.8
  - 8.8.4.4
```

If still failing, try restarting Docker Desktop.

### Qdrant connection failed
```bash
# Verify credentials from host machine
curl "https://your-cluster.cloud.qdrant.io:6333" \
  -H "api-key: YOUR_API_KEY"

# Check environment variables in container
docker exec colpali-api python3 -c "
import os
print('QDRANT_URL:', os.getenv('QDRANT_URL'))
print('QDRANT_API_KEY:', os.getenv('QDRANT_API_KEY')[:10] + '...' if os.getenv('QDRANT_API_KEY') else None)
print('COLLECTION_NAME:', os.getenv('COLLECTION_NAME'))
"
```

### Vector dimension error

Error: `Wrong input: Vector dimension error: expected dim: 1536, got 128`

**Cause:** The collection was created with a different embedding model (expecting 1536 dimensions), but ColPali generates 128-dimensional embeddings.

**Solutions:**

1. **Use a different collection name** in `.env`:
   ```env
   COLLECTION_NAME=colpali-embeddings-128
   ```

2. **Or delete the existing collection** and let the API recreate it:
   ```bash
   curl -X DELETE "https://your-cluster.cloud.qdrant.io:6333/collections/colpali-test" \
     -H "api-key: YOUR_API_KEY"
   ```

---

# Cleanup

## Local Setup

```bash
# Stop services
docker-compose down

# Stop and remove volumes (deletes all local Qdrant data)
docker-compose down -v

# Remove Docker images
docker-compose down --rmi all
```

## Cloud Setup

```bash
# Stop services
docker-compose -f docker-compose.cloud.yml down

# Remove Docker images
docker-compose -f docker-compose.cloud.yml down --rmi all
```

**Note:** Stopping the cloud setup does NOT delete data from Qdrant Cloud. Your embeddings remain stored in the cloud.

---

# Quick Reference

| Task | Local Command | Cloud Command |
|------|---------------|---------------|
| Start | `docker-compose up` | `docker-compose -f docker-compose.cloud.yml --env-file .env up` |
| Start (background) | `docker-compose up -d` | `docker-compose -f docker-compose.cloud.yml --env-file .env up -d` |
| Stop | `docker-compose down` | `docker-compose -f docker-compose.cloud.yml down` |
| Logs | `docker-compose logs -f` | `docker-compose -f docker-compose.cloud.yml logs -f` |
| Rebuild | `docker-compose up --build` | `docker-compose -f docker-compose.cloud.yml --env-file .env up --build` |
| Health Check | `curl http://localhost:8000/health` | `curl http://localhost:8000/health` |

---

# Expected Processing Times

| File Type | Pages/Size | GPU (V100) | CPU |
|-----------|------------|------------|-----|
| PDF (1 page) | ~500KB | ~2-3 sec | ~10-15 sec |
| PDF (10 pages) | ~5MB | ~15-20 sec | ~2-3 min |
| Image (PNG) | ~1MB | ~2-3 sec | ~10-15 sec |

*First request after startup will be slower due to model warm-up*

---

# File Structure

```
colpali-docker/
├── api.py                              # FastAPI application
├── Dockerfile                          # Container build
├── docker-compose.yml                  # Local Qdrant setup
├── docker-compose.cloud.yml            # Qdrant Cloud setup
├── .env                                # Your cloud credentials (gitignored)
├── .env.example                        # Template for .env
├── requirements.txt                    # Python dependencies
├── ColPali-API.postman_collection.json # Postman collection
├── TESTING.md                          # This file
├── README.md                           # Project documentation
└── k8s/                                # Kubernetes manifests for AKS
```

---

# Next Steps After Testing

1. **Version control**: Commit any changes (exclude `.env`!)
   ```bash
   git add .
   git commit -m "Test successful"
   ```

2. **Deploy to Azure AKS**: Run the deployment script
   ```bash
   ./deploy-to-azure.sh
   ```

3. **Set up monitoring**: Configure Application Insights

4. **Add authentication**: Implement API keys or OAuth2

5. **Configure ingress**: Set up domain and SSL/TLS
