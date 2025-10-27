# Deployment Guide

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Local Development](#local-development)
3. [Docker Deployment](#docker-deployment)
4. [Production Deployment](#production-deployment)
5. [Troubleshooting](#troubleshooting)

## Prerequisites

### System Requirements
- **OS**: Linux (Ubuntu 20.04+), macOS 10.15+, Windows 10 dengan WSL2
- **CPU**: 2+ cores
- **RAM**: 4GB minimum, 8GB recommended
- **Disk**: 10GB free space
- **Network**: Stable network connection

### Software Requirements
```bash
# Python
python --version  # 3.8 or higher

# Docker
docker --version  # 20.10 or higher
docker-compose --version  # 1.29 or higher

# Git
git --version  # 2.25 or higher
```

## Local Development

### Step 1: Clone dan Setup

```bash
# Clone repository
git clone https://github.com/yourusername/distributed-sync-system.git
cd distributed-sync-system

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Linux/macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Konfigurasi

```bash
# Copy environment template
cp .env.example .env

# Edit .env file
nano .env  # atau editor pilihan Anda
```

**Konfigurasi .env untuk development:**
```env
NODE_ID=node1
NODE_HOST=localhost
NODE_PORT=5000
CLUSTER_NODES=node1:5000,node2:5001,node3:5002
LOG_LEVEL=DEBUG
METRICS_ENABLED=true
METRICS_PORT=9090
```

### Step 3: Jalankan Single Node

```bash
# Create necessary directories
mkdir -p logs data

# Run node
python -m src.main
```

### Step 4: Jalankan Multiple Nodes (Development)

**Terminal 1 - Node 1:**
```bash
export NODE_ID=node1
export NODE_PORT=5000
export METRICS_PORT=9090
export CLUSTER_NODES=node1:5000,node2:5001,node3:5002
python -m src.main
```

**Terminal 2 - Node 2:**
```bash
export NODE_ID=node2
export NODE_PORT=5001
export METRICS_PORT=9091
export CLUSTER_NODES=node1:5000,node2:5001,node3:5002
python -m src.main
```

**Terminal 3 - Node 3:**
```bash
export NODE_ID=node3
export NODE_PORT=5002
export METRICS_PORT=9092
export CLUSTER_NODES=node1:5000,node2:5001,node3:5002
python -m src.main
```

## Docker Deployment

### Step 1: Build Images

```bash
# Build Docker image
docker build -t distributed-sync-system:latest .

# Verify image
docker images | grep distributed-sync-system
```

### Step 2: Run with Docker Compose

```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f

# View specific node logs
docker-compose logs -f node1
```

### Step 3: Verify Deployment

```bash
# Check node1 health
curl http://localhost:5000/

# Check node2 health
curl http://localhost:5001/

# Check node3 health
curl http://localhost:5002/

# Check metrics
curl http://localhost:9090/metrics
curl http://localhost:9091/metrics
curl http://localhost:9092/metrics
```

### Step 4: Scaling

```bash
# Scale to 5 nodes
docker-compose up -d --scale node=5

# Scale down
docker-compose up -d --scale node=3
```

### Step 5: Stop Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes
docker-compose down -v

# Stop and remove images
docker-compose down --rmi all
```

## Production Deployment

### Option 1: Docker Swarm

```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml distributed-system

# Check services
docker service ls

# Scale service
docker service scale distributed-system_node=5

# Update service
docker service update --image distributed-sync-system:v2 distributed-system_node

# Remove stack
docker stack rm distributed-system
```

### Option 2: Kubernetes

**1. Create namespace:**
```bash
kubectl create namespace distributed-system
```

**2. Create deployment (deployment.yaml):**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: distributed-sync-system
  namespace: distributed-system
spec:
  replicas: 3
  selector:
    matchLabels:
      app: distributed-sync-system
  template:
    metadata:
      labels:
        app: distributed-sync-system
    spec:
      containers:
      - name: node
        image: distributed-sync-system:latest
        ports:
        - containerPort: 5000
        - containerPort: 9090
        env:
        - name: NODE_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: CLUSTER_NODES
          value: "node1:5000,node2:5001,node3:5002"
```

**3. Deploy:**
```bash
kubectl apply -f deployment.yaml
kubectl get pods -n distributed-system
```

### Option 3: Systemd Service

**1. Create service file (/etc/systemd/system/distributed-node.service):**
```ini
[Unit]
Description=Distributed Sync System Node
After=network.target

[Service]
Type=simple
User=distributed
WorkingDirectory=/opt/distributed-system
Environment="NODE_ID=node1"
Environment="NODE_PORT=5000"
Environment="CLUSTER_NODES=node1:5000,node2:5001,node3:5002"
ExecStart=/opt/distributed-system/venv/bin/python -m src.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**2. Enable dan start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable distributed-node
sudo systemctl start distributed-node
sudo systemctl status distributed-node
```

## Monitoring Setup

### Prometheus Configuration

**prometheus.yml:**
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'distributed-system'
    static_configs:
      - targets:
        - 'localhost:9090'
        - 'localhost:9091'
        - 'localhost:9092'
        labels:
          cluster: 'main'
```

### Grafana Dashboard

```bash
# Start Grafana
docker run -d -p 3000:3000 grafana/grafana

# Access: http://localhost:3000
# Default login: admin/admin

# Add Prometheus data source
# URL: http://localhost:9090

# Import dashboard from docs/grafana-dashboard.json
```

## Health Checks

### Manual Health Check Script

```bash
#!/bin/bash
# health_check.sh

NODES=("localhost:5000" "localhost:5001" "localhost:5002")

for node in "${NODES[@]}"; do
    echo "Checking $node..."
    curl -s "http://$node/health" || echo "FAILED"
done
```

### Automated Health Check (Systemd)

```ini
[Unit]
Description=Health Check for Distributed System

[Timer]
OnBootSec=5min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
```

## Backup and Recovery

### Backup Script

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backup/distributed-system"
DATE=$(date +%Y%m%d-%H%M%S)

# Backup data directory
tar -czf "$BACKUP_DIR/data-$DATE.tar.gz" data/

# Backup logs
tar -czf "$BACKUP_DIR/logs-$DATE.tar.gz" logs/

# Keep only last 7 days
find "$BACKUP_DIR" -mtime +7 -delete
```

### Recovery

```bash
# Stop system
docker-compose down

# Restore data
tar -xzf backup/data-20240101-120000.tar.gz

# Start system
docker-compose up -d
```

## Security Hardening

### 1. Network Security

```bash
# UFW rules
sudo ufw allow 5000:5002/tcp  # Node ports
sudo ufw allow 9090:9092/tcp  # Metrics ports
sudo ufw enable
```

### 2. Docker Security

```yaml
# docker-compose.yml additions
services:
  node:
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp
```

### 3. TLS Configuration (Production)

```bash
# Generate certificates
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365

# Update .env
TLS_ENABLED=true
TLS_CERT_PATH=/certs/cert.pem
TLS_KEY_PATH=/certs/key.pem
```

## Troubleshooting

### Common Issues

**1. Port already in use**
```bash
# Find process using port
lsof -i :5000
netstat -ano | findstr :5000  # Windows

# Kill process
kill -9 <PID>
```

**2. Docker container not starting**
```bash
# Check logs
docker-compose logs node1

# Check container status
docker ps -a

# Inspect container
docker inspect distributed-system_node1_1
```

**3. Nodes cannot connect**
```bash
# Check network
docker network inspect distributed-net

# Check DNS resolution
docker exec node1 ping node2

# Check firewall
sudo iptables -L
```

**4. High memory usage**
```bash
# Check memory
docker stats

# Limit memory in docker-compose.yml
services:
  node:
    mem_limit: 512m
```

**5. Log rotation not working**
```bash
# Setup logrotate
cat > /etc/logrotate.d/distributed-system << EOF
/opt/distributed-system/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    missingok
}
EOF
```

### Performance Tuning

```bash
# Linux kernel tuning
echo 'net.ipv4.tcp_tw_reuse = 1' >> /etc/sysctl.conf
echo 'net.core.somaxconn = 4096' >> /etc/sysctl.conf
sysctl -p

# Docker daemon tuning
# /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

## Maintenance

### Rolling Update

```bash
# Update one node at a time
docker-compose stop node1
docker-compose up -d node1
# Wait for node1 to sync
docker-compose stop node2
docker-compose up -d node2
# Wait for node2 to sync
docker-compose stop node3
docker-compose up -d node3
```

### Log Management

```bash
# View recent logs
docker-compose logs --tail=100 -f

# Clear logs
docker-compose down
docker system prune -a --volumes
```

### Database Cleanup

```bash
# Clean old messages
python -m src.scripts.cleanup --days=7

# Compact logs
python -m src.scripts.compact_logs
```

## Contact & Support

- **Documentation**: [GitHub Wiki](https://github.com/yourusername/distributed-sync-system/wiki)
- **Issues**: [GitHub Issues](https://github.com/yourusername/distributed-sync-system/issues)
- **Email**: your-email@example.com

---

**Last Updated**: October 2024
