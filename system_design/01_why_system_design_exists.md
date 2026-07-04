# 01 — Why System Design Exists

## The Problem

You have a Python script. It works on your laptop. It serves one user — you. Then someone says "let's put this behind an API and let other people use it." That sentence is where system design begins, and it's where most engineers who came from ML/AI backgrounds quietly start accumulating debt they won't notice until it explodes.

Here's the real story of what actually breaks, told in orders of magnitude, because that's the only honest way to tell it.

---

## The Naive Approach and Why It Fails

The naive approach is: run the script on a server. Put Flask/FastAPI in front of it. Deploy to one machine. Done.

And honestly? For 10 users, this works. Maybe 100 users if they're polite enough not to all show up at the same time. The problem is that it works *just well enough* that you build everything else on top of it — your database schema, your deployment pipeline, your mental model of how traffic flows — and by the time you hit 10,000 users, you've built a house on sand and the tide is coming in.

Let me walk you through what actually breaks, at each order of magnitude, so you develop the gut instinct for spotting these walls before you hit them.

---

## The Real Mechanism

### 10 Users → 100 Users: The Single Machine Is Fine

One server. One process. A SQLite database or a Postgres instance on the same machine. Every request comes in, gets processed, goes out. Latency is low because there's no network hop to the database (it's local) and no contention for resources.

**Nothing breaks here.** And that's the dangerous part — it builds false confidence. You think your architecture "works" when what you actually have is the absence of load.

### 100 Users → 1,000 Users: CPU and Memory Show Up

Now requests overlap. While one request is being processed, another arrives. Your single-threaded Python server can't handle both simultaneously (if you're using Flask default, you literally process one request at a time). You switch to a multi-worker setup (Gunicorn with 4 workers). That buys you 4x concurrency.

But each worker holds the ML model or the connection to the vector database in memory. Four workers × one loaded model each = 4x the memory usage. Your 8GB server is now sweating at 7.2GB used.

**What breaks:** Memory. You're loading the same model four times. Or you're loading four database connections where you needed one pool. This is the first resource wall, and the fix is understanding that the CPU does the work and the memory holds the state, and you need to be intentional about both.

### 1,000 Users → 10,000 Users: Disk I/O and the Database Wall

Your application is fine — the workers are handling the traffic. But the database is not. Every request reads from the database. Some requests write. At 1,000 concurrent users, you're issuing maybe 3,000 database queries per second. Your Postgres instance on the same machine is doing:

- Reading from disk (even with caching, some queries miss the buffer pool)
- Writing to disk (every write must be durable — fsync to the write-ahead log)
- Managing locks (concurrent writes to the same rows contend)

**What breaks:** Disk I/O becomes the bottleneck. The database's buffer pool can't cache everything. Queries that were 2ms start taking 50ms because they're hitting disk. Writes start queuing because the WAL fsync can only go so fast. Your p99 latency spikes from 100ms to 2 seconds because one slow query blocks the connection and the next request waits for a connection from the pool.

**The fix people reach for:** Put the database on a bigger machine (vertical scaling — Module 03). Buy more RAM so the buffer pool holds everything. Use SSDs instead of spinning disks. This works until the machine can't get any bigger.

### 10,000 Users → 100,000 Users: The Single Point of Failure

Your big database machine is humming. Your 4-worker application server is groaning. You add more application servers (horizontal scaling — Module 03) behind a load balancer (Module 06). Now you have 8 servers, each with 4 workers, handling requests in parallel.

But the database is still one machine. And that machine is now the single point of failure for your entire system. If it goes down — hardware fault, misconfigured query that eats all CPU, a bad deploy — every single one of your 8 application servers is dead in the water. They can accept requests but can't do anything useful.

**What breaks:** Single point of failure. Not performance — availability. The system goes from "always up" to "up except when the database machine has a bad day," and a bad day is inevitable at this scale.

**The fix:** Read replicas (Module 10). A leader database handles writes, and follower databases handle reads. Now reads can be distributed across multiple machines, and if one follower dies, others pick up the slack. But now you have replication lag — a write to the leader takes some milliseconds to propagate to the followers, and a read from a follower might return stale data. Welcome to the consistency problem (Module 12).

### 100,000 Users → 1,000,000 Users: Network Bandwidth and the Everything Problem

Now everything is a problem at once. Your load balancer is handling 50,000 requests per second. Your database leader is handling 10,000 writes per second. Your read replicas are handling 40,000 reads per second. The network between your application servers and your database cluster is saturated — each query returns maybe 1KB, but 50,000 queries × 1KB = 50MB/s of database traffic alone, plus the request/response traffic from users.

**What breaks:** Network bandwidth between components. Internal service-to-service communication dominates your network capacity. Adding more servers doesn't help if the network between them is the bottleneck.

**The fixes (all at once, because they compound):**
- Caching (Module 07): Don't query the database for data you already have. A cache layer (Redis, Memcached) holds hot data in memory, network-accessible.
- Message queues (Module 14): Don't process everything synchronously. Offload non-urgent work (analytics, notifications, embedding generation) to a queue.
- Sharding (Module 10/22): Split the database itself across multiple machines, each holding a subset of the data.
- CDN (Module 08): Serve static assets from geographically distributed edge servers, not your origin.

### 1,000,000 Users → 10,000,000 Users: Organizational, Not Technical

At this point, the technical problems are known and solvable (that's what this entire curriculum teaches). The new bottleneck is organizational:
- One team can't own the entire system. You split into teams, each owning a service (Module 17).
- A change to the user service can't break the payment service. You need service boundaries, API contracts, independent deployment.
- You need observability (Module 25) to understand what's happening across 20 services, 100 machines, and 500 processes.

---

## Concrete Example From a Real System

**Twitter's Fail Whale (2008-2013):** Twitter started as a Ruby on Rails monolith on a single database. It famously displayed a "Fail Whale" error page when overloaded. The journey from Fail Whale to the system that handles 500 million tweets per day involved every concept in this curriculum: moving from MySQL to a custom distributed datastore, adding extensive caching layers (Cache, Module 07), adopting message queues for fan-out (Module 14), splitting into microservices (Module 17), and building custom observability tools. The technical solutions are well-documented in their engineering blog — but the lesson is: every one of these changes was forced by a specific breakage at a specific scale, not planned upfront.

---

## The Tradeoffs

Every scaling solution introduces complexity:

| Solution | What it fixes | What it costs |
|----------|--------------|---------------|
| More workers/processes | CPU contention | Memory (each worker holds state) |
| Read replicas | Read throughput | Consistency (replication lag) |
| Caching | Database load | Cache invalidation complexity |
| Sharding | Write throughput | Cross-shard queries, operational overhead |
| Message queues | Synchronous bottlenecks | Eventual consistency, debugging difficulty |
| Microservices | Team independence, independent scaling | Network latency, distributed debugging |

**The two fundamental moves that fix any scaling problem:**

1. **Do less work.** Cache the result so you don't compute it again. Batch writes instead of doing them one at a time. Skip processing that nobody's waiting for right now (async).
2. **Do the work in more places.** Add more servers (horizontal scale). Add more database replicas. Distribute data across shards.

Every technique in this entire curriculum is a specific, concrete application of one of these two moves. If you internalize this, you can reason about any scaling problem from first principles instead of memorizing solutions.

---

## How This Connects to Other Modules

This module is the map. Everything else is the territory.

- Module 03 (Scalability) goes deep on vertical vs horizontal scaling
- Module 04 (Estimation) teaches you to predict WHERE the wall will hit before you hit it
- Module 05 (Reliability) gives you the vocabulary to talk about what "breaking" means quantitatively
- Modules 06-18 are the specific building blocks (load balancers, caches, databases, queues, APIs)
- Modules 20-27 are the distributed systems depth that matters when you're at 100K+ users
- Modules 28-36 are complete case studies that walk through real systems end to end

---

## Mentor's Take — What Actually Matters Here

**What matters vs what's textbook noise:** Everything in this module matters. I know that sounds like a cop-out, but here's why I'm saying it: this is the one module that most people skip because it "seems basic." They jump to caching algorithms or consensus protocols because those feel more impressive. And then in an interview or a design review, they propose a sharded distributed database for a system that has 500 users and doesn't need one. The reason they do this is because they never internalized the scale at which each solution becomes necessary. They're pattern-matching from buzzwords instead of reasoning from physics.

**The AI-era connection:** Everything I just described — the CPU wall, the memory wall, the database wall, the network wall — hits AI systems *faster and harder* than traditional web systems. Here's why: a classic web API request takes 5-50ms. A RAG request that retrieves documents, runs an embedding, queries a vector database, and generates a response from an LLM takes 2-10 *seconds*. That 100x slowdown means:

- Your connection pools exhaust 100x faster (Module 09 will hit this hard)
- Your load balancer's timeout assumptions are wrong by 100x
- Your users are holding connections open 100x longer, so you need 100x more concurrent connection capacity for the same QPS
- A single slow LLM API response doesn't just add 5ms to your p99 — it adds 5 *seconds*, which means your tail latency is now measured in tens of seconds, not hundreds of milliseconds

Every scaling wall I described above arrives at 1/100th the user count for AI-backed systems compared to classic CRUD apps. That 10,000-user database wall? It might hit you at 100 users if each request holds a database connection for 5 seconds while waiting for the LLM to respond.

**Brutally honest advice:** If you came from an ML/AI background, your blind spot is almost certainly this: you think the hard part of building an AI product is the model. It's not. The model is a function call. The hard part is everything around it — the system that calls the function, handles the result, recovers from failures, scales under load, and stays up at 3am when you're asleep. This curriculum exists because that "everything around it" is what actually determines whether your product works in production or falls over the first time 50 people use it at the same time. If you're tempted to skip ahead to the "interesting" modules, resist. The gut-level intuition for where systems break at scale is the single most valuable thing you can build, and it only comes from understanding the physics of machines, networks, and data at each order of magnitude.

---

## Check Your Understanding

1. Your RAG API serves 200 requests per minute. Each request takes 4 seconds end-to-end (retrieval + LLM generation). You have a connection pool of 20 Postgres connections. Is the pool going to be a problem? Show the math.

2. You're designing a system expected to handle 10,000 daily active users. Using the two fundamental scaling moves ("do less work" or "do work in more places"), identify which move you'd apply first and why, before reaching for any specific technology.

3. A teammate proposes sharding the vector database at 1,000 users because "we need to be ready for scale." What question do you ask them to determine if this is premature?

4. Your LLM-backed API has a p99 latency of 12 seconds. A classic web API has a p99 of 200ms. How does this 60x difference change the number of application server workers you need to serve 100 concurrent users? What assumptions break?

5. Why does the "single point of failure" problem become more dangerous, not less, as you add more application servers behind a load balancer?
