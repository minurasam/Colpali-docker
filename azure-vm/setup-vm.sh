#!/bin/bash
# =============================================================================
# ColPali Azure VM Setup Script
# =============================================================================
# This script sets up an Azure Ubuntu VM with all dependencies for ColPali
# Run this script as root or with sudo
# =============================================================================

set -e  # Exit on any error

echo "=============================================="
echo "ColPali Azure VM Setup Script"
echo "=============================================="

# Update system packages
echo "[1/8] Updating system packages..."
apt-get update && apt-get upgrade -y

# Install essential packages
echo "[2/8] Installing essential packages..."
apt-get install -y \
    curl \
    wget \
    git \
    build-essential \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    poppler-utils \
    unzip

# Install Python 3.10+
echo "[3/8] Installing Python 3.10..."
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update
apt-get install -y python3.10 python3.10-venv python3.10-dev python3-pip

# Set Python 3.10 as default
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1
update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

# Upgrade pip
echo "[4/8] Upgrading pip..."
python3 -m pip install --upgrade pip

# Install Docker
echo "[5/8] Installing Docker..."
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Start and enable Docker
systemctl start docker
systemctl enable docker

# Add current user to docker group (if not root)
if [ "$SUDO_USER" ]; then
    usermod -aG docker $SUDO_USER
    echo "Added $SUDO_USER to docker group"
fi

# Install Docker Compose standalone (for compatibility)
echo "[6/8] Installing Docker Compose..."
DOCKER_COMPOSE_VERSION="v2.24.0"
curl -L "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Verify installations
echo "[7/8] Verifying installations..."
echo "Python version: $(python3 --version)"
echo "Pip version: $(pip3 --version)"
echo "Docker version: $(docker --version)"
echo "Docker Compose version: $(docker-compose --version)"

# Create application directory
echo "[8/8] Creating application directory..."
mkdir -p /opt/colpali
mkdir -p /opt/colpali/uploads
mkdir -p /opt/colpali/qdrant_storage
mkdir -p /opt/colpali/logs

# Set permissions
chmod -R 755 /opt/colpali

echo ""
echo "=============================================="
echo "VM Setup Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "1. Copy your application files to /opt/colpali/"
echo "2. Configure your .env file"
echo "3. Run: cd /opt/colpali && docker-compose up -d"
echo ""
echo "For GPU support (if applicable):"
echo "Run: sudo ./setup-nvidia.sh"
echo ""