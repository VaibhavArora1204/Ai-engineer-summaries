# Layer 1: Environment & Dependency Management

> Python-focused. Node.js parallels noted where they differ meaningfully.

**The point:** Your code doesn't run in a vacuum. It runs inside an environment — a Python version, a set of installed packages at specific versions, a set of environment variables, an operating system. When any of these differ between your machine and the server, things break. Your Render failure was exactly this.

---

## 1.1 — Python Versions Matter More Than You Think

Your machine has Python 3.11. Render provisioned 3.9. A library you used requires 3.10+. Build fails with a cryptic syntax error or missing module.

**How to control it:**
- `.python-version` file in your repo root. Contains one line: `3.11.9`. Tools like `pyenv` locally and platforms like Render read this file.
- `runtime.txt` — Render-specific. Contains `python-3.11.9`. Other platforms use different mechanisms but the idea is identical.

**Failure mode:** You don't specify a version → platform picks its default (often older) → `match` statement fails because that's 3.10+ syntax → you get `SyntaxError` in deploy logs and have no idea why.

**Node.js parallel:** `.nvmrc` file, `engines` field in `package.json`. Same concept.

---

## 1.2 — Dependencies and Lockfiles

**requirements.txt is not enough.** Here's why:

```
# requirements.txt
fastapi
uvicorn
openai
langchain
```

This says "install these, any version." Today you get `langchain==0.2.14`. Three weeks later, Render builds fresh and gets `langchain==0.3.1` which has breaking API changes. Your code breaks. Nothing in your repo changed. This is called **dependency drift**.

**The fix — pin versions and use a lockfile:**

| Tool | Lock mechanism | What it does |
|------|---------------|--------------|
| `pip freeze > requirements.txt` | Pins everything with `==` | Crude but works. Problem: includes sub-dependencies you didn't ask for, messy to maintain |
| `pip-tools` | `requirements.in` → `requirements.txt` | You write top-level deps in `.in`, it resolves and pins everything in `.txt`. Clean separation |
| `poetry` | `pyproject.toml` → `poetry.lock` | Modern standard. Lockfile captures the entire dependency tree with hashes. Reproducible. Use this |
| `uv` | `pyproject.toml` → `uv.lock` | Fastest resolver. Written in Rust. Drop-in replacement for pip/poetry. Gaining adoption fast |

**Decision rule for you:** Use `uv`. It's the fastest, simplest, and the direction the Python ecosystem is heading. `poetry` is fine too but slower.

**Failure modes:**
- Lockfile not committed to git → CI resolves deps fresh → different versions → breaks
- `pip install` without lockfile on server → works today, breaks next month when a sub-dependency updates
- Conflicting version constraints between two packages → resolver fails → the error you saw on Render

**Node.js parallel:** `package.json` (your deps) + `package-lock.json` (lockfile). Same concept. `npm ci` (not `npm install`) is the command for CI — it reads the lockfile exactly instead of resolving fresh.

---

## 1.3 — Virtual Environments

**The point:** Your system Python has packages installed globally. Your project needs specific versions. Two projects need different versions of the same package. Without isolation, they conflict.

```bash
# What you should always do before anything
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

**On a server/container, this matters less** because the container IS the isolated environment. But locally, not using a venv is the #1 cause of "I installed it but Python can't find it" or "wrong version is being used."

**Failure mode:** You `pip install openai` system-wide. Another project needs an older version. You install it. First project breaks. You spend an hour confused. A venv would have prevented this entirely.

If you use `uv`, it handles this for you — `uv run` auto-creates and manages the venv.

---

## 1.4 — Environment Variables

**The point:** Configuration that changes between environments (local, staging, production) does not belong in code. API keys *especially* do not belong in code.

```python
# WRONG — hardcoded
client = OpenAI(api_key="sk-abc123...")

# RIGHT — from environment
import os
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
# Crashes immediately if key is missing. This is GOOD.
# Better than silently using None and failing 50 requests later.
```

- **Locally:** `.env` file + `python-dotenv` to load it
- **Production:** Set in platform dashboard (Render, Railway) or injected by CI/CD
- `.env` goes in `.gitignore`. **Always.** If your `.env` with API keys is on GitHub, assume the keys are stolen. Bots scrape GitHub for exposed keys within minutes — not an exaggeration.

**Failure modes:**
- `.env` committed to git → API key leaked → someone runs up your OpenAI bill
- Using `os.getenv("KEY")` (returns `None`) instead of `os.environ["KEY"]` (raises `KeyError`) → app starts, seems fine, crashes on first real request when `None` hits the API client
- Env var set in Render dashboard but with a trailing space → `"sk-abc123 "` → auth fails → you debug for an hour

---

## 1.5 — The Build Process — What Actually Happens on Deploy

When you push to Render (or any PaaS), this sequence runs:

```
1. Clone your repo
2. Detect language (looks for requirements.txt, pyproject.toml, package.json)
3. Install system dependencies (if specified)
4. Install Python (version from runtime.txt or default)
5. Install packages (pip install -r requirements.txt, or poetry install, etc.)
6. Run build command (if specified)
7. Run start command (e.g., uvicorn main:app --host 0.0.0.0 --port $PORT)
```

**Each step can fail.** The deploy log tells you which step. Learning to read build logs is not optional — it's the single most important debugging skill in DevOps.

**Failure modes by step:**

| Step | Failure | What you see |
|------|---------|-------------|
| 2 | Wrong detection — Render thinks it's a Node project because `package.json` exists alongside your Python code | `npm install` runs instead of `pip install` |
| 4 | Python version not available on platform | `Requested runtime python-3.13.0 is not available` |
| 5 | **This is where you died.** Dependency conflict | `ERROR: Cannot install X and Y because these package versions have conflicting dependencies` |
| 7 | `--host 0.0.0.0` missing (using `127.0.0.1` or `localhost` instead) | App starts, logs look fine, but platform can't reach it → **502 Bad Gateway** |
| 7 | `$PORT` not read from env var, hardcoded to 3000/8000 | Same as above — 502, because platform assigns a dynamic port |

**The `--host 0.0.0.0` trap deserves extra emphasis:**

```python
# WRONG — only accepts connections from inside the container
uvicorn.run(app, host="127.0.0.1", port=8000)

# RIGHT — accepts connections from the platform's reverse proxy
uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
```

`127.0.0.1` means "only listen for connections from myself." On your laptop, that's fine — you ARE "myself." On a server, the platform's load balancer is a *different* process trying to connect to your app. It gets refused. You see 502. Logs show the app running fine. This confuses people for hours.

---

## 1.6 — .gitignore — What Should Never Be in Your Repo

A surprising number of deploy failures come from either committing files that shouldn't be there, or not committing files that should.

**Must be in .gitignore:**
```
.env
.venv/
__pycache__/
*.pyc
.mypy_cache/
dist/
build/
*.egg-info/
node_modules/    # if you have any JS tooling
.DS_Store
```

**Must be committed (people forget these):**
- `requirements.txt` or `poetry.lock` or `uv.lock` — your lockfile
- `.python-version` or `runtime.txt` — your Python version spec
- `Dockerfile` (when you get to Layer 2)
- `.github/workflows/*.yml` (when you get to Layer 4)

**Failure mode:** `.venv/` committed to git → repo is 500MB → clone takes forever in CI → platform may also try to use the local venv paths which don't exist on the server → bizarre path errors.

---

## Checkpoint Scenario

Before we move to Layer 2 (Docker), reason through this:

> You deploy a FastAPI + LangChain app to Render. It worked yesterday. Today you push a small code change (just a prompt tweak in a string). Deploy fails with:
> `ERROR: Cannot install langchain==0.2.16 and chromadb==0.4.22 because these package versions have conflicting dependencies.`
>
> You didn't change any dependencies. Only the prompt string.

**Questions:**
1. Why did this break? What specifically changed between yesterday and today even though you only modified a prompt?
2. What's the immediate fix?
3. What would have *prevented* this from ever happening?

Think through it. Answer when ready. Don't search it.

---

## Build Task

After answering the checkpoint, do this on your actual machine:

1. Pick any Python project you have (or create a folder with a `main.py` that has at least 2 dependencies)
2. Run `pip install uv` (if you don't have it)
3. Run `uv init` in that folder
4. Add your dependencies with `uv add fastapi uvicorn`
5. Verify `uv.lock` was created and inspect it — notice how it pins exact versions and sub-dependencies
6. Commit both `pyproject.toml` and `uv.lock` to git

Come back when done. This is the foundation everything else builds on.
