#!/bin/bash

# ColPali AKS Deployment Script
# This script automates the deployment of ColPali to Azure Kubernetes Service

set -e

# Configuration
RESOURCE_GROUP="colpali-rg"
LOCATION="eastus"
AKS_CLUSTER_NAME="colpali-aks"
ACR_NAME="colpaliacr$(date +%s)"  # Must be globally unique
GPU_NODE_POOL="gpu"
GPU_VM_SIZE="Standard_NC6s_v3"  # NVIDIA Tesla V100
CPU_NODE_POOL="system"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}ColPali Azure Kubernetes Service Deployment${NC}"
echo -e "${BLUE}================================================${NC}"

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo -e "${RED}Azure CLI is not installed. Please install it first.${NC}"
    exit 1
fi

# Check if logged in
echo -e "\n${GREEN}[1/10] Checking Azure login...${NC}"
az account show &> /dev/null || az login

# Create Resource Group
echo -e "\n${GREEN}[2/10] Creating resource group: ${RESOURCE_GROUP}${NC}"
az group create \
    --name ${RESOURCE_GROUP} \
    --location ${LOCATION}

# Create Azure Container Registry
echo -e "\n${GREEN}[3/10] Creating Azure Container Registry: ${ACR_NAME}${NC}"
az acr create \
    --resource-group ${RESOURCE_GROUP} \
    --name ${ACR_NAME} \
    --sku Premium \
    --location ${LOCATION}

# Build and push Docker image to ACR
echo -e "\n${GREEN}[4/10] Building and pushing Docker image to ACR...${NC}"
az acr build \
    --registry ${ACR_NAME} \
    --image colpali-api:latest \
    --file Dockerfile \
    .

# Create AKS cluster with GPU support
echo -e "\n${GREEN}[5/10] Creating AKS cluster: ${AKS_CLUSTER_NAME}${NC}"
echo -e "${BLUE}This may take 10-15 minutes...${NC}"
az aks create \
    --resource-group ${RESOURCE_GROUP} \
    --name ${AKS_CLUSTER_NAME} \
    --node-count 1 \
    --node-vm-size Standard_D4s_v3 \
    --nodepool-name ${CPU_NODE_POOL} \
    --enable-managed-identity \
    --attach-acr ${ACR_NAME} \
    --generate-ssh-keys \
    --network-plugin azure \
    --enable-addons monitoring

# Add GPU node pool
echo -e "\n${GREEN}[6/10] Adding GPU node pool...${NC}"
az aks nodepool add \
    --resource-group ${RESOURCE_GROUP} \
    --cluster-name ${AKS_CLUSTER_NAME} \
    --name ${GPU_NODE_POOL} \
    --node-count 1 \
    --node-vm-size ${GPU_VM_SIZE} \
    --node-taints sku=gpu:NoSchedule \
    --labels agentpool=gpu

# Get AKS credentials
echo -e "\n${GREEN}[7/10] Getting AKS credentials...${NC}"
az aks get-credentials \
    --resource-group ${RESOURCE_GROUP} \
    --name ${AKS_CLUSTER_NAME} \
    --overwrite-existing

# Install NVIDIA GPU Operator
echo -e "\n${GREEN}[8/10] Installing NVIDIA GPU Operator...${NC}"
kubectl create namespace gpu-operator || true
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia || true
helm repo update
helm install --wait \
    gpu-operator nvidia/gpu-operator \
    --namespace gpu-operator \
    --create-namespace

# Update Kubernetes manifests with ACR name
echo -e "\n${GREEN}[9/10] Updating Kubernetes manifests...${NC}"
sed -i "s/<YOUR_ACR_NAME>/${ACR_NAME}/g" k8s/colpali-deployment.yaml

# Deploy application to AKS
echo -e "\n${GREEN}[10/10] Deploying ColPali to AKS...${NC}"
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/qdrant-deployment.yaml
kubectl apply -f k8s/colpali-deployment.yaml

# Wait for deployments
echo -e "\n${BLUE}Waiting for deployments to be ready...${NC}"
kubectl wait --for=condition=available --timeout=600s deployment/qdrant -n colpali
kubectl wait --for=condition=available --timeout=600s deployment/colpali-api -n colpali

# Get service external IP
echo -e "\n${BLUE}Getting service information...${NC}"
kubectl get services -n colpali

echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}Deployment completed successfully!${NC}"
echo -e "${GREEN}================================================${NC}"

echo -e "\n${BLUE}Next steps:${NC}"
echo -e "1. Wait for the LoadBalancer to get an external IP:"
echo -e "   ${BLUE}kubectl get svc colpali-api -n colpali --watch${NC}"
echo -e "\n2. Test the API:"
echo -e "   ${BLUE}export EXTERNAL_IP=\$(kubectl get svc colpali-api -n colpali -o jsonpath='{.status.loadBalancer.ingress[0].ip}')${NC}"
echo -e "   ${BLUE}curl http://\$EXTERNAL_IP/health${NC}"
echo -e "\n3. Upload a PDF:"
echo -e "   ${BLUE}curl -X POST -F \"file=@your-document.pdf\" http://\$EXTERNAL_IP/ingest/pdf${NC}"
echo -e "\n4. View logs:"
echo -e "   ${BLUE}kubectl logs -f -n colpali -l app=colpali-api${NC}"
echo -e "\n5. Access Qdrant UI (port-forward):"
echo -e "   ${BLUE}kubectl port-forward -n colpali svc/qdrant 6333:6333${NC}"
echo -e "   Then visit: http://localhost:6333/dashboard"

echo -e "\n${BLUE}Resource Information:${NC}"
echo -e "Resource Group: ${RESOURCE_GROUP}"
echo -e "AKS Cluster: ${AKS_CLUSTER_NAME}"
echo -e "ACR Name: ${ACR_NAME}"
echo -e "Location: ${LOCATION}"

echo -e "\n${RED}To delete all resources:${NC}"
echo -e "${RED}az group delete --name ${RESOURCE_GROUP} --yes --no-wait${NC}"
