# Testing Guide - ColPali API

## Local Testing with Docker Compose

### Step 1: Start the Services

Navigate to the project directory and start Docker Compose:

```bash
cd "c:\Users\MinuraSamaranayake\OneDrive - Codice\Documents\Github\FortiMind Test Workspace\ColPali\colpali-docker"
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

### Step 2: Verify Services

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
  "device": "cuda"  // or "cpu" if no GPU
}
```

### Step 3: Access Web Interfaces

- **FastAPI Swagger UI**: http://localhost:8000/docs
- **FastAPI ReDoc**: http://localhost:8000/redoc
- **Qdrant Dashboard**: http://localhost:6333/dashboard

---

## Testing with Postman

### Import the Collection

1. Open Postman
2. Click **Import** (top left)
3. Select **File** > Choose `ColPali-API.postman_collection.json`
4. The collection will appear in your Collections tab

### Collection Structure

The collection includes these requests:

1. **Health Check** - Verify API is running
2. **Get Statistics** - View collection stats
3. **List Documents** - See all ingested documents
4. **Ingest PDF** - Upload PDF file
5. **Ingest Image** - Upload image file
6. **Delete Document** - Remove document by ID

### Variables

The collection uses these variables:
- `base_url`: `http://localhost:8000` (default)
- `document_id`: Auto-populated after ingestion

### Testing Workflow

#### 1. Health Check
- Select "Health Check" request
- Click **Send**
- Verify response shows `"status": "healthy"`

#### 2. Upload a PDF
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

#### 3. Upload an Image
- Select "Ingest Image" request
- Go to **Body** tab
- Click on the `file` field and select an image (PNG, JPG, etc.)
- Click **Send**

#### 4. List Documents
- Select "List Documents" request
- Click **Send**
- See all ingested documents

#### 5. View Statistics
- Select "Get Statistics" request
- Click **Send**
- See collection info and vector count

#### 6. Delete Document
- Select "Delete Document" request
- In **Variables** tab (bottom), set `document_id` to the ID you want to delete
- OR manually edit URL: `http://localhost:8000/document/YOUR_DOCUMENT_ID`
- Click **Send**

---

## Testing with cURL

### Health Check
```bash
curl http://localhost:8000/health
```

### Upload PDF
```bash
curl -X POST \
  http://localhost:8000/ingest/pdf \
  -F "file=@path/to/your/document.pdf"
```

### Upload Image
```bash
curl -X POST \
  http://localhost:8000/ingest/image \
  -F "file=@path/to/your/image.png"
```

### List Documents
```bash
curl http://localhost:8000/documents
```

### Get Statistics
```bash
curl http://localhost:8000/stats
```

### Delete Document
```bash
curl -X DELETE http://localhost:8000/document/YOUR_DOCUMENT_ID
```

---

## Testing with Python Script

Use the provided test script:

```bash
# Install requests if needed
pip install requests

# Test with a PDF
python test_api.py http://localhost:8000 path/to/your/document.pdf

# Test with an image
python test_api.py http://localhost:8000 path/to/your/image.png

# Just health check (no file)
python test_api.py http://localhost:8000
```

---

## Testing with FastAPI Swagger UI

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

## Verifying Qdrant Storage

### Via Qdrant Dashboard
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

---

## Monitoring Logs

### View all logs
```bash
docker-compose logs -f
```

### View only API logs
```bash
docker-compose logs -f colpali-api
```

### View only Qdrant logs
```bash
docker-compose logs -f qdrant
```

---

## Troubleshooting

### API not starting
```bash
# Check logs
docker-compose logs colpali-api

# Common issues:
# - Model download in progress (wait 10-15 min first time)
# - GPU not available (will fall back to CPU)
# - Port 8000 already in use
```

### Qdrant connection failed
```bash
# Restart Qdrant
docker-compose restart qdrant

# Check if Qdrant is accessible
curl http://localhost:6333
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

---

## Performance Testing

### Upload Multiple Files
```bash
for file in *.pdf; do
  echo "Uploading $file..."
  curl -X POST -F "file=@$file" http://localhost:8000/ingest/pdf
  echo ""
done
```

### Measure Processing Time
```bash
time curl -X POST -F "file=@large-document.pdf" http://localhost:8000/ingest/pdf
```

### Check Resource Usage
```bash
docker stats colpali-api
```

---

## Cleanup

### Stop services
```bash
docker-compose down
```

### Stop and remove volumes (deletes all data)
```bash
docker-compose down -v
```

### Remove Docker images
```bash
docker-compose down --rmi all
```

---

## Sample Test Files

You can test with:
- Your existing PDF: `ACPM-Rev-6-12122023 2.pdf` (in the pdfs folder)
- Any image file: `imhh.png` (in parent directory)
- Any other PDF or image files you have

---

## Expected Processing Times

| File Type | Pages/Size | GPU (V100) | CPU |
|-----------|------------|------------|-----|
| PDF (1 page) | ~500KB | ~2-3 sec | ~10-15 sec |
| PDF (10 pages) | ~5MB | ~15-20 sec | ~2-3 min |
| Image (PNG) | ~1MB | ~2-3 sec | ~10-15 sec |

*First request after startup will be slower due to model warm-up*

---

## Next Steps After Testing

Once local testing is successful:

1. **Version control**: Commit any changes
   ```bash
   git add .
   git commit -m "Test successful"
   ```

2. **Deploy to Azure**: Run the deployment script
   ```bash
   ./deploy-to-azure.sh
   ```

3. **Set up monitoring**: Configure Application Insights

4. **Add authentication**: Implement API keys or OAuth2

5. **Configure ingress**: Set up domain and SSL/TLS
