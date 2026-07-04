# Paper 16: ReAct — Reasoning and Acting in Language Models (Yao et al., 2022)

## What Existed Before and What Broke

Before ReAct, two separate research threads existed that didn't talk to each other:

**Thread 1: Reasoning without action.** Chain-of-Thought (Paper 9) showed that models could reason step by step. But the reasoning was entirely internal — the model generated thoughts but couldn't interact with the world. If a reasoning step required checking a fact, calling an API, or reading a document, the model couldn't do it. It had to rely on whatever knowledge was in its weights or context, hallucinating when that knowledge was insufficient.

```
CoT alone:
  Q: "What's the current stock price of Apple multiplied by its P/E ratio?"
  Thought: Apple's stock price is around $180. Its P/E ratio is about 30.
  Answer: $180 × 30 = $5,400
  
  Problem: The price and P/E are WRONG — they're hallucinated from 
  training data that's months or years out of date. The model can't 
  look up the current values. It reasons correctly on wrong inputs.
```

**Thread 2: Action without reasoning.** Tool-use papers showed that models could call APIs and use tools. But the model had no explicit reasoning about WHEN to use a tool, WHICH tool to use, or HOW to interpret the result. Tool calls were reactive pattern-matching, not deliberate decisions.

```
Tool use alone:
  Q: "What's the current stock price of Apple multiplied by its P/E ratio?"
  Action: search("Apple stock price P/E ratio")
  Result: "Apple (AAPL) $195.23, P/E 32.4"
  Action: calculate(195.23 * 32.4)
  Result: 6325.45
  Answer: $6,325.45
  
  Works if the search returns exactly what's needed in exactly 
  the right format. Falls apart on ambiguous queries, multi-step 
  reasoning that requires choosing between tools, or results 
  that need interpretation before the next step.
```

The gap: reasoning without grounding hallucinates. Action without reasoning is brittle. ReAct interleaves them.

---

## The Core Mechanism

### The Thought-Action-Observation Loop

ReAct's core contribution is a simple interleaving pattern:

```
Loop:
  Thought: Model reasons about what it knows and what it needs to do next
  Action:  Model specifies a tool call with parameters
  Observation: System executes the action and returns the result
  
  Repeat until the model generates a Finish action.
```

Concrete example:

```
Question: "Were the directors of Jaws and Casino Royale born in the same country?"

Thought 1: I need to find the directors of both Jaws and Casino Royale. 
           Let me start with Jaws.
Action 1:  Search[director of Jaws]
Observation 1: Jaws is a 1975 film directed by Steven Spielberg.

Thought 2: Steven Spielberg directed Jaws. Now I need the director of 
           Casino Royale. There are multiple Casino Royale films, I should 
           specify the most recent one.
Action 2:  Search[director of Casino Royale 2006]
Observation 2: Casino Royale (2006) was directed by Martin Campbell.

Thought 3: Steven Spielberg directed Jaws, Martin Campbell directed 
           Casino Royale (2006). Now I need to find where each was born.
Action 3:  Search[Steven Spielberg birthplace]
Observation 3: Steven Spielberg was born in Cincinnati, Ohio, United States.

Thought 4: Spielberg was born in the US. Now I need Campbell's birthplace.
Action 4:  Search[Martin Campbell birthplace]  
Observation 4: Martin Campbell was born in Hastings, New Zealand.

Thought 5: Spielberg was born in the US, Campbell in New Zealand. 
           Different countries.
Action 5:  Finish[No, they were not born in the same country. Steven 
           Spielberg (Jaws) was born in the United States, while Martin 
           Campbell (Casino Royale) was born in New Zealand.]
```

**Why the Thought step matters:** Without explicit reasoning before each action, the model would need to pattern-match directly from the question to the right tool call. With the Thought step, the model:
- Decomposes the problem into sub-goals
- Decides which tool to use and why
- Interprets results before deciding the next step
- Handles ambiguity (multiple Casino Royale films) through explicit reasoning
- Knows when it has enough information to answer

### This Is the Skeleton of Every Agent

Every agent framework you've seen — LangChain, CrewAI, AutoGPT, Claude's tool use — is a ReAct loop with scaffolding:

```
LangChain AgentExecutor:
  while not done:
    thought + action = llm.predict(prompt + history)    # Thought + Action
    observation = tool.execute(action)                    # Observation
    history.append(thought, action, observation)
    if action == "Final Answer": done = True
    
Claude tool use (Anthropic API):
  while not done:
    response = claude.message(messages)                   # Thought
    if response.has_tool_call:                           # Action
      result = execute_tool(response.tool_call)          # Observation
      messages.append(tool_result)
    else:
      done = True                                        # Final answer

OpenAI function calling:
  while not done:
    response = openai.chat(messages, functions=tools)
    if response.function_call:                           # Action
      result = execute(response.function_call)           # Observation
      messages.append(function_result)
    else:
      done = True
```

The scaffolding varies (error handling, cost limits, memory management), but the core loop is always: think → act → observe → repeat.

---

## What This Creates for Your System

### Loop Control Is the Core Engineering Problem

The academic paper says "loop until Finish action." Production requires much more:

```
Failure mode 1: Infinite loops
  Model encounters an error → tries the same action → same error → retry → ...
  
  Fix: max step limit (hard cap at 10-20 steps)
  Fix: loop detection (same action + same params → break)
  Fix: error escalation (after N failures on same action, force different approach)

Failure mode 2: Goal drift
  Model starts solving the right problem → gets distracted by an 
  interesting tangent in an observation → pursues the tangent → 
  never returns to the original question
  
  Fix: goal reminder in system prompt ("Your goal is: {original_question}")
  Fix: periodic re-anchoring ("Is this action moving toward answering 
  the original question?")

Failure mode 3: Context explosion
  Each T/A/O cycle adds ~500-1000 tokens to context.
  10-step loop: 5-10K tokens of history.
  20-step loop: 10-20K tokens. Approaching context limits.
  
  Fix: context compaction (summarize old T/A/O cycles)
  Fix: sliding window (keep last N cycles + summary of earlier ones)
  Fix: selective retention (keep only cycles with useful observations)

Failure mode 4: Cost explosion
  Each loop iteration is an LLM call.
  10 iterations × $0.02/call = $0.20 per user query.
  If the model loops 50 times on a hard query: $1.00 per query.
  
  Fix: cost budget per query (hard cap at $X)
  Fix: step-dependent model routing (cheap model for early exploration,
  expensive model for final synthesis)
```

### Tool Design Is Higher Leverage Than Prompt Engineering

For agent systems, the design of your tools — their names, descriptions, parameter schemas, and return formats — has more impact on reliability than any amount of prompt engineering:

```
✗ Bad tool design:
  Tool name: "search"
  Description: "Searches for information"
  Parameters: {"query": "string"}
  Returns: raw HTML or unstructured text
  
  Problems:
  - "search" is ambiguous — search where? Google? Internal docs? Database?
  - Description tells the model nothing about when to use this vs other tools
  - Unstructured return: model must parse HTML to find relevant info
  - Model frequently calls "search" when it should use a specific tool

✓ Good tool design:
  Tool name: "search_company_knowledge_base"
  Description: "Search the company's internal knowledge base for policy 
  documents, HR guidelines, and process documentation. Use this when the 
  user asks about company-specific policies or procedures. Do NOT use 
  for general knowledge questions."
  Parameters: {
    "query": "string - natural language search query",
    "department": "enum: [HR, Engineering, Legal, Finance] - optional filter",
    "max_results": "integer - default 5, max 20"
  }
  Returns: {
    "results": [{"title": "...", "snippet": "...", "url": "...", "relevance_score": 0.95}],
    "total_found": 42
  }
  
  Improvements:
  - Name tells the model exactly what this tool searches
  - Description includes when to use AND when NOT to use
  - Parameters have types, descriptions, and constraints
  - Return format is structured — model can parse programmatically
  - Relevance score helps model assess result quality
```

**The rule of thumb:** If your agent uses the wrong tool or calls a tool with wrong parameters more than 10% of the time, the problem is tool design, not the model. Rename the tool, improve the description, restructure the parameters, and format the return value as structured data. This is the highest-leverage fix for agent reliability.

### Agent Evaluation — The Harder Problem

Evaluating agents is fundamentally harder than evaluating single-turn LLM outputs:

```
Single-turn evaluation:
  Input → Output → Compare to ground truth
  Straightforward. Well-understood metrics.

Agent evaluation:
  Input → [T/A/O loop with variable steps] → Output
  
  What to evaluate:
  1. Final answer correctness: Did the agent get the right answer?
  2. Tool selection accuracy: Did it use the right tools?
  3. Tool parameter accuracy: Did it pass correct parameters?
  4. Efficiency: Did it solve it in minimal steps?
  5. Failure handling: Did it recover from errors gracefully?
  6. Cost: How many tokens/API calls did it use?
  7. Latency: How long did the full loop take?
  
  Each metric can be good while others are bad:
  - Correct answer but 20 steps (inefficient)
  - Correct answer but used 3 unnecessary tools (wasteful)
  - Wrong answer but all tool calls were correct (reasoning failure)
```

---

## What Production Systems Changed After This

**Agent frameworks exploded.** LangChain, CrewAI, AutoGPT, BabyAGI, Microsoft Semantic Kernel — every agent framework is a ReAct implementation with different scaffolding. The core loop is identical across all of them. The differentiation is in error handling, memory management, tool integration, and developer experience.

**Tool use became a first-class API feature.** Anthropic's tool use, OpenAI's function calling, Google's function calling — these are productizations of the Action step in ReAct. The API accepts tool definitions, the model generates structured tool calls, and you execute them in your code.

**The "agentic" product category.** Before ReAct, LLM products were Q&A systems. After ReAct, they became agents that could take actions: book appointments, modify databases, send emails, write and execute code. This expanded the product surface from "answer questions" to "do things."

**Computer use / browser agents.** The most ambitious ReAct applications: agents that can use a computer — clicking buttons, typing text, navigating websites. Same T/A/O loop, where Actions are mouse clicks and keyboard inputs, and Observations are screenshots.

---

## How This Connects to the Other 17 Papers

**Combines Paper 9 (CoT) with tool use:** The Thought step is Chain-of-Thought reasoning. The Action step is tool invocation. ReAct's contribution is the interleaving — reasoning informs action selection, observations inform further reasoning.

**Requires Paper 4's (GPT-3) in-context learning:** The agent prompt includes tool descriptions and examples of the T/A/O format. The model generalizes this format to new queries through in-context learning.

**Requires Paper 6's (InstructGPT) instruction following:** The model must reliably follow the T/A/O format, call tools with correct parameters, and respond to system prompt instructions about when to use which tool. Without instruction tuning, the model's adherence to this structured format is unreliable.

**Creates demand for Paper 8 (FlashAttention) and Paper 14 (PagedAttention):** Agent loops accumulate context rapidly. A 15-step agent loop might consume 10-15K tokens of T/A/O history. Efficient attention (FlashAttention) and memory management (PagedAttention) make this tractable.

**Extends Paper 15 (RAG) into agentic RAG:** RAG retrieves documents passively (one retrieval step, then generation). Agentic RAG uses the ReAct loop to perform multiple retrievals, refine queries based on results, and synthesize across multiple retrieval rounds. The ReAct loop makes RAG adaptive rather than one-shot.

---

## The Honest Take

**1. What most engineers miss when they skip this paper and just use the API:**

Every agent framework is a ReAct loop. When an agent misbehaves, the diagnosis is: which part of the Thought-Action-Observation loop broke?

- Model generates a hallucinated tool call (tool doesn't exist) → **Action failure**. Fix: better tool descriptions, constrained tool selection.
- Model misinterprets tool output and makes wrong decision → **Observation interpretation failure**. Fix: structured tool output format, explicit parsing instructions.
- Model gets stuck in a loop retrying the same failed action → **Thought failure** (can't reason about failure). Fix: error handling instructions, loop detection.
- Model solves the wrong problem → **Goal drift**. Fix: goal re-anchoring in system prompt.

Without understanding ReAct, agent debugging is guessing. With it, every failure has a specific location in the loop and a specific class of fix.

**2. The one non-obvious systems implication that blog posts never explain:**

The context window cost of agent loops is the primary production constraint, not the quality of the model's reasoning. A 15-step agent loop that accumulates 15K tokens of T/A/O history is expensive (15 LLM calls + 15K tokens of context per call). The cost scales quadratically with loop depth (each step adds context for all subsequent steps).

This means agent design is fundamentally a cost optimization problem: how do you get the right answer in the minimum number of steps? Tool design (fewer, better tools reduce step count), context management (compaction reduces per-step cost), and routing (use a cheap model for exploration, expensive model for final synthesis) are all cost optimization levers that matter more than model quality for production agent economics.

**3. Essential, useful context, or interesting history?**

**Essential. This is the other foundational applied paper (alongside RAG, Paper 15).** RAG is the pattern for knowledge-augmented systems. ReAct is the pattern for action-capable systems. Together, they cover the two dominant architectures for production LLM applications: systems that answer questions (RAG) and systems that do things (agents/ReAct).

If you build or debug any agent system, understanding the T/A/O loop and its failure modes is non-negotiable. Every framework abstracts it differently, but the underlying mechanism is always ReAct. Understanding the mechanism lets you debug through the framework abstraction instead of being blocked by it.
