# ColPali Document Embedding API with Qdrant

This project provides a production-ready deployment of the ColPali document embedding model on Azure Kubernetes Service (AKS) with Qdrant vector database integration.

## Overview

**ColPali** is a vision-language model optimized for document understanding and retrieval. This deployment includes:

- FastAPI REST API for document ingestion
- Automatic PDF to image conversion
- Multi-page document processing
- Vector embeddings storage in Qdrant
- GPU-accelerated inference on AKS
- Horizontal pod autoscaling
- Production-ready Kubernetes manifests

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Azure Load Balancer                   │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                  AKS Cluster (GPU)                       │
│  ┌──────────────────────┐    ┌────────────────────────┐ │
│  │  ColPali API Pod     │    │   Qdrant Pod           │ │
│  │  - FastAPI Server    │◄──►│   - Vector Database    │ │
│  │  - ColPali Model     │    │   - Persistent Storage │ │
│  │  - GPU: V100         │    │                        │ │
│  └──────────────────────┘    └────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                     │
                     ▼
         ┌──────────────────────┐
         │ Azure Container      │
         │ Registry (ACR)       │
         └──────────────────────┘
```

## API Endpoints

### Health Check
```bash
GET /health
```

Response:
```json
{
  "status": "healthy",
  "model_loaded": true,
  "qdrant_connected": true,
  "device": "cuda"
}
```

### Ingest PDF Document
```bash
POST /ingest/pdf
Content-Type: multipart/form-data

Parameters:
- file: PDF file (required)
- document_id: Unique identifier (optional, auto-generated if not provided)
```

Response:
```json
{
  "document_id": "uuid-string",
  "filename": "document.pdf",
  "total_pages": 10,
  "embedding_dimension": 128,
  "tokens_per_page": 1024,
  "message": "Successfully ingested PDF with 10 pages"
}
```

### Ingest Image
```bash
POST /ingest/image
Content-Type: multipart/form-data

Parameters:
- file: Image file (PNG, JPG, JPEG, BMP, TIFF, WEBP)
- document_id: Unique identifier (optional)
```

Response:
```json
{
  "document_id": "uuid-string",
  "filename": "image.png",
  "total_pages": 1,
  "embedding_dimension": 128,
  "tokens_per_page": 1024,
  "message": "Successfully ingested image"
}
```

### List Documents
```bash
GET /documents
```

Response:
```json
[
  {
    "document_id": "uuid-1",
    "filename": "document1.pdf",
    "total_pages": 10,
    "embedding_dimension": 128
  },
  {
    "document_id": "uuid-2",
    "filename": "image1.png",
    "total_pages": 1,
    "embedding_dimension": 128
  }
]
```

### Delete Document
```bash
DELETE /document/{document_id}
```

Response:
```json
{
  "message": "Document uuid-string deleted successfully"
}
```

### Get Statistics
```bash
GET /stats
```

Response:
```json
{
  "collection_name": "colpali_embeddings",
  "total_vectors": 150,
  "vector_dimension": 128,
  "distance_metric": "COSINE"
}
```

## Local Development with Docker Compose

### Prerequisites
- Docker and Docker Compose
- NVIDIA Docker runtime (for GPU support)
- At least 16GB RAM
- 20GB disk space

### Quick Start

1. Build and run the services:
```bash
docker-compose up --build
```

2. Test the API:
```bash
# Health check
curl http://localhost:8000/health

# Upload a PDF
curl -X POST -F "file=@your-document.pdf" http://localhost:8000/ingest/pdf

# Upload an image
curl -X POST -F "file=@your-image.png" http://localhost:8000/ingest/image

# List all documents
curl http://localhost:8000/documents

# Get statistics
curl http://localhost:8000/stats
```

3. Access Qdrant Dashboard:
```
http://localhost:6333/dashboard
```

4. View API Documentation:
```
http://localhost:8000/docs
```

## Azure Deployment

### Prerequisites

1. Azure CLI installed and configured
2. kubectl installed
3. Helm installed
4. Azure subscription with quota for GPU VMs
5. Docker installed

### Automated Deployment

Run the deployment script:

```bash
chmod +x deploy-to-azure.sh
./deploy-to-azure.sh
```

This script will:
1. Create an Azure Resource Group
2. Create an Azure Container Registry (ACR)
3. Build and push the Docker image to ACR
4. Create an AKS cluster with a system node pool
5. Add a GPU node pool with NVIDIA V100 GPUs
6. Install NVIDIA GPU Operator
7. Deploy Qdrant and ColPali API to AKS

### Manual Deployment Steps

#### 1. Create Azure Resources

```bash
# Variables
RESOURCE_GROUP="colpali-rg"
LOCATION="eastus"
AKS_CLUSTER_NAME="colpali-aks"
ACR_NAME="colpaliacr$(date +%s)"

# Create resource group
az group create --name $RESOURCE_GROUP --location $LOCATION

# Create ACR
az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Premium

# Build and push image
az acr build --registry $ACR_NAME --image colpali-api:latest --file Dockerfile .
```

#### 2. Create AKS Cluster

```bash
# Create AKS cluster
az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $AKS_CLUSTER_NAME \
  --node-count 1 \
  --node-vm-size Standard_D4s_v3 \
  --nodepool-name system \
  --enable-managed-identity \
  --attach-acr $ACR_NAME \
  --generate-ssh-keys

# Add GPU node pool
az aks nodepool add \
  --resource-group $RESOURCE_GROUP \
  --cluster-name $AKS_CLUSTER_NAME \
  --name gpu \
  --node-count 1 \
  --node-vm-size Standard_NC6s_v3 \
  --node-taints sku=gpu:NoSchedule \
  --labels agentpool=gpu

# Get credentials
az aks get-credentials --resource-group $RESOURCE_GROUP --name $AKS_CLUSTER_NAME
```

#### 3. Install NVIDIA GPU Operator

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update
helm install gpu-operator nvidia/gpu-operator --namespace gpu-operator --create-namespace
```

#### 4. Deploy Application

```bash
# Update image name in manifests
sed -i "s/<YOUR_ACR_NAME>/$ACR_NAME/g" k8s/colpali-deployment.yaml

# Deploy
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/qdrant-deployment.yaml
kubectl apply -f k8s/colpali-deployment.yaml

# Wait for deployments
kubectl wait --for=condition=available --timeout=600s deployment/qdrant -n colpali
kubectl wait --for=condition=available --timeout=600s deployment/colpali-api -n colpali
```

#### 5. Get External IP

```bash
kubectl get svc colpali-api -n colpali --watch
```

Wait for the `EXTERNAL-IP` to be assigned.

### Testing the Deployment

```bash
# Set the external IP
export EXTERNAL_IP=$(kubectl get svc colpali-api -n colpali -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Health check
curl http://$EXTERNAL_IP/health

# Upload a document
curl -X POST -F "file=@document.pdf" http://$EXTERNAL_IP/ingest/pdf

# List documents
curl http://$EXTERNAL_IP/documents
```

### Accessing Qdrant Dashboard

```bash
kubectl port-forward -n colpali svc/qdrant 6333:6333
```

Then visit: http://localhost:6333/dashboard

## Monitoring and Debugging

### View Logs

```bash
# ColPali API logs
kubectl logs -f -n colpali -l app=colpali-api

# Qdrant logs
kubectl logs -f -n colpali -l app=qdrant

# All pods in namespace
kubectl logs -f -n colpali --all-containers=true
```

### Check Pod Status

```bash
kubectl get pods -n colpali
kubectl describe pod <pod-name> -n colpali
```

### Check GPU Availability

```bash
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpu: .status.allocatable."nvidia.com/gpu"}'
```

### Scale the API

```bash
# Manual scaling
kubectl scale deployment colpali-api -n colpali --replicas=3

# Check HPA status
kubectl get hpa -n colpali
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| QDRANT_HOST | qdrant | Qdrant service hostname |
| QDRANT_PORT | 6333 | Qdrant HTTP port |
| COLLECTION_NAME | colpali_embeddings | Qdrant collection name |
| TRANSFORMERS_CACHE | /cache/huggingface | HuggingFace model cache |

### Resource Limits

Default resource allocations in Kubernetes:

**ColPali API Pod:**
- Requests: 8Gi RAM, 2 CPU cores, 1 GPU
- Limits: 16Gi RAM, 4 CPU cores, 1 GPU

**Qdrant Pod:**
- Requests: 2Gi RAM, 1 CPU core
- Limits: 4Gi RAM, 2 CPU cores
- Storage: 20Gi

### GPU VM Sizes

Available GPU VM sizes in Azure:

| VM Size | GPU | vCPUs | RAM | Cost/Month (approx) |
|---------|-----|-------|-----|---------------------|
| Standard_NC6s_v3 | 1x V100 | 6 | 112 GB | $1,500 |
| Standard_NC12s_v3 | 2x V100 | 12 | 224 GB | $3,000 |
| Standard_NC24s_v3 | 4x V100 | 24 | 448 GB | $6,000 |

## Cost Optimization

1. **Use spot instances** for non-production workloads:
```bash
az aks nodepool add --priority Spot --eviction-policy Delete --spot-max-price -1
```

2. **Auto-scaling**: HPA is configured to scale based on CPU/memory usage

3. **Stop cluster** when not in use:
```bash
az aks stop --name $AKS_CLUSTER_NAME --resource-group $RESOURCE_GROUP
az aks start --name $AKS_CLUSTER_NAME --resource-group $RESOURCE_GROUP
```

4. **Use Azure Reserved Instances** for production workloads

## Cleanup

### Delete Kubernetes Resources

```bash
kubectl delete namespace colpali
```

### Delete Azure Resources

```bash
az group delete --name $RESOURCE_GROUP --yes --no-wait
```

## Troubleshooting

### Pod Not Starting

```bash
kubectl describe pod <pod-name> -n colpali
kubectl logs <pod-name> -n colpali
```

### GPU Not Available

```bash
# Check GPU operator
kubectl get pods -n gpu-operator

# Check node labels
kubectl get nodes --show-labels
```

### Out of Memory

Increase resource limits in `k8s/colpali-deployment.yaml`:
```yaml
resources:
  limits:
    memory: "32Gi"
```

### Qdrant Connection Failed

```bash
# Check Qdrant service
kubectl get svc qdrant -n colpali

# Test connectivity
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- curl http://qdrant:6333
```

## Security Considerations

1. **Enable RBAC** on AKS cluster
2. **Use Azure Key Vault** for secrets
3. **Enable network policies**
4. **Use private ACR** with authentication
5. **Implement API authentication** (JWT, OAuth2)
6. **Enable TLS/HTTPS** with cert-manager
7. **Regular security updates** of base images

## Performance Tuning

1. **Batch Processing**: Process multiple pages in parallel
2. **Model Quantization**: Use INT8 quantization for faster inference
3. **Caching**: Enable model caching in persistent volumes
4. **Connection Pooling**: Configure Qdrant connection pooling
5. **GPU Memory**: Adjust batch size based on GPU memory

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test locally with Docker Compose
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For issues and questions:
- GitHub Issues: [Create an issue]
- Documentation: [Azure AKS Docs](https://docs.microsoft.com/azure/aks/)
- ColPali Model: [HuggingFace](https://huggingface.co/vidore/colpali-v1.2)

## Acknowledgments

- ColPali model by Vidore
- Qdrant vector database
- FastAPI framework
- Azure Kubernetes Service
