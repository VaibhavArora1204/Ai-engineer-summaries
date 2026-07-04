# 18 — Service Communication Patterns

## The Problem

You've split your monolith into services (Module 17). The embedding module is now the Embedding Service. The search module is the Search Service. They used to communicate via function calls — instant, reliable, type-checked. Now they communicate over the network.

The network is fundamentally unreliable. Packets get dropped. DNS lookups fail. TCP connections hang. Servers crash mid-response. Timeouts fire before responses arrive. A function call either succeeds or throws an exception. A network call can succeed, fail, hang indefinitely, succeed slowly, succeed but return corrupted data, or fail silently. Every service-to-service call is a bet that the network will behave, and in production, it frequently doesn't.

This module is the engineering playbook for making network calls between services survivable. If your product uses LLM APIs (OpenAI, Anthropic, any external provider), this is directly relevant to you — every LLM API call is a service-to-service call with all the same failure modes.

---

## The Naive Approach and Why It Fails

**Naive approach: call the service and hope it works.**

```python
def generate_embedding(text):
    response = requests.post("http://embedding-service/embed", json={"text": text})
    return response.json()["vector"]
```

This fails in production because:

1. **No timeout.** If the embedding service hangs (thread pool exhausted, GC pause), your request waits forever. The calling service's thread is blocked indefinitely. Block enough threads → your calling service is dead too.
2. **No retry logic.** A transient network blip returns a 500. Your code treats it as a permanent failure and returns an error to the user, even though retrying 1 second later would succeed.
3. **No circuit breaker.** The embedding service is down. Your service sends 1,000 requests/second to a dead endpoint. Each request hangs for 30 seconds (TCP timeout). You now have 30,000 blocked threads. Your service falls over. The failure has cascaded from the embedding service to your service.
4. **No backoff.** The embedding service recovers from a temporary overload. Your service retries all failed requests immediately. The flood of retries overwhelms the recovering service, and it goes down again. This is a self-inflicted thundering herd.

---

## The Real Mechanism

### Timeouts — The First Line of Defense

Every network call must have a timeout. Without one, a hung dependency can block your service indefinitely.

```python
# BAD: No timeout. Will hang forever if embedding service is unresponsive.
response = requests.post("http://embedding-service/embed", json=data)

# GOOD: Connection timeout (5s) + Read timeout (30s)
response = requests.post(
    "http://embedding-service/embed",
    json=data,
    timeout=(5, 30)  # (connect_timeout, read_timeout)
)

# Connection timeout: How long to wait for the TCP connection to establish.
#   If the server is unreachable (wrong IP, firewall, crashed), fail fast.
#   5 seconds is generous. Some teams use 1-2 seconds.

# Read timeout: How long to wait for the response after connection is established.
#   For an LLM call that takes 5-30 seconds, this must be longer.
#   For a database query that should take <100ms, 2 seconds is generous.
```

**The AI-era timeout problem:** LLM API calls take 2-30 seconds. Traditional web service calls take 10-100ms. If your default timeout is 5 seconds (common for web services), every LLM call will timeout. If your default timeout is 60 seconds (to accommodate LLMs), a hung non-LLM call will block for 60 seconds before failing. Solution: different timeout budgets for different dependency types.

```python
TIMEOUTS = {
    "embedding_service": (5, 60),   # Embedding generation can take 60s
    "auth_service": (2, 5),          # Auth checks should be instant
    "vector_search": (2, 10),        # Vector search should be fast
    "llm_generation": (5, 120),      # LLM generation can take 2 minutes
}
```

### Retries with Exponential Backoff and Jitter

When a call fails, retry — but not immediately and not indefinitely.

```python
import random
import time

def call_with_retry(func, max_retries=3, base_delay=1.0):
    for attempt in range(max_retries + 1):
        try:
            return func()
        except (ConnectionError, TimeoutError, HTTPError) as e:
            if attempt == max_retries:
                raise  # Give up after max retries
            
            # Exponential backoff: 1s, 2s, 4s
            delay = base_delay * (2 ** attempt)
            
            # Jitter: randomize to prevent thundering herd
            jittered_delay = delay * (0.5 + random.random())
            
            print(f"Attempt {attempt + 1} failed. Retrying in {jittered_delay:.1f}s")
            time.sleep(jittered_delay)
```

**Why exponential backoff:** If a service is overloaded, retrying immediately adds more load. Exponential backoff gives the service time to recover. Each retry waits longer: 1s, 2s, 4s, 8s...

**Why jitter:** Without jitter, if 1,000 requests all fail at the same time, they all retry after exactly 1 second — creating a synchronized thundering herd. Jitter randomizes the retry timing so retries are spread out: some retry after 0.5s, some after 1.3s, some after 1.8s.

**What NOT to retry:**
```
Retry:     5xx (server error), timeout, connection refused (transient)
Don't retry: 400 (bad request), 401 (unauthorized), 404 (not found) (permanent)
             — retrying a 400 will get a 400 every time. It's a bug, not a blip.

Special case: 429 (rate limited)
  Retry, but respect the Retry-After header.
  Don't use your own backoff — use the server's stated delay.
```

**The AI-era retry trap:** An LLM API call costs $0.50 in tokens. It fails with a 500. You retry. The retry also fails. You retry again. Each retry costs another $0.50. After 3 retries: $2.00 spent on a request that will never succeed. LLM retries must be cost-aware: budget-cap the total cost of retries, not just the count.

### Circuit Breakers — Preventing Cascading Failures

A circuit breaker prevents your service from sending requests to a dependency that is known to be down. It is the single most important pattern in this module.

```
Circuit breaker states:

  CLOSED (normal operation):
    All requests flow through to the dependency.
    The circuit breaker monitors: how many recent requests failed?
    
    If failure rate > threshold (e.g., 50% of last 20 requests):
      → Trip to OPEN
    
  OPEN (dependency is down, don't send traffic):
    All requests are immediately rejected (fail fast, no waiting).
    Return a fallback response or error.
    
    After a timeout period (e.g., 30 seconds):
      → Move to HALF-OPEN
    
  HALF-OPEN (testing if dependency has recovered):
    Allow ONE request through to the dependency.
    
    If it succeeds:
      → Close the circuit (resume normal traffic)
    
    If it fails:
      → Reopen the circuit (dependency is still down, wait longer)
```

**Why this matters for AI systems:**

```
Without circuit breaker:
  OpenAI API goes down for 5 minutes.
  Your service sends 1,000 requests/minute to a dead endpoint.
  Each request hangs for 30 seconds (TCP timeout).
  Your thread pool fills with 30,000 blocked threads.
  YOUR service crashes — even though OpenAI was the one that failed.
  Now your users can't access ANY feature, not just AI-powered ones.
  This is a cascading failure.

With circuit breaker:
  OpenAI API goes down.
  First 10 requests fail (50% failure rate in last 20 requests).
  Circuit trips to OPEN.
  Next 990 requests are immediately rejected (no waiting, no hanging threads).
  Your service stays alive. Non-AI features keep working.
  After 30 seconds, circuit goes to HALF-OPEN, tries one request.
  OpenAI is back → circuit closes → resume normal traffic.
```

### The Bulkhead Pattern — Isolation of Failure Domains

Named after ship bulkheads that prevent a leak in one compartment from flooding the entire vessel:

```
Without bulkhead:
  Your service has one thread pool (size: 100).
  50 threads are waiting on the slow LLM service (30s timeout each).
  50 threads remaining for ALL other operations.
  One more slow LLM request → thread pool exhausted.
  Auth checks, health checks, fast DB queries — all blocked.

With bulkhead:
  Separate thread pools per dependency:
  ┌─────────────────────────────────────────────────┐
  │  LLM calls:     pool of 20 threads              │
  │  DB queries:    pool of 30 threads               │
  │  Auth checks:   pool of 10 threads               │
  │  Search calls:  pool of 20 threads               │
  │  General:       pool of 20 threads               │
  └─────────────────────────────────────────────────┘
  
  LLM service hangs → 20 LLM threads blocked.
  DB queries, auth, search: unaffected (their thread pools are separate).
```

### Fallback Patterns — Graceful Degradation

When a dependency is down (circuit open), don't just return an error. Return a degraded but useful response:

```python
def get_embedding(text):
    try:
        return embedding_service.embed(text)  # Primary path
    except CircuitOpenError:
        # Fallback 1: Try a different provider
        try:
            return backup_embedding_service.embed(text)
        except:
            pass
        
        # Fallback 2: Return a cached embedding (stale but functional)
        cached = redis.get(f"embedding:{hash(text)}")
        if cached:
            return cached
        
        # Fallback 3: Return a degraded response
        return {"error": "embedding_unavailable", "can_retry_at": time.time() + 30}
```

For AI systems, the fallback chain is critical:
- Primary: OpenAI → Fallback: Anthropic → Fallback: Self-hosted model → Fallback: Cached response → Fallback: Graceful error

---

## Concrete Example From a Real System

**Illustrative: Resilient RAG Pipeline with Circuit Breakers**

```
User query → API Server
  │
  ├─ Auth check (auth-service, circuit breaker, 2s timeout)
  │   Fallback: cached auth token (valid for 5 min)
  │
  ├─ Embedding (embedding-service, circuit breaker, 30s timeout)
  │   Fallback: OpenAI direct → Anthropic → cached embedding
  │
  ├─ Vector search (pgvector, circuit breaker, 5s timeout)
  │   Fallback: keyword search (Postgres full-text, always available)
  │
  └─ LLM generation (llm-service, circuit breaker, 120s timeout)
      Fallback: smaller model → cached answer → "AI unavailable, 
      here are the relevant document sections:"
      
Key insight: The system degrades gracefully at each step.
If the LLM is down, users still get relevant document chunks.
If vector search is down, they get keyword search results.
If the embedding service is down, they get cached embeddings.
The system is never fully "down" — it's just progressively less capable.
```

---

## The Tradeoffs

| Pattern | Benefit | Cost |
|---------|---------|------|
| Timeouts | Prevents indefinite hangs | Must be tuned per dependency (too short = false failures, too long = slow cascades) |
| Retries | Recovers from transient failures | Amplifies load if not backed off; wastes money on expensive API calls |
| Exponential backoff | Gives failing service time to recover | Increases latency for retried requests |
| Jitter | Prevents thundering herd | Adds randomness to latency |
| Circuit breaker | Prevents cascading failures, fast failure | Adds complexity, requires tuning (thresholds, timeout periods) |
| Bulkhead | Isolates failure domains | More thread pools to manage, possible under-utilization |
| Fallback | Graceful degradation, better UX | Fallback logic adds complexity, fallback quality may not be acceptable |

---

## How This Connects to Other Modules

- **Module 06** (Load Balancing): Health checks in load balancers are a form of circuit breaker — they stop routing to unhealthy backends.
- **Module 14** (Message Queues): Async communication via queues avoids many of these failure modes (no hanging connections, no cascading failures). The tradeoff: eventual consistency.
- **Module 16** (API Design): Retry behavior depends on HTTP status codes (retry 5xx, don't retry 4xx).
- **Module 17** (Microservices): These patterns are the cost of splitting a monolith. Function calls don't need circuit breakers.
- **Module 19** (Service Discovery): Services must be discoverable before they can be called. Service discovery determines HOW you find the service endpoint.
- **Module 24** (Idempotency): Retries require idempotent operations. If `POST /charge` is retried, you must not double-charge.
- **Module 25** (Observability): Circuit breaker state, retry rate, and timeout rate are critical observability metrics.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Know circuit breakers cold — the three states (closed, open, half-open), what triggers each transition, and why they prevent cascading failures. Know retries with exponential backoff and jitter — not just the concept, but why each component is necessary (backoff: give the service time; jitter: prevent thundering herd). Know timeouts and why they must be set per dependency. Know the bulkhead pattern conceptually. These four patterns come up in every system design interview that involves microservices or external API calls. If you can draw the circuit breaker state machine and explain when it opens and how it tests recovery, you've passed this module.

**The AI-era connection:** This is THE module for AI-era systems. An LLM API call is exactly the kind of slow, occasionally-failing, expensive dependency that circuit breakers and bulkheads exist for. The brutal honest take: most people retry a failed LLM call with zero backoff or jitter, accidentally creating a self-inflicted thundering herd against the provider the moment it has a bad minute. I have seen teams bring OpenAI's API to its knees (for their own rate limit) by retrying 10,000 failed requests simultaneously when a brief outage recovered. The fix is simple: exponential backoff + jitter + circuit breaker. But most AI engineers implement none of these because they've never built a system that needed them before — they came from ML backgrounds where the "API" was a local function call.

**Brutally honest advice:** The most dangerous AI-era anti-pattern is "naked retries on expensive calls." An LLM call costs $0.50. It fails. You retry 3 times with no backoff. Each retry also fails (the service is down, not just busy). You've spent $2.00 on nothing. Now multiply by 1,000 concurrent requests. You've burned $2,000 in 30 seconds on retries to a dead service. The fix: (1) circuit breaker (stop sending requests after N failures), (2) cost-aware retry budgets (max total retry cost per request, not just max retry count), (3) fallback to a cheaper/self-hosted model when the primary is down. The fallback chain (primary provider → secondary provider → self-hosted → cached response → graceful error) is the production pattern that separates reliable AI products from brittle ones.

---

## Check Your Understanding

1. Your service calls OpenAI's API. It hangs for 60 seconds and then times out. Meanwhile, 59 more requests arrive and also start waiting. What is this called (the pattern of one failure blocking many requests)? Which two patterns prevent it?

2. OpenAI has a brief outage (30 seconds). Without circuit breakers, your service sends 500 requests/second to a dead endpoint. Each hangs for 30 seconds. How many threads are blocked after 30 seconds? With a circuit breaker that trips after 10 failures, how many threads are blocked?

3. Your retry policy retries failed LLM calls 3 times with 0 delay. 1,000 requests fail simultaneously due to a rate limit. What happens when all 1,000 requests retry at the same instant? What two modifications to the retry policy prevent this?

4. Your service calls 4 dependencies: auth (fast), DB (fast), embedding (slow), LLM (very slow). Without bulkheads, explain how a slow LLM can make auth checks fail. With bulkheads, why is auth unaffected?

5. Design a fallback chain for a RAG system's LLM generation step: primary model (Claude) → fallback 1 → fallback 2 → fallback 3. For each fallback level, specify what the user sees and what the quality tradeoff is.
