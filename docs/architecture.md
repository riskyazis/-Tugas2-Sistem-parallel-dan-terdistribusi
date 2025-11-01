# Arsitektur Sistem - Distributed Synchronization System

## 📐 Overview

Sistem ini mengimplementasikan distributed synchronization menggunakan Raft Consensus Algorithm sebagai fondasi untuk koordinasi antar node. Sistem terdiri dari beberapa komponen utama yang bekerja bersama untuk menyediakan distributed locking, queueing, dan caching.

## 🏗️ Komponen Utama

### 1. Raft Consensus Layer

**Tujuan**: Menyediakan consensus dan koordinasi antar nodes

**Komponen**:

- **Leader Election**: Algoritma untuk memilih leader node
- **Log Replication**: Replikasi state changes ke semua nodes
- **Safety Guarantee**: Memastikan consistency across cluster

**States**:

- **Follower**: State default, menerima updates dari leader
- **Candidate**: State transisi saat election
- **Leader**: Node yang mengkoordinasi cluster

**Flow Leader Election**:

```
┌──────────┐
│ Follower │───timeout───┐
└──────────┘             │
                         ▼
                  ┌───────────┐
     lost────────│ Candidate │
     election    └───────────┘
                         │
                    won election
                         │
                         ▼
                   ┌─────────┐
                   │ Leader  │
                   └─────────┘
```

### 2. Distributed Lock Manager (DLM)

**Tujuan**: Koordinasi akses ke shared resources

**Fitur**:

- **Shared Locks**: Multiple readers concurrent access
- **Exclusive Locks**: Single writer access
- **Deadlock Detection**: Cycle detection dalam wait-for graph
- **Lock Timeout**: Automatic lock release

**Lock Acquisition Flow**:

```
Client Request
     │
     ▼
Is Leader?──No──►Forward to Leader
     │
    Yes
     │
     ▼
Check Lock Availability
     │
     ├──Available──►Grant Lock──►Replicate via Raft
     │
     └──Not Available──►Add to Wait Queue
```

**Deadlock Detection**:

- Build wait-for graph
- Detect cycles menggunakan DFS
- Resolution: Abort salah satu transaction (future work)

### 3. Distributed Queue System

**Tujuan**: Message passing dengan reliability guarantee

**Fitur**:

- **Consistent Hashing**: Distribute messages across nodes
- **At-Least-Once Delivery**: Message tidak hilang
- **Message Persistence**: Saved to Redis
- **Consumer Groups**: Multiple consumers

**Message Flow**:

```
Producer
   │
   ▼
Enqueue──►Consistent Hash──►Target Node
   │
   ▼
Redis Persistence
   │
   ▼
Consumer Dequeue
   │
   ├──Success──►ACK──►Remove from Queue
   │
   └──Failure──►NACK──►Requeue
```

**Consistent Hashing**:

- Virtual nodes untuk load balancing
- Minimal disruption saat node failure
- Ring-based key distribution

### 4. Distributed Cache (MESI Protocol)

**Tujuan**: Fast data access dengan consistency guarantee

**MESI States**:

- **Modified (M)**: Cache dirty, exclusive ownership
- **Exclusive (E)**: Cache clean, exclusive ownership
- **Shared (S)**: Cache clean, dapat ada di multiple caches
- **Invalid (I)**: Cache tidak valid

**State Transitions**:

```
        Read Hit
    ┌─────────────┐
    │      ▼      │
[I]───Read──►[S]──┴──►[E]
 │            │         │
Write        Write    Write
 │            │         │
 └──────────►[M]◄───────┘
```

**Cache Coherence Flow**:

```
Node 1 Write Request
        │
        ▼
    Invalidate Other Caches
        │
        ├──►Node 2: Mark [I]
        ├──►Node 3: Mark [I]
        └──►Node 4: Mark [I]
        │
        ▼
    Update Local Cache [M]
```

## 🔄 Interaksi Antar Komponen

### Complete System Flow

```
┌─────────────────────────────────────────────────────────┐
│                    Client Layer                          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│               FastAPI HTTP Server                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │Lock API  │  │Queue API │  │Cache API │             │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘             │
└───────┼─────────────┼─────────────┼────────────────────┘
        │             │             │
        ▼             ▼             ▼
┌────────────────────────────────────────────────────────┐
│           Application Components Layer                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │   DLM    │  │  Queue   │  │  Cache   │            │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘            │
└───────┼─────────────┼─────────────┼───────────────────┘
        │             │             │
        └─────────────┼─────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────────────┐
│              Raft Consensus Layer                       │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Leader    │  │  Follower 1  │  │  Follower 2  │ │
│  │  Election   │  │              │  │              │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘ │
└─────────┼────────────────┼─────────────────┼─────────┘
          │                │                 │
          └────────────────┼─────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────┐
│          Communication Layer                            │
│  ┌──────────────┐  ┌───────────────┐                  │
│  │   Message    │  │    Failure    │                  │
│  │   Passing    │  │   Detection   │                  │
│  └──────┬───────┘  └───────┬───────┘                  │
└─────────┼──────────────────┼─────────────────────────┘
          │                  │
          └──────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────┐
│                 Network Layer                           │
│              HTTP/JSON Messages                         │
│         (Could be gRPC for production)                  │
└────────────────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────┐
│           Persistence Layer (Redis)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │  Raft    │  │  Queue   │  │  Cache   │            │
│  │  State   │  │Messages  │  │  Backup  │            │
│  └──────────┘  └──────────┘  └──────────┘            │
└────────────────────────────────────────────────────────┘
```

## 🛡️ Fault Tolerance

### Network Partition Handling

**Scenario 1: Leader Isolation**

```
Normal:                 Partition:
┌─L─┐                   ┌─L─┐  │  ┌─F─┐
│   │◄──►┌─F─┐         │(isolated) │   │◄──►┌─F─┐
└───┘    └───┘         └───┘  │  └───┘    └───┘
  ▲        ▲                   │    │        │
  │        │                   │    │   elect new
  ▼        ▼                   │    ▼      leader
┌─F─┐    ┌─F─┐               │  ┌─F─┐    ┌─L'─┐
└───┘    └───┘               │  └───┘    └────┘

Result: Majority partition elects new leader
```

**Scenario 2: Split Brain Prevention**

- Raft requires majority untuk decisions
- Minority partition tidak bisa commit changes
- Prevents data inconsistency

### Node Failure Recovery

**Detection**:

1. Heartbeat timeout
2. Failed RPC calls
3. Failure detector notification

**Recovery Steps**:

```
1. Detect Failure
   │
   ▼
2. Update Cluster Membership
   │
   ▼
3. Redistribute Load
   │  ┌──► Queue Messages
   │  ├──► Cache Entries
   │  └──► Lock Ownership
   │
   ▼
4. Start Recovery Protocol
   │
   ▼
5. Node Rejoin
   │
   ▼
6. State Synchronization
```

## 📊 Performance Considerations

### Scalability

**Horizontal Scaling**:

- Add more nodes untuk increase capacity
- Consistent hashing minimize data movement
- Lock distribution via Raft

**Bottlenecks**:

- Leader sebagai single point for writes
- Network latency untuk consensus
- Redis I/O untuk persistence

**Optimizations**:

1. **Batching**: Group operations
2. **Pipelining**: Async message passing
3. **Caching**: Local cache untuk reads
4. **Connection Pooling**: Reuse connections

### Latency Analysis

**Lock Acquisition**:

- Local: 1-2 ms
- Leader: 5-10 ms (1 RTT + consensus)
- Follower: 10-20 ms (2 RTT + consensus)

**Queue Operations**:

- Enqueue: 2-5 ms (with persistence)
- Dequeue: 1-3 ms (from memory)

**Cache Operations**:

- Hit: 0.5-1 ms
- Miss: 5-10 ms (fetch from source)
- Invalidation: 2-5 ms (broadcast)

## 🔐 Security Considerations

### Communication Security

- TLS encryption untuk inter-node communication (optional)
- Certificate-based authentication
- Message signing untuk integrity

### Access Control

- RBAC untuk API endpoints
- Token-based authentication
- Audit logging semua operations

## 🎯 Design Decisions

### Why Raft over Paxos?

- Lebih mudah dipahami dan implement
- Clear leader election
- Good performance

### Why HTTP/JSON over gRPC?

- Simplicity untuk demo
- Easy debugging
- Human-readable
- Can upgrade to gRPC easily

### Why MESI over other protocols?

- Industry standard
- Good balance performance/complexity
- Well-documented

### Why Redis for persistence?

- Fast in-memory operations
- Persistence options (AOF/RDB)
- Simple data structures
- Wide adoption

## 🔄 Future Improvements

1. **Multi-Raft**: Separate Raft groups untuk different services
2. **Read Replicas**: Scale read operations
3. **Sharding**: Horizontal partitioning
4. **Compression**: Reduce network traffic
5. **Encryption**: End-to-end security
6. **Monitoring**: Advanced metrics dan alerting
7. **Auto-scaling**: Dynamic cluster size

---

**Referensi**:

- Raft Paper: https://raft.github.io/raft.pdf
- MESI Protocol: Computer Architecture textbooks
- Distributed Systems: Tanenbaum & Van Steen
