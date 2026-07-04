# 31 — Case Study: Multi-Agent Orchestration System

## Requirements Clarification

**Functional:**
- A "Mayor" orchestrator agent receives a complex user task (e.g., "Research competitor pricing, build a comparison table, and draft a report").
- The Mayor decomposes the task into sub-tasks and assigns them to specialized worker agents (Web Crawler Agent, Data Analyst Agent, Writer Agent).
- Worker agents execute independently, potentially calling tools (web search, code execution, database queries).
- The Mayor aggregates results and produces a final output.

**Non-Functional:**
- Tasks may run for 10 seconds to 10 minutes. Some run for hours (multi-step research).
- At most one worker should process each sub-task (no duplicates).
- If a worker hangs (infinite loop, LLM gets stuck), the system must detect and recover.
- Token/cost budget enforcement: a single task should not spend more than $X without approval.
- Full observability: trace every tool call, every LLM decision, every sub-agent invocation.

---

## Back-of-Envelope Estimation

```
Users: 1,000 concurrent users submitting tasks.
Tasks/user: 5 per day = 5,000 tasks/day.
Sub-tasks per task: avg 4 = 20,000 sub-tasks/day.
QPS: 20K / 86,400 ≈ 0.23 sub-tasks/second average.

But each sub-task holds resources for 30-120 seconds:
  Concurrent sub-tasks: 0.23 × 60 (avg duration) = ~14 concurrent.
  Peak (3x): ~42 concurrent sub-task executions.

LLM cost per task:
  Orchestrator reasoning: ~3 LLM calls × 2,000 tokens each = 6,000 tokens
  Worker agents: 4 workers × 3 LLM calls × 3,000 tokens = 36,000 tokens
  Total: ~42,000 tokens per task
  At $5/M input + $15/M output (mix): ~$0.50 per task
  5,000 tasks/day: $2,500/day = $75K/month

  Budget enforcement is critical. One runaway agent loop generating 500 LLM
  calls can cost $50+ on a single task.

Infrastructure:
  42 concurrent sub-tasks, each holding a worker process.
  With async Python (FastAPI + asyncio): 4-8 server instances.
  Queue depth: typically 0-10 messages, spikes to 50-100.
```

---

## High-Level Design

```
User → API → Task Orchestrator (Mayor)
                    ↓
              Task Queue (SQS/RabbitMQ)
                    ↓
        ┌───────────┼───────────┐
        ↓           ↓           ↓
   Worker Agent  Worker Agent  Worker Agent
   (Crawler)     (Analyst)     (Writer)
        ↓           ↓           ↓
   Tool Calls    Tool Calls    Tool Calls
   (Web, DB)     (Code Exec)   (LLM Gen)
        ↓           ↓           ↓
              Results Queue
                    ↓
              Task Orchestrator
                    ↓
              Final Response → User
```

### The Request Flow

1. **User submits task** via API. The API creates a `task` record in Postgres (status: "planning").
2. **Orchestrator (Mayor) plans:** Calls an LLM to decompose the task into sub-tasks. Creates sub-task records in Postgres and publishes them to the Task Queue.
3. **Workers pull sub-tasks** from the queue. Each sub-task message includes the sub-task ID, the agent type, the instructions, and the parent task ID.
4. **Workers execute:** Each worker runs its agent loop (LLM reasoning → tool calls → LLM reasoning → ...). Workers publish their results to a Results Queue (or write directly to Postgres).
5. **Orchestrator aggregates:** Once all sub-tasks for a task are complete, the orchestrator calls the Writer Agent (or uses an LLM directly) to synthesize the results.
6. **Response delivered:** Via SSE stream or stored for async retrieval.

---

## Deep Dive: The Genuinely Hard Parts

### 1. Task Assignment — A Distributed Lock / Queue Problem (Callback to Module 21)

**The problem:** Two workers must not pick up the same sub-task.

**Solution: Use the queue's built-in mechanism.**
SQS Visibility Timeout and RabbitMQ's ACK mechanism solve this:
- Worker A receives message "sub-task-42" from SQS. The message becomes invisible for 300 seconds (visibility timeout = task TTL).
- No other worker can see the message during this window.
- Worker A processes the sub-task and calls `DeleteMessage`. Done.
- If Worker A crashes, the visibility timeout expires, and the message reappears for another worker.

This is simpler and more reliable than explicit distributed locks for task assignment.

**Extending the lease for long tasks:**
Agent tasks can run for 10+ minutes. The default visibility timeout might be 5 minutes. The worker must periodically extend it:
```python
while agent_is_still_running:
    sqs.change_message_visibility(receipt_handle, VisibilityTimeout=300)
    await asyncio.sleep(240)  # Extend every 4 minutes
```
This is exactly the "heartbeat" pattern from Module 21.

### 2. Runaway Agent Detection — Circuit Breakers for Agents (Callback to Module 18)

**The nightmare:** A worker agent enters a reasoning loop. The LLM keeps calling tools, getting results, and deciding it needs more information. 50 LLM calls later, the task has consumed $25 and is still running.

**Defense layers:**

1. **Token budget per sub-task:** Before each LLM call, check cumulative tokens used. If over budget, force-stop and return a partial result.
   ```python
   if self.total_tokens > self.token_budget:
       return "BUDGET_EXCEEDED: Partial result with findings so far..."
   ```

2. **Step counter:** Maximum number of agent steps (LLM calls + tool calls). Typical limit: 15-25 steps.
   ```python
   if self.step_count > self.max_steps:
       return "MAX_STEPS_EXCEEDED: ..."
   ```

3. **Wall-clock timeout:** Kill the agent after N minutes regardless of progress.
   ```python
   async with asyncio.timeout(600):  # 10 minutes max
       result = await agent.run(sub_task)
   ```

4. **Cost circuit breaker:** If the total cost of a parent task exceeds a threshold, pause all sub-tasks and notify the user for approval before continuing.

### 3. State Management for Long-Running Tasks

Agent tasks are not request-response. They're workflows that can run for minutes or hours. The state cannot live in memory (the server might restart).

**Pattern: Externalized State Machine**

```python
# Task states
class TaskState(Enum):
    PLANNING = "planning"
    SUBTASKS_QUEUED = "subtasks_queued"
    IN_PROGRESS = "in_progress"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_PAUSED = "budget_paused"

# Postgres stores the state
class Task(Model):
    id: uuid
    user_id: int
    state: TaskState
    plan: json  # The decomposed sub-tasks
    results: json  # Aggregated results from workers
    total_tokens: int
    total_cost_usd: float
    created_at: datetime
    updated_at: datetime
```

Each worker reads the task state from Postgres at the start, executes, and writes the updated state back. If the worker crashes mid-execution, the task is in the last committed state, and a new worker can resume or retry.

### 4. Tracing Non-Deterministic Execution Paths (Callback to Module 25)

Traditional distributed tracing assumes a fixed call graph. Agent traces are non-deterministic:

```
Task "Research competitors"
├── [Mayor] Planning (LLM call #1) → decided on 3 sub-tasks
├── [Sub-task 1: Crawler] 
│   ├── LLM decides to search "competitor A pricing"
│   ├── Tool: web_search("competitor A pricing") → 5 results
│   ├── LLM decides to read top 2 results
│   ├── Tool: read_url("https://...") → content
│   ├── Tool: read_url("https://...") → content  
│   └── LLM summarizes findings
├── [Sub-task 2: Crawler]
│   ├── LLM decides to search "competitor B pricing"
│   └── ... (different tool call pattern than sub-task 1)
├── [Sub-task 3: Analyst]
│   ├── LLM decides to write Python code for comparison
│   ├── Tool: code_exec(comparison_script) → error
│   ├── LLM debugs, writes new code
│   ├── Tool: code_exec(fixed_script) → results
│   └── LLM formats results
└── [Mayor] Aggregation (LLM call #N) → final report
```

**Instrumentation requirements:**
- Each agent step is a **span** with: step index, LLM model used, prompt (truncated), response, tokens consumed, cost, tool name (if tool call), tool result (truncated).
- The parent task ID is the **trace ID** propagated to all sub-tasks.
- Agent "decision" spans capture WHY the agent chose a particular tool — this is the data you need for prompt engineering improvements.

---

## Bottlenecks and Fixes

| Bottleneck | Trigger | Fix |
|-----------|---------|-----|
| Duplicate task processing | Worker crash + retry | Queue visibility timeout (built-in lease) |
| Runaway agent (cost) | Infinite reasoning loop | Token budget + step counter + wall-clock timeout |
| Lost state on crash | In-memory state, worker dies | Externalize state to Postgres |
| Hard to debug agent behavior | Non-deterministic paths | Step-level tracing with decision spans |
| Connection pool exhaustion | Long-running agent holds DB connection | Release connection between LLM calls (Module 30's lesson) |
| Slow task completion | Sequential sub-tasks | Parallelize independent sub-tasks via queue |

---

## Mentor's Take — What Actually Matters Here

**What matters:** This case study reveals that agent orchestration is not an AI problem — it's a distributed systems problem wearing an AI costume. Task queuing, lease management, idempotent task execution, state machines, circuit breakers, tracing — you've seen all of these in the previous 30 modules. The "agent" part (the LLM deciding what to do) is a function call inside a distributed workflow engine.

**The AI-era connection:** This IS the bleeding edge. Most agent orchestration systems in production today are hand-rolled state machines with `if/else` branching (CrewAI, AutoGen, LangGraph). They work for demos. They fail in production because they don't have: queue-based task distribution, lease-based timeout management, cost circuit breakers, or externalized state. Building a production-grade agent orchestrator is building a miniature Kubernetes-for-AI-tasks — and it requires the same distributed systems engineering discipline.

**Brutally honest advice:** Do not build a multi-agent system until you've maxed out what a single agent with good tools can do. Most "multi-agent" demos are solving problems that a single well-prompted agent with 4-5 tools handles better, faster, and cheaper. The overhead of orchestration (planning, coordination, aggregation) adds latency, cost, and failure modes. Multi-agent architectures are justified when sub-tasks have genuinely different resource requirements (one needs GPU, another needs web access, another needs code execution) or when parallelism provides a meaningful speedup. If you can't explain why the task can't be done by one agent, you don't need multiple agents.

---

## Check Your Understanding

1. A worker agent is processing sub-task #42. It crashes after completing the LLM call but before writing results to Postgres and ACKing the queue message. What happens to the sub-task? Is the LLM cost wasted?

2. An agent enters a loop: Search → Read → "I need more information" → Search → Read → "I need more information" → ... Design a detection mechanism that stops this loop without a hard step limit.

3. Your orchestrator assigns 4 sub-tasks to workers in parallel. Sub-tasks 1, 2, and 3 complete successfully. Sub-task 4 fails because the web search tool returned an error. What should the orchestrator do? (Consider: should it retry sub-task 4? Should it ask the Mayor LLM to re-plan? Should it return a partial result?)

4. Explain why agent orchestration makes connection pool exhaustion (Module 30) even worse than a standard RAG pipeline, considering that an agent might make 5-10 sequential LLM calls per sub-task.

5. Your agent system costs $0.50 per task on average, but 2% of tasks cost over $5 due to runaway loops. What is the impact on monthly costs at 5,000 tasks/day, and how does a cost circuit breaker change this?

---

### Answers

1. **Answer:** The queue visibility timeout expires, and the message becomes visible again. Another worker picks up sub-task #42 and processes it from scratch. Yes, the original LLM cost is wasted — the tokens were consumed but the result was lost. To mitigate: the worker should write intermediate results to Postgres (or Redis) BEFORE the LLM call returns, so if it crashes, the next worker can check for cached intermediate results (similar to the idempotency pattern in Module 24, but for partial work).

2. **Answer:** Track the semantic similarity of consecutive search queries. If the agent's last 3 searches are >0.90 similar to each other (it's rephrasing the same question), it's looping. Alternatively, maintain a set of URLs already visited — if the agent tries to read the same URL twice, intercept and return "You've already read this page. Summarize your current findings." These heuristic detections supplement the hard step limit as a smarter, earlier intervention.

3. **Answer:** The orchestrator should implement a retry policy first (retry sub-task 4 with exponential backoff, up to 3 times). If retries fail, it should ask the Mayor LLM to re-evaluate: "Sub-task 4 (web search for competitor C) failed after 3 retries. Do you want to: (a) skip this sub-task and produce a partial report noting the gap, (b) reformulate the sub-task with a different approach?" The Mayor decides based on the task requirements. A partial result with a gap note is usually better than failing the entire task.

4. **Answer:** A standard RAG request holds a connection for one retrieval + one LLM call (~20ms retrieval + 4s LLM = 4s total if you DON'T release). An agent sub-task makes 5-10 sequential LLM calls, each taking 3-5 seconds. Total: 15-50 seconds of execution. If the code holds a DB connection for the entire sub-task, one sub-task occupies a connection for 50 seconds instead of 4. At 42 concurrent sub-tasks × 50 seconds, you need 42 connections held simultaneously. This exhausts a standard pool. The fix (Module 30) is even more critical here: acquire and release the connection for each individual database operation within the agent loop, not for the entire sub-task.

5. **Answer:** Normal costs: 5,000 × $0.50 = $2,500/day = $75K/month. Runaway costs: 2% of 5,000 = 100 tasks/day at $5+ average (conservatively $10). That's $1,000/day extra = $30K/month. Total: $105K/month, with $30K wasted on runaway tasks. A cost circuit breaker at $2/task would catch the runaways after they've consumed $2, saving ~$800/day ($24K/month). The circuit breaker pays for itself on day one.
