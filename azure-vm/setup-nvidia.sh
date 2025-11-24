#!/bin/bash
# =============================================================================
# NVIDIA GPU Setup Script for Azure VM
# =============================================================================
# Run this script only if your Azure VM has NVIDIA GPU (NC, ND, NV series)
# Run as root or with sudo
# =============================================================================

set -e

echo "=============================================="
echo "NVIDIA GPU Setup for Azure VM"
echo "=============================================="

# Check if NVIDIA GPU is present
if ! lspci | grep -i nvidia > /dev/null; then
    echo "ERROR: No NVIDIA GPU detected on this VM."
    echo "This script is only for GPU-enabled VMs (NC, ND, NV series)"
    exit 1
fi

echo "NVIDIA GPU detected. Proceeding with driver installation..."

# Install NVIDIA drivers
echo "[1/4] Installing NVIDIA drivers..."
apt-get update
apt-get install -y linux-headers-$(uname -r)

# Add NVIDIA package repository
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

apt-get update

# Install NVIDIA driver (use ubuntu-drivers for automatic detection)
apt-get install -y ubuntu-drivers-common
ubuntu-drivers autoinstall

# Install NVIDIA Container Toolkit for Docker GPU support
echo "[2/4] Installing NVIDIA Container Toolkit..."
apt-get install -y nvidia-container-toolkit

# Configure Docker to use NVIDIA runtime
echo "[3/4] Configuring Docker for NVIDIA..."
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

# Verify installation
echo "[4/4] Verifying NVIDIA installation..."
echo ""
echo "NVIDIA Driver Info:"
nvidia-smi

echo ""
echo "=============================================="
echo "NVIDIA GPU Setup Complete!"
echo "=============================================="
echo ""
echo "GPU support is now enabled for Docker containers."
echo ""
echo "To use GPU in docker-compose, uncomment the deploy section:"
echo "  deploy:"
echo "    resources:"
echo "      reservations:"
echo "        devices:"
echo "          - driver: nvidia"
echo "            count: all"
echo "            capabilities: [gpu]"
echo ""
echo "You may need to reboot the VM for all changes to take effect:"
echo "  sudo reboot"
echo ""