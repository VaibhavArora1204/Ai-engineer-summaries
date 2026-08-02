# Graph Systems in Practice — From DSA to Production

> **Stack**: Python. All scripts are standalone, no dependencies beyond stdlib.
>
> **Prerequisite**: You already know traversal, cycles, topological sort from DSA. This document shows where those exact primitives show up disguised as real systems — so you never freeze when a work problem turns out to be a graph problem.
>
> **Your focus**: Service/system architecture and product features that are secretly graph problems.

---

## Section 1 — Where Graphs Actually Show Up at Work (The DAG Track)

### 1.1 — Dependency Graphs Are Everywhere. Most Engineers Just Don't Name Them.

Package managers resolving dependencies, build systems ordering compilation steps, CI/CD pipelines ordering jobs, Terraform ordering resource creation, database migration ordering, task schedulers like Airflow — all of these are the **same underlying structure**: a **DAG**.

**DAG (Directed Acyclic Graph)**: A graph where edges have direction (A depends on B, not the other way) and there are no cycles (you can never follow edges and loop back to where you started). That's it. If you can draw a "depends-on" arrow between things and there's no circular dependency, you have a DAG.

**Why this matters**: The algorithm that turns a DAG into a runnable order is **topological sort** — the exact one you did in DSA. Every dependency resolver runs topological sort to figure out "what must happen before what." You already know the algorithm. Now you know where it runs, silently, behind every `pip install`, every `terraform apply`, every Airflow DAG trigger.

### 1.2 — Build: A Real Dependency Resolver (200-module build system)

Scenario: You're working on a large Python monorepo. 200 internal packages, each with declared dependencies on other internal packages. The build system needs to figure out: what order to compile/test them in, and what can run in parallel.

This is not hypothetical. This is what Bazel, Pants, Buck, and every real build system does internally.

**Save as `graph_dep.py` and run it:**

```python
"""
Build system dependency resolver for a 200-module monorepo.
Topological sort gives you build order. BFS levels give you parallelism.
Cycle detection catches the thing that would deadlock your build.

This is the same topological sort from DSA, running on real-scale data.
"""

import random
from collections import defaultdict, deque

random.seed(42)

# ============================================================================
# GENERATE A REALISTIC 200-MODULE DEPENDENCY GRAPH
# ============================================================================
# Real monorepos have layers: core libs → domain libs → services → apps
# Dependencies flow downward (apps depend on services, not the other way).
# We simulate this structure.

LAYERS = {
    "core":    [f"core_{i}" for i in range(15)],          # 15 core libs (logging, config, auth, etc.)
    "infra":   [f"infra_{i}" for i in range(25)],         # 25 infrastructure packages
    "domain":  [f"domain_{i}" for i in range(50)],        # 50 domain/business logic packages
    "service": [f"service_{i}" for i in range(60)],       # 60 service packages
    "api":     [f"api_{i}" for i in range(30)],           # 30 API layer packages
    "app":     [f"app_{i}" for i in range(20)],           # 20 application entry points
}

LAYER_ORDER = ["core", "infra", "domain", "service", "api", "app"]

deps = {}  # module -> [modules it depends on]

for layer_idx, layer_name in enumerate(LAYER_ORDER):
    modules = LAYERS[layer_name]
    for mod in modules:
        mod_deps = []

        # Each module depends on 0-3 modules from the SAME layer (peer deps)
        peers = [m for m in modules if m != mod]
        if peers and random.random() < 0.3:
            mod_deps.extend(random.sample(peers, min(2, len(peers))))

        # Each module depends on 1-5 modules from LOWER layers (real deps flow down)
        for lower_idx in range(layer_idx):
            lower_layer = LAYERS[LAYER_ORDER[lower_idx]]
            if lower_layer:
                count = random.randint(1, min(3, len(lower_layer)))
                mod_deps.extend(random.sample(lower_layer, count))

        # Remove duplicates
        deps[mod] = list(set(mod_deps))

all_modules = set(deps.keys())
total_edges = sum(len(d) for d in deps.values())
print(f"BUILD SYSTEM: {len(all_modules)} modules, {total_edges} dependency edges\n")

# ============================================================================
# TOPOLOGICAL SORT — Kahn's Algorithm (BFS-based)
# ============================================================================
# This is the EXACT same topological sort you know from DSA.
# The "nodes" are real build targets, not integers in a textbook.

# Build adjacency: dep -> [things that depend on it]
graph = defaultdict(list)
in_degree = defaultdict(int)

for mod in all_modules:
    in_degree.setdefault(mod, 0)

for mod, requirements in deps.items():
    for req in requirements:
        graph[req].append(mod)
        in_degree[mod] += 1

queue = deque([n for n in all_modules if in_degree[n] == 0])
order = []

while queue:
    node = queue.popleft()
    order.append(node)
    for neighbor in graph[node]:
        in_degree[neighbor] -= 1
        if in_degree[neighbor] == 0:
            queue.append(neighbor)

if len(order) != len(all_modules):
    missing = all_modules - set(order)
    print(f"⚠️  CYCLE DETECTED — topological sort incomplete!")
    print(f"   {len(missing)} modules stuck in cycle")

    # --- Find the actual cycle using DFS ---
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in all_modules}
    cycle_path = []

    def find_cycle(node, path):
        color[node] = GRAY
        path.append(node)
        for dep in deps.get(node, []):
            if color[dep] == GRAY:
                idx = path.index(dep)
                cycle_path.extend(path[idx:] + [dep])
                return True
            if color[dep] == WHITE and find_cycle(dep, path):
                return True
        path.pop()
        color[node] = BLACK
        return False

    for m in missing:
        if color[m] == WHITE:
            if find_cycle(m, []):
                break

    if cycle_path:
        print(f"   Cycle: {' → '.join(cycle_path)}")
else:
    print(f"✅ VALID BUILD ORDER — all {len(order)} modules sorted")
    print(f"\n   First 10 (build these first — zero or fewest deps):")
    for i, mod in enumerate(order[:10], 1):
        dep_count = len(deps[mod])
        print(f"     {i:3d}. {mod:20s} ({dep_count} deps)")
    print(f"\n   Last 5 (build these last — most deps):")
    for i, mod in enumerate(order[-5:], len(order)-4):
        dep_count = len(deps[mod])
        print(f"     {i:3d}. {mod:20s} ({dep_count} deps)")

# ============================================================================
# PARALLEL EXECUTION GROUPS (BFS levels)
# ============================================================================
# Modules at the same BFS level have no dependency between them.
# A real scheduler uses this to parallelize.

in_deg_copy = {mod: len(requirements) for mod, requirements in deps.items()}
level_queue = deque([(n, 0) for n in all_modules if in_deg_copy[n] == 0])
levels = defaultdict(list)

while level_queue:
    node, lvl = level_queue.popleft()
    levels[lvl].append(node)
    for neighbor in graph[node]:
        in_deg_copy[neighbor] -= 1
        if in_deg_copy[neighbor] == 0:
            level_queue.append((neighbor, lvl + 1))

print(f"\n{'='*60}")
print(f"PARALLEL EXECUTION GROUPS")
print(f"{'='*60}")
print(f"(Modules in the same level can build simultaneously)\n")
for lvl in sorted(levels.keys()):
    mods = sorted(levels[lvl])
    print(f"  Level {lvl:2d}: {len(mods):3d} modules can run in parallel")
    if len(mods) <= 8:
        print(f"           {', '.join(mods)}")
    else:
        print(f"           {', '.join(mods[:5])} ... and {len(mods)-5} more")

critical_path_len = max(levels.keys()) + 1
max_parallel = max(len(v) for v in levels.values())
print(f"\n  CRITICAL PATH: {critical_path_len} sequential levels")
print(f"  MAX PARALLELISM: {max_parallel} modules at once (Level {max(levels.keys(), key=lambda k: len(levels[k]))})")
print(f"\n  If each build step takes ~5s:")
print(f"    Sequential: {len(all_modules) * 5}s ({len(all_modules) * 5 / 60:.0f} min)")
print(f"    Parallel:   {critical_path_len * 5}s ({critical_path_len * 5 / 60:.1f} min)")
print(f"    Speedup:    {len(all_modules) / critical_path_len:.1f}x")
```

**What you'll see**: A valid build order for 200 modules, parallel execution groups showing massive speedup potential, and the critical path. If you were building Bazel — this is the core of what it does.

### 1.3 — Break It: Cycle Detection

Add this after the `deps` dictionary is built (before `all_modules = ...`) and re-run:

```python
# INTENTIONAL CYCLE: core_0 depends on service_5, but service_5 already depends on core_0
deps["core_0"].append("service_5")
```

The topological sort will fail and tell you exactly which modules are stuck. In a real system:
- **Python**: You get an `ImportError` or silent partial initialization — the error message doesn't say "cycle," it says an attribute doesn't exist. Notoriously hard to debug.
- **Terraform**: `terraform plan` hangs or errors with "cycle detected in resource dependencies."
- **Docker Compose**: Services with circular `depends_on` won't start.

An undetected cycle doesn't error cleanly — it **deadlocks or infinite-loops**. Every real dependency resolver runs cycle detection **before scheduling**, not after something hangs.

### 1.4 — Parallelization Comes From the Graph Structure

The parallel execution groups output from 1.2 is the key insight. The reason DAG-based schedulers (Spark, Airflow, distributed build systems) can run tasks in parallel safely is that **independent branches of the graph have no ordering constraint between them**. The graph structure itself tells the scheduler what's safe to parallelize — not a manual parallel/sequential flag a human sets.

The **critical path** (longest chain of sequential dependencies) determines your minimum build time regardless of how many CPUs you throw at it. Everything else is parallelizable around it. This is why understanding your dependency graph matters at scale — the difference between a 16-minute sequential build and a 1-minute parallel build is the graph structure.

---

## Section 2 — Service and System Topology as a Graph

### 2.1 — Your Architecture IS a Graph Whether You Modeled It as One or Not

Every service-to-service call is an edge. Every service is a node. You don't have to explicitly model it as a graph — it already is one. When you open Datadog or Jaeger and look at a request trace, you're looking at a subgraph of your service topology. Aggregate all your traces and you get the full service dependency graph.

In production, this graph is how you answer questions like:
- "If the auth service goes down, what else breaks?" (blast radius)
- "Which service is the single point of failure?" (hot nodes / supernodes)
- "Can two services deadlock each other?" (cycle detection)
- "What's the minimum latency path from the user to Stripe?" (shortest path)

All of these are graph traversal problems — the same BFS/DFS you know from DSA, just running on infrastructure instead of textbook arrays.

### 2.2 — Blast Radius via Graph Traversal

**Blast radius**: the scope of what breaks if one node fails. In incident response, this is the first question: "service X is down — what's affected?"

The answer is a graph traversal. Start at the failing node, traverse **reverse edges** (follow the "depends-on" relationship backwards to find everything that depends on the failing node). Every node you can reach is potentially affected. This is the same BFS you used in DSA for level-order traversal, applied to failure propagation instead of tree levels.

A request trace during an incident is literally a path through this graph. The blast radius is the union of all paths that pass through the failing node. The graph gives you this answer in O(V+E) time — no manual inspection of service configs needed.

### 2.3 — Hot Nodes / Supernodes

**Hot node (supernode)**: a node with disproportionately high **in-degree** — meaning many other nodes depend on it. In a service architecture, this is your shared auth service, your shared cache, your central database. In a social graph, it's the celebrity account with 50 million followers.

This is a **structural property of the graph**, not a code quality issue. You detect it by literally counting incoming edges per node — the node with the highest in-degree is your hottest node. It's also where an outage will hurt worst (highest blast radius), and where extra redundancy and circuit-breaking earns its cost.

**Adjacency structure** (term from graph theory): the data structure that stores which nodes connect to which. An adjacency list maps each node to its list of neighbors. An adjacency matrix uses a 2D array. For sparse graphs (most real service graphs — 50 services don't each call all 49 others), adjacency lists are more efficient. Every graph algorithm in this document uses adjacency lists.

The concept ties directly to DSA: in-degree is just `len(adj_reverse[node])` — counting how many nodes have an edge pointing at this node.

### 2.4 — Cycles in Service Graphs Are a Real Anti-Pattern

You already know cycle detection from DSA (DFS with three-color marking: WHITE=unvisited, GRAY=in current path, BLACK=fully explored; hitting a GRAY node means you've found a cycle).

In a build system (Section 1.3), a cycle means a failed build. Annoying but fixable.

In a service graph, a cycle with **synchronous calls** is far worse. Two services calling each other synchronously (A calls B, B calls A) creates the same deadlock risk as a circular build dependency, **plus** a distributed-systems-specific failure mode: a slow response in one direction cascades into the other, doubling latency and doubling the chance of timeout-triggered cascading failure. The cost of being wrong here is **live user-facing latency and outages**, not a failed build.

This is why service mesh tools (Istio, Linkerd) and architecture linters flag synchronous cycles as a critical anti-pattern. The detection algorithm is identical — DFS cycle detection from DSA — but the consequence of missing it is production downtime.

### 2.2–2.4 Build Task + 3.1–3.3 Algorithms

The script below covers all of Sections 2.2–3.3 in one runnable file. It builds the service graph and then runs every algorithm discussed above against it.

**Save as `graph_service.py` and run it:**

```python
"""
Service topology graph — realistic 50-service e-commerce platform.
Blast radius, hot node detection, cycle detection, shortest path,
connected components, and betweenness centrality.

Every algorithm here is something you already know from DSA,
applied to infrastructure instead of textbook problems.
"""

from collections import defaultdict, deque
import heapq

# ============================================================================
# REALISTIC SERVICE GRAPH — E-COMMERCE PLATFORM (~50 services)
# ============================================================================
# This mirrors what you'd actually see at a mid-size company.
# Edge weights = p99 latency in ms between services.

edges = [
    # --- API Gateway layer ---
    ("api_gateway", "auth_service", 15),
    ("api_gateway", "rate_limiter", 5),
    ("api_gateway", "user_service", 25),
    ("api_gateway", "product_service", 20),
    ("api_gateway", "order_service", 30),
    ("api_gateway", "search_service", 40),
    ("api_gateway", "recommendation_service", 35),

    # --- Auth/Identity ---
    ("auth_service", "user_service", 10),
    ("auth_service", "session_store", 5),
    ("auth_service", "token_service", 8),

    # --- User domain ---
    ("user_service", "user_db", 10),
    ("user_service", "cache_service", 3),
    ("user_service", "notification_service", 20),

    # --- Product domain ---
    ("product_service", "product_db", 12),
    ("product_service", "cache_service", 3),
    ("product_service", "inventory_service", 15),
    ("product_service", "pricing_service", 10),
    ("product_service", "image_service", 25),

    # --- Order domain (the complex one) ---
    ("order_service", "order_db", 10),
    ("order_service", "payment_service", 200),
    ("order_service", "inventory_service", 15),
    ("order_service", "shipping_service", 50),
    ("order_service", "notification_service", 20),
    ("order_service", "fraud_service", 100),
    ("order_service", "tax_service", 30),

    # --- Payment (external dependency — slow and critical) ---
    ("payment_service", "payment_db", 10),
    ("payment_service", "stripe_api", 500),        # external — slowest edge
    ("payment_service", "fraud_service", 80),
    ("payment_service", "ledger_service", 15),

    # --- Fraud detection ---
    ("fraud_service", "fraud_db", 10),
    ("fraud_service", "ml_scoring_service", 150),
    ("fraud_service", "user_service", 10),         # checks user history

    # --- Search ---
    ("search_service", "elasticsearch", 30),
    ("search_service", "product_service", 20),
    ("search_service", "cache_service", 3),

    # --- Recommendations ---
    ("recommendation_service", "ml_scoring_service", 100),
    ("recommendation_service", "user_service", 15),
    ("recommendation_service", "product_service", 20),
    ("recommendation_service", "cache_service", 3),

    # --- Shipping ---
    ("shipping_service", "shipping_db", 10),
    ("shipping_service", "fedex_api", 300),        # external
    ("shipping_service", "ups_api", 280),          # external
    ("shipping_service", "notification_service", 20),

    # --- Inventory ---
    ("inventory_service", "inventory_db", 8),
    ("inventory_service", "cache_service", 3),
    ("inventory_service", "notification_service", 15),  # low-stock alerts

    # --- Notification (fan-out service) ---
    ("notification_service", "email_service", 50),
    ("notification_service", "sms_service", 40),
    ("notification_service", "push_service", 30),

    # --- Infrastructure shared services ---
    ("email_service", "sendgrid_api", 200),        # external
    ("sms_service", "twilio_api", 150),            # external

    # --- Monitoring/Observability (everything reports here) ---
    ("api_gateway", "metrics_collector", 2),
    ("auth_service", "metrics_collector", 2),
    ("order_service", "metrics_collector", 2),
    ("payment_service", "metrics_collector", 2),
    ("metrics_collector", "prometheus", 5),
    ("prometheus", "alertmanager", 3),
    ("alertmanager", "pagerduty_api", 100),        # external

    # --- Logging ---
    ("api_gateway", "log_aggregator", 1),
    ("order_service", "log_aggregator", 1),
    ("payment_service", "log_aggregator", 1),
    ("log_aggregator", "elasticsearch", 10),       # logs go to same ES as search
]

# ============================================================================
# BUILD ADJACENCY STRUCTURES
# ============================================================================

adj = defaultdict(list)        # forward: caller → [callees]
rev_adj = defaultdict(list)    # reverse: callee → [callers]
all_nodes = set()
edge_weights = {}

for src, dst, w in edges:
    adj[src].append(dst)
    rev_adj[dst].append(src)
    edge_weights[(src, dst)] = w
    all_nodes.add(src)
    all_nodes.add(dst)

print(f"SERVICE GRAPH: {len(all_nodes)} services, {len(edges)} call edges\n")

# ============================================================================
# 2.2 — BLAST RADIUS via graph traversal
# ============================================================================
# Blast radius = the scope of what breaks if one node fails.
# Answerable by traversing REVERSE edges from the failing node outward.
# Same BFS from DSA, applied to failure propagation.

def blast_radius(failing_node):
    """
    BFS along REVERSE edges. Every node reachable backwards depends on
    this node — if it fails, they all potentially break.
    """
    visited = set()
    queue = deque([failing_node])
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for upstream in rev_adj[node]:
            if upstream not in visited:
                queue.append(upstream)
    visited.discard(failing_node)
    return visited

print("=" * 70)
print("BLAST RADIUS ANALYSIS — \"What breaks if X goes down?\"")
print("=" * 70)

# Test the services you'd actually worry about in production
targets = [
    "cache_service",           # shared cache — everything uses it
    "user_service",            # identity — auth depends on it
    "payment_service",         # money path
    "stripe_api",              # external — you don't control it
    "notification_service",    # fan-out
    "elasticsearch",           # shared by search AND logging
    "inventory_service",       # order + product depend on it
]

blast_results = {}
for target in targets:
    affected = blast_radius(target)
    blast_results[target] = affected
    print(f"\n  If '{target}' fails:")
    print(f"    Blast radius = {len(affected)} services affected")
    if len(affected) <= 12:
        print(f"    Affected: {', '.join(sorted(affected))}")
    else:
        top = sorted(affected)[:8]
        print(f"    Affected: {', '.join(top)} ... +{len(affected)-8} more")

# ============================================================================
# 2.3 — HOT NODES / SUPERNODES
# ============================================================================
# A supernode = high in-degree = many things depend on it.
# Disproportionate blast radius. Detectable by counting incoming edges.
# Not a code quality issue — a structural property of the graph.

print(f"\n{'='*70}")
print("HOT NODE ANALYSIS (in-degree = how many services call this)")
print("=" * 70)

in_deg = defaultdict(int)
out_deg = defaultdict(int)
for src, dst, _ in edges:
    in_deg[dst] += 1
    out_deg[src] += 1

hottest = sorted(all_nodes, key=lambda n: in_deg[n], reverse=True)

print(f"\n  {'Service':<30} {'In-degree':>10} {'Out-degree':>11}  Risk")
print(f"  {'─'*30} {'─'*10} {'─'*11}  {'─'*30}")
for node in hottest[:15]:
    ind = in_deg[node]
    outd = out_deg[node]
    risk = ""
    if ind >= 5:
        risk = "🔴 SUPERNODE — needs redundancy + circuit breakers"
    elif ind >= 3:
        risk = "⚠️  hot node — monitor closely"
    elif ind >= 2:
        risk = "⚡ moderate coupling"
    print(f"  {node:<30} {ind:>10} {outd:>11}  {risk}")

print("""
  WHAT TO DO WITH HOT NODES:
  These are where extra redundancy and circuit-breaking earns its cost.
  A shared cache (cache_service) with 5+ dependents needs:
    - Multiple replicas
    - Circuit breakers so one slow consumer doesn't DOS the cache for everyone
    - Graceful degradation: if cache is down, services should fall back to DB
      (slower, but alive) — not crash.
  This is a structural property of the graph, not a code quality issue.
""")

# ============================================================================
# 2.4 — CYCLE DETECTION
# ============================================================================

print("=" * 70)
print("CYCLE DETECTION — service-level")
print("=" * 70)

def find_cycles(adj_list, nodes):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    cycles = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for neighbor in adj_list.get(node, []):
            if color.get(neighbor) == GRAY:
                idx = path.index(neighbor)
                cycles.append(path[idx:] + [neighbor])
            elif color.get(neighbor, WHITE) == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for node in nodes:
        if color[node] == WHITE:
            dfs(node, [])
    return cycles

cycles = find_cycles(adj, all_nodes)
if cycles:
    print(f"\n  ⚠️  {len(cycles)} CYCLE(S) FOUND:")
    for c in cycles:
        print(f"    {' → '.join(c)}")
    print("""
  WHY THIS IS WORSE THAN A BUILD SYSTEM CYCLE:
  A cycle in a build graph = a failed build. Annoying, fixable.
  A cycle in a service graph with synchronous calls = A calls B calls A =
  distributed deadlock. Slow response in one direction cascades into the
  other, doubling latency, doubling timeout probability.
  The cost of being wrong: live user-facing outage, not a failed CI run.
""")
else:
    print("\n  ✅ No synchronous cycles detected.")
    print("     Note: order_service → fraud_service → user_service is NOT a cycle")
    print("     because user_service doesn't call back into order_service.")
    print("     If it did — you'd have A→B→C→A, which is a cascading latency bomb.")

# ============================================================================
# 3.1 — SHORTEST PATH (Dijkstra)
# ============================================================================
# Real use: what's the fastest/cheapest path a request takes through your system?
# During an incident: "how does a user checkout reach Stripe?" — the answer
# is this path. If there's a 500ms external call in the middle, you now know
# the bottleneck without reading code.

print(f"\n{'='*70}")
print("SHORTEST PATH — Dijkstra's Algorithm")
print("=" * 70)
print("(\"What's the minimum latency path from X to Y?\")")

def dijkstra(source):
    """
    Finds the lowest-cost path from source to every reachable node.
    You know BFS finds shortest path in unweighted graphs.
    Dijkstra is the weighted version — uses a priority queue (min-heap)
    so it always processes the cheapest next node.
    """
    dist = {n: float('inf') for n in all_nodes}
    prev = {n: None for n in all_nodes}
    dist[source] = 0
    pq = [(0, source)]

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v in adj[u]:
            w = edge_weights.get((u, v), 1)
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                prev[v] = u
                heapq.heappush(pq, (dist[v], v))
    return dist, prev

def get_path(prev, target):
    path = []
    node = target
    while node is not None:
        path.append(node)
        node = prev[node]
    return list(reversed(path))

# Key questions you'd ask during an incident or architecture review
queries = [
    ("api_gateway", "stripe_api",    "User checkout → payment provider"),
    ("api_gateway", "elasticsearch", "User search → search backend"),
    ("api_gateway", "fedex_api",     "User → shipping provider"),
    ("api_gateway", "pagerduty_api", "Request error → alert fired"),
    ("order_service", "twilio_api",  "Order placed → SMS notification"),
]

for src, dst, desc in queries:
    dist, prev = dijkstra(src)
    if dist[dst] < float('inf'):
        path = get_path(prev, dst)
        print(f"\n  {desc}:")
        print(f"    Latency: {dist[dst]}ms")
        print(f"    Path:    {' → '.join(path)}")
        # Identify the bottleneck edge
        max_edge_w = 0
        max_edge = ("", "")
        for i in range(len(path)-1):
            w = edge_weights.get((path[i], path[i+1]), 0)
            if w > max_edge_w:
                max_edge_w = w
                max_edge = (path[i], path[i+1])
        if max_edge_w > 50:
            print(f"    ⚠️  Bottleneck: {max_edge[0]} → {max_edge[1]} ({max_edge_w}ms)")

# ============================================================================
# 3.2 — CONNECTED COMPONENTS
# ============================================================================

print(f"\n{'='*70}")
print("CONNECTED COMPONENTS (treating edges as undirected)")
print("=" * 70)

def connected_components(nodes, fwd, rev):
    """
    Find connected components treating directed graph as undirected.

    Real uses:
    - Fraud ring detection (accounts sharing devices/IPs = edges)
    - Finding isolated subsystems in your architecture
    - Deduplication (records sharing identifiers = edges)
    """
    visited = set()
    components = []

    for start_node in nodes:
        if start_node in visited:
            continue
        component = set()
        queue = deque([start_node])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for nb in fwd.get(node, []):
                if nb not in visited:
                    queue.append(nb)
            for nb in rev.get(node, []):
                if nb not in visited:
                    queue.append(nb)
        components.append(component)
    return components

comps = connected_components(all_nodes, adj, rev_adj)
print(f"\n  Found {len(comps)} connected component(s):")
for i, comp in enumerate(comps):
    if len(comp) <= 10:
        print(f"    Component {i+1} ({len(comp)} nodes): {', '.join(sorted(comp))}")
    else:
        print(f"    Component {i+1} ({len(comp)} nodes): {', '.join(sorted(comp)[:8])} ... +{len(comp)-8} more")

if len(comps) == 1:
    print("""
  ONE SINGLE COMPONENT — every service can reach every other service.
  No isolation boundary. If any critical node fails (cache_service, user_db),
  the blast radius is potentially the entire system.

  If you had 2+ components, some services would be fully isolated —
  either intentionally (good: fault isolation) or accidentally
  (bad: orphaned service nobody monitors).
""")

# ============================================================================
# 3.3 — BETWEENNESS CENTRALITY
# ============================================================================

print("=" * 70)
print("CENTRALITY — finding structurally critical nodes in-degree can miss")
print("=" * 70)

def betweenness_centrality(nodes, adj_list):
    """
    Betweenness centrality: how many shortest paths between OTHER node pairs
    pass through a given node.

    Unlike in-degree (counts direct connections), betweenness captures
    BRIDGE NODES — they sit on many shortest paths even with modest
    direct connection count.

    A node with moderate in-degree but high betweenness is a hidden
    single point of failure that simple hot-node detection misses.
    """
    centrality = {n: 0.0 for n in nodes}
    node_list = list(nodes)

    for source in node_list:
        dist_map = {source: 0}
        num_paths = {source: 1}
        stack = []
        predecessors = defaultdict(list)
        queue = deque([source])

        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in adj_list.get(v, []):
                if w not in dist_map:
                    dist_map[w] = dist_map[v] + 1
                    queue.append(w)
                if dist_map.get(w) == dist_map[v] + 1:
                    num_paths[w] = num_paths.get(w, 0) + num_paths[v]
                    predecessors[w].append(v)

        dependency = {n: 0.0 for n in nodes}
        while stack:
            w = stack.pop()
            for v in predecessors[w]:
                ratio = num_paths.get(v, 1) / max(num_paths.get(w, 1), 1)
                dependency[v] += ratio * (1 + dependency[w])
            if w != source:
                centrality[w] += dependency[w]

    n = len(node_list)
    if n > 2:
        norm = 1.0 / ((n - 1) * (n - 2))
        centrality = {k: v * norm for k, v in centrality.items()}
    return centrality

bc = betweenness_centrality(all_nodes, adj)
bc_sorted = sorted(bc.items(), key=lambda x: x[1], reverse=True)

# Compare centrality ranking to in-degree ranking
indeg_rank = {node: rank for rank, node in enumerate(sorted(all_nodes, key=lambda n: in_deg[n], reverse=True))}

print(f"\n  {'Service':<30} {'Betweenness':>12} {'In-degree':>10} {'In-deg Rank':>12}  Mismatch?")
print(f"  {'─'*30} {'─'*12} {'─'*10} {'─'*12}  {'─'*35}")
for i, (node, score) in enumerate(bc_sorted[:15]):
    ind = in_deg[node]
    irank = indeg_rank[node] + 1
    mismatch = ""
    if i < 5 and irank > 10:
        mismatch = "⚠️  HIGH centrality, LOW in-degree = hidden SPOF!"
    elif i < 5 and irank > 5:
        mismatch = "⚡ centrality rank ≠ in-degree rank"
    print(f"  {node:<30} {score:>12.4f} {ind:>10} {irank:>12}  {mismatch}")

print("""
  KEY LESSON: The betweenness and in-degree rankings often disagree.
  In-degree says "cache_service is the hottest" (most things call it).
  Betweenness might say "notification_service is the most critical bridge"
  (it sits on every path from business logic to external notification channels).

  A bridge node with moderate in-degree but high betweenness is a DIFFERENT,
  easy-to-miss category of single point of failure. The disagreement between
  these two metrics is the actual insight.
""")
```

---

## Section 3 — Product Features That Are Secretly Graph Problems

Sections 2's build task already included Dijkstra (3.1), Connected Components (3.2), and Betweenness Centrality (3.3) running against the service graph. Below is the theory for each, plus standalone product-domain exercises.

### 3.1 — Shortest Path: Beyond Routing

**Dijkstra's algorithm** (define plainly): finds the lowest-cost path between two nodes in a weighted graph. You know BFS finds shortest path in unweighted graphs (every edge costs 1). Dijkstra extends this to weighted graphs — instead of a regular queue, it uses a **priority queue (min-heap)** so it always processes the cheapest next node first. Time complexity: O((V+E) log V) with a binary heap.

The DSA tie-back: BFS explores nodes level by level (distance 1, then distance 2, etc.). Dijkstra does the same thing but with arbitrary edge weights — it explores nodes in order of cumulative cost, not hop count.

**Obvious use**: Google Maps, Uber routing, logistics.

**Non-obvious uses you'll actually hit in product/service work**:

| Scenario | Nodes | Edges | Weight |
|---|---|---|---|
| Network hop optimization | Servers/routers | Network links | Latency |
| Cheapest payment routing | Payment processors | Transfer routes | Fee % |
| Incident escalation chain | People/teams | Escalation rules | Response time |
| Social: degrees of separation | Users | Follow/friend links | 1 (unweighted → use BFS) |
| Supply chain optimization | Warehouses | Transport routes | Cost or time |
| Architecture review | Services | API calls | p99 latency |

During an incident, if you need to know "how does a user request reach Stripe?" — the answer is the shortest path through your service graph. If that path has a node with a 500ms external call in the middle, you now know where the bottleneck is without reading code. The graph told you.

### 3.2 — Connected Components: Finding Clusters

**Connected component**: a maximal set of nodes where every node can reach every other node (following edges in either direction). If you treat a directed graph as undirected, the connected components tell you which groups of nodes are isolated from each other.

The DSA tie-back: this is just BFS/DFS from every unvisited node. Each time you start a new BFS from an unvisited node, you've found a new component. Same algorithm, different name.

**Real product uses**:
- **Fraud ring detection**: Accounts connected through shared payment methods, devices, or IP addresses form a component. A large component of accounts with shared attributes = a potential fraud ring to investigate.
- **Deduplication**: Records connected through shared identifiers (same email, same phone, same address) form a component — they're probably the same entity.
- **Service architecture**: Finding fully isolated subsystems (a cluster of services with no path to the rest). This is either intentional isolation (good — fault boundaries) or an accidentally orphaned system nobody's monitoring (bad).
- **Network segmentation**: In network security, connected components tell you which network segments can communicate and which are properly isolated.

### 3.3 — Centrality / Ranking: The Real Single Point of Failure

**Betweenness centrality**: measures how many shortest paths between OTHER node pairs pass through a given node. High betweenness = this node is a **bridge** — it sits on many communication paths even if it doesn't have the most direct connections.

The DSA tie-back: betweenness centrality is computed by running BFS from every node (to find all shortest paths), then back-propagating to count how many of those paths pass through each intermediate node. It's O(V × (V+E)) — expensive on huge graphs, trivial on service-scale graphs.

**Why this matters more than in-degree**: In-degree (Section 2.3) counts direct dependents. It finds the obviously popular nodes. But betweenness captures a **different category of critical node** — one that might have only 3 direct connections but sits on every path between two large clusters. Remove it, and the clusters become disconnected.

**Real product uses**:
- **PageRank** (Google's original search ranking): Not just in-degree (count of incoming links), but recursive importance — a link from a high-PageRank page is worth more. Same intuition as betweenness: structural position matters more than raw connection count.
- **Recommendation engines**: "People who are central to communities you overlap with" is a better recommendation signal than "people with the most followers."
- **Org chart analysis**: The person with the highest betweenness in your company's Slack/email graph is often not the highest-ranked person — they're the person whose departure would most disrupt information flow. This is a different, easy-to-miss category of single point of failure.
- **Infrastructure**: A service with moderate in-degree but high betweenness is a hidden SPOF. In-degree told you cache_service is the hottest; betweenness might tell you notification_service is the most critical bridge. That disagreement is the actual insight.

### 3.1 Exercise — Social Graph: Degrees of Separation + Friend Recommendations

**Save as `graph_social.py` and run it:**

```python
"""
Social graph — degrees of separation, friend recommendations, bridge nodes.
This is how LinkedIn's "2nd connection" and "People You May Know" work.

BFS on an unweighted graph. You already know BFS.
"""

from collections import defaultdict, deque

# ============================================================================
# REALISTIC SOCIAL GRAPH — 30 people, 4 clusters (like real social networks)
# ============================================================================
# Real social networks are "clustered" — most connections are within groups
# (coworkers, college friends, family), with a few bridge connections between groups.

social = {
    # --- Engineering team at Company A ---
    "alice":   ["bob", "carol", "dave", "eve"],
    "bob":     ["alice", "carol", "frank"],
    "carol":   ["alice", "bob", "dave"],
    "dave":    ["alice", "carol", "grace"],        # bridge → Product
    "eve":     ["alice", "frank"],
    "frank":   ["bob", "eve", "george"],

    # --- Product team at Company A ---
    "grace":   ["dave", "henry", "ivan", "judy"],  # dave is bridge from Engineering
    "henry":   ["grace", "ivan", "karl"],
    "ivan":    ["grace", "henry", "judy"],
    "judy":    ["grace", "ivan"],

    # --- College friends (external to Company A) ---
    "karl":    ["henry", "lisa", "mike", "nancy"], # henry is bridge from Product
    "lisa":    ["karl", "mike", "oscar"],
    "mike":    ["karl", "lisa", "nancy"],
    "nancy":   ["karl", "mike"],
    "oscar":   ["lisa", "pete"],                   # bridge → Industry network

    # --- Industry network / Conference connections ---
    "pete":    ["oscar", "quinn", "rachel", "alice"],  # loops back to alice!
    "quinn":   ["pete", "rachel", "steve"],
    "rachel":  ["pete", "quinn", "tina", "uma"],
    "steve":   ["quinn", "victor"],
    "tina":    ["rachel", "uma"],
    "uma":     ["rachel", "tina", "victor"],
    "victor":  ["steve", "uma", "wendy"],

    # --- Isolated cluster (Company B — no connection to Company A) ---
    "wendy":   ["victor", "xander", "yara"],
    "xander":  ["wendy", "yara", "zack"],
    "yara":    ["wendy", "xander"],
    "zack":    ["xander"],
}

# ============================================================================
# DEGREES OF SEPARATION
# ============================================================================

def bfs_shortest(graph, source, target):
    """BFS — shortest path in unweighted graph. Same BFS as DSA."""
    if source == target:
        return 0, [source]
    visited = {source}
    queue = deque([(source, [source])])
    while queue:
        node, path = queue.popleft()
        for nb in graph.get(node, []):
            if nb == target:
                return len(path), path + [nb]
            if nb not in visited:
                visited.add(nb)
                queue.append((nb, path + [nb]))
    return -1, []

pairs = [
    ("alice", "judy"),     # Engineering → Product (through dave & grace)
    ("alice", "nancy"),    # Engineering → College friends
    ("alice", "victor"),   # Engineering → Industry → far edge
    ("bob", "zack"),       # across the entire graph
    ("frank", "tina"),     # non-obvious path
    ("alice", "alice"),    # self
]

print("DEGREES OF SEPARATION\n")
print(f"  {'Pair':<25} {'Degrees':>8}  Path")
print(f"  {'─'*25} {'─'*8}  {'─'*50}")
for a, b in pairs:
    deg, path = bfs_shortest(social, a, b)
    label = {0: "self", 1: "1st", 2: "2nd", 3: "3rd"}.get(deg, f"{deg}th")
    path_str = ' → '.join(path) if path else "no path"
    print(f"  {a} → {b:<15} {deg:>8}  {path_str}  ({label})")

# ============================================================================
# FRIEND RECOMMENDATIONS — "People You May Know"
# ============================================================================
# Algorithm: for a given user, find all 2nd-degree connections (friends of
# friends who aren't already friends). Rank by number of mutual friends.
# This is how LinkedIn and Facebook's recommendation engines work at the core.

def recommend_friends(graph, user, top_n=5):
    """
    Find friends-of-friends, ranked by mutual friend count.
    2nd degree connections with the most shared friends = best recommendations.
    """
    direct_friends = set(graph.get(user, []))
    direct_friends.add(user)

    # Count how many mutual friends each 2nd-degree connection has
    mutual_count = defaultdict(int)
    mutual_through = defaultdict(list)

    for friend in graph.get(user, []):
        for fof in graph.get(friend, []):
            if fof not in direct_friends:
                mutual_count[fof] += 1
                mutual_through[fof].append(friend)

    ranked = sorted(mutual_count.items(), key=lambda x: x[1], reverse=True)
    return ranked[:top_n], mutual_through

print(f"\n{'='*60}")
print("FRIEND RECOMMENDATIONS — \"People You May Know\"")
print("=" * 60)

for user in ["alice", "karl", "rachel"]:
    recs, through = recommend_friends(social, user)
    print(f"\n  Recommendations for '{user}':")
    if not recs:
        print(f"    (none — already connected to everyone nearby)")
    for person, count in recs:
        via = ', '.join(through[person][:3])
        print(f"    → {person:<12} ({count} mutual: {via})")

# ============================================================================
# BRIDGE NODE DETECTION — who connects the clusters?
# ============================================================================

print(f"\n{'='*60}")
print("BRIDGE NODES — removing them disconnects clusters")
print("=" * 60)

def reachable_from(graph, start, exclude=None):
    visited = set()
    queue = deque([start])
    while queue:
        n = queue.popleft()
        if n in visited or n == exclude:
            continue
        visited.add(n)
        for nb in graph.get(n, []):
            if nb != exclude and nb not in visited:
                queue.append(nb)
    return visited

all_people = set(social.keys())
base_reach = len(reachable_from(social, "alice"))

bridges = []
for person in sorted(social.keys()):
    reach = len(reachable_from(social, "alice", exclude=person))
    lost = base_reach - reach - 1  # -1 for the excluded person
    if lost > 0:
        bridges.append((person, lost))

bridges.sort(key=lambda x: x[1], reverse=True)
print(f"\n  (Measured from alice's perspective: how many people become unreachable)\n")
for person, lost in bridges:
    bar = "█" * lost
    print(f"  Remove '{person}': alice loses {lost:>2} connections  {bar}")

print("""
  INSIGHT: Bridge nodes (dave, henry, oscar, pete) are the connectors
  between social clusters. In a social product:
    - These users are disproportionately valuable (they spread content across groups)
    - If they churn, entire clusters become unreachable for recommendations
    - They're the "super-spreaders" of information/viral content
  Identifying them is literally betweenness centrality from Section 2.
""")
```

### 3.2 — Fraud Ring Detection via Connected Components

**Save as `graph_fraud.py` and run it:**

```python
"""
Fraud ring detection via connected components.
Accounts sharing devices, IPs, or payment methods form edges.
A connected component of accounts sharing attributes = potential fraud ring.

Same BFS-based connected components as the service graph exercise.
Different domain. Same algorithm.
"""

from collections import defaultdict, deque

# ============================================================================
# SIMULATED ACCOUNT DATA — shared attributes create edges
# ============================================================================
# In production, you'd pull this from your payment/auth database.
# Each shared device, IP, or card between two accounts = suspicious link.

accounts = {
    # --- Legitimate cluster (same household, shared device is normal) ---
    "acc_001": {"devices": ["dev_A"], "ips": ["1.1.1.1"], "cards": ["card_100"], "txn_count": 342},
    "acc_002": {"devices": ["dev_A"], "ips": ["1.1.1.1"], "cards": ["card_101"], "txn_count": 128},

    # --- Fraud ring 1: 5 accounts sharing devices and cards suspiciously ---
    "acc_003": {"devices": ["dev_B", "dev_C"], "ips": ["2.2.2.2"], "cards": ["card_200"], "txn_count": 3},
    "acc_004": {"devices": ["dev_C"],          "ips": ["2.2.2.3"], "cards": ["card_200", "card_201"], "txn_count": 7},
    "acc_005": {"devices": ["dev_D"],          "ips": ["2.2.2.3"], "cards": ["card_201"], "txn_count": 2},
    "acc_006": {"devices": ["dev_D", "dev_E"], "ips": ["2.2.2.4"], "cards": ["card_202"], "txn_count": 1},
    "acc_007": {"devices": ["dev_E"],          "ips": ["2.2.2.4"], "cards": ["card_203"], "txn_count": 5},

    # --- Fraud ring 2: different pattern — shared IPs across countries ---
    "acc_008": {"devices": ["dev_F"], "ips": ["3.3.3.3", "4.4.4.4"], "cards": ["card_300"], "txn_count": 12},
    "acc_009": {"devices": ["dev_G"], "ips": ["4.4.4.4"],           "cards": ["card_301"], "txn_count": 8},
    "acc_010": {"devices": ["dev_H"], "ips": ["4.4.4.4", "5.5.5.5"], "cards": ["card_302"], "txn_count": 4},
    "acc_011": {"devices": ["dev_I"], "ips": ["5.5.5.5"],           "cards": ["card_303"], "txn_count": 2},

    # --- Clean isolated accounts ---
    "acc_012": {"devices": ["dev_J"],  "ips": ["6.6.6.6"], "cards": ["card_400"], "txn_count": 891},
    "acc_013": {"devices": ["dev_K"],  "ips": ["7.7.7.7"], "cards": ["card_401"], "txn_count": 1205},
    "acc_014": {"devices": ["dev_L"],  "ips": ["8.8.8.8"], "cards": ["card_402"], "txn_count": 456},

    # --- Suspicious single account (shares card with fraud ring 1 member) ---
    "acc_015": {"devices": ["dev_M"],  "ips": ["9.9.9.9"], "cards": ["card_202"], "txn_count": 15},
}

# ============================================================================
# BUILD GRAPH: accounts sharing ANY attribute get an edge
# ============================================================================

attr_to_accounts = defaultdict(set)
for acc_id, attrs in accounts.items():
    for dev in attrs["devices"]:
        attr_to_accounts[f"device:{dev}"].add(acc_id)
    for ip in attrs["ips"]:
        attr_to_accounts[f"ip:{ip}"].add(acc_id)
    for card in attrs["cards"]:
        attr_to_accounts[f"card:{card}"].add(acc_id)

adj = defaultdict(set)
edge_reasons = defaultdict(list)  # (a, b) -> [shared attributes]

for attr_val, accs in attr_to_accounts.items():
    acc_list = list(accs)
    for i in range(len(acc_list)):
        for j in range(i + 1, len(acc_list)):
            a, b = min(acc_list[i], acc_list[j]), max(acc_list[i], acc_list[j])
            adj[a].add(b)
            adj[b].add(a)
            edge_reasons[(a, b)].append(attr_val)

total_edges = sum(len(v) for v in adj.values()) // 2
print(f"FRAUD DETECTION GRAPH: {len(accounts)} accounts, {total_edges} suspicious links\n")

# ============================================================================
# FIND CONNECTED COMPONENTS = POTENTIAL FRAUD RINGS
# ============================================================================

visited = set()
rings = []

for acc in accounts:
    if acc in visited:
        continue
    component = set()
    queue = deque([acc])
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        component.add(node)
        for nb in adj.get(node, set()):
            if nb not in visited:
                queue.append(nb)
    rings.append(component)

rings.sort(key=len, reverse=True)

print("=" * 70)
print("CONNECTED COMPONENTS — POTENTIAL FRAUD RINGS")
print("=" * 70)

for i, ring in enumerate(rings):
    ring_sorted = sorted(ring)
    total_txns = sum(accounts[a]["txn_count"] for a in ring)
    avg_txns = total_txns / len(ring)

    if len(ring) == 1:
        acc = ring_sorted[0]
        print(f"\n  Component {i+1}: ISOLATED ACCOUNT — {acc} ({accounts[acc]['txn_count']} txns) — LOW RISK")
    else:
        risk = "🔴 HIGH" if len(ring) >= 4 else "⚠️  MEDIUM" if len(ring) >= 2 else "LOW"
        print(f"\n  Component {i+1}: {len(ring)} ACCOUNTS — Risk: {risk}")
        print(f"    Avg transactions per account: {avg_txns:.0f} (low avg = suspicious)")
        print(f"    Accounts:")
        for acc in ring_sorted:
            a = accounts[acc]
            print(f"      {acc}: {a['txn_count']:>4} txns | devices={a['devices']} ips={a['ips']} cards={a['cards']}")

        # Show WHY they're linked
        shared = defaultdict(set)
        for a_idx in range(len(ring_sorted)):
            for b_idx in range(a_idx + 1, len(ring_sorted)):
                a, b = ring_sorted[a_idx], ring_sorted[b_idx]
                key = (min(a, b), max(a, b))
                for reason in edge_reasons.get(key, []):
                    shared[reason].add(a)
                    shared[reason].add(b)

        if shared:
            print(f"    Links:")
            for attr, accs in sorted(shared.items()):
                print(f"      {attr} → shared by {', '.join(sorted(accs))}")

print("""
  WHAT A FRAUD ANALYST DOES WITH THIS:
  1. Large components with LOW avg transaction count = suspicious
     (fraud accounts do a few test transactions then go big)
  2. Components connected through DEVICES are higher risk than shared IPs
     (shared IP could be a VPN/office; shared device is harder to explain)
  3. Components with accounts created in quick succession = even more suspicious
     (we didn't track creation date here, but you would in production)

  The algorithm is identical to the service-graph connected components.
  Different domain. Same BFS. Same result structure. Different interpretation.
""")
```

---

## Section 4 — When a Single Machine Can't Hold the Graph

### 4.1 — Why Graphs Don't Shard Like Tables

A relational table shards cleanly because rows are mostly independent — put users A-M on shard 1 and N-Z on shard 2, and most queries hit one shard.

A graph doesn't shard cleanly because **edges connect nodes that might land on different machines**. If user A (shard 1) is friends with user Z (shard 2), querying "friends of A" requires a network hop to shard 2. A multi-hop query ("friends of friends of A") can require crossing partition boundaries repeatedly — each hop is a network round-trip.

This is **graph partitioning**, and it's a genuinely harder problem than table sharding. No solved-by-analogy extension of it.

**Practical strategies real systems use:**

| Strategy | How | Used by |
|---|---|---|
| **Edge-cut partitioning** | Assign nodes to partitions, replicate edges crossing boundaries | Neo4j, JanusGraph |
| **Vertex-cut partitioning** | Replicate high-degree nodes across partitions to reduce edge cuts | PowerGraph, GraphX |
| **Locality-aware placement** | Place tightly-connected subgraphs on the same machine (community detection first) | Social graph systems |
| **Just don't shard** | Keep the whole graph in memory on one machine | Most real engineering work |

### 4.2 — Vertex-Centric Computation

**Vertex-centric computation**: Distributed graph processing frameworks (Spark GraphX, Pregel-model systems) process graphs by having each node compute based only on its own state and its neighbors' state, then exchange updates in synchronized rounds. This avoids needing global graph state on one machine, at the cost of needing multiple rounds to propagate information across the whole graph.

**When this actually matters**: Past a graph that fits comfortably in memory on one machine. Which covers **most real engineering work**.

- A 50-service microservice graph? A laptop handles it.
- A 10,000-product catalog with relationships? Still a laptop.
- A company's 50,000-employee org graph? Still a laptop.
- 10 million user social graph? Still one beefy server (16GB+ RAM).

**Where you genuinely need distributed graph processing:**
- Social graph at 100M+ users (Facebook, LinkedIn scale)
- Web graph for search ranking (billions of pages for PageRank)
- Biological networks (protein interaction graphs, billions of edges)
- Real-time fraud detection on 100M+ transaction streams

If you're not at that scale — and most engineers aren't — a single-machine graph library (NetworkX in Python, igraph, or raw adjacency lists like we've been writing) is correct and sufficient. Most engineers who reach for distributed graph processing don't need it yet.

---

## Section 5 — Failure Modes, Synthesized

Go back through Sections 1-4 after running all scripts. Name one real instance of each from your own outputs:

```
[ ] 1. CYCLE THAT WOULD DEADLOCK (Section 1.3)
    → In graph_dep.py, you added core_0 → service_5 creating a circular dep.
    → In the service graph (2.4): if order_service called fraud_service and
      fraud_service called order_service back synchronously — cascading deadlock.
    Your example from the output: ___________________________________________

[ ] 2. HOT NODE WITH OUTSIZED BLAST RADIUS (Section 2.3)
    → In graph_service.py, which node had the highest in-degree?
    → What was its blast radius from Section 2.2?
    → Is it the one you'd intuitively guess, or a different one?
    Your example: ___________________________________________

[ ] 3. STRUCTURALLY CRITICAL NODE THAT CENTRALITY CAUGHT BUT IN-DEGREE MISSED (Section 3.3)
    → In graph_service.py's centrality output, which node had high betweenness
      but relatively low in-degree?
    → This is the hidden single point of failure — the bridge node.
    Your example: ___________________________________________

[ ] 4. GRAPH SMALL ENOUGH THAT DISTRIBUTED PROCESSING IS PURE OVERHEAD (Section 4.2)
    → Your service graph has ~50 nodes. Your social graph has 26 people.
    → At what scale would you genuinely need distributed graph processing?
    → Why would reaching for GraphX/Pregel here be wrong?
    Your example: ___________________________________________
```

---

## Closing Exercise

Pick one:

**If you have prior AI/agent orchestration context**: If you were adding a knowledge-graph retrieval layer (RAG backed by a graph DB) or a state-machine agent orchestration graph to a service architecture — which structure from this session would it plug into and why?

**If not**: Name one graph problem at your actual work or projects, right now, that you now know how to name and approach — that you'd have previously solved with an ad-hoc nested loop, a pile of if/else, or a brute-force search instead of recognizing the graph structure underneath it.

---

## Quick Reference — When You See These Problems, They're Graph Problems

| You see this at work... | It's actually... | Algorithm |
|---|---|---|
| "What order should these run in?" | Topological sort on a DAG | Kahn's (BFS) or DFS |
| "What can run in parallel?" | Independent nodes at same BFS level | Level-order traversal |
| "What breaks if X fails?" | Blast radius = BFS from failing node | Traversal on reverse edges |
| "What's the fastest/cheapest route?" | Shortest path | Dijkstra (weighted), BFS (unweighted) |
| "Are these things connected?" | Connected components | BFS/DFS |
| "What's the most critical node?" | Centrality analysis | Betweenness centrality |
| "Is there a circular dependency?" | Cycle detection | DFS with 3-color marking |
| "Who are similar users?" | Community detection | Louvain, Label propagation |
| "What should we recommend?" | Link prediction / mutual neighbors | Graph-based collaborative filtering |
| "Is this a fraud ring?" | Connected components on shared-attribute graph | BFS |
| "Can this deadlock?" | Cycle detection on wait-for graph | DFS |
| "Who's the real bottleneck person?" | Betweenness centrality on communication graph | Brandes' algorithm |
| "How viral will this content go?" | Influence propagation | BFS/cascade simulation |

---

## Files to Run

All scripts are standalone Python, zero external dependencies. Save anywhere and run with `python <filename>`:

| File | Sections | What it does |
|---|---|---|
| `graph_dep.py` | 1.2–1.4 | 200-module dependency resolver: topological sort + cycle detection + parallelization |
| `graph_service.py` | 2.1–3.3 | 50-service e-commerce platform: blast radius + hot nodes + cycles + Dijkstra + components + centrality |
| `graph_social.py` | 3.1 | 30-person social graph: degrees of separation + friend recommendations + bridge detection |
| `graph_fraud.py` | 3.2 | 15-account fraud ring detection via connected components on shared attributes |

After running all four, fill in the Section 5 checklist. If you can't fill in every box with a specific example from your own outputs, that's a gap — re-run that section and look at the output carefully.
