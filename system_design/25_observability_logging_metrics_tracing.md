# 25 — Observability: Logging, Metrics, Tracing

## The Problem

Your RAG API has been running fine for 3 months. Today, users start reporting "the AI is slow." You check the server — CPU is at 30%, memory is fine, no errors in the logs. But p99 latency jumped from 4 seconds to 18 seconds.

Where is the bottleneck? Is it the embedding call? The vector search? The LLM generation? The database connection pool? A slow downstream dependency? You have no idea, because your system has 6 components in the request path and you're logging `print("request processed")` at the end.

This is the observability problem: you can't fix what you can't see. And you can't see into a distributed system by reading logs from one server.

Observability has three pillars, each serving a distinct purpose:
- **Logs** tell you *what happened* on a single machine.
- **Metrics** tell you *how the system is behaving* in aggregate.
- **Traces** tell you *what happened to a specific request* across multiple machines.

You need all three. They are not interchangeable.

---

## The Naive Approach and Why It Fails

**"I'll just add more print statements."**

```python
print(f"Request received: {request.id}")
print(f"Embedding took {embed_time}ms")
print(f"Vector search returned {len(results)} results")
print(f"LLM response generated in {llm_time}ms")
```

This fails at scale for three reasons:

1. **Volume:** At 500 requests/second, you generate thousands of log lines per second. Unstructured text logs are impossible to search, aggregate, or alert on. "Find all requests where the LLM took longer than 10 seconds" requires regex parsing of millions of lines.

2. **Distributed context:** The request starts at the API gateway, hits the embedding service, queries the vector database, calls the LLM, and returns through the gateway. Each service has its own logs on its own server. There's no thread connecting the log lines from different services for the same request.

3. **No aggregation:** Print statements tell you about individual events. They can't answer: "What is the average latency this hour? What percentage of requests are failing? Is the error rate increasing?"

---

## The Real Mechanism

### Pillar 1: Structured Logging

**The key upgrade from `print()`: structured logging.**

Instead of:
```
2024-01-15 10:23:45 ERROR: Failed to process request for user 123
```

Use:
```json
{
  "timestamp": "2024-01-15T10:23:45.123Z",
  "level": "ERROR",
  "service": "rag-api",
  "request_id": "req-abc-123",
  "trace_id": "trace-xyz-789",
  "user_id": 123,
  "action": "llm_generation",
  "error": "OpenAI API timeout after 30s",
  "latency_ms": 30000,
  "model": "gpt-4o",
  "token_count": 2500
}
```

Structured logs are JSON. Every field is queryable. You can now run: "Show me all ERROR logs from the `rag-api` service where `model = gpt-4o` and `latency_ms > 10000` in the last hour." This is impossible with unstructured text.

**Log levels matter:**
- `DEBUG`: Granular details for local development. Never enable in production at scale.
- `INFO`: Normal operations (request received, task completed). The default production level.
- `WARN`: Something unexpected but not broken (cache miss, retry triggered, slow query).
- `ERROR`: Something broke for this specific request (timeout, exception, invalid input).
- `FATAL`: The process is crashing. Page someone.

**The production rule:** Log at INFO by default. Use WARN for things that are worth investigating if they happen frequently. Use ERROR only for actual failures. If everything is ERROR, nothing is — alert fatigue is the silent killer of on-call engineers.

**Log aggregation systems:** You can't SSH into 50 servers and `grep` log files. You need centralized log aggregation:
- **ELK Stack:** Elasticsearch + Logstash + Kibana. Self-hosted, powerful, operationally heavy.
- **Loki:** Grafana's log aggregation system. Lighter than ELK, indexes labels (not full text).
- **Managed:** Datadog Logs, AWS CloudWatch Logs, Google Cloud Logging.

### Pillar 2: Metrics

Metrics are numerical measurements collected at regular intervals. They answer: "How is the system behaving right now, in aggregate?"

**The Four Golden Signals (from Google's SRE book):**

1. **Latency:** How long requests take. Track p50, p95, p99 (Module 05).
2. **Traffic:** How many requests per second.
3. **Errors:** What fraction of requests are failing (error rate).
4. **Saturation:** How full are your resources (CPU, memory, disk, connection pool, thread pool).

**Metric types:**
- **Counter:** A monotonically increasing number. "Total requests served: 1,234,567." You derive rates from counters (requests/second = counter delta / time delta).
- **Gauge:** A point-in-time measurement that can go up or down. "Current CPU usage: 45%." "Active database connections: 18."
- **Histogram:** A distribution of values. "Latency distribution: 50% under 200ms, 95% under 1s, 99% under 4s." Histograms are essential for latency because averages hide tail latency.

**Prometheus** is the industry standard for metrics collection. It works on a pull model: Prometheus scrapes your application's `/metrics` endpoint every 15 seconds. Your application exposes metrics in Prometheus format:

```
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="POST", endpoint="/chat", status="200"} 45123
http_requests_total{method="POST", endpoint="/chat", status="500"} 87

# HELP http_request_duration_seconds Request latency histogram
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{endpoint="/chat", le="0.5"} 12000
http_request_duration_seconds_bucket{endpoint="/chat", le="1.0"} 30000
http_request_duration_seconds_bucket{endpoint="/chat", le="5.0"} 44000
http_request_duration_seconds_bucket{endpoint="/chat", le="+Inf"} 45123
```

**Grafana** dashboards visualize Prometheus metrics. A standard production dashboard shows the four golden signals on one screen.

### Pillar 3: Distributed Tracing

Logs tell you what happened on one machine. Metrics tell you aggregate behavior. But when a single request passes through 6 services, neither logs nor metrics can tell you WHERE the request spent its time.

**Distributed tracing** follows a single request through every service it touches.

**Mechanism:**

1. When a request enters your system (e.g., hits the API gateway), a unique **Trace ID** is generated.
2. The Trace ID is attached to the request as an HTTP header (e.g., `X-Trace-Id: trace-abc-123`) and propagated to every downstream service call.
3. Each service records **spans** — named, timed segments of work within that service.
4. All spans with the same Trace ID are collected and assembled into a **trace** — a tree/waterfall showing exactly how the request flowed through the system and how long each step took.

**Example trace for a RAG request:**

```
Trace ID: trace-abc-123
├── [API Gateway] 4,200ms
│   ├── [Auth Service] 15ms — validate JWT token
│   ├── [RAG Service] 4,150ms
│   │   ├── [Embedding] 45ms — call local embedding model
│   │   ├── [Vector Search] 22ms — pgvector similarity search
│   │   ├── [Document Fetch] 8ms — retrieve full documents from Postgres
│   │   ├── [Prompt Construction] 3ms — format prompt template
│   │   └── [LLM Generation] 4,050ms — OpenAI GPT-4o API call
│   └── [Response Formatting] 12ms
```

Now you can see: the LLM generation took 4,050ms out of 4,200ms total. That's 96% of the latency. No amount of optimizing the vector search (22ms) will meaningfully improve the user experience. You need to either switch to a faster model, implement streaming, or cache frequent queries.

**Tracing tools:**
- **Jaeger:** Open-source, CNCF project. Full-featured distributed tracing.
- **Zipkin:** Open-source alternative. Simpler.
- **OpenTelemetry:** The industry standard library for instrumenting your code. It generates traces, metrics, and logs in a vendor-neutral format that can be exported to any backend (Jaeger, Datadog, Honeycomb).
- **Managed:** Datadog APM, AWS X-Ray, Google Cloud Trace.

---

## Concrete Example From a Real System

**Debugging a Production Latency Spike:**

Your RAG API's p99 latency jumped from 4s to 18s. Here's how the three pillars work together:

1. **Metrics (Grafana dashboard):** You see p99 latency spiked at 2:15 PM. Traffic volume is normal. Error rate is 0%. CPU is 30%. But the metric `db_connection_pool_active` jumped from 15 to 20 (the max). **Diagnosis: connection pool exhaustion.**

2. **Traces (Jaeger):** You pull a sample of slow traces from the 2:15 PM window. They all show: the `[LLM Generation]` span took 15 seconds instead of the usual 3 seconds. The `[DB Query]` span shows 12 seconds of *wait time* before the query even started — it was waiting for a free connection from the pool.

3. **Logs:** You filter structured logs for `trace_id = trace-abc-123`. You find: `"warn": "connection pool wait exceeded 10s, pool size: 20/20"`. And on the LLM span: `"info": "OpenAI latency spike, retry #2, backoff: 5000ms"`.

**Root cause:** OpenAI had a temporary latency spike. Each request held a database connection for the full duration of the LLM call (because the code retrieved documents, then called the LLM, then wrote the result — all within a single connection lease). When the LLM took 15s instead of 3s, 20 concurrent requests consumed all 20 connections. Subsequent requests queued, waiting for a free connection.

**Fix:** Release the database connection after document retrieval, BEFORE calling the LLM. Re-acquire a connection after the LLM responds to write the result. The database connection is held for milliseconds (document retrieval + result write) instead of seconds (the entire LLM call).

Without all three pillars working together, you might have spent hours guessing.

---

## The Tradeoffs

| Pillar | Answers | Storage Cost | Runtime Overhead |
|--------|---------|-------------|-----------------|
| Structured Logging | What happened, on which machine, why | High (verbose text, need retention policy) | Low-Medium |
| Metrics | Aggregate system behavior, trends, alerts | Low (numerical time series) | Very Low |
| Distributed Tracing | Per-request journey across services | Medium-High (one trace per request, sample in production) | Low-Medium |

**Sampling:** In production at 10,000 requests/second, tracing every request is prohibitively expensive. Most teams sample: trace 1% of requests randomly, plus 100% of requests that error or exceed a latency threshold. This gives you representative data without the storage cost.

---

## How This Connects to Other Modules

- **Module 05** (Reliability): SLIs (latency, availability, error rate) ARE metrics. Observability is how you measure whether you're meeting your SLOs.
- **Module 18** (Service Communication): Circuit breaker state changes, retry counts, and timeout events should all emit metrics and logs. Without observability on your resilience mechanisms, you can't tell if they're helping or hiding problems.
- **Module 19** (Service Discovery): Health checks are a form of observability — they continuously probe service health and feed into the service registry's routing decisions.
- **Module 25** feeds directly into **Module 31** (Multi-Agent Orchestration), where tracing non-deterministic execution paths becomes the hardest observability challenge in modern systems.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** The three pillars are all equally important in theory. In practice, if you're a small team (under 10 engineers), here's the priority:

1. **Metrics first.** Set up Prometheus + Grafana. Dashboard the four golden signals. Set up alerts for error rate > 1% and p99 latency > threshold. This takes 2-3 hours and gives you 70% of the value.
2. **Structured logging second.** Switch from `print()` to a structured logger (Python's `structlog`, Node's `pino`). Send logs to a centralized system. This makes debugging possible.
3. **Distributed tracing third.** Add OpenTelemetry instrumentation. This is the most valuable tool for diagnosing latency issues, but it requires instrumentation effort across all services.

Most teams do step 1 and stop. When their p99 spikes and they can't explain why, they skip to step 3 in a panic. Do all three proactively.

**The AI-era connection:** Tracing an agent with a non-deterministic execution path is a fundamentally harder problem than tracing a fixed microservice call graph. In a traditional microservice system, the trace is a predictable tree: API Gateway → Auth → User Service → Database. You can draw this on a whiteboard.

An agent's trace is non-deterministic. The model decides at runtime which tools to call, in what order, sometimes recursively, sometimes calling sub-agents that themselves make tool calls. The trace might look like:
```
[Agent] → [SearchTool] → [Agent thinks] → [CodeExecutionTool] → [Agent thinks] 
→ [SearchTool again] → [SubAgent] → [SubAgent calls WriteTool] → [Agent synthesizes]
```

This breaks most traditional tracing UIs that assume a fixed call graph. You need tracing that can handle:
- **Dynamic depth:** The trace tree depth is unbounded (agent calls sub-agent calls sub-sub-agent).
- **Loops:** The agent might call the same tool 5 times.
- **Decision spans:** You need to trace not just tool calls but the LLM's *reasoning steps* — why did it decide to call SearchTool instead of CodeTool?
- **Cost attribution:** Each span should carry a `token_count` and `cost_usd` field so you can see exactly where money is being spent.

Tools like LangSmith, Arize Phoenix, and Weights & Biases Weave are building tracing UIs specifically for this problem. They understand that the trace is a DAG (directed acyclic graph), not a tree, and that "reasoning" is a first-class span type alongside "HTTP call."

**Brutally honest advice:** Most teams' observability stack was built assuming deterministic request paths. They bolt an agent on top and discover that their Grafana dashboards show average latency increasing, but they can't explain why because the agent's behavior varies wildly between requests. One request makes 2 tool calls and finishes in 3 seconds. The next makes 12 tool calls and takes 45 seconds. The "average" is meaningless.

For agent systems, you need to instrument at the STEP level, not the REQUEST level. Track: number of tool calls per request (histogram), tokens consumed per request (histogram), cost per request (histogram), and reasoning loops per request (counter). These metrics don't exist in traditional web observability — you have to define and instrument them yourself.

---

## Check Your Understanding

1. Your structured logs show 50 ERROR entries per minute, all with the message "OpenAI API timeout." Your metrics dashboard shows the error rate is 0.5%. Your trace for one of these errors shows the LLM span taking 30 seconds before timing out. Explain how each pillar (logs, metrics, tracing) contributed a different piece of the diagnosis that the other two could not have provided alone.

2. You're running at 10,000 requests/second and sampling 1% of traces. A bug affects only 0.01% of requests (1 per second). What is the probability that your sampling captures one of these buggy requests in a given second? How would you adjust your sampling strategy?

3. An AI agent makes 8 tool calls during a single user request. The total latency is 25 seconds. Your trace shows that 3 of the tool calls were redundant (the agent searched for the same information twice and called a code executor unnecessarily). Where does this trace data need to be sent for it to be useful for improving the agent, and what team action does it enable?

4. Your Grafana dashboard shows that `db_connection_pool_active` is consistently at 19 out of 20 maximum connections. What is about to happen, and which metric would give you early warning before it hits 20?

5. Why can't you simply increase the log level to DEBUG in production to get more visibility? What are the concrete costs?

---

### Answers

1. **Answer:** Logs told you the specific error message and that it was an OpenAI timeout (the "what"). Metrics told you the error rate (0.5%) and that it started at a specific time — answering "how widespread" and "when" — without requiring you to count log lines. Tracing showed you the exact position in the request flow where time was spent (the LLM span specifically, not the embedding or vector search), answering "where in the request path." Without metrics, you can't tell if it's 5 errors or 5,000. Without traces, you can't tell if the timeout is at the LLM layer or the database layer. Without logs, you don't have the specific error message.

2. **Answer:** At 1% sampling of 10,000 req/s, you sample 100 requests/second. The bug affects 1 request/second (0.01%). The probability of capturing a buggy request in any given second is 1% (you sample 100 out of 10,000, and 1 of the 10,000 is buggy). You'd capture roughly 1 buggy trace per 100 seconds (~36 per hour). To improve: implement tail-based sampling — sample 100% of requests that error or exceed a latency threshold. This guarantees you capture every buggy request while keeping overall sampling low.

3. **Answer:** The trace data needs to be sent to an agent evaluation/observability platform (LangSmith, Arize, or custom tooling) where engineers can review it. The actionable insight: the prompt or tool descriptions need refinement so the agent doesn't make redundant calls. This is prompt engineering informed by production traces — the trace data tells you exactly WHERE the agent's reasoning went wrong, enabling targeted prompt improvements. The 3 redundant calls also represent wasted LLM tokens and latency that could be eliminated.

4. **Answer:** Connection pool exhaustion is imminent. The next traffic spike (or a single slow query holding a connection longer than usual) will push it to 20/20. New requests will queue, waiting for a free connection, causing latency spikes. The early warning metric is `db_connection_pool_wait_time` (time requests spend waiting for a free connection). This metric starts rising before the pool hits capacity, giving you a leading indicator to increase the pool size or optimize connection usage before users are impacted.

5. **Answer:** DEBUG logging in production generates 10-100x more log volume than INFO. Concrete costs: (1) Storage: at 10,000 req/s, DEBUG might produce 1GB+ of logs per minute, costing hundreds/thousands of dollars per month in log aggregation storage. (2) CPU/IO: writing that volume of logs consumes significant CPU cycles and disk I/O on the application server, potentially degrading request latency. (3) Signal-to-noise: finding an actual error in a sea of DEBUG messages becomes nearly impossible — the important information is buried. The correct approach: keep production at INFO, and enable DEBUG temporarily for a specific service or request path using dynamic log level configuration when actively debugging an issue.
