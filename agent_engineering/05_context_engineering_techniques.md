# Context Engineering — Techniques
## What's Actually New vs Rebranded
**Rebranded:**
- "Context engineering" as a term is Andrej Karpathy's rebranding of what RAG engineers and prompt engineers have been doing for two years: deciding what goes into the model's input. The practice of "curating what information enters the model's limited attention budget" is what every developer building a retrieval pipeline has been doing since GPT-3.5 got tool use.
- Compaction is summarization. It has been used in chatbots since before LLMs existed.
- File exclusion (ignoring node_modules, build output) is a `.gitignore` pattern.
**Genuinely new:**
- **Context as the system-level constraint:** "The main constraint on AI-assisted development is no longer model capability, but how context is structured, surfaced, and governed at system level." This framing is new. Before mid-2025, the assumption was that model capability was the constraint. Now, with models that can reason well when given the right context, the bottleneck has shifted to context quality and management.
- **The 1M token wall:** An empirical discovery, not a theoretical prediction. "Models hit a clear performance ceiling around 1 million tokens. Performance degrades meaningfully past this point regardless of what the context window technically supports." This invalidated the marketing claim that larger context windows = better performance.
- **Subagents as context isolation:** Using multiple agents not for task parallelism but for context isolation — each subagent gets a clean context window focused on one sub-problem. This is a genuine architectural pattern that didn't exist before multi-agent frameworks.
- **The MECW finding:** Norman Paulsen's Maximum Effective Context Window study showing that effective context limits differ drastically from advertised limits — some top-performing models failed with as few as 100 tokens on certain tasks. This is hard data that contradicts marketing.
## The Mechanism
### Anthropic's Three Core Techniques
**1. Compaction**
```
Trigger: Context window approaching limit (e.g., >80% full)
Process:
  1. Take the full conversation history
  2. Model generates a summary preserving:
     - Architectural decisions made
     - Unresolved bugs and their symptoms
     - Implementation details in progress
     - File paths and function names mentioned
  3. Discard the full history
  4. Start a new context window with:
     - System prompt (unchanged)
     - The summary (compressed history)
     - Five most recently accessed files (re-read from disk)
  5. Continue generation from the compressed state
What gets lost:
  - Exact wording of earlier conversations
  - Subtle context whose importance isn't obvious at compression time
  - Specific tool outputs from early iterations
  
The art: deciding what to keep. Overly aggressive compaction loses
subtle but critical context. Conservative compaction delays the
inevitable but doesn't prevent it.
```
**2. Tool Result Clearing**
```
Problem: A tool call from 20 turns ago still has its 500-line output
sitting in the context window. The agent will never look at it again,
but it's consuming tokens.
Fix: Replace old tool results with a placeholder:
  BEFORE: [tool_call: grep auth] → [500 lines of grep output]
  AFTER:  [tool_call: grep auth] → [result cleared — 47 matches found]
This is the safest, lightest-touch form of compaction because:
  - The model remembers WHAT it did (the tool call is still there)
  - The model knows the SUMMARY of what happened (match count)
  - But the raw output that's no longer useful is gone
  - Typically reclaims 30-60% of context in tool-heavy sessions
```
**3. Structured Note-Taking / Agentic Memory**
```
Pattern: The agent maintains a scratchpad OUTSIDE the context window.
Implementation:
  1. Agent writes notes to a file (TODO.md, NOTES.md, or a memory store)
  2. Notes persist on disk — they survive context compaction
  3. At the start of each iteration, the agent reads its notes back in
  4. Notes are curated: the agent decides what's worth remembering
Claude Code's implementation:
  - The agent maintains a TODO list during long tasks
  - When context is compacted, the TODO list persists
  - The agent re-reads it to know where it left off
The key insight: memory outside the context window is CHEAP
(disk space, database rows). Memory inside the context window is
EXPENSIVE (tokens, degraded attention). Move long-term memory out
of the window. Bring it back in surgically when needed.
```
### Just-In-Time Context (The Pattern That Actually Scales)
```
// BAD: Load everything upfront
const context = await loadEntireCodebase();  // 800K tokens, most irrelevant
// GOOD: Just-in-time loading
// 1. Agent reads task: "Fix auth token refresh"
// 2. Agent searches for auth-related files (grep, semantic search)
// 3. Loads ONLY src/lib/auth.ts (the relevant file)
// 4. Discovers import from db/schema.ts
// 5. Loads ONLY that file, only at this moment
// 6. Discovers the schema changed last week
// 7. Loads ONLY the relevant git diff
Total tokens consumed: ~5,000 (3 files)
vs upfront: ~800,000 (entire codebase)
Signal-to-noise ratio: 160× better
```
**Strategic file exclusion** is the second-highest impact context engineering move after the system/project memory file. Excluding `node_modules`, build output, binary assets, and lock files alone can reduce context consumption by 80%+ on a typical project.
### Subagents as Context Isolation
```
Single-agent approach:
  One agent, one context window, handles entire research task.
  Context fills with partial findings from multiple sub-topics.
  By the time it reaches the last sub-topic, early findings are
  degraded by the "lost in the middle" effect.
Multi-agent approach:
  Coordinator agent dispatches 5 subagents:
    Subagent 1: "Research X" → clean context, full attention budget
    Subagent 2: "Research Y" → clean context, full attention budget
    Subagent 3: "Research Z" → clean context, full attention budget
    ...
  Each subagent returns a structured summary to the coordinator.
  Coordinator synthesizes all summaries in its own fresh context.
Result: Each sub-task gets the model's full attention budget.
        Quality is better than single-agent for complex research.
        
Cost: Up to 15× more tokens than single-agent chat 
      (Anthropic's own reported number).
```
## The Primary Source Evidence
**Anthropic's canonical framing:** "As models become more capable, the challenge isn't just crafting the perfect prompt — it's thoughtfully curating what information enters the model's limited attention budget at each step... find the smallest set of high-signal tokens that maximize the likelihood of your desired outcome."
**Anthropic's future direction:** "We're already seeing that smarter models require less prescriptive engineering, allowing agents to operate with more autonomy. But even as capabilities scale, treating context as a precious, finite resource will remain central to building reliable, effective agents."
**The 1M token wall:** SWE-rebench maintainer: "Models hit a clear performance ceiling around 1 million tokens. Performance degrades meaningfully past this point regardless of what the context window technically supports."
**MECW study (Paulsen, January 2026):** Maximum Effective Context Window differs drastically from advertised limits — some top-performing models failed with as few as 100 tokens on certain tasks, most showed severe accuracy degradation by 1,000 tokens on certain task types.
**15× cost multiplier for subagents:** Anthropic's own reported number for multi-agent research vs. single-agent chat.
## The Failure Mode
**Without context engineering on a long-running agent loop:**
The agent runs for 30 iterations. Each iteration adds tool calls and their results to the conversation. By iteration 15, the context window is 60% full. By iteration 25, it's 95% full. Quality degrades not because the model is dumb, but because:
1. **Context rot** — the signal-to-noise ratio in the window drops as irrelevant old tool outputs accumulate
2. **Lost in the middle** — critical information from iterations 5-10 is buried in the middle of the context, where models empirically pay less attention
3. **Context anxiety** (model-specific) — Sonnet 4.5 started wrapping up tasks prematurely as it sensed its context limit approaching
The result: the agent declares "done" prematurely, produces lower-quality output, or makes errors that it wouldn't make with a clean context window.
**Victor Dibia's benchmark data:** A single agent task reading 12 files, tracing 3 call stacks, making 15 LLM calls to find a bug burned 120,000 tokens — roughly $1.80 on a frontier model. Run that 50 times a day across a team: ~$2,700/month on a single agent workflow. Without compaction, the brute-force approach (full history, no clearing) consumed 915K tokens across 50 iterations.
## What a Senior Engineer Should Internalize
Context is the most expensive, most constrained, and most impactful resource in your entire agent system. It is more constrained than compute, more expensive than storage, and more impactful on output quality than model selection. A mediocre model with surgical context will outperform a frontier model drowning in irrelevant tokens. The discipline of context engineering is not "prompt engineering 2.0" — it is memory management for a system whose RAM is simultaneously its working memory, its instruction set, and its sensory input. Treat every token that enters the context window the way you'd treat every byte in L1 cache: it must earn its place, and the moment it stops being useful, it must be evicted.

