# Loop Implementation — From Ralph to Orchestration
## What's Actually New vs Rebranded
Ralph — `while :; do cat PROMPT.md | claude ; done` — is literally a bash while loop piping stdin to a CLI. This is not new technology. It is a 1970s Unix idiom applied to a 2025 tool. The skeptics are right to point this out.
What's new is the **progression from ralph to `/loop` to orchestration loops**, which represents a genuine architectural evolution:
| Feature | Ralph (bash, 2025) | `/goal` (product, 2026) | Orchestration (Gas Town, 2026) |
|---------|-------------------|------------------------|-------------------------------|
| Scheduling | Human types `bash run.sh` | Human types `/goal` | Cron, infrastructure, autonomous |
| Context | Reset every tick (PROMPT.md) | Managed by product (compaction, memory) | Per-agent context isolation |
| Concurrency | None (sequential pipe) | Single agent | 20-30 parallel agents |
| State persistence | Disk + git (manual) | Built-in session management | Git-backed, crash-recoverable |
| Termination | Agent exits, loop restarts | Validator confirms goal met | Mayor agent decides |
| Error recovery | Hope the next iteration works | Built-in retry | Patrol agents monitor and reassign |
The jump from ralph to orchestration loops is real engineering: it requires distributed state management, agent-to-agent communication, workload scheduling, and failure recovery. This is not a cron job in a hat — it is a distributed system where the workers happen to be LLMs.
## The Mechanism
### Level 1: Ralph (Minimal Viable Loop)
```bash
#!/bin/bash
# ralph.sh — the simplest possible agent loop
# Innovation: discipline, not complexity
while :; do
    # 1. Context is ALWAYS reset to anchor files (no context drift)
    cat PROMPT.md | claude --print
    
    # 2. Agent does one discrete unit of work
    #    Progress lives on DISK (files, git), not in conversation
    #    Agent reads disk state, picks next task, does it, commits
    
    # 3. Implicit termination: human watches, hits Ctrl+C
    #    Better: check git log for "DONE" commit message
done
```
**Why it works despite being trivial:** Every iteration starts from zero context. The model reads the current state of the project from disk (not from a growing conversation window), picks the next task, does it, and exits. There is no context rot because there is no accumulating context. There is no goal drift because PROMPT.md re-anchors the goal every tick.
**Huntley's actual setup for building "Cursed":**
- `PROMPT.md` — the specification, the current state, what to do next
- `AGENTS.md` — agent-specific instructions (how to use the CLI, how to run tests)
- Progress tracked in git commits
- Cost: ~$297 total for a complete esoteric programming language
### Level 2: `/goal` and `/loop` (Productized Loop)
Claude Code's `/loop` is ralph with first-class product support:
```
/loop 5m /babysit
```
This means: every 5 minutes, run the `/babysit` command (which auto-addresses code review comments, rebases PRs). The loop manages:
| Feature | How it works |
|---------|-------------|
| Fixed intervals | `/loop 5m check the deploy` — poll every 5 minutes |
| Dynamic intervals | `/loop check the deploy` — Claude picks 1 min to 1 hour based on observed state |
| Custom behavior | `loop.md` file in your project overrides the default maintenance prompt |
| Termination | Press Esc while waiting; or the agent decides the goal is met |
| Sub-agent dispatch | The loop body can spawn worktree-isolated sub-agents for parallel work |
**Real `/loop` commands from the source material:**
| Command | What it does |
|---------|-------------|
| `/loop 5m /babysit` | Auto-address code review, rebase PRs every 5 minutes |
| `/loop 30m /slack-feedback` | Put up PRs for Slack feedback on a 30-minute cadence |
| `/loop 5m check the deploy` | Poll deploy status on a fixed interval |
| `/loop babysit all my PRs` | Maintain all open PRs indefinitely, dispatching sub-agents for each comment |
### Level 3: Orchestration Loop (Gas Town)
Steve Yegge's Gas Town (January 2026, open source) coordinates 20-30 Claude Code instances:
```
Architecture:
  Mayor Agent (orchestrator)
  ├── reads GitHub issues, Slack messages, deployment status
  ├── decides what needs doing
  ├── assigns tasks to Worker Agents (each in its own worktree)
  ├── Patrol Agents run continuous monitoring loops
  └── all state stored in git (crash recovery)
Mechanism:
  1. Mayor reads current project state (GitHub, Slack, CI)
  2. Mayor decides: "Issue #47 needs fixing, PR #23 needs rebasing, 
     deploy is failing on staging"
  3. Mayor dispatches:
     - Worker A → fix issue #47 (in worktree A)
     - Worker B → rebase PR #23 (in worktree B)
     - Worker C → debug staging deploy (in worktree C)
  4. Workers report back via git commits
  5. Patrol agents run continuous loops checking for regressions, 
     stale PRs, build failures
  6. If a worker stalls or fails, Mayor reassigns the task
  7. All of this survives a crash because state is in git, not memory
```
## The Primary Source Evidence
**Ralph's cost-efficiency:** Huntley built Cursed for $297 in API costs. The efficiency comes from context discipline — no context window accumulation means no paying for stale tokens.
**Boris Cherny's production numbers:** 259 PRs landed in 30 days, 100% written by Claude Code running in loops. This is not a demo — this is the creator of Claude Code eating his own cooking at production scale.
**The transition moment:** Boris explicitly describes three stages of his own evolution — typist → prompt operator → loop engineer. The shift to loop engineering happened when he "deleted his IDE in November 2025 and has not opened it since." The loop replaced the IDE as the primary interface.
## The Failure Mode
**Ralph without anchor files → AutoGPT failure.** If you remove the fixed `PROMPT.md` reset and let the loop accumulate conversation context across iterations, you get:
1. **Context rot** — the conversation grows, quality degrades, the model starts ignoring earlier instructions
2. **Goal drift** — without re-reading the original specification every tick, the model slowly wanders off-task
3. **Token explosion** — each iteration costs more because it includes all prior history
Ralph's key insight: progress lives on **disk** (git commits, file changes), not in the conversation. Each iteration re-reads the ground truth from disk. The conversation is disposable.
**Orchestration without termination → runaway cost.** Gas Town without patrol agents and the Mayor's oversight would be 30 agents burning tokens with no coordination. The Mayor agent is the termination logic for the entire system.
## What a Senior Engineer Should Internalize
The implementation sophistication ladder — ralph → `/loop` → orchestration — maps directly to how much state management you need. Ralph needs none (stateless iterations, git is the state). `/loop` needs some (session persistence, dynamic intervals). Orchestration loops need a full distributed state system (agent coordination, task assignment, failure recovery). Pick the lowest level that solves your problem. Most tasks that feel like they need orchestration actually need ralph with good anchor files. The overhead of multi-agent coordination is only justified when the problem genuinely decomposes into parallel, independent sub-tasks — and even then, the Mayor pattern (one coordinator reading shared state) is simpler and more debuggable than peer-to-peer agent communication.
