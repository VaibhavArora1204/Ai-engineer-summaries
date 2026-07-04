# 06 — Load Balancing

## The Problem

You've horizontally scaled your application to 4 servers (Module 03). Users send requests to your domain. But your domain resolves to one IP address. All traffic hits Server 1. Servers 2, 3, and 4 sit idle. You've paid for 4x the capacity and gotten 1x the throughput.

You need something that sits in front of your servers and distributes incoming requests across them. That something is a load balancer, and it's the single piece of infrastructure that makes horizontal scaling actually work.

---

## The Naive Approach and Why It Fails

**Naive approach 1: DNS round-robin.** Configure your DNS to return a different server IP for each lookup. Client A gets 203.0.113.1, Client B gets 203.0.113.2, etc.

This "works" but fails in practice because:
- DNS is cached. Client A gets 203.0.113.1 and caches it for the TTL (often 300 seconds). Every request for the next 5 minutes goes to Server 1. If Server 1 goes down, Client A is stuck sending requests to a dead server for 5 minutes.
- No health checking. DNS doesn't know if a server is alive. It keeps returning dead servers' IPs.
- Uneven distribution. DNS round-robin doesn't account for request weight — a server processing a 10-second LLM call gets the same share as a server processing a 5ms health check.

**Naive approach 2: Client-side balancing.** The client knows about all servers and picks one randomly.

This works for internal service-to-service communication (gRPC clients often do this), but doesn't work for external clients (browsers, mobile apps) because you can't trust or control client behavior.

---

## The Real Mechanism

### What a Load Balancer Does

A load balancer is a server that:
1. Receives all incoming requests on a single IP/port
2. Selects a healthy backend server based on an algorithm
3. Forwards the request to that server
4. Returns the response to the client

The client talks to the load balancer's IP. It never knows which backend server handled the request. This is the abstraction that makes horizontal scaling invisible to clients.

```
Client → Load Balancer (public IP: 203.0.113.1)
                ├── Server A (private: 10.0.0.1)
                ├── Server B (private: 10.0.0.2)
                ├── Server C (private: 10.0.0.3)
                └── Server D (private: 10.0.0.4)
```

### L4 vs L7 Load Balancing

This is one of the most commonly asked distinctions and it maps directly to the OSI network layers:

**Layer 4 (Transport Layer — TCP/UDP):**
- Operates on TCP connections, not HTTP content
- Sees: source IP, destination IP, source port, destination port
- Does NOT see: HTTP headers, URL paths, cookies, request body
- Decision: based on connection metadata only
- Performance: extremely fast (no need to parse HTTP)
- Use case: high-throughput, protocol-agnostic balancing

```
L4 load balancer sees:
  "A TCP connection from 1.2.3.4:54321 to 203.0.113.1:443"
  
It picks Server B and forwards the entire TCP connection.
Every packet in this connection goes to Server B.
```

**Layer 7 (Application Layer — HTTP):**
- Terminates the HTTP connection (reads the full request)
- Sees: URL path, HTTP method, headers, cookies, request body
- Can make routing decisions based on content
- Can modify requests and responses (add headers, rewrite URLs)
- Performance: slower than L4 (must parse HTTP), but much more flexible
- Use case: content-based routing, SSL termination, API gateway

```
L7 load balancer sees:
  "GET /api/v2/chat HTTP/1.1
   Host: api.yourproduct.com
   Authorization: Bearer eyJ..."

It can route:
  /api/v1/* → legacy server pool
  /api/v2/* → new server pool
  /api/v2/chat → dedicated chat server pool (the slow LLM ones)
```

**For AI systems, L7 is almost always what you want** because you need content-based routing — different endpoints have wildly different latency profiles (a `/health` check is 1ms, a `/chat` endpoint is 5 seconds), and you probably want to route them to different backend pools.

### Load Balancing Algorithms

**Round Robin:** Requests go to servers in order: A, B, C, D, A, B, C, D...

```
Simple, fair when all requests are equal cost.
Fails when requests are NOT equal cost: if Server A is processing
a 10-second LLM call while Server B just finished a 5ms health check,
round robin sends the next request to Server A anyway — it doesn't
know Server A is busy.
```

**Weighted Round Robin:** Same as round robin, but servers have weights. Server A (weight 3) gets 3 requests for every 1 that Server B (weight 1) gets. Useful when servers have different capacities (e.g., one has a GPU, another doesn't).

**Least Connections:** Send the next request to the server with the fewest active connections.

```
Server A: 12 active connections
Server B: 3 active connections
Server C: 8 active connections

Next request → Server B (fewest connections)

This naturally accounts for slow requests: a server processing
a 10-second LLM call holds that connection open, so it accumulates
fewer requests while it's busy. This is a much better algorithm
for AI workloads than round robin.
```

**Weighted Least Connections:** Least connections with weights. The request goes to the server with the lowest ratio of `active_connections / weight`. Combines capacity awareness with load awareness.

**IP Hash:** Hash the client's IP address to determine the server. Same IP always goes to the same server.

```
server = hash(client_ip) % num_servers

Pro: session affinity without cookies — same client always hits same server
Con: if a server goes down, all its clients are redistributed
Con: uneven distribution if some IPs generate much more traffic than others
```

**Consistent Hashing:** A more sophisticated version of IP hash that minimizes redistribution when servers are added or removed. When a server is added, only ~1/N of requests move. When a server is removed, only its requests move. This is critical for cache-aware routing and will be covered in depth in Module 22.

### Health Checks

A load balancer must know which servers are alive. It does this with health checks:

```
Active health checks (load balancer → server):
  Every 5 seconds, send GET /health to each server.
  If a server fails 3 consecutive checks: mark it "unhealthy," stop sending traffic.
  If an unhealthy server passes 2 consecutive checks: mark it "healthy," resume traffic.

Passive health checks (observing real traffic):
  If a server returns 5xx errors for 50% of requests in a 30-second window:
  mark it "unhealthy."
  
Best practice: use BOTH. Active checks catch servers that are down.
Passive checks catch servers that are "up" but misbehaving.
```

**The deep health check:** A `/health` endpoint that returns 200 OK if the server process is running is not sufficient. A useful health check verifies the server can actually do its job:

```python
@app.get("/health")
async def health():
    # Shallow: just checks the process is running
    # return {"status": "ok"}
    
    # Deep: checks actual dependencies
    try:
        await db.execute("SELECT 1")          # database reachable?
        await redis.ping()                     # cache reachable?
        await vector_db.health()               # vector DB reachable?
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(
            status_code=503, 
            content={"status": "unhealthy", "reason": str(e)}
        )
```

### The Load Balancer's Own Failure Mode

The load balancer is itself a single point of failure. If it goes down, no traffic reaches any backend. The solution:

```
Active-Passive (common):
  Two load balancers: one active, one standby.
  They share a virtual IP (VIP) via protocols like VRRP.
  If the active LB fails, the standby takes over the VIP.
  Failover time: 1-5 seconds.

Active-Active (better, harder):
  Multiple load balancers, all serving traffic.
  DNS returns multiple LB IPs.
  More capacity, no single point of failure, but harder to coordinate.

Managed (what you should probably use):
  AWS ALB/NLB, GCP Cloud Load Balancing, Azure Load Balancer.
  The cloud provider handles redundancy. You don't think about LB failure.
  This is the right answer 95% of the time unless you have specific
  requirements that mandate self-managed infrastructure.
```

---

## Concrete Example From a Real System

**Illustrative — multi-model routing as load balancing:** A company runs a RAG product. They use three LLM providers: OpenAI (fast, expensive), Anthropic (high quality, medium price), and a self-hosted Llama model (slower, cheapest). They put an L7 load balancer in front with content-based routing:

```
Routing rules (L7 load balancer config):
  
  If request header X-Priority: low → route to self-hosted Llama pool
  If request header X-Priority: high → route to OpenAI pool
  If OpenAI pool health check fails → failover to Anthropic pool
  If all providers fail → return cached response (graceful degradation)

Weighted routing for cost optimization:
  OpenAI:     weight 2 (40% of traffic)
  Anthropic:  weight 2 (40% of traffic)  
  Self-hosted: weight 1 (20% of traffic)
```

This is load balancing wearing an AI costume. The algorithms (weighted routing, health checks, failover) are identical to what you'd use for routing across 4 identical web servers. The inputs are different: instead of CPU load, you're routing based on cost, latency, and model capability. But the mechanism is exactly the same.

---

## The Tradeoffs

| Algorithm | Best for | Fails when |
|-----------|----------|------------|
| Round Robin | Uniform, fast requests | Requests have wildly different latencies (AI workloads) |
| Least Connections | Mixed-latency requests (AI!) | All connections are long-lived (WebSockets) |
| IP Hash | Session affinity without cookies | Uneven client distribution, server addition/removal |
| Consistent Hashing | Cache-aware routing, minimal disruption on scaling | Overkill for stateless backends |
| Weighted variants | Heterogeneous backends (GPU vs CPU servers) | Weights are set manually and go stale |

| L4 vs L7 | L4 | L7 |
|-----------|----|----|
| Speed | Faster (no HTTP parsing) | Slower |
| Flexibility | None (can't route by URL/header) | Full (content-based routing) |
| TLS | Passes through (backend handles TLS) | Terminates TLS (offloads crypto from backends) |
| Use case | Raw throughput, database proxying | API routing, content-based decisions |

---

## How This Connects to Other Modules

- **Module 03** (Scalability) introduced horizontal scaling. This module is the mechanism that makes horizontal scaling work.
- **Module 02** (Networking) explained TLS cost. L7 load balancers terminate TLS, offloading crypto from application servers.
- **Module 07** (Caching) will benefit from consistent hashing — routing requests for the same cache key to the same server.
- **Module 18** (Service Communication) will cover circuit breakers and retries — complementary patterns to health-check-based routing.
- **Module 22** (Sharding) uses consistent hashing for data distribution — the same algorithm used here for request distribution.
- **Module 29** (Case Study: Rate Limiter) will need distributed rate limiting that accounts for multiple backends behind a load balancer.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Know L4 vs L7 cold — it comes up in every design conversation and every interview. Know least connections — it's the right default for AI workloads because it naturally adapts to slow requests. Know that the load balancer itself is a SPOF and the answer is "use a managed one" unless you have a specific reason not to. Everything else (the 8 other algorithms, VRRP protocol details, BGP anycast) is reference material you look up when you need it.

**The AI-era connection:** Multi-model routing is load balancing. This is one of the cleanest examples of "the same core concept wearing its 2026 costume." When your product routes requests across OpenAI, Anthropic, and a self-hosted model based on cost, latency, and quality requirements, you are doing weighted L7 load balancing with health checks. The load balancer config is where you encode your model routing strategy: which provider gets what share of traffic, what happens when a provider goes down, and how you failover. If you build this as custom Python code in your application, you're reimplementing a load balancer badly. Use the infrastructure that exists for this — it's been debugged for 20 years.

**Brutally honest advice:** The mistake I see from AI-background engineers is building model routing logic in application code — a big if/elif chain that picks a provider based on request parameters. This works at small scale and becomes unmaintainable at production scale because: (1) you can't change routing weights without redeploying your app, (2) you have no health checks — if OpenAI goes down, your if/elif keeps sending requests to it until you manually update the code, (3) you can't A/B test routing strategies without code changes. Use a load balancer or an API gateway (Kong, Envoy, even nginx with upstream blocks) for model routing. It's the same tool, solving the same problem, that web infrastructure engineers solved decades ago. Don't reinvent it.

---

## Check Your Understanding

1. You have 4 backend servers behind a round-robin load balancer. Three of them handle a `/health` endpoint (1ms each) and one handles a `/chat` endpoint that takes 5 seconds (LLM call). What problem emerges, and which algorithm fixes it?

2. Your load balancer terminates TLS (L7). Traffic between the load balancer and your backend servers is unencrypted HTTP. Is this a security problem? Under what circumstances is it acceptable, and when is it not?

3. You're building multi-model routing: 60% of requests go to OpenAI, 30% to Anthropic, 10% to self-hosted. OpenAI goes down. Describe what happens with (a) no health checks, (b) active health checks with a 30-second detection window.

4. Why is least-connections a better default than round-robin for a RAG API where request latency varies from 200ms (cache hit) to 8 seconds (full LLM generation)?

5. Your system has one load balancer with no redundancy. What's the maximum availability of your system, regardless of how many backend servers you have? What's the fix?
