# 03 — Harness Engineering: ETCLOVG


## What's Actually New vs Rebranded
Let's separate the genuinely new from the relabeled:
**Rebranded (not new):**
- "Execution controls" → process isolation, containerization, sandboxing. This is Docker and chroot and seccomp, circa 2013.
- "Tooling" → API integrations. This is middleware, SDKs, and RPC. Decades old.
- "Governance" → access control, audit logging, compliance. Every enterprise system has this.
**Genuinely new:**
- **The coupling insight:** "Real-world reliability is shaped by execution controls, feedback loops, governance, and operational design — not only by model capability." This reframes the entire optimization target. Before this, the default assumption was: make the model smarter → system gets better. The harness survey's data says: 65% of enterprise AI failures trace to harness defects, not model deficits. That is a genuinely new empirical finding that changes how you allocate engineering effort.
- **Harnesses as assumptions about model weakness:** Anthropic's explicit statement: "Harnesses encode assumptions about what Claude can't do on its own. However, those assumptions need to be frequently questioned because they can go stale as models improve." No prior engineering discipline has had to deal with the fact that the component you're building guardrails around is improving underneath you on a quarterly basis.
- **Self-improving harnesses:** The NexAU substrate — representing harness components as file-level artifacts so another agent can operate on the harness itself — is genuinely novel. There is no equivalent in traditional software engineering.
**The honest framing:** The seven-layer taxonomy (ETCLOVG) is a useful checklist, but individually, most layers are traditional software infrastructure applied to a new runtime (LLMs). The novelty is in the **system-level interaction** between these layers and the fact that the central component (the model) is non-deterministic, improving, and capable of operating on the harness itself.
## The Mechanism
### The ETCLOVG Seven-Layer Taxonomy
From "Agent Harness Engineering: A Survey" (2026):
```
STRUCTURAL CORE (what the harness IS):
  E — Execution:   How agent actions run (sandbox, container, permissions)
  T — Tooling:     What actions the agent can take (bash, MCP servers, APIs)
  C — Context:     What information enters the model's attention budget
  L — Lifecycle:   How the agent starts, runs, pauses, resumes, terminates
CONTROL PLANE (how you GOVERN the harness):
  O — Observability: Can you trace a failure? Logging, metrics, traces.
  V — Verification:  Is the output correct? Tests, validators, human review.
  G — Governance:     Who authorized this action? Audit trail, compliance, permissions.
```
"The first four describe the structural core of a harness; the last three describe the control plane around it."
### The Practitioner's Seven Components (simpler framing, same substance)
```
1. Control loop    → The plan-act-observe cycle. Decides "done" or "next action."
2. Tools           → Bash + filesystem = highest leverage general-purpose tools.
                     MCP servers extend to specialized systems.
3. Memory          → Durable storage outside the context window.
                     Files, AGENTS.md, memory stores.
4. Context mgmt    → Compaction, summarization, progressive disclosure.
                     This is where harness engineering CONTAINS context engineering.
5. Sandbox         → The isolated execution environment.
                     Agent mistakes can't damage the host machine.
6. Permissions     → What the agent can do autonomously vs needs human approval.
                     The line between automation and human-in-the-loop.
7. Observability   → Can you trace every decision, tool call, and token expenditure?
                     If you can't trace a failure, you can't improve the harness.
```
### How These Seven Interact (the dependency chain most people miss)
```
Observability feeds back into every other layer:
  Control loop stalling?    → Observability shows no-progress iterations
  Wrong tool being called?  → Observability traces tool selection decisions
  Context rotting?          → Observability tracks token counts and quality scores
  Sandbox breached?         → Observability logs unauthorized access attempts
  Permission too loose?     → Observability shows which autonomous actions failed
Without observability, you're flying blind. Every other layer is unimprovable
because you can't diagnose what's going wrong.
```
## The Primary Source Evidence
**The 65% finding:** "The most significant finding in recent deployments is that raw reasoning deficits are rarely the cause of project failure. Strong evidence shows that 65% of enterprise AI failures trace back to Harness Defects — specifically Context Drift, Schema Misalignment, and State Degradation. Optimizing the model without stabilizing the harness yields diminishing returns."
Breakdown of the three harness defect types:
- **Context Drift:** The model's working memory degrades over a long session — critical information from early turns gets lost, overwritten, or ignored
- **Schema Misalignment:** The model's output doesn't match what the downstream system expects — JSON fields are wrong, formats shift, tool calls use deprecated signatures
- **State Degradation:** The persistent state the harness maintains (files, databases, memory stores) becomes inconsistent — the agent edits a file but the harness's cache still reflects the old version
**The build vs buy principle:** "Build a harness when your workflow is unusual enough that no existing one fits; buy (or adopt) a managed one otherwise." And critically: treat harness development like CI for agents — "a benchmark of representative tasks that re-runs on every harness change, so a tweak that lifts one metric can't silently wreck another."
## The Failure Mode
Without a harness, you have a model in a notebook. It can answer questions. It cannot:
- Remember what it did yesterday
- Run code safely without destroying your environment
- Recover from its own mistakes
- Be audited after the fact
- Be improved systematically
**Concrete failure from the source material:** Anthropic started with all agent components in a single container — session, harness, and sandbox sharing an environment. File edits were direct syscalls, which was fast and simple. But when the container failed, they lost state for every "hand" the brain was reaching into. They had "adopted a pet" — a single point of failure that combined state, execution, and control in one fragile unit.
The fix required decomposing the harness into three independent components (Session, Harness, Sandbox) connected by `execute(name, input) → string` interfaces. This is the standard distributed systems playbook: decouple components, define clean interfaces, make each independently replaceable.
## What a Senior Engineer Should Internalize
A harness is a record of your model's current weaknesses. Every guardrail, every context management rule, every permission boundary exists because the model couldn't be trusted to handle that aspect on its own at the time the guardrail was written. The critical operational discipline is that as models improve, parts of your harness become dead weight or actively harmful — Anthropic discovered that context resets built for Sonnet 4.5's "context anxiety" became unnecessary overhead on Opus 4.5. You must re-evaluate your harness against every model upgrade. The harness is not a static artifact you ship and forget. It is a living, co-evolving system that must be tested against the model it wraps, continuously.
