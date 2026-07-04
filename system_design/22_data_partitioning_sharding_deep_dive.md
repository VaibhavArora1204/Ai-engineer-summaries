# 22 — Data Partitioning and Sharding — Deep Dive

## The Problem

Your database has 2 billion rows. A single Postgres instance handles maybe 500 GB of hot data in RAM and tops out at roughly 10,000-50,000 writes per second, depending on schema and hardware. You're past that. Vertical scaling (bigger machine) has hit its ceiling. You need to split the data across multiple machines.

This is **sharding** (also called horizontal partitioning): splitting a single logical dataset across multiple physical database instances, where each instance holds a subset of the data.

Module 10 introduced the concept. This module goes deep on the mechanism — specifically **consistent hashing**, which is how virtually every modern distributed system decides "which shard holds this data."

---

## The Naive Approach and Why It Fails

**Naive approach: Modulo hashing.**
```
shard_number = hash(user_id) % number_of_shards
```

With 4 shards: `hash("user-123") % 4 = 2`, so user-123 lives on shard 2.

This works perfectly... until you add a 5th shard. Now `hash("user-123") % 5 = 3`. User-123's data is on shard 2, but the routing formula says shard 3. Nearly every key gets remapped. With 4 shards going to 5, approximately 80% of all keys need to move. With 100 shards going to 101, approximately 99% need to move.

This means adding one server requires migrating almost your entire dataset across the network, during which your system is either down or returning inconsistent results. This is called a **resharding storm**, and at scale it takes hours or days.

---

## The Real Mechanism

### Consistent Hashing

Consistent hashing solves the resharding problem. When you add or remove a shard, only ~1/N of the keys need to move (where N is the number of shards), not nearly all of them.

**The Ring:**
1. Imagine a circular number line from 0 to 2^32 - 1 (a hash ring).
2. Each shard is placed on the ring at a position determined by hashing its name: `position = hash("shard-A")`.
3. When you need to store or look up a key, you hash the key: `position = hash("user-123")`.
4. Walk clockwise around the ring from that position. The first shard you encounter owns that key.

**Adding a new shard:**
You place the new shard on the ring. It "takes over" a portion of the ring from its clockwise neighbor. Only the keys in that specific arc need to move. All other keys stay exactly where they are.

**Removing a shard:**
The dead shard's arc is absorbed by its clockwise neighbor. Only the keys on the dead shard need to relocate to one other shard.

**The Virtual Node Optimization:**

A naive ring with 4 shards places 4 points on the ring. The arcs between them might be wildly unequal — one shard might own 40% of the ring and another only 10%. This creates **load imbalance**.

The fix: give each physical shard multiple **virtual nodes**. Instead of placing "Shard A" once on the ring, you place "Shard-A-v1", "Shard-A-v2", ..., "Shard-A-v150" — 150 points for each physical shard. These points are distributed evenly around the ring by the hash function. The result:

- Each physical shard owns hundreds of small, interleaved arcs instead of one large arc.
- Load is distributed almost perfectly evenly.
- When a new physical shard is added, it takes ~1/N of the keys from each existing shard (its virtual nodes land in arcs previously belonging to other shards' virtual nodes), rather than stealing a large chunk from just one neighbor.

**Real-world usage:**
- Amazon DynamoDB uses consistent hashing for partition key routing.
- Apache Cassandra uses consistent hashing with virtual nodes (called "vnodes").
- Redis Cluster uses hash slots (a simplified variant — 16,384 fixed slots distributed across nodes).
- Memcached client libraries use consistent hashing to decide which cache server holds each key.

### Choosing a Shard Key

The shard key is the column whose value determines which shard a row lives on. This is the single most important decision in sharding. Get it wrong, and you can't fix it without a full data migration.

**Criteria for a good shard key:**

1. **High cardinality:** Many distinct values. `country` (200 countries) is low cardinality — you'd have 200 shards at most, with massive skew. `user_id` (millions of users) is high cardinality.
2. **Even distribution:** Values should be roughly uniformly distributed across shards. Sequential IDs with modulo hashing are fine. Timestamps are terrible (all writes hit the "current" shard).
3. **Query isolation:** Queries should be answerable from a single shard. If you shard by `user_id` and your most common query is `WHERE user_id = X`, every query hits exactly one shard. If your most common query is `WHERE city = 'Mumbai'`, you need a scatter-gather across all shards, which is slow.

**Common shard key patterns:**

| Domain | Good Shard Key | Bad Shard Key |
|--------|---------------|---------------|
| Multi-tenant SaaS | `tenant_id` | `created_at` |
| Social media | `user_id` | `post_id` (JOINs with user table break) |
| E-commerce | `order_id` or `customer_id` | `product_category` (skewed) |
| Chat application | `conversation_id` | `user_id` (a user is in many conversations) |
| IoT telemetry | `device_id` | `timestamp` (hot partition) |

### The Hot Partition / Hot Key Problem

Even with consistent hashing and a good shard key, hot keys create problems.

**Example:** A celebrity tweets. Their tweet ID hashes to Shard 3. 50 million people try to read it simultaneously. Shard 3 is overwhelmed; Shards 1, 2, and 4 are idle.

**Mitigations:**

1. **Caching:** Cache the hot key in a distributed cache (Module 07). Reads hit the cache, not the shard. This is the most common and effective mitigation.
2. **Key salting / read replicas for hot keys:** Append a random suffix (e.g., `tweet:123:shard_1`, `tweet:123:shard_2`, ..., `tweet:123:shard_5`) so the hot key is spread across 5 shards. Reads pick a random suffix. This increases write complexity but distributes read load.
3. **Application-level routing:** The application detects the hot key (via monitoring) and routes reads to a dedicated cache tier or read replica specifically for that key.

### Rebalancing Pain

Even with consistent hashing, adding or removing shards requires data migration for ~1/N of the keys. At terabyte scale, this means:

1. **Data copying across the network** (potentially hundreds of GBs).
2. **Handling writes during migration** (dual-write to old and new shard, or freeze writes temporarily).
3. **Updating routing metadata** atomically so all application servers agree on the new mapping.
4. **Verification** that no data was lost or duplicated.

This is why sharding is called a "violent operational event." You want to shard late, shard once, and get the shard key right the first time.

---

## Concrete Example From a Real System

**Discord's Message Storage:**

Discord stores billions of messages. They shard by `channel_id`:
- All messages in a single channel live on the same shard.
- This means fetching a channel's message history is a single-shard query (fast).
- But a single massively popular channel (e.g., a large server's general chat) creates a hot partition.

Discord initially used Cassandra with consistent hashing. They migrated to ScyllaDB (a Cassandra-compatible database written in C++) for better per-node performance, which let them handle hot partitions without adding more nodes.

The shard key choice (`channel_id`) was correct because the dominant access pattern is "load messages for this channel." If they'd sharded by `user_id`, loading a channel's history would require scatter-gathering across every shard that contained a message from any user who'd ever posted in that channel.

---

## The Tradeoffs

| Approach | Benefit | Cost |
|----------|---------|------|
| Consistent hashing (virtual nodes) | Minimal data movement during rebalancing | Complexity of routing layer, virtual node mapping |
| Range-based sharding | Simple, efficient range queries on shard key | Hot partitions (recent data = hot range), uneven load |
| Directory-based sharding | Maximum flexibility (explicit lookup table) | Lookup table is a SPOF and bottleneck |
| No sharding (single DB) | Simple operations, ACID across all data | Vertical scaling ceiling |

**When to shard:** When a single database instance can no longer handle the write throughput or storage volume, AND you've already exhausted: read replicas (for reads), caching (for reads), vertical scaling (bigger machine), and query optimization (indexes, schema tuning).

**When NOT to shard:** When any of the above can still solve your problem. Sharding introduces: no cross-shard JOINs, no cross-shard transactions, increased operational complexity, and application-level routing logic. Delay it as long as possible.

---

## How This Connects to Other Modules

- **Module 10** (Scaling Relational DBs): Introduced sharding as a concept. This module delivered the mechanism (consistent hashing) and the operational reality.
- **Module 07** (Caching): Caching is the primary mitigation for hot partition problems. Cache the hot key in Redis/Memcached so reads never hit the overloaded shard.
- **Module 11** (NoSQL): Cassandra, DynamoDB, and other NoSQL databases have sharding built into their core design. Their "partition key" IS the shard key.
- **Module 20** (Consensus): The routing metadata ("which shard owns which hash range") must be stored consistently — often in etcd or ZooKeeper. An inconsistent routing table means data goes to the wrong shard.
- **Module 36** (Distributed Cache): Redis Cluster uses 16,384 hash slots (a variant of consistent hashing) to distribute keys across cache nodes.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Consistent hashing is worth understanding deeply — the ring, virtual nodes, and the ~1/N data migration property. You will encounter it in Cassandra, DynamoDB, Redis Cluster, Memcached, load balancers, and CDN routing. The algorithm itself is simple; the operational consequences of shard key choice are what will make or break your system.

The single most important skill: choosing the right shard key. This requires knowing your access patterns cold. "What query does my application run most frequently?" The answer to that question determines your shard key. If your most common query is `WHERE tenant_id = X`, shard by `tenant_id`. If it's `WHERE user_id = X AND created_at > ...`, shard by `user_id`. If you don't know your access patterns, you're not ready to shard.

**The AI-era connection:** Vector databases face a unique version of the hot-key problem. In a classic database, a "hot key" is a specific row ID getting hammered. In a vector database, the "key" is semantic — a popular topic, not a specific ID. If your RAG system serves a customer support bot, and 40% of all queries are about "password reset," the vectors in the semantic neighborhood of "password reset" become a hot region in the HNSW index. This isn't a single hot key — it's a hot *neighborhood* in embedding space.

Mitigations look different:
- You can't just cache one key. You need to cache the semantic query result (Module 07 — semantic caching).
- You can't just replicate one row. You might need read replicas of the entire vector index.
- Sharding by document ID distributes storage evenly but does nothing for query hotspots, because the hot queries don't map to specific document IDs — they map to regions of the embedding space.

This is why, for most startups, a single pgvector instance with semantic caching in front of it is the right architecture. Sharding a vector database is a fundamentally harder problem than sharding a relational database, and you should avoid it until you've genuinely proven the single instance is the bottleneck.

**Brutally honest advice:** I have watched three different AI startups announce "we're sharding the vector database" at under 10 million vectors. pgvector on a single 32GB RAM Postgres instance with an HNSW index handles 10 million 1536-dimensional vectors with sub-100ms query latency. 10 million vectors is roughly 60GB of raw embedding data — fits on one machine. These teams spent 2-3 engineering-months setting up sharded Qdrant or Milvus clusters, debugging routing inconsistencies, and handling rebalancing. They solved a problem they didn't have. Measure first. Shard last.

---

## Check Your Understanding

1. You have 4 shards using modulo hashing (`hash(key) % 4`). You add a 5th shard. Approximately what percentage of keys need to be remigrated? Now answer the same question for consistent hashing with virtual nodes.

2. You are building a multi-tenant SaaS RAG platform. Each tenant has between 1,000 and 500,000 documents. You need to shard the vector database. Should you shard by `tenant_id` or by `document_id`? Defend your choice by analyzing the most common query pattern.

3. A celebrity's profile page on a social network is getting 100,000 reads per second. The profile data is on Shard 7 (determined by consistent hashing on `user_id`). The other 15 shards are idle. What is the first mitigation you apply, and why is it NOT "re-shard the data"?

4. Explain why adding a 4th node to a 3-node consistent hashing ring with 100 virtual nodes per physical node causes approximately 25% of keys to move, not 75%.

5. Your chat application is sharded by `user_id`. A user opens a group chat with 200 participants. To render the message history, the application needs messages from all 200 users. Describe the performance problem this creates and suggest a better shard key for this access pattern.

---

### Answers

1. **Answer:** With modulo hashing, ~80% of keys move (nearly every key's `hash(key) % 5` differs from `hash(key) % 4`). With consistent hashing and virtual nodes, approximately 20% (1/5) of keys move — only the keys that fall in the arcs now assigned to the new shard. The rest stay on their original shards untouched.

2. **Answer:** Shard by `tenant_id`. The most common query in a RAG system is "retrieve relevant documents for Tenant X's user query" — all vector search happens within a single tenant's document set. If you shard by `tenant_id`, the entire search is a single-shard operation. If you shard by `document_id`, a query for Tenant X's documents would scatter-gather across all shards containing any of that tenant's documents, adding massive latency and network overhead.

3. **Answer:** The first mitigation is caching. Put the celebrity's profile in Redis/Memcached with a short TTL (e.g., 60 seconds). 100,000 reads/second hit the cache, not the shard. Re-sharding doesn't help because the hot key would still hash to exactly one shard — you'd just move the problem to a different shard number. Caching absorbs the read load entirely.

4. **Answer:** The new node gets 100 virtual nodes placed around the ring. These 100 virtual nodes land in arcs that were previously owned by the existing 3 nodes' 300 virtual nodes (100 each). Each new virtual node "steals" a small arc from the previous owner. In total, the new node takes ownership of approximately 1/4 of the total ring space (since there are now 4 nodes sharing equally). Only the keys in those stolen arcs (~25%) need to move. The remaining 75% of keys are in arcs whose ownership didn't change.

5. **Answer:** This creates a scatter-gather nightmare. To load the group chat, the app must query all shards that contain any of the 200 users' messages, wait for the slowest shard to respond, and merge/sort the results in the application layer. With 16 shards and 200 users, you'd likely hit all 16 shards for a single page load. The correct shard key for a chat application is `conversation_id` (or `channel_id`). All messages in a single conversation live on one shard, so loading the chat history is a single-shard, single-query operation regardless of how many participants are in the conversation.
