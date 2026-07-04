# 17 — Microservices vs Monoliths

## The Problem

Your application has grown. The codebase is 200,000 lines. The team is 15 engineers. Deploys take 45 minutes. A bug in the billing module brings down the search API. The team that owns document ingestion wants to deploy 5 times a day, but the team that owns billing deploys once a week and insists on a full regression test before each deploy.

The monolith is becoming a bottleneck — not because monoliths are inherently bad, but because the organizational and operational friction of a single deployable unit grows with team size and feature scope. The question isn't "should I use microservices?" — it's "at what point does splitting the monolith reduce more pain than it creates?"

---

## The Naive Approach and Why It Fails

**Naive approach 1: "Microservices are how real companies do it, so we should too."**

A 3-person startup splits their RAG application into 7 microservices on day one: API gateway, auth service, document service, chunking service, embedding service, vector search service, notification service. Each has its own repo, CI pipeline, database, and Kubernetes deployment.

They now spend 60% of their engineering time on infrastructure: service discovery, distributed tracing, inter-service authentication, API versioning between services, debugging distributed failures, and managing 7 deployment pipelines. They ship features at 1/3 the speed of a competing startup that has one Python process and a Postgres database.

**Naive approach 2: "We'll never split. Monoliths are simpler."**

A 50-person company keeps everything in one codebase. The auth team accidentally deploys a migration that locks the users table for 10 minutes. The search API, which reads from the users table for permission checks, goes down. Customer-facing search is unavailable because an internal auth migration went wrong.

Both approaches fail because they ignore the actual decision criterion: team size, deployment independence, and fault isolation requirements.

---

## The Real Mechanism

### What a Monolith Actually Is

A monolith is a single deployable unit — one binary, one container, one process. All code runs in the same process, communicates through function calls, shares the same database, and is deployed as one artifact.

```
Monolith:
  ┌─────────────────────────────────────┐
  │            Application              │
  │                                     │
  │  ┌──────────┐  ┌──────────────────┐ │
  │  │   Auth   │  │  Document Mgmt   │ │
  │  │  module  │──│  module          │ │
  │  └──────────┘  └──────────────────┘ │
  │  ┌──────────┐  ┌──────────────────┐ │
  │  │  Search  │  │   Embedding      │ │
  │  │  module  │──│   module         │ │
  │  └──────────┘  └──────────────────┘ │
  │                                     │
  │  Shared database: PostgreSQL        │
  │  Communication: function calls      │
  │  Deployment: one container          │
  └─────────────────────────────────────┘
```

**Monolith advantages (and they are real):**
- **Function calls, not network calls.** `auth.check_permission(user_id)` is a function call — nanoseconds, zero serialization, type-checked at compile time. In microservices, this becomes an HTTP/gRPC call: milliseconds, JSON/protobuf serialization, network failure modes.
- **Shared database.** A JOIN between users and documents is a single SQL query. In microservices, it's a cross-service data fetch that requires API calls, data aggregation in code, and eventual consistency.
- **One deployment.** Deploy once, everything is in sync. No version compatibility matrix between 7 services.
- **Simple debugging.** A stack trace shows the full call path. In microservices, a request crosses 5 services — you need distributed tracing (Module 25) to see what happened.
- **Transactions.** `BEGIN; deduct_balance(); create_order(); COMMIT;` is atomic. In microservices, this requires a saga (Module 23).

### What Microservices Actually Are

Microservices split the application into independently deployable services, each owning its own data and communicating over the network:

```
Microservices:
  ┌──────────┐     ┌──────────────┐     ┌──────────────┐
  │   Auth   │     │   Document   │     │  Embedding   │
  │  Service │     │   Service    │     │  Service     │
  │          │     │              │     │              │
  │  Own DB  │     │  Own DB      │     │  Own DB      │
  │ (users)  │     │ (documents)  │     │ (embeddings) │
  └──────────┘     └──────────────┘     └──────────────┘
       │                  │                    │
       └─── HTTP/gRPC ───┴── HTTP/gRPC ───────┘
```

**The real reasons to split (not fashion, not "best practice"):**

1. **Independent deployment.** The embedding team deploys a new model without touching the auth service. The auth team ships a security patch without redeploying the entire application. This matters when different parts of the system have different deployment cadences.

2. **Independent scaling.** The embedding service needs 10 GPU workers. The auth service needs 2 CPU workers. In a monolith, you scale the entire application (including the auth module that doesn't need GPUs) to get more embedding capacity.

3. **Fault isolation.** The embedding service crashes (out of GPU memory). The auth service, document service, and search service continue running. Users can't generate new embeddings, but they can still log in, upload documents, and search existing content.

4. **Team boundaries (Conway's Law).** Conway's Law: "Organizations design systems that mirror their communication structure." If you have separate teams for auth, documents, and AI, they will naturally want independent codebases, deployments, and on-call rotations. Forcing them into a monolith creates constant merge conflicts and deployment coordination overhead.

### The Real Costs of Microservices

```
Cost 1: Network calls replace function calls.
  Monolith: auth.check(user_id) → 0.001ms (function call)
  Microservices: GET auth-service:8080/check/user_id → 1-5ms + failure modes
  
  Every function call that crosses a service boundary now has:
  - Network latency (1-5ms per call)
  - Serialization/deserialization overhead
  - Possible timeout, retry, circuit breaker logic
  - A new failure mode: the network itself can fail

Cost 2: Distributed data.
  Monolith: SELECT d.title, u.name FROM documents d JOIN users u ON ...
  Microservices: 
    1. GET document-service/docs/42 → {"title": "NDA", "user_id": 7}
    2. GET auth-service/users/7 → {"name": "Alice"}
    3. Combine in application code.
  
  Two network calls. Two potential failures. No transaction guarantees.
  What if user 7 is deleted between call 1 and call 2?

Cost 3: Distributed debugging.
  Monolith: Stack trace shows the full call path.
  Microservices: Request hits API gateway → auth → document → embedding → search.
    One of them returns a 500. Which one? You need distributed tracing 
    (Module 25) with correlation IDs propagated through every call.

Cost 4: Operational multiplication.
  Each service needs: CI/CD pipeline, monitoring, alerting, logging,
  health checks, auto-scaling rules, database management, security patching.
  7 services = 7x the operational work. For a 3-person team, 
  this is 7x the work divided by 3 engineers = everyone is doing ops.
```

### The Decision Framework — When to Split

```
Stay monolith when:
  ✓ Team < 10 engineers
  ✓ Entire team deploys together on the same cadence
  ✓ No part of the system needs to scale independently (e.g., GPU vs CPU)
  ✓ The codebase is maintainable with good internal module boundaries
  ✓ You're in the first 1-2 years of a startup

Split into microservices when:
  ✓ Team > 10 engineers with clear team boundaries
  ✓ Different parts need different deployment cadences
  ✓ Different parts need different scaling (GPU workers vs CPU workers)
  ✓ A failure in one part should NOT bring down other parts
  ✓ You've exhausted internal modularization (the "modular monolith")

The middle ground — Modular Monolith:
  One deployable unit, but with strict internal module boundaries.
  Each module owns its own database tables (no cross-module JOINs).
  Communication between modules uses internal interfaces (not direct DB access).
  When a module needs to be extracted into a service, the interface 
  is already defined — the extraction is mechanical, not architectural.
```

---

## Concrete Example From a Real System

**Illustrative: RAG Platform Architecture Decision**

A startup (5 engineers) builds a RAG product. Initial architecture: monolith (Python + FastAPI + PostgreSQL + pgvector).

```
Month 1-12 (Monolith — correct choice):
  One FastAPI application handles:
  - User auth
  - Document upload and management
  - Chunking and embedding (calls OpenAI API)
  - Vector search (pgvector queries)
  - LLM generation (calls Anthropic API)
  
  Deployment: one Docker container, one Postgres instance.
  Team deploys 5x/day. All 5 engineers work in one repo.
  This is the correct architecture for a 5-person team.

Month 12-18 (Pain points emerge):
  - Embedding generation needs GPUs. Scaling the entire monolith 
    to get more embedding capacity wastes money on CPU instances.
  - A bug in the embedding code crashes the process. All users 
    lose access to search (even for already-indexed documents).
  - The AI team wants to experiment with new embedding models 
    without redeploying the entire application.

Month 18 (Extract embedding service — first microservice):
  ┌──────────────────────┐    ┌──────────────────┐
  │   Main Application   │    │ Embedding Service │
  │                      │    │                   │
  │  Auth, Upload, Search│───→│ Chunk + Embed     │
  │  Generation          │    │ (GPU instances)   │
  │                      │    │ Own scaling policy│
  │  PostgreSQL + pgvector│   │ Talks to OpenAI  │
  └──────────────────────┘    └──────────────────┘
  
  The monolith remains for everything else.
  Only the embedding workload is extracted — the part that needs 
  different compute (GPUs), independent scaling, and fault isolation.
  
  The team did NOT split auth, documents, or search into separate services.
  Those modules don't have different scaling needs and don't benefit 
  from independent deployment.
```

This is the correct evolution: start monolith, extract services one at a time as specific operational needs demand it.

---

## The Tradeoffs

| Factor | Monolith | Microservices |
|--------|----------|---------------|
| Communication | Function calls (ns) | Network calls (ms) + failure modes |
| Data access | JOINs, transactions | Cross-service API calls, eventual consistency |
| Deployment | One artifact, one pipeline | N artifacts, N pipelines |
| Scaling | Scale everything together | Scale each service independently |
| Fault isolation | One crash affects everything | One crash affects one service |
| Debugging | Stack traces | Distributed tracing required |
| Team size fit | < 10 engineers | > 10 engineers with team boundaries |
| Operational cost | Low (one system) | High (N systems to monitor/maintain) |

---

## How This Connects to Other Modules

- **Module 06** (Load Balancing): Each microservice sits behind its own load balancer or is routed through an API gateway.
- **Module 14** (Message Queues): Async communication between microservices (events, commands) via queues.
- **Module 16** (API Design): Inter-service APIs (gRPC for internal, REST for external) are the communication contracts.
- **Module 18** (Service Communication): Circuit breakers, retries, and timeouts become essential when function calls become network calls.
- **Module 19** (Service Discovery): Microservices need to find each other. Service discovery is the mechanism.
- **Module 23** (Distributed Transactions): Cross-service transactions require sagas. This is a direct cost of splitting.
- **Module 25** (Observability): Distributed tracing becomes essential for debugging cross-service requests.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Know the real reasons to split (independent deployment, independent scaling, fault isolation, team boundaries) and the real costs (network calls, distributed data, operational overhead). Know Conway's Law. Know the "modular monolith" as the middle ground. Be able to articulate when a monolith is the right choice (small team, early stage) without sounding defensive. In an interview, if asked "monolith or microservices?" the correct answer is "it depends on the team size and operational requirements" — followed by a clear explanation of the tradeoffs for the specific scenario. Jumping straight to microservices is a red flag; it signals you don't understand the costs.

**The AI-era connection:** The brutal honest take: AI engineers reach for microservices too early because "that's how real companies do it." When your RAG pipeline is genuinely one system with clear internal boundaries (retrieval, generation, ingestion) that does NOT yet need to be three deployed services, splitting it creates overhead without benefit. The first microservice extraction should be driven by a specific operational need — usually the embedding/inference workload needing different compute (GPUs) or independent scaling. Everything else (auth, document management, search) can stay in the monolith until team size or deployment friction forces a split.

The second mistake: splitting by "AI concern" (embedding service, retrieval service, generation service) instead of by "team boundary." If one team owns all three AI concerns, splitting them into three services just means one team maintains three deployments for no organizational benefit. Split when different teams need to deploy independently, not when the architecture diagram looks prettier.

**Brutally honest advice:** If you're a team of 3-5 building an AI product and you're running Kubernetes with a service mesh and 7 microservices, you are doing it wrong. You are spending engineering time on infrastructure that adds zero user value. Ship a monolith. Use a managed Postgres instance. Deploy to a single container on a managed platform (Railway, Render, or AWS App Runner). Revisit the architecture when you have a specific, measured operational pain point — not when you read a blog post about how Netflix uses microservices. Netflix has 2,000 engineers. You have 4.

---

## Check Your Understanding

1. A 3-person startup splits their RAG app into 5 microservices. Each has its own Kubernetes deployment and CI/CD pipeline. What percentage of their engineering time is likely spent on infrastructure vs features? Is this the right architecture?

2. Your monolith's embedding module crashes (OOM on a large document). All users lose access to search, auth, and document upload. How would extracting the embedding module into a microservice prevent this? What new failure mode does the extraction introduce?

3. Conway's Law says "organizations design systems that mirror their communication structure." If your team has no organizational boundaries (everyone works on everything), what does Conway's Law predict about the benefit of microservices?

4. Your monolith does `BEGIN; deduct_credits(user_id, 100); generate_embedding(text); INSERT INTO chunks(...); COMMIT;` atomically. If you split this across a credit service and an embedding service, what happens if the embedding service fails after credits are deducted? What pattern (Module 23) handles this?

5. You're building a RAG product. Your team is 8 engineers. The AI team (3 people) wants to deploy embedding model changes 3x/day. The platform team (5 people) deploys weekly. Both share a monolith. What is the minimum architectural change to solve this friction?
