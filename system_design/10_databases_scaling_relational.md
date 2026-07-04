# 10 — Databases Part 2 — Scaling Relational Databases

## The Problem

Your PostgreSQL database is handling 1,000 queries/second beautifully on a single server with 64GB RAM and 16 cores. Your product launches. Traffic grows 10x. Now 10,000 queries/second are hitting one database server, and it's buckling: CPU at 95%, query latency climbing from 5ms to 500ms, connection pool exhausted. Users see timeout errors.

You have two fundamental moves (Module 01): make the one server bigger (vertical scaling), or spread the work across multiple servers (horizontal scaling). Both have hard limits and brutal tradeoffs.

---

## The Naive Approach and Why It Fails

**Naive approach: "Just upgrade the server."**

You move from a 16-core, 64GB machine to a 96-core, 768GB monster. This is vertical scaling — and it actually works, much further than most engineers expect. Modern cloud instances (AWS `db.r6g.16xlarge`) can handle enormous workloads on a single node.

This fails when:
1. **Hardware has a ceiling.** The biggest server AWS sells has 448 vCPUs and 24 TB of RAM. If your data or traffic exceeds what one machine can handle, there is no bigger machine to buy.
2. **Single point of failure.** One server = one disk, one network card, one OS. A kernel panic, a failed SSD, or a botched OS upgrade takes your entire database offline. No redundancy.
3. **Cost grows non-linearly.** Doubling the server size more than doubles the cost. A 96-core instance costs 3-4x what a 48-core instance costs, not 2x.

The fix involves two strategies: read replicas (for read-heavy workloads) and sharding (for write-heavy or data-volume workloads). But — and this is critical — you should exhaust vertical scaling, indexing (Module 09), and caching (Module 07) before reaching for either of these.

---

## The Real Mechanism

### Read Replicas — Scaling Reads

Most applications are read-heavy: 80-95% of database traffic is `SELECT` queries. If reads are your bottleneck, you don't need to distribute writes — you need to distribute reads.

```
Architecture:
  Primary (Leader):  Handles ALL writes (INSERT, UPDATE, DELETE)
                     Also handles reads that require absolute freshness
  
  Replica 1 (Follower): Handles reads. Receives write stream from Primary.
  Replica 2 (Follower): Handles reads. Receives write stream from Primary.
  Replica 3 (Follower): Handles reads. Receives write stream from Primary.
  
  Application routes:
    write_db = connect("primary.db.internal")
    read_db  = connect("replica-pool.db.internal")  # load balanced across replicas
```

**The Replication Mechanism:**

The Primary writes every change to its Write-Ahead Log (WAL). The WAL is streamed to replicas. Replicas apply the WAL entries to their own copies of the data.

```
Synchronous Replication:
  Primary writes → WAL → streams to Replica → Replica confirms → Primary ACKs client
  
  Guarantee: Replica always has the latest data. Zero lag.
  Cost: Every write is as slow as the slowest replica. If a replica is on 
        a congested network, all writes wait.
  Use when: Data loss is unacceptable (financial systems).

Asynchronous Replication (the default, the common choice):
  Primary writes → WAL → ACKs client immediately → streams to Replica eventually
  
  Guarantee: Replica is "eventually" consistent. Typically 10-100ms behind.
  Cost: Replication lag. A user writes data, immediately reads it from a replica,
        and sees the old data. "I just updated my profile, why does it show the old name?"
  Use when: Slight staleness is acceptable (most applications).
```

**Replication Lag — The Bug That Looks Like a UI Bug:**

```
Timeline (async replication):
  T=0ms:   User updates profile name to "Alice Smith" → hits Primary
  T=1ms:   Primary writes to WAL, ACKs user: "Updated!"
  T=2ms:   User's browser reloads profile page → hits Replica
  T=2ms:   Replica hasn't received the WAL entry yet (still "Alice Jones")
  T=2ms:   User sees "Alice Jones" → "WTF? I just changed it!"
  T=50ms:  Replica receives WAL entry, applies it. Now shows "Alice Smith."
  
Fix: Read-after-write consistency. After a write, route the immediate
     subsequent read to the Primary (not a replica). This guarantees
     the user sees their own writes. Other users can read from replicas
     (they don't need to see Alice's update instantly).
```

### Sharding — Scaling Writes and Data Volume

When your problem is write throughput (the Primary can't handle more INSERTs) or data volume (the dataset doesn't fit on a single machine), you need sharding: splitting the data across multiple independent databases, each holding a subset of the data.

```
Before sharding: 1 database, 100 million users, ALL queries hit one server
After sharding:  4 databases (shards), ~25 million users each

Shard 0: Users A-F    (25M users)
Shard 1: Users G-L    (25M users)  
Shard 2: Users M-R    (25M users)
Shard 3: Users S-Z    (25M users)
```

**Sharding Strategies:**

**Range-Based Sharding:**
Assign rows to shards based on a value range of the shard key.

```
Shard key: user_id
Shard 0: user_id 1-25,000,000
Shard 1: user_id 25,000,001-50,000,000
Shard 2: user_id 50,000,001-75,000,000
Shard 3: user_id 75,000,001-100,000,000

Pro: Range scans are efficient (all of Shard 0's data is contiguous)
Con: Hot spots. If new users get sequential IDs, Shard 3 handles ALL new
     writes while Shards 0-2 sit idle. This is the "hot partition" problem.
```

**Hash-Based Sharding:**
Hash the shard key and modulo by number of shards.

```
shard = hash(user_id) % 4

Pro: Uniform distribution. No hot spots (assuming a good hash function).
Con: Range scans are impossible. "Get all users created this week" must
     query ALL shards. Adding a shard (going from 4 → 5) requires 
     rehashing and moving ~80% of the data.
```

**Directory-Based Sharding:**
A lookup table maps each key to its shard.

```
Directory service:
  user_id 1     → Shard 2
  user_id 2     → Shard 0
  user_id 3     → Shard 3
  ...

Pro: Maximum flexibility. Can move individual users between shards.
Con: The directory is a single point of failure and a bottleneck.
     Every query must first look up the directory.
```

### The Pain of Sharding — Why You Should Avoid It As Long As Possible

Sharding introduces brutal operational and application-level complexity:

1. **Cross-shard queries are expensive or impossible.** `SELECT * FROM users JOIN orders ON users.id = orders.user_id` — if users and orders are sharded on different keys, this JOIN must query every shard and combine results in the application layer. This is a distributed join and it's orders of magnitude slower than a local join.

2. **Cross-shard transactions don't exist.** You can't do `BEGIN; UPDATE shard_0; UPDATE shard_1; COMMIT;` atomically. You need distributed transactions (Module 23) or saga patterns.

3. **Rebalancing is painful.** When one shard gets too big, you need to split it. This involves copying data, updating routing, and handling requests during the migration — all without downtime.

4. **Operational burden multiplies.** Every shard needs monitoring, backups, failover, and version management. 4 shards = 4x the operational work.

**The Decision Framework:**
```
Before sharding, exhaust these (in order):
  1. Add missing indexes (Module 09)          → often fixes the problem
  2. Add caching (Module 07)                  → reduces read load 80-95%
  3. Add read replicas (above)                → handles read scaling
  4. Vertically scale the Primary             → handles write scaling up to HW limit
  5. Optimize slow queries (EXPLAIN ANALYZE)  → fixes the actual bottleneck
  
Only shard when:
  - Your data volume exceeds what fits on a single machine
  - Your write throughput exceeds what a single machine can handle
  - You've exhausted all 5 steps above
```

---

## Concrete Example From a Real System

**Illustrative: Scaling a RAG System's Vector Store**

A startup has 10 million document chunks with embeddings in a PostgreSQL + pgvector table. At first, a single `db.r6g.4xlarge` (128GB RAM, 16 vCPUs) handles everything beautifully.

Growth to 100 million chunks creates two problems:
1. The IVFFlat index for vector similarity search no longer fits in RAM. Queries that were 50ms are now 500ms because the index pages are being read from disk.
2. Concurrent vector searches and document ingestion (embedding + insert) compete for I/O.

**Their scaling path:**
```
Step 1 (Read replicas): 
  Route vector search queries to 3 read replicas.
  Ingestion (writes) goes to Primary only.
  Result: Search latency drops back to 50ms. Write load unchanged.

Step 2 (Vertical scaling):
  Upgrade Primary to db.r6g.16xlarge (512GB RAM).
  Entire IVFFlat index fits in RAM again.
  Result: Handles 100M chunks on a single Primary.

Step 3 (If growth continues to 1 billion chunks):
  Shard by organization_id (tenant-based sharding).
  Each shard holds one tenant's chunks.
  Large tenants get dedicated shards.
  Small tenants are co-located on shared shards.
  Result: Horizontal scaling with natural tenant isolation.
  Cost: Cross-tenant analytics require querying all shards.
```

Notice that they didn't shard until step 3 — and most companies never reach step 3.

---

## The Tradeoffs

| Strategy | Benefit | Cost |
|----------|---------|------|
| Vertical scaling | Simple, no code changes, no distributed complexity | Hardware ceiling, single point of failure, non-linear cost |
| Read replicas (async) | Scales reads massively, simple to set up | Replication lag, stale reads, doesn't help with write bottlenecks |
| Read replicas (sync) | Zero lag, strong consistency | Every write blocked by slowest replica, reduced write throughput |
| Hash sharding | Even distribution, no hot spots | Impossible range scans, painful rebalancing on shard count change |
| Range sharding | Efficient range scans | Hot spots on sequential keys |
| Directory sharding | Maximum flexibility | Directory is SPOF and bottleneck |

---

## How This Connects to Other Modules

- **Module 07** (Caching): Cache before you replicate. A 90% cache hit rate means your database sees 10% of read traffic.
- **Module 09** (Relational Fundamentals): Indexing and connection pooling must be optimized before scaling horizontally.
- **Module 12** (CAP Theorem): Async replication makes your system AP (Available, Partition-tolerant) at the cost of Consistency.
- **Module 13** (Replication and Consistency): Deep dive into the replication mechanics introduced here.
- **Module 22** (Sharding Deep Dive): Consistent hashing, hot key mitigation, and rebalancing strategies in depth.
- **Module 23** (Distributed Transactions): The solution for cross-shard write consistency.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** In interviews, you will be asked "how do you scale a database?" The correct answer structure is: (1) identify whether the bottleneck is reads, writes, or data volume, (2) exhaust simple solutions first (indexes → cache → read replicas → vertical scaling), (3) only then discuss sharding. Jumping straight to sharding is a red flag for interviewers — it signals you don't understand the operational cost or that you haven't considered simpler alternatives. Know async vs sync replication and the replication lag bug (read-after-write consistency). Know the three sharding strategies and their tradeoffs. That's the full set for interviews and for most production systems.

**The AI-era connection:** The brutal honest take on premature sharding: most AI engineers reach for "let's shard the vector store" before they've actually proven the single-node Postgres + pgvector setup is the bottleneck. pgvector on a 512GB RAM instance with properly tuned IVFFlat or HNSW indexes can handle 100+ million vectors. That's enough for most startups for their first 2-3 years. Sharding a vector database introduces the cross-shard similarity search problem — you must query every shard and merge the results to get a global top-K, which is algorithmically harder than sharding a key-value lookup. Don't shard your vector store until you've measured that single-node pgvector genuinely can't handle your scale. The complexity cost of premature sharding is enormous, and unlike adding an index (reversible in minutes), sharding is extremely difficult to undo.

**Brutally honest advice:** The most common scaling mistake I see from AI engineers is not a database problem at all — it's holding database connections open during LLM calls (Module 09's connection pool exhaustion). Before you add read replicas or shard, check whether your application is holding connections for 5 seconds during RAG generation instead of 5 milliseconds for a SELECT. If your connection pool is exhausted not because of query volume but because of connection hold time, adding more database infrastructure won't fix it. Release the connection after the query, before calling the LLM. This one fix often eliminates the perceived need to scale the database entirely.

---

## Check Your Understanding

1. Your application has 90% reads and 10% writes. You add 3 read replicas. What is the theoretical maximum read throughput improvement? What happens to write throughput?

2. A user updates their display name. 50ms later, they refresh the page and see their old name. Is this a bug? What causes it, and what is the standard fix (without switching to synchronous replication)?

3. You shard your users table by `hash(user_id) % 4`. Now you need to run `SELECT COUNT(*) FROM users WHERE country = 'US'`. How many shards must you query? Why is this problematic?

4. Your Postgres instance has 100 million document chunks with embeddings. CPU is at 40%, RAM usage is at 60%, but vector search latency is 500ms (up from 50ms last month). What is the most likely cause, and what is the fix BEFORE sharding?

5. Explain why tenant-based sharding (shard by `organization_id`) is a natural fit for a multi-tenant SaaS RAG application. What cross-shard operation becomes impossible, and does that matter for this use case?
