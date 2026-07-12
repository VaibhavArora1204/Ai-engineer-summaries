# Layer 2: Containerization (Docker)

> Python-focused. The single most important tool in this entire curriculum.

**The point:** Docker makes your code run identically everywhere — your laptop, CI, staging, production — by packaging your code, its dependencies, its runtime, and its OS-level config into a single artifact called an image. The "works on my machine" problem dies here.

---

## 2.1 — What a Container Actually Is

A container is **not** a virtual machine. This matters for debugging.

| | VM | Container |
|---|---|---|
| What it virtualizes | Entire hardware — CPU, RAM, disk, network | Just the filesystem and process namespace |
| Has its own OS kernel | Yes (runs its own Linux/Windows) | No — shares the host's kernel |
| Boot time | 30-60 seconds | Milliseconds |
| Size | Gigabytes | Megabytes to low gigabytes |
| Isolation | Full hardware isolation | Process-level isolation (weaker, but sufficient) |

**Why this matters operationally:**
- Containers share the host kernel → a kernel bug affects all containers on that host
- Containers are cheap to start/stop → you can run 50 containers on a machine that could run 5 VMs
- "My container works on Linux but not on Windows" → because the container uses the Linux kernel. On Windows, Docker Desktop runs a hidden Linux VM to provide that kernel. On a Linux server, it's native. This is why Docker on Mac/Windows is slightly different from Docker on Linux

**Mental model:** A container is a process that *thinks* it has its own computer. It has its own filesystem, its own network interface, its own process list. But underneath, it's just a regular process on the host, with Linux kernel features (`cgroups`, `namespaces`) creating the illusion of isolation.

---

## 2.2 — Images vs Containers

**Image** = a frozen, read-only filesystem snapshot + metadata (what command to run on startup, what port to expose, what env vars to set). Think of it as a `.zip` of an entire OS with your app installed.

**Container** = a running instance of an image. You can run 10 containers from the same image. Each gets its own writable layer on top of the read-only image.

```
Image (read-only)          Container 1 (running)      Container 2 (running)
┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
│ Ubuntu 22.04     │       │ Writable layer   │       │ Writable layer   │
│ Python 3.11      │──────►│──────────────────│  ────►│──────────────────│
│ Your code        │       │ Image layers     │       │ Image layers     │
│ Your dependencies│       │ (read-only)      │       │ (read-only)      │
└──────────────────┘       └──────────────────┘       └──────────────────┘
```

**Key commands:**

```bash
docker build -t myapp:v1 .       # Build an image from a Dockerfile
docker run myapp:v1              # Create and start a container from the image
docker ps                        # List running containers
docker ps -a                     # List ALL containers (including stopped)
docker logs <container_id>       # View container stdout/stderr — YOUR FIRST DEBUG TOOL
docker exec -it <container_id> bash  # Shell into a running container for debugging
docker stop <container_id>       # Stop a container
docker rm <container_id>         # Remove a stopped container
docker images                    # List all local images
docker rmi <image_id>            # Remove an image
```

**Failure mode:** Container exits immediately → you run `docker ps`, see nothing → run `docker ps -a`, see your container with status `Exited (1)` → run `docker logs <container_id>` → see the actual error. This is the workflow. Burn it in.

---

## 2.3 — Dockerfile — Writing the Recipe

A Dockerfile is a sequence of instructions that builds an image. Each instruction creates a **layer**. Layers are cached — if nothing changed in a layer, Docker reuses the cached version. This matters enormously for build speed.

### Basic Dockerfile for a Python FastAPI app:

```dockerfile
# 1. Base image — what OS and Python version
FROM python:3.11-slim

# 2. Set working directory inside the container
WORKDIR /app

# 3. Copy dependency files FIRST (for caching — explained below)
COPY requirements.txt .

# 4. Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy your actual code
COPY . .

# 6. Expose the port your app listens on (documentation, not enforcement)
EXPOSE 8000

# 7. The command that runs when the container starts
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Why the order matters — layer caching:

```
COPY requirements.txt .     ← Only changes when dependencies change
RUN pip install ...          ← CACHED if requirements.txt didn't change
COPY . .                    ← Changes on every code change
```

If you `COPY . .` first, then `pip install`, Docker can't cache the install step because COPY invalidated the cache (your code changed). Every build reinstalls all dependencies from scratch. On a project with heavy deps (torch, langchain), that's 5-10 minutes wasted per build.

**Rule:** Copy dependency files → install → copy code. Always.

### With `uv` instead of pip:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (frozen = use lockfile exactly, no resolution)
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 2.4 — .dockerignore

Same concept as `.gitignore`. Tells Docker what NOT to include in the build context (the files Docker can see during build).

```
.venv/
__pycache__/
*.pyc
.git/
.env
node_modules/
.mypy_cache/
*.md
tests/
```

**Why this matters:**
- `.venv/` is often 500MB+ → sending it to Docker daemon takes minutes, and you don't need it (you install deps fresh in the image)
- `.env` should never be in an image — secrets baked into an image are secrets anyone with access to the image can extract
- `.git/` can be hundreds of MB in large repos

**Failure mode:** No `.dockerignore` → build context is 1GB → `docker build` hangs for minutes on "Sending build context to Docker daemon" → you think Docker is broken, it's not, it's just copying files you don't need.

---

## 2.5 — Multi-Stage Builds

**The problem:** Your build process needs tools (compilers, build deps like `gcc`, dev headers) that your runtime doesn't. Including them in the final image wastes space and increases attack surface.

```dockerfile
# ---- Stage 1: Build ----
FROM python:3.11 AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Stage 2: Runtime ----
FROM python:3.11-slim

WORKDIR /app

# Copy only the installed packages from the build stage
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Result:** Build stage uses `python:3.11` (has gcc, make, headers — ~900MB). Runtime stage uses `python:3.11-slim` (~150MB). Final image is small, deploys fast, has less attack surface.

**When to use this:** When you have packages that need C compilation during install (e.g., `psycopg2`, `numpy`, `grpcio`). If all your deps are pure Python, the slim image alone is fine.

---

## 2.6 — Docker Compose — Running Multiple Services Locally

Your app doesn't run alone. It needs a database, maybe Redis, maybe a vector DB. Docker Compose lets you define and run all of them together locally.

```yaml
# docker-compose.yml
version: "3.8"

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/myapp
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - db

  db:
    image: postgres:16
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=myapp
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  pgdata:
```

**Key concepts:**
- `services` = each container (your app, the database, etc.)
- `build: .` = build from the Dockerfile in current directory
- `image: postgres:16` = use a pre-built image from Docker Hub
- `ports: "8000:8000"` = map host port to container port (host:container)
- `depends_on` = start order (but does NOT wait for the service to be *ready*, just *started* — this bites people)
- `volumes` = persistent storage. Without this, database data dies when the container is removed
- Service names (`db`) become DNS names inside the Docker network → your app connects to `db:5432`, not `localhost:5432`

**Commands:**

```bash
docker compose up              # Start everything (foreground, see all logs)
docker compose up -d           # Start everything (background/detached)
docker compose down            # Stop and remove containers
docker compose down -v         # Stop, remove containers AND volumes (wipes DB data)
docker compose logs app        # View logs for one service
docker compose build           # Rebuild images without starting
docker compose ps              # List running services
```

**Failure modes:**
- `depends_on` doesn't wait for readiness → app starts, DB isn't accepting connections yet → app crashes → compose restarts it → eventually works, but you see errors in logs. Fix: add health checks or retry logic in your app
- Forgetting `volumes` → DB works great, you `docker compose down`, all data is gone
- Port conflict → something else on your machine uses port 5432 → compose fails to bind. Either stop the other service or change the host port: `"5433:5432"`
- Using `localhost` in app to reach DB → wrong. Inside Docker network, use the service name (`db`). `localhost` inside the app container means the app container itself, where no database is running

---

## 2.7 — Volumes and Data Persistence

Containers are **ephemeral** by default. Anything written inside a container is gone when the container is removed. This is intentional — it forces you to be explicit about what persists.

**Two types of persistence:**

```yaml
# Named volume — Docker manages the storage location
volumes:
  pgdata:
    driver: local

# Bind mount — maps a host folder into the container
services:
  app:
    volumes:
      - ./src:/app/src    # Host path : Container path
```

**Named volumes** — for production-like persistence (databases). Docker manages where the data lives on disk. You don't need to know or care.

**Bind mounts** — for development. Mount your source code into the container so code changes reflect immediately without rebuilding the image. Not for production.

**Failure mode:** Using bind mounts in production → host filesystem fills up → no monitoring on it because it's outside Docker's awareness → database silently fails on writes → data corruption.

---

## 2.8 — Docker Networking

When you run `docker compose up`, Compose creates a **network** for your services. Each service gets a DNS entry matching its name.

```
┌─── Docker Network (myapp_default) ───┐
│                                       │
│  app (172.18.0.2)  ←→  db (172.18.0.3)│
│                                       │
└───────────────────────────────────────┘
        │
   ports: 8000 → exposed to host
```

- Services talk to each other by service name: `app` connects to `db:5432`
- Only services with `ports` mapping are accessible from outside the Docker network
- The DB in the example above is reachable from the host at `localhost:5432` only because we explicitly mapped the port. Remove the port mapping → DB is only accessible from other containers in the same network

**Failure mode:** Two Compose projects running simultaneously → if they use the same port on the host, second one fails. Each project gets its own isolated network by default (good), but port mappings on the host can conflict.

---

## 2.9 — Registry — Where Images Live

You build an image locally. Production needs to pull it from somewhere. That somewhere is a **registry**.

| Registry | When to use |
|----------|------------|
| Docker Hub | Public images (base images like `python:3.11`, `postgres:16`). Free for public repos |
| GitHub Container Registry (ghcr.io) | Your private images. Free with GitHub. Integrates with GitHub Actions |
| AWS ECR / GCP Artifact Registry | Cloud-specific. Use when you deploy to that cloud |

**Workflow:**
```bash
docker build -t ghcr.io/yourusername/myapp:v1 .   # Build and tag for registry
docker push ghcr.io/yourusername/myapp:v1          # Push to registry
# On the server / in CI:
docker pull ghcr.io/yourusername/myapp:v1           # Pull from registry
docker run ghcr.io/yourusername/myapp:v1            # Run it
```

**Tags:** `:v1`, `:latest`, `:abc123` (git commit hash). Using `:latest` in production is a common mistake — it's mutable. Someone pushes a new `:latest`, your production pulls it on next restart, you get an untested version. Use immutable tags (version numbers or commit hashes).

**Failure mode:** Using `:latest` → deploy happens at 2am (auto-restart or scaling event) → pulls newest image that hasn't been tested → app breaks → you're debugging a version you didn't deploy.

---

## 2.10 — Common Debugging Workflow

When something goes wrong with Docker (and it will), this is the decision tree:

```
Container won't START?
├── docker build fails
│   ├── "Sending build context" hangs → .dockerignore missing, context too large
│   ├── "COPY failed" → file not in build context, check .dockerignore
│   ├── "RUN pip install fails" → dependency issue, same as Layer 1 but now inside container
│   └── Check which Dockerfile line failed, each RUN is a layer
│
├── docker run exits immediately
│   ├── docker logs <id> → read the error
│   ├── CMD is wrong (typo, wrong path)
│   ├── Missing env var → app crashes on import
│   └── Port already in use (if using --network host)
│
└── Container runs but app doesn't work
    ├── 502 from platform → app not listening on right host/port
    ├── Can't reach database → wrong hostname (localhost vs service name)
    ├── Permission denied → file ownership issues in image
    └── docker exec -it <id> bash → get inside, poke around, check file paths
```

**The single most important command:** `docker logs <container_id>`. Always. Before anything else. Read the logs.

---

## Checkpoint Scenario

> You Dockerize your FastAPI app. `docker build` succeeds. `docker run` shows the app starting. You hit `localhost:8000` in your browser → connection refused.
>
> You check `docker logs` — it shows `Uvicorn running on http://127.0.0.1:8000`.
>
> The app IS running inside the container. But you can't reach it from outside.

**Questions:**
1. What's wrong?
2. What's the one-character fix?
3. Why does `127.0.0.1` work on your laptop but not inside a container?

---

## Build Task

1. Take any Python project you have (or create a `main.py` FastAPI app with one endpoint)
2. Write a `Dockerfile` for it (use the template from 2.3)
3. Write a `.dockerignore`
4. Run `docker build -t myapp .`
5. Run `docker run -p 8000:8000 myapp`
6. Hit `localhost:8000` — verify it works
7. Break it intentionally: change `--host 0.0.0.0` to `--host 127.0.0.1`, rebuild, run, and observe the failure
8. If your app needs a database, write a `docker-compose.yml` and run it with `docker compose up`
