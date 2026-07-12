# Layer 7: LLMOps — Operating LLM-Powered Apps in Production

> Not MLOps (model training). This is about operating apps that call LLM APIs.
> You don't train models. You consume them. These are your operational problems.

**The point:** Your LLM app has failure modes that traditional web apps don't: quality degrades silently, costs are unpredictable and per-request, prompts are unversioned code that bypass all testing, and your app's reliability depends on someone else's API uptime. LLMOps is the discipline of managing these specific risks.

---

## 7.1 — The LLMOps Problem Set

Traditional web app: code is deterministic. Same input → same output. Tests are assertions. Deploys are rollback-safe.

LLM app: **the LLM is a black box you don't control.** Same input → different output every time. "Tests" are statistical. A prompt change can break your app as severely as a code bug, but nothing in your standard CI catches it.

### Your actual operational risks:

| Risk | What It Looks Like | How You Detect It |
|------|-------------------|------------------|
| Quality degradation | Answers get worse over time | Eval runs, user feedback, retrieval metrics |
| Cost explosion | Bill doubles overnight | Cost-per-request tracking, budget alerts |
| API outage | OpenAI goes down, your app goes down | Fallback chains, health checks |
| Rate limiting | You hit OpenAI's rate limits under load | 429 monitoring, request queuing |
| Prompt regression | New prompt is worse than old | Eval gating in CI, A/B testing |
| Context window overflow | Input too long, gets truncated | Token counting before API call |
| Model deprecation | OpenAI sunsets gpt-4-0613, your hardcoded model string stops working | Use model aliases, pin dates, monitor deprecation notices |

---

## 7.2 — Prompt Versioning

**Prompts are code.** They should be version-controlled, reviewed, tested, and rolled back — just like any other code change.

### What NOT to do:

```python
# Prompt buried in application code, changed casually
response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a helpful assistant that answers questions based on the provided context. Be concise and accurate."}
    ]
)
```

**Problems:** No version history. No way to A/B test. Can't roll back without reverting code. Can't run eval on the prompt separately from a code change.

### What TO do:

```
prompts/
├── chat_system.txt          # System prompt text
├── chat_system.v2.txt       # New version being tested
├── rag_system.txt
└── summarize.txt

# Or structured:
prompts/
├── chat/
│   ├── system.txt
│   ├── user_template.txt    # "Given context: {context}\n\nQuestion: {query}"
│   └── config.yaml          # model, temperature, max_tokens
└── summarize/
    ├── system.txt
    └── config.yaml
```

```python
# prompts/chat/config.yaml
model: gpt-4
temperature: 0.3
max_tokens: 1024
system_prompt_file: system.txt
user_template_file: user_template.txt
```

```python
# Load prompts from files, not inline strings
from pathlib import Path
import yaml

def load_prompt_config(prompt_name: str):
    config_path = Path(f"prompts/{prompt_name}/config.yaml")
    config = yaml.safe_load(config_path.read_text())
    system_prompt = Path(f"prompts/{prompt_name}/{config['system_prompt_file']}").read_text()
    return config, system_prompt
```

**Benefits:**
- Git history shows exactly when each prompt changed and who changed it
- PR review for prompt changes (someone else reads your prompt before it ships)
- Eval suite runs against prompt changes in CI
- Rollback = revert a text file, not a code change

---

## 7.3 — Eval Pipelines — Your AI Test Suite

**The golden rule: if you can't measure quality, you can't ship prompt changes safely.**

### Building an eval set:

```jsonl
// eval/golden_prompts.jsonl — start with 20-50, grow over time
{"id": "001", "query": "How do I deploy to Render?", "expected_topics": ["dockerfile", "render.yaml", "build command"], "expected_format": "step-by-step"}
{"id": "002", "query": "What's the difference between EC2 and Lambda?", "expected_topics": ["compute", "pricing", "scaling"], "expected_format": "comparison"}
{"id": "003", "query": "Fix my CORS error", "expected_topics": ["Access-Control-Allow-Origin", "middleware", "backend fix"], "expected_format": "code example"}
```

### Eval strategies:

**1. Deterministic checks (run first, cheap):**
```python
def check_format(response: str, expected_format: str) -> bool:
    if expected_format == "json":
        try:
            json.loads(response)
            return True
        except:
            return False
    if expected_format == "step-by-step":
        return bool(re.search(r'(step \d|1\.|first)', response, re.I))
    return True
```

**2. Keyword/topic coverage (cheap, moderately useful):**
```python
def check_topics(response: str, expected_topics: list[str]) -> float:
    hits = sum(1 for topic in expected_topics if topic.lower() in response.lower())
    return hits / len(expected_topics)
```

**3. LLM-as-judge (expensive, most accurate):**
```python
async def llm_judge(query: str, response: str, criteria: str) -> float:
    judgment = await client.chat.completions.create(
        model="gpt-4",
        messages=[{
            "role": "system",
            "content": f"""Rate this response on a scale of 1-5 for: {criteria}
            Query: {query}
            Response: {response}
            Return ONLY a JSON object: {{"score": <1-5>, "reason": "<one sentence>"}}"""
        }],
        temperature=0
    )
    result = json.loads(judgment.choices[0].message.content)
    return result["score"] / 5.0  # Normalize to 0-1
```

### Eval pipeline in CI:

```yaml
# .github/workflows/eval.yml
name: Eval Gate

on:
  pull_request:
    paths:
      - 'prompts/**'        # Only run when prompts change
      - 'eval/**'           # Or eval set changes

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - name: Run eval
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: uv run python eval/run_eval.py --threshold 0.80
      - name: Post results to PR
        if: always()
        run: |
          # Post eval results as a PR comment
          uv run python eval/post_results.py --github-token ${{ secrets.GITHUB_TOKEN }}
```

**Now prompt changes get gated:** change a prompt → PR runs eval → if quality drops below threshold → PR can't merge. Same concept as tests blocking code merges.

---

## 7.4 — Cost Attribution and Control

Every LLM call costs money. Without tracking, you get a surprise bill.

### Cost tracking architecture:

```python
# Pricing table (update when models change)
PRICING = {
    "gpt-4": {"input": 0.03, "output": 0.06},       # per 1K tokens
    "gpt-4-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.005, "output": 0.015},
}

def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prices = PRICING.get(model, {"input": 0, "output": 0})
    return (prompt_tokens * prices["input"] / 1000) + \
           (completion_tokens * prices["output"] / 1000)

# In your LLM wrapper — every call gets cost-tagged
async def call_llm(messages, model="gpt-4", feature="unknown", user_tier="free"):
    response = await client.chat.completions.create(model=model, messages=messages)
    cost = calculate_cost(model, response.usage.prompt_tokens, response.usage.completion_tokens)

    logger.info(
        "llm_call",
        model=model,
        feature=feature,
        user_tier=user_tier,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        cost_usd=cost
    )
    return response
```

### Cost control strategies:

| Strategy | How | Savings |
|----------|-----|---------|
| Model routing | Use gpt-4-mini for simple queries, gpt-4 for complex | 50-90% on simple queries |
| Caching | Cache identical queries (semantic cache for similar) | 30-70% for repeat queries |
| Prompt optimization | Shorter system prompts, less context, fewer examples | 10-30% |
| Token limits | Set max_tokens to what you actually need | Prevents runaway completions |
| User quotas | Limit requests per user per day by tier | Caps worst-case cost |
| Budget alerts | Alert when daily/weekly spend exceeds threshold | Catches anomalies |

### Budget alerting:

```python
# Daily cost check (run as a cron job or scheduled task)
async def check_daily_budget():
    today_cost = await db.execute(
        "SELECT SUM(cost_usd) FROM llm_calls WHERE date = CURRENT_DATE"
    )
    if today_cost > DAILY_BUDGET_THRESHOLD:
        alert(f"Daily LLM spend ${today_cost:.2f} exceeds budget ${DAILY_BUDGET_THRESHOLD}")

    # Also check per-user anomalies
    top_users = await db.execute("""
        SELECT user_id, SUM(cost_usd) as total
        FROM llm_calls WHERE date = CURRENT_DATE
        GROUP BY user_id ORDER BY total DESC LIMIT 5
    """)
    for user in top_users:
        if user.total > PER_USER_DAILY_LIMIT:
            alert(f"User {user.user_id} spent ${user.total:.2f} today")
```

---

## 7.5 — Fallback Chains — Surviving API Outages

OpenAI goes down. Anthropic rate-limits you. Your primary model is slow under load. Without fallbacks, your app is dead.

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

class LLMRouter:
    def __init__(self):
        self.providers = [
            {"name": "openai-gpt4", "client": openai_client, "model": "gpt-4"},
            {"name": "openai-gpt4-mini", "client": openai_client, "model": "gpt-4-mini"},
            {"name": "anthropic-sonnet", "client": anthropic_client, "model": "claude-sonnet-4-20250514"},
        ]
        self.cache = ResponseCache()

    async def call(self, messages, timeout=10.0, feature="default"):
        # Try cache first
        cached = self.cache.get(messages)
        if cached:
            logger.info("llm_cache_hit", feature=feature)
            return cached

        # Try each provider in order
        for provider in self.providers:
            try:
                response = await asyncio.wait_for(
                    self._call_provider(provider, messages),
                    timeout=timeout
                )
                self.cache.set(messages, response)
                logger.info("llm_call_success", provider=provider["name"], feature=feature)
                return response
            except asyncio.TimeoutError:
                logger.warning("llm_timeout", provider=provider["name"], feature=feature)
                continue
            except Exception as e:
                logger.warning("llm_error", provider=provider["name"], error=str(e), feature=feature)
                continue

        # All providers failed
        logger.error("llm_all_providers_failed", feature=feature)
        return self._fallback_response()

    def _fallback_response(self):
        return {
            "content": "I'm currently unable to process your request. Please try again in a few minutes.",
            "fallback": True
        }
```

**Fallback chain order:**
1. Cache (instant, free)
2. Primary model (best quality)
3. Cheaper/faster model (degraded quality, but works)
4. Alternative provider (different API, same capability)
5. Static fallback response (last resort — better than a 500 error)

**Key insight:** A degraded response is almost always better than an error. Users can tolerate "slightly worse answer" but not "app is broken."

**Failure mode:** Fallback to a cheaper model that can't handle the same context length → truncated input → garbage output that looks like a real answer. Always validate that your fallback model can handle your prompt sizes.

---

## 7.6 — Feature Flags for AI

Deploy a prompt change to 5% of users. Measure quality. Roll out gradually.

```python
# Simple feature flag implementation (no external service needed to start)
import random

FEATURE_FLAGS = {
    "new_chat_prompt": {
        "enabled": True,
        "rollout_percentage": 10,  # 10% of users
    },
    "gpt4_mini_routing": {
        "enabled": True,
        "rollout_percentage": 50,
    }
}

def is_flag_enabled(flag_name: str, user_id: str) -> bool:
    flag = FEATURE_FLAGS.get(flag_name)
    if not flag or not flag["enabled"]:
        return False

    # Deterministic: same user always gets same result
    # (hash-based, not random, so experience is consistent per user)
    hash_val = hash(f"{flag_name}:{user_id}") % 100
    return hash_val < flag["rollout_percentage"]

# Usage:
async def handle_chat(query, user_id):
    if is_flag_enabled("new_chat_prompt", user_id):
        prompt = load_prompt("chat_v2")
    else:
        prompt = load_prompt("chat_v1")
    ...
```

**Why this matters for AI:** You can't fully test prompt changes pre-production. Real user queries are different from your eval set. Feature flags let you expose changes to a small group, measure real-world quality, and roll back without a deploy if something goes wrong.

**External tools (when you outgrow the simple version):** LaunchDarkly, PostHog, Unleash. They add targeting rules (flag on for paid users only), analytics, and dashboards.

---

## 7.7 — Context Window Management

Every LLM has a context window limit. When you exceed it, the API either errors or silently truncates your input. Both are bad.

```python
import tiktoken

def count_tokens(text: str, model: str = "gpt-4") -> int:
    encoder = tiktoken.encoding_for_model(model)
    return len(encoder.encode(text))

def build_prompt_with_budget(
    system_prompt: str,
    user_query: str,
    retrieved_docs: list[str],
    model: str = "gpt-4",
    max_context: int = 8000,      # Leave room for output
    max_output: int = 1024
):
    budget = max_context - max_output
    used = count_tokens(system_prompt + user_query, model)
    remaining = budget - used

    # Add documents until budget is exhausted
    included_docs = []
    for doc in retrieved_docs:
        doc_tokens = count_tokens(doc, model)
        if doc_tokens > remaining:
            break
        included_docs.append(doc)
        remaining -= doc_tokens

    if not included_docs:
        logger.warning("context_budget_exhausted",
            system_tokens=count_tokens(system_prompt, model),
            query_tokens=count_tokens(user_query, model),
            budget=budget
        )

    return build_messages(system_prompt, included_docs, user_query)
```

**Failure modes:**
- No token counting → send 50k tokens to a model with 8k context → error or truncation → answer ignores most of your context
- Token counting but no prioritization → first 3 retrieved docs fill the context, most relevant doc is #4 and gets dropped
- Not accounting for output tokens → fill context to max → model has no room to generate a full response → truncated output

---

## 7.8 — Model Deprecation and Versioning

LLM providers deprecate models. OpenAI sunset `gpt-4-0314` with 3 months notice. If your code hardcodes that model string, it stops working on the sunset date.

```python
# BAD — hardcoded model, will break when deprecated
model = "gpt-4-0613"

# BETTER — configurable, update one place
MODEL_CONFIG = {
    "primary": os.environ.get("LLM_PRIMARY_MODEL", "gpt-4"),
    "fallback": os.environ.get("LLM_FALLBACK_MODEL", "gpt-4-mini"),
}

# BEST — model alias that auto-resolves to latest
# OpenAI does this with "gpt-4" (alias) vs "gpt-4-0613" (specific snapshot)
# Use the alias for flexibility, snapshot for reproducibility in eval
```

**Decision rule:** Use model aliases (`gpt-4`) in production for auto-updates. Use snapshots (`gpt-4-0613`) in eval runs for reproducibility. If a new model version degrades your eval score, you have the old snapshot as a comparison point.

---

## Checkpoint Scenario

> You run an AI customer support bot. It costs you $30/day in OpenAI API calls. A new customer signs up and starts sending 500 queries per day through your bot, each with long context (pasting entire documents and asking questions).
>
> Your daily cost jumps to $180. You don't notice for a week. Bill is now $1,260 higher than expected.

**Questions:**
1. What three things should have existed to catch this within the first day?
2. Should you block this user? What's the right response operationally?
3. Design a cost-control system that would prevent this. Be specific about what triggers and what actions.

---

## Build Task

1. Create a `prompts/` directory in a project, move all inline prompt strings into files
2. Build a minimal eval script: 10 test queries, check format compliance and topic coverage
3. Implement a basic fallback chain: primary model → cheaper model → static response
4. Add token counting before every LLM call with `tiktoken`
5. Add cost logging to every LLM call (log model, tokens, calculated cost)
