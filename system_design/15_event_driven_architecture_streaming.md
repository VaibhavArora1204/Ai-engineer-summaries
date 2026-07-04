# 15 — Event-Driven Architecture and Streaming

## The Problem

Your RAG system has a document ingestion pipeline: user uploads a PDF → extract text → chunk → embed → index in vector DB → update search metadata → send confirmation email. You've built this as a synchronous chain of function calls. It works.

Then requirements grow. Now you also need to: update the analytics dashboard, recalculate the user's storage quota, trigger a compliance scan, and notify the admin Slack channel. Your single pipeline function now calls 8 downstream services. Adding a 9th requires modifying the pipeline code, redeploying, and praying you didn't break anything.

This is the fundamental problem: tight coupling between the thing that happens (document uploaded) and everything that needs to react to it. Event-driven architecture inverts this relationship — the producer announces what happened, and every interested consumer reacts independently.

---

## The Naive Approach and Why It Fails

**Naive approach: Direct function calls for every downstream effect.**

```python
def process_document(doc):
    text = extract_text(doc)
    chunks = chunk_text(text)
    embeddings = embed_chunks(chunks)
    write_to_vector_db(chunks, embeddings)
    update_search_metadata(doc)
    send_confirmation_email(doc.user)
    update_analytics(doc)
    recalculate_storage_quota(doc.user)
    trigger_compliance_scan(doc)
    notify_slack_admin(doc)
    # ... adding more here every month
```

This fails because:
1. **Coupling:** Every new downstream effect requires changing this function. Adding "send webhook to customer's integration" means modifying the ingestion code.
2. **Cascading failures:** If `notify_slack_admin()` throws an exception (Slack API down), the entire pipeline fails — including the embedding and indexing that were already completed. The user's document is in a half-processed state.
3. **Latency accumulation:** Each downstream call adds latency. 8 downstream calls × 200ms each = 1.6 seconds added to an already slow pipeline.
4. **No independent scaling:** The compliance scan takes 10 seconds. Everything else takes <200ms. But they all run on the same worker, so compliance scans slow down everything.

---

## The Real Mechanism

### Events vs Commands — The Fundamental Distinction

```
Command (imperative): "Send a confirmation email to Alice"
  - Directed at a specific service
  - Expects the receiver to do something specific
  - Sender knows about the receiver
  - Tight coupling

Event (declarative): "Document 42 was uploaded by Alice"
  - Announces what happened, doesn't say what to do about it
  - Any number of services can listen and react
  - Sender doesn't know who's listening
  - Loose coupling
```

This distinction matters: when your ingestion pipeline publishes "DocumentUploaded" events instead of calling specific services, adding a new downstream effect (webhook, compliance scan, analytics) requires zero changes to the producer. The new consumer subscribes to the event stream and starts receiving events. The producer is untouched.

### Queue vs Stream — The Critical Distinction

Module 14 introduced message queues. Event-driven architecture introduces **streams** — a fundamentally different model.

```
Queue (RabbitMQ, SQS):
  Message is CONSUMED and DELETED after processing.
  Each message goes to ONE consumer (competing consumers).
  No history: once processed, the message is gone.
  Use for: work distribution (process this job).

Stream (Kafka, Kinesis, Redpanda):
  Events are APPENDED to a durable, ordered log.
  Events are NOT deleted after consumption.
  Multiple consumers can read the SAME events independently.
  Each consumer tracks its own position (offset) in the log.
  Full history: events are retained for hours, days, or forever.
  Use for: event notification, replay, audit, analytics.
  
  ┌────────────────────────────────────────────────┐
  │  Topic: document-events                        │
  │                                                │
  │  offset 0: {type: "uploaded", doc: 42}         │
  │  offset 1: {type: "chunked",  doc: 42}         │
  │  offset 2: {type: "embedded", doc: 42}         │
  │  offset 3: {type: "indexed",  doc: 42}         │
  │  offset 4: {type: "uploaded", doc: 43}         │
  │                                                │
  │  Consumer A (embedding worker): at offset 2    │
  │  Consumer B (analytics):        at offset 4    │
  │  Consumer C (compliance):       at offset 1    │
  │                                                │
  │  Each consumer reads at its own pace.           │
  │  Slow consumers don't block fast ones.          │
  └────────────────────────────────────────────────┘
```

**Why Kafka's model is powerful:** Because events are retained and consumers track their own offsets, you can:
- **Replay events:** A new analytics pipeline can start from offset 0 and process the entire history.
- **Debug production:** Read the event log to see exactly what happened and in what order.
- **Add consumers without modifying producers:** Deploy a new compliance scanner that subscribes to the same topic. It immediately starts processing from the latest offset (or from the beginning, if it needs historical data).

### Event Sourcing — The Database as an Event Log

Instead of storing the current state ("user has $70"), store the events that produced the state:

```
Traditional (state-based):
  accounts table: {user: "Alice", balance: 70}
  
  Problem: How did Alice get $70? No history. If a bug set the wrong balance,
  you can't trace what happened.

Event sourced:
  events table:
    {event: "deposit",    amount: 100, balance_after: 100, time: T1}
    {event: "withdrawal", amount: 30,  balance_after: 70,  time: T2}
  
  Current state: replay all events → $100 - $30 = $70
  
  Benefits:
    - Full audit trail (critical for financial, legal, compliance)
    - Can rebuild state from scratch by replaying events
    - Can answer "what was the balance at time T1?" by replaying up to T1
    - Events are append-only (no updates, no deletes → simple, fast writes)
  
  Costs:
    - Reads are expensive (must replay all events to get current state)
    - Fix: maintain a materialized "current state" view, updated by events
    - Storage grows forever (every event is kept)
    - Schema evolution is hard (old events have old formats)
```

**When event sourcing is worth the complexity:** Financial systems (audit trail), collaborative editing (undo/redo), systems where "what happened" is as important as "what's the current state." When it's not worth it: most CRUD applications. A user profile that changes occasionally doesn't need an event log — just store the current state.

### CQRS — Command Query Responsibility Segregation

Separate the write model (optimized for writes) from the read model (optimized for reads):

```
Without CQRS:
  One database serves both reads and writes.
  Schema is a compromise: normalized enough for write integrity,
  denormalized enough for read performance.

With CQRS:
  ┌──────────┐    events    ┌──────────────┐
  │  Write   │ ──────────→  │  Read Model  │
  │  Model   │              │ (materialized │
  │ (events) │              │  views, search│
  │          │              │  indexes)     │
  └──────────┘              └──────────────┘
       ↑                          ↑
    Writes                     Reads
    (commands)              (queries)
  
  Write model: append-only event log (Kafka, PostgreSQL)
  Read model: whatever format is fastest for queries
    - Denormalized tables for API responses
    - Elasticsearch for full-text search
    - pgvector for similarity search
    - Redis for hot-path lookups
```

**The key insight:** The read model is a *projection* of the event stream. You can build multiple read models from the same events, each optimized for a different query pattern. If a read model becomes stale or corrupted, rebuild it by replaying the event stream from scratch.

**The cost:** The read model is eventually consistent with the write model. There's a lag between writing an event and it appearing in the read model. For most applications (RAG, search, analytics), this lag (milliseconds to seconds) is acceptable.

---

## Concrete Example From a Real System

**Illustrative: Event-Driven RAG Ingestion Pipeline**

```
Event-driven redesign of the pipeline from Module 14:

User uploads PDF → API publishes event: {type: "DocumentUploaded", doc_id: 42}

Subscribers (each reads independently, scales independently):

┌─────────────────────────────────────────────────────┐
│ Topic: document-events                               │
│                                                      │
│ Consumer Group A: ChunkingWorker                     │
│   Reads "DocumentUploaded" → extracts text, chunks  │
│   Publishes: {type: "DocumentChunked", chunks: [...]}│
│                                                      │
│ Consumer Group B: EmbeddingWorker                    │
│   Reads "DocumentChunked" → generates embeddings    │
│   Publishes: {type: "DocumentEmbedded", ...}        │
│                                                      │
│ Consumer Group C: IndexWriter                        │
│   Reads "DocumentEmbedded" → writes to pgvector     │
│   Publishes: {type: "DocumentIndexed"}              │
│                                                      │
│ Consumer Group D: NotificationService               │
│   Reads "DocumentIndexed" → sends email, webhook    │
│                                                      │
│ Consumer Group E: AnalyticsService                   │
│   Reads ALL events → updates dashboard metrics      │
│                                                      │
│ Consumer Group F: ComplianceScan (added 6 months later)
│   Reads "DocumentUploaded" → scans for PII          │
│   Added with ZERO changes to the producer            │
└─────────────────────────────────────────────────────┘
```

**Why this is better than the synchronous pipeline:**
- Adding ComplianceScanner required zero changes to the upload API.
- If the NotificationService crashes, chunking and embedding continue unaffected.
- EmbeddingWorker can scale to 10 pods while ChunkingWorker stays at 2 (they scale independently).
- The entire event history is retained — you can replay it to rebuild the search index from scratch.

---

## The Tradeoffs

| Pattern | Benefit | Cost |
|---------|---------|------|
| Event-driven (pub-sub) | Loose coupling, independent scaling, easy to add consumers | Harder to reason about (no linear flow), eventual consistency |
| Synchronous pipeline | Easy to understand, immediate consistency | Tight coupling, cascading failures, latency accumulation |
| Event sourcing | Full audit trail, replayable, rebuildable state | Storage growth, read complexity (need materialized views) |
| CQRS | Optimized read and write models independently | Two models to maintain, eventual consistency between them |
| Kafka-style log | Durable, replayable, multi-consumer | Operational complexity (partitions, offsets, retention) |

**The honest decision framework:**

```
When to use event-driven architecture:
  ✓ Multiple independent consumers need to react to the same event
  ✓ You're adding new consumers regularly (growing platform)
  ✓ Downstream processing needs to scale independently
  ✓ You need an audit trail or replay capability

When to use a simple synchronous pipeline:
  ✓ One producer, one consumer, one action
  ✓ Small team (< 5 engineers) maintaining everything
  ✓ You can accept the latency of sequential processing
  ✓ You won't need to add more consumers for 6+ months
  
Most teams should start synchronous and migrate to events when the 
coupling pain becomes real — not when they read about it in a blog post.
```

---

## How This Connects to Other Modules

- **Module 14** (Message Queues): Queues are the transport. Events are the semantic layer on top. This module extends Module 14 from "work distribution" to "system architecture."
- **Module 13** (Replication): Change Data Capture (CDC) publishes database changes as events. Your replication pipeline IS an event stream.
- **Module 16** (API Design): Event-driven APIs (webhooks) are the push equivalent of polling-based APIs.
- **Module 23** (Distributed Transactions): Sagas use events to coordinate multi-service operations without distributed transactions.
- **Module 25** (Observability): Event logs are the ultimate observability tool — they show exactly what happened, in order.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Know the difference between a queue and a stream (consumed-and-deleted vs durable log). Know events vs commands (declarative vs imperative). Know why event-driven decouples producers from consumers and why that matters when your system is growing. Know event sourcing exists and when it's justified (audit trails, replayability) vs overkill (CRUD apps). Know CQRS at a high level (separate read and write models). Don't memorize Kafka partition internals — you'll learn those when you're configuring Kafka.

**The AI-era connection:** Event-driven design becomes essential for ingestion pipelines the moment your pipeline has more than two stages. Document uploads → chunking → embedding → indexing is a natural event chain. Building this as a synchronous pipeline is fine for a prototype, but the moment you need to add metadata extraction, compliance scanning, or analytics, the synchronous pipeline becomes unmaintainable. The honest tradeoff: for a team of 2-3 engineers building a RAG MVP, a synchronous pipeline (Module 14's queue-based approach) is simpler and faster to ship. For a team of 10+ engineers building a platform where new consumers are added quarterly, event-driven with Kafka is the correct architecture. The wrong choice is starting with Kafka on day one with 2 engineers — you'll spend more time operating Kafka than building your product.

**Brutally honest advice:** The single most common over-engineering mistake I see in AI startups is adopting Kafka before they need it. Kafka is operationally expensive: partitions, consumer groups, offset management, retention policies, schema registries. A team that's shipping their first RAG product does not need Kafka. They need a simple message queue (SQS, Redis Streams, or even Postgres LISTEN/NOTIFY) and a synchronous pipeline. Adopt Kafka when you have: (a) multiple teams producing and consuming events, (b) event replay as a hard requirement, (c) a dedicated platform/infra engineer who can own Kafka operations. Until then, a queue is simpler, cheaper, and sufficient. Don't let "we might need replay someday" justify the operational complexity of Kafka on day one.

---

## Check Your Understanding

1. Your ingestion pipeline calls 6 downstream services synchronously. Service #4 (compliance scan) throws an exception. What happens to services 5 and 6? How does an event-driven architecture prevent this?

2. You add a new AnalyticsConsumer to your Kafka topic 6 months after launch. It needs to process all historical events. How does Kafka's log-based model support this? Could you do this with RabbitMQ?

3. Your event-sourced system has 10 million events for an account. To display the current balance, you need to replay all 10 million events. Why is this unacceptable in production? What is the standard solution?

4. Explain why CQRS is a natural fit for a RAG system where documents are written (ingested) infrequently but retrieved (searched) thousands of times per second.

5. Your team has 3 engineers building a RAG MVP. A senior engineer suggests using Kafka for the ingestion pipeline. The pipeline has one producer and one consumer. Argue for or against this decision, citing specific operational costs.
