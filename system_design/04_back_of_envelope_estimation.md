# 04 — Back-of-Envelope Estimation

## The Problem

You're in a design review. Or an interview. Or a planning meeting. Someone says: "We need to build a system that handles 10 million users." Everyone nods. Nobody asks: how many requests per second is that? How much storage do we need? How much will the compute cost? What's the latency budget?

Without these numbers, "designing a system for 10 million users" is fiction. You're making architectural decisions — sharding, caching, horizontal scaling — without knowing whether they're necessary. You're either over-engineering (spending 6 months building a distributed system that a single Postgres instance could handle) or under-engineering (deploying a single-server setup that falls over on day one).

Back-of-envelope estimation is the single skill that separates a real design conversation from buzzword theater. It takes 5-10 minutes, uses arithmetic you learned in middle school, and immediately tells you what's hard about the system and what's not.

---

## The Naive Approach and Why It Fails

The naive approach is to skip estimation entirely and jump to architecture. "We have lots of users, so we need microservices, Redis, Kafka, sharding, and Kubernetes."

This fails because you don't know what "lots" means. 10,000 users who each make 2 requests per day is 0.23 requests per second at peak — a laptop could handle that. 10,000 users who each make 200 requests per day is 23 requests per second at peak — still easily one server. You don't need microservices. You don't need Kafka. You don't need sharding. You need one machine and a good night's sleep.

The other naive approach: doing the math but with wrong assumptions. Assuming peak traffic is 2x average (it's often 5-10x for consumer apps), assuming all data is "hot" (usually only 10-20% is accessed frequently), or ignoring the read/write ratio (a system that's 95% reads and 5% writes has completely different bottlenecks than a 50/50 system).

---

## The Real Mechanism

### The Estimation Pipeline

Every estimation follows this pipeline, regardless of the system:

```
Step 1: Traffic Estimation
  → How many users? How many actions per user per day?
  → Convert to requests per second (QPS)
  → Identify peak multiplier

Step 2: Read/Write Ratio
  → What fraction of requests are reads vs writes?
  → This determines whether caching helps and what database strategies matter

Step 3: Storage Estimation
  → How much data does each action produce?
  → How much data accumulates over 1 year, 5 years?
  → What's the "hot" data set (data accessed in the last N days)?

Step 4: Bandwidth Estimation
  → How much data flows in/out per second?
  → Is the bottleneck ingress (user uploads) or egress (responses)?

Step 5: Compute/Latency Budget
  → What's the latency target for a single request?
  → How many compute-seconds does each request consume?
  → How many servers needed = (QPS × compute-time-per-request) / cores-per-server
```

### The Numbers You Must Memorize

These are order-of-magnitude numbers. They're not precise — they're close enough for estimation:

```
Time:
  1 day      = 86,400 seconds     ≈ 100,000 seconds (use 10^5)
  1 month    = 2,592,000 seconds  ≈ 2.5 × 10^6 seconds
  1 year     = 31,536,000 seconds ≈ 3 × 10^7 seconds

Storage:
  1 character = 1 byte (ASCII) or 1-4 bytes (UTF-8)
  1 KB = 1,000 bytes (a short text message)
  1 MB = 1,000,000 bytes (a high-res photo, a small PDF)
  1 GB = 10^9 bytes (1,000 photos, or ~250 MP3 songs)
  1 TB = 10^12 bytes (a medium database)
  1 PB = 10^15 bytes (a large company's total data)

Throughput:
  SSD random read: ~100μs (0.1ms)
  SSD sequential read: ~500 MB/s
  Network within datacenter: 1-10 Gbps
  HDD sequential read: ~200 MB/s
  Redis GET: ~0.5ms (including network)
  Postgres simple query: ~1-5ms
  Postgres complex query: ~10-100ms
  LLM API call: ~1,000-10,000ms (1-10 seconds)

Quick conversions:
  1 million requests/day = ~12 requests/second (10^6 / 10^5)
  1 billion requests/day = ~12,000 requests/second
```

### Worked Example 1: URL Shortener (Classic)

**Requirements:** 100M new URLs created per month, 10:1 read:write ratio.

```
Traffic:
  Writes: 100M / month = 100M / (2.5M seconds) ≈ 40 writes/second
  Reads:  10:1 ratio → 400 reads/second
  Peak:   3x average → 120 writes/sec, 1,200 reads/sec at peak

Storage:
  Each URL record: short_code (7 chars) + long_url (avg 100 chars) + metadata (50 bytes)
  ≈ 200 bytes per record
  100M records/month × 200 bytes = 20 GB/month
  5 years: 20 GB × 60 months = 1.2 TB total

Bandwidth:
  Reads: 1,200 req/sec × 200 bytes = 240 KB/sec outbound (trivial)
  Writes: 120 req/sec × 200 bytes = 24 KB/sec inbound (trivial)

Verdict: A single Postgres instance can handle 1,200 reads/sec and 120 writes/sec 
easily. 1.2TB over 5 years fits on one disk. Start with one server, add caching 
(Module 07) for the hot URLs when needed. No need to shard, no need for microservices.
```

### Worked Example 2: Chat Application (Medium)

**Requirements:** 50M daily active users, 40 messages sent per user per day, text only.

```
Traffic:
  Messages: 50M × 40 = 2 billion messages/day
  QPS: 2B / 86,400 ≈ 23,000 messages/second
  Peak: 3x → ~70,000 messages/second

Storage:
  Each message: text (avg 200 bytes) + metadata (user_id, timestamp, chat_id = 50 bytes)
  ≈ 250 bytes per message
  2B messages/day × 250 bytes = 500 GB/day
  1 year: 500 GB × 365 = ~180 TB

Bandwidth:
  Writes: 70K msg/sec × 250 bytes = 17.5 MB/sec inbound at peak
  Reads: if each user reads 200 messages/day (scrolling, loading chats)
    50M × 200 = 10B reads/day ≈ 115K reads/sec
    115K × 250 bytes = 28.75 MB/sec outbound at peak

Verdict: 70K writes/second needs sharding (Module 22). 180TB/year needs distributed 
storage. 115K reads/second needs caching + read replicas. This is a genuinely 
distributed system. Kafka for message delivery (Module 14), sharded database, 
aggressive caching of recent messages.
```

### Worked Example 3: RAG Pipeline (AI-Specific)

**Requirements:** A RAG-based customer support bot. 1,000 businesses, each with 100 support agents using it, 50 queries per agent per day.

```
Traffic:
  Queries: 1,000 × 100 × 50 = 5M queries/day
  QPS: 5M / 86,400 ≈ 58 queries/second
  Peak (business hours, 8-hour window): 5M / (8 × 3600) ≈ 174 queries/second
  Peak burst (everyone returns from lunch): 3x → ~520 queries/second

Latency per query (the RAG pipeline):
  1. Embed the query:        ~50ms  (local model or API call)
  2. Vector search:          ~20ms  (pgvector on a warm index)
  3. Retrieve full documents: ~5ms  (Postgres lookup by ID)
  4. Construct prompt:        ~2ms  (string formatting)
  5. LLM generation:          ~3,000ms (the dominant cost)
  6. Stream response:         ~streaming over 3 seconds
  
  Total: ~3,100ms per request
  Each request holds resources for ~3 seconds

Compute:
  At 520 QPS peak, with 3s per request = 1,560 concurrent requests
  If each worker handles 1 concurrent request: need ~1,560 workers
  With async I/O (worker is mostly waiting for LLM): each worker handles ~10 concurrent
  Need: ~156 workers → ~40 servers with 4 workers each
  
  BUT: most of the 3s is waiting for the LLM API, not compute.
  With proper async: a single worker can handle many concurrent requests.
  Realistic: ~10-20 servers with async FastAPI workers.

Storage (document corpus):
  Each business: ~10,000 documents, avg 5 pages each, avg 2,000 chars/page
  Per business: 10K × 5 × 2KB = 100MB of raw text
  Embeddings: 10K documents × 5 chunks/doc × 1536 dimensions × 4 bytes/float
             = 50K × 6KB = 300MB of embeddings per business
  1,000 businesses: 100GB raw text + 300GB embeddings = 400GB total
  
  Fits on one big Postgres+pgvector instance! No sharding needed yet.

Cost (the estimation most AI engineers skip):
  LLM cost per query: ~1,000 input tokens × $3/M = $0.003 input
                     + ~500 output tokens × $15/M = $0.0075 output
                     ≈ $0.01 per query
  5M queries/day × $0.01 = $50,000/day = $1.5M/month on LLM API costs alone
  
  Embedding cost: one-time bulk embedding of corpus
  100GB text / 8K tokens per batch = 12.5M embedding calls
  At $0.10/M tokens ≈ $1,250 total (one-time, negligible)

Verdict: The compute and storage are manageable on a surprisingly small cluster. 
The COST is the real problem — $1.5M/month on LLM API. This is why caching 
(Module 07, semantic caching) and prompt optimization are system design 
concerns for AI, not just engineering concerns. A 20% cache hit rate saves 
$300K/month. Now caching isn't "nice to have" — it's the most important 
architectural decision in the system.
```

### Worked Example 4: Notification System

**Requirements:** 200M users, send 3 notifications per user per day, multi-channel (push + email).

```
Traffic:
  Notifications: 200M × 3 = 600M/day
  QPS: 600M / 86,400 ≈ 7,000 notifications/second
  Peak: 5x (e.g., flash sale, breaking news) → 35,000/second

Storage:
  Each notification record: 200 bytes (user_id, type, message, timestamp, status)
  600M/day × 200 bytes = 120 GB/day
  Retention 90 days: 10.8 TB

Bandwidth:
  35K/sec × 200 bytes = 7 MB/sec to notification providers (trivial)
  But: each notification hits an external API (FCM, APNS, email service)
  35K external API calls/second at peak — this is the real bottleneck

Verdict: The internal system (queue, database) is not the hard part. 
The hard part is managing 35K/sec outbound API calls to external providers 
that each have their own rate limits, reliability characteristics, and 
failure modes. This is where Module 18 (circuit breakers) and Module 14 
(message queues for rate-controlled delivery) become essential.
```

### Worked Example 5: Image Storage Service

**Requirements:** 10M photos uploaded per day, average 3MB each, 5-year retention.

```
Storage:
  10M × 3MB = 30TB/day
  5 years: 30TB × 365 × 5 = 54.75 PB
  
  Even with compression (2x): ~27 PB over 5 years.
  This doesn't fit on any single machine. This is S3/distributed storage territory.

Bandwidth:
  Uploads: 10M photos/day in 16 "active" hours
  = 10M / (16 × 3600) ≈ 174 uploads/second
  174 × 3MB = 522 MB/second inbound

  Downloads (assume 3x reads vs writes):
  522 × 3MB × 3 = 1.56 GB/second outbound
  → CDN is essential here (Module 08)

Verdict: This is a storage-dominated problem. The compute is trivial 
(receiving and serving files). The storage and bandwidth are enormous. 
This is why S3 exists (Module 34). And this is one of the rare cases 
where CDN (Module 08) is genuinely critical.
```

---

## The Tradeoffs

| Estimation Shortcut | Risk |
|---------------------|------|
| Using average traffic instead of peak | Under-provisioning, outages during spikes |
| Ignoring the read/write ratio | Wrong database strategy (read replicas help reads, not writes) |
| Ignoring data retention | Storage costs blindside you at month 6 |
| Treating LLM cost as fixed | Missing that caching could save 20-50% of your largest cost center |
| Assuming linear scaling | Ignoring that some operations are O(n²) — database joins, embedding comparisons |

---

## How This Connects to Other Modules

- **Module 01** gave you the scaling walls. This module gives you the tool to predict *which wall you'll hit first*.
- **Module 03** (Scalability) gave you vertical vs horizontal. Estimation tells you *when* to make that switch.
- **Module 05** (Reliability) will add latency budgets to your estimations.
- **Module 07** (Caching): your RAG estimation above showed caching saves $300K/month. That number is what makes Module 07 urgent.
- **Module 09** (Databases): connection pool sizing comes directly from your QPS estimate and your per-request hold time.
- Every case study in Phase 4 (Modules 28-36) starts with a back-of-envelope estimation. You'll use this method every time.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** The specific numbers in the examples don't matter — they'll be wrong for your system. What matters is the *method*: traffic → read/write ratio → storage → bandwidth → compute. And the most important step that most people skip: **the cost estimation.** In traditional system design, compute and storage are relatively cheap. In AI systems, the LLM API call dominates everything. A RAG system at 5M queries/day costs $1.5M/month on LLM calls. That single number should reshape every architectural decision: caching, prompt optimization, model selection, batching. If you don't estimate cost, you're designing blind.

**The AI-era connection:** This is where back-of-envelope estimation changes fundamentally for AI systems. In a traditional web app, the cost of a request is approximately zero (a few microseconds of CPU, a few bytes of bandwidth). In an AI system, the cost of a request is measurable and significant ($0.01-$0.50 depending on model and token count). This means:
- Caching isn't just a performance optimization — it's a cost optimization. A 30% cache hit rate on a $1.5M/month API bill saves $450K/month. That justifies a serious engineering investment in semantic caching.
- Retry logic isn't free. In a classic web app, retrying a failed database write costs nothing. Retrying a failed LLM call costs $0.01-$0.50 per retry. This changes how aggressively you retry (Module 18), and makes idempotency (Module 24) not just a correctness concern but a financial one.
- Token count is the new bandwidth. You're not just estimating bytes/second — you're estimating tokens/second and tokens/dollar. Prompt optimization (reducing input token count by 30%) is equivalent to a 30% cost reduction on your largest line item.

**Brutally honest advice:** Most AI engineers never learned back-of-envelope estimation because ML research doesn't require it. You train a model on a dataset, you evaluate on a test set, the bottleneck is the training run and the GPU cost — not request-per-second or storage-per-year. But the moment you put that model behind an API and sell it to customers, the economics of serving it become the dominant concern. I have seen teams build beautiful RAG pipelines that work perfectly at 10 QPS and then discover that at 500 QPS the LLM API bill is $2M/month, which is more than their entire revenue. They had never estimated. Estimation is not glamorous. It's arithmetic on a napkin. And it will save you from building a system that is technically excellent and financially impossible.

---

## Check Your Understanding

1. Your RAG system serves 2,000 queries per hour during business hours (8 hours/day). Each query costs $0.015 in LLM API charges. What's the monthly LLM cost? If you implement semantic caching with a 25% hit rate, how much do you save per month?

2. A chat application has 5M daily active users, each sending 30 messages per day. Average message size is 150 bytes. Estimate: (a) peak QPS assuming 3x average and a 10-hour active window, (b) daily storage growth, (c) storage after 2 years.

3. Your API server processes each RAG request in 4 seconds (most of it waiting for the LLM). You use async workers, each handling 8 concurrent requests. At 200 peak QPS, how many workers do you need? How many servers at 4 workers per server?

4. A vector database holds embeddings for 10M documents. Each embedding is 1536 dimensions × 4 bytes = 6,144 bytes. What's the total storage for embeddings alone? Does this fit on a single machine?

5. You're told "we need to handle 100M users." Before making any design decisions, what are the first three numbers you need to estimate, and why does the answer change everything?
