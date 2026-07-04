# 03 — Scalability: Vertical vs Horizontal

## The Problem

Your RAG API is running on one server. Traffic doubled last month. You have two options: buy a bigger machine, or add another machine. Both sound simple. Both have consequences that will shape every architectural decision you make for the next two years. And the choice is not as obvious as "always go horizontal" — despite what most blog posts will tell you.

---

## The Naive Approach and Why It Fails

The naive approach is to just pick one without understanding the mechanics.

**Naive vertical:** "Just get a bigger machine." You upgrade from 8GB RAM / 4 cores to 64GB RAM / 32 cores. Everything works, no code changes. You feel smart. Then you hit the ceiling — there is no 1TB RAM / 256 core machine (or if there is, it costs more per month than your entire team's salary). You've deferred the problem, not solved it.

**Naive horizontal:** "Just add more servers." You spin up 4 identical servers behind a load balancer. But your application stores conversation history in memory. User A sends a message to Server 1, which stores the conversation. User A's next message goes to Server 3 (round-robin load balancing). Server 3 has no idea who User A is. The conversation is broken. You've just discovered that horizontal scaling requires **statelessness**, and you weren't stateless.

Both naive approaches fail because they skip the prerequisite question: **what is holding state, and where?**

---

## The Real Mechanism

### Vertical Scaling (Scaling Up)

Replace the machine with a bigger one. More CPU cores, more RAM, faster disks, faster network cards.

```
Before: 1 server, 4 cores, 8GB RAM, 100GB SSD
After:  1 server, 64 cores, 256GB RAM, 2TB NVMe

What changes:
  ✓ More concurrent processes (more cores = more workers)
  ✓ Larger database buffer pool (more RAM = more data cached in memory)
  ✓ Faster disk I/O (NVMe vs SATA SSD is 5-10x throughput)
  ✓ Zero code changes required
  ✓ Zero architectural changes required

What doesn't change:
  ✗ Still a single point of failure
  ✗ Still one machine's network bandwidth
  ✗ There is a physical ceiling (the biggest machine available)
  ✗ Cost scales superlinearly (2x the performance often costs 3-4x the price)
```

**When vertical is the right call:** When you're early (under ~10K users), when your team is small (1-3 engineers), when the bottleneck is clearly a single resource (CPU or memory), and when the operational complexity of distributing the system would slow you down more than the machine cost.

**The honest truth about vertical scaling:** Most startups should vertically scale for longer than they think. A single Postgres instance on a 96-core, 384GB RAM machine can handle an absurd amount of work — potentially millions of rows, thousands of queries per second. The instinct to "go distributed" early is usually premature and usually comes from reading about how Google does it, not from actually hitting the limits of a single beefy machine.

### Horizontal Scaling (Scaling Out)

Add more machines and distribute the work across them.

```
Before: 1 server handling everything
After:  4 servers, each handling ~25% of traffic, behind a load balancer

What this requires:
  1. A load balancer (Module 06) to distribute requests
  2. STATELESS application servers — no request-dependent state in local memory
  3. Shared state externalized to a separate system (database, Redis, S3)
  4. Session management moved out of the application process
```

**What "stateless" actually means:** A stateless server can handle any request from any user without needing to have handled that user's previous request. The server has no memory of past interactions — it's a pure function: `input → output`, every time.

This means every piece of state that used to live "in the application" must be moved somewhere external:

```
State that must be externalized:

  User sessions → Redis or a database, not in-memory dicts
  Conversation history → Database, not a Python list in your process
  Uploaded files → S3 or a shared filesystem, not the local /tmp directory
  Rate limiting counters → Redis, not an in-process counter
  Cached results → Redis/Memcached, not a Python LRU cache

The rule: if restarting your server process loses data 
that would break a user's experience, that data is state 
and must live somewhere durable and shared.
```

**The cost of going stateless:** Every piece of state that used to be a local variable access (~1 nanosecond) is now a network call to Redis or Postgres (~0.5-2 milliseconds). That's a 500,000x slowdown for each state access. This is real — you feel it in latency. The tradeoff is: slightly higher per-request latency in exchange for the ability to add machines and handle proportionally more traffic.

### The Decision Matrix

| Factor | Vertical Scaling | Horizontal Scaling |
|--------|-----------------|-------------------|
| Code changes required | None | Significant (statelessness) |
| Operational complexity | Low (one machine) | High (distributed system) |
| Failure resilience | Zero (SPOF) | High (one machine dies, others continue) |
| Cost curve | Superlinear (2x perf ≈ 3-4x cost) | Linear (2x perf ≈ 2x cost) |
| Scaling ceiling | Physical limit of largest available machine | Theoretically unlimited |
| When it stops working | You hit the biggest machine available | You hit the complexity your team can manage |

### The Hybrid Reality

In practice, nobody does pure vertical or pure horizontal. Real systems do both:

```
Typical production setup:
  - Database: vertically scaled (big machine, lots of RAM)
    because databases are hard to distribute correctly
  - Application servers: horizontally scaled (many small machines)
    because stateless HTTP handlers are easy to distribute
  - Cache (Redis): vertically scaled initially, then sharded (horizontal)
    as cache size grows beyond one machine's RAM
```

The decision is **per component**, not per system. Your database might be vertical while your API servers are horizontal. This is normal and correct.

---

## Concrete Example From a Real System

**Illustrative:** A team runs a RAG product. Their architecture:

```
Phase 1 (0-500 users):
  1 server: FastAPI app + Postgres + Redis + pgvector
  Works fine. Simple. Easy to debug. Easy to deploy.

Phase 2 (500-5,000 users):
  Vertically scale: bigger machine (32 cores, 128GB RAM)
  Postgres buffer pool now caches the entire vector index in memory
  Redis holds all cached embeddings without eviction
  Still one machine, still easy to operate

Phase 3 (5,000+ users):
  Must go horizontal for the application layer:
  - 4 FastAPI workers behind an ALB (Application Load Balancer)
  - Each worker is stateless — conversation history in Postgres, 
    cached embeddings in Redis
  - Postgres stays on one big machine (still not the bottleneck)
  - Redis stays on one instance (still fits in memory)

Phase 4 (50,000+ users):
  - Postgres needs read replicas (Module 10)
  - Redis might need sharding (Module 22)
  - Consider a dedicated vector DB if pgvector can't keep up
  - This is where Modules 10-13 become survival knowledge
```

Notice: they didn't shard the database at 500 users. They didn't add read replicas at 1,000 users. They vertically scaled until they couldn't, then horizontally scaled the stateless layer first, because that's the cheapest and lowest-risk way to add capacity.

---

## The Tradeoffs

| You gain | You give up |
|----------|-------------|
| **Vertical:** zero complexity, zero code changes | Single point of failure, physical ceiling, superlinear cost |
| **Horizontal:** near-infinite ceiling, fault tolerance | Statelessness requirement, operational complexity, network latency for shared state |

**The meta-tradeoff:** Horizontal scaling trades *per-request efficiency* (local state access is faster) for *system-level capacity* (more machines = more total throughput). This is the same fundamental tradeoff you'll see in caching (Module 07), sharding (Module 22), and microservices (Module 17). Get comfortable with it — it's the recurring theme of this entire curriculum.

---

## How This Connects to Other Modules

- **Module 01** described the scaling walls. This module explains the two fundamental strategies for getting past them.
- **Module 06** (Load Balancing) is the prerequisite for horizontal scaling — you need something to distribute traffic.
- **Module 07** (Caching) is the primary tool for making horizontal scaling practical — externalized caching with Redis/Memcached.
- **Module 09** (Databases) will address connection pooling, which becomes critical when multiple application servers all connect to one database.
- **Module 10** (Scaling Databases) is where vertical scaling finally runs out for the database and you must go horizontal for data.
- **Module 17** (Microservices) is horizontal scaling applied to the organizational structure — splitting the system into independently scalable services.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** The textbook framing is "vertical scaling is limited, horizontal scaling is better." That's technically true and practically misleading. What matters is developing the judgment to know *when* to make the jump. In my experience, the right time to go horizontal is when you've vertically scaled the specific bottleneck component (usually the database or the application server) to the point where the next machine upgrade costs more than adding a second machine + the engineering time to make the system stateless. For most startups and small teams, that point is much later than they think.

**The AI-era connection:** AI services are *accidentally stateful* in ways that are uniquely sneaky. Here's the trap: you load a model into memory on each application server. That model might be 4GB. You have 4 workers per server. That's 16GB of RAM consumed by model copies alone. Now you want to horizontally scale by adding more servers. Each new server loads 4 copies of the model. Your memory cost scales linearly with server count, even though the model is identical everywhere. This is why AI-serving systems often use a separate model-serving layer (vLLM, TGI, TensorRT-LLM) that loads the model once and serves multiple workers — it's a form of deduplicating state to enable horizontal scaling. The same trap shows up with local vector index caches: if each server builds its own HNSW index, you've duplicated a potentially multi-GB data structure across every machine. Externalize it (pgvector, Qdrant, Pinecone) or accept that each new machine costs you not just compute but duplicate memory.

**Brutally honest advice:** Here's the advice I wish someone had given me early: **don't make the system stateless before you have to.** Statelessness has a real cost — network latency for every state access, operational complexity of running Redis and connection pools, debugging difficulty when state is spread across multiple systems. If you're under 1,000 users and your single server is handling the load, keeping conversation history in an in-memory dict is *fine*. It's not production-grade, it's not scalable, and it's the right call for your current situation. The mistake is building for Google-scale when you have 50 users. The other mistake — the one that's actually fatal — is building for 50 users and then being unable to scale when you hit 5,000 because your architecture assumed local state everywhere. The skill is knowing the difference, and you develop that skill by doing Module 04 (estimation) honestly: how many users will I have in 6 months? Is that number large enough to justify the statelessness overhead right now?

---

## Check Your Understanding

1. Your FastAPI application stores user sessions in a Python dictionary (`sessions = {}`). You want to add a second server behind a load balancer. What specifically breaks, and what's the minimum change to fix it?

2. You have a Postgres database on a 16-core, 64GB RAM machine handling 2,000 queries per second. Your application servers are horizontally scaled to 8 instances. A teammate suggests sharding the database. What question do you ask to determine if this is premature?

3. Your RAG service loads a 4GB embedding model into each worker process. You run 4 workers per server, 3 servers. How much total memory is consumed by model copies? What architectural change would reduce this?

4. Why does vertical scaling have a superlinear cost curve? (Hint: think about hardware pricing, not just performance.)

5. A system has 3 horizontally scaled application servers and 1 vertically scaled database. One application server crashes. What happens to the system? Now the database crashes. What happens? What does this tell you about where to focus your reliability effort?
