# Layer 8: Infrastructure as Code & Advanced Deployment

> Know the concepts and terms. Don't build this yet unless your app demands it.

**The point:** Everything in Layers 1-7 gets you a working, monitored, deployed AI app. Layer 8 is what you reach for when: you need reproducible infrastructure across environments, you need more control than PaaS gives you, or you're managing multiple services. Most of this is premature for a solo developer or small team, but knowing the terms prevents you from being blindsided in interviews or team discussions.

---

## 8.1 — Infrastructure as Code (IaC)

**The problem:** You set up your infrastructure by clicking buttons in AWS/GCP/Render dashboards. It works. Then:
- You need to recreate it for a staging environment → "what did I click?"
- Someone changes a setting in the console → no one knows what changed or why
- New team member joins → "how do I set up the same infrastructure?"

**The solution:** Define infrastructure in code files. Version-controlled, reviewable, reproducible.

### Terraform — the industry standard:

```hcl
# main.tf — defines a Cloud Run service with a Postgres database

# The AI app service
resource "google_cloud_run_service" "app" {
  name     = "my-ai-app"
  location = "asia-south1"

  template {
    spec {
      containers {
        image = "gcr.io/my-project/my-ai-app:latest"

        env {
          name  = "DATABASE_URL"
          value = google_sql_database_instance.db.connection_name
        }

        resources {
          limits = {
            memory = "512Mi"
            cpu    = "1"
          }
        }
      }
    }
  }
}

# The database
resource "google_sql_database_instance" "db" {
  name             = "my-app-db"
  database_version = "POSTGRES_16"
  region           = "asia-south1"

  settings {
    tier = "db-f1-micro"   # Cheapest tier
  }
}
```

```bash
terraform plan    # Shows what WILL change, without changing anything
terraform apply   # Actually creates/modifies the infrastructure
terraform destroy # Tears everything down
```

**Why this matters:**
- `terraform plan` shows you the diff before applying — like a PR for infrastructure
- State file tracks what exists — Terraform knows what to create, update, or delete
- Same config creates identical environments: `terraform apply -var="env=staging"` and `terraform apply -var="env=production"`

### Alternatives:

| Tool | Language | Notes |
|------|----------|-------|
| Terraform | HCL (own language) | Most widely used. Cloud-agnostic |
| Pulumi | Python, TypeScript, Go | IaC in real programming languages. Good if you hate learning HCL |
| AWS CDK | TypeScript, Python | AWS-specific. Very good if you're all-in on AWS |
| Ansible | YAML | Better for server configuration than cloud resource provisioning |

**For you right now:** Don't set up Terraform. Know what it does and why it exists. When you move off PaaS, it'll be relevant. If someone mentions it in an interview, you can explain the problem it solves.

---

## 8.2 — Kubernetes (K8s) — What It Is, Why You Don't Need It

**Kubernetes** is a container orchestration platform. It manages running containers at scale — starting them, stopping them, scaling them, restarting them when they crash, routing traffic to them.

### What K8s gives you:

```yaml
# deployment.yaml — tells K8s what to run
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-ai-app
spec:
  replicas: 3                    # Run 3 instances
  selector:
    matchLabels:
      app: my-ai-app
  template:
    metadata:
      labels:
        app: my-ai-app
    spec:
      containers:
        - name: app
          image: ghcr.io/you/my-ai-app:v1.2.3
          ports:
            - containerPort: 8000
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:         # Restart if this fails
            httpGet:
              path: /health
              port: 8000
            periodSeconds: 30
          readinessProbe:        # Stop sending traffic if this fails
            httpGet:
              path: /health
              port: 8000
            periodSeconds: 10
```

### K8s concepts in plain terms:

| Concept | What It Is | Analogy |
|---------|-----------|---------|
| **Pod** | Smallest deployable unit. Usually = 1 container | A single running instance of your app |
| **Deployment** | Declares "I want 3 pods of this image" | Your desired state |
| **Service** | Stable network endpoint that routes to pods | A load balancer for your pods |
| **Ingress** | Routes external traffic to services | The front door with HTTPS |
| **ConfigMap** | Non-secret configuration | Like env vars, but K8s-managed |
| **Secret** | Sensitive configuration | Like env vars, but encrypted |
| **Namespace** | Logical isolation | Like folders for your K8s resources |
| **Node** | A machine in the cluster | One server that runs pods |
| **Cluster** | A set of nodes | Your entire K8s infrastructure |
| **Helm** | Package manager for K8s | Like `pip install` but for K8s apps |

### When you'd actually need K8s:

You need Kubernetes when:
- You have **5+ services** that need to communicate, scale independently, and be deployed separately
- You need **auto-scaling** based on custom metrics (e.g., scale up when GPU queue depth > 10)
- You need **self-healing** — pods that restart automatically on crash, rescheduled on node failure
- You're running **multiple environments** (dev, staging, prod) with identical config
- You need **rolling updates with health-check-gated promotion** — K8s does this natively

You do NOT need Kubernetes when:
- You have 1-3 services → PaaS or Docker Compose on a single server
- You're a solo developer → K8s operational overhead will consume more time than it saves
- Your traffic is predictable and low → scaling isn't a problem to solve
- You want to "learn K8s" → learn it in theory, use a managed K8s (GKE, EKS) only when you have a real need

**The K8s tax:** A small team spending 40% of their engineering time managing Kubernetes instead of building product. Common in startups that adopted K8s too early. Don't be this team.

### Managed Kubernetes (when you do need it):

| Service | Provider | What It Manages |
|---------|----------|----------------|
| GKE (Google) | GCP | Control plane, node upgrades, auto-scaling. Best K8s experience |
| EKS (AWS) | AWS | Control plane. Nodes are more manual. Most adopted enterprise |
| AKS (Azure) | Azure | Control plane. Decent, improving |

**Never run your own Kubernetes control plane.** The operational complexity is staggering. Managed K8s removes the hardest part. If you can't afford managed K8s, you can't afford K8s at all.

---

## 8.3 — Deployment Strategies in Detail

Expanding on what Layer 4 introduced:

### Rolling Update

```
Timeline:
t0: [v1] [v1] [v1]     ← all running v1
t1: [v2] [v1] [v1]     ← one pod updated, health checked
t2: [v2] [v2] [v1]     ← second pod updated
t3: [v2] [v2] [v2]     ← rollout complete

If v2 fails health check at t1:
t1: [v2❌] [v1] [v1]   ← v2 pod fails
    Rollout paused, v2 pod killed
    [v1] [v1] [v1]     ← back to all v1
```

**Config (K8s):**
```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1          # Create 1 new pod before killing old
    maxUnavailable: 0    # Never have fewer pods than desired
```

### Blue-Green

```
Blue (v1):  running, serving traffic
Green (v2): deployed, tested, NOT serving

Cutover: switch load balancer from Blue to Green
Rollback: switch back to Blue (still running)

After validation: shut down Blue
```

**Implementation:** Two separate deployments. Switch the Service selector from `version: blue` to `version: green`. On PaaS, this is usually called "zero-downtime deploy" and happens automatically.

### Canary

```
t0: [v1] [v1] [v1] [v1] [v1]          ← 100% v1
t1: [v1] [v1] [v1] [v1] [v2]          ← 20% traffic to v2
    Monitor for 10 min...
t2: [v1] [v1] [v1] [v2] [v2]          ← 40% to v2
    Monitor for 10 min...
t3: [v2] [v2] [v2] [v2] [v2]          ← 100% v2

If metrics degrade at t1:
    Kill v2, back to [v1] [v1] [v1] [v1] [v1]
```

**Why canary is critical for AI apps:** Your eval suite is a sample. Real users send queries you've never tested. Canary lets you expose the new prompt/model to real traffic at low risk. If quality metrics drop for the canary group, you catch it before it hits everyone.

**Tools for canary:** Istio (K8s service mesh), Argo Rollouts, or simple feature flags (Layer 7).

---

## 8.4 — Auto-Scaling

**Horizontal scaling:** Add more instances when load increases. Remove when it drops.

```yaml
# K8s HorizontalPodAutoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  scaleTargetRef:
    name: my-ai-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70     # Scale up when CPU > 70%
```

**AI-specific scaling concerns:**
- LLM inference is CPU/memory heavy → scaling up is expensive
- Each instance might hold an in-memory cache (embeddings, model weights) → new instances start cold
- Scaling up takes time (30s-2min) → traffic spike hits before scale-up completes → latency spike
- Scale-to-zero saves money but cold start for AI apps can be 10-30s

**On PaaS:** Most handle this automatically but with limited control. Render auto-scales on paid plans. Cloud Run scales per-request.

**Decision rule for AI apps:** Set `minReplicas: 1` (never fully cold), set `maxReplicas` to what your budget allows, scale on request queue depth or latency, not just CPU.

---

## 8.5 — Multi-Environment Setup

**The standard: dev → staging → production.**

| Environment | Purpose | How it's used |
|-------------|---------|--------------|
| **Development** | Local machine + Docker Compose | You work here daily |
| **Staging** | Identical to production but no real users | Deploy here first. Test with production-like data. Catch issues before users do |
| **Production** | Real users, real data | Deploy here after staging validation |

**How environments differ:**

```
Environment Variables (different per env):
├── dev:     DATABASE_URL=localhost, OPENAI_API_KEY=sk-test, LOG_LEVEL=debug
├── staging: DATABASE_URL=staging-db, OPENAI_API_KEY=sk-staging, LOG_LEVEL=info
└── prod:    DATABASE_URL=prod-db, OPENAI_API_KEY=sk-prod, LOG_LEVEL=info

Code: IDENTICAL across all environments.
Infrastructure: staging mirrors production (same services, smaller scale).
```

**The #1 rule:** Never use production API keys/data in development. Use separate keys, separate databases, separate OpenAI orgs if possible (to isolate billing).

**Failure mode:** "It works in staging" → staging uses a different model version, smaller data, different rate limits → behavior differs in production. Make staging as close to production as possible. Same model, same versions, different data.

---

## 8.6 — Service Mesh and API Gateway

**Terms you'll hear. Briefly:**

**API Gateway:** A single entry point for all your APIs. Handles routing, rate limiting, auth, logging. Examples: Kong, AWS API Gateway, Traefik.

```
Client → API Gateway → /api/chat     → chat service
                     → /api/search   → search service
                     → /api/auth     → auth service
```

**Service Mesh:** Manages communication between your internal services. Handles retries, timeouts, circuit breaking, mTLS (encrypted internal traffic). Examples: Istio, Linkerd.

**When you need these:** When you have 5+ services and the networking between them is becoming complex. Not before then. For 1-3 services, your reverse proxy (Nginx/Caddy) does everything you need.

---

## 8.7 — GitOps

**The idea:** Your Git repo is the single source of truth for both code AND infrastructure. Changes to infrastructure are made via PRs, not by clicking buttons in dashboards.

```
Developer pushes to main
→ CI builds and tests code
→ CI builds Docker image, pushes to registry
→ CI updates K8s manifests (image tag) in the infra repo
→ ArgoCD (GitOps tool) detects the change
→ ArgoCD applies the new manifests to the cluster
→ K8s rolls out the new version
```

**Tools:** ArgoCD, Flux. Both watch a Git repo and automatically apply changes to K8s.

**Why it matters:** Every infrastructure change has a Git commit, a PR review, a history. "Who deployed what and when?" is answered by `git log`. Rollback is `git revert`.

**For you:** Premature. Know the concept. When someone says "we use GitOps," you know they mean infrastructure state lives in Git and is synced to the cluster automatically.

---

## 8.8 — Disaster Recovery (DR)

**The question:** If your primary region goes down, how fast can you recover?

| Metric | Meaning | Example |
|--------|---------|---------|
| **RTO (Recovery Time Objective)** | How long can you be down? | "We need to be back in 4 hours" |
| **RPO (Recovery Point Objective)** | How much data can you lose? | "We can lose up to 1 hour of data" |

**DR strategies by cost:**

```
Cheapest                                                    Most expensive
┌──────────────┬───────────────────┬─────────────────┬──────────────┐
│ Backup &     │ Pilot light       │ Warm standby    │ Hot standby  │
│ Restore      │                   │                 │ (Multi-region│
│              │                   │                 │  active)     │
│ RTO: hours   │ RTO: 30 min       │ RTO: minutes    │ RTO: seconds │
│ RPO: hours   │ RPO: minutes      │ RPO: seconds    │ RPO: zero    │
│ Cost: $      │ Cost: $$          │ Cost: $$$       │ Cost: $$$$   │
└──────────────┴───────────────────┴─────────────────┴──────────────┘
```

**For your stage:** Just have backups. Automated daily database backups to a different location. That's it. Test restoring from backup once. If you've never tested a restore, you don't have backups — you have files you hope are backups.

---

## Summary: What To Use When

| Your Stage | Infrastructure | Why |
|-----------|---------------|-----|
| Learning/MVP | PaaS (Render, Railway) | Minimum ops burden. Focus on product |
| First real users (< 1000) | PaaS + managed DB + Sentry | Still not worth self-managing infra |
| Growing (1000-10000 users) | Cloud Run or PaaS paid tier + proper monitoring | Need reliability, not complexity |
| Scale (10000+ users, team of 3+) | Managed K8s (GKE/EKS) + Terraform + proper CI/CD | Complexity is now justified |
| Enterprise | Full K8s + service mesh + multi-region + GitOps | You have an infra team |

**The trap:** Jumping to the bottom of this table before you've earned your way there. Every layer of complexity you add is a layer you have to debug at 3am. Add complexity only when the problem demands it, not because it looks impressive.

---

## Checkpoint Scenario

> You're in an interview. The interviewer asks: "Your team is deploying an AI chatbot. You currently use Render. The CTO wants to move to Kubernetes because 'we need to scale.' You have 500 daily active users and 3 engineers. What do you do?"

**Questions:**
1. What is your response to the CTO?
2. At what point (what metric or pain point) would Kubernetes become the right choice?
3. What would you invest engineering time in instead, given current scale?

---

## Build Task

None for this layer at your stage. Instead:
1. Review the Summary table above. Map yourself to a row. Be honest.
2. For each term in this layer (Terraform, K8s, Helm, Ingress, GitOps), write a one-sentence definition in your own words without looking back at this document.
3. If you can't define one, re-read that section and try again. The goal is interview survival, not hands-on expertise — yet.
