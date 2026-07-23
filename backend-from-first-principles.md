# Backend Engineering from First Principles — Complete Study Notes

> Written in the voice of a senior engineer at the whiteboard. No fluff. Every paragraph earns its place.
> Based on the syllabus from "Backend from First Principles" by Sriniously.

---

## Table of Contents

1.  [Roadmap / High-Level Overview](#1-roadmap--high-level-overview-of-backend-engineering)
2.  [HTTP Protocol](#2-http-protocol)
3.  [Routing](#3-routing)
4.  [Serialization & Deserialization](#4-serialization--deserialization)
5.  [Authentication & Authorization](#5-authentication--authorization)
6.  [Validation & Transformation](#6-validation--transformation)
7.  [Middlewares](#7-middlewares)
8.  [Request Context](#8-request-context)
9.  [Handlers, Controllers, and Services](#9-handlers-controllers-and-services)
10. [CRUD Deep Dive](#10-crud-deep-dive)
11. [RESTful Architecture & Best Practices](#11-restful-architecture--best-practices)
12. [Databases](#12-databases)
13. [Business Logic Layer (BLL)](#13-business-logic-layer-bll)
14. [Caching](#14-caching)
15. [Transactional Emails](#15-transactional-emails)
16. [Task Queuing & Scheduling](#16-task-queuing--scheduling)
17. [Elasticsearch](#17-elasticsearch)
18. [Error Handling](#18-error-handling)
19. [Config Management](#19-config-management)
20. [Logging, Monitoring & Observability](#20-logging-monitoring--observability)
21. [Graceful Shutdown](#21-graceful-shutdown)
22. [Security](#22-security)
23. [Scaling & Performance](#23-scaling--performance)
24. [Concurrency & Parallelism](#24-concurrency--parallelism)
25. [Object Storage & Large Files](#25-object-storage--large-files)
26. [Real-Time Backend Systems](#26-real-time-backend-systems-websocketssse)
27. [Testing & Code Quality](#27-testing--code-quality)
28. [12-Factor App Methodology](#28-12-factor-app-methodology)
29. [OpenAPI Standards](#29-openapi-standards)
30. [Webhooks](#30-webhooks)
31. [DevOps for Backend Engineers](#31-devops-for-backend-engineers)
32. [How It All Fits Together](#32-how-it-all-fits-together)

---

## 1. Roadmap / High-Level Overview of Backend Engineering

### WHY

Every application has two halves: the part the user sees and the part that makes it actually work. The backend is the second half. It stores data, enforces rules, coordinates between systems, and makes sure that when 10,000 users hit the same endpoint at the same time, nobody gets somebody else's bank balance.

Without a mental map of what "backend" actually encompasses, engineers learn topics in random order, build fragile systems, and don't understand why things break at 3 AM. The roadmap exists so you know what you don't know, and in what order to learn it.

### WHAT — The Mental Model

A backend system is a pipeline. A request enters, gets processed through layers, and a response exits. Every topic in this syllabus is a layer or a cross-cutting concern in that pipeline:

```
Client Request
  │
  ▼
[ HTTP Protocol ]          ← How the message travels
  │
  ▼
[ Routing ]                ← Which code handles this message
  │
  ▼
[ Middleware ]              ← Cross-cutting: auth, logging, rate-limiting
  │
  ▼
[ Validation ]             ← Is this input even legal?
  │
  ▼
[ Handler / Controller ]   ← Orchestrate the response
  │
  ▼
[ Service / BLL ]          ← Business rules, the actual "point" of the app
  │
  ▼
[ Data Layer ]             ← Databases, caches, search indices, object storage
  │
  ▼
[ Serialization ]          ← Turn internal data into a response format
  │
  ▼
Response
```

Cross-cutting concerns weave through all of these: **error handling**, **logging**, **security**, **config management**, **testing**.

Infrastructure concerns sit beneath everything: **scaling**, **concurrency**, **DevOps**, **graceful shutdown**.

### The Five Pillars

Think of backend engineering as five pillars:

1. **Request Handling** — HTTP, routing, middleware, serialization, validation. Getting data in and out.
2. **Business Logic** — Handlers, services, BLL. The rules that make your app your app, not someone else's.
3. **Data Management** — Databases, caching, search, object storage. Where state lives.
4. **Reliability** — Error handling, logging, monitoring, graceful shutdown, testing. Keeping it running at 3 AM.
5. **Operations** — Config management, scaling, concurrency, DevOps, 12-factor methodology. Running it in production.

Every topic in this syllabus fits into one of these. When you learn a new concept, mentally slot it into a pillar. That's how you build a systems-level mental model instead of a bag of disconnected facts.

### HOW THIS CONNECTS

This overview is the map. Every subsequent section zooms into one square on the map. We start with HTTP because that's the front door — nothing happens until a request arrives.

---

## 2. HTTP Protocol

### WHY

HTTP is the contract between your client and your server. Every single interaction — loading a page, submitting a form, fetching an API response, uploading a file — is an HTTP transaction. If you don't understand HTTP deeply, you'll misuse status codes, break caching, create security holes, and build APIs that confuse every consumer.

**Concrete failure:** An engineer returns `200 OK` with `{ "error": "Not found" }` in the body. The client's HTTP library treats it as success. The frontend happily renders a blank page. Monitoring shows zero errors. The bug lives in production for weeks.

### WHAT

HTTP (Hypertext Transfer Protocol) is a stateless, request-response protocol defined by RFC 9110. "Stateless" means every request is independent — the server doesn't inherently remember your previous request. This is a feature, not a limitation: it makes servers horizontally scalable because any server can handle any request.

**Anatomy of a request:**

```
POST /api/users HTTP/1.1          ← Method + Target + Version
Host: api.example.com             ← Headers (metadata)
Content-Type: application/json
Authorization: Bearer eyJhbG...

{"name": "Alice", "email": "alice@example.com"}   ← Body (optional)
```

**Anatomy of a response:**

```
HTTP/1.1 201 Created              ← Version + Status Code + Reason Phrase
Content-Type: application/json
Location: /api/users/42

{"id": 42, "name": "Alice"}      ← Body
```

**The parts that matter:**

**Methods** define intent (per RFC 9110 §9):
| Method | Semantics | Idempotent? | Safe? |
|--------|-----------|-------------|-------|
| GET | Retrieve a representation | Yes | Yes |
| POST | Process an entity (create) | No | No |
| PUT | Replace the target resource entirely | Yes | No |
| PATCH | Partial modification | No | No |
| DELETE | Remove the target resource | Yes | No |
| HEAD | Same as GET, but no body | Yes | Yes |
| OPTIONS | Describe communication options | Yes | Yes |

**Idempotent** means making the same request N times has the same effect as making it once. PUT is idempotent: "set user 42's name to Alice" — do it ten times, still Alice. POST is not: "create a user" — do it ten times, you might get ten users.

**Safe** means the method doesn't modify server state. GET is safe — it only reads. This matters because caches, crawlers, and prefetch mechanisms assume safe methods don't have side effects. If your GET endpoint deletes data, you'll have a very bad day when Google crawls it.

**Status codes** are grouped by semantics:
- **2xx** — Success. `200 OK`, `201 Created`, `204 No Content`.
- **3xx** — Redirection. `301 Moved Permanently`, `304 Not Modified`.
- **4xx** — Client error. `400 Bad Request`, `401 Unauthorized` (really means unauthenticated), `403 Forbidden` (authenticated but not authorized), `404 Not Found`, `409 Conflict`, `422 Unprocessable Content`, `429 Too Many Requests`.
- **5xx** — Server error. `500 Internal Server Error`, `502 Bad Gateway`, `503 Service Unavailable`, `504 Gateway Timeout`.

**Headers** carry metadata. The important ones:
- `Content-Type` — MIME type of the body (`application/json`, `multipart/form-data`).
- `Authorization` — Credentials (typically `Bearer <token>`).
- `Cache-Control` — Caching directives (`no-store`, `max-age=3600`).
- `Accept` — What content types the client can handle (content negotiation).
- `ETag` / `If-None-Match` — Conditional requests for cache validation.
- `X-Request-Id` — Trace a request through distributed systems (not standard but universal).

### HOW — HTTP/1.1 vs HTTP/2 vs HTTP/3

**HTTP/1.1**: One request per TCP connection (or pipelining, which nobody uses). Head-of-line blocking: if request 1 is slow, request 2 waits.

**HTTP/2**: Multiplexing — multiple requests share one TCP connection via streams. Binary framing instead of text. Header compression (HPACK). Server push (largely unused and being deprecated). Solves HTTP-level head-of-line blocking but TCP-level HOL blocking remains.

**HTTP/3**: Replaces TCP with QUIC (built on UDP). Eliminates TCP head-of-line blocking. Each stream is independent — a lost packet in one stream doesn't block others. Connection migration (switch from Wi-Fi to cellular without re-establishing).

For backend engineers: you rarely implement HTTP yourself. Your framework handles it. But you need to understand the protocol because you're designing APIs that speak it, debugging network issues, and configuring reverse proxies (Nginx, Envoy) that operate at this level.

### GOTCHAS

- **Treating POST as idempotent.** Network retries on a non-idempotent endpoint create duplicate records. Solution: idempotency keys (a client-generated UUID sent in a header; the server deduplicates).
- **Misusing status codes.** Returning `200` for errors means monitoring tools, load balancers, and clients can't distinguish success from failure. Use the right code.
- **Ignoring `Content-Type`.** Sending JSON with `text/plain` or no Content-Type confuses client parsers. Some frameworks accept it; some don't. Explicitly set it.
- **Large bodies without streaming.** Loading a 2 GB upload entirely into memory before processing. Use chunked transfer encoding or streaming body parsers.
- **`401` vs `403` confusion.** `401` means "I don't know who you are" (missing/invalid credentials). `403` means "I know who you are, but you can't do this."

### HOW THIS CONNECTS

HTTP is the transport. The next topic — Routing — is how the server decides *which code* should handle an incoming HTTP request based on its method and path.

---

## 3. Routing

### WHY

Your server receives HTTP requests on a single port. Routing is the mechanism that says "this request goes to this function." Without routing, you'd have one massive handler function with a giant if/else chain checking the URL path — which is exactly what early CGI scripts looked like, and exactly why they were unmaintainable.

**Concrete failure:** Two developers add handlers for `/users` and `/users/:id`. Due to route ordering, `/users/settings` matches the `:id` parameter route, treating the string `"settings"` as a user ID. The database query fails silently (no user found), and the endpoint returns a confusing 404.

### WHAT

A router is a lookup structure that maps `(HTTP method, URL path pattern)` → `handler function`. It's essentially a dispatch table, but most modern routers use a tree structure (radix tree / trie) for efficient matching.

**Route patterns:**

```
Static:      GET  /api/health           → healthCheck()
Parameterized: GET  /api/users/:id        → getUser(id)
Wildcard:    GET  /api/files/*path      → serveFile(path)
```

**Matching precedence matters:**

```
GET /api/users/me        ← Static route: should match first
GET /api/users/:id       ← Parameterized: matches if static doesn't
```

Most frameworks follow "most specific wins" — static routes beat parameterized, longer prefixes beat shorter. But this isn't universal. Express.js matches routes in registration order (first match wins). Go's `net/http` in 1.22+ uses most-specific-wins. Know your framework's strategy.

### HOW

```python
# Flask (Python) — decorator-based routing
@app.route("/api/users", methods=["GET"])
def list_users():
    return jsonify(users)

@app.route("/api/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    return jsonify(find_user(user_id))
```

```go
// Go 1.22+ stdlib — pattern-based routing
mux := http.NewServeMux()
mux.HandleFunc("GET /api/users", listUsers)
mux.HandleFunc("GET /api/users/{id}", getUser)
```

```javascript
// Express.js — method chaining
router.get('/api/users', listUsers);
router.get('/api/users/:id', getUser);
```

**Route grouping/prefixing** is a pattern every serious framework supports. It reduces repetition and organizes routes by domain:

```python
# Group all user-related routes under /api/users
user_routes = Blueprint('users', __name__, url_prefix='/api/users')

@user_routes.route("/", methods=["GET"])
def list_users(): ...

@user_routes.route("/<int:user_id>", methods=["GET"])
def get_user(user_id): ...
```

### GOTCHAS

- **Route ordering in order-dependent routers.** In Express, `router.get('/users/:id', ...)` registered before `router.get('/users/search', ...)` means `/users/search` is caught by `:id = "search"`. Register static routes first.
- **Trailing slash ambiguity.** Is `/users` the same as `/users/`? Depends on the framework. Some redirect, some 404, some treat them identically. Pick a convention and enforce it (usually: no trailing slash, redirect if present).
- **Path parameter type coercion.** `:id` comes in as a string. If your handler passes it directly to a database query expecting an integer, you get a type error or, worse, a SQL injection. Validate/parse route params before use.
- **Route conflicts in large codebases.** Two different modules register overlapping routes. No error at startup, but one silently shadows the other.

### HOW THIS CONNECTS

Routing tells the server *where* to send the request. But the request body arrives as raw bytes (or a JSON string). Before your handler can work with it, you need **serialization & deserialization** to convert between wire formats and in-memory objects.

---

## 4. Serialization & Deserialization

### WHY

Your server thinks in objects, structs, and dictionaries. The network thinks in bytes. Serialization converts internal data structures into a byte format for transmission; deserialization does the reverse. Without understanding this boundary, you'll have implicit conversion bugs, performance problems with large payloads, and security vulnerabilities from deserializing untrusted data.

**Concrete failure:** A Python service pickles user objects and stores them in Redis. An attacker crafts a malicious pickle payload, stores it in a user-controlled field. When the server deserializes it, it executes arbitrary code. This is CVE-after-CVE territory.

### WHAT

**Serialization** = data structure → wire format (bytes/string).
**Deserialization** = wire format → data structure.

Common wire formats:

| Format | Human-readable | Schema | Speed | Use case |
|--------|---------------|--------|-------|----------|
| JSON | Yes | No (implicit) | Moderate | REST APIs, config files |
| Protocol Buffers | No (binary) | Yes (.proto files) | Fast | gRPC, internal services |
| MessagePack | No (binary) | No | Fast | Redis, embedded systems |
| XML | Yes | Yes (XSD) | Slow | SOAP, legacy enterprise |
| YAML | Yes | No | Slow | Config files, Kubernetes |
| Avro | No (binary) | Yes (embedded) | Fast | Kafka, data pipelines |

**JSON is the lingua franca of web APIs.** It's human-readable, every language has a parser, and it maps naturally to key-value structures. Its weaknesses: no native date type (everything's a string), no distinction between integer and float (everything's a number in the spec), no comments, and it's verbose for large payloads.

### HOW

**Deserialization with validation** (the right way):

```typescript
// TypeScript with zod — parse, don't validate
import { z } from 'zod';

const CreateUserSchema = z.object({
  name: z.string().min(1).max(100),
  email: z.string().email(),
  age: z.number().int().min(13).max(150),
});

type CreateUser = z.infer<typeof CreateUserSchema>;

// In your handler:
const parsed = CreateUserSchema.safeParse(req.body);
if (!parsed.success) {
  return res.status(422).json({ errors: parsed.error.issues });
}
// parsed.data is now typed and validated
```

```go
// Go — struct tags control JSON mapping
type CreateUser struct {
    Name  string `json:"name" validate:"required,min=1,max=100"`
    Email string `json:"email" validate:"required,email"`
    Age   int    `json:"age" validate:"required,gte=13,lte=150"`
}

func handler(w http.ResponseWriter, r *http.Request) {
    var user CreateUser
    if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
        http.Error(w, "invalid JSON", http.StatusBadRequest)
        return
    }
    // Now validate...
}
```

**Serialization for responses:**

```python
# Python — control what gets serialized
from dataclasses import dataclass, asdict
import json

@dataclass
class UserResponse:
    id: int
    name: str
    email: str
    # Note: password_hash is NOT here — never serialize secrets

def to_response(user_db_row):
    response = UserResponse(id=user_db_row.id, name=user_db_row.name, email=user_db_row.email)
    return json.dumps(asdict(response))
```

### GOTCHAS

- **Deserializing without validation.** JSON.parse() gives you an `any` — you have zero guarantees about shape or types. Always validate after deserializing (or use a library that does both, like zod, pydantic, or serde).
- **Exposing internal fields.** Serializing your entire database model (including `password_hash`, `internal_notes`, `is_admin`) to the API response. Use explicit response DTOs.
- **Date/time hell.** JSON has no date type. Always use ISO 8601 strings (`"2024-01-15T10:30:00Z"`) and always include timezone (preferably UTC). If you use Unix timestamps, document whether they're seconds or milliseconds.
- **Floating point precision.** JSON numbers are IEEE 754 doubles. For financial data, serialize as strings: `"amount": "19.99"` not `"amount": 19.99` (which might become `19.990000000000002`).
- **Circular references.** Object A references Object B which references Object A. JSON.stringify() throws. ORM entities with bidirectional relationships hit this constantly.
- **Insecure deserialization.** Never use `pickle` (Python), `ObjectInputStream` (Java), or `eval` (anything) on untrusted input. These execute arbitrary code. Use data-only formats (JSON, protobuf).

### HOW THIS CONNECTS

You've routed the request and parsed the body. But who is making this request? That's **authentication & authorization** — verifying identity and permissions before any real work happens.

---

## 5. Authentication & Authorization

### WHY

Authentication answers "who are you?" Authorization answers "what are you allowed to do?" Without authentication, anyone can pretend to be anyone. Without authorization, authenticated users can access or modify anything. These are separate concerns, and conflating them is one of the most common security mistakes.

**Concrete failure:** An API uses JWTs for authentication but checks permissions by looking up the user's role from the JWT claims without verifying it against the database. An admin gets demoted to a regular user, but their existing JWT still says `role: admin` until it expires. For the next 24 hours, a non-admin has admin privileges.

### WHAT

**Authentication mechanisms:**

**Session-based:** Server creates a session (stored in memory, database, or Redis), gives the client a session ID in a cookie. Each request sends the cookie back. Server looks up the session. **Stateful** — server must remember sessions.

**Token-based (JWT):** Server creates a signed token containing claims (user ID, role, expiry). Client stores the token and sends it in the `Authorization: Bearer <token>` header. Server validates the signature and reads claims. **Stateless** — server doesn't need to store anything. But this comes with a trade-off: you can't easily revoke a token before it expires.

**JWT structure** (three base64url-encoded parts separated by dots):
```
eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjo0Miwicm9sZSI6InVzZXIiLCJleHAiOjE3MDAwMDAwMDB9.signature
  └── Header ──────┘  └── Payload (Claims) ─────────────────────────────────────────┘  └── Signature ┘
```

**Registered claims** (from the JWT spec):
- `iss` (issuer) — who created this token
- `sub` (subject) — who this token is about (typically user ID)
- `aud` (audience) — who this token is intended for
- `exp` (expiration) — Unix timestamp when it expires
- `iat` (issued at) — when it was created
- `jti` (JWT ID) — unique identifier for the token (useful for revocation)

**Authorization models:**

| Model | How it works | Good for |
|-------|-------------|----------|
| RBAC (Role-Based) | Users have roles, roles have permissions | Most apps |
| ABAC (Attribute-Based) | Policies based on user/resource/environment attributes | Complex enterprise |
| ACL (Access Control Lists) | Each resource has a list of who can do what | File systems, docs |
| ReBAC (Relationship-Based) | Permissions based on relationships between entities | Google Docs-style sharing |

### HOW

**JWT authentication middleware (pseudocode):**

```javascript
// Node.js — JWT verification middleware
function authenticate(req, res, next) {
  const header = req.headers.authorization;
  if (!header?.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Missing token' });
  }

  const token = header.slice(7);
  try {
    const payload = jwt.verify(token, process.env.JWT_SECRET);
    req.user = { id: payload.sub, role: payload.role };
    next();
  } catch (err) {
    if (err.name === 'TokenExpiredError') {
      return res.status(401).json({ error: 'Token expired' });
    }
    return res.status(401).json({ error: 'Invalid token' });
  }
}
```

**Authorization check:**

```python
# Python — decorator-based authorization
def require_role(*allowed_roles):
    def decorator(handler):
        @wraps(handler)
        def wrapper(request, *args, **kwargs):
            if request.user.role not in allowed_roles:
                raise ForbiddenError("Insufficient permissions")
            return handler(request, *args, **kwargs)
        return wrapper
    return decorator

@require_role("admin", "moderator")
def delete_user(request, user_id):
    # Only admins and moderators reach here
    ...
```

**The refresh token pattern:**
```
Access Token:  short-lived (15 min), sent with every request
Refresh Token: long-lived (7 days), stored securely, used only to get new access tokens

POST /auth/login → { access_token, refresh_token }
POST /auth/refresh (with refresh_token) → { new_access_token }
POST /auth/logout → invalidate the refresh token server-side
```

This gives you the statelessness benefits of JWTs (no DB lookup on every request for the access token) while retaining the ability to revoke sessions (by invalidating the refresh token).

### GOTCHAS

- **Storing JWTs in localStorage.** Vulnerable to XSS — any script on the page can steal the token. Use `httpOnly`, `Secure`, `SameSite=Strict` cookies for browser-based apps.
- **Not validating JWT claims.** Checking the signature is necessary but not sufficient. You must also check `exp` (expiry), `aud` (audience), and `iss` (issuer). A valid token from a different service is still unauthorized.
- **Using symmetric signing (HS256) in multi-service architectures.** Every service has the signing secret, so any service can forge tokens. Use asymmetric signing (RS256/ES256) — only the auth service has the private key, other services have the public key.
- **Missing authorization on every endpoint.** Authentication middleware runs globally, but authorization is per-endpoint. Engineers add new endpoints and forget to add permission checks. Default-deny is safer than default-allow.
- **Broken Object-Level Authorization (BOLA/IDOR).** User A requests `GET /api/orders/42`. The server checks that User A is authenticated but not that order 42 belongs to User A. This is the #1 API vulnerability per OWASP API Security Top 10.

### HOW THIS CONNECTS

You've verified who the user is and what they're allowed to do. But the data they sent — is it actually valid? A user might be authenticated and authorized but still send `age: -5` or `email: "not-an-email"`. That's **validation & transformation**.

---

## 6. Validation & Transformation

### WHY

Every piece of data crossing a trust boundary must be validated. The client is a trust boundary. Other services are trust boundaries. Even your own database is — you might have legacy data that violates current rules. Validation ensures your system operates on data that meets its invariants. Without it, garbage data propagates through your system, corrupts your database, and causes cascading failures that are nightmarish to debug because the root cause (bad input) is hours or days removed from the symptom (wrong output).

**Concrete failure:** A user submits a form with `quantity: -3`. No validation on the backend. The order total becomes negative. The payment processor interprets this as a refund. The company loses money. This actually happened at real companies.

### WHAT

**Validation** = rejecting data that doesn't meet requirements.
**Transformation** = converting data into the internal format you need.

These are separate concerns, but they often happen together. Think of it as a pipeline:

```
Raw Input → Deserialize → Validate → Transform → Internal Representation
```

**Types of validation:**
- **Type validation:** Is `age` a number? Is `email` a string?
- **Format validation:** Is `email` a valid email format? Is `date` in ISO 8601?
- **Range validation:** Is `age` between 0 and 150? Is `quantity` positive?
- **Business rule validation:** Is this coupon code still valid? Does this product exist?
- **Cross-field validation:** If `role` is `"student"`, `school_id` must be present.

The first three belong in the validation layer. Business rule validation often lives in the service/BLL layer because it requires database lookups.

### HOW

**"Parse, don't validate"** — a principle from typed functional programming that means your validation step should produce a new, strongly-typed value, not just return true/false on the original untyped input.

```typescript
// Bad: validate returns boolean, you still work with untyped data
function isValidAge(input: unknown): boolean {
  return typeof input === 'number' && input >= 0 && input <= 150;
}

// Good: parse returns a typed result or throws
function parseAge(input: unknown): number {
  if (typeof input !== 'number' || input < 0 || input > 150) {
    throw new ValidationError('age must be a number between 0 and 150');
  }
  return input; // TypeScript now knows this is a number
}
```

**Transformation examples:**
```python
# Normalize email to lowercase (transformation)
email = raw_email.strip().lower()

# Parse date string to datetime object
created_at = datetime.fromisoformat(raw_date_string)

# Convert cents to dollars for display
display_price = f"${amount_cents / 100:.2f}"
```

**Schema validation libraries** (framework-agnostic concept, different implementations):
- **JavaScript/TypeScript:** zod, yup, joi, ajv
- **Python:** pydantic, marshmallow, cerberus
- **Go:** go-playground/validator, ozzo-validation
- **Java:** Bean Validation (JSR 380) / Hibernate Validator
- **Rust:** serde + validator crate

```python
# Pydantic (Python) — model-based validation + transformation
from pydantic import BaseModel, EmailStr, field_validator

class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    age: int

    @field_validator('name')
    @classmethod
    def name_must_be_nonempty(cls, v):
        if not v.strip():
            raise ValueError('name must not be blank')
        return v.strip()  # transformation: trim whitespace

    @field_validator('age')
    @classmethod
    def age_must_be_reasonable(cls, v):
        if v < 13 or v > 150:
            raise ValueError('age must be between 13 and 150')
        return v
```

### GOTCHAS

- **Client-side validation only.** Never trust the client. Validation must happen on the server. Client-side validation is a UX convenience, not a security measure.
- **Validating too late.** If you validate in the service layer after already doing database lookups, you've wasted resources. Validate at the boundary.
- **Inconsistent error formats.** One endpoint returns `{ "error": "bad email" }`, another returns `{ "errors": [{ "field": "email", "msg": "invalid" }] }`. Standardize your validation error format from day one.
- **Over-permissive regex.** Email validation regexes are either too strict (rejecting valid emails like `user+tag@domain.com`) or too loose. Use a library for format validation.
- **Not transforming before storing.** Storing `" Alice@EXAMPLE.COM  "` as-is means you can't find it later when searching for `"alice@example.com"`. Normalize at the boundary.

### HOW THIS CONNECTS

Validation is often one of the first things that runs on a request after authentication. But it's not the only "before the handler" logic — there's logging, CORS, rate limiting, compression. These cross-cutting concerns are handled by **middlewares**.

---

## 7. Middlewares

### WHY

Some logic needs to run on every request (or a group of requests) regardless of which handler serves it. Logging, authentication, CORS headers, rate limiting, request ID generation, compression, body parsing — this logic is the same across dozens of endpoints. Copy-pasting it into every handler is a maintenance disaster. Middleware is the architectural pattern for factoring it out.

**Concrete failure:** A team adds rate limiting to their `/api/login` endpoint to prevent brute force attacks. They forget to add it to `/api/password-reset`. An attacker brute-forces password reset tokens.

### WHAT

A middleware is a function that wraps a handler. It runs before the handler, optionally modifies the request, lets the handler execute, optionally modifies the response, and handles cleanup. The key insight: **middlewares compose**. You stack them, and each one wraps the next, forming a pipeline (or "onion").

```
Request → [Logging → [Auth → [RateLimit → [Handler] → RateLimit] → Auth] → Logging] → Response
```

Each middleware sees the request on the way in and the response on the way out. This is the "onion model" — execution enters layer by layer, reaches the core (handler), then exits layer by layer.

### HOW

```javascript
// Express.js — middleware is a function(req, res, next)
function requestLogger(req, res, next) {
  const start = Date.now();
  res.on('finish', () => {
    const duration = Date.now() - start;
    console.log(`${req.method} ${req.path} ${res.statusCode} ${duration}ms`);
  });
  next(); // pass control to the next middleware/handler
}

function rateLimiter(req, res, next) {
  const key = req.ip;
  const count = incrementCounter(key); // e.g., Redis INCR
  if (count > 100) {
    return res.status(429).json({ error: 'Too many requests' });
    // Note: no next() call — the chain stops here
  }
  next();
}

app.use(requestLogger);   // runs on ALL routes
app.use(rateLimiter);      // runs on ALL routes
app.use('/api/admin', requireAdmin); // runs only on /api/admin/*
```

```go
// Go — middleware wraps http.Handler
func loggingMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        start := time.Now()
        next.ServeHTTP(w, r)  // call the wrapped handler
        log.Printf("%s %s %v", r.Method, r.URL.Path, time.Since(start))
    })
}

// Compose: handler = logging(auth(rateLimit(actualHandler)))
```

```python
# Django — middleware as a class
class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response  # the next middleware or view

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)  # call the chain
        duration = time.time() - start
        response['X-Request-Duration'] = f"{duration:.3f}s"
        return response
```

### Middleware ordering matters

```
# Correct order:
1. Request ID generation    ← so all subsequent logging has a trace ID
2. Logging                  ← log the raw request
3. CORS                     ← handle preflight requests before auth
4. Body parsing             ← parse JSON before validation
5. Authentication           ← verify identity before checking permissions
6. Rate limiting            ← prevent abuse (can be before or after auth)
7. Authorization            ← check permissions
8. Validation               ← validate request body

# Wrong order: Auth before body parsing means you can't read the body
# to extract credentials in some auth schemes.
```

### GOTCHAS

- **Calling `next()` and then also sending a response.** This causes "headers already sent" errors. Once you respond, don't call next.
- **Async middleware that doesn't await.** In Node.js, if your middleware does async work (e.g., checking a rate limit in Redis) but doesn't properly `await` or return the promise, the handler runs before the middleware finishes.
- **Middleware that swallows errors.** A catch block that logs the error but still calls `next()` without re-throwing or sending an error response. The handler executes with corrupt state.
- **Over-broad middleware.** Applying authentication middleware to your health check endpoint means your load balancer can't check if the server is alive without a valid token.

### HOW THIS CONNECTS

Middlewares often need to pass data downstream — the authenticated user, a request ID, timing information. This data needs to travel with the request without polluting function signatures. That's what **request context** solves.

---

## 8. Request Context

### WHY

When a middleware authenticates a user, the handler needs that user object. When you generate a request ID for tracing, every function in the call chain needs access to it for logging. You could pass these values as function parameters, but that means every function signature would need `request_id`, `user`, `trace_span`, etc. — a maintenance nightmare. Request context is the mechanism for carrying per-request data through the processing pipeline.

**Concrete failure:** In a Node.js app, a developer stores the current user in a module-level variable (`let currentUser = ...`). Under concurrent requests, request A sets `currentUser` to Alice, then request B sets it to Bob, then request A reads `currentUser` and gets Bob. Alice sees Bob's data. This is a **request context leak**.

### WHAT

Request context is a per-request data container that's accessible throughout the request's lifecycle without being passed as an explicit parameter. Different ecosystems implement this differently:

| Language/Framework | Mechanism |
|-------------------|-----------|
| Go | `context.Context` (explicitly passed) |
| Node.js | `AsyncLocalStorage` (implicitly propagated through async chain) |
| Python | `contextvars` (thread/async-local storage) |
| Java | `ThreadLocal` / Project Loom's `ScopedValue` |
| Express.js | `req` object (attach properties to it) |

Go's approach is philosophically different: context is an explicit function parameter, not implicit ambient state. This makes the data flow visible but means every function in the chain needs a `ctx` parameter.

### HOW

```go
// Go — explicit context passing (the Go way)
func authMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        user := validateToken(r.Header.Get("Authorization"))
        // Store user in the request context
        ctx := context.WithValue(r.Context(), userContextKey, user)
        next.ServeHTTP(w, r.WithContext(ctx))
    })
}

func getOrderHandler(w http.ResponseWriter, r *http.Request) {
    // Retrieve user from context
    user := r.Context().Value(userContextKey).(*User)
    orders := orderService.GetByUser(r.Context(), user.ID)
}
```

```javascript
// Node.js — AsyncLocalStorage (implicit propagation)
const { AsyncLocalStorage } = require('async_hooks');
const requestStore = new AsyncLocalStorage();

// Middleware: establish the context
app.use((req, res, next) => {
  const context = {
    requestId: crypto.randomUUID(),
    user: null, // populated later by auth middleware
  };
  requestStore.run(context, () => next());
});

// Anywhere in the call chain — no need to pass it:
function getRequestId() {
  return requestStore.getStore()?.requestId;
}
```

```python
# Python — contextvars
import contextvars

request_id_var = contextvars.ContextVar('request_id')

# In middleware:
request_id_var.set(str(uuid.uuid4()))

# In any function called during request processing:
def log_message(msg):
    rid = request_id_var.get()
    print(f"[{rid}] {msg}")
```

### GOTCHAS

- **Context leaks in concurrent runtimes.** In Node.js without AsyncLocalStorage, using closures or module-level state to carry per-request data is a race condition waiting to happen. The event loop interleaves requests.
- **Overloading context.** Stuffing everything into context (database connections, config, entire request body) turns it into a god object. Context is for **cross-cutting per-request data**: request ID, authenticated user, trace spans. Not for business data.
- **Go context values are untyped.** `context.Value()` returns `interface{}`. Use unexported key types to prevent collisions: `type contextKey struct{}` instead of `context.WithValue(ctx, "user", ...)`.
- **Context cancellation.** Go contexts carry cancellation signals. If a client disconnects, the context gets cancelled. If your handler ignores context cancellation, it keeps doing work (DB queries, API calls) that nobody will read the result of. Always pass context to downstream calls and check `ctx.Err()`.

### HOW THIS CONNECTS

Request context is the glue that lets middlewares communicate with handlers. Now we enter the handler itself — and need to understand the three-layer architecture of **handlers, controllers, and services** that organizes your business logic.

---

## 9. Handlers, Controllers, and Services

### WHY

A common mistake is putting everything into one function: parse the request, check auth, validate, query the database, apply business rules, format the response. This function becomes 200 lines long, impossible to test, and entangled with HTTP-specific concerns. Separating into layers makes each piece independently testable, reusable, and replaceable.

**Concrete failure:** Your "create order" handler directly talks to the database. Now you need the same logic in a background job that processes CSV bulk imports. You can't reuse the handler because it expects an HTTP request object. You duplicate the logic. Now you have two copies that drift apart over time.

### WHAT

The three layers:

**Handler (or Controller):** HTTP-aware. Extracts data from the HTTP request (params, body, headers), calls the service, and constructs the HTTP response. It knows about `req` and `res`, status codes, and headers. It does NOT know about database queries or business rules.

**Service:** Business-logic-aware. Implements operations like "create an order." It knows about business rules ("orders require at least one item," "premium users get free shipping"). It does NOT know about HTTP or database query syntax.

**Repository (or Data Access Layer):** Database-aware. Translates between your domain objects and database operations (queries, inserts, updates). It knows SQL (or ORM calls). It does NOT know about business rules or HTTP.

```
Handler → Service → Repository → Database
  │           │           │
  HTTP     Business     Data
  concerns  rules      access
```

Some codebases merge Handler and Controller (they're effectively the same thing with different names). Some merge Service and Repository (fine for simple CRUD). The point isn't rigid layering — it's **separation of concerns**.

### HOW

```python
# handler.py — HTTP layer
class UserHandler:
    def __init__(self, user_service: UserService):
        self.user_service = user_service

    def create_user(self, request):
        # 1. Extract and validate input (HTTP concern)
        data = CreateUserSchema.parse(request.json)

        # 2. Delegate to service (business logic)
        user = self.user_service.create_user(data.name, data.email)

        # 3. Format response (HTTP concern)
        return Response(
            status=201,
            body=UserResponseSchema.from_model(user),
            headers={"Location": f"/api/users/{user.id}"}
        )

# service.py — business logic layer
class UserService:
    def __init__(self, user_repo: UserRepository, email_service: EmailService):
        self.user_repo = user_repo
        self.email_service = email_service

    def create_user(self, name: str, email: str) -> User:
        # Business rule: email must be unique
        if self.user_repo.find_by_email(email):
            raise DuplicateEmailError(email)

        # Business rule: normalize the name
        user = User(name=name.strip().title(), email=email.lower())
        saved_user = self.user_repo.save(user)

        # Side effect: send welcome email
        self.email_service.send_welcome(saved_user)

        return saved_user

# repository.py — data access layer
class UserRepository:
    def __init__(self, db):
        self.db = db

    def save(self, user: User) -> User:
        result = self.db.execute(
            "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id",
            user.name, user.email
        )
        user.id = result[0]['id']
        return user

    def find_by_email(self, email: str) -> Optional[User]:
        row = self.db.execute("SELECT * FROM users WHERE email = $1", email)
        return User.from_row(row[0]) if row else None
```

**The key test:** Can you call `user_service.create_user()` from a CLI tool, a background job, and an HTTP handler without modification? If yes, you've separated correctly.

### GOTCHAS

- **Handlers doing business logic.** If your handler has an `if` statement that checks a business rule, that rule can't be reused from a different entry point.
- **Services knowing about HTTP.** If your service imports `Request` or `Response`, it's contaminated. Services should take plain data types and return domain objects.
- **Too many layers in simple apps.** For a 3-endpoint CRUD app, Handler → Repository is fine. The service layer earns its existence when you have non-trivial business rules.
- **Circular dependencies between services.** `OrderService` depends on `UserService` which depends on `OrderService`. This indicates a missing abstraction — extract the shared logic into a new service.

### HOW THIS CONNECTS

Now that you understand the layered architecture, let's look at the most common pattern that uses it: **CRUD** — Create, Read, Update, Delete operations, which account for the majority of endpoints in most applications.

---

## 10. CRUD Deep Dive

### WHY

CRUD (Create, Read, Update, Delete) operations are the bread and butter of backend engineering. They seem trivial — just save and fetch data, right? In practice, they're where most bugs live, because they're where your application state changes. Every CRUD endpoint is a chance for data corruption, race conditions, and security holes.

**Concrete failure:** Two users simultaneously update the same document. User A reads version 1, User B reads version 1. User A saves their changes (version 2). User B saves their changes (also based on version 1, creating a different version 2). User A's changes are silently overwritten. This is the **lost update problem**.

### WHAT

| Operation | HTTP Method | SQL | Success Status | Notes |
|-----------|-------------|-----|----------------|-------|
| Create | POST | INSERT | 201 Created | Return the created resource + Location header |
| Read (one) | GET | SELECT | 200 OK | Return the resource |
| Read (many) | GET | SELECT | 200 OK | Pagination, filtering, sorting |
| Update (full) | PUT | UPDATE | 200 OK | Client sends the entire resource |
| Update (partial) | PATCH | UPDATE | 200 OK | Client sends only changed fields |
| Delete | DELETE | DELETE | 204 No Content | Or 200 with a body, either convention works |

### HOW

**Create with conflict handling:**

```sql
-- PostgreSQL: INSERT with conflict detection
INSERT INTO users (email, name)
VALUES ('alice@example.com', 'Alice')
ON CONFLICT (email) DO NOTHING
RETURNING id, email, name;
-- Returns empty if email already existed (no error thrown)
```

**Read with pagination** (cursor-based is superior to offset-based for large datasets):

```python
# Offset-based: simple but slow for large offsets (DB must scan and discard rows)
# GET /api/users?page=2&limit=20
offset = (page - 1) * limit
db.query("SELECT * FROM users ORDER BY id LIMIT $1 OFFSET $2", limit, offset)

# Cursor-based: fast regardless of position, uses an indexed column
# GET /api/users?cursor=42&limit=20
db.query("SELECT * FROM users WHERE id > $1 ORDER BY id LIMIT $2", cursor, limit)
# Response includes: { "data": [...], "next_cursor": 62 }
```

**Update with optimistic concurrency control** (solving the lost update problem):

```sql
-- Add a version column to your table
ALTER TABLE documents ADD COLUMN version INT DEFAULT 1;

-- Update only if the version matches what the client last saw
UPDATE documents
SET content = $1, version = version + 1
WHERE id = $2 AND version = $3
RETURNING id, version;

-- If zero rows returned: someone else modified it. Return 409 Conflict.
```

```python
def update_document(doc_id, new_content, expected_version):
    result = db.execute(
        "UPDATE documents SET content = %s, version = version + 1 "
        "WHERE id = %s AND version = %s RETURNING id, version",
        new_content, doc_id, expected_version
    )
    if not result:
        raise ConflictError("Document was modified by another user")
    return result[0]
```

**Soft delete vs hard delete:**

```sql
-- Soft delete: keep the row, mark it as deleted
UPDATE users SET deleted_at = NOW() WHERE id = $1;

-- All queries must now filter:
SELECT * FROM users WHERE deleted_at IS NULL;

-- Hard delete: actually remove the row
DELETE FROM users WHERE id = $1;
```

Soft delete gives you undo capability and audit trails. Hard delete gives you simpler queries and GDPR compliance (actually removing data). Most production systems use soft delete for user-facing resources.

### GOTCHAS

- **N+1 query problem.** Fetching a list of orders, then for each order fetching the user. 1 query + N queries. Use JOINs or batch loading.
- **Unbounded reads.** `SELECT * FROM logs` with no LIMIT on a table with 100 million rows. Always paginate. Always.
- **PATCH without merge semantics.** Client sends `{ "name": "Alice" }` as a PATCH. Your code does `UPDATE users SET name=$1, email=$2 WHERE id=$3` with `email=null`. You just wiped the email. PATCH should only update the fields that were sent.
- **Delete without cascade/cleanup.** Deleting a user but leaving their orders, comments, and sessions as orphaned records pointing to a nonexistent user ID.
- **Missing unique constraints.** Relying on application-level uniqueness checks (check-then-insert) without a database UNIQUE constraint. Under concurrent requests, two identical rows slip through.

### HOW THIS CONNECTS

CRUD operations are the building blocks. The next topic — **RESTful architecture** — is the architectural style that organizes these operations into a coherent, predictable API design.

---

## 11. RESTful Architecture & Best Practices

### WHY

Without a consistent architecture for your API, every endpoint is a snowflake. Developer A uses `POST /getUsers`, developer B uses `GET /api/v2/user/list`, developer C uses `GET /fetch-all-users`. Clients can't predict your API. Documentation is a nightmare. REST provides a set of constraints that, when followed, make your API predictable, cacheable, and evolvable.

**Concrete failure:** An API starts at v1 with `/api/getUser?id=5`. Six months later, there are 200 endpoints, each with different naming patterns, different error formats, and inconsistent HTTP method usage. No one can build a client library. The team spends more time answering "how do I use this endpoint" questions than building features.

### WHAT

REST (Representational State Transfer) was defined by Roy Fielding in his 2000 dissertation. It's **not** a protocol or a standard — it's an architectural style with six constraints:

1. **Client-Server:** Client and server are separate. They evolve independently.
2. **Stateless:** Each request contains all information needed to process it. No session state on the server between requests.
3. **Cacheable:** Responses must define whether they're cacheable. Enables CDNs and client-side caching.
4. **Uniform Interface:** The key constraint. Resources have identifiers (URIs), representations (JSON), and self-descriptive messages (proper Content-Type, status codes).
5. **Layered System:** Client doesn't know if it's talking to the origin server or a proxy/cache/load balancer.
6. **Code-on-Demand (optional):** Server can send executable code to the client (e.g., JavaScript).

**The core idea:** Everything is a **resource** identified by a **URI**, manipulated through **representations** (JSON, XML) using **standard HTTP methods**.

### HOW — Practical REST Design

**Resource naming:**
```
# Resources are nouns, not verbs
✅ GET  /api/users          — list users
✅ GET  /api/users/42       — get user 42
✅ POST /api/users          — create a user
✅ PUT  /api/users/42       — replace user 42
❌ GET  /api/getUser/42     — verb in the URL
❌ POST /api/createUser     — verb in the URL

# Nested resources for relationships
GET  /api/users/42/orders       — orders belonging to user 42
GET  /api/users/42/orders/7     — order 7 of user 42

# Use query parameters for filtering, sorting, pagination
GET  /api/users?role=admin&sort=-created_at&limit=20&cursor=abc123
```

**Consistent response envelope:**

```json
// Success (list)
{
  "data": [{ "id": 1, "name": "Alice" }, { "id": 2, "name": "Bob" }],
  "pagination": { "next_cursor": "abc123", "has_more": true }
}

// Success (single)
{
  "data": { "id": 1, "name": "Alice", "email": "alice@example.com" }
}

// Error
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input",
    "details": [
      { "field": "email", "message": "must be a valid email address" }
    ]
  }
}
```

**API versioning strategies:**

| Strategy | Example | Trade-off |
|----------|---------|-----------|
| URL path | `/api/v1/users` | Simple, explicit, but couples version to routing |
| Header | `Accept: application/vnd.api+json;version=2` | Clean URLs, but harder to test/browse |
| Query param | `/api/users?version=2` | Easy to test, but messy |

URL path versioning is the most common and pragmatic choice. Bump the version when you make breaking changes (removing fields, changing types, renaming endpoints).

**HATEOAS (Hypertext As The Engine Of Application State):**

```json
{
  "data": {
    "id": 42,
    "name": "Alice",
    "links": {
      "self": "/api/users/42",
      "orders": "/api/users/42/orders",
      "avatar": "/api/users/42/avatar"
    }
  }
}
```

This is the least-followed REST constraint. In theory, the client discovers available actions through links in the response. In practice, most APIs provide separate documentation (OpenAPI specs) and hardcode URLs in clients. HATEOAS is still valuable for APIs consumed by many teams, because it makes the API self-documenting.

### GOTCHAS

- **Overusing POST.** `POST /api/search` when `GET /api/users?q=alice` would work. GET requests are cacheable; POST requests are not.
- **Inconsistent pluralization.** `/api/user/42` vs `/api/orders/7`. Pick plural, stick with it.
- **Deep nesting.** `/api/users/42/orders/7/items/3/reviews/1`. After 2 levels of nesting, use a flat resource: `GET /api/reviews/1`.
- **Breaking changes without versioning.** Renaming a response field or changing its type breaks all existing clients. Always version before making breaking changes.
- **Ignoring HTTP caching.** If you never set `Cache-Control`, `ETag`, or `Last-Modified` headers, you're forcing every client and CDN to re-fetch on every request.

### HOW THIS CONNECTS

REST gives you the API design framework. The resources your API exposes need to be stored somewhere persistent — that's **databases**, the next topic, and arguably the most important piece of infrastructure in any backend.

---

## 12. Databases

### WHY

Without a database, your application has amnesia. Every restart loses all data. Every server has its own local state. You can't share data between instances. A database is a specialized system that stores data durably, allows concurrent access, and provides guarantees (ACID) that your application code alone cannot.

**Concrete failure:** A developer uses an in-memory dictionary as a "database." The server crashes. All user data is gone. There's no backup. The company loses six months of customer data.

### WHAT

**Two families:**

**Relational (SQL):** PostgreSQL, MySQL, SQLite. Data is organized in tables with defined schemas. Relationships between tables via foreign keys. SQL for queries. Strong consistency (ACID transactions). Best when: your data has relationships, you need complex queries (joins, aggregations), you need transactions.

**Non-relational (NoSQL):** Further subdivided:
- **Document:** MongoDB, CouchDB. Store JSON-like documents. Flexible schema. Good for: heterogeneous data, rapid prototyping, content management.
- **Key-Value:** Redis, DynamoDB. Simple get/set by key. Blazing fast. Good for: caching, sessions, counters.
- **Column-Family:** Cassandra, ScyllaDB. Optimized for writes and time-series data. Good for: logs, IoT data, analytics.
- **Graph:** Neo4j, Amazon Neptune. Optimize for relationship traversal. Good for: social networks, recommendation engines, knowledge graphs.

**ACID properties** (for relational databases):
- **Atomicity:** A transaction is all or nothing. If any part fails, everything rolls back.
- **Consistency:** A transaction moves the database from one valid state to another. Constraints (foreign keys, unique, check) are always satisfied.
- **Isolation:** Concurrent transactions don't interfere with each other (to a configurable degree — see isolation levels).
- **Durability:** Once committed, the data survives crashes (written to disk/WAL).

### HOW — PostgreSQL-Grounded Examples

**Schema design:**

```sql
-- Users table
CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    name        VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ          -- soft delete
);

-- Orders table with foreign key
CREATE TABLE orders (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    total_cents BIGINT NOT NULL CHECK (total_cents >= 0),
    status      VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'paid', 'shipped', 'delivered', 'cancelled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for common queries
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_status ON orders(status) WHERE deleted_at IS NULL;
```

**Connection pooling** (critical for production):

Your database has a maximum number of connections (typically 100-500 for PostgreSQL). If every incoming request opens a new connection, you'll exhaust them under load. A connection pool maintains a set of reusable connections.

```python
# Python with psycopg pool
from psycopg_pool import ConnectionPool

pool = ConnectionPool(
    conninfo="host=localhost dbname=myapp user=app",
    min_size=5,     # always keep 5 connections open
    max_size=20,    # never exceed 20
)

def get_user(user_id):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return cur.fetchone()
    # connection is returned to the pool automatically
```

**Transactions:**

```python
def transfer_funds(from_id, to_id, amount):
    with pool.connection() as conn:
        with conn.transaction():  # BEGIN
            conn.execute(
                "UPDATE accounts SET balance = balance - %s WHERE id = %s AND balance >= %s",
                (amount, from_id, amount)
            )
            rows_affected = conn.rowcount
            if rows_affected == 0:
                raise InsufficientFundsError()  # triggers ROLLBACK
            conn.execute(
                "UPDATE accounts SET balance = balance + %s WHERE id = %s",
                (amount, to_id)
            )
        # COMMIT happens here automatically
```

**Migrations:**

```sql
-- migrations/001_create_users.up.sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL
);

-- migrations/001_create_users.down.sql
DROP TABLE users;
```

Use a migration tool (Flyway, golang-migrate, Alembic, Knex migrations) to version-control your schema changes. Never modify production schemas by hand.

### GOTCHAS

- **No indexes on frequently queried columns.** A `WHERE` clause without an index does a full table scan. On a table with 10 million rows, that query goes from 2ms to 10 seconds.
- **`SELECT *` in production code.** You'll accidentally expose new columns added later (security risk) and fetch unnecessary data (performance). List columns explicitly.
- **String concatenation for queries.** `f"SELECT * FROM users WHERE id = {user_id}"` → SQL injection. Always use parameterized queries.
- **Not using transactions for multi-step operations.** If step 1 succeeds and step 2 fails, you have inconsistent data. Wrap related operations in a transaction.
- **Storing money as floats.** `FLOAT` can't exactly represent `0.1`. Use `BIGINT` (store cents) or `NUMERIC`/`DECIMAL` (exact arithmetic).
- **Connection leaks.** Opening connections without closing them (especially on error paths). Always use connection pool patterns with try/finally or context managers.

### HOW THIS CONNECTS

The database stores your data, but the logic for *how* that data gets created, validated, and transformed — the rules that make your business *your business* — lives in the **Business Logic Layer**.

---

## 13. Business Logic Layer (BLL)

### WHY

The business logic layer is the reason your application exists. Without it, you have a generic CRUD app that any code generator could produce. The BLL encodes the rules, constraints, and workflows that are specific to your domain: "a user can't place an order that exceeds their credit limit," "premium users get free shipping on orders over $50," "an appointment can only be booked during business hours in the provider's timezone."

**Concrete failure:** Business rules are scattered across handlers, database triggers, and frontend code. A new endpoint bypasses the "orders must have at least one item" check that existed in the original handler. Empty orders make it to the payment processor, which charges $0 and flags the merchant for suspicious activity.

### WHAT

The BLL sits between the handler/controller layer and the data access layer. It's where you answer the question: **"given these inputs and the current state of the system, what should happen?"**

```
Handler (HTTP)  →  BLL (Business Rules)  →  Repository (Data)
    Thin               Thick                    Thin
```

The BLL should be the thickest layer. Handlers are thin (just translate HTTP ↔ domain calls). Repositories are thin (just translate domain objects ↔ SQL). The BLL is where the complexity — and the value — lives.

**Domain model vs anemic model:**

An **anemic model** is a data structure with no behavior — just getters and setters. All logic lives in service classes that manipulate these structures. This is common in Java/Spring codebases. It's not inherently wrong, but it spreads business rules across multiple service classes, making them harder to find.

A **rich domain model** embeds behavior in the domain objects themselves:

```python
# Rich domain model — the Order knows its own rules
class Order:
    def __init__(self, user, items):
        if not items:
            raise BusinessRuleViolation("Order must have at least one item")
        self.user = user
        self.items = items
        self.status = OrderStatus.PENDING

    @property
    def total(self):
        subtotal = sum(item.price * item.quantity for item in self.items)
        if self.user.is_premium and subtotal > 5000:  # cents
            return subtotal  # free shipping
        return subtotal + self.shipping_cost

    def cancel(self):
        if self.status == OrderStatus.SHIPPED:
            raise BusinessRuleViolation("Cannot cancel shipped orders")
        self.status = OrderStatus.CANCELLED

    def ship(self):
        if self.status != OrderStatus.PAID:
            raise BusinessRuleViolation("Can only ship paid orders")
        self.status = OrderStatus.SHIPPED
```

### HOW — Organizing Business Logic

**Service layer orchestrating multiple operations:**

```python
class OrderService:
    def __init__(self, order_repo, inventory_service, payment_service, notification_service):
        self.order_repo = order_repo
        self.inventory = inventory_service
        self.payment = payment_service
        self.notifications = notification_service

    def place_order(self, user, cart_items) -> Order:
        # 1. Business rule: validate inventory
        for item in cart_items:
            if not self.inventory.check_availability(item.product_id, item.quantity):
                raise OutOfStockError(item.product_id)

        # 2. Create domain object (business rules enforced in constructor)
        order = Order(user=user, items=cart_items)

        # 3. Business rule: check credit limit
        if order.total > user.credit_limit_cents:
            raise CreditLimitExceeded(order.total, user.credit_limit_cents)

        # 4. Reserve inventory (side effect)
        self.inventory.reserve(cart_items)

        try:
            # 5. Process payment (side effect)
            payment = self.payment.charge(user, order.total)
            order.mark_paid(payment.id)

            # 6. Persist
            saved_order = self.order_repo.save(order)

            # 7. Notify (async, non-blocking — don't fail the order if email fails)
            self.notifications.send_order_confirmation_async(user, saved_order)

            return saved_order
        except PaymentError:
            # Compensating action: release reserved inventory
            self.inventory.release(cart_items)
            raise
```

### GOTCHAS

- **Business logic in the database.** Triggers, stored procedures, and check constraints *can* enforce rules, but they're invisible to the application, hard to test, and impossible to reuse across databases. Use DB constraints as a safety net, not as the primary enforcement.
- **Business logic in the handler.** If a business rule lives in a handler, it doesn't apply when the same operation is triggered from a queue worker, CLI tool, or another service.
- **Missing compensating actions.** In the example above, if payment succeeds but the save fails, you've charged the user without creating an order. Always think about rollback/compensation for multi-step operations.
- **God services.** A single `OrderService` with 50 methods. Split by sub-domain or use case.

### HOW THIS CONNECTS

The BLL often needs data fast — sometimes the same data repeatedly. Reading from the database on every request is slow and costly. That's where **caching** comes in: keeping frequently accessed data in faster storage.

---

## 14. Caching

### WHY

Databases are durable but slow (disk I/O, network round-trips, query parsing). Some queries are expensive (complex joins, aggregations) and their results don't change on every request. Caching stores the results of expensive operations in fast storage (memory) so subsequent requests get the answer in microseconds instead of milliseconds.

**Concrete failure:** An e-commerce homepage makes 15 database queries per page load (featured products, categories, banners, user cart, recommendations). At 1,000 concurrent users, the database receives 15,000 queries per second. Response times spike from 100ms to 5 seconds. The database connection pool is exhausted. All requests start timing out. The entire site goes down.

### WHAT

**Cache layers:**

```
Client → CDN/Edge Cache → Reverse Proxy Cache → Application Cache → Database
```

- **Client cache:** Browser cache controlled by `Cache-Control` headers.
- **CDN/Edge:** Cloudflare, CloudFront. Caches static assets and sometimes API responses geographically close to users.
- **Reverse proxy:** Nginx, Varnish. Sits in front of your app, caches responses.
- **Application cache:** Redis, Memcached. Your code explicitly caches computation results.
- **Database cache:** PostgreSQL's shared_buffers, query plan cache. Automatic, but limited.

**Application-level caching strategies:**

| Strategy | Description | When to use |
|----------|-------------|-------------|
| Cache-Aside (Lazy) | App checks cache first; on miss, queries DB, writes to cache | Most common. Simple. |
| Write-Through | App writes to cache and DB simultaneously | When you need strong consistency |
| Write-Behind | App writes to cache, cache asynchronously writes to DB | High write throughput (risky: data loss if cache crashes) |
| Read-Through | Cache itself fetches from DB on miss | When the cache layer handles loading |

### HOW

**Cache-Aside pattern with Redis:**

```python
import redis
import json

cache = redis.Redis(host='localhost', port=6379, db=0)

def get_user(user_id: int) -> dict:
    cache_key = f"user:{user_id}"

    # 1. Check cache
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    # 2. Cache miss — query database
    user = db.query("SELECT id, name, email FROM users WHERE id = %s", user_id)
    if not user:
        return None

    # 3. Populate cache with TTL
    cache.setex(cache_key, 300, json.dumps(user))  # expire in 5 minutes

    return user

def update_user(user_id: int, data: dict):
    # Update database
    db.execute("UPDATE users SET name = %s WHERE id = %s", data['name'], user_id)

    # Invalidate cache (don't update — invalidate)
    cache.delete(f"user:{user_id}")
```

**Why invalidate, not update?** If you update the cache, there's a window where the DB has new data and the cache has old data, or vice versa. Invalidation means the next read will fetch fresh data from the DB. It's simpler and safer.

**Cache key design:**

```
# Good: predictable, namespaced, includes all query parameters
user:{id}
product:{id}:details
search:users:role=admin:page=1:limit=20

# Bad: ambiguous, collision-prone
user_data
search_results
```

**TTL (Time To Live)** strategy:
- **Hot, frequently accessed, slowly changing data:** Long TTL (hours). Example: product catalog.
- **User-specific data:** Medium TTL (minutes). Example: user profile.
- **Real-time data:** Short TTL (seconds) or no cache. Example: stock prices.
- **Computed aggregations:** Cache the result, invalidate when inputs change. Example: dashboard statistics.

### GOTCHAS

- **Cache stampede (thundering herd).** A popular cache key expires. 1,000 requests simultaneously hit the database to rebuild it. Solution: **lock-based recomputation** (only one request rebuilds, others wait) or **probabilistic early expiration** (refresh before TTL).
- **Stale data.** User updates their profile, but the cache still has the old version. They see their own old data. Solution: invalidate on write, or use short TTLs.
- **Caching negative results.** User ID 999 doesn't exist. Without caching the miss, every request for user 999 hits the database. Cache the miss with a short TTL: `cache.setex("user:999", 60, "null")`.
- **Memory pressure.** Caching too much data without eviction policies. Redis will OOM. Set `maxmemory` and an eviction policy (`allkeys-lru` is usually correct).
- **Serialization overhead.** JSON-encoding large objects to put them in Redis can be slower than the DB query you were trying to avoid. Profile before caching.

### HOW THIS CONNECTS

Caching is about making reads fast. But some operations don't need to be fast — they need to be reliable and happen asynchronously. Sending an email after a user signs up shouldn't block the response. That's what **transactional emails** (and more broadly, async processing) handle.

---

## 15. Transactional Emails

### WHY

Transactional emails are system-triggered emails in response to a user action: welcome emails, password resets, order confirmations, invoice receipts. They're not marketing blasts — they're part of your application's functionality. Getting them wrong means users can't reset their passwords, don't know their order shipped, or worse, receive someone else's sensitive information.

**Concrete failure:** The email sending code is synchronous in the signup handler. The SMTP server is slow (3 seconds per email). Under load, the signup endpoint responds in 3+ seconds. Users think the signup failed. They retry. You get duplicate accounts.

### WHAT

**The pipeline:**

```
User Action → Handler → Queue (async) → Email Worker → SMTP/API → Delivery
```

Key insight: **never send emails synchronously in the request path.** Push them to a queue and let a background worker handle delivery. If the email service is down, the queue retries. The user gets their HTTP response immediately.

**Components:**
- **Templates:** HTML/text templates with variables (user name, order details). Use a template engine (Handlebars, Jinja2, mjml).
- **Transport:** SMTP protocol, or more commonly, an email API (SendGrid, AWS SES, Postmark, Resend).
- **Queue:** The mechanism to decouple email sending from request handling (covered in detail in Topic 16).

### HOW

```python
# 1. Define the email template
# templates/welcome.html
"""
<h1>Welcome, {{ user_name }}!</h1>
<p>Verify your email: <a href="{{ verification_url }}">Click here</a></p>
"""

# 2. Queue the email (in your service layer)
def create_user(name, email):
    user = user_repo.save(User(name=name, email=email))
    verification_token = generate_token(user.id)

    # Don't send here — queue it
    email_queue.enqueue(
        template="welcome",
        to=user.email,
        context={
            "user_name": user.name,
            "verification_url": f"https://app.com/verify?token={verification_token}"
        }
    )
    return user

# 3. Worker processes the queue
def email_worker(job):
    html = render_template(job.template, job.context)
    try:
        email_client.send(
            to=job.to,
            subject=SUBJECTS[job.template],
            html=html,
        )
    except TemporaryError:
        raise Retry(delay=60)  # retry in 60 seconds
    except PermanentError:
        log.error(f"Permanent email failure: {job.to}", exc_info=True)
        # Don't retry — bad address, blocked domain, etc.
```

**Email deliverability essentials:**

| Record | Purpose |
|--------|---------|
| SPF | Declares which servers can send email for your domain |
| DKIM | Cryptographic signature proving the email wasn't tampered with |
| DMARC | Policy for what to do with emails that fail SPF/DKIM |

Without these DNS records, your emails go to spam. Set them up before sending a single transactional email.

### GOTCHAS

- **No idempotency.** Queue worker crashes after sending but before acknowledging the job. Job gets re-processed. User gets two welcome emails. Solution: record sent emails in a database table, check before sending, or use idempotency keys with your email provider.
- **Sensitive data in emails.** Including the password in a welcome email, or a full credit card number in a receipt. Emails are transmitted in plaintext.
- **No unsubscribe mechanism for non-marketing emails.** Even transactional emails should have a way to manage preferences. Some jurisdictions require it.
- **Sending from a no-reply address.** Users reply to transactional emails with support questions. Those replies go to a void. Use a real address or set `Reply-To`.

### HOW THIS CONNECTS

Emails are just one example of work that should happen asynchronously. The broader pattern — offloading work from the request path into background workers — is **task queuing & scheduling**, the next topic.

---

## 16. Task Queuing & Scheduling

### WHY

Not everything should happen during an HTTP request. Sending emails, generating reports, processing uploaded images, syncing data with third-party APIs — these are slow, failure-prone, or non-critical for the user's immediate response. Task queues let you defer this work to background workers, keeping your API fast and resilient.

**Concrete failure:** An endpoint generates a PDF report synchronously. It takes 30 seconds. The reverse proxy (Nginx) has a 30-second timeout. The request times out. The user retries. Now you're generating two reports. Your server runs out of memory because PDF generation is memory-intensive. Everything falls over.

### WHAT

**Queue = producer/consumer pattern:**

```
Producer (API handler) → Queue (Redis, RabbitMQ, SQS) → Consumer (Worker process)
```

**Key concepts:**
- **At-least-once delivery:** The queue guarantees the message is delivered at least once. If the worker crashes, the message is redelivered. Your worker must be idempotent.
- **At-most-once delivery:** The message is delivered at most once but might be lost. Rare — used for metrics or non-critical data.
- **Exactly-once delivery:** Theoretically impossible in distributed systems. Achieved in practice by combining at-least-once delivery with idempotent consumers.

**Scheduling** is time-triggered work:
- **Cron jobs:** Run at fixed intervals (daily report generation, monthly billing).
- **Delayed tasks:** Run once after a delay (send a reminder 24 hours after signup).
- **Recurring tasks:** Run repeatedly with intervals (poll a third-party API every 5 minutes).

### HOW

```python
# Using Celery (Python) — the most common task queue in Python

# tasks.py — define tasks
from celery import Celery

app = Celery('myapp', broker='redis://localhost:6379/0')

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_image(self, image_id):
    try:
        image = download_image(image_id)
        thumbnail = resize(image, 200, 200)
        upload_thumbnail(image_id, thumbnail)
        db.execute("UPDATE images SET thumbnail_ready = true WHERE id = %s", image_id)
    except TemporaryError as exc:
        raise self.retry(exc=exc)

@app.task
def generate_monthly_report(month, year):
    data = aggregate_monthly_data(month, year)
    pdf = render_report(data)
    store_report(pdf, f"report-{year}-{month}.pdf")
    notify_admin(f"Report for {year}-{month} ready")

# handler.py — enqueue from request handler
def upload_image(request):
    image_id = save_raw_image(request.file)
    process_image.delay(image_id)  # .delay() enqueues it, returns immediately
    return Response(status=202, body={"message": "Processing", "image_id": image_id})
    # 202 Accepted — "I got your request, will process it later"

# Scheduling with Celery Beat
app.conf.beat_schedule = {
    'monthly-report': {
        'task': 'tasks.generate_monthly_report',
        'schedule': crontab(day_of_month=1, hour=2, minute=0),  # 1st of month, 2am
        'args': (),  # args computed dynamically in the task
    },
}
```

```go
// Go — using goroutines for simple background work (no external queue)
func uploadHandler(w http.ResponseWriter, r *http.Request) {
    imageID := saveRawImage(r)

    // Simple: fire and forget with a goroutine
    go func() {
        if err := processImage(imageID); err != nil {
            log.Printf("image processing failed: %v", err)
            // But who retries? Nobody. This is why you need a real queue.
        }
    }()

    w.WriteHeader(http.StatusAccepted)
    json.NewEncoder(w).Encode(map[string]string{"image_id": imageID})
}
```

The Go goroutine approach is simple but has no retry, no persistence (if the server crashes, the task is lost), and no observability. For production workloads, use a proper queue (even in Go).

### GOTCHAS

- **Non-idempotent workers.** The message is delivered twice (at-least-once). Your worker charges the customer twice. Solution: use a deduplication key (e.g., order ID) and check whether the work was already done.
- **Poison messages.** A malformed message causes the worker to crash every time it processes it. It's retried infinitely. Solution: dead-letter queue — after N retries, move the message to a separate queue for investigation.
- **No backpressure.** Producers enqueue faster than consumers process. The queue grows until it runs out of memory. Solution: set queue size limits, add workers, or rate-limit the producer.
- **Cron jobs without distributed locking.** You have 5 servers, each running the same cron. The daily report runs 5 times. Solution: use a distributed lock (Redis SETNX) so only one instance runs.
- **Lost tasks on deploy.** Worker is processing a task, you deploy new code, the worker process is killed. The task is lost. Solution: graceful shutdown (Topic 21) — stop accepting new tasks, finish current ones, then exit.

### HOW THIS CONNECTS

Task queues and background workers generate data that often needs to be searched and analyzed. Product searches, log analysis, full-text search — these use cases call for a specialized search engine, which is where **Elasticsearch** comes in.

---

## 17. Elasticsearch

### WHY

Relational databases are excellent for structured queries (`WHERE email = 'alice@example.com'`) but terrible at full-text search (`WHERE description LIKE '%lightweight waterproof running shoe%'`). `LIKE '%term%'` can't use indexes, requires scanning every row, doesn't handle synonyms ("sneaker" vs "shoe"), doesn't rank by relevance, and doesn't support fuzzy matching (typo tolerance). Elasticsearch is a distributed search engine built for exactly this problem.

**Concrete failure:** An e-commerce site runs product search using SQL `LIKE` queries. A customer searches for "running shoes." The query scans 2 million product rows, takes 8 seconds, returns results in random order (no relevance ranking), and misses products listed as "sneakers" or "jogging footwear."

### WHAT

Elasticsearch is a distributed search and analytics engine built on Apache Lucene. It stores documents (JSON objects) and builds an **inverted index** — a mapping from terms to the documents containing them.

**Inverted index (the core data structure):**

```
Term          → Documents
"running"     → [doc_1, doc_5, doc_23]
"shoe"        → [doc_1, doc_7, doc_23, doc_45]
"waterproof"  → [doc_1, doc_12]
```

Searching for "running shoe" = intersection of the two posting lists = `[doc_1, doc_23]`, scored by relevance (TF-IDF or BM25).

**Key concepts:**
- **Index:** Like a database table. A collection of documents with similar structure.
- **Document:** A JSON object stored in an index.
- **Mapping:** The schema of an index — field names and their types (text, keyword, date, integer).
- **Analyzer:** Tokenizer + filters that process text before indexing. E.g., "Running SHOES!" → ["running", "shoes"].
- **Shard:** A subdivision of an index for horizontal scaling.
- **Replica:** A copy of a shard for redundancy and read throughput.

### HOW

```json
// Create an index with mapping
PUT /products
{
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1
  },
  "mappings": {
    "properties": {
      "name":        { "type": "text", "analyzer": "english" },
      "description": { "type": "text", "analyzer": "english" },
      "category":    { "type": "keyword" },
      "price_cents": { "type": "integer" },
      "in_stock":    { "type": "boolean" },
      "created_at":  { "type": "date" }
    }
  }
}

// Index a document
POST /products/_doc
{
  "name": "Lightweight Waterproof Running Shoe",
  "description": "Breathable mesh upper with waterproof membrane",
  "category": "footwear",
  "price_cents": 12999,
  "in_stock": true,
  "created_at": "2024-01-15"
}

// Search with relevance ranking
GET /products/_search
{
  "query": {
    "bool": {
      "must": {
        "multi_match": {
          "query": "running shoes",
          "fields": ["name^3", "description"],
          "fuzziness": "AUTO"
        }
      },
      "filter": [
        { "term": { "in_stock": true } },
        { "range": { "price_cents": { "lte": 15000 } } }
      ]
    }
  }
}
```

**`text` vs `keyword` field types:**
- `text`: Analyzed (tokenized, lowercased, stemmed). Use for full-text search. "Running Shoes" → indexed as ["run", "shoe"].
- `keyword`: Not analyzed. Stored as-is. Use for exact matching, filtering, aggregations. "Running Shoes" is stored as "Running Shoes".

**Syncing data from your primary database to Elasticsearch:**

```
Primary DB (source of truth) → Change Data Capture / Queue → Elasticsearch (search replica)
```

Elasticsearch is NOT your primary database. It's a search index built from your primary database. Data flows one direction: DB → ES.

Sync strategies:
1. **Dual write:** On every DB write, also write to ES. Simple but risks inconsistency if one write fails.
2. **Change Data Capture (CDC):** Tools like Debezium watch the DB's write-ahead log and push changes to ES via Kafka. Reliable but complex.
3. **Periodic sync:** Cron job re-indexes changed records. Simple but introduces lag.

### GOTCHAS

- **Using Elasticsearch as a primary database.** It's eventually consistent, can lose acknowledged writes under certain failure modes, and doesn't support transactions. It's a search index, not a database.
- **Mapping explosion.** Dynamically indexing documents with thousands of unique field names (e.g., user-generated key-value pairs). Each field creates metadata. Solution: disable dynamic mapping and use explicit mappings.
- **Not paginating search results.** ES defaults to returning 10 results. Using `from: 10000, size: 10` is extremely expensive (ES must load and score 10,010 documents). Use `search_after` for deep pagination.
- **Indexing without throttling.** Bulk-indexing millions of documents without rate limiting overwhelms the cluster. Use the Bulk API with reasonable batch sizes (1,000-5,000 docs per batch).

### HOW THIS CONNECTS

Search, like every other part of your system, can fail. Network errors, malformed queries, unavailable clusters — these need to be handled gracefully. That brings us to **error handling**, a topic that cuts across everything we've discussed so far.

---

## 18. Error Handling

### WHY

Every line of code can fail. Database connections drop, external APIs time out, users send garbage input, disks fill up. Error handling determines whether these failures crash your server, corrupt data, or are handled gracefully with informative feedback. Bad error handling is the #1 cause of cascading failures in production — one unhandled error in a background job brings down the entire worker pool.

**Concrete failure:** A Node.js API doesn't have an unhandled promise rejection handler. An async function throws an error that nobody catches. In Node < 15, this triggers a warning. In Node ≥ 15, the process crashes. Every in-flight request is dropped.

### WHAT

**Error categories:**

| Category | Examples | Response to client | Action |
|----------|----------|-------------------|--------|
| Operational | Network timeout, DB down, disk full | 5xx (retry-safe) | Log, alert, retry |
| Programmer | Null reference, type error, logic bug | 500 | Log, fix the code |
| Validation | Bad input, missing fields | 4xx (400, 422) | Return specific error message |
| Business | Insufficient funds, duplicate email | 4xx (409, 422) | Return business-specific message |
| External | Third-party API error | 502 Bad Gateway | Log, retry if appropriate |

The fundamental principle: **don't let implementation details leak to the client.** A stack trace in a 500 response is a security vulnerability (leaks file paths, library versions, internal architecture).

### HOW

**Structured error responses:**

```json
{
  "error": {
    "code": "INSUFFICIENT_FUNDS",
    "message": "Account balance is insufficient for this transfer",
    "details": {
      "required": 5000,
      "available": 3200
    },
    "request_id": "req_abc123"
  }
}
```

**Error hierarchy in your application:**

```python
# Base application error
class AppError(Exception):
    def __init__(self, message, code, status_code=500, details=None):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details

class NotFoundError(AppError):
    def __init__(self, resource, resource_id):
        super().__init__(
            message=f"{resource} {resource_id} not found",
            code="NOT_FOUND",
            status_code=404
        )

class ValidationError(AppError):
    def __init__(self, errors):
        super().__init__(
            message="Validation failed",
            code="VALIDATION_ERROR",
            status_code=422,
            details=errors
        )

class ConflictError(AppError):
    def __init__(self, message):
        super().__init__(message=message, code="CONFLICT", status_code=409)
```

**Global error handler middleware:**

```python
# This is the last middleware — catches everything handlers don't
def error_handler_middleware(get_response):
    def middleware(request):
        try:
            return get_response(request)
        except AppError as e:
            # Known application error — structured response
            return JsonResponse(
                {"error": {"code": e.code, "message": e.message, "details": e.details}},
                status=e.status_code
            )
        except Exception as e:
            # Unknown error — don't leak details
            request_id = getattr(request, 'request_id', 'unknown')
            logger.exception(f"Unhandled error [request_id={request_id}]")
            return JsonResponse(
                {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred",
                           "request_id": request_id}},
                status=500
            )
    return middleware
```

**Go's explicit error handling:**

```go
// Go doesn't have exceptions — errors are values
func getUser(id int) (*User, error) {
    user, err := db.QueryUser(id)
    if err != nil {
        if errors.Is(err, sql.ErrNoRows) {
            return nil, &NotFoundError{Resource: "user", ID: id}
        }
        return nil, fmt.Errorf("querying user %d: %w", id, err) // wrap with context
    }
    return user, nil
}
```

Go's approach forces you to handle errors at every call site. It's verbose but makes error paths explicit and visible. You can't accidentally ignore an error the way you can with uncaught exceptions.

### GOTCHAS

- **Swallowing errors.** `catch (e) {}` — the error disappears. The operation silently fails. Data is inconsistent. Nobody knows until a customer complains.
- **Logging the error but not returning an appropriate response.** The handler logs the error and returns 200 with an empty body. The client thinks the operation succeeded.
- **Retrying non-idempotent operations.** A payment fails with a timeout. Did it actually go through? Retrying might double-charge. Use idempotency keys for side-effecting operations.
- **Generic error messages.** "Something went wrong" with no request ID or error code. The user can't report the issue, and support can't find it in logs. Always include a request ID.
- **Error serialization issues.** JavaScript's `Error` objects don't JSON.stringify() cleanly (the `message` and `stack` properties are non-enumerable). You need explicit serialization.

### HOW THIS CONNECTS

Error messages reference configuration values ("database connection limit exceeded"), environment-specific behavior ("retry 3 times"), and feature flags. Where do these values come from? That's **config management**.

---

## 19. Config Management

### WHY

Your application behaves differently depending on where it runs: different database URLs in development vs staging vs production, different API keys for third-party services, different feature flags for different regions. Hardcoding these values is a security risk (API keys in source code), a deployment bottleneck (you must rebuild to change a config), and a debugging nightmare ("it works on my machine").

**Concrete failure:** A developer commits a `.env` file with production database credentials to a public GitHub repository. An automated scraper finds it within minutes. The database is compromised.

### WHAT

Configuration is any value that changes between deployments but not between code changes. The 12-Factor App methodology (Topic 28) is definitive here: **store config in the environment.**

**Configuration hierarchy** (from highest to lowest precedence):
1. **Command-line flags** — `--port=8080`
2. **Environment variables** — `PORT=8080`
3. **Config files** (per-environment) — `config/production.yaml`
4. **Defaults in code** — fallback values

**Categories of configuration:**

| Type | Examples | Storage |
|------|----------|---------|
| Secrets | API keys, DB passwords, JWT secrets | Vault, AWS Secrets Manager, env vars (never in code) |
| Infrastructure | DB host, Redis URL, port number | Env vars, config files |
| Feature flags | `enable_new_checkout: true` | Config service (LaunchDarkly, Unleash) or env vars |
| Application | Pagination defaults, rate limits | Config files, env vars |

### HOW

```python
# Python — pydantic-settings for typed config with validation
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # Database
    database_url: str = Field(..., description="PostgreSQL connection string")
    db_pool_min: int = Field(5, ge=1)
    db_pool_max: int = Field(20, ge=1)

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = Field(..., min_length=32)
    jwt_expiry_minutes: int = 15

    # App
    debug: bool = False
    log_level: str = "INFO"

    class Config:
        env_file = ".env"        # load from .env file
        env_prefix = ""          # no prefix (or "MYAPP_" if you want namespacing)
        case_sensitive = False

# Usage
settings = Settings()  # Reads from env vars and .env file, validates types
# If DATABASE_URL is not set, pydantic raises an error at startup — fail fast
```

```go
// Go — envconfig for struct-based config
type Config struct {
    Port        int    `envconfig:"PORT" default:"8080"`
    DatabaseURL string `envconfig:"DATABASE_URL" required:"true"`
    JWTSecret   string `envconfig:"JWT_SECRET" required:"true"`
    Debug       bool   `envconfig:"DEBUG" default:"false"`
}

func LoadConfig() (*Config, error) {
    var cfg Config
    if err := envconfig.Process("", &cfg); err != nil {
        return nil, fmt.Errorf("loading config: %w", err)
    }
    return &cfg, nil
}
```

**The `.env` file pattern:**

```bash
# .env (development only — NEVER committed to version control)
DATABASE_URL=postgres://dev:dev@localhost:5432/myapp_dev
JWT_SECRET=dev-secret-not-for-production-use-32chars!!
REDIS_URL=redis://localhost:6379/0
DEBUG=true

# .env.example (committed — shows required vars without values)
DATABASE_URL=
JWT_SECRET=
REDIS_URL=
DEBUG=false
```

### GOTCHAS

- **Secrets in version control.** `.env` files in git. Config files with passwords. Even if you delete them, they're in the git history forever. Use `.gitignore` from the start and consider tools like `git-secrets` to prevent accidental commits.
- **No validation at startup.** Missing or malformed config discovered at runtime — maybe hours after deployment, when a rarely-used code path is hit. Validate all config at application startup. Fail fast.
- **Config scattered everywhere.** Some values in env vars, some in a YAML file, some hardcoded in a constants file, some in the database. Centralize.
- **Boolean config as strings.** `ENABLE_FEATURE=true` is a string, not a boolean. `if (process.env.ENABLE_FEATURE)` is true for any non-empty string, including `"false"`. Use a config library that handles type conversion.
- **Different defaults in different environments.** Pagination limit defaults to 10 in one service and 50 in another. Define defaults once in a config struct, not at usage sites.

### HOW THIS CONNECTS

Config management decides *what* gets logged, at what level, and where. Logging, in turn, is how you understand what your running system is actually doing — which leads us to **logging, monitoring & observability**.

---

## 20. Logging, Monitoring & Observability

### WHY

You can't SSH into a production server and add print statements when something goes wrong. Logging, monitoring, and observability are how you understand what your system is doing *right now* and what it was doing *when things broke at 3 AM*. Without them, debugging production issues is guesswork.

**Concrete failure:** A service starts returning errors. There are no logs, no metrics, no traces. The team spends 4 hours restarting services, checking config, and reading code before discovering that a downstream database is out of disk space. With a single disk usage metric and an alert at 80%, this would have been caught before any errors occurred.

### WHAT

The three pillars of observability (per the Google SRE Book and industry consensus):

**1. Logs** — Discrete events with context.
```json
{"timestamp":"2024-01-15T10:30:00Z","level":"ERROR","message":"payment failed",
 "request_id":"req_abc123","user_id":42,"amount_cents":5000,"error":"card_declined"}
```

**2. Metrics** — Numerical measurements aggregated over time.
```
http_requests_total{method="GET", path="/api/users", status="200"} 15234
http_request_duration_seconds{quantile="0.99"} 0.250
db_connection_pool_active 18
db_connection_pool_max 20
```

**3. Traces** — The path of a single request through multiple services.
```
Trace ID: abc123
├─ API Gateway (12ms)
│  └─ Auth Service (3ms)
├─ Order Service (45ms)
│  ├─ Database Query (8ms)
│  ├─ Inventory Service (15ms)
│  └─ Payment Service (20ms)
└─ Total: 45ms
```

### HOW

**Structured logging** (not printf-style):

```python
import structlog

logger = structlog.get_logger()

# Bad: unstructured
print(f"User {user_id} placed order {order_id} for ${amount}")

# Good: structured, parseable, filterable
logger.info("order_placed",
    user_id=user_id,
    order_id=order_id,
    amount_cents=amount,
    payment_method="stripe",
    duration_ms=elapsed
)
# Output: {"event":"order_placed","user_id":42,"order_id":99,"amount_cents":5000,...,"timestamp":"2024-01-15T10:30:00Z"}
```

**Log levels:**

| Level | When to use | Example |
|-------|-------------|---------|
| DEBUG | Detailed diagnostic info (dev only) | "Parsed request body: {…}" |
| INFO | Normal operations worth recording | "Order created", "User logged in" |
| WARN | Something unexpected but recoverable | "Cache miss rate above 50%", "Retrying failed request" |
| ERROR | Operation failed, needs attention | "Payment processing failed", "Database connection lost" |
| FATAL | Unrecoverable, application must stop | "Cannot bind to port", "Missing required config" |

**The four golden signals** (from Google SRE):
1. **Latency:** How long requests take (especially the tail — p95, p99).
2. **Traffic:** Requests per second.
3. **Errors:** Error rate (5xx responses / total responses).
4. **Saturation:** How full your resources are (CPU, memory, DB connections, disk).

```python
# Prometheus metrics (Python example)
from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'path', 'status']
)

REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency',
    ['method', 'path'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

# In middleware:
def metrics_middleware(get_response):
    def middleware(request):
        start = time.time()
        response = get_response(request)
        duration = time.time() - start

        REQUEST_COUNT.labels(request.method, request.path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, request.path).observe(duration)

        return response
    return middleware
```

**Distributed tracing with request IDs:**

```python
# Generate a unique ID per request (middleware)
def tracing_middleware(get_response):
    def middleware(request):
        request_id = request.headers.get('X-Request-Id', str(uuid.uuid4()))
        # Bind to structured logger for all downstream log calls
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = get_response(request)
        response['X-Request-Id'] = request_id
        return response
    return middleware
```

**Alerting rules** (Prometheus/Grafana example):

```yaml
# Alert if error rate exceeds 1% for 5 minutes
- alert: HighErrorRate
  expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.01
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Error rate above 1% for 5 minutes"
```

### GOTCHAS

- **Logging sensitive data.** Passwords, tokens, credit card numbers in logs. These logs get stored in centralized logging systems, exported to third parties, and seen by many people. Sanitize.
- **Logging at the wrong level.** Everything at INFO means you can't find real issues. Everything at DEBUG means your log storage bill is $10,000/month.
- **High-cardinality labels.** Adding `user_id` as a Prometheus metric label creates a separate time series per user. With 100,000 users, that's 100,000 time series per metric. Prometheus falls over. Use logs for high-cardinality data, metrics for aggregates.
- **No correlation between logs and traces.** A log says "payment failed." Which request? Which user? Which trace? Always include request IDs in log entries.
- **Alerting on symptoms, not causes.** "CPU is high" is a symptom. "Request queue depth exceeds 1000" is closer to a cause. Alert on what tells you something actionable.

### HOW THIS CONNECTS

Monitoring tells you when something is wrong. But what happens when you need to deploy a fix or shut down a server? You need to do it without dropping in-flight requests — that's **graceful shutdown**.

---

## 21. Graceful Shutdown

### WHY

When you deploy new code, the old process must stop. If you `kill -9` it, every in-flight HTTP request gets dropped, every database transaction in progress gets rolled back (or worse, left hanging), every message being processed by a queue worker is lost. Graceful shutdown is the pattern of stopping *safely*: finish current work, refuse new work, clean up resources, then exit.

**Concrete failure:** A deployment kills a worker process mid-transaction. The database transaction was: (1) debit account A, (2) credit account B. Step 1 completed, step 2 didn't. The database rolls back the transaction, but the worker had already sent a "transfer complete" email after step 1. The user thinks their money was transferred, but it wasn't.

### WHAT

The graceful shutdown sequence:

```
1. Receive shutdown signal (SIGTERM)
2. Stop accepting new connections/tasks
3. Wait for in-flight requests to complete (with a timeout)
4. Close database connections, flush log buffers, etc.
5. Exit with code 0
```

Kubernetes sends SIGTERM, waits `terminationGracePeriodSeconds` (default 30s), then sends SIGKILL. Your app must finish its shutdown within that window.

### HOW

```go
// Go — graceful shutdown with signal handling
func main() {
    server := &http.Server{Addr: ":8080", Handler: router}

    // Start server in a goroutine
    go func() {
        if err := server.ListenAndServe(); err != http.ErrServerClosed {
            log.Fatalf("server error: %v", err)
        }
    }()

    // Wait for interrupt signal
    quit := make(chan os.Signal, 1)
    signal.Notify(quit, syscall.SIGTERM, syscall.SIGINT)
    <-quit

    log.Println("Shutting down server...")

    // Create a deadline context for the shutdown
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()

    // Gracefully shutdown: stops accepting new connections,
    // waits for existing ones to complete
    if err := server.Shutdown(ctx); err != nil {
        log.Fatalf("forced shutdown: %v", err)
    }

    // Close other resources
    dbPool.Close()
    redisClient.Close()

    log.Println("Server exited cleanly")
}
```

```javascript
// Node.js — graceful shutdown
const server = app.listen(8080);

function gracefulShutdown(signal) {
  console.log(`Received ${signal}. Starting graceful shutdown...`);

  // Stop accepting new connections
  server.close(() => {
    console.log('HTTP server closed');

    // Close DB connections
    dbPool.end()
      .then(() => {
        console.log('Database pool closed');
        process.exit(0);
      })
      .catch((err) => {
        console.error('Error closing DB pool:', err);
        process.exit(1);
      });
  });

  // Force exit if graceful shutdown takes too long
  setTimeout(() => {
    console.error('Forceful shutdown — timeout exceeded');
    process.exit(1);
  }, 25000); // slightly less than K8s terminationGracePeriodSeconds
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));
```

### GOTCHAS

- **Not handling SIGTERM.** Many apps only handle SIGINT (Ctrl+C). Kubernetes and most process managers send SIGTERM. Handle both.
- **Infinite graceful shutdown.** A long-running request (WebSocket, file upload) prevents the server from shutting down. Always set a timeout on the shutdown context.
- **Health check still passing during shutdown.** The load balancer keeps routing new requests to a dying server. Set a flag when shutdown starts and make the health check return 503 immediately.
- **Forgetting background workers.** The HTTP server shuts down gracefully, but the cron scheduler and queue workers are still running and get killed abruptly. Shutdown all components.
- **Connection pools not drained.** Database connections left open prevent the database from shutting down cleanly.

### HOW THIS CONNECTS

Graceful shutdown is about operational safety. But it's a small part of the broader topic of **security** — protecting your system from both accidental damage and intentional attacks.

---

## 22. Security

### WHY

Every backend system is a target. SQL injection, cross-site scripting, broken authentication, sensitive data exposure — these aren't theoretical. They're in the OWASP Top 10 because they're found in production applications every day. Security is not a feature you add later; it's a property of how you build every layer.

**Concrete failure:** An application concatenates user input into SQL queries. An attacker submits `'; DROP TABLE users; --` as a username. The query executes, deleting all user data. This is SQL injection — the #3 item on the OWASP Top 10 (Injection) — and it's still one of the most exploited vulnerabilities in 2024.

### WHAT — OWASP Top 10 (2021, still current) Mapped to Backend Engineering

| # | Vulnerability | Backend relevance |
|---|---------------|-------------------|
| A01 | Broken Access Control | Missing authorization checks (BOLA/IDOR) |
| A02 | Cryptographic Failures | Storing passwords in plaintext, weak hashing |
| A03 | Injection | SQL injection, NoSQL injection, command injection |
| A04 | Insecure Design | Missing rate limiting, no abuse detection |
| A05 | Security Misconfiguration | Debug mode in production, default credentials |
| A06 | Vulnerable Components | Unpatched dependencies with known CVEs |
| A07 | Authentication Failures | Weak passwords, no MFA, brute-forceable login |
| A08 | Data Integrity Failures | Insecure deserialization, untrusted CI/CD pipelines |
| A09 | Logging Failures | Not logging security events, logging sensitive data |
| A10 | SSRF | Server making requests to internal URLs based on user input |

### HOW

**Password hashing** (never store plaintext):

```python
import bcrypt

# Hashing a password (on registration)
password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12))
# Store password_hash in the database

# Verifying a password (on login)
if bcrypt.checkpw(submitted_password.encode('utf-8'), stored_hash):
    # Correct password
else:
    # Wrong password
```

Use bcrypt, scrypt, or Argon2id. Never MD5 or SHA-256 (too fast — GPUs can crack billions of hashes per second).

**SQL injection prevention:**

```python
# BAD — string concatenation
query = f"SELECT * FROM users WHERE email = '{email}'"  # SQL INJECTION!

# GOOD — parameterized query
cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
```

**Rate limiting:**

```python
# Simple sliding window with Redis
def check_rate_limit(user_id, limit=100, window=60):
    key = f"rate:{user_id}:{int(time.time()) // window}"
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, window)
    if count > limit:
        raise RateLimitExceeded()
```

**CORS (Cross-Origin Resource Sharing):**

```python
# Only allow requests from your frontend domain
CORS_CONFIG = {
    "origins": ["https://app.example.com"],        # NOT "*" in production
    "methods": ["GET", "POST", "PUT", "DELETE"],
    "allow_headers": ["Authorization", "Content-Type"],
    "max_age": 3600,
}
```

**Security headers:**

```
Content-Security-Policy: default-src 'self'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

**SSRF prevention:**

```python
# BAD — user controls the URL the server fetches
url = request.body['webhook_url']
response = requests.get(url)  # What if url = "http://169.254.169.254/latest/meta-data/"?
                               # That's the AWS metadata endpoint. Leaked credentials.

# GOOD — validate and restrict
from urllib.parse import urlparse
parsed = urlparse(url)
if parsed.hostname in BLOCKED_HOSTS or is_private_ip(parsed.hostname):
    raise SecurityError("URL not allowed")
```

### GOTCHAS

- **Security through obscurity.** "Nobody will guess our API endpoint." They will.
- **Using JWT without `exp` claim.** Tokens that never expire. If leaked, they grant permanent access.
- **CORS `*` with credentials.** `Access-Control-Allow-Origin: *` combined with `Access-Control-Allow-Credentials: true` is rejected by browsers, but the misconfiguration reveals a fundamental misunderstanding.
- **Not rate limiting authentication endpoints.** Login, password reset, and MFA verification endpoints are brute-force targets.
- **Dependencies with known vulnerabilities.** `npm audit` and `pip audit` exist for a reason. Run them in CI.

### HOW THIS CONNECTS

Security protects your system. But as your system grows, you need it to handle more load — more users, more data, more concurrent requests. That's **scaling & performance**.

---

## 23. Scaling & Performance

### WHY

Your app works with 100 users. What happens with 100,000? With 1,000,000? Scaling is about maintaining performance and reliability as load increases. Performance is about doing more work with the same resources. They're distinct but related: good performance delays the need to scale, and scaling without addressing performance just burns money faster.

**Concrete failure:** An e-commerce site runs a flash sale. Traffic spikes 50x. The single database server maxes out on connections. The application server runs out of memory. Response times climb from 100ms to 30 seconds. Users abandon carts. The site effectively goes down during the highest-revenue moment of the year.

### WHAT

**Vertical scaling (scale up):** Bigger server. More CPU, more RAM. Simple, no code changes. Limit: there's a biggest server you can buy.

**Horizontal scaling (scale out):** More servers. Application is stateless, so any server can handle any request. Load balancer distributes traffic. Limit: your application must be designed for it (stateless, no local file storage, shared sessions).

**The scaling checklist:**

| Layer | Strategy |
|-------|----------|
| Application | Horizontal scaling, stateless design, async processing |
| Database reads | Read replicas, caching (Redis), materialized views |
| Database writes | Sharding (split data across DBs), write-behind caching |
| Static assets | CDN |
| Compute-heavy work | Task queues, worker pools |
| Search | Elasticsearch cluster (sharding built-in) |
| Sessions | External session store (Redis), or JWTs |

### HOW

**Load balancing strategies:**

```
# Round Robin — simple, equal distribution
Server A → Server B → Server C → Server A → ...

# Least Connections — route to the server with fewest active requests
# Better when request processing times vary significantly

# Consistent Hashing — route based on a key (user ID, session ID)
# Same user always hits the same server (useful for local caches)
# But requires redistribution when servers are added/removed
```

**Database read replicas:**

```
                    ┌─→ Replica 1 (reads)
Writes → Primary ──┤
                    └─→ Replica 2 (reads)
```

```python
# Use a read replica for GET requests
def get_user(user_id):
    return read_replica.execute("SELECT * FROM users WHERE id = %s", user_id)

def update_user(user_id, data):
    primary.execute("UPDATE users SET name = %s WHERE id = %s", data['name'], user_id)
    # Caveat: replication lag means read replica might return stale data briefly
```

**Connection pooling with PgBouncer** (sits between your app and PostgreSQL):

```
App (100 instances × 20 connections = 2000 app connections)
    → PgBouncer (maintains 100 actual PostgreSQL connections)
    → PostgreSQL (maxes out at ~500 connections)
```

Without PgBouncer, 100 app instances would need 2,000 PostgreSQL connections, which would crush the database.

**Performance profiling before scaling:**

```python
# Don't guess — measure
# 1. Profile the hottest endpoint
cProfile.run('handle_request()')

# 2. Common findings:
#    - N+1 queries: 100 DB calls where 2 would suffice
#    - Missing index: full table scan on every request
#    - Synchronous I/O: blocking the event loop (Node) or thread (Python)
#    - Unnecessary serialization: converting to JSON and back multiple times
```

### GOTCHAS

- **Premature optimization.** Sharding your database when you have 1,000 users. Profile first, optimize the bottleneck, then scale.
- **Stateful application servers.** Storing session data, uploaded files, or cache in-memory on the app server. When you add a second server, half your users lose their sessions.
- **Ignoring database as the bottleneck.** You can scale your app servers to 100 instances, but if they all hit one database, you've just moved the bottleneck.
- **Read replica lag.** User updates their profile (hits primary), immediately refreshes (hits replica). They don't see their own update. Solution: read-your-writes consistency — route the user to the primary for a few seconds after a write.
- **Not load testing.** "It'll probably be fine" is not a scaling strategy. Use tools like k6, wrk, or Locust to simulate realistic load before a launch.

### HOW THIS CONNECTS

Scaling adds more machines. But each machine runs code that needs to handle multiple things at once — requests, background jobs, I/O waits. That's **concurrency & parallelism**.

---

## 24. Concurrency & Parallelism

### WHY

A backend server handles many requests simultaneously. It waits for databases, external APIs, and file systems — all I/O operations that take milliseconds to seconds. If the server handles one request at a time, waiting for I/O, it wastes most of its time doing nothing. Concurrency lets the server make progress on multiple requests during those waits.

**Concrete failure:** A Python Flask app runs with a single worker. One request triggers a 5-second external API call. During those 5 seconds, the server can't handle any other requests. A queue forms. Users experience 30-second response times.

### WHAT

**Concurrency ≠ Parallelism.**

- **Concurrency:** Structuring your program to handle multiple tasks that make progress by interleaving. One CPU core, switching between tasks. Good for I/O-bound work.
- **Parallelism:** Actually running multiple tasks simultaneously on multiple CPU cores. Good for CPU-bound work.

**How different ecosystems handle this:**

| Runtime | Concurrency model | Notes |
|---------|-------------------|-------|
| **Node.js** | Single-threaded event loop + async I/O | One thread handles all requests. I/O doesn't block. CPU-intensive work blocks the entire server. Use Worker Threads for CPU work. |
| **Go** | Goroutines (lightweight green threads) + channels | Thousands of goroutines on a few OS threads. Runtime handles scheduling. Both I/O and CPU scale well. |
| **Python** | GIL limits true parallelism. Async (asyncio) for I/O concurrency. `multiprocessing` for CPU parallelism. | The GIL means only one thread executes Python bytecode at a time. Use gunicorn with multiple workers for parallelism. |
| **Java** | OS threads + virtual threads (Project Loom) | Traditional: one thread per request (memory-heavy). Loom: lightweight virtual threads similar to goroutines. |
| **Rust** | async/await (Tokio runtime) + OS threads | Zero-cost abstractions. Explicit control. Best performance but most complex. |

### HOW

```javascript
// Node.js — event loop (concurrent I/O, single-threaded)
// These three database calls run concurrently:
async function getDashboard(userId) {
  const [user, orders, notifications] = await Promise.all([
    db.query('SELECT * FROM users WHERE id = $1', [userId]),
    db.query('SELECT * FROM orders WHERE user_id = $1', [userId]),
    db.query('SELECT * FROM notifications WHERE user_id = $1', [userId]),
  ]);
  // All three queries were in-flight simultaneously
  // Total time ≈ max(query1, query2, query3), not sum
  return { user, orders, notifications };
}
```

```go
// Go — goroutines for concurrent work
func getDashboard(ctx context.Context, userID int) (*Dashboard, error) {
    g, ctx := errgroup.WithContext(ctx)

    var user *User
    var orders []*Order
    var notifs []*Notification

    g.Go(func() error {
        var err error
        user, err = userRepo.Get(ctx, userID)
        return err
    })
    g.Go(func() error {
        var err error
        orders, err = orderRepo.ListByUser(ctx, userID)
        return err
    })
    g.Go(func() error {
        var err error
        notifs, err = notifRepo.ListByUser(ctx, userID)
        return err
    })

    if err := g.Wait(); err != nil {
        return nil, err
    }

    return &Dashboard{User: user, Orders: orders, Notifications: notifs}, nil
}
```

**Race conditions** — the fundamental concurrency bug:

```python
# RACE CONDITION: check-then-act
def withdraw(account_id, amount):
    balance = db.query("SELECT balance FROM accounts WHERE id = %s", account_id)
    if balance >= amount:
        # Another request could have withdrawn between the check and the update!
        db.execute("UPDATE accounts SET balance = balance - %s WHERE id = %s", amount, account_id)

# FIX: atomic operation
def withdraw(account_id, amount):
    result = db.execute(
        "UPDATE accounts SET balance = balance - %s WHERE id = %s AND balance >= %s RETURNING balance",
        amount, account_id, amount
    )
    if not result:
        raise InsufficientFunds()
```

### GOTCHAS

- **CPU-bound work on the Node.js event loop.** A single request that does heavy computation (image processing, crypto) blocks all other requests. Use Worker Threads or offload to a task queue.
- **Python's GIL trap.** Adding threads to a CPU-bound Python workload doesn't help — the GIL serializes them. Use `multiprocessing` or write the hot path in C/Rust.
- **Shared mutable state.** Two goroutines/threads modifying the same map without a mutex. Data corruption, panics, or silently wrong results. Go's race detector (`go run -race`) catches these.
- **Deadlocks.** Thread A locks resource 1, waits for resource 2. Thread B locks resource 2, waits for resource 1. Both wait forever. Solution: always acquire locks in a consistent order.
- **Goroutine/thread leaks.** Spawning goroutines that never terminate (waiting for a channel that never receives). They accumulate, consuming memory.

### HOW THIS CONNECTS

Concurrent access patterns are especially important for one type of resource: large files. Images, videos, PDFs — these require different handling than typical JSON request/response flows. That's **object storage & large files**.

---

## 25. Object Storage & Large Files

### WHY

Your database stores structured data: names, emails, timestamps. It's terrible at storing binary blobs — a 100 MB video in a PostgreSQL `bytea` column is slow to store, slow to retrieve, bloats your backup size, and can't be served directly by a CDN. Object storage (S3, GCS, Azure Blob Storage) is purpose-built for this: durable, scalable, cheap storage for files of any size, accessible via HTTP.

**Concrete failure:** An app stores user-uploaded profile pictures in the database as base64-encoded strings. Each image averages 5 MB. With 100,000 users, the database is 500 GB of images. Backups take 6 hours. The `SELECT * FROM users` query that ran fine with 1,000 users now times out because it's loading megabytes of image data per row.

### WHAT

**Object storage model:**
- **Bucket:** A namespace for objects (like a top-level directory).
- **Object:** A file, identified by a key (path-like string: `uploads/users/42/avatar.jpg`).
- **Metadata:** Key-value pairs attached to the object (content type, cache control, custom headers).

**The upload flow** (never receive the file on your API server if you can avoid it):

```
Client → Presigned URL request → Your API (generates presigned URL)
Client → Direct upload → Object Storage (S3)
Client → Confirm upload → Your API (saves metadata to DB)
```

### HOW

**Presigned URL upload (S3 example):**

```python
import boto3

s3 = boto3.client('s3')

def generate_upload_url(user_id: int, filename: str) -> dict:
    key = f"uploads/users/{user_id}/{uuid4()}/{filename}"

    presigned_url = s3.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': 'my-app-uploads',
            'Key': key,
            'ContentType': 'image/jpeg',  # restrict content type
        },
        ExpiresIn=300,  # URL valid for 5 minutes
    )

    return {
        "upload_url": presigned_url,
        "key": key,
    }

# Handler
def upload_avatar_handler(request):
    url_info = generate_upload_url(request.user.id, request.body['filename'])
    return Response(status=200, body=url_info)
    # Client uses upload_url to PUT the file directly to S3

# After upload, client confirms:
def confirm_avatar_handler(request):
    key = request.body['key']
    # Verify the object actually exists in S3
    s3.head_object(Bucket='my-app-uploads', Key=key)
    # Save the reference (not the file) in the database
    db.execute("UPDATE users SET avatar_key = %s WHERE id = %s", key, request.user.id)
    return Response(status=200)
```

**Serving files via CDN:**

```
# In your database: avatar_key = "uploads/users/42/abc123/avatar.jpg"
# Public URL: https://cdn.example.com/uploads/users/42/abc123/avatar.jpg
# CDN is configured to pull from S3 on cache miss
```

**Streaming large file downloads:**

```python
# Streaming from S3 through your server (when you need auth before serving)
def download_file(request, file_key):
    s3_response = s3.get_object(Bucket='my-bucket', Key=file_key)

    return StreamingResponse(
        s3_response['Body'].iter_chunks(chunk_size=8192),
        media_type=s3_response['ContentType'],
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
```

### GOTCHAS

- **Receiving uploads through your API server.** Your server becomes a bottleneck and uses memory proportional to file size. Use presigned URLs for client-to-S3 direct upload.
- **Not validating file types.** Users upload executable files disguised as images. Validate content type by reading file headers (magic bytes), not by trusting the file extension.
- **Public buckets.** S3 buckets with public access. Your users' private documents are indexed by Google. Always use private buckets with presigned URLs or CDN with authentication.
- **No lifecycle policies.** Temporary upload files accumulate forever. Set S3 lifecycle rules to delete objects in `uploads/temp/` after 24 hours.
- **Presigned URLs without expiration.** If someone leaks the URL, anyone can upload to your bucket indefinitely. Keep expiration short (5-15 minutes).

### HOW THIS CONNECTS

File uploads are a request-response pattern — the client sends a file, the server acknowledges. But some use cases need continuous, bidirectional communication: chat, live feeds, collaborative editing. That's **real-time backend systems**.

---

## 26. Real-Time Backend Systems (WebSockets/SSE)

### WHY

HTTP is request-response: the client asks, the server answers. But what if the server needs to push data to the client without being asked? A chat message from another user, a live stock price update, a notification that a background job finished. Polling (client repeatedly asking "anything new?") wastes bandwidth and adds latency. Real-time protocols solve this with persistent connections.

**Concrete failure:** A chat application uses HTTP polling — the client sends `GET /messages` every second. With 10,000 users, that's 10,000 requests/second, most returning empty responses. Server costs skyrocket. Battery drain kills the mobile app's ratings. And messages still arrive with up to 1 second of latency.

### WHAT

**Three approaches:**

| Approach | Direction | Protocol | Complexity | Use case |
|----------|-----------|----------|------------|----------|
| **Long Polling** | Server → Client | HTTP | Low | Legacy compat, simple notifications |
| **SSE** (Server-Sent Events) | Server → Client | HTTP | Medium | Live feeds, dashboards, notifications |
| **WebSocket** | Bidirectional | WS (starts as HTTP upgrade) | High | Chat, multiplayer games, collaboration |

**SSE** is HTTP-based, uses the `text/event-stream` content type, automatically reconnects on disconnect, and works through most proxies. It's unidirectional (server → client only). For most "push updates to the client" use cases, SSE is simpler and sufficient.

**WebSocket** is a full-duplex protocol that starts as an HTTP upgrade handshake, then switches to a persistent TCP connection with its own framing. Both sides can send messages at any time.

### HOW

**SSE (Server-Sent Events):**

```python
# Python (FastAPI/Starlette)
from starlette.responses import StreamingResponse

async def event_stream(user_id: int):
    async for event in subscribe_to_user_events(user_id):
        yield f"event: {event.type}\ndata: {json.dumps(event.data)}\n\n"

@app.get("/api/events")
async def sse_endpoint(request: Request):
    return StreamingResponse(
        event_stream(request.user.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

```javascript
// Client-side SSE (browser)
const events = new EventSource('/api/events');
events.addEventListener('new_message', (e) => {
  const message = JSON.parse(e.data);
  appendToChat(message);
});
events.onerror = () => {
  // EventSource automatically reconnects
  console.log('Connection lost, reconnecting...');
};
```

**WebSocket:**

```javascript
// Node.js server with 'ws' library
const WebSocket = require('ws');
const wss = new WebSocket.Server({ server: httpServer });

// Track connected clients
const clients = new Map(); // userId → Set<WebSocket>

wss.on('connection', (ws, req) => {
  const userId = authenticateWebSocket(req); // auth from query param or cookie

  if (!clients.has(userId)) clients.set(userId, new Set());
  clients.get(userId).add(ws);

  ws.on('message', (data) => {
    const msg = JSON.parse(data);
    handleMessage(userId, msg);
  });

  ws.on('close', () => {
    clients.get(userId)?.delete(ws);
  });

  // Heartbeat to detect dead connections
  ws.isAlive = true;
  ws.on('pong', () => { ws.isAlive = true; });
});

// Ping all clients every 30 seconds
setInterval(() => {
  wss.clients.forEach((ws) => {
    if (!ws.isAlive) return ws.terminate();
    ws.isAlive = false;
    ws.ping();
  });
}, 30000);

// Send a message to a specific user
function sendToUser(userId, event) {
  clients.get(userId)?.forEach((ws) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(event));
    }
  });
}
```

**Scaling WebSockets across multiple servers:**

The problem: User A is connected to Server 1. User B is connected to Server 2. User A sends a message to User B. Server 1 doesn't have User B's connection.

Solution: **Pub/Sub backbone** (Redis Pub/Sub, Kafka, or NATS):

```
Server 1 (User A) → publishes message to Redis channel
                     Redis → broadcasts to all servers
Server 2 (User B) ← receives and delivers to User B's WebSocket
```

### GOTCHAS

- **Not implementing heartbeats.** Clients silently disconnect (mobile goes to sleep, network change). Without heartbeats (ping/pong), dead connections accumulate, consuming server resources.
- **Authentication on WebSocket.** WebSocket doesn't support custom headers in the browser. Options: pass a token as a query parameter (`ws://host?token=...`), use cookies, or authenticate in the first message.
- **Memory leaks from connection tracking.** Adding connections to a Map/Set on connect but not removing on disconnect. Eventually the server runs out of memory.
- **Forgetting about reconnection.** Clients will disconnect. SSE has built-in reconnection. WebSocket does not — the client must implement it (with exponential backoff).
- **Sending too much data.** Broadcasting every database change to all connected clients. Use subscriptions or rooms to scope what each client receives.

### HOW THIS CONNECTS

Real-time systems, like everything else, need to be reliable. Reliability comes from discipline — **testing & code quality** — which ensures your system works correctly now and continues to work correctly as you change it.

---

## 27. Testing & Code Quality

### WHY

Without tests, you have two options: (1) manually test every feature before every release (which doesn't scale), or (2) deploy and pray (which fails spectacularly). Testing is automated verification that your system does what it should. Code quality practices (linting, formatting, code review) prevent bugs from being introduced in the first place.

**Concrete failure:** A developer changes the format of a date field in an API response from `"2024-01-15"` to `"01/15/2024"`. No tests cover this. The mobile app expects ISO 8601 format, fails to parse the new format, and crashes for all users.

### WHAT

**The testing pyramid:**

```
          ╱╲
         ╱  ╲       E2E Tests (few, slow, expensive)
        ╱────╲      Verify the full system end-to-end
       ╱      ╲
      ╱────────╲    Integration Tests (some, medium)
     ╱          ╲   Test components together (API + DB)
    ╱────────────╲
   ╱              ╲  Unit Tests (many, fast, cheap)
  ╱────────────────╲ Test individual functions in isolation
```

| Type | Tests | Speed | Scope | Mocking |
|------|-------|-------|-------|---------|
| Unit | A single function/class | Milliseconds | Internal logic, no I/O | Dependencies mocked |
| Integration | API + database, service + cache | Seconds | Cross-component interaction | External services mocked, real DB |
| E2E | Full HTTP request through the stack | Seconds-minutes | Entire system | Nothing mocked |

### HOW

**Unit test (service layer):**

```python
# test_order_service.py
def test_place_order_insufficient_stock():
    # Arrange
    mock_inventory = Mock()
    mock_inventory.check_availability.return_value = False

    service = OrderService(
        order_repo=Mock(),
        inventory_service=mock_inventory,
        payment_service=Mock(),
    )

    # Act & Assert
    with pytest.raises(OutOfStockError):
        service.place_order(user=mock_user, cart_items=[CartItem(product_id=1, quantity=5)])

    # Verify payment was never attempted
    service.payment_service.charge.assert_not_called()
```

**Integration test (API + real database):**

```python
# test_users_api.py
@pytest.fixture
def db():
    """Create a test database, run migrations, yield connection, tear down."""
    conn = create_test_database()
    run_migrations(conn)
    yield conn
    drop_test_database(conn)

def test_create_user(client, db):
    response = client.post("/api/users", json={
        "name": "Alice",
        "email": "alice@example.com"
    })

    assert response.status_code == 201
    assert response.json()["data"]["email"] == "alice@example.com"

    # Verify it's actually in the database
    user = db.execute("SELECT * FROM users WHERE email = 'alice@example.com'")
    assert user is not None

def test_create_user_duplicate_email(client, db):
    # Create first user
    client.post("/api/users", json={"name": "Alice", "email": "alice@example.com"})

    # Attempt duplicate
    response = client.post("/api/users", json={"name": "Bob", "email": "alice@example.com"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_EMAIL"
```

```go
// Go — table-driven tests
func TestParseAge(t *testing.T) {
    tests := []struct {
        name    string
        input   int
        wantErr bool
    }{
        {"valid age", 25, false},
        {"minimum age", 13, false},
        {"below minimum", 12, true},
        {"negative age", -1, true},
        {"above maximum", 151, true},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            _, err := parseAge(tt.input)
            if (err != nil) != tt.wantErr {
                t.Errorf("parseAge(%d) error = %v, wantErr %v", tt.input, err, tt.wantErr)
            }
        })
    }
}
```

**Code quality tools:**

| Concern | Tools |
|---------|-------|
| Linting | ESLint, pylint/ruff, golangci-lint |
| Formatting | Prettier, black, gofmt |
| Type checking | TypeScript, mypy, Go compiler |
| Security scanning | Snyk, npm audit, pip audit, gosec |
| Dead code | unused exports (TS), vulture (Python) |

### GOTCHAS

- **Testing implementation, not behavior.** Testing that a function calls `db.query()` exactly once with exactly these arguments is brittle. Test the outcome: "when I create a user, querying by email returns that user."
- **No tests for error paths.** The happy path is tested, but what happens when the DB is down? When the input is malformed? When the user doesn't exist? Error paths are where most production bugs hide.
- **Flaky tests.** Tests that pass/fail randomly. Usually caused by: time-dependent logic, shared state between tests, uncontrolled ordering, or external service dependencies.
- **Slow test suites.** If tests take 30 minutes, developers stop running them locally and push directly to CI, slowing everyone down.
- **100% code coverage as a goal.** Coverage tells you what code was *executed*, not what was *verified*. A test that runs a function without assertions has coverage but no value. Aim for meaningful coverage of business-critical paths.

### HOW THIS CONNECTS

Testing ensures correctness. But running your application correctly across environments (development, staging, production) requires a methodology for structuring the app itself. That's the **12-Factor App methodology**.

---

## 28. 12-Factor App Methodology

### WHY

You've built an app that works on your laptop. Now deploy it to staging. Then production. Then scale to 10 instances. Then add a CI/CD pipeline. At each step, things break because the app wasn't designed for operational flexibility. The 12-Factor methodology (from the Heroku team, codified at 12factor.net) is a set of principles for building apps that deploy cleanly, scale easily, and run reliably in modern cloud environments.

### WHAT — All 12 Factors

**I. Codebase** — One codebase tracked in version control, many deploys.
One repo = one app. Multiple environments (staging, prod) deploy from the same codebase at different commits. If you have shared code between apps, it goes in a library, not a shared repo.

**II. Dependencies** — Explicitly declare and isolate dependencies.
Use `package.json`, `go.mod`, `requirements.txt`, `Cargo.toml`. Never rely on system-level packages being pre-installed. Vendoring or lock files ensure reproducibility.

**III. Config** — Store config in the environment.
Anything that varies between deploys (database URLs, API keys, feature flags) is config. It goes in environment variables, not in code. Covered in detail in Topic 19.

**IV. Backing Services** — Treat backing services as attached resources.
A database, a message queue, an SMTP server — your app accesses them via a URL from config. Swapping your local PostgreSQL for an RDS instance should require only changing a URL, not code.

**V. Build, Release, Run** — Strictly separate build and run stages.
- **Build:** Compile, bundle, install dependencies → immutable build artifact.
- **Release:** Combine build artifact + config → immutable release.
- **Run:** Execute the release.

You never modify a release in production. To change anything, create a new release.

**VI. Processes** — Execute the app as one or more stateless processes.
Processes are stateless and share-nothing. Any persistent state goes in a backing service (database, Redis). This enables horizontal scaling — add more processes, they're all identical.

**VII. Port Binding** — Export services via port binding.
Your app is a self-contained process that listens on a port. It doesn't require injection into a web server container (like deploying a WAR to Tomcat). The HTTP server is embedded.

**VIII. Concurrency** — Scale out via the process model.
Different types of work run as different process types: `web` for HTTP, `worker` for background jobs, `clock` for scheduled tasks. Scale by adding more processes of the type that's bottlenecked.

**IX. Disposability** — Maximize robustness with fast startup and graceful shutdown.
Processes start quickly and stop gracefully (Topic 21). This enables rapid deploys, elastic scaling, and fault recovery.

**X. Dev/Prod Parity** — Keep development, staging, and production as similar as possible.
Same backing services (don't use SQLite in dev and PostgreSQL in prod), same OS (Docker helps), similar data volumes.

**XI. Logs** — Treat logs as event streams.
Don't write to log files. Write to stdout. Let the execution environment (Docker, Kubernetes, Heroku) capture, route, and store logs. Your app shouldn't know or care about log storage.

**XII. Admin Processes** — Run admin/management tasks as one-off processes.
Database migrations, one-time data fixes, console REPL sessions — run them as separate processes using the same codebase and config as the running app.

### HOW

Most of these factors are enforced through discipline and tooling, not code patterns. Docker naturally enforces several factors:

```dockerfile
# Dockerfile — enforces factors I, II, V, VII, XI
FROM node:20-slim

# II. Dependencies explicitly declared
COPY package.json package-lock.json ./
RUN npm ci --production

# V. Build stage
COPY . .
RUN npm run build

# VII. Port binding
EXPOSE 8080

# XI. Logs to stdout (default behavior of console.log)
# IX. Fast startup
CMD ["node", "dist/server.js"]
```

```yaml
# docker-compose.yml — enforces IV, VIII
services:
  web:                          # VIII. Separate process type
    build: .
    ports: ["8080:8080"]
    environment:                # III. Config in environment
      - DATABASE_URL=postgres://dev:dev@db:5432/app
      - REDIS_URL=redis://redis:6379

  worker:                       # VIII. Separate process type
    build: .
    command: ["node", "dist/worker.js"]
    environment:
      - DATABASE_URL=postgres://dev:dev@db:5432/app
      - REDIS_URL=redis://redis:6379

  db:                           # IV. Backing service
    image: postgres:16

  redis:                        # IV. Backing service
    image: redis:7
```

### GOTCHAS

- **Config in code.** Hardcoded connection strings, API keys in constants files. Violates Factor III and is a security risk.
- **Local file storage.** Writing uploaded files to the local filesystem. Violates Factor VI — when you scale to multiple processes, only one has the file.
- **Custom log file management.** Log rotation, log file paths in the app. Violates Factor XI. Write to stdout.
- **"Snowflake" servers.** SSH into a server, install dependencies, tweak config. Nothing is reproducible. Violates Factors I, II, V, X.

### HOW THIS CONNECTS

The 12-Factor methodology gives you the structural discipline for building deployable apps. But how do other teams (or your future self) know what your API looks like? That's where **OpenAPI standards** come in — a machine-readable description of your API.

---

## 29. OpenAPI Standards

### WHY

Your API is a contract. Other teams, partners, and frontend developers consume it. Without a formal specification, the "documentation" is a Slack thread, a stale wiki page, or reverse-engineering the code. OpenAPI (formerly Swagger) provides a standard, machine-readable format for describing REST APIs. From a single spec, you can auto-generate documentation, client SDKs, mock servers, and validation middleware.

**Concrete failure:** A frontend developer builds against the API based on a meeting conversation. The backend developer adds a required field to a request schema. No spec was updated because there was no spec. The frontend breaks in production because it doesn't send the new required field.

### WHAT

The OpenAPI Specification (OAS) is a YAML or JSON document that describes your API's endpoints, request/response schemas, authentication methods, and more. Current version: OpenAPI 3.1 (aligned with JSON Schema).

### HOW

```yaml
# openapi.yaml (abbreviated)
openapi: 3.1.0
info:
  title: My App API
  version: 1.0.0
  description: Backend API for My App

servers:
  - url: https://api.example.com/v1

paths:
  /users:
    post:
      summary: Create a new user
      operationId: createUser
      tags: [Users]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateUserRequest'
      responses:
        '201':
          description: User created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UserResponse'
          headers:
            Location:
              schema:
                type: string
              description: URL of the created user
        '409':
          description: Email already exists
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
        '422':
          description: Validation error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'

components:
  schemas:
    CreateUserRequest:
      type: object
      required: [name, email]
      properties:
        name:
          type: string
          minLength: 1
          maxLength: 100
        email:
          type: string
          format: email
    UserResponse:
      type: object
      properties:
        data:
          type: object
          properties:
            id:
              type: integer
            name:
              type: string
            email:
              type: string
              format: email
    ErrorResponse:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
            message:
              type: string

  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT

security:
  - bearerAuth: []
```

**Two approaches to OpenAPI:**

1. **Spec-first (design-first):** Write the OpenAPI spec, then generate server stubs and client SDKs. Forces you to think about the API contract before writing code. Good for APIs consumed by many teams.

2. **Code-first:** Write the code with annotations/decorators, generate the spec from code. Less upfront effort, spec always matches implementation. Good for internal APIs or when iterating quickly.

```python
# Code-first example with FastAPI (generates OpenAPI automatically)
from fastapi import FastAPI
from pydantic import BaseModel, EmailStr

app = FastAPI(title="My App API", version="1.0.0")

class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr

class UserResponse(BaseModel):
    id: int
    name: str
    email: str

@app.post("/users", response_model=UserResponse, status_code=201)
def create_user(request: CreateUserRequest):
    ...
    # FastAPI auto-generates OpenAPI spec from type hints
    # Access it at GET /openapi.json or the Swagger UI at GET /docs
```

### GOTCHAS

- **Spec-code drift.** The spec says one thing, the code does another. If you go spec-first, validate your implementation against the spec in CI (tools: Prism, schemathesis, committee). If you go code-first, the spec is generated from code — no drift possible.
- **Overly permissive schemas.** Not defining required fields, not setting string lengths, not using enums. Consumers guess at constraints and send garbage.
- **Not versioning the spec.** The spec is a contract. Changing it without versioning breaks consumers.

### HOW THIS CONNECTS

OpenAPI describes your API for human and machine consumers who call *your* endpoints. But sometimes *you* need to call *their* endpoints — in response to events in your system. That's **webhooks**.

---

## 30. Webhooks

### WHY

You integrate with Stripe for payments. When a customer's payment succeeds, you need to fulfill their order. Polling Stripe's API every second asking "any new payments?" is wasteful and adds latency. Webhooks invert this: Stripe calls *your* endpoint when something happens. It's the event-driven equivalent of a push notification for APIs.

**Concrete failure:** A webhook endpoint doesn't verify the signature on incoming requests. An attacker discovers the URL, sends a fake "payment succeeded" webhook, and gets free products.

### WHAT

A webhook is an HTTP callback: when an event occurs in system A, it sends an HTTP POST to a URL registered by system B.

```
Stripe: "payment succeeded" → POST https://your-api.com/webhooks/stripe → Your handler: fulfill order
```

**You as a webhook consumer** (receiving webhooks from external services):

```
External Service → POST /webhooks/provider → Your verification → Your handler
```

**You as a webhook producer** (sending webhooks to your customers):

```
Event in your system → Queue → Webhook delivery service → POST to customer's URL
```

### HOW

**Consuming webhooks (e.g., Stripe):**

```python
import hmac
import hashlib

@app.post("/webhooks/stripe")
def handle_stripe_webhook(request):
    # 1. Verify the signature (CRITICAL — without this, anyone can send fake events)
    payload = request.body
    sig_header = request.headers.get('Stripe-Signature')
    try:
        event = verify_stripe_signature(payload, sig_header, WEBHOOK_SECRET)
    except InvalidSignatureError:
        return Response(status=400)

    # 2. Handle idempotently (Stripe may send the same event multiple times)
    if already_processed(event['id']):
        return Response(status=200)  # Acknowledge without reprocessing

    # 3. Process the event
    match event['type']:
        case 'payment_intent.succeeded':
            fulfill_order(event['data']['object'])
        case 'customer.subscription.deleted':
            cancel_subscription(event['data']['object'])
        case _:
            logger.info(f"Unhandled event type: {event['type']}")

    # 4. Mark as processed
    mark_processed(event['id'])

    # 5. Always return 2xx quickly — process heavy work async
    return Response(status=200)
```

**Producing webhooks (sending to your customers):**

```python
# Webhook delivery with retry and signature
def deliver_webhook(endpoint_url, event_type, payload, secret):
    body = json.dumps(payload)
    timestamp = int(time.time())
    signature = hmac.new(
        secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-Webhook-Signature': f"t={timestamp},v1={signature}",
        'X-Webhook-Event': event_type,
    }

    for attempt in range(5):
        try:
            response = requests.post(endpoint_url, data=body, headers=headers, timeout=10)
            if 200 <= response.status_code < 300:
                return  # Success
            if response.status_code >= 500:
                raise RetryableError()  # Server error, retry
            # 4xx = don't retry (client error)
            log_delivery_failure(endpoint_url, event_type, response.status_code)
            return
        except (Timeout, ConnectionError):
            delay = (2 ** attempt) + random.uniform(0, 1)  # exponential backoff + jitter
            time.sleep(delay)

    # All retries exhausted
    disable_webhook_endpoint(endpoint_url)
    notify_customer("Your webhook endpoint is unreachable")
```

### GOTCHAS

- **Not verifying signatures.** Without signature verification, anyone who discovers your webhook URL can send fake events. Always verify using the secret provided by the webhook source.
- **Synchronous processing.** If your webhook handler takes 30 seconds to process, the sender times out and retries. You get duplicate events. Return 200 immediately, process async.
- **Not handling duplicates.** Webhook providers send the same event multiple times (at-least-once delivery). Your handler must be idempotent. Use the event ID as a deduplication key.
- **Webhook URL discovery.** Don't put webhook endpoints at predictable URLs without signature verification. `/webhooks/stripe` is guessable.
- **No retry logic when producing.** Your customer's server is down for 5 minutes. If you only try once, they miss the event. Implement exponential backoff with a maximum number of retries and a dead-letter mechanism.

### HOW THIS CONNECTS

Webhooks are one part of how your application interacts with the outside world in production. Keeping the entire production system running — building, deploying, monitoring, scaling — is the domain of **DevOps for backend engineers**.

---

## 31. DevOps for Backend Engineers

### WHY

You've built a backend that handles HTTP, authenticates users, validates input, runs business logic, talks to databases, sends emails, and processes background jobs. Now it needs to actually run. DevOps is the set of practices and tools that bridge development and operations: getting your code from your laptop to production reliably, repeatedly, and safely.

**Concrete failure:** A developer deploys by SSHing into the production server, running `git pull`, and restarting the service. They accidentally run this on the wrong server. The wrong version of the code goes live. There's no rollback mechanism. Customers are affected for hours.

### WHAT

**Core DevOps concepts for backend engineers:**

| Concept | What | Why |
|---------|------|-----|
| **CI/CD** | Automated build, test, deploy pipeline | Every code change is automatically tested and deployed |
| **Containerization** | Docker packages app + dependencies into an image | "Works on my machine" → works everywhere |
| **Orchestration** | Kubernetes/ECS/Nomad manages containers | Auto-scaling, health checks, rolling deploys |
| **Infrastructure as Code** | Terraform/Pulumi defines infrastructure in config files | Reproducible, version-controlled infrastructure |
| **Environments** | Dev → Staging → Production | Test in production-like environments before users see it |

### HOW

**Docker basics:**

```dockerfile
# Multi-stage build — keep the final image small
FROM node:20-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
# Copy only what's needed to run
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

# Non-root user (security)
USER node
EXPOSE 8080
CMD ["node", "dist/server.js"]
```

**CI/CD pipeline (GitHub Actions example):**

```yaml
# .github/workflows/deploy.yml
name: CI/CD Pipeline

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: test
        ports: ['5432:5432']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm ci
      - run: npm run lint
      - run: npm run type-check
      - run: npm run test
        env:
          DATABASE_URL: postgres://postgres:test@localhost:5432/test

  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build and push Docker image
        run: |
          docker build -t my-app:${{ github.sha }} .
          docker push registry.example.com/my-app:${{ github.sha }}
      - name: Deploy to Kubernetes
        run: |
          kubectl set image deployment/my-app my-app=registry.example.com/my-app:${{ github.sha }}
          kubectl rollout status deployment/my-app --timeout=5m
```

**Kubernetes deployment basics:**

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  template:
    spec:
      containers:
        - name: my-app
          image: registry.example.com/my-app:latest
          ports:
            - containerPort: 8080
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: app-secrets
                  key: database-url
          # Health checks (Kubernetes restarts unhealthy pods)
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

**Health check endpoints:**

```python
@app.get("/health/live")
def liveness():
    # "Is the process alive and not deadlocked?"
    return {"status": "ok"}

@app.get("/health/ready")
def readiness():
    # "Can this instance serve traffic?"
    try:
        db.execute("SELECT 1")
        redis.ping()
        return {"status": "ready"}
    except Exception:
        return Response(status=503, body={"status": "not ready"})
```

**Deployment strategies:**

| Strategy | How it works | Risk |
|----------|-------------|------|
| **Rolling update** | Replace instances one by one | Low — gradual rollout |
| **Blue/green** | Run two identical environments, switch traffic | Zero downtime, instant rollback, double cost |
| **Canary** | Route 5% of traffic to new version, then gradually increase | Lowest risk, needs observability |
| **Recreate** | Kill all old, start all new | Downtime — only for non-critical services |

### GOTCHAS

- **No rollback plan.** The deploy breaks production. How do you go back? If you don't have an answer before you deploy, you're not ready to deploy.
- **Running as root in containers.** A container escape vulnerability + running as root = attacker has root on the host. Always use a non-root user.
- **No resource limits.** A memory leak crashes the entire node (VM) because Kubernetes didn't know to limit the container. Set `resources.limits`.
- **Secrets in Docker images.** Building with `COPY .env .` bakes secrets into the image layer. Anyone with image access can extract them.
- **No staging environment.** Deploying directly to production. "Testing in production" is a strategy, but not your only strategy.

### HOW THIS CONNECTS

DevOps is the final piece that makes everything operational. It connects back to every previous topic: CI/CD runs your tests (27), deploys your containerized 12-Factor app (28), provisions your databases (12) and caches (14), configures your monitoring (20), and ensures graceful shutdown (21) during deployments.

---

## 32. How It All Fits Together

Let's trace a single request through the entire system. A user places an order in an e-commerce app. This walkthrough references topics by number so you can jump back to any section.

```
CLIENT → POST /api/v1/orders
         Authorization: Bearer eyJhbG...
         Content-Type: application/json
         X-Request-Id: req_abc123
         Body: { "items": [{ "product_id": 42, "quantity": 2 }] }
```

### Step 1: HTTP Arrival (Topic 2)

The request arrives over HTTP/2 at a load balancer (Topic 23), which selects a backend instance using least-connections routing. The request hits the application server, which parses the HTTP message — method (`POST`), path (`/api/v1/orders`), headers, and body.

### Step 2: Routing (Topic 3)

The router matches `POST /api/v1/orders` to the order creation handler. The route was registered as part of the `orders` route group with prefix `/api/v1/orders`.

### Step 3: Middleware Chain (Topic 7)

The request passes through the middleware stack in order:

1. **Request ID middleware** — reads `X-Request-Id` from the header (or generates one) and stores it in the **request context** (Topic 8).
2. **Logging middleware** (Topic 20) — logs `{"event":"request_started","method":"POST","path":"/api/v1/orders","request_id":"req_abc123"}`.
3. **Metrics middleware** (Topic 20) — starts a timer.
4. **CORS middleware** (Topic 22) — checks the `Origin` header against allowed origins.
5. **Body parser** (Topic 4) — **deserializes** the JSON body into a language-native object.
6. **Authentication middleware** (Topic 5) — extracts the JWT from the `Authorization` header, verifies the signature and expiry, extracts `user_id: 42` from the `sub` claim, stores the user in request context.
7. **Rate limiter** (Topic 22) — checks if user 42 has exceeded their request quota.

### Step 4: Handler (Topic 9)

The handler (`createOrderHandler`) receives the request:

1. **Validation** (Topic 6) — validates the request body against the `CreateOrderSchema`. Checks: `items` is a non-empty array, each item has a valid `product_id` (integer) and `quantity` (positive integer). If validation fails, returns **422** with structured error details (Topic 18).
2. **Authorization** (Topic 5) — checks that the authenticated user has the `create:orders` permission (RBAC check).
3. **Delegates to service** — calls `orderService.placeOrder(user, validatedItems)`.

### Step 5: Service / BLL (Topics 9, 13)

The **business logic layer** orchestrates the order:

1. **Checks inventory** — queries the product catalog. The product data might come from **cache** (Topic 14) — a Redis cache-aside lookup for product 42. Cache hit: skip DB. Cache miss: query **database** (Topic 12), populate cache.
2. **Applies business rules** (Topic 13) — "premium users get free shipping on orders over $50." User 42 is premium. Order total: $79.98. Shipping: $0.
3. **Reserves inventory** — decrements stock in a **database transaction** (Topic 12, ACID). Uses optimistic concurrency to prevent overselling (Topic 10).
4. **Processes payment** — calls the payment service (external API). Uses a timeout and **error handling** (Topic 18) with retry for transient failures.
5. **Saves the order** — INSERT into the `orders` table within the same transaction. The transaction **commits** atomically (Topic 12).
6. **Enqueues side effects** (Topic 16) — pushes an "order confirmation email" task onto the **task queue**. A background worker will pick this up and send the **transactional email** (Topic 15).
7. **Publishes event** — publishes `order.created` to the event bus for **Elasticsearch** (Topic 17) indexing (so the order appears in search) and for **webhook** delivery (Topic 30) to any subscribed integrations.

### Step 6: Response (Topics 4, 9)

The handler receives the created order from the service, **serializes** it into JSON (Topic 4), strips internal fields (no `password_hash`, no `internal_notes`), and returns:

```
HTTP/1.1 201 Created
Content-Type: application/json
Location: /api/v1/orders/99
X-Request-Id: req_abc123

{
  "data": {
    "id": 99,
    "status": "paid",
    "total_cents": 7998,
    "items": [{ "product_id": 42, "name": "Widget Pro", "quantity": 2, "price_cents": 3999 }],
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Step 7: Middleware (Return Path) (Topic 7)

The response passes back through the middleware stack (onion model):

1. **Metrics middleware** — records latency: `http_request_duration_seconds{method="POST",path="/api/v1/orders"} 0.045`.
2. **Logging middleware** — logs `{"event":"request_completed","status":201,"duration_ms":45,"request_id":"req_abc123"}`.

### Step 8: Async Side Effects (Topics 15, 16, 17, 30)

Meanwhile, outside the request lifecycle:

- A **queue worker** (Topic 16) picks up the email task and sends a confirmation email via SendGrid (Topic 15).
- A **search indexer** writes the order to **Elasticsearch** (Topic 17) so it appears in the admin's order search.
- A **webhook delivery worker** (Topic 30) sends `POST` requests to any subscribed webhook endpoints with the order data.

### The Operational Layer

Underneath all of this:

- **Config** (Topic 19) determined the database URL, JWT secret, Redis host, and rate limit thresholds.
- **Monitoring** (Topic 20) is tracking request rates, latency percentiles, error rates, and DB connection pool utilization. If the p99 latency exceeds 500ms, an alert fires.
- **Security** (Topic 22) is enforced at every layer: parameterized queries prevent SQL injection, bcrypt hashes protect passwords, CORS restricts browser origins, rate limiting prevents abuse.
- **The app runs as a Docker container** (Topic 31), deployed via a CI/CD pipeline (Topic 31), following 12-Factor principles (Topic 28). The API is documented with an **OpenAPI spec** (Topic 29).
- **Graceful shutdown** (Topic 21) ensures that when a new version deploys, the old instance finishes serving in-flight requests before exiting.
- **Tests** (Topic 27) caught the bug where orders with zero items were accepted, before it reached production.
- **Concurrency** (Topic 24) — the Node.js event loop (or Go goroutines, or Python async) is handling hundreds of requests simultaneously, using `Promise.all` for concurrent database queries within the handler.

---

**That's the complete picture.** Every topic in this syllabus is a piece of one interconnected system. None of them exist in isolation. The mark of a senior engineer isn't knowing each piece — it's understanding how they compose, where they conflict, and how to make trade-offs between them under real-world constraints.

Build things. Break things. Read the error messages. Read the RFCs. And remember: production is the only environment that matters.
