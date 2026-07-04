# 40 — Practice Problems: Three Tiers, With Guided Hints

## How to Use This File

Pick a problem. Set a 45-minute timer. Talk through your design out loud (yes, out loud, even if it feels ridiculous — this is how you build the verbal fluency needed in interviews). Follow the 7-step framework from Module 37.

Do NOT look at the hints until you've spent at least 15 minutes working through the problem on your own.

---

## Tier 1: Foundation (Single-System Focus)

### Problem 1: Design a Paste Service (like Pastebin)
Users create text pastes (up to 10 MB). Each paste gets a unique URL. Pastes can be public or private (accessible via link). Support optional expiration.

**Guiding questions:**
- What's the read-to-write ratio? How does this affect your architecture?
- How do you generate unique paste IDs? (Callback to Module 28's short code generation.)
- Where do you store the paste content — in the database or in object storage?
- How do you handle a paste that goes viral (500K reads/second)?

**Hardest part:** Large paste storage. 10 MB in a Postgres row is expensive. Think about S3 (Module 34) for content and Postgres for metadata.

**Module callbacks:** 28 (URL generation), 34 (Object storage), 07 (Caching viral pastes).

---

### Problem 2: Design a Key-Value Store with TTL Support
Build a simplified Redis: support GET, SET, DELETE, and automatic key expiration. Single-node first, then discuss how to distribute across multiple nodes.

**Guiding questions:**
- How do you implement TTL efficiently? Do you check every key every second, or use a smarter approach?
- What eviction policy do you use when memory is full?
- How do you distribute keys across multiple nodes? (Callback to Module 22.)

**Hardest part:** Efficient TTL implementation. Redis uses a combination of lazy expiration (check on access) and periodic sampling (randomly check 20 keys every 100ms, delete expired ones). This is more efficient than scanning all keys.

**Module callbacks:** 36 (Redis internals), 22 (Consistent hashing for distribution).

---

### Problem 3: Design a Rate Limiter for an AI API Gateway
Your API gateway proxies requests to OpenAI, Anthropic, and self-hosted models. Each tenant has rate limits on: requests per minute, tokens per minute, and dollars per day.

**Guiding questions:**
- How do you handle the two-dimensional rate limiting (RPM + TPM)?
- How do you estimate token count BEFORE forwarding the request? (Input tokens are countable; output tokens must be estimated.)
- The tenant has a $100/day budget. At 3 PM, they've spent $95. A request comes in that will consume approximately $3. Do you allow it?
- What happens when Redis (your rate limit store) goes down?

**Hardest part:** The three-dimensional rate limiting: RPM × TPM × $/day. Each dimension has a different time window and a different counting mechanism.

**Module callbacks:** 29 (Rate limiter), 16 (API design), 24 (Idempotency for cost tracking).

---

### Problem 4: Design an Image Upload and Processing Pipeline
Users upload images. The system generates thumbnails (3 sizes), extracts EXIF metadata, runs NSFW detection, and stores the original + thumbnails. Users can browse their images with pagination.

**Guiding questions:**
- Should thumbnail generation be synchronous (user waits) or asynchronous (user sees a placeholder)?
- How do you handle a user uploading 500 images at once? (Backpressure — Module 14.)
- Where do you store the images? (Not in the database — Module 34.)
- How do you serve images with low latency to global users? (CDN — Module 08.)

**Hardest part:** The async processing pipeline with failure handling. What if the NSFW detection service is down? Do you block the entire upload? Queue and retry?

**Module callbacks:** 34 (S3 storage), 08 (CDN), 14 (Message queue for async processing), 18 (Circuit breaker for NSFW service).

---

### Problem 5: Design a Leaderboard System
A mobile game has 10 million players. The leaderboard shows the top 100 players globally and each player's rank. Updated in real-time as scores change.

**Guiding questions:**
- What data structure supports efficient rank queries? (Hint: Redis Sorted Sets.)
- How do you handle 10M players all updating scores simultaneously? (Write contention.)
- A player asks "What's my rank?" How do you answer this without scanning all 10M entries?
- What's the latency budget? (Real-time gaming → under 50ms.)

**Hardest part:** "What's my rank?" at scale. Redis ZRANK on a sorted set with 10M members runs in O(log N) — under 1ms. This is a case where the right data structure (skip list in Redis Sorted Set) solves the problem trivially.

**Module callbacks:** 36 (Redis sorted sets), 07 (Caching top-100), 22 (Sharding if multi-region).

---

## Tier 2: Integration (Multi-Component, Moderate Complexity)

### Problem 6: Design a Document Collaboration System (Google Docs Simplified)
Multiple users edit the same document simultaneously. Each user sees others' cursors and changes in real-time.

**Guiding questions:**
- How do you handle conflicting edits (two users edit the same paragraph simultaneously)?
- What real-time communication mechanism do you use? (WebSockets — bidirectional editing.)
- How do you persist the document? (Every keystroke to the database? Or batch writes?)
- How do you show edit history and allow undo?

**Hardest part:** Conflict resolution. Research Operational Transformation (OT) or Conflict-free Replicated Data Types (CRDTs) at the intuition level. The key insight: each edit is an "operation" (insert char 'a' at position 5), and operations from different users are transformed to account for concurrent changes.

**Module callbacks:** 26 (WebSockets), 20 (Consensus — the document state must eventually converge), 14 (Event stream for operation history).

---

### Problem 7: Design a Semantic Search API for a Multi-Tenant SaaS
200 business customers, each with up to 100K documents. Users send natural language queries and receive relevant document excerpts with citations.

**Guiding questions:**
- Single shared index with tenant_id filtering, or separate index per tenant?
- How do you prevent Tenant A's documents from appearing in Tenant B's results?
- What's your hybrid search strategy (vector + keyword)?
- How do you handle a new customer uploading 100K documents on day one? (Bulk ingestion.)

**Hardest part:** Tenant isolation at the vector search level. Row-Level Security in pgvector, or namespace isolation in a managed vector DB.

**Module callbacks:** 30 (RAG pipeline), 27 (Search — hybrid), 22 (Sharding by tenant), 14 (Async ingestion queue).

---

### Problem 8: Design a Webhook Delivery System
Your platform sends webhooks to customer endpoints when events occur (payment received, order shipped). Customers register their webhook URLs. You must guarantee at-least-once delivery with retry on failure.

**Guiding questions:**
- How do you handle a customer's webhook endpoint being down for 6 hours?
- What's your retry strategy (exponential backoff with jitter)?
- How do you prevent a slow/failing webhook endpoint from blocking webhooks to other customers?
- How does the customer verify the webhook is genuinely from you? (Signature verification.)

**Hardest part:** Isolation between customers. If Customer A's endpoint is timing out (taking 30 seconds per request), the workers processing Customer A's webhooks shouldn't delay Customer B's webhooks. Solution: per-customer queues or a priority system that deprioritizes failing endpoints.

**Module callbacks:** 24 (Idempotency — customer's handler must be idempotent), 18 (Circuit breaker per endpoint), 14 (Queue per customer), 35 (Notification patterns).

---

### Problem 9: Design an AI-Powered Customer Support Bot
The bot uses RAG to answer questions from a company's knowledge base. If it can't answer confidently, it escalates to a human agent. It handles 1,000 concurrent conversations.

**Guiding questions:**
- How do you determine "confidence"? (LLM self-assessment, retrieval score threshold, or a separate classifier?)
- How does the handoff from bot to human work? (State transfer — the human sees the conversation history and the bot's attempted answer.)
- How do you prevent the bot from giving dangerous advice (legal, medical)?
- What happens when the LLM API goes down mid-conversation?

**Hardest part:** The confidence threshold for escalation. Too low = too many escalations, defeating the purpose. Too high = the bot confidently gives wrong answers. This is a product/ML problem wrapped in a system design problem.

**Module callbacks:** 30 (RAG), 26 (WebSocket/SSE for streaming), 18 (Circuit breaker for LLM API), 25 (Tracing conversations for quality review).

---

### Problem 10: Design a Payment Reconciliation System
Compare your internal transaction records against Stripe's records. Detect discrepancies (double charges, missed refunds, orphaned charges). Run hourly. Alert on mismatches.

**Guiding questions:**
- How do you handle the time window? (Transactions in the last 2 hours from both systems, but clock skew means you need overlap.)
- What types of discrepancies can exist? (Present in Stripe but not locally, present locally but not in Stripe, status mismatch.)
- How do you auto-resolve vs alert for manual review?
- How do you handle a discrepancy that keeps appearing every hour because the fix takes 3 days?

**Hardest part:** The time-window edge case. A transaction created at 9:59:59 might appear in Stripe's 10:00-12:00 window but your internal 8:00-10:00 window. Always use overlapping windows and dedup previously-detected discrepancies.

**Module callbacks:** 32 (Payment processing), 24 (Idempotency), 25 (Observability — alerting).

---

## Tier 3: Advanced (Full System, Multiple Interacting Concerns)

### Problem 11: Design a Multi-Model AI Gateway
A proxy that routes requests to OpenAI, Anthropic, Google, or self-hosted models based on: cost, latency, capability, and availability. Support fallback (if primary fails, route to secondary).

**Guiding questions:**
- How do you decide which model to route to? (Rules-based? Dynamic scoring based on real-time latency?)
- How do you handle different API formats? (OpenAI's format vs Anthropic's format — adapter pattern.)
- What happens when one provider has a 5-minute outage? (Circuit breaker, automatic failover.)
- How do you track cost across providers with different pricing models?

**Hardest part:** Dynamic routing with real-time provider health. Maintain a sliding window of each provider's p95 latency and error rate. Route away from degraded providers automatically.

**Module callbacks:** 06 (Load balancing — provider routing IS load balancing), 18 (Circuit breaker per provider), 29 (Rate limiting per provider's limits), 25 (Observability per provider).

---

### Problem 12: Design a Real-Time Fraud Detection System for Payments
Analyze every transaction in real-time (< 200ms). Flag suspicious transactions for review. Block clearly fraudulent transactions automatically. Handle 10,000 transactions/second.

**Guiding questions:**
- What features do you compute for each transaction? (Amount deviation from user's history, geographic anomaly, velocity — number of transactions in the last hour.)
- How do you compute "user's average transaction amount" in real-time? (Pre-computed aggregates in Redis.)
- What's the cost of a false positive (blocking a legitimate transaction) vs false negative (allowing fraud)?
- How do you handle a model update? (Blue-green deployment of the scoring model.)

**Hardest part:** Latency budget. 200ms to: load user history, compute features, run the scoring model, make the decision, and return. Each step must be sub-50ms.

**Module callbacks:** 07 (Caching user profiles and aggregates), 15 (Event streaming for real-time aggregation), 18 (Circuit breaker — if the scoring model is down, default to rules-based).

---

### Problem 13: Design a Distributed Task Scheduler (Cron at Scale)
10,000 recurring tasks (some every minute, some daily). Tasks must execute exactly once per schedule. Handle task failures with retry. Support task dependencies (Task B runs after Task A completes).

**Guiding questions:**
- How do you prevent two scheduler instances from both firing the same task? (Distributed lock — Module 21.)
- How do you handle a task that takes longer than its schedule interval? (Still running when the next execution is due.)
- How do you implement task dependencies? (DAG — directed acyclic graph of tasks.)
- What happens when the scheduler crashes mid-execution?

**Hardest part:** Exactly-once execution with distributed schedulers. Use a leader election (Module 20) to ensure only one scheduler instance fires tasks, with a follower ready to take over.

**Module callbacks:** 21 (Distributed locks), 20 (Leader election), 14 (Task queue), 24 (Idempotent task execution).

---

### Problem 14: Design an E-Commerce Flash Sale System
A limited-edition product (1,000 units) goes on sale at exactly 12:00 PM. 500,000 users try to buy it simultaneously. The system must: prevent overselling, handle the traffic spike, and process payments fairly (first-come-first-served).

**Guiding questions:**
- How do you handle 500K simultaneous requests? (CDN for static pages, queue for purchase attempts.)
- How do you prevent overselling 1,000 units? (Atomic conditional update — Module 33's Last Biryani Problem.)
- How do you prevent bots from buying all the inventory? (CAPTCHA, rate limiting, device fingerprinting.)
- What's the user experience for the 499,000 people who don't get one?

**Hardest part:** The queue-based purchase flow. Put all purchase attempts into a queue at 12:00 PM. A single consumer processes them in order, applying the atomic `UPDATE stock WHERE stock > 0` for each. First 1,000 succeed. The rest get "Sold out."

**Module callbacks:** 33 (Inventory contention), 29 (Rate limiting bots), 23 (Saga for payment + inventory), 08 (CDN for static sale page).

---

### Problem 15: Design an End-to-End AI Agent Evaluation Platform
A platform that runs hundreds of test cases against an AI agent, records the agent's behavior (tool calls, reasoning, final output), scores each run on correctness/safety/cost metrics, and provides a dashboard comparing agent versions.

**Guiding questions:**
- How do you run 500 test cases in parallel without overwhelming the LLM API? (Rate-limited parallel execution with a semaphore.)
- How do you store and compare traces across agent versions? (Trace storage + diff visualization.)
- How do you handle non-determinism? (The agent might pass a test 7 out of 10 times. You need statistical significance.)
- How do you define "correctness" for an open-ended agent response? (LLM-as-judge, human review, or a combination.)

**Hardest part:** Non-determinism. You can't run a test once and call it passed/failed. You need N runs per test case and statistical analysis (pass rate, confidence interval). This turns a 500-test-case suite into 5,000 LLM API calls (10 runs each), costing ~$50-500 per evaluation run.

**Module callbacks:** 31 (Agent orchestration), 25 (Observability/tracing), 29 (Rate limiting against LLM API), 14 (Queue for test execution).

---

## Mentor's Take — How to Actually Practice

**Record yourself.** Set a 45-minute timer. Pick a problem. Talk through the 7-step framework out loud. Record the audio (or video of a whiteboard). Listen back. You will cringe. That cringe is the learning.

**Focus on two things per practice session:**
1. Did I do the estimation before choosing the architecture?
2. Did I identify the genuinely hard part, or did I deep-dive on the easy part?

**Frequency:** One problem per week. At that pace, you'll have covered all 15 in about 4 months. By problem 10, the framework will be muscle memory.

**Don't look for "the answer."** These problems don't have one correct design. They have a space of reasonable designs, each with different tradeoffs. The goal is to navigate that space confidently, not to memorize a specific solution.
