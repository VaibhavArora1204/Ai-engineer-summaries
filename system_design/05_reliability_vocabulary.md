# 05 — Reliability Vocabulary

## The Problem

Your RAG API is deployed. It works. But what does "works" mean? Does it mean every request succeeds? No system does that. Does it mean it's fast? How fast is fast? Does it mean it doesn't go down? How much downtime is acceptable — zero (impossible), 5 minutes a year (extremely expensive), 8 hours a year (probably fine for most products)?

Without precise vocabulary, reliability conversations devolve into arguments between people using the same words to mean different things. "It should be highly available" — what does that mean? 99%? 99.99%? Those sound similar but the difference in engineering effort and cost is a factor of 100.

This module gives you the vocabulary. Not the theory — the practical vocabulary that lets you participate in (and defend) real design conversations about how reliable a system needs to be, what trade-offs that requires, and where to set the line between "good enough" and "gold-plating."

---

## The Naive Approach and Why It Fails

The naive approach is to promise 100% availability, assume latency is one number, and never define what "working" means.

This fails because:
- 100% availability is physically impossible. Hardware fails. Networks partition. Software has bugs. Promising 100% means you never set realistic expectations and you're always "failing."
- "Latency is 200ms" is meaningless without a percentile. The average might be 200ms while 1% of users wait 5 seconds. That 1% has a terrible experience and your average hides it.
- "The system is working" is ambiguous. Working for who? If the API returns 200 OK but the answer is wrong because the vector database is stale, is the system "working"?

---

## The Real Mechanism

### Availability — The Nines

Availability is the percentage of time the system is operational and serving correct responses.

```
Availability    Downtime per year     Downtime per month    Downtime per day
99%             3.65 days             7.3 hours             14.4 minutes
99.9%           8.76 hours            43.8 minutes          1.44 minutes
99.95%          4.38 hours            21.9 minutes          43.2 seconds
99.99%          52.6 minutes          4.38 minutes          8.64 seconds
99.999%         5.26 minutes          26.3 seconds          0.86 seconds
```

**The cost of each additional nine is roughly 10x the engineering effort.** Going from 99% to 99.9% might mean adding a load balancer and a second server. Going from 99.9% to 99.99% might mean multi-region deployment, automated failover, and a 24/7 on-call rotation. Going from 99.99% to 99.999% might require custom hardware, formal verification, and a team of 10 SREs.

**How availability compounds in distributed systems:** If your system has two services in series (Service A calls Service B), the total availability is:

```
Total availability = Availability_A × Availability_B

Service A: 99.9% available
Service B: 99.9% available
System:    99.9% × 99.9% = 99.8% available

That's not 3 nines — it's less than 3 nines. Each additional service
in the chain multiplies the failure probability.

With 5 services at 99.9% each:
System: 99.9%^5 = 99.5% — almost 2 nines less than each individual service.
```

This is why a RAG pipeline (embedding service → vector DB → LLM API → your application server) has compound availability problems that a monolithic CRUD app doesn't.

### Latency — p50, p90, p99, and Why Tail Latency Is What Matters

Latency is not one number. It's a distribution. Here's why the percentiles matter:

```
Imagine 1,000 requests to your API:
  - 500 complete in under 150ms  (p50 = 150ms — the "median" experience)
  - 900 complete in under 300ms  (p90 = 300ms — most users' experience)
  - 990 complete in under 800ms  (p99 = 800ms — the worst 1%)
  - 999 complete in under 3,000ms (p99.9 = 3,000ms — the worst 0.1%)
```

**p50 (median):** The experience of the "typical" user. This is what product people usually mean when they say "our latency is X."

**p90:** The experience of 9 out of 10 users. If your p90 is bad, a lot of people have a bad experience. This is usually the most useful number for product decisions.

**p99 (tail latency):** The experience of the worst 1%. In a system serving 10,000 requests per second, the p99 represents 100 users *every second* having a bad experience. That's 360,000 bad experiences per hour.

**Why tail latency matters more than you think:**

```
The "fan-out" problem:

A single user page load makes 5 parallel API calls.
Each API call has p99 = 100ms.
The page load completes when the SLOWEST call completes.

Probability that at least one of 5 calls hits the p99:
1 - (0.99)^5 = 4.9%

So ~5% of page loads experience a p99-level delay.
That's not tail latency anymore — it's the common case.

With 20 parallel calls (e.g., an agent making 20 tool calls):
1 - (0.99)^20 = 18.2%

Nearly 1 in 5 agent runs hits a tail-latency event.
```

This is why p99 optimization is not academic — it directly impacts user experience at scale, especially in systems with fan-out (which is exactly what agents and RAG pipelines do).

### Throughput vs Latency — They Compete

Throughput is how many requests your system can handle per unit of time (e.g., 1,000 requests/second).

**The critical insight:** latency and throughput are in tension, not independent.

```
A server that handles 1 request at a time:
  Latency: 10ms per request (fast)
  Throughput: 100 requests/second (low)

The same server handling 50 concurrent requests:
  Latency: 50ms per request (5x worse — contention, queueing)
  Throughput: 1,000 requests/second (10x better)

You don't get both. Pushing throughput up pushes latency up.
This is Little's Law: Concurrency = Throughput × Latency
```

**Why this matters for AI systems:** An LLM API call takes 2-5 seconds. That's 100-500x longer than a typical database query. To maintain the same throughput (requests/second) with 100x longer per-request latency, you need 100x more concurrency (more workers, more connections, more memory). Module 01 already flagged this — now you have the vocabulary to reason about it precisely.

### SLA, SLO, SLI — The Reliability Contract Stack

These three terms are used constantly in production engineering and design discussions. They stack:

**SLI (Service Level Indicator):** The actual measurement. A concrete metric.
```
Examples:
  - "The ratio of successful HTTP requests to total requests" (availability SLI)
  - "The 99th percentile latency of API responses" (latency SLI)
  - "The percentage of LLM responses that pass quality validation" (correctness SLI — AI-specific)
```

**SLO (Service Level Objective):** The target for the SLI. An internal goal.
```
Examples:
  - "99.9% of requests should succeed" (availability SLO)
  - "p99 latency should be under 2 seconds" (latency SLO)
  - "95% of LLM responses should pass quality validation" (correctness SLO — AI-specific)
```

**SLA (Service Level Agreement):** The contract with the customer. A business commitment with consequences (refunds, credits) if violated.
```
Examples:
  - "We guarantee 99.9% uptime. If we miss it, you get a 10% credit."
  - SLAs are always LESS strict than SLOs (you set your internal bar higher
    than what you promise customers, so you have a buffer)
```

**The practical hierarchy:**
```
SLA: 99.9% availability (promised to customers)
SLO: 99.95% availability (internal target — 0.05% buffer)
SLI: actual measured availability over the last 30 days

If SLI drops below SLO → alert, investigate, fix before it hits SLA
If SLI drops below SLA → contractual violation, customer credits, postmortem
```

### Error Budgets — The Counter-Intuitive Insight

If your SLO is 99.9% availability, that means you "budget" 0.1% downtime per month. That's ~43 minutes of allowed downtime per month.

This flips the reliability conversation from "we must never fail" to "we have a budget of 43 minutes of failure per month. How do we spend it?"

```
Error budget remaining: 43 minutes this month

Options:
  a) Spend 10 minutes deploying a risky but high-value feature
  b) Save the budget for unexpected failures
  c) Budget is nearly exhausted → freeze deploys, focus on stability

Error budgets make reliability a quantitative, manageable resource
instead of an infinite, fear-driven mandate.
```

---

## Concrete Example From a Real System

**Google's SRE approach (publicly documented):** Google's Site Reliability Engineering practice (documented in their free SRE book) formalizes error budgets. Teams negotiate SLOs with product owners. As long as the error budget has remaining capacity, engineering teams can deploy freely. When the error budget is consumed, the team must stop feature development and focus on reliability until the budget recovers. This is publicly documented and widely adopted.

**Illustrative AI-specific example:** A RAG product sets these SLOs:
- Availability SLO: 99.9% of requests return a valid response within 10 seconds
- Latency SLO: p99 < 8 seconds
- Quality SLO (novel, AI-specific): 90% of responses score above threshold on automated quality eval

The quality SLO is the new one. In a traditional system, a 200 OK means the request succeeded. In an AI system, a 200 OK might contain a hallucinated, wrong, or irrelevant response. "Availability" as traditionally defined (did the HTTP request succeed?) is necessary but not sufficient. You need a quality SLI that measures whether the response was actually *useful*.

---

## The Tradeoffs

| Reliability level | Engineering cost | When it's appropriate |
|-------------------|-----------------|----------------------|
| 99% (~3.6 days downtime/year) | Low — single server, manual recovery | Internal tools, dev environments |
| 99.9% (~8.7 hours/year) | Moderate — load balancer, health checks, basic monitoring | Most B2B SaaS, non-critical APIs |
| 99.99% (~52 min/year) | High — multi-AZ, automated failover, on-call, comprehensive monitoring | User-facing products, payment systems |
| 99.999% (~5 min/year) | Very high — multi-region, formal verification, dedicated SRE team | Financial systems, healthcare, critical infrastructure |

**The tradeoff between reliability and velocity:** Higher reliability means more safeguards, slower deployments, more testing. This directly competes with speed of feature development. Error budgets are the mechanism for managing this tension — they give you a quantitative answer to "can we afford to ship this risky feature right now?"

---

## How This Connects to Other Modules

- **Module 01** described what "breaks." This module gives you the vocabulary to measure how much breaking is acceptable.
- **Module 02** (Networking) explained the p99 latency floor from cold connections. Now you know why p99 specifically matters.
- **Module 04** (Estimation) estimated QPS and compute. Now you know that those numbers must come with latency targets and availability commitments.
- **Module 06** (Load Balancing) will show how load balancing improves availability by removing SPOFs.
- **Module 18** (Service Communication) will show how circuit breakers and retries protect your SLOs when a dependency fails.
- **Module 25** (Observability) will show how you actually measure SLIs in production.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** The formulas for compound availability and Little's Law are useful to know but you'll look them up when you need them. What you'll use *every single week* is the ability to have a productive conversation about SLOs. "What should the SLO be for this service?" is a question that comes up in every design review, every planning meeting, every incident postmortem. If you can't answer it with a number and a justification for why that number and not a higher one, you're not contributing to the conversation. The answer is almost never "as high as possible" — it's "as high as we need given the cost of getting there and the consequence of missing it." A 99.9% SLO for an internal analytics dashboard is over-engineering. A 99.9% SLO for a payment processing API is under-engineering. The skill is knowing where on the spectrum your system sits.

**The AI-era connection:** LLM-backed systems make every reliability metric harder. Here's the specific scenario: your RAG API depends on OpenAI's API. OpenAI's API has its own availability characteristics — let's generously call it 99.9%. Your system also depends on your vector database (99.95%) and your application servers (99.99%).

```
Your system's theoretical max availability:
99.99% × 99.95% × 99.9% = 99.84%

That's less than 3 nines — 14 hours of downtime per year —
even if YOUR code is perfect, because you depend on a third-party 
LLM API you don't control.
```

Now add the latency dimension. Your p50 latency is dominated by the LLM API response time (~2-4 seconds). You don't control that. It can spike to 10+ seconds during provider-side load spikes. Your p99 is at the mercy of a dependency you cannot optimize. This means:
- Your SLO must account for your dependency's reliability, not just your own.
- You need fallback strategies (Module 18): a cached response, a simpler model, a graceful degradation.
- You need to measure a **quality SLI** — because the LLM can return a 200 OK with a hallucinated garbage response, and traditional availability metrics will say "everything's fine" while your users are getting wrong answers.

**Brutally honest advice:** The blind spot I see in engineers coming from AI/ML backgrounds is treating reliability as a binary — either the system is up or it's down. In production, the system is *always partially degraded*. The database replica is 200ms behind. The cache is 90% warm. The LLM provider's p99 spiked this morning but recovered. One of your 4 servers just restarted and hasn't warmed its local caches yet. The system is "up" but operating at degraded quality/performance. The skill is not building a system that never degrades — it's building a system that degrades gracefully, that you can observe in real time, and that you have SLOs for so you know when the degradation crosses from "normal" to "actionable." If your monitoring only tells you "up" or "down," you're blind to the 90% of reality that lives in between.

---

## Check Your Understanding

1. Your system has three services in series: API gateway (99.99%), RAG service (99.95%), and LLM provider (99.9%). What's the compound availability? How many minutes of downtime per month does this allow?

2. Your API's p50 latency is 200ms and p99 is 4,000ms. A page load makes 8 parallel API calls. What percentage of page loads will experience at least one p99-level delay? Show the math.

3. Your team's SLO is 99.9% availability. It's the 20th of the month and you've had 35 minutes of downtime. Your error budget for the month is ~43 minutes. A teammate wants to deploy a major database migration that risks 15 minutes of downtime. Should you do it? Defend your answer using error budget reasoning.

4. Define an SLI, SLO, and SLA for a RAG-based customer support bot. Include at least one quality-specific SLI that goes beyond traditional availability/latency metrics.

5. Why is tail latency (p99) more important than average latency for AI systems that use agent loops with multiple tool calls? How does fan-out amplify tail latency?
