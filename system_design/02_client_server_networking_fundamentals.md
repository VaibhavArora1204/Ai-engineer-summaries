# 02 — Client-Server and Networking Fundamentals

## The Problem

Your FastAPI server works perfectly on localhost. You deploy it to a cloud VM. Users start complaining about mysterious latency. Not the kind where your code is slow — your application logs show the function completed in 15ms. But the user's browser says the request took 350ms. Where did the other 335ms go?

That 335ms is the network. And until you understand what "the network" actually *does* between your client and your server, you will misdiagnose performance problems for your entire career. You'll optimize your Python code, swap out your ORM, upgrade your database, and nothing will change — because the bottleneck was never in your application. It was in DNS resolution, TCP handshakes, TLS negotiation, or keep-alive misconfigurations. These are invisible to application-level profiling.

---

## The Naive Approach and Why It Fails

The naive approach is to treat the network as a magic pipe. Request goes in one end, response comes out the other. If it's slow, the application must be slow.

This fails because the network is not a pipe — it's a multi-step protocol negotiation that happens *before your application code even runs*. On the very first request from a new client:

```
Client wants to reach api.yourproduct.com

Step 1: DNS Resolution           ~20-100ms
Step 2: TCP Handshake             ~1 RTT (round-trip time, 20-150ms depending on distance)
Step 3: TLS Handshake             ~1-2 RTTs (another 20-300ms)
Step 4: HTTP Request/Response     ~1 RTT + server processing time

Total before your code runs: 60-550ms of pure network overhead
```

On a warm, keep-alive connection, steps 1-3 are skipped. On a cold connection (first request, or after a connection was closed), all of them hit. This is why your p99 has a "weird floor" — it's the cold-connection overhead that you can't optimize away in your application.

---

## The Real Mechanism

### DNS Resolution: Translating Names to Addresses

When a client requests `api.yourproduct.com`, the first thing that happens is not a connection to your server. It's a DNS lookup:

```
1. Client checks local DNS cache (OS-level)        → cache hit? done in <1ms
2. Client asks configured DNS resolver (e.g., 8.8.8.8) → cache hit there? done in ~5ms
3. Resolver asks root nameserver → "who handles .com?"
4. Resolver asks .com TLD server → "who handles yourproduct.com?"
5. Resolver asks yourproduct.com's authoritative nameserver → "what's the IP of api.yourproduct.com?"
6. Answer propagates back: 203.0.113.42

Total uncached: 50-200ms (multiple round trips across the internet)
Cached: <5ms
TTL: the authoritative server says "cache this for N seconds"
```

**Why this matters for system design:** DNS is the first point where load balancing happens. When you configure your domain to point to multiple IPs (or use a DNS-based load balancer like AWS Route 53), DNS resolution is what decides which server the client talks to. Understanding DNS TTL is understanding how fast you can redirect traffic during an outage.

### TCP: The Connection

TCP is the reliable delivery protocol underneath HTTP. Before a single byte of your API request is sent, the client and server must complete a three-way handshake:

```
Client → Server:  SYN           "I want to connect"
Server → Client:  SYN-ACK       "Acknowledged, I'm ready"
Client → Server:  ACK           "Acknowledged, let's go"

Cost: 1 round trip (1 RTT)
Latency: depends on distance. Same datacenter: <1ms. Cross-continent: 50-150ms.
```

**What a connection costs the server:** Every open TCP connection consumes:
- A file descriptor (Linux default limit: 1024 per process, tunable to ~1M)
- Kernel memory for the socket buffer (~4-8KB send buffer + ~4-8KB receive buffer)
- A slot in the connection tracking table

At 10,000 concurrent connections, you're consuming ~100MB of kernel memory just for socket buffers. At 100,000 connections, you need to tune your OS (increase `ulimit`, tune `net.core.somaxconn`, increase the file descriptor limit). This is real operational work that most application developers never think about until connections start getting refused.

**TCP vs UDP — when each matters:**

| TCP | UDP |
|-----|-----|
| Reliable delivery (retransmits lost packets) | Fire-and-forget (no retransmission) |
| Ordered (packets arrive in sequence) | Unordered (packets may arrive out of order) |
| Connection-oriented (handshake first) | Connectionless (send immediately) |
| Higher latency (handshake + acknowledgment overhead) | Lower latency (no handshake) |
| HTTP, database connections, API calls | DNS queries, video streaming, real-time gaming |

For API traffic (which is what you'll deal with 99% of the time building AI products), TCP is the answer. UDP matters for DNS (the initial lookup) and for some real-time streaming scenarios, but you won't be choosing between them at the application level — your HTTP library uses TCP underneath.

### TLS: The Encryption Layer

HTTPS = HTTP + TLS. The TLS handshake happens after the TCP handshake and before any HTTP data is sent:

```
TLS 1.2 (older, still common):
  Client → Server:  ClientHello     (supported cipher suites, random number)
  Server → Client:  ServerHello     (chosen cipher suite, certificate)
  Client → Server:  Key exchange    (encrypted pre-master secret)
  Server → Client:  Finished        (handshake complete)
  Cost: 2 round trips

TLS 1.3 (modern, should be your default):
  Client → Server:  ClientHello + key share
  Server → Client:  ServerHello + key share + certificate + finished
  Client → Server:  Finished
  Cost: 1 round trip

TLS 1.3 with 0-RTT resumption (returning client):
  Client → Server:  ClientHello + early data (the actual HTTP request!)
  Cost: 0 additional round trips
```

**At scale, TLS handshake cost is real:** If your server handles 10,000 new connections per second and each TLS 1.2 handshake costs 2ms of CPU time (asymmetric crypto is expensive), you're spending 20 CPU-seconds per second just on handshakes — nearly an entire core dedicated to TLS. This is why:
- TLS 1.3 matters (halves the handshake)
- Connection reuse (HTTP keep-alive) matters enormously
- TLS termination at the load balancer (Module 06) is standard practice — offload the crypto from your application servers

### HTTP: The Application Protocol

HTTP sits on top of TCP+TLS. The key versions:

**HTTP/1.1:** One request at a time per connection (head-of-line blocking). To send 6 parallel requests, the browser opens 6 TCP connections. Each connection costs a TCP handshake + TLS handshake. Workaround: browsers open 6 concurrent connections per domain.

**HTTP/2:** Multiple requests multiplexed over a single connection. One TCP+TLS handshake, then many requests flow simultaneously as "streams." This dramatically reduces connection overhead. Server push (the server sends resources before the client asks) is theoretically useful but rarely used in practice for APIs.

**HTTP/3:** Uses QUIC (which runs over UDP instead of TCP), eliminating TCP's head-of-line blocking entirely. The handshake combines the transport and TLS handshake into a single round trip. Adoption is growing but not universal.

**For your API servers:** HTTP/2 is the practical choice today. It eliminates the per-request connection overhead and is supported by all modern reverse proxies (nginx, Caddy, cloud load balancers). Your application code doesn't need to change — HTTP/2 is handled by the infrastructure in front of your app.

### Keep-Alive and Connection Reuse

This is where theory meets "why is my p99 weird":

```
Without keep-alive (HTTP/1.0 default):
  Every request: DNS + TCP + TLS + HTTP = 60-550ms overhead
  
With keep-alive (HTTP/1.1+ default):
  First request:  DNS + TCP + TLS + HTTP = 60-550ms
  Second request:  HTTP only = 1-50ms (connection already open)
  Third request:   HTTP only = 1-50ms
  ...
  After idle timeout (e.g., 60s of no traffic): connection closed
  Next request after timeout: full handshake again
```

**The p99 latency floor mystery:** Your p99 latency has a floor of, say, 300ms. Your application processes every request in 15ms. What's happening: ~1% of your requests hit cold connections (new clients, or keep-alive timeout expired). Those requests pay the full DNS + TCP + TLS overhead. That's your p99 floor. You can't fix it by optimizing your application — you fix it by:
1. Increasing your keep-alive timeout (so connections stay open longer)
2. Using connection pooling on the client side
3. Using HTTP/2 (fewer connections needed, each stays open longer)

---

## Concrete Example From a Real System

**Illustrative (realistic but not from a specific company):** A team building a RAG API on FastAPI deployed behind nginx. Their p50 latency was 800ms (expected — that's the LLM response time). Their p99 was 3.2 seconds. They spent two weeks optimizing their retrieval pipeline, their embedding model, their prompt template. Nothing changed the p99.

The actual problem: nginx had `keepalive_timeout 5s` (default). Their clients (a frontend app) had bursty traffic — users would interact, then read for 10 seconds, then interact again. Every burst after a 5-second pause triggered new TCP+TLS connections. Changing `keepalive_timeout 65s` and enabling HTTP/2 dropped the p99 from 3.2s to 1.1s — a 3x improvement from a two-line nginx config change, zero application code changes.

---

## The Tradeoffs

| Decision | Benefit | Cost |
|----------|---------|------|
| Long keep-alive timeout | Fewer cold connections, lower p99 | More connections held open, more server memory |
| HTTP/2 | Multiplexed requests, fewer connections | Slightly more complex debugging (binary protocol) |
| TLS 1.3 | Faster handshake (1 RTT vs 2) | Requires modern clients (universal by now) |
| TLS termination at load balancer | Offloads crypto from app servers | Traffic between LB and app server is unencrypted (acceptable within a VPC, not across the internet) |
| Connection pooling (client-side) | Reuses connections, avoids handshake per request | Pool exhaustion if misconfigured (too few connections for the concurrency) |

---

## How This Connects to Other Modules

- **Module 01** described the scaling walls. This module explains the physics *underneath* those walls — every request, no matter how fast your application, pays the network cost described here.
- **Module 05** (Reliability) will formalize latency and tail latency. The p99 floor mystery described here is a concrete example of why tail latency matters.
- **Module 06** (Load Balancing) operates at these layers — L4 (TCP level) vs L7 (HTTP level). Understanding this module makes the L4/L7 distinction intuitive.
- **Module 09** (Databases) will cover connection pooling in depth. The same keep-alive and connection-reuse principles apply between your application and your database.
- **Module 18** (Service Communication) will revisit timeouts, retries, and connection management between services. Everything here is the foundation for that.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** DNS, TCP handshakes, TLS — you need to know these exist and what they cost, but you'll rarely debug them directly. What you WILL use constantly is the understanding of **connection cost and reuse**. The keep-alive timeout misconfiguration story I told above? I've seen it in production three times. The connection pool exhaustion story from Module 01? That's the same physics — connections cost resources, and AI systems hold them open 100x longer than classic web apps. Internalize this: **every open connection costs memory, and every new connection costs latency.** That's the gut-level truth from this module.

**The AI-era connection:** Here's where this module isn't just theoretical background — it's survival knowledge for your RAG work. When your API calls an LLM provider (OpenAI, Anthropic), that call is going over the public internet. That means full DNS + TCP + TLS on the first call. The LLM response takes 2-8 seconds, during which your server is holding a TCP connection open to the provider AND a TCP connection open to your client. If you have 50 concurrent users, you have 50 outbound connections to the provider and 50 inbound connections from users. Your server's connection table has 100 entries, your client's keep-alive timeout is battling your provider's keep-alive timeout, and if either side closes early, the next request pays the full handshake cost again. Understanding this connection lifecycle is the difference between a RAG API that "works on my machine" and one that survives 50 concurrent users.

**Brutally honest advice:** I know networking feels like "infrastructure stuff" that someone else handles. It's not. As an AI engineer building products, you will personally hit a latency problem that traces back to a misconfigured timeout, a keep-alive setting, or a connection pool size. When you do, you'll need to read nginx or cloud load balancer docs, understand what `keepalive_timeout`, `proxy_read_timeout`, and `upstream keepalive` actually mean, and make a change. If you skipped this module, that debugging session will take days instead of hours. The most common mistake I see from ML/AI engineers is assuming latency is always about the model or the application code. Often, it's about the wire.

---

## Check Your Understanding

1. A client makes its first ever request to your API at `api.example.com` over HTTPS using TLS 1.3. How many round trips occur before the server even sees the HTTP request? List each step.

2. Your server has 4 workers, each with a connection pool of 10 to Postgres. Your RAG requests hold each database connection for 3 seconds (while waiting for the LLM). What's the maximum number of concurrent RAG requests your server can handle before connection pool exhaustion? What's the fix?

3. Your nginx reverse proxy has `keepalive_timeout 5s`. Your users interact with your chat UI in bursts with 8-second gaps between messages. Explain why your p99 latency is higher than expected and what single config change fixes it.

4. Why does HTTP/2 reduce connection-related latency more dramatically than simply enabling keep-alive on HTTP/1.1? What problem does HTTP/1.1 keep-alive NOT solve that HTTP/2 does?

5. Your LLM API endpoint calls OpenAI's API. Your server holds an outbound connection to OpenAI for 5 seconds per request. At 200 concurrent users, how many outbound connections does your server maintain? What OS-level limit might you hit, and how do you check it?
