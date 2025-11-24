#!/bin/bash
# =============================================================================
# ColPali Deployment Script for Azure VM
# =============================================================================
# This script deploys the ColPali application on the Azure VM
# Run this after setup-vm.sh has completed
# =============================================================================

set -e

APP_DIR="/opt/colpali"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo "ColPali Deployment Script"
echo "=============================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./deploy.sh)"
    exit 1
fi

# Create application directory if not exists
echo "[1/7] Setting up application directory..."
mkdir -p $APP_DIR
mkdir -p $APP_DIR/uploads
mkdir -p $APP_DIR/qdrant_storage
mkdir -p $APP_DIR/huggingface_cache
mkdir -p $APP_DIR/logs

# Copy application files
echo "[2/7] Copying application files..."
cp -r "$SCRIPT_DIR/../api.py" $APP_DIR/
cp -r "$SCRIPT_DIR/../requirements.txt" $APP_DIR/
cp -r "$SCRIPT_DIR/../Dockerfile" $APP_DIR/

# Determine which docker-compose to use
echo ""
echo "Select deployment mode:"
echo "1) Local Qdrant (runs Qdrant container alongside API)"
echo "2) Qdrant Cloud (connects to external Qdrant Cloud)"
read -p "Enter choice [1/2]: " DEPLOY_MODE

if [ "$DEPLOY_MODE" == "2" ]; then
    echo "[3/7] Using Qdrant Cloud configuration..."
    cp "$SCRIPT_DIR/docker-compose.cloud.yml" $APP_DIR/docker-compose.yml

    # Check if .env exists
    if [ ! -f "$APP_DIR/.env" ]; then
        echo ""
        echo "Qdrant Cloud requires configuration."
        read -p "Enter Qdrant Cloud URL: " QDRANT_URL
        read -p "Enter Qdrant API Key: " QDRANT_API_KEY
        read -p "Enter Collection Name [colpali-embeddings-128]: " COLLECTION_NAME
        COLLECTION_NAME=${COLLECTION_NAME:-colpali-embeddings-128}

        cat > $APP_DIR/.env << EOF
QDRANT_URL=$QDRANT_URL
QDRANT_API_KEY=$QDRANT_API_KEY
COLLECTION_NAME=$COLLECTION_NAME
EOF
        echo "Created .env file"
    fi
else
    echo "[3/7] Using local Qdrant configuration..."
    cp "$SCRIPT_DIR/docker-compose.prod.yml" $APP_DIR/docker-compose.yml
fi

# Set permissions
echo "[4/7] Setting permissions..."
chmod -R 755 $APP_DIR
chmod 600 $APP_DIR/.env 2>/dev/null || true

# Build Docker image
echo "[5/7] Building Docker image (this may take a while)..."
cd $APP_DIR
docker-compose build

# Install systemd service
echo "[6/7] Installing systemd service..."
cp "$SCRIPT_DIR/colpali.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable colpali.service

# Start the service
echo "[7/7] Starting ColPali service..."
systemctl start colpali.service

# Wait for services to start
echo ""
echo "Waiting for services to start..."
sleep 10

# Check status
echo ""
echo "=============================================="
echo "Deployment Complete!"
echo "=============================================="
echo ""
echo "Service Status:"
systemctl status colpali.service --no-pager || true
echo ""
echo "Docker Containers:"
docker ps
echo ""
echo "Useful Commands:"
echo "  - View logs: journalctl -u colpali -f"
echo "  - Docker logs: docker-compose -f $APP_DIR/docker-compose.yml logs -f"
echo "  - Restart: sudo systemctl restart colpali"
echo "  - Stop: sudo systemctl stop colpali"
echo ""
echo "API Endpoints:"
echo "  - Health: http://<VM-IP>:8000/health"
echo "  - Docs: http://<VM-IP>:8000/docs"
echo "  - Ingest PDF: POST http://<VM-IP>:8000/ingest/pdf"
echo ""
echo "NOTE: The first request may take 10-15 minutes as the model downloads."
echo ""