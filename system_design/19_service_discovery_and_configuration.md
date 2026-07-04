# 19 — Service Discovery and Configuration

## The Problem

Your service needs to call the embedding service. Where is it? In a monolith, the answer is trivial: it's a function call in the same process. In microservices, it's a network call to some host and port. But which host? Which port?

```python
# Hardcoded? Works until the service moves.
response = requests.post("http://10.0.1.42:8080/embed", json=data)

# What happens when:
# - 10.0.1.42 is restarted and gets a new IP?
# - You add a second embedding service instance for scaling?
# - You deploy to a staging environment where the IP is different?
# - The embedding service crashes and a new instance spins up on 10.0.1.55?
```

Hardcoding service locations is the equivalent of hardcoding database passwords — it works on your laptop, it breaks in production, and it's a maintenance nightmare at any real scale. Service discovery is the mechanism that answers "where is service X right now?" dynamically, in real time.

---

## The Naive Approach and Why It Fails

**Naive approach: configuration files with static IPs.**

```yaml
# config.yaml
services:
  embedding: "http://10.0.1.42:8080"
  auth: "http://10.0.1.43:8081"
  search: "http://10.0.1.44:8082"
```

This fails because:
1. **IPs change.** Cloud instances are ephemeral. Auto-scaling creates new instances with new IPs. Container orchestrators (Kubernetes) assign random IPs to pods.
2. **No load balancing.** If you add a second embedding service instance, you need to update the config, redeploy, and restart every service that calls the embedding service.
3. **No health awareness.** If `10.0.1.42` crashes, the config still points there. Requests fail until a human manually updates the config.
4. **Environment coupling.** Production, staging, and development all have different IPs. You need separate config files per environment, and they drift constantly.

---

## The Real Mechanism

### The Service Registry Pattern

A service registry is a dedicated database that tracks which instances of each service are currently running and healthy.

```
Service Registry (e.g., Consul, etcd, ZooKeeper):
  ┌──────────────────────────────────────────────────┐
  │  Service: embedding-service                       │
  │    Instance 1: 10.0.1.42:8080  (healthy, 50% CPU)│
  │    Instance 2: 10.0.1.55:8080  (healthy, 30% CPU)│
  │    Instance 3: 10.0.1.61:8080  (unhealthy, DOWN) │
  │                                                    │
  │  Service: auth-service                             │
  │    Instance 1: 10.0.2.10:8081  (healthy)          │
  │    Instance 2: 10.0.2.11:8081  (healthy)          │
  │                                                    │
  │  Service: search-service                           │
  │    Instance 1: 10.0.3.20:8082  (healthy)          │
  └──────────────────────────────────────────────────┘
```

**Registration:** When a service instance starts, it registers itself with the registry ("I'm embedding-service, I'm at 10.0.1.42:8080").

**Health checking:** The registry periodically pings each instance. If an instance fails health checks, it's marked unhealthy and removed from discovery results.

**Deregistration:** When a service instance shuts down gracefully, it deregisters. If it crashes, the health check detects the failure and removes it.

### Client-Side Discovery vs Server-Side Discovery

**Client-Side Discovery:**
```
The calling service queries the registry directly, gets a list of healthy 
instances, and picks one (round-robin, random, least connections).

┌──────────┐     ┌──────────┐     ┌──────────┐
│  Client   │────→│ Registry │     │ Embedding│
│  Service  │     │          │     │ Service  │
│           │←────│ returns  │     │ 10.0.1.42│
│           │     │ healthy  │     ├──────────┤
│           │     │ instances│     │ Embedding│
│           │──────────────────────→│ Service  │
│           │  (direct call)       │ 10.0.1.55│
└──────────┘                       └──────────┘

Pros: No additional network hop (client calls target directly).
      Client can use custom load balancing logic.
Cons: Every client must include discovery + load balancing logic.
      Every language/framework must implement it.
      Registry coupling: if registry is down, clients can't discover.

Used by: Netflix Eureka, gRPC client-side balancing.
```

**Server-Side Discovery:**
```
The calling service sends the request to a load balancer or proxy.
The proxy handles discovery and routing.

┌──────────┐     ┌──────────┐     ┌──────────┐
│  Client   │────→│   Load   │────→│ Embedding│
│  Service  │     │ Balancer │     │ Service  │
│           │     │  /Proxy  │     │ 10.0.1.42│
│           │     │          │     ├──────────┤
│           │     │ (knows   │     │ Embedding│
│           │     │  about   │────→│ Service  │
│           │     │  all     │     │ 10.0.1.55│
│           │     │ instances│     └──────────┘
└──────────┘     └──────────┘

Pros: Clients are simple — just call the proxy's address.
      Load balancing and discovery centralized (change once, affects all clients).
Cons: Additional network hop through the proxy (adds ~1ms latency).
      Proxy is a single point of failure (mitigate with active-passive).

Used by: AWS ALB, Kubernetes Services, nginx, Envoy.
```

### Kubernetes Service Discovery — The De Facto Standard

If you're deploying to Kubernetes (and most production systems are), service discovery is built in:

```yaml
# Kubernetes Service definition
apiVersion: v1
kind: Service
metadata:
  name: embedding-service
spec:
  selector:
    app: embedding
  ports:
    - port: 80
      targetPort: 8080
```

```python
# Any pod in the cluster can reach the embedding service at:
response = requests.post("http://embedding-service/embed", json=data)

# Kubernetes automatically:
# 1. Assigns a stable DNS name (embedding-service.namespace.svc.cluster.local)
# 2. Load-balances across all healthy pods matching the selector
# 3. Removes unhealthy pods from the routing (based on readiness probes)
# 4. Updates routing when pods are added/removed (auto-scaling)
```

This is server-side discovery: the Kubernetes Service acts as an internal load balancer. The client just uses the DNS name — no registry client library, no health checking code, no load balancing logic.

**For most teams, Kubernetes Service discovery is sufficient.** You don't need Consul, etcd, or a service mesh unless you have specific requirements (cross-cluster discovery, advanced traffic management, mutual TLS enforcement).

### Centralized Configuration Management

Related to service discovery: how do you manage configuration (feature flags, API keys, model parameters, rate limit thresholds) across multiple services?

```
Naive: Environment variables or config files baked into the Docker image.
  Problem: Changing a config requires redeploying the service.
  
Better: Centralized config store (Consul KV, AWS SSM Parameter Store,
  HashiCorp Vault for secrets).
  Services read config from the store at startup and periodically poll for changes.
  Change a config value → all services pick it up without redeployment.

Example — runtime model switching:
  Config store key: ai/embedding-model → "text-embedding-3-small"
  
  To switch to a new model:
  1. Update config: ai/embedding-model → "text-embedding-3-large"
  2. All embedding workers pick up the change within 60 seconds.
  3. No redeployment. No downtime.

This is critical for AI systems where you want to:
  - Switch LLM providers without redeploying
  - Adjust rate limit thresholds in real time
  - Toggle feature flags (enable/disable RAG fallback)
  - Rotate API keys without restarting services
```

### Health Checking — Deep vs Shallow

Service discovery depends on accurate health information. A service that reports "healthy" but can't actually serve requests is worse than a service that's honestly "down" — because the load balancer keeps sending it traffic.

```python
# Shallow health check: "Is the process running?"
@app.get("/health")
def health():
    return {"status": "ok"}  # Process is alive, but can it actually work?

# Deep health check: "Can this service actually do its job?"
@app.get("/health")
async def health():
    checks = {}
    try:
        await db.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "failed"
    
    try:
        await redis.ping()
        checks["cache"] = "ok"
    except Exception:
        checks["cache"] = "failed"
    
    try:
        # Check if the embedding model is loaded
        test_embedding = model.encode("health check")
        checks["model"] = "ok"
    except Exception:
        checks["model"] = "failed"
    
    all_healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_healthy else 503,
        content={"status": "healthy" if all_healthy else "degraded", "checks": checks}
    )
```

In Kubernetes:
```yaml
# Readiness probe: Is the pod ready to receive traffic?
readinessProbe:
  httpGet:
    path: /health
    port: 8080
  periodSeconds: 10
  failureThreshold: 3   # After 3 failures, remove from load balancer

# Liveness probe: Is the pod alive (not deadlocked/crashed)?
livenessProbe:
  httpGet:
    path: /health/live
    port: 8080
  periodSeconds: 30
  failureThreshold: 5   # After 5 failures, RESTART the pod
```

**The distinction matters:** A readiness probe failure removes the pod from the service (stops sending traffic). A liveness probe failure restarts the pod. Use readiness for "can this pod serve?" and liveness for "is this pod alive?"

---

## Concrete Example From a Real System

**Illustrative: Service Discovery for a Multi-Model RAG Platform**

```
Kubernetes cluster running a RAG platform:

Services (Kubernetes Service objects):
  api-gateway          → 3 pods, port 80
  auth-service         → 2 pods, port 8081
  document-service     → 3 pods, port 8082
  embedding-service    → 5 pods (GPU nodes), port 8083
  vector-search        → 4 pods, port 8084
  llm-router           → 2 pods, port 8085

Config Store (AWS SSM Parameter Store):
  /prod/ai/embedding-model       → "text-embedding-3-small"
  /prod/ai/llm-primary           → "claude-sonnet-4"
  /prod/ai/llm-fallback          → "gpt-4.1-mini"
  /prod/ai/max-tokens            → "4096"
  /prod/ratelimit/rpm            → "100"
  /prod/ratelimit/tpm            → "500000"

Runtime model switch workflow:
  1. Engineer updates /prod/ai/embedding-model → "text-embedding-3-large"
  2. Embedding-service pods poll config every 30 seconds
  3. Next poll cycle: all 5 pods load the new model
  4. No redeployment. No downtime.
  5. If the new model causes issues → update config back → automatic rollback

Service discovery in action:
  api-gateway calls: http://embedding-service/embed
  Kubernetes resolves embedding-service → one of 5 healthy pods
  If pod 3 fails readiness probe → Kubernetes removes it from rotation
  If pod 3 recovers → Kubernetes adds it back
  All automatic. Zero application code changes.
```

---

## The Tradeoffs

| Approach | Best For | Gives Up |
|----------|----------|----------|
| Hardcoded IPs | Nothing (don't do this) | Everything (breaks on any infrastructure change) |
| DNS-based (Kubernetes Services) | Most deployments, simplest | Advanced routing (no weighted traffic, no header-based routing) |
| Client-side (Eureka, gRPC) | Custom load balancing, latency-sensitive | Every client needs discovery logic |
| Service mesh (Istio, Linkerd) | Advanced traffic management, mutual TLS, observability | Massive operational complexity, resource overhead |
| Centralized config (SSM, Consul KV) | Runtime config changes without redeployment | Config store becomes a dependency (must be highly available) |

---

## How This Connects to Other Modules

- **Module 06** (Load Balancing): Service discovery and load balancing are tightly coupled. The load balancer needs to know which instances exist; the registry provides that.
- **Module 17** (Microservices): Service discovery is a direct cost of splitting a monolith. In a monolith, there's nothing to discover.
- **Module 18** (Service Communication): Circuit breakers use health information from the same health checks that service discovery uses.
- **Module 20** (Consensus): Service registries like etcd and ZooKeeper use consensus algorithms for strong consistency of the registry data.
- **Module 25** (Observability): Service discovery metadata (which instances are running, which are unhealthy) is a key input to dashboards and alerting.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** If you're deploying to Kubernetes (and you probably are), know that Kubernetes Services give you DNS-based service discovery for free. Know the difference between client-side and server-side discovery. Know what a service registry does (tracks instances, health checks, provides discovery). Know health checking (deep vs shallow, readiness vs liveness in Kubernetes). Know centralized config management and why it's better than env vars for anything that changes at runtime. Don't memorize Consul or etcd internals — you'll read the docs when you need them.

**The AI-era connection:** Honest scoping: service discovery becomes important for you when you have multi-service agent architectures with dynamically scaling workers. If you have an embedding service that auto-scales from 2 to 20 GPU pods based on ingestion load, service discovery ensures that all API calls automatically route to all available pods without configuration changes. If you have a multi-model LLM router that switches between providers based on cost, latency, and availability, centralized config management lets you change routing weights without redeploying.

But: if you have a single RAG service behind one load balancer, you don't need a service mesh. You need a Kubernetes Service object and an ALB. Don't adopt Istio because you read a blog post about it. Istio adds 200MB+ of memory overhead per pod (the sidecar proxy), increases request latency by 1-5ms, and requires a dedicated team to operate. It's the right tool for organizations with 50+ microservices and strict security requirements. It's the wrong tool for a startup with 5 services.

**Brutally honest advice:** The config management mistake I see constantly in AI teams: baking API keys and model names into Docker images as environment variables. This means switching from `text-embedding-3-small` to `text-embedding-3-large` requires rebuilding and redeploying the container. Use a config store (AWS SSM Parameter Store is free for basic usage). Store API keys in Vault or AWS Secrets Manager. Reference them at runtime, not at build time. The first time you need to emergency-rotate a compromised API key at 2am, you'll be grateful you can do it by updating a secret in Vault instead of triggering a full CI/CD pipeline.

---

## Check Your Understanding

1. You deploy 4 instances of your embedding service. One crashes and gets a new IP when Kubernetes restarts it. With hardcoded IPs, what happens? With Kubernetes Service discovery, what happens?

2. Explain the difference between a Kubernetes readiness probe and a liveness probe. Your embedding service has loaded its model into GPU memory but the model is corrupted (produces garbage embeddings). Which probe should detect this? What should the probe check?

3. Your team uses environment variables for the LLM model name (`LLM_MODEL=claude-sonnet-4`). You need to switch to `claude-opus-4` immediately due to a quality issue. Describe the steps required with env vars vs with centralized config.

4. A startup with 3 services adopts Istio as their service mesh. Each service's sidecar proxy uses 200MB RAM. With 3 replicas per service (9 pods), what is the total memory overhead from Istio sidecars? Is this justified?

5. Client-side discovery requires every calling service to include discovery and load balancing logic. Why is this a problem when your services are written in 3 different languages (Python, Go, Rust)?
