# Layer 5: Networking & Security Fundamentals

> What you need to know to debug "it doesn't connect" and not leak your API keys.

**The point:** Every time your app can't reach something, a user can't reach your app, or something works in Postman but not in the browser — it's a networking or security issue. You don't need a networking degree. You need to know the 20% that covers 95% of real problems.

---

## 5.1 — HTTP: The Protocol Your App Speaks

Every request between a browser and your API, between your backend and OpenAI, between your app and your database proxy — is HTTP (or a protocol built on it).

### The Request/Response Cycle:

```
Client (browser, curl, your Python code)
  │
  ├── Request ──────────────────────────────►  Server
  │   Method: GET/POST/PUT/DELETE
  │   URL: https://api.openai.com/v1/chat/completions
  │   Headers: Authorization: Bearer sk-..., Content-Type: application/json
  │   Body: {"model": "gpt-4", "messages": [...]}
  │
  │◄── Response ─────────────────────────────  Server
  │   Status: 200 OK
  │   Headers: Content-Type: application/json
  │   Body: {"choices": [...]}
```

### Status Codes You Must Know Cold:

| Code | Meaning | When You See It | What To Do |
|------|---------|----------------|------------|
| 200 | OK | Normal success | Nothing |
| 201 | Created | POST that created a resource | Nothing |
| 301 | Moved Permanently | URL changed, browser should update | Check if you're using old URL |
| 400 | Bad Request | Your request body is malformed | Check JSON format, required fields |
| 401 | Unauthorized | Missing or invalid API key | Check Authorization header, key validity |
| 403 | Forbidden | Valid key but insufficient permissions | Key doesn't have access to this resource |
| 404 | Not Found | Endpoint doesn't exist | Check URL path, typos |
| 405 | Method Not Allowed | Used GET instead of POST, etc. | Check API docs for correct method |
| 408 | Request Timeout | Server didn't respond in time | Increase timeout or investigate server |
| 429 | Too Many Requests | Rate limited | Implement backoff, check rate limits |
| 500 | Internal Server Error | Server code crashed | Check YOUR server logs |
| 502 | Bad Gateway | Reverse proxy can't reach your app | App not running, wrong port (Layer 3) |
| 503 | Service Unavailable | Server is overloaded or down | Scale up or check health |
| 504 | Gateway Timeout | Reverse proxy reached app but app timed out | Request took too long, optimize or increase timeout |

**The difference between 502 and 504 matters for debugging:**
- 502 = the platform's proxy couldn't establish a connection to your app → your app isn't running or is on the wrong port
- 504 = the proxy connected but your app didn't respond in time → your code is too slow (likely the LLM call is taking too long, or you have an infinite loop)

---

## 5.2 — CORS — Why Your Frontend Can't Call Your Backend

**The scenario:** Your frontend is at `localhost:3000`. Your backend is at `localhost:8000`. You call `fetch('http://localhost:8000/api/chat')` from the frontend. The browser blocks it with a CORS error.

**Why:** Browsers enforce the **Same-Origin Policy**. A page at `origin A` cannot make requests to `origin B` unless `origin B` explicitly says it's okay. An origin = protocol + domain + port. `localhost:3000` ≠ `localhost:8000` → different origins → blocked.

**The fix is on the backend, not the frontend:**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://myapp.com"],  # NOT "*" in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Common CORS mistakes:**

| Mistake | Consequence |
|---------|-------------|
| `allow_origins=["*"]` in production | Any website can call your API — fine for public APIs, dangerous if your API has auth or costs money per call |
| Frontend developer tries to fix CORS with a proxy | Masks the problem, breaks in production |
| Forgetting OPTIONS preflight | Browser sends a preflight OPTIONS request before POST. If your backend doesn't handle OPTIONS, CORS fails even with correct headers |
| CORS error in logs but API works in Postman | Postman is not a browser. It doesn't enforce CORS. The browser does. This is expected behavior, not a bug |

**Key insight:** CORS is NOT a security measure against attackers. An attacker can use `curl` or a server-side script to call your API without any browser restrictions. CORS protects users' browsers from being tricked into making requests by malicious websites. Your actual security is authentication (API keys, JWT), not CORS.

---

## 5.3 — TLS/SSL — Encryption in Transit

**HTTPS = HTTP + TLS.** TLS encrypts the connection so nobody between the client and server can read or modify the data.

**What you need to know:**
- PaaS handles TLS for you (Render, Railway auto-provision Let's Encrypt certificates)
- On IaaS, use **Caddy** (auto-TLS, zero config) over Nginx (manual cert config with certbot)
- TLS certificates expire (every 90 days for Let's Encrypt). Auto-renewal must be configured
- `https://` is non-negotiable for production. Browsers show warnings for `http://`. Search engines penalize it. Data in transit is readable without it

**Failure modes:**
- Cert expired → browser shows "Your connection is not private" → users don't trust your app, bounce rate 90%+
- Mixed content → your page loads over HTTPS but makes `http://` API calls → browser blocks them silently. You see a tiny console warning. Users see broken functionality
- Self-signed cert in production → browsers reject it. Self-signed is for local development only

---

## 5.4 — Authentication & Authorization

**Authentication** = who are you? **Authorization** = what can you do?

### For your AI app, three patterns:

**1. API Keys (server-to-server)**
```python
# Your backend → OpenAI
# Key stored in env var, never in frontend code
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
```
- Simple. No expiry (usually). Can be revoked.
- Risk: leaked key = full access until revoked. No way to scope per-user.
- Use for: backend calling external APIs (OpenAI, Pinecone, etc.)

**2. JWT (JSON Web Token) (user-facing auth)**
```
User logs in → server creates JWT with {user_id, role, exp} → sends to client
Client stores JWT → sends in Authorization header on every request
Server verifies JWT signature → knows who the user is without a DB lookup
```
- Stateless: server doesn't store sessions. Good for scaling.
- Risk: JWT is valid until it expires, even if user is banned. Keep expiry short (15-60 min) + use refresh tokens.
- Use for: authenticating users of your app.

**3. OAuth (login with Google/GitHub)**
- Delegates authentication to a trusted provider
- You don't handle passwords. Google verifies the user, gives you their email/profile.
- Use Clerk, Supabase Auth, or NextAuth to implement. Don't build OAuth from scratch — the spec is a minefield of security edge cases.

**The cardinal sin of AI apps: exposing your API key to the frontend.**
```javascript
// NEVER DO THIS — anyone can View Source → steal your key → call OpenAI on your dime
fetch('https://api.openai.com/v1/chat/completions', {
  headers: { 'Authorization': 'Bearer sk-YOUR_KEY_HERE' }
})
```

**Always proxy through your backend:**
```
Frontend → your backend (authenticated) → OpenAI (your key, server-side)
```

This way: you control access, you rate-limit per user, your key is never exposed.

---

## 5.5 — Rate Limiting — Protecting Your Wallet and Your APIs

Every request to your AI endpoint costs money (OpenAI tokens, compute time). Without rate limiting, one user (or a bot) can send 10,000 requests and run up your bill.

```python
# FastAPI with slowapi
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/chat")
@limiter.limit("10/minute")       # 10 requests per minute per IP
async def chat(request: Request):
    ...
```

**Rate limiting tiers (for an AI app):**
- **Anonymous users**: 5-10 requests/minute, 50/day
- **Authenticated free tier**: 20-50 requests/day
- **Paid users**: 100-500 requests/day
- **Internal/admin**: higher but still limited (protect against bugs, not just abuse)

**What to return when rate limited:** HTTP 429 with `Retry-After` header telling the client when to try again.

**Failure modes:**
- No rate limiting → bot scrapes your API → $500 OpenAI bill overnight
- Rate limiting by IP only → users behind the same corporate NAT share a limit → legitimate users get blocked
- Rate limiting on the frontend only → attacker bypasses your frontend, hits API directly → no protection
- Rate limit too aggressive → real users hit limits during normal use → frustration → churn

---

## 5.6 — Reverse Proxy — What Sits in Front of Your App

In production, users don't connect directly to your Python process. A **reverse proxy** sits in between:

```
Internet → Reverse Proxy (Nginx/Caddy) → Your App (uvicorn)
```

**What the reverse proxy does:**
- TLS termination (handles HTTPS, forwards plain HTTP to your app)
- Load balancing (distributes requests across multiple instances)
- Static file serving (images, CSS, JS — faster than Python)
- Request buffering (absorbs slow client connections so your app isn't tied up)
- Gzip compression
- Rate limiting (another layer)
- IP blocking / DDoS protection (basic)

**On PaaS:** The platform runs the reverse proxy for you. You never configure it.

**On IaaS (when you get there):**
- **Caddy**: Auto-HTTPS, simple config. Use this unless you have a reason not to.
- **Nginx**: More manual, more control. Standard in the industry. Config is verbose and error-prone.
- **Traefik**: Docker-native, auto-discovers services. Used with Docker Compose and Kubernetes.

**You don't need to set this up now.** But when you see 502 errors, know that the reverse proxy is the component reporting that error — your app itself never returns 502. 502 means "I (the proxy) tried to reach the backend and couldn't."

---

## 5.7 — Firewalls and Network Security

**The principle of least access:** only open what needs to be open. Everything else is closed by default.

**On PaaS:** Mostly handled for you. Your app gets an HTTPS endpoint. No ports to manage.

**On IaaS (for your knowledge):**
```
Default: all ports closed

Open:
  - 443 (HTTPS) → from anywhere (0.0.0.0/0)
  - 22 (SSH) → from YOUR IP only, not from anywhere
  - 5432 (Postgres) → ONLY from your app's IP/VPC, NEVER from 0.0.0.0/0

That's it. Three rules. Not five, not ten. Three.
```

**Failure mode that costs companies millions:** Postgres/Redis/Elasticsearch exposed to the internet (`0.0.0.0/0` on their port) → bots scan for open databases → your data is stolen/ransomed. This happens to real companies. Regularly. The fix is one firewall rule.

---

## 5.8 — SSH — Accessing Remote Servers

When you do eventually use IaaS, SSH is how you access the server:

```bash
# Generate an SSH key pair (do this once)
ssh-keygen -t ed25519 -C "your@email.com"
# Creates ~/.ssh/id_ed25519 (private, NEVER share) and ~/.ssh/id_ed25519.pub (public, safe to share)

# Copy public key to server (done during server setup)
# Then connect:
ssh user@93.184.216.34

# Copy files to/from server:
scp local_file.txt user@93.184.216.34:/path/on/server/
```

**You won't need SSH on PaaS.** But you'll need it eventually, and it's also used for GitHub authentication (SSH keys vs HTTPS tokens).

**Failure mode:** SSH key permissions too open → `WARNING: UNPROTECTED PRIVATE KEY FILE!` → SSH refuses to connect. Fix: `chmod 600 ~/.ssh/id_ed25519`.

---

## Checkpoint Scenario

> You build a RAG app with a React frontend (localhost:3000) and a FastAPI backend (localhost:8000). Locally, everything works. You deploy the frontend to Vercel, the backend to Render. The frontend loads, but every API call fails silently.
>
> Browser console shows: `Access to fetch at 'https://your-api.onrender.com/chat' from origin 'https://your-app.vercel.app' has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present on the requested resource.`

**Questions:**
1. What is the fix? Be specific — show the code change.
2. Why did this work locally but break in production?
3. After fixing CORS, a security engineer reviews your code and says your OpenAI key is exposed. Where is it exposed and what's the fix?

---

## Build Task

1. Add CORS middleware to a FastAPI app with `allow_origins` set to specific domains (not `*`)
2. Add rate limiting with `slowapi` — set it to 10 requests/minute
3. Verify that env vars are used for all secrets (grep your codebase for hardcoded keys)
4. Test CORS: run your API, try calling it from a different port with `fetch()` in a browser console. Observe the CORS error. Add the correct origin. Observe it working.
