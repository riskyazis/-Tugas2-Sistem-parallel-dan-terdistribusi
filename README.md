# Distributed Synchronization System

Sistem sinkronisasi terdistribusi yang mengimplementasikan Queue, Cache, dan Lock Manager dengan Raft consensus algorithm.

## 📋 Overview

Implementasi sistem sinkronisasi terdistribusi dengan fitur:

- **Raft Consensus Algorithm** - Leader election dan log replication
- **Distributed Lock Manager** - Lock acquisition dengan deadlock detection
- **Distributed Queue** - FIFO queue dengan consistent hashing
- **Distributed Cache** - Cache dengan MESI coherence protocol
- **Failure Detection** - Heartbeat-based failure detector
- **Docker Containerization** - 3 nodes + Redis cluster

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Distributed Cluster                         │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐          │
│  │  Node 1  │◄────►│  Node 2  │◄────►│  Node 3  │          │
│  │  :5001   │      │  :5002   │      │  :5003   │          │
│  │          │      │          │      │          │          │
│  │ • Raft   │      │ • Raft   │      │ • Raft   │          │
│  │ • Queue  │      │ • Queue  │      │ • Queue  │          │
│  │ • Cache  │      │ • Cache  │      │ • Cache  │          │
│  │ • Lock   │      │ • Lock   │      │ • Lock   │          │
│  └────┬─────┘      └────┬─────┘      └────┬─────┘          │
│       │                  │                  │                │
│       └──────────────────┼──────────────────┘                │
│                          │                                   │
│                    ┌─────▼─────┐                            │
│                    │   Redis   │                            │
│                    │   :6379   │                            │
│                    └───────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

### Components

- **Raft Consensus**: Leader election, heartbeats, log replication
- **Queue Node**: Distributed FIFO queue dengan consistent hashing
- **Cache Node**: MESI cache coherence (Modified, Exclusive, Shared, Invalid)
- **Lock Manager**: Distributed locking dengan Ricart-Agrawala algorithm
- **Message Passing**: Async HTTP communication antar nodes
- **Failure Detector**: Heartbeat-based dengan configurable timeout

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.10+

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

Sistem akan menjalankan:

- **Node 1**: http://localhost:5001
- **Node 2**: http://localhost:5002
- **Node 3**: http://localhost:5003
- **Redis**: localhost:6379

### 3. Verify Cluster

```bash
curl http://localhost:5001/health
curl http://localhost:5001/cluster
```

## � API Endpoints

### Health & Cluster Management

- `GET /health` - Health check status
- `GET /cluster` - Cluster configuration & node info
- `GET /stats` - Node statistics
- `GET /metrics` - Prometheus metrics

### Queue Operations

```bash
# Enqueue message
curl -X POST http://localhost:5001/api/queue/enqueue \
  -H "Content-Type: application/json" \
  -d '{"queue": "my_queue", "message": {"data": "hello"}}'

# Dequeue message
curl -X POST http://localhost:5001/api/queue/dequeue \
  -H "Content-Type: application/json" \
  -d '{"queue": "my_queue"}'
```

### Cache Operations

```bash
# Set cache value
curl -X POST http://localhost:5001/api/cache/set \
  -H "Content-Type: application/json" \
  -d '{"key": "mykey", "value": {"data": "myvalue"}}'

# Get cache value
curl http://localhost:5001/api/cache/get?key=mykey

# Delete cache value
curl -X DELETE http://localhost:5001/api/cache/delete?key=mykey
```

### Lock Operations

```bash
# Acquire lock
curl -X POST http://localhost:5001/api/lock/acquire \
  -H "Content-Type: application/json" \
  -d '{"resource": "critical_section", "requester": "client_1"}'

# Release lock
curl -X POST http://localhost:5001/api/lock/release \
  -H "Content-Type: application/json" \
  -d '{"resource": "critical_section", "requester": "client_1"}'
```

**Interactive API Documentation**: http://localhost:5001/docs

## 📁 Project Structure

```
distributed-sync-system/
├── src/
│   ├── nodes/              # Node implementations
│   │   ├── __init__.py
│   │   ├── base_node.py
│   │   ├── lock_manager.py
│   │   ├── queue_node.py
│   │   └── cache_node.py
│   ├── consensus/          # Consensus algorithms
│   │   ├── __init__.py
│   │   └── raft.py
│   ├── communication/      # Inter-node communication
│   │   ├── __init__.py
│   │   ├── message_passing.py
│   │   └── failure_detector.py
│   └── utils/              # Utilities
│       ├── __init__.py
│       ├── config.py
│       └── metrics.py
├── tests/
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration tests
│   └── performance/        # Performance tests
├── docker/
│   ├── Dockerfile.node     # Node container image
│   └── docker-compose.yml  # Cluster orchestration
├── docs/
│   ├── architecture.md     # System architecture
│   ├── api_spec.yaml       # OpenAPI specification
│   └── deployment_guide.md # Deployment instructions
├── benchmarks/
│   └── load_test_scenarios.py  # Load testing scenarios
├── requirements.txt        # Python dependencies
├── .env.example           # Environment configuration
└── README.md              # This file
```

## � Technical Details

### Raft Consensus Algorithm

Implementasi Raft untuk distributed consensus dengan:

- **Leader Election**: Timeout-based election dengan majority voting
- **Log Replication**: Leader replikasi log entries ke followers
- **Heartbeats**: Periodic heartbeats untuk maintain leadership
- **Term Management**: Monotonically increasing term numbers

### MESI Cache Coherence Protocol

Cache coherence menggunakan MESI protocol:

- **Modified (M)**: Cache line modified, exclusive ownership
- **Exclusive (E)**: Cache line clean, exclusive ownership
- **Shared (S)**: Cache line shared dengan nodes lain
- **Invalid (I)**: Cache line tidak valid

### Distributed Lock Manager

Lock acquisition dengan:

- **Ricart-Agrawala Algorithm**: Request-based mutual exclusion
- **Deadlock Detection**: Timeout-based detection
- **Priority Ordering**: Timestamp-based priority untuk fairness

### Message Passing

Async HTTP-based communication dengan:

- **aiohttp**: Async HTTP client/server
- **JSON serialization**: orjson untuk performance
- **Retry mechanism**: Automatic retry pada network failures
- **Timeout handling**: Configurable request timeouts

## 🧪 Testing

### Manual API Testing

Test Queue operations:

```bash
# Enqueue
curl -X POST http://localhost:5001/api/queue/enqueue \
  -H "Content-Type: application/json" \
  -d '{"queue": "test", "message": {"id": 1, "data": "test"}}'

# Dequeue
curl -X POST http://localhost:5001/api/queue/dequeue \
  -H "Content-Type: application/json" \
  -d '{"queue": "test"}'
```

Test Cache operations:

```bash
# Set
curl -X POST http://localhost:5001/api/cache/set \
  -H "Content-Type: application/json" \
  -d '{"key": "test_key", "value": {"message": "hello"}}'

# Get
curl http://localhost:5001/api/cache/get?key=test_key
```

### Load Testing

Run load tests dengan berbagai scenarios:

```bash
python benchmarks/load_test_scenarios.py
```

## 📊 Configuration

Copy `.env.example` ke `.env` dan sesuaikan:

```bash
# Node Configuration
NODE_ID=1
NODE_HOST=0.0.0.0
NODE_PORT=5001

# Cluster Configuration
CLUSTER_SIZE=3
PEER_NODES=node2:5002,node3:5003

# Raft Configuration
RAFT_ELECTION_TIMEOUT_MIN=150
RAFT_ELECTION_TIMEOUT_MAX=300
RAFT_HEARTBEAT_INTERVAL=50

# Redis Configuration
REDIS_HOST=redis
REDIS_PORT=6379
```

## 🛠️ Development

### Install Dependencies

```bash
pip install -r requirements.txt
```

Dependencies include:

- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `aiohttp` - Async HTTP client/server
- `redis` - Redis client (async support)
- `pydantic` - Data validation
- `orjson` - Fast JSON serialization
- `prometheus-client` - Metrics collection
- `psutil` - System monitoring

### Running Single Node (Development)

```bash
# Set environment variables
export NODE_ID=1
export NODE_PORT=5001
export REDIS_HOST=localhost

# Run node
python -m src.nodes.base_node
```

### Docker Development

Build dan run dengan docker-compose:

```bash
cd docker
docker-compose up --build
```

Rebuild setelah code changes:

```bash
docker-compose down
docker-compose up --build
```

View logs:

```bash
docker-compose logs -f node1
docker-compose logs -f node2
docker-compose logs -f node3
```

## 🐛 Troubleshooting

### Port Already in Use

```bash
# Linux/Mac
lsof -i :5001
kill -9 <PID>

# Windows
netstat -ano | findstr "5001"
taskkill /PID <PID> /F
```

### Redis Connection Failed

```bash
# Check Redis is running
docker ps | grep redis

# Restart Redis
docker-compose restart redis
```

### Docker Build Failed

```bash
# Clean everything
docker-compose down -v
docker system prune -a

# Rebuild
docker-compose up --build
```

### Node Cannot Communicate

Check network connectivity:

```bash
# From host
curl http://localhost:5001/health
curl http://localhost:5002/health
curl http://localhost:5003/health

# Inside container
docker exec -it distributed-node-1 sh
wget -O- http://node2:5002/health
```

## 📖 Documentation

- **Architecture**: `docs/architecture.md` - System design & components
- **API Specification**: `docs/api_spec.yaml` - OpenAPI 3.0 spec
- **Deployment Guide**: `docs/deployment_guide.md` - Production deployment

## 🤝 Contributing

1. Fork repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

