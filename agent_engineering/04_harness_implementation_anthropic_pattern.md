# Harness Implementation — Anthropic's Production Pattern
## What's Actually New vs Rebranded
**Rebranded:** Session/Harness/Sandbox is the standard three-tier architecture (presentation/logic/data) applied to agents. The interface `execute(name, input) → string` is a remote procedure call. None of this is architecturally novel.
**Genuinely new:**
1. **"Decoupling the brain from the hands"** — the insight that the harness should not know what kind of sandbox it's talking to. A phone, a container, a Pokémon emulator — the harness doesn't care. This enables brains to pass hands to one another, which is a prerequisite for multi-agent systems where agents can delegate tools to each other.
2. **The harness staleness problem** — "Harnesses encode assumptions about what Claude can't do on its own. Those assumptions need to be frequently questioned because they can go stale as models improve." This is a genuinely new operational concern with no equivalent in traditional infrastructure. Your nginx config doesn't get smarter every quarter.
3. **Self-improving harnesses (NexAU)** — the idea that harness components should be structured as file-level artifacts so an optimizer agent can inspect, diagnose, and edit them. This is the first serious attempt at meta-agentic infrastructure.
## The Mechanism
### Anthropic's Three-Piece Architecture
From "Scaling Managed Agents" (2026), Anthropic's engineering blog:
```
┌─────────────────────────────────────────────────────────┐
│                      SESSION                             │
│  Append-only log of everything that happened.           │
│  Tool calls, model outputs, observations, timestamps.   │
│  The single source of truth for replay and debugging.   │
└──────────────────────┬──────────────────────────────────┘
                       │ reads/writes
┌──────────────────────▼──────────────────────────────────┐
│                      HARNESS                             │
│  The loop that:                                         │
│  1. Calls Claude with current context                   │
│  2. Receives Claude's response (tool call or text)      │
│  3. Routes tool calls to the appropriate Sandbox        │
│  4. Feeds results back to Claude                        │
│  5. Decides: continue, compact context, or terminate    │
└───────────┬─────────────────┬───────────────────────────┘
            │                 │
   ┌────────▼──────┐  ┌──────▼────────┐
   │   SANDBOX A   │  │   SANDBOX B   │
   │  (container)  │  │   (phone)     │
   │               │  │               │
   │ execute(name, │  │ execute(name, │
   │  input)→str   │  │  input)→str   │
   └───────────────┘  └───────────────┘
```
**The interface contract:** Every sandbox exposes exactly one method: `execute(name, input) → string`. The harness doesn't know what's behind this interface. It could be:
- A Docker container running bash commands
- A phone simulator running UI tests
- A browser automation tool
- A Pokémon emulator (Anthropic's actual example)
**Because no hand is coupled to any brain, brains can pass hands to one another.** Agent A can say "here, use this sandbox" to Agent B. This is the foundation for multi-agent tool sharing.
### Why Single-Container Failed (The "Adopted a Pet" Problem)
Anthropic's first architecture: all three components (session, harness, sandbox) in one container.
```
BEFORE (monolith):
  ┌─────────────────────────────┐
  │  Container                  │
  │  ├── Session state          │
  │  ├── Harness loop           │
  │  └── Sandbox (bash, files)  │
  │                             │
  │  File edits = direct syscalls (fast!)  │
  │  BUT: container dies = everything dies │
  └─────────────────────────────┘
AFTER (decomposed):
  Session  ←→  Harness  ←→  Sandbox(es)
  (durable)    (stateless)  (replaceable)
  
  Each component independently:
  - scalable
  - replaceable
  - crash-recoverable
```
**The cost of decomposition:** Network latency for every tool call. File edits that were direct syscalls now go over an RPC boundary. But the benefit — fault isolation, crash recovery, multi-sandbox support — is worth it at production scale.
### The Context Anxiety Discovery
```
Model: Claude Sonnet 4.5
Symptom: As context approached window limit, model would
         "wrap up" tasks prematurely — declaring done before
         actually finishing.
Harness fix: Context resets (compaction + reinitiation with summary)
Model: Claude Opus 4.5
Same harness, same fix applied
Symptom: Context resets now unnecessary — Opus didn't exhibit
         context anxiety. The resets added overhead with no benefit.
Lesson: The context reset was a Sonnet-specific workaround that
        became dead weight on Opus. The harness must be re-evaluated
        against every model upgrade.
```
### The Self-Improving Harness (NexAU Pattern)
From "Agentic Harness Engineering" (2026):
```
Traditional harness:
  One tangled blob. System prompt + tool descriptions + tool implementations + 
  middleware + memory + skills + sub-agent routing. 
  If a run fails, you can't tell what caused it.
NexAU substrate:
  Seven independently inspectable file-level artifacts:
  ├── system_prompt.md          (inspectable, editable)
  ├── tool_descriptions.yaml    (inspectable, editable)
  ├── tool_implementations/     (inspectable, editable)
  ├── middleware_policies.yaml   (inspectable, editable)
  ├── memory_store/             (inspectable, editable)
  ├── skills/                   (inspectable, editable)
  └── sub_agent_routing.yaml    (inspectable, editable)
Optimizer agent:
  1. Runs the harness on a benchmark task suite
  2. Observes: which runs failed? Where did they fail?
  3. Traces failure to a specific component (e.g., tool description 
     was misleading, memory entry was stale)
  4. Proposes edit to that specific component
  5. Re-runs benchmark to verify edit improved results
  6. Commits if improved, reverts if not
```
The bottleneck is not agent capability — it's **observability**. If the harness is a tangled blob, no optimizer (human or agent) can attribute a failure to the right component.
## The Primary Source Evidence
**The "adopted a pet" quote:** Anthropic's own characterization of their monolithic container architecture. They explicitly describe the failure mode: "when the container failed, they lost state for every 'hand' the brain was reaching into."
**The interface principle:** "We're opinionated about the shape of these interfaces, not about what runs behind them." This is Anthropic stating that the interface contract (`execute(name, input) → string`) is the stable surface, while everything behind it is expected to change.
**The staleness principle:** "A common thread across this work is that harnesses encode assumptions about what Claude can't do on its own. However, those assumptions need to be frequently questioned because they can go stale as models improve." This is stated as a general principle, backed by the specific context-anxiety example.
## The Failure Mode
Without this architecture:
1. **Single container failure** → lose everything. No crash recovery, no session replay.
2. **Coupled brain and hands** → agents can't share tools. Every agent needs its own full sandbox setup. Multi-agent coordination requires duplicated infrastructure.
3. **Stale harness** → guardrails built for Sonnet persist when running Opus. The harness adds overhead that the model no longer needs, or worse, the guardrails interfere with capabilities the new model has but the harness suppresses.
The stale-harness problem is the most insidious because it's invisible. Your system works, but it works worse than it could because you're carrying dead weight from a weaker model generation. You only discover this if you systematically re-benchmark your harness against each new model.
## What a Senior Engineer Should Internalize
The Anthropic pattern is the standard three-tier architecture (durable log, stateless orchestrator, replaceable execution) applied to LLM agents. The implementation is not novel. What is novel is the operational discipline it demands: because the central component (the model) improves on a quarterly cadence, the harness around it is not a build-once artifact. It is a continuously re-evaluated set of assumptions about model weakness. Every harness component should have a comment: "this exists because the model can't do X on its own as of [date]." When the model can do X, remove the component. If you don't do this, your harness becomes a museum of obsolete workarounds, each one adding latency, cost, and complexity without contributing reliability.
