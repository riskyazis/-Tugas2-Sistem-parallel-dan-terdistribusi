# Deployment Guide

Complete guide for deploying the Distributed Synchronization System.

---

## Prerequisites

### Required Software

- Docker 20.10+
- Docker Compose 2.0+
- Python 3.10+ (for local development)
- Git

### System Requirements

- CPU: 2+ cores
- RAM: 4GB minimum, 8GB recommended
- Disk: 10GB free space
- Network: Docker bridge network support

---

## Quick Deployment (Docker)

### 1. Clone Repository

```bash
git clone <repository-url>
cd distributed-sync-system
```

### 2. Start Docker Cluster

```bash
cd docker
docker-compose up --build
```

This will start:

- **Node 1**: `http://localhost:5001` (Metrics: 9091)
- **Node 2**: `http://localhost:5002` (Metrics: 9092)
- **Node 3**: `http://localhost:5003` (Metrics: 9093)
- **Redis**: `localhost:6379`

### 3. Verify Deployment

```bash
# Check all containers are running
docker ps

# Check node 1 health
curl http://localhost:5001/health

# Check cluster info
curl http://localhost:5001/cluster
```

---

## Docker Configuration

### Environment Variables

Create `.env` file in `docker/` directory:

```bash
# Node Configuration
NODE_ID=1
NODE_HOST=0.0.0.0
NODE_PORT=5001

# Cluster
CLUSTER_SIZE=3
PEER_NODES=http://distributed-node-2:5002,http://distributed-node-3:5003

# Redis
REDIS_HOST=distributed-redis
REDIS_PORT=6379

# Raft
RAFT_ELECTION_TIMEOUT_MIN=150
RAFT_ELECTION_TIMEOUT_MAX=300
RAFT_HEARTBEAT_INTERVAL=50

# Cache
CACHE_COHERENCE_PROTOCOL=MESI
CACHE_TTL=300

# Logging
LOG_LEVEL=INFO
```

### Docker Compose Services

```yaml
version: "3.8"

services:
  distributed-node-1:
    build:
      context: ..
      dockerfile: docker/Dockerfile.node
    container_name: distributed-node-1
    environment:
      NODE_ID: 1
      NODE_PORT: 5001
      METRICS_PORT: 9091
    ports:
      - "5001:5001"
      - "9091:9091"
    networks:
      - distributed-network
    depends_on:
      - distributed-redis

  # ... (similar for node-2 and node-3)

  distributed-redis:
    image: redis:7-alpine
    container_name: distributed-redis
    ports:
      - "6379:6379"
    networks:
      - distributed-network

networks:
  distributed-network:
    driver: bridge
```

---

## Local Development Deployment

### 1. Setup Python Environment

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Start Redis

```bash
# Using Docker
docker run -d -p 6379:6379 --name redis redis:7-alpine

# Or install Redis locally
```

### 3. Run Nodes Manually

**Terminal 1 - Node 1:**

```bash
export NODE_ID=1
export NODE_PORT=5001
export PEER_NODES="http://localhost:5002,http://localhost:5003"
python run.py
```

**Terminal 2 - Node 2:**

```bash
export NODE_ID=2
export NODE_PORT=5002
export PEER_NODES="http://localhost:5001,http://localhost:5003"
python run.py
```

**Terminal 3 - Node 3:**

```bash
export NODE_ID=3
export NODE_PORT=5003
export PEER_NODES="http://localhost:5001,http://localhost:5002"
python run.py
```

---

## Production Deployment

### Using Kubernetes (Advanced)

Create Kubernetes manifests:

**1. ConfigMap:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: distributed-system-config
data:
  CLUSTER_SIZE: "3"
  REDIS_HOST: "redis-service"
  RAFT_ELECTION_TIMEOUT_MIN: "150"
  RAFT_ELECTION_TIMEOUT_MAX: "300"
```

**2. Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: distributed-node
spec:
  replicas: 3
  selector:
    matchLabels:
      app: distributed-node
  template:
    metadata:
      labels:
        app: distributed-node
    spec:
      containers:
        - name: node
          image: distributed-system:latest
          ports:
            - containerPort: 5001
          envFrom:
            - configMapRef:
                name: distributed-system-config
```

**3. Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: distributed-service
spec:
  selector:
    app: distributed-node
  ports:
    - port: 5001
      targetPort: 5001
  type: LoadBalancer
```

---

## Scaling

### Horizontal Scaling

To add more nodes:

1. Update `CLUSTER_SIZE` in configuration
2. Add new service in `docker-compose.yml`
3. Update `PEER_NODES` for all existing nodes
4. Restart cluster

Example adding node-4:

```yaml
distributed-node-4:
  build:
    context: ..
    dockerfile: docker/Dockerfile.node
  environment:
    NODE_ID: 4
    NODE_PORT: 5004
    CLUSTER_SIZE: 4
    PEER_NODES: "http://distributed-node-1:5001,http://distributed-node-2:5002,http://distributed-node-3:5003"
  ports:
    - "5004:5004"
```

---

## Monitoring

### Prometheus Integration

**prometheus.yml:**

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "distributed-system"
    static_configs:
      - targets:
          - "localhost:9091"
          - "localhost:9092"
          - "localhost:9093"
        labels:
          cluster: "distributed-system"
```

### Grafana Dashboard

Import dashboard for visualizing:

- Request latency
- Throughput
- Raft state
- Cache hit rate
- Queue depth

---

## Troubleshooting Deployment

### Container Fails to Start

```bash
# Check logs
docker logs distributed-node-1

# Check if ports are available
netstat -an | grep 5001

# Rebuild without cache
docker-compose build --no-cache
docker-compose up
```

### Nodes Can't Communicate

```bash
# Check network
docker network inspect distributed-network

# Test connectivity
docker exec distributed-node-1 ping distributed-node-2

# Check firewall rules
```

### Redis Connection Issues

```bash
# Test Redis connectivity
docker exec distributed-node-1 ping distributed-redis

# Check Redis is running
docker ps | grep redis

# Test Redis directly
redis-cli ping
```

---

## Backup and Recovery

### Backup Strategy

1. **Redis Data**: Use Redis persistence (RDB/AOF)
2. **Raft Logs**: Backup log files from each node
3. **Configuration**: Version control all config files

### Recovery Steps

1. Stop all nodes
2. Restore Redis data
3. Restore Raft logs
4. Restart nodes in sequence
5. Verify cluster health

---

## Security Considerations

### Production Checklist

- [ ] Enable TLS for inter-node communication
- [ ] Implement authentication for API endpoints
- [ ] Use secrets management for credentials
- [ ] Enable network policies/firewalls
- [ ] Regular security updates
- [ ] Monitor for suspicious activity
- [ ] Implement rate limiting
- [ ] Enable audit logging

---

## Performance Tuning

### Optimization Tips

1. **Raft Timeouts**: Adjust based on network latency
2. **Redis**: Enable persistence based on durability needs
3. **Connection Pooling**: Configure appropriate pool sizes
4. **Resource Limits**: Set Docker memory/CPU limits
5. **Logging Level**: Use INFO in production, DEBUG for troubleshooting

### Resource Limits (docker-compose.yml)

```yaml
services:
  distributed-node-1:
    # ...
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M
        reservations:
          cpus: "0.5"
          memory: 256M
```

---

## Health Checks

### Docker Health Check

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5001/health || exit 1
```

### Manual Health Check

```bash
# Check all nodes
for port in 5001 5002 5003; do
  echo "Node $port:"
  curl -s http://localhost:$port/health | jq
done
```

---

## Maintenance

### Rolling Updates

1. Update node-1, wait for health check
2. Update node-2, wait for health check
3. Update node-3, wait for health check

```bash
# Update node-1
docker-compose stop distributed-node-1
docker-compose up -d --build distributed-node-1

# Wait and verify
curl http://localhost:5001/health

# Repeat for other nodes
```

### Log Rotation

Configure Docker logging driver:

```yaml
services:
  distributed-node-1:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## Appendix

### Useful Commands

```bash
# View all logs
docker-compose logs -f

# View specific node logs
docker logs -f distributed-node-1

# Execute command in container
docker exec -it distributed-node-1 bash

# Restart single service
docker-compose restart distributed-node-1

# Stop all services
docker-compose down

# Remove volumes (clean state)
docker-compose down -v

# Check resource usage
docker stats
```

### Port Reference

| Service | HTTP | Metrics | Description  |
| ------- | ---- | ------- | ------------ |
| Node 1  | 5001 | 9091    | Primary node |
| Node 2  | 5002 | 9092    | Replica node |
| Node 3  | 5003 | 9093    | Replica node |
| Redis   | 6379 | -       | Data store   |

---

For more information, see:

- [Architecture Documentation](architecture.md)
- [API Specification](api_spec.yaml)
- [README](../README.md)
