# Layer 3: Cloud & Hosting — Where Your Code Actually Runs

> Understanding what's behind the "Deploy" button.

**The point:** Every deployment platform is just someone else's computer running your code. The differences are in how much of the setup they handle for you vs. how much control you get. Picking the wrong tier of abstraction for your stage wastes time or money or both.

---

## 3.1 — The Hosting Spectrum

There are three tiers. Each trades control for operational burden.

```
More control, more ops work
▲
│  IaaS (Infrastructure as a Service)
│  ├── AWS EC2, GCP Compute Engine, DigitalOcean Droplets
│  ├── You get: a Linux box with an IP address
│  ├── You handle: OS updates, Python install, process management,
│  │   firewall, HTTPS certs, log collection, restart-on-crash, scaling
│  └── When to use: you need full control, custom networking, GPU access,
│      or you're running something the PaaS can't (like a custom ML serving stack)
│
│  PaaS (Platform as a Service)
│  ├── Render, Railway, Fly.io, Heroku, Google App Engine
│  ├── You give: code or Docker image + config
│  ├── They handle: OS, runtime, HTTPS, restart, basic scaling, log aggregation
│  └── When to use: side projects, MVPs, small production apps. RIGHT FOR YOU NOW
│
│  Serverless / FaaS (Function as a Service)
│  ├── AWS Lambda, Google Cloud Run, Vercel Functions, Cloudflare Workers
│  ├── You give: a function that handles one request
│  ├── They handle: everything. Scales to zero (no cost when idle), scales up on demand
│  ├── Constraints: cold starts (500ms-10s), execution time limits, memory limits
│  └── When to use: APIs with variable traffic, event processing, webhooks
│      Tricky for AI: inference latency + cold start = bad UX. Cloud Run is the
│      exception — it can keep instances warm and handle longer requests
▼
Less control, less ops work
```

**Decision rule for you right now:** PaaS (Render/Railway). You need to focus on learning deployment mechanics, not managing Linux servers. Once you've deployed 2-3 apps on PaaS and understand the abstractions, moving to IaaS or serverless is straightforward because you'll understand what the PaaS was doing for you.

**The IaaS trap for beginners:** "I'll just spin up an EC2 instance" → 3 hours later you're debugging SSH keys, security groups, Nginx config, systemd service files, and certbot, and you still haven't started deploying your app. That's learning sysadmin, not learning to ship.

---

## 3.2 — PaaS Deep Dive — What Render/Railway Actually Do

When you push to Render, here's what happens behind the scenes:

```
1. Webhook fires from GitHub → Render starts a build
2. Render provisions a build machine
3. If Dockerfile exists → docker build
   If no Dockerfile → auto-detect language, use buildpack
4. Image pushed to Render's internal registry
5. Render starts a new container from the image
6. Health check runs (if configured)
   ├── Passes → old container killed, traffic routed to new container
   └── Fails → new container killed, old container keeps serving (rollback)
7. HTTPS cert auto-provisioned via Let's Encrypt
8. DNS pointed to Render's load balancer
9. Your app is live at yourapp.onrender.com
```

**Things the PaaS handles that you'd have to do yourself on IaaS:**
- HTTPS certificate provisioning and renewal
- Reverse proxy (Nginx/Caddy) in front of your app
- Process restart on crash
- Log collection and viewing
- Basic metrics (CPU, memory)
- Git-based deploys

**Things the PaaS does NOT handle that will bite you:**
- Database backups (you must configure this)
- Complex environment variable management across environments
- Custom networking between services
- Anything that needs persistent disk beyond what they offer
- Cost optimization at scale (PaaS gets expensive past ~$50-100/month)

---

## 3.3 — Serverless: Cloud Run Is the Sweet Spot for AI Apps

Most serverless platforms (Lambda, Vercel Functions) have hard limits on execution time (15 min max on Lambda, 10s default on Vercel). AI inference can take 2-30 seconds. This is a bad fit.

**Cloud Run** is the exception:
- Container-based serverless (you give it a Docker image, not just a function)
- Request timeout up to 60 minutes
- Can keep instances warm (min-instances > 0) → no cold start
- Scales to zero when no traffic → no cost when idle
- Scales up automatically under load

```
Serverless Comparison for AI Apps:

| Feature              | Lambda    | Vercel Fn | Cloud Run | Cloud Run (min=1) |
|---------------------|-----------|-----------|-----------|-------------------|
| Cold start          | 1-10s     | 1-5s      | 5-30s     | None              |
| Max execution time  | 15 min    | 10-300s   | 60 min    | 60 min            |
| Scales to zero      | Yes       | Yes       | Yes       | No (min 1)        |
| Container support   | Yes (ECR) | No        | Yes       | Yes               |
| Cost when idle      | $0        | $0        | $0        | ~$5-15/mo         |
| Good for AI?        | Marginal  | No        | Yes       | Best              |
```

**For your stage:** Start with Render (PaaS, simpler). When you need scale-to-zero or cost optimization, move to Cloud Run. Both take Docker images, so the migration is "change where you push the image."

---

## 3.4 — DNS, Domains, HTTPS — The Path From URL to Your Server

When someone types `myapp.com` in their browser:

```
Browser → DNS resolver → "What IP is myapp.com?" → DNS server responds "93.184.216.34"
Browser → TCP connection to 93.184.216.34:443 (HTTPS)
Browser → TLS handshake (verify certificate, establish encryption)
Browser → HTTP request: GET / HTTP/2
Server → HTTP response: 200 OK, <html>...
```

**What you need to know:**
- **A Record**: Maps a domain to an IP address. `myapp.com → 93.184.216.34`
- **CNAME Record**: Maps a domain to another domain. `myapp.com → myapp.onrender.com` (Render gives you this, you CNAME your custom domain to it)
- **DNS propagation**: Changes take time (minutes to hours) to spread globally. You changed DNS, app still shows old site → wait, or check with `dig` or `nslookup`
- **HTTPS**: Encrypts traffic. Let's Encrypt provides free certificates. PaaS handles this automatically. If you're on IaaS, use Caddy (auto-HTTPS) over Nginx (manual cert config)

**Failure modes:**
- DNS not propagated yet → some users see your app, others see a DNS error → wait 24 hours max
- CNAME pointing to wrong target → domain resolves but hits someone else's server or nothing
- Mixed content → your page is HTTPS but you hardcoded `http://` API URLs → browser blocks them silently
- Certificate expired → browser shows scary warning. PaaS auto-renews, IaaS you must set up renewal (certbot cron job)

---

## 3.5 — Managed Services — Why You Don't Run Your Own Database

Running a database yourself means you're responsible for:
- Backups (and testing that backups actually restore)
- Disk space monitoring
- Version upgrades
- Replication (if you need high availability)
- Security patches
- Connection pool management

**Managed services pay someone else to handle this.** For a side project or small production app, this is the right call.

| Need | Managed Options | Free Tier? |
|------|----------------|------------|
| PostgreSQL | Supabase, Neon, Railway, Render DB | Yes (all) |
| Redis/Cache | Upstash, Railway | Yes |
| Vector DB | Pinecone (free), Qdrant Cloud, Supabase pgvector | Yes (limited) |
| File Storage | Cloudflare R2, AWS S3, Supabase Storage | R2: generous free |
| Auth | Clerk, Supabase Auth, Auth0 | Yes (limited) |
| Queues | Upstash (Redis-based), AWS SQS | Yes |

**Decision rule:** Use managed until the cost exceeds ~$50-100/month for that service. Below that, the engineering time to self-manage costs more than the service.

**Failure mode with managed services:**
- Connection pool exhaustion → your app opens unlimited connections, managed DB has a limit (e.g., 20 on free tier) → `too many connections` error → app crashes under any real load
- Free tier limits → Neon sleeps after 5 min idle → first request after sleep takes 3-5s for DB wake-up + your AI inference time → 8s total → user leaves
- Assuming managed = no responsibility → you still need to handle connection retries, timeouts, and backups of your data (some managed services don't backup on free tiers)

---

## 3.6 — Regions and Latency — Physics You Can't Optimize Away

Your server is a physical machine in a data center. If it's in `us-east-1` (Virginia) and your user is in Mumbai, every request travels ~14,000 km round-trip.

```
Request path:
Mumbai → undersea cable → Virginia → your app processes → Virginia → undersea cable → Mumbai

Network latency alone: ~200ms round-trip
+ AI inference (OpenAI API call): ~500-2000ms
+ DB query: ~5-50ms
= Total: 700-2250ms for one request
```

**What you can control:**
- Deploy in a region close to your users (Mumbai → `ap-south-1` or `asia-south1`)
- Deploy in a region close to your external APIs (if you use OpenAI, their servers are mostly US → deploying your backend in US reduces API latency even if your users are elsewhere)
- Tradeoff: backend near users (less network latency) vs. backend near OpenAI (less API latency). For AI-heavy apps where inference is the bottleneck, being near the API provider usually wins

**What you can't control:** Speed of light. No amount of engineering removes the physics of crossing oceans.

**For your stage:** Pick one region close to you or your users. Don't think about multi-region. If someone asks in an interview, say "multi-region is a complexity I'd defer until we have latency SLAs or regulatory requirements for data locality."

---

## 3.7 — The $PORT Problem — Why Apps Return 502

This is the most common deploy failure on every PaaS and it's worth its own section.

**How PaaS works internally:**

```
Internet → PaaS Load Balancer (port 443/HTTPS) → reverse proxy → your container (port ???)
```

The PaaS assigns a **random** port to your container via the `$PORT` environment variable. Your app must listen on that port. If you hardcode `8000`, and the platform assigns `10234`, the reverse proxy can't reach your app → **502 Bad Gateway**.

```python
# WRONG
uvicorn.run(app, host="0.0.0.0", port=8000)

# RIGHT
import os
port = int(os.environ.get("PORT", 8000))
uvicorn.run(app, host="0.0.0.0", port=port)
```

**In Docker + PaaS:** The `EXPOSE` in your Dockerfile is documentation only — it doesn't actually open the port. What matters is what port your app *listens* on at runtime matching what the platform expects.

**Failure mode:** App starts, logs look fine ("Uvicorn running on 0.0.0.0:8000"), platform says "deploy successful," but every request returns 502. You're listening on the wrong port. Grep your deploy logs for "PORT" to see what the platform assigned.

---

## Checkpoint Scenario

> You deploy a FastAPI + OpenAI RAG app to Render's free tier. It works. A user in India reports the app is "very slow" — 8-10 seconds per response.
>
> You check: your Render service is in Oregon (us-west). Your OpenAI API calls take ~1.5s. Your DB query takes 200ms. Your app processing takes 100ms.
>
> The user's complaint is legitimate — it IS 8-10 seconds for them.

**Questions:**
1. Where is the extra ~6-7 seconds coming from? (Hint: the app was idle)
2. What are two ways to fix this without changing your code?
3. Why does this problem not exist on a traditional VPS (IaaS)?

---

## Build Task

1. Deploy any Dockerized Python app to Render or Railway
2. Use the `$PORT` env var correctly
3. Add a custom domain (even a free subdomain from the platform)
4. Verify HTTPS works
5. Check deploy logs — identify each step from Section 3.2
6. Hit the health check endpoint from a different device/network to verify it's actually public
