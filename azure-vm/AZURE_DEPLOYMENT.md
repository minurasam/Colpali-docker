# ColPali Azure VM Deployment Guide

This guide walks you through deploying the ColPali Document Embedding API on an Azure Virtual Machine.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Azure VM Recommendations](#azure-vm-recommendations)
3. [Step-by-Step Deployment](#step-by-step-deployment)
4. [Configuration Options](#configuration-options)
5. [Monitoring and Maintenance](#monitoring-and-maintenance)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Azure subscription with permissions to create VMs
- SSH client (Terminal on Mac/Linux, PuTTY or Windows Terminal on Windows)
- Basic familiarity with Linux command line

---

## Azure VM Recommendations

### CPU-Only Deployment (Slower, Lower Cost)

| Setting | Recommended Value |
|---------|-------------------|
| **Size** | Standard_D4s_v3 (4 vCPU, 16 GB RAM) or higher |
| **OS** | Ubuntu Server 22.04 LTS |
| **Disk** | 128 GB Premium SSD |
| **Region** | Choose closest to users |

**Estimated Cost:** ~$140-200/month

### GPU Deployment (Faster, Higher Cost)

| Setting | Recommended Value |
|---------|-------------------|
| **Size** | Standard_NC6s_v3 (6 vCPU, 112 GB RAM, 1x V100 GPU) |
| **OS** | Ubuntu Server 22.04 LTS |
| **Disk** | 256 GB Premium SSD |
| **Region** | Check GPU availability |

**Estimated Cost:** ~$900-1200/month

### Minimum Requirements

- **RAM:** 16 GB minimum (32 GB recommended for production)
- **Storage:** 100 GB (model cache ~5GB + application)
- **CPU:** 4 cores minimum

---

## Step-by-Step Deployment

### Step 1: Create Azure VM

1. Go to [Azure Portal](https://portal.azure.com)
2. Click **Create a resource** > **Virtual Machine**
3. Configure:
   - **Subscription:** Select your subscription
   - **Resource group:** Create new or use existing
   - **VM name:** `colpali-vm`
   - **Region:** Select your preferred region
   - **Image:** Ubuntu Server 22.04 LTS - x64 Gen2
   - **Size:** Standard_D4s_v3 (or NC6s_v3 for GPU)
   - **Authentication:** SSH public key (recommended)
   - **Username:** `azureuser`
4. **Networking:**
   - Create new virtual network or use existing
   - **Public IP:** Create new
   - **NIC network security group:** Basic
   - **Public inbound ports:** Allow SSH (22)
5. Click **Review + Create** > **Create**

### Step 2: Configure Network Security Group

Add inbound rules for the API:

| Priority | Name | Port | Protocol | Source | Action |
|----------|------|------|----------|--------|--------|
| 100 | SSH | 22 | TCP | Your IP | Allow |
| 110 | ColPali-API | 8000 | TCP | Any | Allow |
| 120 | Qdrant | 6333 | TCP | Any* | Allow |

*Note: Restrict Qdrant port to specific IPs in production

### Step 3: Connect to VM

```bash
ssh azureuser@<YOUR-VM-PUBLIC-IP>
```

### Step 4: Upload Deployment Files

From your local machine, upload the deployment files:

```bash
# Create a zip of the colpali-docker folder
cd /path/to/ColPali
zip -r colpali-docker.zip colpali-docker/

# Upload to VM
scp colpali-docker.zip azureuser@<YOUR-VM-PUBLIC-IP>:~/
```

Or use Git (if repo is accessible):

```bash
# On the VM
git clone <your-repo-url>
```

### Step 5: Run Setup Script

```bash
# Connect to VM
ssh azureuser@<YOUR-VM-PUBLIC-IP>

# Unzip files
unzip colpali-docker.zip
cd colpali-docker/azure-vm

# Make scripts executable
chmod +x *.sh

# Run VM setup (installs Docker, Python, etc.)
sudo ./setup-vm.sh
```

### Step 6: (Optional) Setup GPU Support

For GPU-enabled VMs only:

```bash
sudo ./setup-nvidia.sh

# Reboot after GPU driver installation
sudo reboot
```

After reboot, verify GPU:

```bash
nvidia-smi
```

### Step 7: Deploy Application

```bash
cd ~/colpali-docker/azure-vm

# Run deployment script
sudo ./deploy.sh
```

The script will prompt you to choose:
1. **Local Qdrant** - Runs Qdrant container on the VM
2. **Qdrant Cloud** - Connects to external Qdrant Cloud

### Step 8: Verify Deployment

Wait 5-10 minutes for the model to download, then:

```bash
# Check service status
sudo systemctl status colpali

# Check Docker containers
docker ps

# Test health endpoint
curl http://localhost:8000/health
```

Access from browser:
- Swagger UI: `http://<VM-IP>:8000/docs`
- Health Check: `http://<VM-IP>:8000/health`

---

## Configuration Options

### Environment Variables

Edit `/opt/colpali/.env`:

```bash
# For Qdrant Cloud
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your-api-key
COLLECTION_NAME=colpali-embeddings-128

# For Local Qdrant (default)
QDRANT_HOST=qdrant
QDRANT_PORT=6333
COLLECTION_NAME=colpali_embeddings
```

### Enable GPU in Docker

Edit `/opt/colpali/docker-compose.yml` and uncomment:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

Then restart:

```bash
sudo systemctl restart colpali
```

---

## Monitoring and Maintenance

### View Logs

```bash
# Application logs via systemd
sudo journalctl -u colpali -f

# Docker container logs
cd /opt/colpali
docker-compose logs -f

# ColPali API logs only
docker logs colpali-api -f
```

### Service Management

```bash
# Start service
sudo systemctl start colpali

# Stop service
sudo systemctl stop colpali

# Restart service
sudo systemctl restart colpali

# Check status
sudo systemctl status colpali
```

### Update Application

```bash
# Stop service
sudo systemctl stop colpali

# Pull latest code
cd /path/to/source
git pull

# Copy new files
sudo cp api.py /opt/colpali/
sudo cp requirements.txt /opt/colpali/

# Rebuild and restart
cd /opt/colpali
docker-compose build
sudo systemctl start colpali
```

### Disk Space Management

```bash
# Check disk usage
df -h

# Clean Docker resources
docker system prune -a

# Clean old logs
sudo journalctl --vacuum-time=7d
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check detailed logs
sudo journalctl -u colpali -n 100 --no-pager

# Check Docker logs
docker-compose logs --tail=100
```

### Out of Memory

Symptoms: Container killed, "OOM" in logs

Solutions:
1. Upgrade VM size (more RAM)
2. Use smaller batch sizes
3. Enable swap:

```bash
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Model Download Fails

```bash
# Check network connectivity
curl -I https://huggingface.co

# Manually trigger download
docker exec -it colpali-api python3 -c "from colpali_engine.models import ColPali; ColPali.from_pretrained('vidore/colpali-v1.2')"
```

### GPU Not Detected

```bash
# Verify NVIDIA driver
nvidia-smi

# Check Docker GPU access
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi

# Reinstall NVIDIA Container Toolkit
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Connection Refused on Port 8000

```bash
# Check if container is running
docker ps

# Check container health
docker inspect colpali-api | grep -A 10 "Health"

# Check Azure NSG rules
# Ensure port 8000 is open in Network Security Group
```

### Qdrant Connection Failed

```bash
# For local Qdrant
docker logs qdrant

# For Qdrant Cloud
# Check .env file has correct URL and API key
# Test connectivity
curl -H "Api-Key: YOUR_API_KEY" https://your-cluster.cloud.qdrant.io:6333/health
```

---

## Security Recommendations

1. **Restrict SSH access** to specific IPs in NSG
2. **Use Azure Key Vault** for storing API keys
3. **Enable Azure Defender** for VM
4. **Set up Azure Backup** for VM
5. **Configure HTTPS** with nginx reverse proxy
6. **Restrict Qdrant port** (6333) access if using local Qdrant
7. **Use managed identities** for Azure resource access

---

## Cost Optimization

1. **Use Reserved Instances** for 1-3 year commitments (up to 72% savings)
2. **Auto-shutdown** during non-business hours
3. **Use Spot VMs** for dev/test workloads
4. **Right-size VM** based on actual usage metrics
5. **Use Qdrant Cloud** to avoid running Qdrant container locally

---

## Support

For issues:
1. Check logs (see Monitoring section)
2. Review Troubleshooting section
3. Open GitHub issue with logs and VM configuration