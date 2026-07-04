# 07 — Caching — Deep Dive

## The Problem

Your system is doing the exact same expensive work over and over. An identical database query run 1,000 times a second. A complex calculation run on the same inputs. A RAG pipeline retrieving the exact same documents for a common user question, then asking the LLM to generate the exact same answer — burning $0.03 and 4 seconds every single time.

This burns compute, burns money (especially if you're paying an LLM API per token), and forces your users to wait for work that has already been done. The fundamental scaling move "do less work" (Module 01) starts here. Caching is the single highest-leverage optimization in most systems because it converts an O(n) cost (compute per request) into an O(1) cost (memory lookup) for repeated work.

---

## The Naive Approach and Why It Fails

The naive approach is an in-memory dictionary.

```python
cache = {}

def get_user_profile(user_id):
    if user_id in cache:
        return cache[user_id]
    profile = db.query(user_id)
    cache[user_id] = profile
    return profile
```

This works on your laptop. It fails the moment you hit horizontal scaling (Module 03):

- **Inconsistency:** If you have 4 application servers, you have 4 separate caches. Server A caches profile X. The user updates profile X on Server B. Server A still has the old profile. The user bounces between servers via the load balancer and sees their profile flickering between old and new versions — a maddening, intermittent bug that's nearly impossible to reproduce locally.
- **Memory leaks:** The dictionary grows forever. There is no eviction. Your server process gradually consumes all available RAM and gets OOM-killed by the OS at 3am. The restart clears the cache, causing a stampede (more on this below).
- **Cold starts:** When a server restarts, its cache is empty. It hammers the database with 100% of requests while warming up. If all 4 servers restart simultaneously (a deploy), your database gets hit with 4x its normal load at once.
- **Duplication:** With 4 servers caching independently, the same data is stored 4 times. You're using 4x the total memory for zero additional benefit.

The fix is an external, distributed cache (Redis, Memcached) with proper eviction and invalidation policies. Every application server reads from the same shared cache, solving consistency and duplication.

---

## The Real Mechanism

### Cache Levels — The Memory Hierarchy of Distributed Systems

Just as a CPU has L1/L2/L3 caches and then main memory, a distributed system has multiple cache levels. Each level trades speed for capacity and scope:

```
Level 0: CPU cache         → nanoseconds,  kilobytes    (you don't control this)
Level 1: Application local → microseconds, megabytes    (in-process, per-server)
Level 2: Distributed cache → ~1ms,         gigabytes    (Redis, shared across servers)
Level 3: CDN edge cache    → ~10ms,        terabytes    (Cloudflare, global)
Level 4: Database           → ~5-50ms,     terabytes    (the "source of truth")
Level 5: LLM API            → ~2-30sec,    infinite     (the most expensive "compute")
```

1. **Client/Browser Cache:** (Fastest, zero network) Browsers cache static assets locally. Controlled by HTTP headers (`Cache-Control: max-age=3600`). When this hits, the server does literally zero work — the browser never even makes a request. This is the most efficient cache layer by far, and the one most backend engineers forget about.

2. **CDN Edge Cache:** (Fast, low network) Geographically distributed caching for static assets and API responses (Module 08). A user in Sydney hits the Sydney CDN node instead of your Virginia origin server. Saves 200ms of physics.

3. **Application Local Cache:** (Fast, in-memory) `functools.lru_cache` in Python, Guava Cache in Java, or a simple dictionary with TTL. Fast because it's in-process (no network hop), but suffers from the inconsistency problems above. Useful for small, rarely changing reference data (country codes, feature flags, model configs) that can tolerate being slightly stale across servers.

4. **Distributed Cache:** (Fast-ish, one network hop) Redis or Memcached. The standard "cache layer." All application servers read from and write to the same cache instance, solving the multi-server consistency problem. Redis typically serves reads in <1ms. This is the cache layer you'll spend the most time designing and debugging.

5. **Database Query Cache:** Many databases (MySQL, PostgreSQL) have internal query caches. These are transparent and require no application code changes, but they're limited in scope and can become counterproductive under write-heavy workloads (the cache gets invalidated on every write, adding overhead without benefit).

### Caching Patterns — How Data Gets Into (and Out Of) the Cache

**Cache-Aside (Lazy Loading):**
The most common pattern. Your application code explicitly manages the cache.

```python
def get_user_profile(user_id):
    # 1. Check cache
    cached = redis.get(f"user:{user_id}")
    if cached:
        return json.loads(cached)  # HIT
    
    # 2. Cache miss → query database
    profile = db.query(user_id)
    
    # 3. Populate cache for next time
    redis.setex(f"user:{user_id}", 3600, json.dumps(profile))  # TTL: 1 hour
    
    return profile
```

*Pros:* Only data that is actually requested gets cached (no wasted memory). Cache failures are graceful — the app falls back to the database (slower, but works).
*Cons:* Three network hops on a cache miss (check cache → query DB → write cache). Data goes stale if not invalidated. The first request for any item is always slow (cold miss).

**Write-Through:**
Application writes to cache; cache synchronously writes to database.

```
Application → Cache (write) → Database (write) → ACK
```

*Pros:* Cache is always consistent with the database. Reads are always fast and fresh.
*Cons:* Writes are slow — every write must hit both cache and database synchronously before acknowledging. This doubles write latency. You also cache data that might never be read (wasted memory).

**Write-Back (Write-Behind):**
Application writes to cache. Cache acknowledges immediately. Cache asynchronously flushes writes to the database in batches.

```
Application → Cache (write + ACK immediately)
                    └→ Database (async, batched, later)
```

*Pros:* Insanely fast writes. Great for high-throughput counters, metrics, and analytics.
*Cons:* If the cache crashes before the async flush, data is permanently lost. Used for metrics, counters, and analytics — rarely for critical user data like profiles or financial records. This is a durability tradeoff, not a performance optimization.

**Write-Around:**
Application writes directly to database, bypassing cache. Cache is populated only on the next read (via cache-aside).
*Pros:* Doesn't fill the cache with data that is written but never read.
*Cons:* The first read after a write is always a cache miss.

**Which pattern to use?** For most systems: cache-aside for reads, write-around for writes. This gives you the benefit of caching hot reads without polluting the cache with write-once data. Write-through only when read-after-write consistency is critical (e.g., user updates profile and must see the update immediately).

### Eviction Policies — When the Cache Is Full, What Dies?

Your cache has finite memory. Redis is typically configured with `maxmemory` and an eviction policy:

- **LRU (Least Recently Used):** Delete the item whose last access was furthest in the past. The industry standard default. Works well for most access patterns because recently accessed items are likely to be accessed again (temporal locality).

- **LFU (Least Frequently Used):** Delete the item accessed the fewest total times. Better than LRU for heavy-tail distributions where a few items are extremely popular. LFU keeps the "always popular" items even if they weren't accessed in the last few seconds.

- **Random:** Delete a random item. Surprisingly effective in practice — close to LRU's performance with zero bookkeeping overhead. Used in some high-throughput systems where the eviction policy overhead matters.

- **TTL (Time To Live):** Not technically an eviction policy for a full cache, but a staleness policy. Every item gets a countdown. When it expires, it's deleted regardless of available memory. TTLs are your primary tool for controlling how stale your cache is allowed to be.

### The Three Failure Modes You Will Hit in Production

This is the difference between knowing caching and operating a cache at scale.

**1. Cache Penetration (Querying Things That Don't Exist)**

```
Attack: Request user_id=-1 (doesn't exist in cache OR database)
  → Cache miss (nothing cached for -1)
  → DB query returns empty (user -1 doesn't exist)
  → Nothing to cache
  → Attacker repeats 10,000 times/sec
  → Every request bypasses cache and hits DB directly
  → Database falls over under load it was never designed for
```

The fix: **Cache the negative result.** Even if the DB says "not found," write a short-TTL entry (`{user:-1: NOT_FOUND, TTL: 60s}`) to the cache. Future requests hit the cache and get the "not found" flag without touching the database. Alternatively, use a Bloom filter as a pre-check: if the Bloom filter says "definitely not in the database," don't even query.

**2. Cache Breakdown (Hot Key Expiry)**

```
Scenario: A viral product page (or a common RAG query) is cached with TTL=1h.
  → At exactly 14:00:00, the TTL expires
  → At 14:00:00.001, 5,000 requests arrive for that key
  → Cache says "MISS" to all 5,000 simultaneously
  → All 5,000 requests hit the database to regenerate the same data
  → Database is overwhelmed (or you burn $150 in LLM calls for the same answer)
```

The fix: **Mutex/distributed lock.** When the cache misses on a hot key, the first request acquires a short-lived distributed lock (Module 21) for that key. It queries the database and repopulates the cache. The other 4,999 requests see the lock, wait a few milliseconds, then retry the cache — which now has the fresh data. Only one database query is executed.

Alternative fix: **Background refresh.** Instead of expiring the key and serving a miss, have a background job re-populate the cache *before* the TTL expires. The key never goes empty. This requires knowing which keys are "hot" enough to warrant proactive refresh.

**3. Cache Stampede (Thundering Herd)**

```
Scenario: Your Redis server crashes and restarts with an empty cache.
  → Your application, accustomed to a 95% cache hit rate, now has a 0% hit rate
  → 100% of traffic hits the database
  → The database, sized for 5% of total traffic, is instantly overwhelmed
  → Database goes down → application goes down → complete outage
```

The fix: **Pre-warming** (scripts that repopulate the most popular keys from the database before accepting traffic). **Jittered TTLs** (instead of all keys expiring at exactly 1 hour, each key gets a TTL between 55-65 minutes — so expirations are spread out, not synchronized). **Rate-limited cache filling** (limit how many cache misses can simultaneously query the database).

---

## Concrete Example From a Real System

**Illustrative: Multi-Tier Semantic Cache for a RAG System**

A legal-AI firm runs a RAG pipeline. Their users ask the same questions repeatedly ("Summarize the NDA," "What's the termination clause?"). Each full RAG pipeline run costs $0.08 (embedding + retrieval + LLM generation) and takes 4 seconds. They implement a 3-tier caching strategy:

```
Tier 1: Exact Match Cache (Redis)
  Key: SHA-256(normalize(prompt))
  Value: The complete LLM response
  TTL: 24 hours
  Hit rate: ~15% (handles trivial duplicates like "Summarize the NDA")
  Latency: 1ms

Tier 2: Semantic Cache (Vector DB — pgvector)
  Key: Embedding vector of the prompt
  Match: Cosine similarity > 0.97 against previous prompt embeddings
  Value: The LLM response from the matched previous prompt
  Hit rate: ~25% additional (catches rephrased queries)
  Latency: 50ms (embedding computation + ANN search)

Tier 3: Full RAG Pipeline (The Expensive Path)
  Only runs when Tier 1 and Tier 2 both miss
  Latency: 4,000ms
  Cost: $0.08 per call
  
After generation, async-write the prompt + embedding + response to Tiers 1 and 2.
```

This layered approach means that ~40% of requests never hit the LLM at all. At 10,000 requests/day, that's 4,000 avoided LLM calls × $0.08 = **$320/day saved**, or roughly $9,600/month.

---

## The Tradeoffs

| Mechanism | Benefit | Cost |
|-----------|---------|------|
| Adding any cache | Offloads DB, lowers latency | Consistency bugs (stale data), operational overhead, another system to maintain |
| Long TTL | High hit rate, very fast | Data is stale longer, user frustration when they update something and don't see it |
| Short TTL | Data stays fresh | Lower hit rate, more DB load, defeats the purpose for slowly-changing data |
| Local (in-process) cache | No network hop, microsecond reads | Inconsistent across servers, memory leak risk |
| Distributed cache (Redis) | Consistent, shared, large capacity | Network hop (~1ms), single point of failure if not clustered |
| Semantic caching | Massive LLM cost savings for similar queries | High complexity, risk of returning subtly wrong answers for queries that are similar but not identical |

**The fundamental tradeoff of caching:** You are trading consistency for speed and capacity. The moment you introduce a cache, you accept that your system will sometimes serve stale data. Your only job is to define what "stale" means for your use case and enforce it with TTLs and invalidation.

---

## How This Connects to Other Modules

- **Module 01** & **Module 03**: Caching is the primary tool for "do less work" and the key enabler of horizontal scaling by removing load from the centralized database.
- **Module 04** (Estimation): Cache hit rate directly impacts your compute and cost estimates, especially for LLM API calls. A 90% hit rate means your effective LLM cost is 10% of gross.
- **Module 06** (Load Balancing): Consistent hashing in load balancers can route requests for the same cache key to the same server, improving local cache hit rates.
- **Module 08** (CDN): A CDN is just a distributed HTTP cache operating at the network edge — the same patterns (TTL, invalidation, cache busting) apply.
- **Module 09** & **Module 10** (Databases): Caching is what you do *before* you resort to read replicas or sharding. It's cheaper and simpler.
- **Module 12** (CAP Theorem & Consistency): Caching inherently introduces eventual consistency. The cache is a stale read from a consistency perspective.
- **Module 21** (Distributed Locks): Cache breakdown (hot key expiry) is solved with distributed locks — a direct practical application.
- **Module 22** (Sharding): When your Redis instance gets too big, you shard it using consistent hashing — the same technique used in Module 22.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Everyone asks about LRU vs LFU in interviews. In reality, you configure Redis to use `allkeys-lru` and never think about it again — it is the correct default for 95% of applications. What actually takes down production systems — what I've been paged for at 3am — are Cache Stampedes and Hot Key Expiries (Cache Breakdown). Knowing the difference between those two failure modes, and the fix for each (jitter + pre-warming for stampedes, mutex locks for breakdown), is the difference between a senior engineer who can diagnose the outage and a junior engineer who stares at a wall of 503s and says "the database is slow." Also: cache invalidation is genuinely the hardest problem in distributed systems. If you can avoid building complex invalidation logic by using short TTLs and letting data expire naturally, do that. The complexity of maintaining cache-database consistency through explicit invalidation is almost never worth it for non-financial data.

**The AI-era connection:** Semantic caching is caching in costume, but the costume is genuinely dangerous. In classic caching, the key is an exact string (`user:123`). If you hit the cache, you *know* the data is the correct data for that key. In semantic caching, the key is a vector embedding, and a "hit" is defined by a similarity threshold (e.g., cosine similarity > 0.95). This means you are intentionally returning a cached answer for a query that is *similar but not identical* to the original.

Consider this:
- User A asks: "What is the capital of France?" → Answer: "Paris" (Cached)
- User B asks: "What is the capital of Paris?" → Semantic hit! Very similar embeddings!
- The semantic cache confidently returns "Paris" — which is factually wrong for this question.

This is a failure mode that *cannot exist* in traditional exact-match caching. The cache introduced a factual error that the LLM would not have made.

**Brutally honest advice:** You will be tempted to implement a semantic cache early because the LLM API bills are high and your product manager is nervous about costs. Resist until you have exact-match caching fully deployed and measured. Exact-match caching typically saves 10-20% of API costs with zero risk of semantic hallucination. Semantic caching can save another 20-30%, but every single cache hit carries a risk of returning a subtly wrong answer to a subtly different question. If you implement it, you *must* log both the original query and the matched query side-by-side, and you must have a human review those logs regularly to tune your similarity threshold. The threshold is domain-specific: a 0.95 threshold might be fine for casual chatbots but catastrophic for medical or legal applications where "similar" questions can have completely different correct answers. Start exact. Add semantic only after you've measured the savings and accepted the risk in writing.

---

## Check Your Understanding

1. You implement a cache-aside pattern. A user updates their profile in the database, but the cache is not invalidated. What exactly happens the next time this user's profile is requested? If this were a write-through cache, how would the outcome differ?

2. Your system experiences a Cache Penetration attack where a script requests 10,000 random, non-existent UUIDs per second. Explain why a standard LRU cache with a 1-hour TTL doesn't protect your database, and describe two specific countermeasures.

3. Why is Cache Breakdown (Hot Key Expiry) a significantly worse problem for a RAG system generating a 30-second report than for a web app returning a 10ms JSON payload? Quantify the difference in wasted compute.

4. You set up a semantic cache using pgvector with a cosine similarity threshold of 0.90. Users report getting answers intended for slightly different questions. If you increase the threshold to 0.98, what happens to your (a) correctness, (b) cache hit rate, and (c) LLM API costs? Explain the tradeoff curve.

5. Your Redis cache crashes and restarts empty. Describe the immediate cascade effect on your application and database. Name two techniques to prevent a full outage during this event, and explain why jittered TTLs help even when the cache hasn't crashed.
