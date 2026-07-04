# 14 — Message Queues and Asynchronous Processing

## The Problem

Your user uploads a PDF to your RAG system. Your API server needs to: (1) save the file to object storage, (2) extract text from the PDF, (3) chunk the text, (4) generate embeddings for each chunk, (5) write chunks + embeddings to the database, (6) update the search index. This takes 30-120 seconds.

If you do all of this synchronously (inside the HTTP request handler), the user's browser sits on a loading spinner for 2 minutes. Your API server is holding one HTTP connection and one database connection open the entire time. If 10 users upload PDFs simultaneously, you've consumed 10 connections for 2 minutes each. Your server can't handle any other requests. This is the problem that message queues solve: decoupling "accept the request" from "do the work."

---

## The Naive Approach and Why It Fails

**Naive approach: "Just process it in the background with a thread."**

```python
@app.post("/upload")
async def upload_document(file):
    save_to_s3(file)
    # Launch processing in a background thread
    threading.Thread(target=process_document, args=(file,)).start()
    return {"status": "processing"}  # Return immediately
```

This works on your laptop. It fails in production because:

1. **No durability:** If the server crashes or restarts during processing, the work is lost. There is no record that the document needs to be processed. The user's upload vanishes.
2. **No retry logic:** If step 4 (embedding generation) fails because the OpenAI API is temporarily down, the entire pipeline fails with no automatic retry.
3. **No load management:** All 10 uploads spawn 10 threads, all competing for CPU and making concurrent API calls. Your embedding API rate limit is 100 RPM; 10 threads each calling it concurrently may exceed the limit, causing cascading failures.
4. **No visibility:** You can't see which documents are processing, which failed, or how far along they are. There's no queue depth metric, no processing time metric, no dead letter queue for failures.

The fix: write a message to a durable queue ("process document X"), return 200 to the user immediately, and have a separate worker process read from the queue and do the work. If the worker crashes, the message stays in the queue and another worker picks it up.

---

## The Real Mechanism

### What a Message Queue Does

A message queue is a durable buffer between producers (things that create work) and consumers (things that do work):

```
Producer (API Server)           Consumer (Worker)
  │                                  │
  │ "Process document X"             │
  ├────────────→ ┌────────────┐      │
  │              │   Queue    │ ────→│ Reads message
  │              │            │      │ Processes document
  │              │  [msg1]    │      │ ACKs message (removes from queue)
  │              │  [msg2]    │      │
  │              │  [msg3]    │      │
  │              └────────────┘      │
  │                                  │
  Returns 200 immediately          Takes 30-120 seconds
```

**The key properties:**
- **Durable:** Messages survive server restarts. They're written to disk, not held in memory.
- **Decoupled:** Producers and consumers don't know about each other. Producers don't wait for consumers. Consumers don't know who produced the message.
- **Buffered:** If consumers are busy, messages wait in the queue. The queue absorbs traffic spikes.
- **Competing consumers:** Multiple workers can read from the same queue. The queue ensures each message is delivered to exactly one worker.

### Delivery Guarantees — The Three Options and Why Exactly-Once Is Hard

**At-Most-Once:**
```
Queue sends message to consumer.
Queue immediately deletes the message.
If consumer crashes before processing → message is lost.

Simple. Fast. Acceptable for: metrics, analytics, non-critical notifications.
Unacceptable for: payments, document processing, anything with real consequences.
```

**At-Least-Once (The Standard):**
```
Queue sends message to consumer.
Consumer processes the message.
Consumer sends ACK (acknowledgment) to queue.
Queue deletes the message only after receiving ACK.

If consumer crashes before ACK → queue re-delivers the message to another consumer.
Problem: Consumer might receive the SAME message twice (processed once, crashed 
before ACK, re-delivered, processed again).

Solution: Make your processing IDEMPOTENT (Module 24).
  processing "embed document X" twice should produce the same result,
  not duplicate embeddings.
```

**Exactly-Once (Extremely Hard):**
```
Each message is processed exactly once. No loss, no duplicates.

Why it's hard: The ACK itself can fail.
  Consumer processes message.
  Consumer sends ACK.
  Network drops the ACK.
  Queue doesn't receive ACK → re-delivers.
  Consumer processes again → DUPLICATE.
  
  To prevent this, you need distributed transactions between the queue 
  and the consumer's data store — which is the distributed transaction 
  problem (Module 23) and it's brutally hard.

Reality: Most "exactly-once" systems are actually "at-least-once with 
idempotent consumers." Kafka's exactly-once semantics (EOS) are scoped 
to Kafka-to-Kafka processing, not to external side effects.
```

### Queue vs Pub-Sub — Two Different Communication Patterns

**Queue (Point-to-Point):**
```
One message → one consumer.
Multiple consumers compete: each message goes to exactly one.
Use for: work distribution (process this document, send this email).

Producer → Queue → Consumer A gets msg1
                 → Consumer B gets msg2
                 → Consumer C gets msg3
```

**Pub-Sub (Publish-Subscribe):**
```
One message → ALL subscribers.
Every subscriber gets every message.
Use for: event notification (order placed → inventory, shipping, email all notified).

Producer → Topic → Subscriber A gets msg1
                 → Subscriber B gets msg1
                 → Subscriber C gets msg1
```

Most modern message systems (Kafka, RabbitMQ, SQS+SNS) support both patterns. RabbitMQ has exchanges for pub-sub. Kafka has consumer groups for competing consumers.

### Dead Letter Queues — What Happens When Processing Fails

A message fails processing. The consumer retries. It fails again. And again. After N retries, the message is moved to a **dead letter queue (DLQ)** — a separate queue for messages that couldn't be processed.

```
Main Queue → Consumer attempts processing
  Attempt 1: Fails (OpenAI API timeout)
  Attempt 2: Fails (OpenAI API still down)
  Attempt 3: Fails (max retries exceeded)
  → Message moved to Dead Letter Queue

DLQ collects failed messages for:
  1. Manual inspection (what went wrong?)
  2. Replay after fixing the issue (re-process all DLQ messages)
  3. Alerting (if DLQ depth > 0, page someone)
```

Without a DLQ, failed messages either block the queue forever (head-of-line blocking) or are silently dropped (data loss). Neither is acceptable.

### Backpressure — When Producers Are Faster Than Consumers

If producers add messages faster than consumers process them, the queue grows without bound. This is backpressure, and it must be managed:

```
Backpressure strategies:

1. Drop new messages (lossy):
   Queue has a max size. When full, new messages are rejected.
   Acceptable for: metrics, telemetry. Not for: user requests.

2. Block the producer (flow control):
   When the queue is full, the producer's send() call blocks until space opens.
   This propagates backpressure to the client.
   Acceptable for: internal pipelines. Not for: user-facing APIs (causes timeouts).

3. Scale consumers:
   Auto-scale the number of workers based on queue depth.
   Queue depth > 1000 → add 2 more workers.
   Queue depth < 100 → remove workers.
   The right answer for most production systems.

4. Rate-limit the producer:
   Accept messages but throttle the producer's rate.
   "You can submit 10 documents/minute. Queue 11th for later."
```

---

## Concrete Example From a Real System

**Illustrative: RAG Document Ingestion Pipeline**

A RAG platform ingests documents uploaded by users. The pipeline:

```
┌───────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  API      │    │  Upload  │    │  Chunk   │    │  Embed   │    │  Index   │
│  Server   │───→│  Queue   │───→│  Worker  │───→│  Queue   │───→│  Worker  │
│           │    │          │    │          │    │          │    │          │
│ Returns   │    │ "process │    │ Extracts │    │ "embed   │    │ Writes   │
│ 202       │    │  doc X"  │    │ text,    │    │ chunks   │    │ to       │
│ Accepted  │    │          │    │ creates  │    │ [c1,c2]" │    │ pgvector │
│           │    │          │    │ chunks   │    │          │    │          │
└───────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                      │
                                                      ▼
                                               ┌──────────┐
                                               │   DLQ    │
                                               │(failures)│
                                               └──────────┘

Key design decisions:
  1. Two separate queues: Upload→Chunk and Chunk→Embed are decoupled.
     If the embedding API goes down, chunking continues (doesn't block).
  
  2. Embed Queue batches: Instead of one API call per chunk, worker
     batches 50 chunks into one embedding API call (90% cost reduction).
  
  3. Idempotent workers: Re-processing a chunk produces the same embedding.
     At-least-once delivery is safe.
  
  4. DLQ alerts: If DLQ depth > 0, Slack alert → engineer inspects.
  
  5. Backpressure: If Embed Queue depth > 10,000, auto-scale embed workers
     from 2 → 8 pods. Scale back down when depth < 500.
```

**User experience:**
```
User uploads PDF → 202 Accepted (200ms)
Status endpoint: GET /documents/{id}/status → "processing" / "ready" / "failed"
Webhook notification when ready (optional)
```

---

## The Tradeoffs

| Decision | Benefit | Cost |
|----------|---------|------|
| Sync processing (no queue) | Simple, immediate result | Blocks request, connection exhaustion, no retry |
| Async with queue | Fast response, durable, retries, scalable | Added complexity, eventual consistency, monitoring needed |
| At-most-once delivery | Fastest, simplest | Data loss on failure |
| At-least-once delivery | No data loss | Possible duplicates (must be idempotent) |
| Exactly-once delivery | No loss, no duplicates | Extremely complex, often not truly achievable |
| Single queue | Simple | Bottleneck if different stages have different throughput |
| Multi-stage pipeline | Each stage scales independently | More queues to monitor, more complex |

---

## How This Connects to Other Modules

- **Module 09** (Databases): Queues prevent connection pool exhaustion by decoupling long-running work from HTTP requests.
- **Module 15** (Event-Driven Architecture): Queues are the transport mechanism for event-driven systems. Event sourcing and CQRS build on top of message passing.
- **Module 16** (API Design): Async APIs (return 202 Accepted + status endpoint) are built on top of message queues.
- **Module 18** (Service Communication): Queues are async service communication. The alternative to sync HTTP calls between services.
- **Module 24** (Idempotency): At-least-once delivery requires idempotent consumers. This is not optional.
- **Module 25** (Observability): Queue depth, processing time, DLQ depth, and consumer lag are critical metrics for queue-based systems.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Know the three delivery guarantees (at-most-once, at-least-once, exactly-once) and why exactly-once is effectively impossible for external side effects. Know the difference between queue (competing consumers, one message → one worker) and pub-sub (broadcast, one message → all subscribers). Know dead letter queues — they're the safety net for failed processing, and every production queue needs one. Know backpressure — what happens when producers outpace consumers, and how auto-scaling consumers based on queue depth is the standard fix. Everything else (AMQP protocol details, RabbitMQ exchange types, Kafka partition internals) is reference material for when you're configuring a specific system.

**The AI-era connection:** Agent tool calls and multi-step pipelines are a queueing problem in disguise. When an agent calls a tool (web search, code execution, database query), the call is either synchronous (agent blocks until result) or asynchronous (agent fires the call and checks later). Most agent frameworks hide this queueing decision from you — every tool call is synchronous by default. This works fine until you need to scale past toy traffic. If your agent orchestrator is processing 100 concurrent user requests, each making 5 tool calls that take 2-10 seconds each, you have 500 concurrent blocking calls. This is the same problem that message queues solve in traditional systems: decouple "request the work" from "wait for the result."

The brutal honest take: most agent frameworks make every tool call synchronous because it's simpler to reason about. This is fine at 10 concurrent users and catastrophic at 1,000. If you're building an agent system that needs to handle real production traffic, you will eventually rebuild the tool-call layer as a queue-based system where tool calls are dispatched to a queue, workers execute them, and results are returned asynchronously. Better to know this is coming than to be surprised when your agent platform falls over at its first traffic spike.

**Brutally honest advice:** The most common queue anti-pattern I see is: queue the work but poll for the result. The API server sends "process document X" to the queue and returns 202. The client polls `GET /documents/X/status` every 2 seconds. At 1,000 concurrent uploads, that's 500 polling requests/second hitting your API server — potentially more load than the original synchronous processing would have generated. The fix: use webhooks (push notification when done) or WebSockets (Module 26) for real-time status updates. Polling is acceptable for simple cases but doesn't scale.

---

## Check Your Understanding

1. Your user uploads a document. Your API server processes it synchronously (30 seconds). What happens to your server's connection pool when 20 users upload simultaneously? How does a message queue fix this?

2. Your embedding worker crashes after generating embeddings but before writing them to the database. With at-least-once delivery, what happens? Why must your write operation be idempotent?

3. You use at-most-once delivery for your document processing queue. A worker crashes after processing a document but before the ACK. What happens to that document? Why is this unacceptable for user-uploaded content?

4. Your Embed Queue depth is growing at 100 messages/minute, but workers are only processing 60 messages/minute. What is this condition called? Name two strategies to handle it, and which is preferred for a production system.

5. Explain why "exactly-once delivery" is effectively impossible when the consumer has external side effects (like calling an LLM API). What is the practical alternative, and what property must the consumer have?
