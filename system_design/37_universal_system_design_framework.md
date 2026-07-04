# 37 — The Universal System Design Framework

## The Problem

You sit down for a system design interview, or a design review meeting, or a whiteboard session with your team. Someone says: "Design a notification system" or "How would you build a RAG pipeline that handles 10,000 concurrent users?"

You know the concepts — caching, sharding, queues, consensus. But how do you structure the conversation? Where do you start? How do you avoid the trap of jumping to solutions before understanding the problem?

This module distills everything from modules 01-36 into a repeatable, 7-step process you can apply to any system design problem.

---

## The 7-Step Framework

### Step 1: Clarify Requirements (5 minutes in interview, 1-2 days at work)

**What you do:** Ask questions to narrow down the problem. Do not design anything yet.

**Functional requirements:**
- What does the system do? What are the core features?
- What are the inputs and outputs?
- Who are the users? (Internal service, external API, consumer app?)

**Non-functional requirements:**
- What's the scale? (Users, requests per second, data volume)
- What's the latency budget? (Under 200ms? Under 5 seconds? Under 1 minute?)
- What's the consistency requirement? (Strong? Eventual?)
- What's the availability requirement? (99.9%? 99.99%?)
- What's the cost constraint? (Unlimited cloud budget? Bootstrapped startup?)

**The interview discipline:** Spend the first 3-5 minutes asking questions. The interviewer expects this. Jumping straight to "I'll use Kafka and Redis" before understanding the requirements is the #1 tell of a junior candidate.

### Step 2: Back-of-Envelope Estimation (3-5 minutes)

**What you do:** Convert the requirements into concrete numbers.

```
Users → Requests per second (QPS)
QPS → Storage per day/year
QPS × latency per request → Concurrent connections needed
QPS × cost per request → Monthly cost
```

**Why this matters:** The estimation determines the architecture. 10 QPS is one Postgres instance. 10,000 QPS with 95% reads is Postgres + Redis. 100,000 QPS with heavy writes is sharded database + queue + cache.

**The estimation catches bad instincts:** "We need Kafka" at 10 QPS is over-engineering. "We'll use a single database" at 100,000 QPS is under-engineering. The numbers tell you which is which.

### Step 3: Define the API Contract (2-3 minutes)

**What you do:** Define the core API endpoints. This forces you to think about the system's external interface before the internal design.

```
POST /api/v1/messages
  Body: {conversation_id, content, sender_id}
  Response: {message_id, timestamp, status}

GET /api/v1/conversations/{id}/messages?limit=50&before=cursor
  Response: {messages: [...], next_cursor: "..."}
```

**Why this matters:** The API reveals the access patterns. `GET /messages?conversation_id=X` tells you the read pattern. `POST /messages` tells you the write pattern. The access patterns determine the database schema, shard key, and caching strategy.

### Step 4: High-Level Design (5-10 minutes)

**What you do:** Draw the major components and how they connect. Walk through one request end-to-end.

**Components to consider:**
- API Gateway / Load Balancer
- Application servers
- Database(s) — primary store
- Cache — Redis or equivalent
- Message queue — for async processing
- External APIs — payment provider, LLM API, notification service
- CDN — for static assets, media

**Walk through one request:**
"A user sends a message. The request hits the load balancer, routes to an API server. The server validates the request, writes the message to Postgres, publishes a notification event to the queue, and returns a response. The notification worker picks up the event and sends a push notification."

This end-to-end walkthrough exposes gaps in your design (where does the WebSocket connection fit? What happens if the database write fails?).

### Step 5: Deep Dive on the Hard Parts (10-15 minutes)

**What you do:** Identify the 2-3 genuinely hard problems and go deep.

**How to identify the hard parts:**
- What has the highest QPS? (Scaling challenge)
- What involves money? (Correctness challenge — idempotency, consistency)
- What crosses service boundaries? (Distributed systems challenge — consistency, coordination)
- What has a latency constraint that's hard to meet? (Performance challenge)
- What involves user-generated content at scale? (Storage, moderation challenge)

**Go deep means:** Explain the mechanism, the tradeoff, and why you chose this approach over the alternatives. "I'm using a sliding window counter for rate limiting because fixed window has a boundary burst problem, and sliding window log uses too much memory at this scale."

### Step 6: Identify Bottlenecks and Failure Modes (5 minutes)

**What you do:** Stress-test your design mentally.

**Questions to ask your own design:**
- What happens if the database goes down?
- What happens if traffic spikes 10x?
- What happens if a downstream dependency (LLM API, payment provider) is slow?
- What's the single point of failure?
- Where does the connection pool exhaustion happen first?
- What data can be lost, and what data must NEVER be lost?

**For each failure:** State the fix. "The database is a SPOF. We add a read replica for failover. If the primary dies, the replica is promoted within 30 seconds. We accept up to 500ms of lost writes during the failover window."

### Step 7: Discuss Tradeoffs Explicitly (3-5 minutes)

**What you do:** Acknowledge what you traded away in your design.

Every design decision has a cost:
- Caching improves read latency but introduces staleness.
- Sharding scales writes but makes cross-shard queries expensive.
- Async processing improves API response time but introduces eventual consistency.
- Microservices enable independent deployment but add network complexity.

**The senior signal:** Junior engineers present their design as "the right answer." Senior engineers present their design as "the best set of tradeoffs given these specific requirements, and here's what breaks if the requirements change."

---

## The Interview Version vs The Real-World Version

| Aspect | Interview (45 minutes) | Real World (1-2 weeks) |
|--------|----------------------|----------------------|
| Requirements | Ask interviewer for 3-5 minutes | Talk to PM, users, and stakeholders for days |
| Estimation | 3-minute napkin math | Detailed capacity planning with load testing |
| Design | Whiteboard sketch, verbal walkthrough | Design document, reviewed by 3-5 engineers |
| Deep dive | 2-3 topics, mechanism + tradeoff | Full spike/prototype, benchmarks, vendor evaluation |
| Failure modes | "What happens if X fails" verbal | Chaos engineering, gamedays, runbook creation |
| Tradeoffs | Verbal acknowledgment | Written ADR (Architecture Decision Record) |

**The interview is a compressed, performative version of the real process.** The thinking is the same; the depth and evidence differ.

---

## Worked Example: Applying the Framework to "Design a Semantic Search System"

**Step 1 — Clarify:**
- Multi-tenant? Yes, 200 tenants.
- Document types? PDF, Markdown, HTML.
- Query types? Natural language questions + keyword searches.
- Scale? 50 QPS peak.
- Latency? Under 500ms for search (excluding LLM generation).

**Step 2 — Estimate:**
- 50 QPS × 100ms per search = 5 concurrent searches (trivial for a single DB).
- 200 tenants × 10K docs × 20 chunks × 6 KB embedding = 240 GB embeddings.
- Fits on one pgvector instance.

**Step 3 — API:**
```
POST /api/v1/search
  Body: {tenant_id, query, top_k: 10, search_type: "hybrid"}
  Response: {results: [{chunk_id, content, score, source_doc}]}
```

**Step 4 — High-Level Design:**
User → API → Embedding Service (embed query) → pgvector (vector search) + Postgres (BM25 keyword search) → Reranker → Results.

**Step 5 — Deep Dive:**
Hard part 1: Hybrid search — merging vector and keyword results using Reciprocal Rank Fusion.
Hard part 2: Tenant isolation — Row-Level Security on pgvector to prevent data leakage.

**Step 6 — Bottlenecks:**
- pgvector HNSW index rebuild after bulk ingestion is slow (~30 minutes for 240 GB). Solution: index in the background, swap atomically.
- Embedding API is a single point of failure. Solution: fallback to a local model (slower but available).

**Step 7 — Tradeoffs:**
- pgvector over Pinecone: simpler operations, but we accept slower HNSW index builds and lack of managed scaling. We'll migrate to Pinecone if we exceed 1 billion vectors.
- Hybrid search over pure vector: adds latency (~50ms for the BM25 query) but significantly improves recall on exact-match queries.

---

## Mentor's Take — What Actually Matters Here

**What matters:** The framework is not a formula — it's a thinking discipline. The actual steps matter less than the mindset: understand before designing, estimate before architecting, acknowledge tradeoffs before presenting.

The two most common mistakes:
1. **Jumping to solutions** before understanding the scale. "We need Kafka" — do you? What's the QPS? At 10 QPS, Kafka is overhead, not a solution.
2. **Presenting one design as the only answer.** Every design has tradeoffs. The interviewer wants to see that you understand them. "I chose eventual consistency for the search index because strong consistency would add 200ms to every query, and a 5-second staleness window is acceptable for this use case."

**Brutally honest advice:** Practice this framework by talking out loud. Pick a system (Instagram, Uber, your own project), set a 45-minute timer, and design it following the 7 steps while recording yourself or talking to a wall. The first time will feel awkward. By the fifth time, the framework will be muscle memory. There is no substitute for this practice — reading about system design and doing system design are completely different skills.

---

## Check Your Understanding

1. You're asked to design a URL shortener. You jump straight to "I'll use Redis for the mappings and Kafka for click analytics." What is the interviewer's likely reaction, and what should you have done first?

2. Your back-of-envelope estimation shows 15 QPS average, 50 QPS peak. A teammate proposes using a sharded database with 5 nodes and Redis Cluster. Using the estimation, explain why this is over-engineering.

3. During Step 5 (Deep Dive), you're designing a payment system and you deep-dive into the database schema and the API response format. What did you miss, and why would the interviewer be concerned?

4. In Step 6 (Bottlenecks), you identify that the LLM API is a single point of failure. Propose three different mitigations at three different cost/complexity levels.

5. A junior engineer presents a system design and says "This is the correct architecture." A senior engineer presents the same system and says something different. What does the senior engineer say?

---

### Answers

1. **Answer:** The interviewer's reaction: "This person jumped to tools without understanding the problem." You should have first asked: What's the scale? (How many URLs per day? What's the read-to-write ratio?) Then estimated: 40 writes/sec, 12K reads/sec — a single Postgres instance handles this. Redis is justified for caching hot URLs. Kafka is justified for analytics. But you should arrive at these tools through reasoning from requirements, not by naming technologies upfront.

2. **Answer:** 50 QPS peak is trivially handled by a single Postgres instance (which can handle 10,000+ simple reads per second). 5 sharded database nodes add: cross-shard query complexity, operational overhead for 5 databases, rebalancing pain, and no cross-shard JOINs. Redis Cluster with 3 nodes adds: infrastructure cost and operational complexity. Total: massively over-provisioned infrastructure for a workload that fits on one machine. The right design: one Postgres instance, one Redis instance for caching, and one API server. Add complexity only when load testing proves it's needed.

3. **Answer:** You missed the genuinely hard parts: idempotent charge processing (what happens on retries?), the saga pattern (what happens if payment succeeds but inventory fails?), webhook handling (how do you process Stripe's at-least-once webhooks?), and reconciliation. The schema and API format are important but straightforward — any competent engineer can design them. The interviewer is concerned because you deep-dived on the easy parts and skipped the parts that actually break in production.

4. **Answer:** (1) Low cost/complexity: Client-side retry with exponential backoff + jitter. If OpenAI is temporarily slow, retries eventually succeed. Cost: zero. (2) Medium: Multi-provider fallback. If OpenAI fails, automatically route to Anthropic or a self-hosted model. Cost: integration effort + maintaining two provider configs. (3) High: Request queue + async processing. Decouple the user request from the LLM call. User submits → request is queued → worker processes when LLM is available → user is notified when done. Cost: significant architecture change, but the LLM SPOF is fully mitigated.

5. **Answer:** The senior engineer says: "Given these specific requirements — 50 QPS, eventual consistency acceptable, 5-second latency budget — this architecture is the best set of tradeoffs I found. Here's what I traded away: strong consistency on the search index (5-second stale window), single-region deployment (we'd need multi-region for 99.99% availability, but the cost doesn't justify it at our scale), and I chose pgvector over Pinecone (simpler but we'll need to migrate if we exceed 1B vectors). If the requirements change — say, we need strong consistency or 10x the traffic — here's what I'd change."
