# Layer 6: Monitoring, Logging, Observability

> The difference between "my app is running" and "my app is working."

**The point:** Your app will break in production. The question is whether you find out from your monitoring or from an angry user. Observability is the set of tools and practices that let you answer "what is my app doing right now?" and "what went wrong 3 hours ago?" without guessing.

---

## 6.1 — The Three Pillars

Observability has three pillars. Each answers a different question:

| Pillar | What It Is | Question It Answers |
|--------|-----------|---------------------|
| **Logs** | Timestamped text records of events | "What happened?" — the narrative |
| **Metrics** | Numbers over time | "How much/how many?" — the summary |
| **Traces** | The path of a single request through your system | "Where did the time go?" — the story of one request |

You need all three. Logs without metrics = you can debug individual incidents but can't see trends. Metrics without logs = you see something is wrong but can't figure out what. Traces without either = you can follow a request but can't see the big picture.

---

## 6.2 — Logging — Not print()

**print() is not logging.** It's unstructured, has no severity level, no timestamp, no request context, and gets lost in the noise.

### Structured logging:

```python
import structlog

logger = structlog.get_logger()

# BAD — unstructured
print(f"User {user_id} asked: {query}")

# GOOD — structured, queryable, has context
logger.info(
    "chat_request_received",
    user_id=user_id,
    query_length=len(query),
    model="gpt-4",
    endpoint="/api/chat"
)
```

**Output:**
```json
{
  "event": "chat_request_received",
  "user_id": "u_123",
  "query_length": 45,
  "model": "gpt-4",
  "endpoint": "/api/chat",
  "timestamp": "2026-07-13T00:15:23Z",
  "level": "info"
}
```

**Why structured matters:** When you have 10,000 requests per hour, you need to query your logs:
- "Show me all ERROR logs from the last hour" → filter by level
- "Show me all requests from user u_123" → filter by user_id
- "Show me all requests where latency > 5s" → filter by latency field
- "How many requests used gpt-4 vs gpt-4-mini today?" → aggregate by model

With `print()`, you're grepping through unstructured text. With structured logging, you query JSON fields. At scale, the first is impossible and the second takes milliseconds.

### Log levels — what they mean operationally:

| Level | When To Use | Example |
|-------|------------|---------|
| **DEBUG** | Development only. Extremely verbose. NEVER in production at scale | Variable values, function entry/exit |
| **INFO** | Normal operation milestones | Request received, response sent, user action |
| **WARNING** | Something is degraded but not broken | Retry succeeded, rate limit approaching, fallback triggered |
| **ERROR** | Something broke for this request | Unhandled exception, API call failed, timeout |
| **CRITICAL** | System-level failure | Database unreachable, out of memory, can't start |

**Decision rule:** In production, log at INFO and above. DEBUG produces so much data it will cost you real money in log storage and make finding real issues harder.

**Failure modes:**
- Only ERROR logging → you can debug crashes but can't trace what happened before the crash (no INFO breadcrumbs)
- DEBUG in production → log storage costs $100/month, and real errors are buried in noise
- Logging sensitive data → user queries, API keys, PII in logs → compliance violation, security breach. Sanitize before logging
- No request ID in logs → when a user reports "the app gave me a wrong answer," you can't find which log entries belong to their request

### Request ID — correlating logs:

```python
import uuid
from fastapi import Request

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    # Bind to structlog context — all logs in this request will include it
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    structlog.contextvars.unbind_contextvars("request_id")
    return response
```

Now every log from a single request shares the same `request_id`. When a user reports a problem, you ask for the request ID (returned in the response header) and can pull the complete story of what happened.

---

## 6.3 — Metrics — Numbers That Tell You If Things Are OK

### The Four Golden Signals (Google SRE):

Every service should track these four things. If you track nothing else, track these:

| Signal | What It Measures | Example for AI App |
|--------|-----------------|-------------------|
| **Latency** | How long requests take | p50=800ms, p95=3s, p99=8s |
| **Traffic** | How many requests | 150 requests/minute |
| **Errors** | What fraction of requests fail | 2.3% error rate |
| **Saturation** | How "full" your system is | 78% CPU, 85% memory, 18/20 DB connections |

### Percentile latency — not averages:

```
Request latencies: [100ms, 120ms, 110ms, 130ms, 8000ms]

Average: 1692ms   ← meaningless, one outlier skews everything
p50: 120ms        ← half of users experience this or less
p95: 8000ms       ← 5% of users wait 8 seconds
p99: 8000ms       ← 1% worst case
```

**Average latency is a lie.** If your average is 200ms but p99 is 10s, 1% of users are having a terrible experience and your average hides it. Always track p50, p95, p99.

**For AI apps specifically, also track:**
- Token usage per request (cost)
- LLM API latency separately from your app's total latency
- Retrieval latency (for RAG)
- Cache hit rate (if caching LLM responses)
- Fallback trigger rate (how often your fallback model/cache is used)

### Implementing basic metrics in Python:

```python
import time
from prometheus_client import Counter, Histogram, start_http_server

# Define metrics
REQUEST_COUNT = Counter(
    'app_requests_total',
    'Total requests',
    ['endpoint', 'status', 'model']
)

REQUEST_LATENCY = Histogram(
    'app_request_latency_seconds',
    'Request latency',
    ['endpoint'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

TOKEN_USAGE = Counter(
    'app_token_usage_total',
    'Total tokens used',
    ['model', 'type']  # type: prompt or completion
)

@app.post("/api/chat")
async def chat(request: ChatRequest):
    start = time.time()
    try:
        response = await get_llm_response(request)
        REQUEST_COUNT.labels(
            endpoint="/api/chat",
            status="200",
            model=request.model
        ).inc()
        TOKEN_USAGE.labels(
            model=request.model,
            type="prompt"
        ).inc(response.usage.prompt_tokens)
        TOKEN_USAGE.labels(
            model=request.model,
            type="completion"
        ).inc(response.usage.completion_tokens)
        return response
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/api/chat",
            status="500",
            model=request.model
        ).inc()
        raise
    finally:
        REQUEST_LATENCY.labels(endpoint="/api/chat").observe(time.time() - start)
```

---

## 6.4 — Traces — Following a Request Through Your System

For a RAG app, a single user request might flow through:

```
User Request
├── [50ms]   Parse & validate input
├── [200ms]  Generate embedding (OpenAI embeddings API)
├── [80ms]   Vector search (pgvector/Pinecone)
├── [30ms]   Fetch full documents from DB
├── [20ms]   Build prompt with retrieved context
├── [1500ms] LLM API call (GPT-4)
├── [10ms]   Parse and format response
└── [5ms]    Return response
Total: ~1895ms
```

Without tracing, if a user says "the app is slow," you don't know which step is the bottleneck. With tracing, you see exactly where the time went.

### OpenTelemetry — the standard:

```python
from opentelemetry import trace

tracer = trace.get_tracer("myapp")

async def handle_chat(query: str):
    with tracer.start_as_current_span("handle_chat") as span:
        span.set_attribute("query_length", len(query))

        with tracer.start_as_current_span("embed_query"):
            embedding = await embed(query)

        with tracer.start_as_current_span("vector_search"):
            results = await search(embedding)

        with tracer.start_as_current_span("llm_call") as llm_span:
            response = await call_llm(query, results)
            llm_span.set_attribute("model", "gpt-4")
            llm_span.set_attribute("tokens", response.usage.total_tokens)

        return response
```

This creates a **trace** — a tree of **spans** showing exactly what happened during this request. You can visualize this in Jaeger, Grafana Tempo, or Datadog APM.

**For your stage:** OpenTelemetry is the right investment but it has setup overhead. If you're just starting, structlog with timing measurements (log how long each step takes) gives you 80% of the value for 20% of the effort.

---

## 6.5 — Health Checks — Is Your App Actually Alive?

A health check is an endpoint that your platform hits to determine if your app is healthy:

```python
@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

**This health check is too shallow.** It returns 200 even if your database is down, your OpenAI key is expired, or your vector store is unreachable. A shallow health check that lies is worse than no health check — it makes the platform think your app is fine when it's broken.

### Deep health check:

```python
@app.get("/health")
async def health_check():
    checks = {}

    # Check database
    try:
        await db.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # Check OpenAI (optional — don't burn tokens, just verify key works)
    try:
        # Use a cheap call — list models, not a completion
        await openai_client.models.list()
        checks["openai"] = "ok"
    except Exception as e:
        checks["openai"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    return JSONResponse(
        content={"status": "healthy" if all_ok else "degraded", "checks": checks},
        status_code=status_code
    )
```

**Two types of health checks:**
- **Liveness**: "Is the process alive?" → simple, always return 200 unless crashed. Platform uses this to restart dead processes
- **Readiness**: "Can this instance handle traffic?" → deep check. Platform uses this to route or not route traffic to this instance

On Kubernetes, these are separate endpoints. On PaaS, one `/health` usually serves both purposes.

**Failure modes:**
- Health check takes too long (>5s) → platform thinks app is unresponsive → kills it → restarts → check is slow again → restart loop
- Health check calls OpenAI with a real completion → burns tokens on every check (every 30s = 2880 calls/day = $$$)
- Health check doesn't check critical dependencies → returns 200 while DB is down → traffic routes to broken instance → users get 500s

---

## 6.6 — Alerting — Knowing Before the User Tells You

Monitoring without alerting is a dashboard you look at once, then never again. Alerting turns monitoring into operational awareness.

### What to alert on (and what NOT to):

**Alert on these (wake you up):**
- Error rate > 5% for more than 3 minutes
- p95 latency > 10s for more than 5 minutes
- Health check failing
- 0 requests for 10 minutes (during expected traffic hours) — app is probably down
- Disk > 90% full

**Don't alert on these (they create noise):**
- Single request failure (normal, happens)
- CPU spike (transient, usually recovers)
- Warning-level log entries
- Individual 429s (rate limiting working as intended)

**The #1 alerting failure mode: alert fatigue.** Too many alerts → you ignore them all → you miss the real incident. Every alert must be actionable. If you get an alert and the correct response is "do nothing," delete that alert.

### Tools by stage:

| Stage | Tool | What It Does | Cost |
|-------|------|-------------|------|
| Starting out | Sentry | Error tracking, stack traces, issue grouping | Free tier covers most side projects |
| Growing | Better Stack (formerly Logtail) | Logs + uptime monitoring + alerting | Free tier |
| Production | Grafana Cloud | Metrics, logs, traces, dashboards, alerting | Free for small scale |
| Funded/Scale | Datadog | Everything: metrics, logs, traces, APM, alerts | Expensive ($15-25/host/month) |

**For you right now:** Sentry (free) for error tracking. It's 10 minutes to set up and catches every unhandled exception with full context. That alone puts you ahead of 90% of side projects.

```python
# Sentry setup — literally this simple
import sentry_sdk
sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], traces_sample_rate=0.1)
# That's it. Unhandled exceptions are now auto-reported with stack trace,
# request data, user context, breadcrumbs
```

---

## 6.7 — AI-Specific Observability

Standard web observability covers "is my app up and responding?" AI observability covers "is my app responding *correctly*?"

### The AI observability gap:

```
Traditional app:  App works → correct output     ← binary, easy to monitor
                  App crashes → error, you know   ← obvious failure

AI/LLM app:      App works → output LOOKS correct but is actually wrong
                  App works → output quality silently degrades over time
                  App works → costs silently increase
                  ← NONE of these trigger traditional alerts
```

### What to track for LLM apps:

**1. Full request trace (log every LLM interaction):**
```json
{
  "request_id": "req_abc123",
  "timestamp": "2026-07-13T00:15:23Z",
  "user_id": "u_456",
  "input_query": "How do I deploy to Render?",
  "retrieved_context": ["doc_1: ...", "doc_2: ..."],
  "retrieval_scores": [0.89, 0.72],
  "final_prompt": "Based on the following context...",
  "model": "gpt-4",
  "raw_output": "To deploy to Render, you need to...",
  "processed_output": "To deploy to Render...",
  "prompt_tokens": 1200,
  "completion_tokens": 340,
  "latency_ms": 2100,
  "cost_usd": 0.052,
  "format_valid": true
}
```

**2. Quality metrics to track over time:**
- Format compliance rate: % of responses that match expected structure
- Retrieval hit rate: % of queries where top-k results score above relevance threshold
- Fallback trigger rate: % of requests that fell back to a smaller model or cached response
- Average response length: sudden changes indicate prompt regression
- User feedback rate: thumbs up/down if you have it

**3. Cost attribution:**
```python
# Tag every LLM call with context for cost tracking
cost_per_1k_tokens = {"gpt-4": 0.03, "gpt-4-mini": 0.00015}

# In your LLM wrapper:
logger.info(
    "llm_call_completed",
    model=model,
    prompt_tokens=usage.prompt_tokens,
    completion_tokens=usage.completion_tokens,
    cost_usd=(usage.prompt_tokens * cost_per_1k_tokens[model] / 1000) +
             (usage.completion_tokens * cost_per_1k_tokens[model] * 3 / 1000),
    feature="chat",      # which feature triggered this
    user_tier="free"      # what tier is this user
)
```

Now you can answer: "Our chat feature costs $12/day, and 40% of that is from free-tier users."

**4. Drift detection (periodic eval runs):**
```python
# Run daily or weekly as a cron job or scheduled CI pipeline
async def run_drift_check():
    golden_set = load_golden_set("eval/golden_prompts.jsonl")
    scores = []
    for item in golden_set:
        response = await call_your_app(item["query"])
        score = evaluate(response, item["expected"])
        scores.append(score)

    avg_score = sum(scores) / len(scores)
    if avg_score < THRESHOLD:
        alert(f"Quality drift detected: score {avg_score:.2f} < {THRESHOLD}")
```

This catches: corpus going stale, embedding model updates, upstream model behavior changes, prompt regressions that passed the initial eval but degrade over time.

---

## 6.8 — AIOps — What It Actually Is

Since you asked: AIOps is not a skill you learn. It's a feature set in existing monitoring tools:

| AIOps Feature | What It Does | Tool That Has It |
|--------------|-------------|-----------------|
| Anomaly detection | Learns normal metric patterns, alerts on deviation | Datadog, Grafana ML |
| Log pattern recognition | Groups similar log lines, surfaces unusual patterns | Datadog, Elastic |
| Alert correlation | Groups related alerts into one incident (instead of 50 alerts for one root cause) | PagerDuty, Datadog |
| Root cause suggestion | "This spike correlates with deployment at 2:15pm" | Datadog, New Relic |
| Noise reduction | Filters out known-benign alerts | PagerDuty AIOps |

**When you'd use this:** When you have enough data and alerts that manual triage is overwhelming (typically 50+ microservices, hundreds of alerts/day). At your stage, if you have more alerts than you can manually handle, you have too many alerts — fix your alert rules, don't buy an AIOps product.

**Bottom line:** AIOps is a checkbox for enterprise sales decks. Don't spend time on it. Build good basic alerting first. If you outgrow it, the tools will be there.

---

## Checkpoint Scenario

> Your RAG app has been running for 2 weeks. No errors in Sentry. Health check returns 200. Metrics show stable latency, stable traffic. By all dashboards, everything looks healthy.
>
> Then a user emails: "Your app has been giving me wrong answers for the past week. It used to find relevant documents but now it just makes things up."
>
> You check: the app IS working. LLM calls succeed. No errors. Latency is fine. But retrieval results are garbage — the top-3 retrieved documents have nothing to do with the query.

**Questions:**
1. Why didn't any of your existing monitoring catch this?
2. What specific metric or check, if you had built it, would have caught this a week ago?
3. Name two possible root causes for retrieval quality silently degrading.

---

## Build Task

1. Add `structlog` to a Python project with structured JSON output
2. Add a request ID middleware
3. Create a `/health` endpoint that checks at least one external dependency
4. Set up Sentry free tier — trigger a test exception, verify it appears in the Sentry dashboard
5. Add timing logs to your LLM call (log how long the API call takes, how many tokens it used)
