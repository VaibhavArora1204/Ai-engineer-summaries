# 38 — Common Mistakes and How Designs Are Actually Judged

## The Mistakes That Give You Away

### Mistake 1: Jumping to Complexity Before Proving You Need It

**The tell:** "We'll use microservices with Kubernetes, Redis Cluster, Kafka, and a sharded database."

**Why it's wrong:** You haven't shown WHY any of these are needed. At 50 QPS, a monolith on a single server with Postgres and an in-memory cache handles the load. Adding microservices at this scale introduces network latency, deployment complexity, distributed debugging, and inter-service consistency problems — for zero benefit.

**The fix:** Always start simple. Monolith → add cache → add queue → add read replicas → shard → split services. Each step is triggered by a specific, measurable bottleneck (from your estimation), not by architecture fashion.

### Mistake 2: Premature Sharding

**The tell:** "We should shard the database from day one to be ready for scale."

**Why it's wrong:** Sharding is a one-way door. Once you shard, you lose cross-shard JOINs, cross-shard transactions, and simple schema migrations. The operational overhead is permanent. And at day-one scale (typically under 1M rows), Postgres handles 50,000 QPS of simple reads without breaking a sweat.

**The fix:** Measure first. Profile your queries. Add indexes. Add read replicas. Add caching. THEN, only when you've exhausted all of these and can prove the bottleneck is write throughput on a single node, shard. Most startups never reach this point.

### Mistake 3: Ignoring the "Boring" Parts

**The tell:** The candidate designs an elaborate data pipeline but never mentions authentication, rate limiting, monitoring, or error handling.

**Why it's wrong:** These "boring" parts are what keep the system alive in production. A system without rate limiting gets DDoSed. A system without monitoring fails silently. A system without error handling cascades failures.

**The fix:** In an interview, briefly mention: "Authentication is handled at the API gateway. Rate limiting uses a sliding window counter in Redis. Monitoring uses Prometheus + Grafana for the four golden signals." You don't need to deep-dive these unless asked, but showing you KNOW they exist signals production experience.

### Mistake 4: Presenting One Design as "The Answer"

**The tell:** "This is the correct design." No acknowledgment of alternatives or tradeoffs.

**Why it's wrong:** Every design choice has costs. Strong consistency adds latency. Caching adds staleness. Microservices add complexity. A senior engineer acknowledges these costs explicitly.

**The fix:** "I chose eventual consistency for the search index because a 5-second staleness window is acceptable for this use case. If we needed real-time consistency, I'd use synchronous replication, which would add ~50ms to every write."

### Mistake 5: Buzzword-Without-Mechanism

**The tell:** "We'll use a message queue for this." The interviewer asks "What delivery guarantee does the queue provide?" Silence.

**Why it's wrong:** Naming a technology is not designing. You need to explain: what the technology does (mechanism), why you chose it over alternatives (tradeoff), and how it interacts with the rest of your system (integration).

**The fix:** "We'll use an SQS FIFO queue with at-least-once delivery. The consumer is idempotent — it checks a deduplication table before processing — so duplicate deliveries are harmless. We chose SQS over Kafka because we don't need event replay, and SQS FIFO gives us message-level deduplication within a 5-minute window."

### Mistake 6: Over-Indexing on Model/Algorithm Quality, Under-Indexing on Infrastructure

**The tell (specific to AI-background engineers):** The candidate spends 25 minutes talking about embedding models, chunking strategies, and reranking algorithms, but hasn't mentioned: connection pools, caching, rate limiting, or failure handling.

**Why it's wrong:** The model is a function call. The infrastructure around it determines whether the product works when 50 people use it simultaneously. A perfectly tuned RAG pipeline that exhausts its connection pool under moderate load is useless.

**The fix:** Divide your design time roughly: 30% on the AI-specific components (retrieval, generation, evaluation), 70% on the infrastructure (API design, caching, queuing, scaling, failure modes, monitoring). The interviewer can verify your ML knowledge with ML-specific questions. In a system design interview, they want to see that you can build a system that stays up.

---

## How Designs Are Actually Judged

### What Separates Junior from Senior

| Behavior | Junior | Senior |
|---------|--------|--------|
| Requirements | Assumes requirements, starts designing | Asks clarifying questions, scopes the problem |
| Estimation | Skips or hand-waves | Does the math, lets numbers drive architecture |
| Design | Names technologies | Explains mechanisms and tradeoffs |
| Depth | Goes wide, covers everything shallowly | Goes deep on the 2-3 genuinely hard parts |
| Failure modes | Doesn't consider them | Proactively identifies SPOFs and proposes mitigations |
| Tradeoffs | "This is the right design" | "This design optimizes for X at the cost of Y" |
| Scale | "We'll scale later" or "We need to scale now" | "At this scale, we need X. At 10x, we'd need Y" |
| Communication | Talks at the whiteboard | Has a structured conversation, checks understanding |

### The Three Levels of Design Maturity

**Level 1 — Tool Collector:** "I'll use Redis, Kafka, and Kubernetes." Names tools without understanding when/why they're needed. Can describe what each tool does but can't explain when to NOT use it.

**Level 2 — Pattern Matcher:** "This is a read-heavy system, so I'll add caching and read replicas." Recognizes common patterns and applies them correctly. Can explain the mechanism. Starting to articulate tradeoffs.

**Level 3 — Tradeoff Navigator:** "Given a 5-second latency budget and eventual consistency tolerance, I'll use semantic caching with a 0.95 similarity threshold. This saves $50K/month in LLM costs at the risk of ~2% cache false positives, which I mitigate with user feedback." Understands the specific constraints, makes a quantified tradeoff, and has a mitigation for the downside.

Most interview candidates are at Level 1-2. Reaching Level 3 is what this curriculum is designed to build.

---

## The AI-Background Blind Spot

If you came from an ML/AI background, here's what the interviewer suspects about you (and is looking for evidence to confirm or deny):

**They suspect you:**
- Think the hard part of building an AI product is the model.
- Under-appreciate infrastructure concerns (connection pools, caching, queuing, monitoring).
- Haven't operated a production system under real traffic and dealt with 3am outages.
- Can explain gradient descent but can't explain why a connection pool with 20 connections exhausts under 30 QPS with 5-second LLM latency.

**How to counter this:**
- Lead with the infrastructure. Show you understand the system, not just the model.
- Proactively mention: connection pool sizing, caching strategy, failure modes, cost estimation.
- When you discuss AI-specific components (embedding, generation, retrieval), connect them to infrastructure concerns: "The embedding step adds 50ms latency and holds a GPU resource. I'd batch embedding requests to maximize GPU utilization."

---

## Mentor's Take — What Actually Matters Here

**What matters:** The single most important skill in system design — in both interviews and real life — is the ability to articulate WHY. Why this technology? Why this tradeoff? Why this order of operations? Why is this the bottleneck and not that?

An engineer who says "I chose Postgres because it handles our 50 QPS read workload with a single instance, and I don't want the operational overhead of a distributed database at this scale" demonstrates more design maturity than one who says "I chose CockroachDB because it's distributed and highly available" — even though CockroachDB is objectively a more impressive technology. The first engineer is making a reasoned, context-specific decision. The second is name-dropping.

**Brutally honest advice:** Record yourself doing a system design practice session. Listen back. Count how many times you say a technology name without explaining WHY you chose it. Count how many times you skip estimation. Count how many times you ignore failure modes. These are your specific areas for improvement. Everyone has them. The practice recording is the mirror that shows them.

---

## Check Your Understanding

1. A candidate designs a chat application and proposes microservices from the start: User Service, Message Service, Notification Service, Analytics Service. The expected user base is 10,000 users. What question would you ask to expose the over-engineering?

2. A design review presentation shows a system with: Postgres, Redis, Elasticsearch, Kafka, RabbitMQ, MongoDB, and a dedicated Vector DB. The system serves 100 QPS. What is the likely problem, and what would you recommend?

3. An AI engineer presents a RAG system design. They spend 20 minutes on embedding model selection, chunk size optimization, and reranking algorithms. They mention Postgres once (for storage) and never mention caching, connection pools, or failure handling. What feedback would you give?

4. Explain the difference between "We need Kafka for this" (Level 1) and a Level 3 version of the same design decision.

5. You're interviewing a candidate who says "I'd shard the database from day one because we want to be ready for scale." What's your follow-up question, and what answer would satisfy you?

---

### Answers

1. **Answer:** "How many messages per second does this system need to handle?" Answer: 10K users × maybe 10 messages/day = 100K messages/day = ~1 message/second. "Can a single Postgres instance handle 1 write per second?" Yes, trivially. "Then why do you need 4 separate deployed services with inter-service network calls, distributed tracing, and independent deployments for a workload a single Python process can handle?" The question exposes that the microservice decision is based on fashion, not on a measured bottleneck.

2. **Answer:** The likely problem is "résumé-driven development" — each technology was chosen because it's impressive, not because the workload requires it. At 100 QPS: Postgres alone handles the read/write workload. Redis is justified for caching. Elasticsearch might be justified IF there's a full-text search requirement. Kafka, RabbitMQ, MongoDB, and a dedicated Vector DB are almost certainly unnecessary. Recommendation: remove components until the system breaks in load testing. You'll likely end up with Postgres + Redis + maybe Elasticsearch.

3. **Answer:** "Your model selection and retrieval optimization are strong. But in a system design review, I need to see: (1) Connection pool sizing — at what QPS does the pool exhaust given your LLM latency? (2) Caching strategy — what's the cache hit rate target, and what's the monthly cost difference between cached and uncached? (3) Failure modes — what happens when the LLM API is down? What's the fallback? (4) Cost estimation — what's the per-query LLM cost, and what's the monthly bill at projected scale? These infrastructure concerns determine whether your beautifully-tuned RAG pipeline actually survives production traffic."

4. **Answer:** Level 1: "We need Kafka for this." Level 3: "The ingestion pipeline produces ~500 document-update events per second. These events must be processed by 3 independent consumers (embedding service, search indexer, analytics). Kafka's consumer group model lets each consumer read the same event stream independently at its own pace. We chose Kafka over RabbitMQ because we need event replay — if the embedding service crashes and restarts, it can replay from its last committed offset without the events being lost. The tradeoff: Kafka is more complex to operate than SQS, but the replay guarantee is worth it because re-embedding all documents from scratch costs $500 per incident."

5. **Answer:** Follow-up: "What's the estimated QPS and data volume at launch, and at what point does a single Postgres instance become the bottleneck?" A satisfying answer: "At launch, we expect 100 QPS and 50 GB of data — single Postgres handles this easily. I'd shard at around 50,000 writes/second or 5 TB, which based on our growth projections is 18-24 months away. The shard key would be tenant_id because our queries are always scoped to a single tenant. I'd monitor query latency and connection pool utilization monthly to detect the need before it becomes an outage." This answer shows they've estimated, know the trigger point, have a shard key in mind, and have a monitoring plan. The original statement showed none of that.
