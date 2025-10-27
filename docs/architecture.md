# Architecture Documentation

## System Overview

Sistem Distributed Synchronization ini dibangun dengan arsitektur multi-layer yang mengimplementasikan consensus-based distributed system.

## Layer Architecture

### 1. Communication Layer
**File**: `src/communication/`

#### Message Passing
- Asynchronous TCP-based communication
- Message serialization menggunakan JSON
- Request-response pattern dengan timeout
- Broadcast capability untuk cluster-wide messages

#### Failure Detection
- φ accrual failure detector
- Adaptive threshold berdasarkan heartbeat history
- Node state tracking (ALIVE, SUSPECTED, FAILED)
- Automatic recovery detection

### 2. Consensus Layer
**File**: `src/consensus/`

#### Raft Algorithm Implementation

**Components:**
1. **Leader Election**
   - Random election timeout (150-300ms)
   - RequestVote RPC
   - Vote counting dan majority detection
   - Term management

2. **Log Replication**
   - AppendEntries RPC
   - Log consistency checks
   - Commit index advancement
   - State machine application

3. **Safety Properties**
   - Election Safety: Max satu leader per term
   - Leader Append-Only: Leader tidak pernah overwrite/delete log
   - Log Matching: Log dengan index dan term sama berisi entry yang sama
   - Leader Completeness: Committed entry ada di semua future leaders
   - State Machine Safety: Nodes tidak akan apply berbeda untuk log index yang sama

### 3. Application Layer
**File**: `src/nodes/`

#### Lock Manager
**Algorithm**: Centralized locking dengan Raft consensus

**Features:**
- Shared locks (multiple readers)
- Exclusive locks (single writer)
- Lock timeout management
- Wait queue untuk lock requests

**Deadlock Detection:**
- Wait-for graph construction
- Cycle detection menggunakan DFS
- Youngest transaction abort untuk resolution

**Workflow:**
```
1. Client requests lock
2. Request forwarded to Raft leader
3. Leader appends to log
4. Log replicated to followers
5. Once committed, lock granted
6. Client acknowledged
```

#### Queue System
**Algorithm**: Consistent Hashing + Raft

**Features:**
- Partitioned queues menggunakan consistent hashing
- Virtual nodes untuk load distribution
- Message persistence ke disk
- In-flight message tracking
- Retry mechanism dengan exponential backoff
- Dead Letter Queue untuk failed messages

**Message Flow:**
```
Producer → Hash(queue_name) → Responsible Node → Persistence → Consumer
                                      ↓
                              Raft Replication
                                      ↓
                              Follower Nodes
```

#### Cache System
**Algorithm**: MESI Coherence Protocol

**States:**
- **Modified (M)**: Cache memiliki data terbaru, memory stale
- **Exclusive (E)**: Hanya cache ini yang memiliki data, sama dengan memory
- **Shared (S)**: Multiple caches memiliki data
- **Invalid (I)**: Cache line tidak valid

**State Transitions:**
```
        READ          WRITE
I  →    S/E      I  →   M
S  →    S        S  →   M + Invalidate Others
E  →    E        E  →   M
M  →    M        M  →   M
```

**Replacement Policy**: LRU (Least Recently Used)

## Data Flow

### Write Operation
```
1. Client → Leader
2. Leader → Append to log
3. Leader → Replicate to followers (AppendEntries RPC)
4. Followers → Append to log, respond success
5. Leader → Commit after majority
6. Leader → Apply to state machine
7. Leader → Respond to client
8. Leader → Notify followers of commit (next heartbeat)
```

### Read Operation
```
1. Client → Any node
2. Node → Check local cache
3. If miss → Check cluster
4. If not found → Check state machine
5. Return to client
```

## Failure Scenarios

### 1. Leader Failure
```
1. Followers detect timeout
2. Candidate emerges, starts election
3. RequestVote sent to all nodes
4. Majority vote → New leader
5. New leader sends heartbeats
6. Cluster operational
```

### 2. Network Partition
```
Case 1: Leader in majority partition
→ System continues normally
→ Minority partition cannot commit

Case 2: Leader in minority partition  
→ Majority partition elects new leader
→ Old leader steps down when rejoins
```

### 3. Message Loss
```
1. Timeout detection
2. Retry mechanism activated
3. If persistent failure → Node marked FAILED
4. System continues without failed node
```

## Performance Characteristics

### Time Complexity
- Leader election: O(n) where n = number of nodes
- Lock acquisition: O(log n) for deadlock detection
- Cache lookup: O(1) average
- Queue operations: O(1) average

### Space Complexity
- Raft log: O(m) where m = number of operations
- Lock table: O(k) where k = number of locks
- Cache: O(c) where c = cache capacity
- Queue: O(q) where q = queue size

## Scalability

### Horizontal Scaling
- Add more nodes to cluster
- Consistent hashing redistributes load
- Raft consensus overhead increases with cluster size
- Recommended: 3-7 nodes for optimal performance

### Vertical Scaling
- Increase cache size per node
- Larger log buffer
- More concurrent connections

## Consistency Guarantees

### Raft Consensus
- **Strong consistency** for committed entries
- **Linearizability** for client operations
- **Durability** through log replication

### Cache
- **Eventual consistency** with MESI invalidation
- **Bounded staleness** based on invalidation propagation time

### Queue
- **At-least-once delivery** guarantee
- **FIFO ordering** per partition
- **No ordering** across partitions

## Monitoring & Observability

### Metrics Collected
1. **Throughput**: Operations per second
2. **Latency**: P50, P95, P99 percentiles
3. **Availability**: Uptime percentage
4. **Error Rate**: Failed operations percentage

### Logging
- Structured JSON logs
- Log levels: DEBUG, INFO, WARNING, ERROR
- Request tracing dengan correlation IDs

## Security Considerations

### Current Implementation
- No authentication (development only)
- No encryption (development only)
- No authorization (development only)

### Production Requirements
- TLS for inter-node communication
- Mutual TLS authentication
- RBAC for access control
- Audit logging

## Future Improvements

1. **Multi-Raft**: Multiple Raft groups untuk partitioning
2. **Snapshot**: Log compaction untuk space efficiency
3. **Read Optimization**: Follower reads dengan lease mechanism
4. **Dynamic Membership**: Runtime cluster reconfiguration
5. **Geo-Distribution**: Multi-region support dengan latency-aware routing

## References

1. Ongaro, D., & Ousterhout, J. (2014). In search of an understandable consensus algorithm (extended version). USENIX ATC.
2. Lamport, L. (1998). The part-time parliament. ACM TOCS.
3. Karger, D., et al. (1997). Consistent hashing and random trees. STOC.
4. Sweazey, P., & Smith, A. J. (1986). A class of compatible cache consistency protocols. ISCA.
