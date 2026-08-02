# DevOps → LLMOps: Full Curriculum

> Sequenced by dependency — each layer requires the one before it.
> Status tracking: ❌ not started | 🔄 in progress | ✅ covered
>
> **Content files:** Each layer has a detailed document in this folder (layer1_*.md through layer8_*.md)

---

## Layer 0: The Mental Model — What "Production" Actually Means

Status: 🔄

Your code running locally is a demo. Production means:
- Someone else's machine runs it (you don't control the environment)
- It must start without you being there
- It must keep running when things go wrong
- You must know it's broken before the user tells you
- You must be able to change it without breaking it for current users

Every single DevOps concept exists to solve one of these five problems. If you can't map a concept back to one of these, you're learning trivia.

---

## Layer 1: Environment & Dependency Management

Status: ❌

Why this is first: Your Render failure lives here.

### Topics:
- **Runtime vs build-time dependencies** — what needs to exist when code runs vs. when it compiles/installs
- **Package managers and lockfiles** — package.json vs package-lock.json (or requirements.txt vs pip freeze). Why lockfiles exist: reproducibility. Failure mode: "works on my machine" because versions floated
- **Environment variables** — how config and secrets get into your app without hardcoding. Why .env files exist locally, why they don't go to production
- **Node/Python version mismatches** — .nvmrc, .python-version, engines field. Why Render used a different version than you and everything broke
- **The build process** — what `npm run build` or `pip install` actually does, where it fails, how to read error output

### Key failure modes:
- Lockfile not committed → CI installs different versions → cryptic runtime error
- Python/Node version differs between local and remote → syntax or API incompatibility
- Missing env vars in production → app starts but crashes on first request
- Dev dependencies used in production code → build succeeds, runtime fails

---

## Layer 2: Containerization (Docker)

Status: ❌

Why this matters: Docker makes Layer 1 problems disappear by making the environment a code artifact.

### Topics:
- **What a container actually is** — not a VM. A process with its own filesystem, network, and isolated view of the OS. Uses the host kernel. This matters for debugging.
- **Images vs containers** — image is the blueprint (frozen filesystem + startup command), container is a running instance of it
- **Dockerfile** — the recipe: FROM (base image/OS), COPY (your code), RUN (install deps), CMD (what runs on startup). Each line = a layer, layers are cached
- **Build context** — what Docker can see when building. .dockerignore is your .gitignore equivalent
- **Multi-stage builds** — build in a fat image (has compilers, dev tools), copy output to a slim image (just runtime). Reduces image size 10x. Matters for deploy speed and cost
- **Docker Compose** — running multiple containers locally (app + database + redis). Your local simulation of production
- **Volumes and networking** — how containers talk to each other, how data persists beyond container lifecycle
- **Registry** — Docker Hub, GitHub Container Registry, cloud registries. Where images live so production can pull them

### Key failure modes:
- Image works locally, fails in CI → build context difference or platform mismatch (arm64 vs amd64, common with M-series Macs)
- Container starts then exits immediately → CMD is wrong, or app crashes on startup but you can't see logs because container is gone. `docker logs <container>` is your first grep
- Image is 2GB → didn't use multi-stage builds, included dev deps, node_modules bloat. Deploy takes 5 min instead of 30s
- Container can't reach database → networking misconfigured, containers on different Docker networks
- Data gone after restart → forgot to mount a volume for stateful data

---

## Layer 3: Cloud & Hosting — Where Your Code Runs

Status: ❌

### Topics:
- **PaaS vs IaaS vs Serverless** — the actual tradeoff is control vs. operational burden
  - PaaS (Render, Railway, Fly.io, Heroku): You give them code or a Docker image, they run it. Least control, least ops burden. Right for you now.
  - IaaS (AWS EC2, GCP Compute): You get a Linux box. You install everything. Full control, full responsibility. Premature for you.
  - Serverless (AWS Lambda, Vercel Functions, Cloud Run): Code runs per-request, scales to zero. Great for APIs, terrible for long-running AI inference without careful config.
- **DNS, domains, HTTPS** — what happens between typing a URL and hitting your server. Enough to debug "site not reachable"
- **Managed services** — databases (Supabase, PlanetScale, Neon), caches (Upstash Redis), queues (SQS, BullMQ). Why you use these instead of running your own: you're paying someone else to get paged at 3am for that component
- **Regions and latency** — your server is a physical machine somewhere. If it's in US-East and your user is in Mumbai, every request adds 200ms. This matters for AI apps that already have 500ms+ inference latency

### Key failure modes:
- App deploys but returns 502 → app isn't listening on the port the platform expects ($PORT env var, not hardcoded 3000)
- Free tier cold starts → first request after idle takes 10-30s. Your AI endpoint already takes 3s. User sees 33s load time, leaves
- Database connection pool exhausted → app opens new DB connection per request, PaaS runs 10 instances, 10 × max_connections = database dead
- HTTPS cert expired/misconfigured → browser shows scary warning, users don't trust your app

---

## Layer 4: CI/CD — Automated Build, Test, Deploy

Status: ❌

### Topics:
- **CI (Continuous Integration)** — every push triggers: install deps → build → run tests → report pass/fail. The point: you find out your code is broken in minutes, not after deploy
- **CD (Continuous Deployment/Delivery)** — if CI passes, automatically deploy (deployment) or stage for manual approval (delivery). Decision rule: use deployment for side projects, delivery for anything with users who'd notice breakage
- **GitHub Actions** — the most common CI/CD tool. A YAML file in .github/workflows/. Triggered by events (push, PR, schedule). Runs on disposable VMs (runners)
- **Pipeline stages** — lint → test → build → deploy. Each stage can fail, each failure needs different debugging
- **Secrets in CI** — API keys, deploy tokens. Stored in GitHub Secrets, injected as env vars. Never in YAML, never in code
- **Caching in CI** — node_modules, pip cache, Docker layers. Without caching, every build reinstalls everything from scratch. A 1-min build becomes 8 minutes. Matters because slow CI means you stop running it
- **Branch strategies** — main = production, feature branches for dev. PRs trigger CI, merge to main triggers deploy. Keep it simple

### Key failure modes:
- CI passes, production breaks → tests don't cover what actually fails (missing integration tests, test env differs from prod)
- CI is slow (>10 min) → no caching, unnecessary steps, running all tests for every change. Devs start skipping CI
- Secrets exposed in logs → accidentally echoed env vars. Grep CI logs for your API key patterns
- Deploy succeeds but app is broken → no health check after deploy, no rollback. Old version was fine, new version crashes, no one knows for 20 min

### AI/ML-specific CI/CD problems (preview — detailed in Layer 7):
- How do you "test" an LLM response? assert exact_match doesn't work
- Eval suites as CI gates — run a golden set of prompts, check quality scores, block deploy if score drops
- Model/prompt changes need different CI than code changes

---

## Layer 5: Networking & Security Fundamentals

Status: ❌

### Topics:
- **HTTP/HTTPS** — request/response cycle, status codes (know 200, 201, 301, 400, 401, 403, 404, 429, 500, 502, 503 cold), headers that matter (Authorization, Content-Type, CORS)
- **CORS** — why your frontend can't call your backend. Not a security feature against attackers, it's a browser policy. Misconfigured CORS is the #1 "my API works in Postman but not in browser" issue
- **TLS/SSL** — encryption in transit. Let's Encrypt for free certs. PaaS handles this for you, but know it exists for debugging
- **Firewalls & security groups** — which ports are open, which IPs can reach your service. On PaaS this is mostly handled. On IaaS you will lock yourself out at least once
- **API keys vs OAuth vs JWT** — authentication for your AI APIs. API keys for server-to-server (OpenAI, your backend-to-vector-db). JWT for user-facing auth. Never expose API keys to frontend code
- **Rate limiting** — protecting your endpoint from abuse. Critical for AI endpoints because every request costs you money (API calls, GPU time)
- **Reverse proxy (Nginx/Caddy)** — sits in front of your app, handles HTTPS termination, load balancing, static files. PaaS does this for you. Know it exists

### Key failure modes:
- CORS error in browser → backend doesn't return Access-Control-Allow-Origin header. Fix is on the backend, not the frontend
- 429 Too Many Requests → you're hitting OpenAI rate limits. Need request queuing or backoff. If you're proxying to users, they can DDoS your OpenAI bill
- API key in frontend code → anyone can view-source, steal your key, run up your bill. Seen this cost people $10k+
- Mixed content error → page is HTTPS but calls HTTP API. Browser blocks it silently

---

## Layer 6: Monitoring, Logging, Observability

Status: ❌

### Topics:
- **Logs** — structured (JSON) vs unstructured (print statements). Use structured. Why: you can query JSON, you can't query "print(f'error: {e}')" across 10k requests
- **Log levels** — DEBUG, INFO, WARN, ERROR. Use them correctly. ERROR = something is broken. WARN = something is degraded. INFO = normal operation milestones. DEBUG = development only, never in production at scale (costs $$$)
- **Metrics** — numbers over time. Request count, latency (p50, p95, p99), error rate, CPU/memory usage. These are your dashboard
- **Traces** — following a single request through your entire system (API → retrieval → LLM → post-processing → response). Critical for debugging latency in AI pipelines
- **Health checks** — an endpoint (/health) that returns 200 if your app is alive. Platform uses this to restart dead instances. If your health check lies (returns 200 but app is actually broken), you won't get restarted
- **Alerting** — rules that page you. "Error rate > 5% for 3 min" → PagerDuty/Slack/email. Without alerting, monitoring is a hobby, not an operational tool
- **Tools** — Grafana, Prometheus, Datadog, Better Stack, Sentry (errors), OpenTelemetry (traces). Start with Sentry (free tier) for error tracking. That alone puts you ahead of 80% of side projects

### Key failure modes:
- No structured logging → can't search logs when debugging an incident. Grepping through unstructured text at 3am is pain
- No alerting → app is down for 3 hours, you find out from a user tweet
- Health check returns 200 but app can't reach database → health check is too shallow, doesn't verify dependencies
- Alert fatigue → too many alerts, you ignore them all, miss the real one

---

## Layer 7: LLMOps — Operating LLM-Powered Apps

Status: ❌

> Renamed from MLOps. You don't train models — you consume LLM APIs. These are your specific operational problems.

### Topics:
- **Model serving** — how your model/LLM actually handles requests. Direct API calls (OpenAI), self-hosted (vLLM, TGI, Ollama), behind a gateway
- **Prompt versioning** — prompts are code. They need version control, review, and rollback. A prompt change can break your app as badly as a code bug, but nothing in your CI catches it unless you build eval gates
- **Eval pipelines** — automated quality checks. Golden test sets, LLM-as-judge, format compliance checks. These run in CI and block deploy if quality drops. This is the "test suite" for non-deterministic systems
- **Cost attribution** — which feature, user, or request type is burning your API budget. Without this, you get a $500 bill and can't explain it. Tag every LLM call with feature_name and user_tier at minimum
- **Fallback chains** — GPT-4 fails or is too slow → fall back to GPT-4-mini → fall back to cached response → fall back to "sorry, try again." Without fallback, one OpenAI outage = your entire app is down
- **Drift detection** — your RAG system's retrieval quality silently degrades as your corpus grows stale, embeddings change, or user queries shift. Nothing pages you for this unless you built periodic eval runs against a golden set
- **Feature flags for AI** — deploy a new prompt to 5% of users, measure quality, roll out gradually. Not a Netflix-scale technique — it's basic risk management for changes that can't be fully tested pre-deploy
- **Experiment tracking** — logging which model/prompt/config produced which results. MLflow, Weights & Biases, or even a database table. You need this to answer "why did quality drop last Tuesday"

### Key failure modes:
- No eval gate → pushed a "better" prompt that actually reduced answer quality by 15%, discovered two weeks later from user complaints
- No cost tracking → one user sending 100 requests/day through your RAG pipeline, each costing $0.08. $240/month from one user. You didn't know
- No fallback → OpenAI has a 30-min outage, your app returns 500 errors for 30 min, users leave
- Embedding model updated → all your stored embeddings are now incompatible with query embeddings, retrieval returns garbage, nothing alerts you

---

## Layer 8: Infrastructure as Code & Advanced Deployment

Status: ❌

### Topics:
- **IaC (Terraform, Pulumi)** — defining your infrastructure in code files, not clicking buttons in cloud consoles. Why: reproducibility, review, rollback
- **Kubernetes basics** — what it is (container orchestration), when you need it (you don't, yet), what problems it solves (scaling, self-healing, rolling deploys). Knowing what it is = interview survival. Running it yourself = premature at your stage
- **Rolling deploys vs blue-green vs canary** — how to update a running app without downtime
- **Auto-scaling** — adding instances when load increases, removing when it drops. Critical for AI apps with bursty traffic (viral tweet → 100x traffic → back to normal)
- **Multi-region** — running in multiple data centers. Premature for you. Mentioning it so you know the term

---

## Coverage Map

| Layer | Content File | Status | Priority |
|-------|-------------|--------|----------|
| 0: Mental Model | (this file) | 🔄 Started | Critical |
| 1: Environment & Deps | layer1_environment_dependencies.md | ❌ Read & practice | Critical |
| 2: Docker | layer2_docker.md | ❌ Read & practice | Critical |
| 3: Cloud & Hosting | layer3_cloud_hosting.md | ❌ Read & practice | Critical |
| 4: CI/CD | layer4_cicd.md | ❌ Read & practice | High |
| 5: Networking & Security | layer5_networking_security.md | ❌ Read & practice | High |
| 6: Monitoring & Observability | layer6_observability.md | ❌ Read & practice | High |
| 7: LLMOps | layer7_llmops.md | ❌ Read & practice | High |
| 8: IaC & Advanced Deploy | layer8_iac_advanced.md | ❌ Read (no build) | Low — terms only |

---

## Rules for this curriculum
- We go in order unless you have a burning question
- Each layer ends with a build task or a break-it task
- Every 3-4 exchanges, I checkpoint your understanding with a scenario
- I will call out if you're drifting to a layer you're not ready for
