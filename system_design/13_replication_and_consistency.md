# 13 — Replication and Consistency in Practice

## The Problem

Your database server handles all reads and writes. It's a single point of failure — if it dies, your entire application goes down. Even if it doesn't die, a single server has a throughput ceiling: one machine can only process so many queries per second.

Replication solves both problems by maintaining copies of your data on multiple servers. But the moment you have multiple copies, you face the fundamental question of distributed data: when a write happens on one copy, when (and how) do the other copies get updated? The answer to this question determines your system's consistency, availability, latency, and failure behavior.

---

## The Naive Approach and Why It Fails

**Naive approach: "I'll just copy the database to a second server every night."**

A nightly backup-and-restore is not replication — it's backup with a 24-hour recovery point. If the primary dies at 11pm, you lose an entire day of data. And during the restore (which can take hours for a large database), your application is completely down.

Real replication is continuous, incremental, and (ideally) automatic. Changes to the primary are streamed to replicas as they happen, not batched overnight.

---

## The Real Mechanism

### Leader-Follower (Single-Leader) Replication

The most common replication topology. One node is the **leader** (primary, master). All writes go to the leader. The leader streams changes to one or more **followers** (replicas, secondaries). Reads can go to any node.

```
            ┌──────────┐
  Writes →  │  Leader  │  (The single source of truth for writes)
            └──┬───┬───┘
               │   │      WAL stream (Write-Ahead Log)
         ┌─────┘   └─────┐
         ▼               ▼
   ┌──────────┐    ┌──────────┐
   │ Follower │    │ Follower │   ← Reads can be served from here
   └──────────┘    └──────────┘
```

**Synchronous vs Asynchronous Replication — The Core Tradeoff:**

```
Synchronous:
  1. Client sends write to Leader
  2. Leader writes to its WAL
  3. Leader sends WAL entry to ALL followers
  4. Leader waits for ALL followers to confirm they've written it
  5. Leader ACKs the client: "Write committed"
  
  Guarantee: If the leader dies, any follower has the complete data. Zero data loss.
  Cost: Every write is as slow as the SLOWEST follower. If a follower is on a 
        congested network or slow disk, ALL writes wait for it.
  
  Used by: Financial systems, regulatory systems where data loss is unacceptable.

Semi-Synchronous (practical middle ground):
  1. Leader waits for ONE follower to confirm (not all)
  2. Other followers receive the write asynchronously
  
  Guarantee: At least one follower is always up to date. Tolerable data loss risk.
  Used by: PostgreSQL's default for high-availability setups.

Asynchronous (most common):
  1. Client sends write to Leader
  2. Leader writes to its WAL
  3. Leader ACKs the client immediately: "Write committed"
  4. Leader sends WAL entry to followers eventually (background process)
  
  Guarantee: None. If the leader dies before the WAL entry reaches any follower,
             that write is permanently lost.
  Cost: Replication lag. Followers are behind the leader by 10ms to several seconds.
  
  Used by: Most applications. The speed benefit outweighs the tiny data loss risk.
```

**Replication Lag — The Bug That Looks Like a UI Bug:**

Replication lag is the time between a write being committed on the leader and that write being visible on a follower. With async replication, this is typically 10-100ms but can spike to seconds during high load.

```
Timeline (async replication, 50ms lag):
  
  T=0ms:    User updates profile: name = "Alice Smith" → Leader
  T=1ms:    Leader writes, ACKs user: "Updated!"
  T=2ms:    User's browser reloads profile → load balancer sends to Follower
  T=2ms:    Follower still has old data (hasn't received WAL entry yet)
  T=2ms:    User sees: "Alice Jones" ← OLD NAME
  T=50ms:   Follower receives WAL entry, applies it
  T=51ms:   If user refreshes again → "Alice Smith" ← correct
  
  User's experience: "I changed my name but it didn't save! ...oh wait, now it did."
```

**Three Consistency Guarantees That Fix Replication Lag Bugs:**

```
1. Read-Your-Writes (Read-After-Write) Consistency:
   After a user writes, their subsequent reads go to the Leader (not a follower).
   Other users can still read from followers (stale is fine for them).
   
   Implementation: For 10 seconds after a write, route that user's reads to Leader.
   
2. Monotonic Reads:
   A user never sees data go backward. If they read X=5 from Replica A,
   they won't later read X=3 from Replica B (which is further behind).
   
   Implementation: Pin each user's reads to a specific replica (sticky sessions).
   
3. Consistent Prefix Reads:
   If write A happened before write B, no reader sees B without A.
   
   Example without this guarantee:
     Chat: Alice says "How are you?" → Bob says "Good!"
     Reader sees: "Good!" before "How are you?" (wrong order)
   
   Implementation: Ensure causally related writes go to the same partition.
```

### Multi-Leader Replication

Multiple nodes can accept writes. Each leader replicates its writes to all other leaders.

```
   ┌──────────┐          ┌──────────┐
   │ Leader A │ ←──────→ │ Leader B │    (Bi-directional replication)
   │ (US-East)│          │ (EU-West)│
   └──────────┘          └──────────┘
```

**The promise:** Writes are fast everywhere. A user in Europe writes to the European leader (5ms) instead of the US leader (100ms). Both leaders accept writes concurrently.

**The nightmare: Write Conflicts.**

```
T=0:  User in US updates document title to "Report v2" → Leader A
T=0:  User in EU updates document title to "Bericht v2" → Leader B
T=1:  Both leaders replicate to each other
T=1:  CONFLICT: document.title was set to two different values simultaneously

Resolution strategies:
  - Last-Write-Wins (LWW): Use timestamps. "Bericht v2" at T=0.001 wins over
    "Report v2" at T=0.000. PROBLEM: clock synchronization across continents
    is imperfect. You may silently drop a valid write.
  
  - Merge: Application-level logic. Title becomes "Report v2 / Bericht v2"
    or the user is shown both versions and asked to choose.
  
  - Conflict-free Replicated Data Types (CRDTs): Data structures designed
    to be merged automatically without conflicts. Works for counters, sets,
    and some text types. Does NOT work for arbitrary application data.
```

**When multi-leader makes sense:** Collaborative editing (Google Docs), multi-region deployments where write latency matters, offline-capable apps (mobile apps that sync later). When it doesn't: almost everything else. The conflict resolution complexity is enormous, and most applications don't need writes to be fast in multiple regions.

### Leaderless Replication (Dynamo-Style)

No designated leader. Any node can accept reads and writes. Consistency is achieved through quorum voting.

```
Cluster: 3 nodes (N=3)
Write quorum (W): Must succeed on at least 2 nodes
Read quorum (R): Must read from at least 2 nodes

Rule: W + R > N guarantees overlap → at least one read node has the latest write

Example:
  Write "x=5" to Node A and Node B (W=2, success)
  Node C still has x=3 (hasn't received the write yet)
  
  Read from Node B and Node C (R=2):
    Node B: x=5 (latest)
    Node C: x=3 (stale)
    Client takes the value with the highest version number: x=5 ← CORRECT
```

**The Quorum Math:**

```
N = total nodes,  W = write quorum,  R = read quorum

Strong consistency: W + R > N
  N=3, W=2, R=2: 2+2=4 > 3 ✓ (at least 1 node overlaps)
  N=5, W=3, R=3: 3+3=6 > 5 ✓

Fast writes, eventual reads: W=1, R=N
  Write to any 1 node (fastest possible write)
  Read from ALL nodes (guaranteed to find latest)

Fast reads, slow writes: W=N, R=1
  Write to ALL nodes (slow, but guarantees all nodes have latest)
  Read from any 1 node (fastest possible read)
```

*Examples:* Cassandra, DynamoDB, Riak. These systems use leaderless replication with configurable quorum settings per operation.

---

## Concrete Example From a Real System

**Illustrative: Choosing a Replication Strategy for a RAG System's Vector Index**

A multi-region RAG platform serves users in the US and Europe. Documents are ingested in both regions.

```
Option 1: Single-Leader (PostgreSQL + pgvector)
  Leader in US-East. Followers in EU-West.
  
  US writes: Fast (local leader)
  EU writes: Slow (must cross Atlantic to leader, 100ms minimum)
  EU reads:  Fast (local follower) but potentially stale
  
  Replication lag for EU: 50-200ms (async) → acceptable for most RAG queries
  
  Problem: EU document uploads have 100ms+ write latency.
  Acceptable if: Uploads are infrequent, user can wait.

Option 2: Multi-Leader (CockroachDB or custom sync)
  Leaders in both US-East and EU-West.
  
  Both regions: Fast writes (local leader)
  Conflict risk: Two users update the same document simultaneously
  
  Problem: If the same document chunk gets different embeddings in 
           different regions (due to conflict), similarity search 
           returns different results depending on which region serves it.
  
  This is a correctness disaster for RAG: the SAME question gets 
  DIFFERENT answers depending on the user's geography.
  
  Verdict: Multi-leader is dangerous for RAG. Stick with single-leader.

Option 3: Leaderless (Cassandra) for the embedding store
  Write embeddings to any 2 of 3 nodes (W=2).
  Read embeddings from any 2 of 3 nodes (R=2).
  W+R > N guarantees consistency.
  
  Problem: Vector similarity search (ANN) doesn't fit the quorum model.
  You can't "vote" on which embedding is correct — you need ALL embeddings
  indexed to get accurate nearest-neighbor results.
  
  Verdict: Leaderless works for metadata, not for vector indexes.

Chosen architecture:
  PostgreSQL (single-leader) for documents + metadata
  pgvector on read replicas for vector search (reads only)
  Single leader in US-East, replicas in EU-West
  Document uploads from EU route to US leader (100ms write latency)
  Vector searches in EU hit local replica (2ms read latency, 50ms stale)
```

---

## The Tradeoffs

| Topology | Best For | Gives Up |
|----------|----------|----------|
| Single-Leader (async) | Most applications, simplest | Write bottleneck at leader, replication lag |
| Single-Leader (sync) | Zero data loss requirement | Write speed limited by slowest replica |
| Multi-Leader | Multi-region writes, offline-first apps | Conflict resolution complexity, correctness risk |
| Leaderless (quorum) | Write availability, no single point of failure | Higher read latency (must contact multiple nodes), complexity |

---

## How This Connects to Other Modules

- **Module 10** (Scaling Relational): Read replicas are leader-follower replication applied to scaling reads.
- **Module 12** (CAP Theorem): Single-leader sync = CP. Single-leader async = AP in practice. Multi-leader = AP. Leaderless with W+R>N = tunable.
- **Module 14** (Message Queues): Change Data Capture (CDC) uses the replication WAL to feed events into message queues for downstream consumers.
- **Module 20** (Consensus): Leader election (when the leader fails) uses consensus algorithms (Raft, Paxos).
- **Module 21** (Distributed Locks): Distributed lock services (etcd, ZooKeeper) use consensus-based replication for strong consistency.
- **Module 22** (Sharding): Replication is within a shard (copies of the same data). Sharding is across shards (different data on different nodes). Most production systems use both.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Know leader-follower replication cold — it's the most common topology and the one that comes up in every interview. Know the three replication lag bugs (read-your-writes, monotonic reads, consistent prefix) and their fixes. Know the quorum formula (W+R>N) for leaderless. Know why multi-leader is dangerous (conflicts) and when it's justified (multi-region writes, offline-capable apps). Everything else (the internals of WAL shipping, MVCC, conflict-free replicated data types) is reference material you look up when you need it.

**The AI-era connection:** This connects directly to Module 12's RAG staleness problem. Your RAG system's embedding index is a read replica of your document store. The replication pipeline (document updated → re-chunked → re-embedded → vector DB updated) is async replication with a lag of 30-120 seconds. The consistency guarantees you need depend on your use case: a legal AI where users upload and immediately ask about a document needs read-your-writes consistency. An internal knowledge base where documents change weekly can tolerate minutes of lag.

The key insight: when your user says "the AI gave me the wrong answer after I updated the document," this is a replication lag bug, not a model capability problem. The fix is the same fix that has existed in database replication for 30 years: route the updating user's reads to the source of truth (Postgres, not the vector DB) for a consistency window after their write.

**Brutally honest advice:** Multi-leader replication sounds great in architecture diagrams and terrible in production. The conflict resolution code alone — detecting conflicts, choosing a winner, notifying the losing writer, handling edge cases — is often more complex than the rest of your data layer combined. I have seen teams spend months debugging subtle conflict resolution bugs that caused silent data corruption. Unless you have a specific, measured requirement for multi-region writes with low latency, use single-leader replication and accept the cross-region write latency. For most AI applications, document ingestion is not latency-sensitive — the user is uploading a PDF and waiting for it to be processed anyway. An extra 100ms of write latency to route to the primary is invisible next to the 30-second embedding generation pipeline.

---

## Check Your Understanding

1. You have a single-leader PostgreSQL setup with async replication. The leader fails. The most up-to-date follower is 200ms behind. What data is lost? How could synchronous replication have prevented this, and what would the performance cost have been?

2. A user updates a document in your RAG system. Their embedding sync pipeline takes 60 seconds. They immediately ask a question about the updated content. Without read-your-writes consistency, what happens? Design a fix using only routing logic (no changes to the embedding pipeline).

3. Your Cassandra cluster has N=5, W=2, R=2. Is this strongly consistent? Prove it with the quorum formula. What values of W and R would make it strongly consistent?

4. Explain why multi-leader replication is especially dangerous for a RAG system's embedding store. What specific failure mode occurs when two leaders independently re-embed the same document?

5. Your leader-follower setup has 3 followers. Follower A is 50ms behind, Follower B is 200ms behind, Follower C is 5 seconds behind (slow disk). A user reads from all three followers. Which "version" of the data do they see with (a) round-robin routing, (b) monotonic reads with sticky sessions?
