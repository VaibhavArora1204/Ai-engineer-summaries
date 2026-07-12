# Layer 4: CI/CD — Automated Build, Test, Deploy

> Python-focused, GitHub Actions as the primary tool.

**The point:** CI/CD is the automated pipeline that builds your code, tests it, and deploys it every time you push. Without it, you're manually deploying by clicking buttons or running scripts — which means deploys are scary, infrequent, and error-prone. With it, deploying is boring, which is exactly what you want.

---

## 4.1 — CI vs CD — What They Actually Mean

**CI (Continuous Integration):** Every push to the repo triggers an automated process that:
1. Checks out your code
2. Installs dependencies
3. Runs linters (code style)
4. Runs tests
5. Reports pass/fail

The point of CI: **you find out your code is broken within minutes, not after deploy.** If CI passes, you have reasonable confidence the code at least builds and passes tests.

**CD has two meanings:**
- **Continuous Delivery**: CI passes → code is *ready* to deploy, but a human clicks "deploy." Used when you want a manual gate (e.g., staging review before production).
- **Continuous Deployment**: CI passes → code deploys automatically. No human in the loop.

**Decision rule:**
- Side projects, personal apps: continuous deployment. You're the only user, ship fast.
- Apps with real users: continuous delivery or deployment with feature flags. You want the ability to deploy without risk (flag off = code is deployed but inactive).

---

## 4.2 — GitHub Actions — The Mechanics

GitHub Actions runs **workflows** — YAML files in `.github/workflows/` that execute on triggers.

### Concepts:

```
Workflow (.yml file)
├── Trigger (on: push, pull_request, schedule, manual)
├── Job (runs on a fresh VM — "runner")
│   ├── Step 1: checkout code
│   ├── Step 2: setup Python
│   ├── Step 3: install deps
│   ├── Step 4: run linter
│   ├── Step 5: run tests
│   └── Step 6: deploy (if on main branch)
└── Job 2 (runs in parallel unless needs: job1)
```

**Key facts:**
- Each **job** runs on a fresh VM (ubuntu-latest by default). Nothing persists between jobs unless you explicitly pass artifacts
- **Steps** within a job run sequentially in the same VM
- Jobs run in **parallel** by default. Use `needs: [job-name]` to create dependencies
- Runners are free for public repos, 2000 minutes/month free for private repos
- Each runner has: Ubuntu, common tools (git, docker, curl), 7GB RAM, 14GB disk

### Basic CI Workflow for Python:

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      # 1. Get the code
      - uses: actions/checkout@v4

      # 2. Set up Python
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      # 3. Install uv
      - uses: astral-sh/setup-uv@v3

      # 4. Install dependencies
      - run: uv sync --frozen

      # 5. Lint
      - run: uv run ruff check .

      # 6. Type check (optional but recommended)
      - run: uv run mypy .

      # 7. Test
      - run: uv run pytest tests/ -v

      # 8. Build Docker image (verify it builds, don't push yet)
      - run: docker build -t myapp:test .
```

**What `uses: actions/checkout@v4` means:** It's a pre-built action from the GitHub Actions marketplace. `@v4` pins the version. Actions are just reusable steps. The checkout action clones your repo into the runner.

---

## 4.3 — CI + CD: Adding Deployment

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]   # Only deploy from main

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - run: uv run pytest tests/ -v

  deploy:
    runs-on: ubuntu-latest
    needs: test                    # Only runs if test job passes
    if: github.ref == 'refs/heads/main'  # Extra guard: only on main

    steps:
      - uses: actions/checkout@v4

      # Build and push Docker image
      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}   # Auto-provided by GitHub

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}

      # Deploy to your platform (example: webhook trigger to Render)
      - name: Trigger Render deploy
        run: |
          curl -X POST "${{ secrets.RENDER_DEPLOY_HOOK }}"
```

**Key points:**
- `needs: test` → deploy only runs after tests pass. This is your safety gate
- `${{ secrets.RENDER_DEPLOY_HOOK }}` → secrets stored in GitHub Settings → Secrets. Never in YAML
- `${{ github.sha }}` → the git commit hash. Used as image tag. Immutable. You always know exactly which commit is deployed
- `${{ secrets.GITHUB_TOKEN }}` → auto-generated token with permissions scoped to this repo. Free. No setup needed for GHCR

---

## 4.4 — Secrets Management in CI

**Rule:** Secrets never appear in code, YAML, or logs.

**How to add secrets to GitHub Actions:**
1. Repo → Settings → Secrets and variables → Actions → New repository secret
2. Name: `OPENAI_API_KEY`, Value: `sk-...`
3. Access in workflow: `${{ secrets.OPENAI_API_KEY }}`

**Failure modes:**
- Printing secrets in logs: `echo ${{ secrets.OPENAI_API_KEY }}` → GitHub auto-masks known secrets with `***`, but this is best-effort, not guaranteed. Don't rely on it
- Using secrets in PR workflows from forks → GitHub does NOT inject secrets for fork PRs (security measure). Your CI will fail with empty env vars. This is intentional
- Secret rotation → you change the API key in the provider (OpenAI), forget to update GitHub Secrets → next deploy fails
- Too broad secrets → one secret has access to everything → if leaked, everything is compromised. Use scoped tokens with minimum permissions

---

## 4.5 — Caching — Making CI Fast

Without caching, every CI run installs dependencies from scratch. For a Python project with heavy deps (langchain, torch), that's 3-10 minutes of waiting.

```yaml
# Cache uv dependencies
- uses: astral-sh/setup-uv@v3
  with:
    enable-cache: true   # uv action has built-in caching

# Or manual cache for pip:
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: pip-${{ runner.os }}-${{ hashFiles('requirements.txt') }}
    restore-keys: |
      pip-${{ runner.os }}-
```

**How caching works:**
1. First run: no cache → full install → cache is saved with the key
2. Second run: key matches (requirements.txt hasn't changed) → cache restored → install skips already-installed packages → 30s instead of 5min
3. Key changes (new dependency added) → cache miss → full install → new cache saved

**Cache key design:** Use `hashFiles('lockfile')` so the cache busts only when dependencies actually change.

**Docker layer caching:**
```yaml
- uses: docker/build-push-action@v5
  with:
    push: true
    tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
    cache-from: type=gha    # Use GitHub Actions cache for Docker layers
    cache-to: type=gha,mode=max
```

Without this, every Docker build re-runs every layer. With it, only changed layers rebuild. The difference for a Python app: 8 minutes → 45 seconds.

**Failure mode:** CI takes 15 minutes → developers push without waiting for CI → bugs reach main → CI becomes a thing people ignore. Fast CI (~2-3 minutes) is not a nice-to-have, it's required for CI to be useful.

---

## 4.6 — Branch Strategy

Keep it simple. Two patterns:

### GitHub Flow (use this)
```
main ──────────────────────────────────── (always deployable)
  └── feature/add-search ──── PR ──── merge
  └── fix/timeout-bug ──── PR ──── merge
```

- `main` is always deployable
- All work happens on feature branches
- PRs trigger CI
- Merge to `main` triggers deploy
- That's it. No develop branch, no release branches, no GitFlow

### When you need more (later, not now):
- **Staging environment**: deploy `main` to staging first, promote to production after verification
- **Release branches**: only when you have versioned releases (libraries, mobile apps)
- **GitFlow**: overcomplicated for 99% of projects. If someone suggests it, ask what problem it solves that GitHub Flow doesn't. Usually the answer is nothing

---

## 4.7 — CI for Non-Deterministic Systems (AI-specific)

Standard CI: `assert result == expected`. Deterministic. Either passes or fails.

AI/LLM CI: the same prompt can produce different outputs. `assert result == expected` fails randomly even when nothing is broken. This is the fundamental problem.

**How to test AI systems in CI:**

| Test Type | What It Checks | How |
|-----------|---------------|-----|
| Format tests | Output is valid JSON, has required fields | Parse output, check schema. Deterministic |
| Smoke tests | Model responds, doesn't crash, finishes in <Xs | Call with fixed prompts, check status code and latency. Mostly deterministic |
| Eval tests | Output quality meets threshold | Run N prompts from golden set, score with rubric or LLM-as-judge, check average score > threshold |
| Regression tests | Quality didn't degrade vs. last known good | Compare current eval scores to baseline stored in repo |
| Cost tests | Token usage is within expected range | Count tokens per test prompt, flag if >2x expected |

```yaml
# Example: eval gate in CI
- name: Run eval suite
  run: |
    uv run python eval/run_eval.py \
      --golden-set eval/golden_prompts.jsonl \
      --threshold 0.85 \
      --output eval/results.json

- name: Check eval passed
  run: |
    SCORE=$(jq '.average_score' eval/results.json)
    if (( $(echo "$SCORE < 0.85" | bc -l) )); then
      echo "❌ Eval score $SCORE below threshold 0.85"
      exit 1
    fi
    echo "✅ Eval score $SCORE"
```

**Critical insight:** The golden set is the most important artifact in your repo. It's a curated set of (input, expected_behavior) pairs that represent your app's critical cases. Start with 20-50 examples. Review and expand it after every production bug.

**Failure modes:**
- No eval gate → prompt change goes to production → quality drops 20% → you find out from user complaints 2 weeks later
- Eval set too small → doesn't cover edge cases → CI passes but real-world inputs hit uncovered scenarios
- Eval set tests happy path only → everything passes, but the model fails on adversarial/unusual inputs
- Non-deterministic CI → test flakes → team ignores CI failures → defeats the purpose

---

## 4.8 — Deployment Strategies

How you swap old code for new code without users noticing.

### Rolling Deploy
```
Instances: [v1] [v1] [v1]
           [v2] [v1] [v1]   ← replace one at a time
           [v2] [v2] [v1]
           [v2] [v2] [v2]   ← done
```
- Default on most PaaS
- During the rollout, some requests hit v1, some hit v2
- If v2 is broken, you catch it mid-roll (if you have health checks)
- Failure mode: v1 and v2 have incompatible database schemas → requests during rollout fail because they hit v2 code with v1 database, or vice versa

### Blue-Green
```
Blue (v1):  [v1] [v1] [v1]  ← currently serving traffic
Green (v2): [v2] [v2] [v2]  ← spun up, tested, NOT serving yet

Switch: traffic → Green
If broken: switch back to Blue immediately
```
- Instant rollback (just point traffic back to Blue)
- Costs 2x resources during deploy (both versions running)
- Render's "zero-downtime deploy" is basically this

### Canary
```
[v1] [v1] [v1] [v1] [v1]
[v1] [v1] [v1] [v1] [v2]  ← 20% of traffic to v2

Monitor for 10 min...

If OK: [v2] [v2] [v2] [v2] [v2]  ← full rollout
If bad: [v1] [v1] [v1] [v1] [v1]  ← rollback
```
- Most controlled. Test new version with real traffic at low risk
- Requires traffic splitting (load balancer config or feature flags)
- **This is the right strategy for AI/LLM changes** — a prompt change might look fine in eval but behave differently with real user inputs. Canary catches that

**For your stage:** Rolling deploy (default PaaS behavior) is fine. Know that canary exists for when you're deploying prompt changes to real users.

---

## 4.9 — Rollback — When Things Go Wrong

**Rollback = reverting to the previous known-good version.**

```bash
# If using Git-based deploys (Render):
git revert HEAD     # Create a commit that undoes the last change
git push            # Triggers a new deploy of the reverted code

# If using Docker image deploys:
# Deploy the previous image tag
docker pull ghcr.io/you/app:abc123    # previous commit hash
# Re-deploy with this tag in your platform
```

**The real question: how fast can you rollback?**
- If your deploy takes 10 minutes → you're broken for 10 minutes minimum
- If you have blue-green → rollback is instant (switch traffic back)
- If you have no rollback plan → you're fixing forward under pressure at 3am. Bad

**Failure mode:** Rollback doesn't work because the new version ran a database migration that's not backward-compatible. v1 code can't work with v2 database schema. This is why database migrations must be backward-compatible (add columns, don't rename or remove them in the same deploy).

---

## Checkpoint Scenario

> You push a prompt change to your RAG app. CI passes (format tests pass, eval score is 0.87 vs threshold 0.85). Deploy goes through. Two hours later, users report the app is returning incomplete answers for a specific type of question you didn't have in your eval set.

**Questions:**
1. What went wrong with your CI/CD process?
2. What would a canary deploy have caught that full deployment didn't?
3. What's the fastest way to fix this right now, and what do you add to prevent it next time?

---

## Build Task

1. Create a `.github/workflows/ci.yml` for any Python project
2. Include: checkout, setup Python, install deps (uv), lint (ruff), test (pytest with at least one test)
3. Push to GitHub, verify the workflow runs on the Actions tab
4. Make a failing test, push, verify CI fails
5. Fix it, push, verify CI passes
6. Add dependency caching — compare build times before and after
