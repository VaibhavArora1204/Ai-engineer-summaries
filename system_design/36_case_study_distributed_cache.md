# 36 — Case Study: Distributed Cache System (Build-Your-Own-Redis Concepts)

## Requirements Clarification

**Functional:**
- In-memory key-value store supporting: GET, SET, DELETE, TTL-based expiration.
- Support common data structures: strings, hashes, sorted sets, lists.
- Cluster mode: data distributed across multiple nodes for horizontal scaling.

**Non-Functional:**
- Sub-millisecond latency for reads and writes (<1ms p99).
- Handle 100K+ operations per second per node.
- Graceful handling of node failures (data redistribution).
- Memory-efficient: maximize useful data per GB of RAM.

---

## Back-of-Envelope Estimation

```
Dataset: 50 GB of cache data across the cluster.
Operations: 200,000 ops/second across all nodes.
Cluster size: 50 GB / ~12 GB usable per node ≈ 5 nodes (with replication: 10 nodes).
Operations per node: 200K / 5 ≈ 40K ops/second per node (well within Redis's ~100K+ capacity).
```

---

## Deep Dive: The Core Mechanisms

### 1. Memory Management Within a Node

Redis stores everything in RAM. Memory is finite and expensive. Every byte matters.

**How Redis stores a key-value pair:**

A simple `SET user:123 "Alice"` consumes more memory than you'd expect:
- Key: "user:123" (10 bytes of actual data)
- Value: "Alice" (5 bytes of actual data)
- Redis overhead per entry: ~70-100 bytes (hash table entry, pointer to key, pointer to value, expiry metadata, type metadata)

Total: ~85-115 bytes for 15 bytes of actual data. The overhead dominates for small values.

**Memory optimization techniques:**
1. **Use hashes for small objects:** Instead of 100 keys like `user:123:name`, `user:123:email`, etc., use a single hash: `HSET user:123 name "Alice" email "alice@..."`. Redis stores small hashes in a compact "ziplist" format that uses 5-10x less memory than individual keys.
2. **Short key names:** `u:123` instead of `user_profile_data:123`. At 50 million keys, saving 15 bytes per key saves 750 MB.
3. **Avoid storing large values:** A 1 MB cached JSON blob occupies the same Redis process memory as 10,000 small keys. Large values also block the single-threaded event loop during serialization.

### 2. Eviction Policies — What to Delete When Memory Is Full

When Redis hits its `maxmemory` limit, it must evict (delete) existing keys to make room for new ones.

| Policy | Mechanism | Best For |
|--------|-----------|----------|
| `noeviction` | Reject all writes when full | When losing cache data is unacceptable |
| `allkeys-lru` | Evict least recently used key across all keys | General-purpose caching (most common) |
| `volatile-lru` | Evict LRU only among keys with a TTL set | Mix of permanent config + cached data |
| `allkeys-random` | Evict a random key | When all keys are equally important |
| `volatile-ttl` | Evict the key with the shortest remaining TTL | When you want natural expiration order |
| `allkeys-lfu` | Evict least frequently used key | When some keys are consistently hotter than others |

**LRU vs LFU for AI caching:**
- **LRU (Least Recently Used):** Good for recency-driven access patterns. The most recently accessed item is kept.
- **LFU (Least Frequently Used):** Good for popularity-driven patterns. An item accessed 1,000 times in the last hour is kept over an item accessed once 5 minutes ago.

For semantic caches in RAG systems, **LFU is usually better.** Popular queries ("What is the refund policy?") are asked hundreds of times. A single rare query ("Explain clause 47.3.b") shouldn't evict the popular result just because it was accessed more recently.

### 3. Sharding the Cache (Callback to Module 22 — Consistent Hashing)

**Redis Cluster architecture:**

Redis Cluster uses 16,384 fixed **hash slots** (a simplified consistent hashing variant):
1. Each key is mapped to a slot: `slot = CRC16(key) % 16384`
2. Hash slots are distributed across nodes. Node A owns slots 0-5460, Node B owns 5461-10922, Node C owns 10923-16383.
3. When a client sends `GET user:123`, the client library computes the slot, looks up which node owns that slot, and sends the request directly to that node.

**Adding a node:** Redistribute some slots from existing nodes to the new node. Only the keys in the moved slots need to migrate. Other keys are untouched.

**Why 16,384 slots?** It's a fixed, predetermined number large enough to distribute evenly across up to ~1,000 nodes, but small enough that the slot-to-node mapping table fits in a small packet for cluster gossip messages.

### 4. Replication for Cache Availability

Each Redis master node has one or more replica nodes:
- The master handles all writes and reads.
- The replica receives a continuous stream of write operations from the master (async replication).
- If the master fails, the cluster promotes the replica to master automatically.

**Why losing cache data matters less than losing database data:**
The cache is a copy of data that exists in the primary database. If a Redis node dies and loses its data, the system falls back to the database. Requests are slower (cache miss → database query) but correct. No data is permanently lost.

However, a sudden cache loss for a hot dataset can cause a **cache stampede** (Module 07): thousands of requests simultaneously hit the database, potentially overwhelming it. This is why cache replication matters — not for data durability (the database has that) but for availability (preventing stampedes).

### 5. The "Three Redis Jobs" Anti-Pattern

A common production mistake: using a single Redis instance for three different purposes:

1. **Session cache:** User login sessions. Keys: `session:{token}`. TTL: 24 hours.
2. **Semantic cache:** Cached LLM responses. Keys: `cache:{tenant}:{query_hash}`. TTL: 1 hour. Large values (1-5 KB responses).
3. **Rate limiter:** Request counters. Keys: `ratelimit:{user}:{endpoint}:{window}`. TTL: 60 seconds. Tiny values (integer counters).

**Why this is dangerous:**

The three workloads have conflicting requirements:
- Session cache needs **persistence** (if Redis restarts, users are logged out). Enable RDB snapshots.
- Semantic cache needs **maximum memory** (large values, high eviction). Use `allkeys-lfu`.
- Rate limiter needs **low latency** (sub-millisecond). Any eviction or persistence I/O adds jitter.

When the semantic cache fills up memory and triggers eviction, it might evict rate limiter keys (breaking rate limiting) or session keys (logging users out). When RDB persistence triggers a background fork, the rate limiter's latency spikes from 0.1ms to 5ms.

**The fix:** Separate Redis instances (or at least separate Redis databases within a cluster) for each workload:
- Redis Instance 1: Sessions (persistent, `volatile-lru`)
- Redis Instance 2: Semantic cache (`allkeys-lfu`, no persistence, large `maxmemory`)
- Redis Instance 3: Rate limiter (`volatile-ttl`, no persistence, small memory footprint)

This isolation costs ~$50-100/month in infrastructure but prevents a class of production incidents that are extremely difficult to diagnose.

---

## The Tradeoffs

| Design Choice | Benefit | Cost |
|--------------|---------|------|
| In-memory storage | Sub-millisecond latency | Data lost on restart (unless persisted) |
| LRU eviction | Simple, good for recency patterns | Poor for popularity patterns (popular items can be evicted) |
| LFU eviction | Retains popular items | Slower to adapt to changing access patterns |
| Redis Cluster (hash slots) | Horizontal scaling, automatic failover | Client must know the topology, no cross-slot transactions |
| Separate instances per workload | Isolation, no cross-contamination | More infrastructure to manage and monitor |
| Async replication | Fast writes (no waiting for replica) | Writes can be lost during master failover |

---

## How This Connects to Other Modules

- **Module 07** (Caching): This module is the infrastructure that makes Module 07's strategies (cache-aside, write-through) physically possible.
- **Module 22** (Sharding): Redis Cluster's hash slots are a specific implementation of consistent hashing, applied to cache data.
- **Module 20** (Consensus): Redis Cluster uses gossip protocol for node discovery and failure detection, NOT consensus. This is why Redis can lose acknowledged writes during failover — it trades consistency for performance.
- **Module 29** (Rate Limiter): The rate limiter case study's Redis counters live in this cache system. Understanding eviction policies is critical — if rate limit keys are evicted, the rate limiter fails open.

---

## Mentor's Take — What Actually Matters Here

**What matters:** Understanding that Redis is not "just a cache." It's a data structure server that people use for at least 5 different purposes (caching, sessions, rate limiting, pub/sub, queues). Each purpose has different memory, persistence, and latency requirements. The single most valuable operational insight: **don't mix workloads in one Redis instance.** Separate them. The $100/month in extra infrastructure prevents the $10,000 production incident where your rate limiter breaks because the semantic cache evicted its keys.

The second thing that matters: eviction policy choice. `allkeys-lru` is the default most people use. For AI systems with popular queries, `allkeys-lfu` is almost always better.

**The AI-era connection:** The semantic cache is a new class of Redis workload that didn't exist 3 years ago. It has unique characteristics:
- Values are large (1-5 KB LLM responses vs 50-byte session tokens).
- Keys are semantic embeddings, not exact strings (requires external similarity matching, not Redis's native lookup).
- Cache misses are extremely expensive ($0.01-$0.50 per miss = one LLM call) vs traditional cache misses ($0.0001 = one database query).

The cost asymmetry between a cache hit ($0) and a cache miss ($0.50) means the eviction policy directly affects your LLM bill. Evicting a popular query that would have been a hit 100 more times costs $50. This makes cache sizing and eviction policy for AI systems a financial optimization problem, not just a performance one.

**Brutally honest advice:** Most engineers treat Redis as a black box. They `SET` and `GET` and never think about `maxmemory`, eviction policy, or memory overhead per key. This works at 1,000 keys. At 10 million keys, they discover that Redis is consuming 8 GB for 500 MB of actual data (overhead), the eviction policy is randomly deleting important session keys, and the nightly RDB snapshot causes a 3-second latency spike. Know your Redis instance. Run `INFO memory` and `INFO stats` weekly. Understand what's in there, how much memory it's using, and what eviction policy is active. Treat Redis like the production database it functionally is, not like a magic performance box.

---

## Check Your Understanding

1. You store 10 million keys in Redis, each with a 50-byte value. You expect to use ~500 MB of memory. Actual usage is 3.5 GB. Explain the discrepancy and suggest two ways to reduce it.

2. Your Redis instance uses `allkeys-lru` eviction. A semantic cache stores 50,000 cached LLM responses. One query ("How do I reset my password?") is asked 500 times per day. Another query ("Explain the derivation of equation 7.3") is asked once per month but was accessed 2 minutes ago. Which one gets evicted under LRU? Which should be evicted? What eviction policy would make the right choice?

3. Your Redis master fails. The replica is promoted. During the ~2 second failover window, 100 write operations were on the master but not yet replicated. What happens to those writes? How does this affect your rate limiter (which uses Redis for counters)?

4. You're running sessions, semantic cache, and rate limiting all on one Redis instance with 16 GB maxmemory. The semantic cache grows to 14 GB, triggering aggressive eviction. What happens to session and rate limiter keys? Describe the user-visible impact.

5. Your AI application generates 100K cache entries per day with an average value size of 3 KB. Redis maxmemory is 8 GB. How many days until you hit the memory limit (ignoring overhead)? What happens on that day if the eviction policy is `noeviction`?

---

### Answers

1. **Answer:** The discrepancy is Redis's per-key overhead. Each key-value pair uses ~70-100 bytes of overhead for the hash table entry, pointers, and metadata, in addition to the actual key and value bytes. 10M keys × (70 bytes overhead + ~20 bytes key + 50 bytes value) ≈ 1.4 GB. But Redis's hash table also uses a power-of-two sized array with a load factor, consuming additional memory for empty slots. Total: ~3-4 GB. Reduction: (1) Use hashes to group related small keys (e.g., `HSET user:123 field1 val1 field2 val2` instead of separate keys — ziplist encoding is 5-10x more memory efficient). (2) Shorten key names to reduce per-key byte overhead.

2. **Answer:** Under LRU, the "equation 7.3" query was accessed 2 minutes ago (most recently used). The "reset password" query might not have been asked in the last 5 minutes. LRU evicts the "reset password" query because it was used less recently. But "reset password" should be KEPT — it's asked 500 times/day and saves $0.50 per cache hit = $250/day in LLM costs. The correct eviction policy is `allkeys-lfu` (Least Frequently Used), which would keep "reset password" (high frequency) and evict "equation 7.3" (low frequency).

3. **Answer:** Those 100 writes are permanently lost. Redis replication is asynchronous — the master acknowledged the writes to clients but hadn't streamed them to the replica yet. For the rate limiter: the counter keys from the last ~2 seconds are lost. If a user was at count 98/100 on the master, the new master's counter might show 95 (or 0 if the key was very recent). The rate limiter briefly under-counts, allowing a few extra requests through. For most rate limiting scenarios, this 2-second window of leniency is acceptable. For payment-critical rate limiting, use a Postgres-based counter alongside Redis for the source of truth.

4. **Answer:** When the semantic cache triggers eviction at 14 GB, Redis evicts keys using the configured policy (e.g., `allkeys-lru`). It doesn't distinguish between semantic cache keys, session keys, and rate limiter keys — they're all in the same keyspace. Session keys get evicted → users are randomly logged out ("Why do I keep getting signed out?"). Rate limiter keys get evicted → rate limiting fails open (users can exceed their limits). The fix: separate Redis instances per workload, so eviction in the semantic cache instance doesn't affect sessions or rate limiting.

5. **Answer:** 100K entries/day × 3 KB = 300 MB/day (data only, ignoring overhead). With overhead (~100 bytes per key): 100K × (3,100 bytes) = 310 MB/day. 8 GB / 310 MB ≈ 26 days. On day 26, Redis hits `maxmemory` with `noeviction` policy. All subsequent SET commands return an error: `(error) OOM command not allowed when used memory > 'maxmemory'`. The semantic cache stops accepting new entries. Every query becomes a cache miss, hitting the LLM API. LLM costs spike from whatever the cached rate was to 100% of queries billed. The fix: use `allkeys-lfu` eviction so the least valuable cached entries are automatically evicted to make room, or increase `maxmemory`, or reduce TTL to control growth.
