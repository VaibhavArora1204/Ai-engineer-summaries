# Loop Engineering — What It Actually Is
## What's Actually New vs Rebranded
Let's be direct: the **while loop** is not new. The **cron job** is not new. The skeptics are partially right — @rohit_jsfreaky's "every agent I shipped is a for-loop, an LLM call, and a try/catch around the JSON parsing" is an accurate description of most deployed agents. "Cronjobs have funny re-branding rn" is also fair.
What IS new — genuinely, structurally new — is what sits **inside the loop body**:
| Component | 1975 cron job | 2026 agent loop |
|-----------|--------------|-----------------|
| Decision logic in the body | Hardcoded shell script | A model that reads current state and decides the next action |
| Termination condition | Fixed schedule or exit code | Goal verification — "did the tests pass? did the PR get approved?" |
| Error recovery | Exit 1 and page someone | Model reads the error, diagnoses it, retries with a different approach |
| Concurrency | Sequential or fork/exec | Dispatch sub-agents into isolated worktrees |
| State persistence | Files, database | Git-backed state that survives crashes |
The **loop structure** is ancient. The **decision-maker inside the loop** is not. A loop with a model in the body can read novel state it has never seen before, reason about it, and choose a next action — something no cron job has ever done. That's the genuine innovation. Everything else is familiar infrastructure dressed up.
The term "loop engineering" itself went mainstream in June 2026 when Boris Cherny (creator of Claude Code) said: "I don't prompt Claude anymore. I have loops that are running. They're the ones that are prompting Claude and figuring out what to do. My job is to write loops."
## The Mechanism
A loop is a program that:
```
1. DEFINE a goal (verifiable: tests pass, file produced, PR approved)
2. DEFINE tools the agent can use (bash, file edit, web search, API calls)
3. REPEAT:
   a. Construct context: goal + current state + relevant history
   b. Send to model: "given this state, what should I do next?"
   c. Model returns an action (tool call, file edit, command)
   d. Execute the action in a sandbox
   e. Observe the result (stdout, file diff, test output)
   f. Check termination conditions:
      - Goal met? → EXIT SUCCESS
      - Iteration cap hit? → EXIT TIMEOUT
      - Token budget exhausted? → EXIT BUDGET
      - No progress detected? → EXIT STALL
      - Error unrecoverable? → EXIT FAILURE
   g. If not terminated: feed observation back into context, go to (a)
```
Five parts, none optional:
1. **Goal definition** — clear, ideally machine-verifiable. "Fix the auth bug" is bad. "Make `pytest tests/test_auth.py` pass" is good. A fuzzy goal never knows when to stop.
2. **Tools/actions** — what the agent can do each iteration. Bash + filesystem is the highest-leverage general-purpose toolset.
3. **Observation** — how the result of each action is fed back. Structured output (exit code + stderr) beats raw 10,000-line dumps.
4. **Termination logic** — the most critical and most commonly missing piece. Without it, you have AutoGPT (2023): spinning forever doing nothing.
5. **Error handling** — what happens when a step fails. Does the loop recover, or does it compound the mistake across every subsequent iteration?
## The Primary Source Evidence
**Boris Cherny's evolution ladder** (WorkOS Acquired Unplugged, June 2, 2026):
| Stage | What he did | His role |
|-------|-------------|---------|
| 1. Autocomplete | Wrote code by hand with AI suggestions | Typist |
| 2. Parallel sessions | Ran 5-10 Claude sessions, prompted each | Prompt operator |
| 3. Loops | Writes loops; agents read GitHub, Slack, Twitter and decide what to build | Loop engineer |
The receipt: In the 30 days before December 27, 2025, Boris reported that 100% of his contributions to Claude Code were written by Claude Code — 259 PRs landed. He deleted his IDE in November 2025 and has not opened it since.
**The five-stage lineage:**
1. **ReAct (2022)** — arXiv:2210.03629. Formalized reason-act-observe. One model, one loop, human watching. Every loop still uses this cycle.
2. **AutoGPT (2023)** — Gave an agent a goal and let it prompt itself. Famous for spinning forever. The cautionary tale: a goal without verifiable termination logic is a toy.
3. **The ralph loop (July 2025)** — Geoffrey Huntley. `while :; do cat PROMPT.md | claude ; done`. Innovation wasn't orchestration — it was discipline: fixed anchor files, progress on disk, one unit of work per iteration. Built "Cursed" (an esoteric programming language) for $297 in API costs.
4. **Productized ralph — `/goal` (spring 2026)** — Claude Code and Codex shipped `/goal`: ralph as a product feature, not a bash script.
5. **Orchestration loops (2026)** — Multiple agents, parallel sub-loops, cron scheduling, git-backed durability. Steve Yegge's Gas Town coordinates 20-30 Claude Code instances via a "Mayor" agent.
## The Failure Mode
Without explicit loop engineering, you get **AutoGPT syndrome**: the agent runs indefinitely, burns tokens, accomplishes nothing, and the engineer discovers the damage hours later when the API bill arrives.
Concrete example from the lineage: AutoGPT (2023) became the fastest-growing GitHub repo in history, then became synonymous with failure. It gave an agent a goal and let it self-prompt with no iteration cap, no progress detection, no structured termination. The model would spin in circles — planning to plan, revising its plan to revise the plan — because nothing in the system said "you've done enough" or "you're going nowhere."
Ralph (2025) solved this not with better models or more complex orchestration, but with discipline: fixed context per iteration (no context drift), one unit of work per tick (no compound errors), progress persisted to disk and git (no state loss). The fix was structural, not intellectual.
## What a Senior Engineer Should Internalize
You are no longer the person inside the loop typing prompts and reading outputs. You are the author of the loop — the person who decides what the agent observes, what tools it has, what "done" means, and what happens when it fails. The model is a subroutine. Your job is to write the `while` condition, the observation function, the termination predicate, and the error handler. Everything else — the actual reasoning, code writing, debugging — is delegated to the model inside the loop body. The skill that matters is not "how do I prompt better" but "how do I design a control system that converges to a correct outcome and provably stops."
