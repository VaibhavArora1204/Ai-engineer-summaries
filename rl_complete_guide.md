# Reinforcement Learning — The Complete Guide

## From First Principles to GRPO, DeepSeek-R1, Agentic RL, and Everything Between

### For AI Engineers Who Build Systems, Not Papers

---

> **How to read this file.**
> This is one continuous narrative told in 16 series across 5 acts. Every concept builds on
> the ones before it. If you skip ahead, you will miss the connection that makes the later
> concept land. The goal: after reading this, you understand what is actually happening inside
> every frontier model you call via API, every reasoning model you pay for, every agent you
> build — and you understand it well enough to make real engineering decisions about them.

---

> **The Five Acts**
>
> | Act | What It Covers | Series |
> |-----|----------------|--------|
> | **Act 1 — The Foundation** | What RL is, why it exists, the math that makes it work | 01–03 |
> | **Act 2 — The Algorithms** | How agents actually learn, from tabular to deep | 04–06 |
> | **Act 3 — RL Meets LLMs** | RLHF, reward modeling, the alignment revolution | 07–08 |
> | **Act 4 — The Modern Era** | GRPO, RLVR, reasoning models, DeepSeek-R1, o1 | 09–12 |
> | **Act 5 — Agentic RL** | RL as the training paradigm for autonomous agents | 13–16 |

---

# ACT 1 — THE FOUNDATION

---

## Series 01: What RL Is and Why It Exists

**Act 1 — The Foundation**
*Connects forward to: Series 02 (MDP formalism), Series 07 (PPO/RLHF), Series 15 (production implications)*

---

### The Problem That Creates RL

Imagine you are building a system that has to make a sequence of decisions, and the quality of each decision depends on decisions it hasn't made yet.

A chess move is only good in context of the game that follows. A code suggestion is only good if the code it produces actually runs. A response from an LLM is only good if the human receiving it finds it helpful — but "helpful" is a judgment that comes after the response is already generated.

Supervised learning cannot solve this. Supervised learning needs a label for every input. "Given this board state, the correct move is X." But in most real problems, you do not know the correct action at each step. You know the outcome at the end. You know whether you won the game, whether the code passed the tests, whether the human clicked thumbs-up. You do not know which of the 50 intermediate decisions was responsible.

This is the **credit assignment problem**: good outcome at the end, but which actions along the way were the good ones? Supervised learning requires someone to label each step. RL figures it out from the outcome.

### The Three Learning Paradigms — What Each Can and Cannot Do

**Supervised learning**: you have inputs and correct outputs. The model learns the mapping. It can only be as good as the labels. If your labels are wrong, the model is wrong. If the task requires actions that no human labeled, supervised learning cannot help.

**Unsupervised learning**: you have inputs, no labels. The model learns structure — patterns, clusters, representations. It finds what is there. It cannot optimize for a goal because no goal is specified.

**Reinforcement learning**: you have an agent, an environment, and a reward signal. The agent takes actions, the environment responds, and occasionally the agent gets a reward. The agent's job is to figure out which actions lead to more reward over time. No labels. No demonstrations. Just trial, error, and feedback.

The key difference: supervised learning tells the model what to do. RL tells the model what is good, and the model figures out what to do.

### Why This Matters for AI Systems

Every frontier LLM you call via API today went through RL post-training. The base model was trained with supervised learning (next-token prediction). But the behaviors you actually care about — following instructions, refusing harmful requests, being helpful without being sycophantic, reasoning step by step — all of that was shaped by RL.

When GPT-4 gives you a helpful response, that helpfulness was optimized by RL. When Claude refuses a dangerous request, that refusal boundary was drawn by RL. When a reasoning model generates a chain of thought before answering, that behavior was trained by RL.

The base model is the raw material. RL is the process that turns raw material into the product you use.

### Exploration vs. Exploitation — The Real Tension

Every RL system faces this: do I do the thing I already know works, or do I try something new that might be better?

**Exploitation**: take the action with the highest known reward. Safe. Predictable. But you might be stuck in a local optimum — there could be much better actions you have never tried.

**Exploitation**: try an unknown action. Risky. Might waste time. But it is the only way to discover better strategies.

This is not a textbook abstraction. This shows up everywhere:

- A recommendation system: do you keep showing the user what they already like, or do you show something new to learn their preferences better?
- An LLM during RL training: does it keep generating responses similar to what got high reward before, or does it try novel response strategies?
- An agent navigating a codebase: does it keep using the approach that worked on similar tasks, or does it try a different tool chain?

Every RL algorithm has a mechanism for balancing this. **Epsilon-greedy**: with probability epsilon (say, 10%), take a random action; otherwise, take the best known action. Simple, effective, used widely. **Upper Confidence Bound (UCB)**: favor actions that you are uncertain about — if you have not tried it much, it might be great. As you learn more, the uncertainty shrinks and you exploit more.

In LLM training, this tension shows up as **entropy bonuses** in the RL loss function — extra reward for maintaining diversity in outputs, preventing the model from collapsing to always generating the same safe response.

### The Reward Hypothesis

The foundational assumption of RL, stated clearly:

> *All goals can be expressed as the maximization of a scalar reward signal.*

This is powerful because it gives you a universal framework. Want the model to be helpful? Define helpfulness as the reward. Want it to write correct code? Define test-pass rate as the reward. Want it to reason well on math? Define answer correctness as the reward.

This is dangerous because it assumes you can capture everything you care about in a single number. You usually cannot. The reward model for RLHF is trained on human preferences, but humans are inconsistent, biased, and manipulable. The model learns to maximize the reward signal, not the thing the reward signal was supposed to represent. This gap is called **reward hacking**, and it is one of the central problems in AI alignment. We will revisit it in Series 08 and Series 09.

### What You Should Carry Forward

RL is the mechanism by which AI systems improve beyond what human demonstration can provide. Supervised learning teaches imitation. RL teaches optimization. The difference between a base model and the model you interact with via API is, in large part, RL. Every concept in the rest of this guide connects back to this: an agent, an environment, actions, rewards, and the problem of figuring out which actions lead to the best long-term outcomes.

---

## Series 02: Markov Decision Processes — The Math That Makes RL Work

**Act 1 — The Foundation**
*Connects backward to: Series 01 (RL problem definition). Connects forward to: Series 03 (value functions), Series 07 (PPO), Series 09 (GRPO), Series 14 (agentic RL formulation)*

---

### Why You Need a Formal Framework

RL as described in Series 01 is intuitive but imprecise. "Agent takes actions, gets rewards" is a story. To build algorithms that actually work, you need a mathematical framework that specifies exactly what states are, what actions are, how the world responds, and how rewards are generated. That framework is the **Markov Decision Process (MDP)**.

Every RL algorithm you will encounter — Q-learning, PPO, GRPO, all of them — is solving an MDP, whether explicitly or implicitly. When someone formulates "training an LLM with RLHF" as an RL problem, they are casting it as an MDP. When someone formulates "training an agent to use tools" as an RL problem, they are casting it as an MDP. The specifics change. The framework does not.

### The Five Components

An MDP is defined by five things:

**1. States (S)**: everything the agent can observe about the world at a given moment. In a board game, the state is the board position. In an LLM generating a response, the state is the prompt plus all tokens generated so far (the context window contents). In an agent navigating a codebase, the state is the conversation history plus tool outputs received so far.

**2. Actions (A)**: everything the agent can do from a given state. In a board game, the legal moves. In an LLM, the set of all possible next tokens (the entire vocabulary, typically 32K-128K tokens). In an agent, the set of available tool calls plus their arguments.

**3. Transition function P(s'|s,a)**: given that you are in state s and take action a, the probability of ending up in state s'. This is the world model. In a deterministic game, transitions are deterministic. In an LLM, after generating token a from state s, the next state s' is deterministically s with token a appended. In an agent, the transition depends on what the tool returns — which may be unpredictable.

**4. Reward function R(s,a,s')**: the scalar feedback signal. Can be given at every step or only at the end. In RLHF, the reward model scores the complete response — so reward is 0 for every intermediate token and then the RM score at the final token. In RLVR (verifiable rewards), the reward is 1 if the math answer is correct, 0 otherwise. Only at the end.

**5. Discount factor γ (gamma)**: a number between 0 and 1 that determines how much the agent cares about future rewards versus immediate rewards. γ = 0.99 means a reward 100 steps from now is worth 0.99^100 ≈ 0.37 of its face value. γ = 0 means the agent only cares about the next immediate reward. γ = 1 means all future rewards are weighted equally (only works for finite episodes).

**Why gamma matters in practice**: when training an LLM with RL, gamma close to 1 means the model considers the full response quality. If gamma were lower, the model would prioritize making the first few tokens good and not care about how the response ends. In agent tasks with many steps, gamma determines the planning horizon — how far ahead the agent effectively looks.

### The Markov Property — The Key Assumption

The "Markov" in MDP comes from this property:

> The future depends only on the current state, not on the history of how you got there.

Formally: P(s_{t+1} | s_t, a_t, s_{t-1}, a_{t-1}, ..., s_0, a_0) = P(s_{t+1} | s_t, a_t)

This is what makes the math tractable. If the future depended on the entire history, you would need to track every possible history — combinatorially explosive.

**When the Markov property holds**: board games (the board position tells you everything), most simulated environments, LLM token generation (if the context window contains the full conversation).

**When it breaks**: the real world. An agent interacting with a web browser does not see the full state of the server. A robot does not see occluded objects. An LLM with a finite context window eventually loses information about earlier parts of the conversation.

When the Markov property is violated, you have a **Partially Observable MDP (POMDP)**. Real agent systems are almost always POMDPs. The practical workaround: pack as much relevant history as possible into the "state" representation. For LLMs, this means putting conversation history and tool outputs into the context window. For agents, this means maintaining memory and state summaries.

### Episodes vs. Continuing Tasks

**Episodic tasks** have a clear start and end. A game ends. An LLM generates a response and stops. An agent completes a task or times out. Most RL in AI systems is episodic.

**Continuing tasks** run forever. A recommendation system that continuously serves users. A trading bot that runs indefinitely. These are harder because there is no natural endpoint to compute total reward.

LLM training is almost always episodic: the episode is one prompt-response pair. Agent RL is episodic: the episode is one task attempt.

### The LLM-as-MDP Connection — Make It Concrete

This is the connection that makes the rest of the guide work:

| MDP Component | LLM Token Generation | Agent Tool Use |
|---|---|---|
| State | Prompt + tokens generated so far | Conversation history + tool outputs |
| Action | Next token from vocabulary | Next tool call + arguments |
| Transition | Deterministic: append token to state | Stochastic: depends on tool response |
| Reward | RM score at end of response | Task success at end of episode |
| Discount (γ) | ~1.0 (care about full response) | ~0.99 (care about full trajectory) |
| Episode | One prompt → response | One task attempt |

When you read about PPO optimizing an LLM, it is solving this MDP. When you read about GRPO training a reasoning model, it is solving this MDP with a verifiable reward function. When you read about agentic RL, the MDP has a different action space (tool calls instead of tokens) and a different environment (real tools instead of token appending).

The framework is the same. The instantiation changes.

### The Policy — The Agent's Strategy

A **policy** π is the agent's decision-making function. It maps states to actions.

**Deterministic policy**: π(s) = a. Given state s, always take action a. Rigid.

**Stochastic policy**: π(a|s) = probability of taking action a in state s. Flexible. This is what LLMs are — they output a probability distribution over the vocabulary at each step.

The goal of RL: find the policy π that maximizes expected cumulative discounted reward over episodes. Every RL algorithm is a different strategy for finding this optimal policy.

### What You Should Carry Forward

Every RL problem is an MDP. State, action, transition, reward, gamma. The Markov property makes it solvable. LLM generation and agent tool use are both MDPs with different instantiations of the same components. When you encounter PPO, GRPO, or any other RL algorithm in later series, they are all solving this same framework — they just differ in how they search for the optimal policy.

---

## Series 03: Value Functions and the Bellman Equation

**Act 1 — The Foundation**
*Connects backward to: Series 02 (MDP framework). Connects forward to: Series 04 (Q-learning), Series 07 (PPO's value model), Series 09 (why GRPO removes the value model)*

---

### The Central Insight: Think Long-Term

The naive approach to RL: at each step, take the action that gives the highest immediate reward. This fails catastrophically. In chess, capturing a piece might give immediate "reward" but lose the game. In LLM generation, a token that sounds good right now might lead to an incoherent sentence. In agent tasks, a tool call that returns useful info right now might be a dead-end strategy.

The insight that makes RL work: instead of evaluating actions by their immediate reward, evaluate them by the **total future reward** you expect to get from this point forward if you act optimally. This is the **value function**.

### V(s) — The Value of a State

The **state value function** V(s) answers: "If I am in state s, and I follow my current policy from here, what is the total discounted reward I expect to accumulate?"

High V(s) means: this is a good state to be in. Things tend to go well from here.
Low V(s) means: this is a bad state. Outcomes from here tend to be poor.

For an LLM mid-generation: V(s) would represent "how good is the response likely to be, given what has been generated so far?" A partial response that starts well has high V. A partial response that has gone off the rails has low V.

### Q(s,a) — The Value of an Action in a State

The **action value function** Q(s,a) answers: "If I am in state s, and I take action a, and then follow my policy from there, what total discounted reward do I expect?"

Q(s,a) is more useful than V(s) for making decisions. V(s) tells you how good a state is, but it does not tell you which action to take. Q(s,a) tells you the value of each specific action, so you can pick the best one: π(s) = argmax_a Q(s,a).

The relationship: V(s) = max_a Q(s,a) under the optimal policy. The value of a state is the value of the best action available in that state.

### The Advantage Function — How Much Better Than Average?

The **advantage function** A(s,a) = Q(s,a) - V(s).

This tells you: how much better (or worse) is this specific action compared to the average action in this state?

- A(s,a) > 0: this action is better than what the policy would normally do
- A(s,a) < 0: this action is worse than average
- A(s,a) = 0: this action is exactly as good as the policy's average

**Why this matters enormously**: PPO, GRPO, and virtually every modern RL algorithm optimizes using advantages, not raw rewards. The reason: advantages have lower variance. If you are in a state where all actions give reward around 100, the raw rewards are all large numbers — but the differences between them are small. The advantage strips away the baseline and focuses on the relative quality. This is the signal that matters for learning.

Remember the advantage function. It will appear in every algorithm from here forward.

### The Bellman Equation — The Recursive Insight

Here is the key intuition that powers almost every RL algorithm:

> The value of a state is the immediate reward you get, plus the discounted value of the state you end up in.

Written as a relationship:

```
V(s) = R(s,a) + γ · V(s')
```

(Simplified for deterministic transitions and fixed policy. The full version sums over all possible next states weighted by their transition probabilities.)

This is a recursive definition. The value of state s depends on the value of state s', which depends on the value of state s'', and so on. If you can solve this recursion, you have solved the RL problem.

**The optimal version** (Bellman optimality equation) says:

```
V*(s) = max_a [ R(s,a) + γ · Σ P(s'|s,a) · V*(s') ]
```

"The optimal value of a state is the best action's immediate reward plus the discounted optimal value of wherever that action takes you."

### Why Solving Bellman Equations Directly Is Usually Impossible

If you know the transition function P(s'|s,a) and the reward function R, you can solve the Bellman equation exactly using **dynamic programming** — algorithms called **value iteration** and **policy iteration**.

This works for small, known environments: grid worlds, simple games, well-defined planning problems.

It breaks for the problems we actually care about:

1. **Unknown transitions**: you do not know P(s'|s,a). You do not have a model of the world. You can only observe what happens when you try actions.
2. **Enormous state spaces**: an LLM's state is the context window — billions of possible states. You cannot store a value for each one.
3. **Continuous state spaces**: robot positions, continuous control — infinite states.

The solution to all three: **approximation**. Instead of computing exact values, learn approximate value functions using function approximators (neural networks). This is the bridge from Act 1 (foundations) to Act 2 (algorithms).

### The Connection to What Comes Next

- **Q-learning** (Series 04): learns Q(s,a) from experience, without knowing transitions
- **DQN** (Series 05): uses a neural network to approximate Q(s,a) for large state spaces
- **PPO** (Series 07): uses a neural network (the "critic" / "value model") to estimate V(s) for computing advantages, which are used to update the policy
- **GRPO** (Series 09): the breakthrough — it gets rid of the value model entirely by computing advantages from a group of sampled responses instead of a learned V(s)

The value model in PPO (one of the four models you need in GPU memory) exists specifically to estimate V(s) for computing advantages. GRPO's key insight is finding a way to compute advantages without this model. Understanding why V(s) matters is understanding why eliminating it is significant.

### What You Should Carry Forward

Value functions (V, Q) estimate total future reward from a state or state-action pair. The advantage function (A = Q - V) measures how much better an action is than average — this is the signal that modern RL algorithms actually optimize. The Bellman equation defines the recursive relationship between values of successive states. Solving it exactly is usually impossible in practice, which is why we need the algorithms in the next series.

---

## Series 04: Q-Learning and Temporal Difference Learning

**Act 2 — The Algorithms**
*Connects backward to: Series 03 (value functions, Bellman equation). Connects forward to: Series 05 (DQN — neural network Q-learning), Series 06 (policy gradients — the alternative path)*

---

### The Shift: Learning Without a World Model

Series 03 ended with a problem: solving the Bellman equation requires knowing the transition function P(s'|s,a). In most real problems, you do not know how the world works. You cannot predict what tool output you will get. You cannot predict what the user will say next. You cannot enumerate every possible next state.

**Model-free RL** solves this: learn from experience. Take actions. Observe what happens. Update your estimates. No world model required.

This is the shift from planning (model-based: compute the answer from a known model) to learning (model-free: figure it out from trial and error).

### Temporal Difference Learning — The Core Idea

The fundamental insight of **Temporal Difference (TD) learning**:

> You do not need to wait until the end of an episode to learn. You can update your estimates at every step, using the difference between what you predicted and what you observed.

Consider: you estimate V(s) = 10 (you think this state is worth 10 future reward). You take an action, get immediate reward r = 3, and end up in state s' where V(s') = 8.

Your updated estimate of V(s) should be: r + γ · V(s') = 3 + 0.99 × 8 = 10.92.

You predicted 10, but your one-step estimate says 10.92. The difference is the **TD error**:

```
δ = r + γ · V(s') - V(s) = 10.92 - 10 = 0.92
```

The TD error is a **surprise signal**. Positive δ: things turned out better than expected. Negative δ: things turned out worse. You nudge your estimate of V(s) in the direction of the TD error.

This is the same fundamental mechanism as gradient descent: you have an estimate, you compare it to a better estimate, and you move toward the better one. The key difference: in supervised learning, the "better estimate" is a ground-truth label. In TD learning, the "better estimate" is itself an estimate (r + γ · V(s')). You are updating estimates toward other estimates. This is called **bootstrapping**, and it is the magic and the risk of TD learning. It works remarkably well in practice, but the theoretical guarantees are weaker than Monte Carlo methods (which wait for the full episode to compute the actual return).

### Q-Learning — Learning the Optimal Action Values

**Q-learning** (Watkins, 1989) is TD learning applied to Q values instead of V values:

```
Q(s,a) ← Q(s,a) + α · [ r + γ · max_a' Q(s',a') - Q(s,a) ]
```

Step by step:
1. You are in state s, you take action a
2. You observe reward r and next state s'
3. You look at Q(s',a') for all possible next actions a' and take the maximum
4. r + γ · max Q(s',a') is your better estimate of what Q(s,a) should be
5. You move Q(s,a) toward this better estimate by a learning rate α

**The crucial detail**: in step 3, you take the **maximum** over next actions — the greedy action. But the action you actually took (step 1) might not have been greedy. You might have been exploring.

This makes Q-learning **off-policy**: it learns about the optimal policy (always take the max) while following a different policy (one that includes exploration). This is powerful — you can explore freely and still learn the optimal strategy.

### SARSA — The On-Policy Alternative

**SARSA** updates Q toward the action that was actually taken next, not the greedy action:

```
Q(s,a) ← Q(s,a) + α · [ r + γ · Q(s',a') - Q(s,a) ]
```

Here a' is the action the agent actually takes in s', not necessarily the best one. SARSA is **on-policy**: it learns about the policy it is actually following.

**When does this matter?** In safe exploration. If your exploration policy sometimes takes dangerous actions, Q-learning will still learn the optimal policy (which might involve going near danger). SARSA learns a more conservative policy that accounts for the fact that it will sometimes explore suboptimally. In production systems where exploration has real costs (e.g., an agent making real API calls), on-policy methods can be safer.

### Tabular Q-Learning — Where It Breaks

In tabular Q-learning, Q(s,a) is stored in a lookup table: one entry per (state, action) pair.

A 19×19 Go board has approximately 10^170 possible states. A chess board has approximately 10^47. An LLM's context window has more possible states than atoms in the observable universe. You cannot build a table that large.

This is the **curse of dimensionality**: as the number of dimensions in the state or action space grows, the number of possible states or actions grows exponentially. Tabular methods are mathematically elegant but computationally impossible for real problems.

The solution: **function approximation**. Instead of storing a separate value for every (state, action) pair, use a function (like a neural network) that takes the state as input and outputs approximate Q values for all actions. This is what DQN (Series 05) does.

**What function approximation buys you**: generalization. The neural network learns features of states and can estimate Q values for states it has never seen before, based on similar states it has seen. A chess network does not need to see every board position — it learns visual/positional features that generalize.

**What function approximation costs you**: convergence guarantees. Tabular Q-learning is mathematically guaranteed to converge to the optimal Q function under mild conditions. The moment you introduce a neural network, those guarantees disappear. Deep RL is empirically powerful but theoretically fragile. This tension drives much of the engineering in deep RL: experience replay, target networks, clipping — all stabilization tricks to make an inherently unstable process work.

### The Connection to LLM Systems

Q-learning's core idea — update estimates toward better estimates — shows up throughout modern AI systems:

- **Reward model training**: the RM learns to predict human preference scores. During RLHF, the policy is updated toward actions that the RM scores higher — conceptually similar to moving Q estimates toward observed rewards.
- **Value model in PPO**: PPO maintains a value model (critic) that estimates V(s). This critic is trained with TD-like updates. Series 07 will cover this in depth.
- **The off-policy insight**: Q-learning's ability to learn from data collected by a different policy is the same principle that lets you train on replay buffers, on historical data, and on human demonstrations. DPO (Series 12) takes this further — learning directly from offline preference data without any online interaction.

### What You Should Carry Forward

TD learning: update estimates from other estimates at every step, without waiting for the end. Q-learning: learn optimal Q values off-policy. SARSA: learn on-policy. Tabular methods break at scale → need neural network approximation (next series). The theoretical guarantees of tabular RL disappear with function approximation, creating the need for all the stabilization tricks that define modern deep RL.

---

---

## Series 05: Deep Q-Networks — Neural Networks Meet RL

**Act 2 — The Algorithms**
*Connects backward to: Series 04 (Q-learning, why tabular breaks). Connects forward to: Series 06 (policy gradients — the other approach), Series 07 (PPO), Series 15 (production systems)*

---

### The Problem DQN Solves

Series 04 ended with: tabular Q-learning works, but only for tiny state spaces. Real problems have enormous or continuous state spaces. The obvious fix: replace the Q-table with a neural network. State goes in, Q-values for all actions come out.

The problem: this does not work naively. When you combine neural networks with Q-learning, training becomes catastrophically unstable. Two specific instabilities destroy it:

**Instability 1 — Correlated samples**: Q-learning generates training data sequentially. State s_1, then s_2, then s_3. Consecutive states are highly correlated (s_2 is one step from s_1). Neural networks trained on correlated data do not generalize — they overfit to recent experience and forget earlier learning. This is like training an image classifier where all the cat images come in one batch and all the dog images in the next. The model oscillates instead of converging.

**Instability 2 — Moving targets**: in Q-learning, the target is r + γ · max Q(s',a'). But Q is the very network you are training. As you update the network, the targets change. The network is chasing a moving target. This creates feedback loops: an update that improves Q in one area might shift Q targets in another area, causing oscillations or divergence.

### The Two Stabilization Tricks That Made DQN Work

**Experience replay**: instead of training on transitions as they happen, store them in a large buffer (the **replay buffer**). When training, sample random mini-batches from this buffer. This breaks the temporal correlation — a mini-batch might contain transitions from thousands of steps apart. The neural network sees a diverse, decorrelated dataset.

**Why this is significant beyond DQN**: experience replay is the first instance of a general deep RL principle — separate data collection from data training. In RLHF, you collect trajectories with the current policy, store them, and train on batches. The replay buffer concept shows up as "rollout buffers" in PPO and as "preference datasets" in DPO.

**Target network**: keep a separate, frozen copy of the Q-network. Use this frozen copy to compute Q targets (the r + γ · max Q(s',a') part). Only update the frozen copy every N steps (or blend it slowly toward the active network). Now the targets are stable for N steps, giving the active network stable ground to train against.

**Why this is significant beyond DQN**: the target network concept is the ancestor of the **reference model** in RLHF. In PPO for LLMs, you keep a frozen copy of the original policy (the reference model) to prevent the active policy from drifting too far. Same principle: a frozen checkpoint provides stability. The engineering insight — "keep a frozen copy to anchor against" — transfers directly.

### The DQN Result (Mnih et al., 2013/2015)

DQN achieved human-level performance on 49 Atari games from raw pixels. Same architecture. Same hyperparameters. No game-specific engineering. This was the moment deep RL became real.

The architecture: convolutional neural network takes raw pixel frames as input, outputs Q-values for each possible action (joystick directions + button). The CNN learns visual features — edges, objects, spatial relationships — directly from the RL signal.

### DQN Variants That Matter

**Double DQN**: standard DQN overestimates Q-values. Why? The max operation in max_a Q(s',a') selects the highest Q-value, but if some Q-values are overestimated due to noise, the max preferentially selects the overestimated ones. Systematic upward bias. Double DQN fixes this by using one network to select the action and a different network to evaluate it. Simple. Effective.

**Dueling DQN**: splits the network into two streams — one estimates V(s) (how good is this state in general) and one estimates A(s,a) (how much better is each action than average). Combines them: Q(s,a) = V(s) + A(s,a). This helps because in many states, the state value matters more than the action choice. Standing in front of an open door — the state is good regardless of which step you take first.

**Prioritized experience replay**: instead of sampling uniformly from the replay buffer, sample transitions with high TD error more frequently. These are the "surprising" transitions the model can learn the most from. Faster learning.

### The Engineering Lessons That Transfer to LLM Systems

| DQN Concept | LLM/Agent Equivalent |
|---|---|
| Experience replay buffer | Rollout buffers in PPO, preference datasets in DPO |
| Target network (frozen copy) | Reference model in RLHF (frozen copy of initial policy) |
| Prioritized replay | Curriculum learning, hard-example mining in fine-tuning |
| Correlated sample problem | Why you shuffle training data, why you collect diverse rollouts |

DQN solved the "how to make neural networks work with RL" problem for discrete action spaces. But LLMs and continuous control have a different problem: the action space is enormous (32K+ tokens) or continuous. You cannot compute Q-values for every possible action. This leads to the next series.

### What You Should Carry Forward

Neural networks + Q-learning is unstable without experience replay and target networks. Experience replay breaks temporal correlations. Target networks stabilize learning targets. These stabilization principles (separate data collection from training, freeze copies for stability) are universal in deep RL and show up directly in how RLHF systems are built.

---

## Series 06: Policy Gradient Methods — Directly Optimizing Behavior

**Act 2 — The Algorithms**
*Connects backward to: Series 05 (DQN's limitations). Connects forward to: Series 07 (PPO — the dominant policy gradient method), Series 09 (GRPO — the modern variant)*

---

### Why Q-Learning Hits a Wall

DQN outputs Q-values for every possible action. This requires enumerating all actions. For Atari (18 joystick positions), that is fine. For an LLM choosing from a vocabulary of 128,000 tokens, computing Q-values for every token at every generation step is prohibitively expensive. For continuous action spaces (robot joint angles, continuous control), it is impossible — you cannot enumerate uncountably many actions.

The alternative: do not learn Q-values at all. Instead, directly learn the policy — the function that maps states to actions. Optimize the policy parameters so that the expected reward goes up. These are **policy gradient methods**.

### The Core Idea — REINFORCE

**REINFORCE** (Williams, 1992): the simplest policy gradient algorithm.

The policy π_θ(a|s) is a neural network parameterized by θ. It takes a state and outputs a probability distribution over actions. For LLMs, this is already the architecture — the model takes context and outputs a distribution over tokens.

The goal: find θ that maximizes expected total reward.

The gradient of expected reward with respect to θ is:

```
∇J(θ) = E[ ∇ log π_θ(a|s) · R ]
```

The intuition is straightforward:
- **∇ log π_θ(a|s)** is the direction in parameter space that increases the probability of action a in state s
- **R** is how good the outcome was
- Multiply them: if R was high, increase the probability of the actions that led to it. If R was low, decrease their probability.

This is the core of how LLMs are trained with RL. The policy is the LLM. The actions are tokens. The reward comes from the reward model or verifier. REINFORCE says: increase the probability of token sequences that got high reward, decrease the probability of those that got low reward.

### The Variance Problem — Why Raw REINFORCE Is Unstable

REINFORCE has a critical flaw: **high variance**. The return R is computed from a single trajectory rollout. Trajectories are noisy. Sometimes a mediocre action sequence gets lucky and receives high reward. Sometimes a good sequence gets unlucky. The gradient estimate swings wildly between updates.

High variance → unstable training → slow or failed convergence.

### Baselines — The Fix

If all rewards are positive and large (say, between 90 and 100), REINFORCE says "increase probability of everything" — just more for the 100-reward actions and less for the 90-reward actions. But the signal is drowned in the large positive bias.

**Solution**: subtract a **baseline** b from the return:

```
∇J(θ) = E[ ∇ log π_θ(a|s) · (R - b) ]
```

If b is the average return, then:
- Actions better than average → positive signal → increase probability
- Actions worse than average → negative signal → decrease probability

This does not add bias to the gradient estimate (mathematically proven), but it dramatically reduces variance. The natural baseline is V(s) — the value function. This gives you the **advantage**:

A(s,a) = R - V(s) ≈ Q(s,a) - V(s)

The advantage function, from Series 03, is exactly the variance-reduced policy gradient signal.

### Actor-Critic — Combining the Best of Both Worlds

If you need V(s) as a baseline, you need to learn V(s). But then you have two neural networks:
- The **actor** (policy network): decides what to do
- The **critic** (value network): estimates how good the current state is

The actor updates using policy gradients with the critic's V(s) as baseline. The critic updates using TD learning (Series 04) to improve its V(s) estimates. They train together.

This is the **actor-critic** architecture, and it is the foundation of PPO.

**A3C / A2C** (Asynchronous / Advantage Actor-Critic): run multiple parallel workers, each collecting experience in their own environment copy, all updating a shared model. Parallelism speeds up data collection and provides decorrelated updates.

### Why Policy Gradients Are the Path to LLM RL

DQN and Q-learning learn value functions and derive policies from them (take the action with highest Q). Policy gradient methods learn policies directly. LLMs are already policies — they output action distributions. It is natural to optimize them with policy gradients.

Every RL method used for LLMs since InstructGPT is a policy gradient method:
- RLHF with PPO: clipped policy gradient (next series)
- GRPO: group-relative policy gradient (Series 09)
- DPO: implicit policy gradient derived from preference data (Series 12)
- REINFORCE-based variants: directly used in some open-source RL pipelines

The shift from value-based methods (DQN/Q-learning) to policy gradient methods (REINFORCE/Actor-Critic/PPO) is the shift from "learn what is good and derive behavior" to "directly optimize behavior." For LLMs, the second approach is more natural and more tractable.

### What You Should Carry Forward

Policy gradients optimize the policy directly rather than learning value functions. REINFORCE is simple but high-variance. Baselines (especially V(s)) reduce variance by turning raw returns into advantages. Actor-critic combines a policy network (actor) with a value network (critic). This is the foundation of PPO. LLMs are already policies — policy gradient methods are the natural fit for RL training.

---

# ACT 3 — RL MEETS LLMs

---

## Series 07: PPO — The Algorithm That Runs RLHF

**Act 3 — RL Meets LLMs**
*Connects backward to: Series 06 (policy gradients, actor-critic). Connects forward to: Series 08 (reward modeling), Series 09 (GRPO — the simplification), Series 12 (algorithm comparison)*

---

### The Problem PPO Solves

Series 06 established: policy gradients directly optimize the policy. The gradient says "move in this direction to increase expected reward." But how far do you move?

In supervised learning, a learning rate that is slightly too large just means slower convergence. In RL with policy gradients, a step that is too large is **catastrophic**. The policy changes, which changes the data distribution, which changes the gradient, which changes the next update. A single bad update can push the policy into a region of parameter space where it generates garbage. And it cannot recover — because now all its training data is garbage.

This is the **policy collapse problem**. Naive policy gradients are a cliff walk: one wrong step and you fall.

### Trust Regions — The Conceptual Solution

The idea: do not let the new policy be too different from the old policy. Constrain the update so the policy only changes a little bit at each step.

**TRPO** (Trust Region Policy Optimization, Schulman et al. 2015): mathematically constrain the KL divergence between old and new policy to be below a threshold. Guarantee improvement (or at least no catastrophic degradation) at each step.

Problem: TRPO is computationally expensive. It requires computing second-order derivatives (the Fisher information matrix) and solving a constrained optimization problem at each step.

### PPO — The Practical Approximation

**PPO** (Proximal Policy Optimization, Schulman et al. 2017) approximates TRPO's constraint with a simple clipping mechanism in the objective function. No second-order derivatives. No constrained optimization. Just a modified loss function.

**The probability ratio**:

```
r_t(θ) = π_θ(a_t|s_t) / π_θ_old(a_t|s_t)
```

This is: how much more (or less) likely is this action under the new policy compared to the old policy? If r = 1, the policies are identical for this action. If r = 1.5, the new policy is 50% more likely to take this action.

**The clipped objective**:

```
L_CLIP = E[ min( r_t · A_t, clip(r_t, 1-ε, 1+ε) · A_t ) ]
```

Where ε is typically 0.1 or 0.2.

What this does, intuitively:
- If the advantage A_t is positive (action was good), the loss wants to increase r_t (make the action more likely). But it clips r_t at 1+ε, preventing the probability from increasing too much.
- If the advantage A_t is negative (action was bad), the loss wants to decrease r_t (make the action less likely). But it clips r_t at 1-ε, preventing the probability from decreasing too much.

The `min` takes the more conservative estimate — the lower of the clipped and unclipped objectives. This creates a trust region around the old policy: you can improve, but only within bounds.

### Generalized Advantage Estimation (GAE)

Computing advantages requires estimating how much better an action was than average. There is a spectrum:

- **Monte Carlo**: wait for the episode to end, compute actual returns, subtract V(s). Unbiased but high variance (noisy).
- **TD(0)**: use r + γV(s') - V(s). Low variance but biased (because V is an approximation).

**GAE** blends these with a parameter λ (lambda):
- λ = 1: pure Monte Carlo (high variance, no bias)
- λ = 0: pure TD (low variance, high bias)
- λ = 0.95 (typical): mostly Monte Carlo but with some TD smoothing

This is a practical knob that engineers tune. It controls the variance-bias tradeoff in advantage estimation.

### The Four Models of PPO for RLHF

This is where PPO becomes expensive for LLM training. You need four models simultaneously in GPU memory:

| Model | Role | Size |
|---|---|---|
| **Policy model** | The LLM being optimized. Generates responses. | Full model (e.g., 70B) |
| **Reference model** | Frozen copy of the initial policy. Used for KL penalty. | Full model (e.g., 70B) |
| **Reward model** | Trained on human preferences. Scores responses. | Full model (e.g., 70B) |
| **Value model** | The critic. Estimates V(s) for advantage computation. | Full model (e.g., 70B) |

Four copies of a 70B model. The memory cost is staggering. This is why PPO-based RLHF has traditionally been accessible only to well-resourced labs.

### The KL Penalty — Why It Is Essential

The objective for PPO in RLHF is not just "maximize reward model score." It is:

```
Objective = Reward(response) - β · KL(π_θ || π_ref)
```

The KL penalty measures how much the current policy π_θ has diverged from the reference policy π_ref. β controls how strongly this penalty is applied.

**Without the KL penalty**: the policy quickly finds ways to exploit the reward model. It generates text that scores high on the RM but is gibberish, repetitive, or pathologically optimized for the RM's blind spots. This is **reward hacking** — the model maximizes the proxy (RM score) rather than the goal (actual helpfulness).

**With the KL penalty**: the policy is anchored to the reference model. It can improve, but it cannot drift too far from coherent language model behavior. The penalty acts as a regularizer, keeping the optimization well-behaved.

**Tuning β**: too high → the policy barely changes from the reference, wasting RL training. Too low → reward hacking and degenerate outputs. Finding the right β is a critical hyperparameter search, often done with adaptive methods that adjust β to maintain a target KL divergence.

### The PPO Training Loop

Step by step, one iteration of PPO for RLHF:

1. **Sample prompts** from a prompt dataset
2. **Generate responses** from the current policy (the LLM)
3. **Score responses** with the reward model
4. **Compute advantages** using the value model and GAE
5. **Compute KL penalty** between policy and reference model
6. **Update the policy** using the clipped PPO objective with advantages and KL penalty
7. **Update the value model** to better predict future rewards
8. Repeat

Each iteration involves a forward pass through all four models. The generation step is autoregressive (token by token), making it the most expensive part.

### PPO Instabilities in Practice

Things that go wrong when training LLMs with PPO:

- **Reward model collapse**: as the policy shifts, it generates text outside the RM's training distribution. The RM's scores become unreliable. The policy optimizes against garbage signals.
- **Value function divergence**: the critic's V(s) estimates become inaccurate, leading to bad advantage estimates, leading to bad policy updates. A cascading failure.
- **Entropy collapse**: the policy becomes too confident, always generating the same response. Exploration dies. The model gets stuck.
- **Mode collapse**: the policy converges to a narrow set of high-reward response patterns. Diversity is lost.

These are engineering challenges, not theoretical problems. Production RLHF systems have extensive monitoring, early stopping, and intervention mechanisms to catch these failures.

### Why PPO Dominated for 3 Years (2022-2024)

Despite its complexity and cost, PPO was the workhorse of RLHF because:
1. It reliably improved model quality over SFT alone
2. The clipping mechanism prevented catastrophic failures most of the time
3. InstructGPT's success (1.3B PPO-trained model preferred over 175B base model) proved the paradigm
4. No simpler alternative had been validated at frontier scale

Then DPO arrived (Series 12) offering simplicity without RL, and GRPO arrived (Series 09) offering PPO's quality with lower cost. PPO's dominance waned — but its principles are embedded in every successor.

### What You Should Carry Forward

PPO prevents catastrophic policy collapse via clipped probability ratios. It requires four models for RLHF: policy, reference, reward, and value. The KL penalty prevents reward hacking by anchoring to the reference model. The four-model memory cost is PPO's biggest practical limitation. GRPO's breakthrough (Series 09) is removing one of these four models. DPO's breakthrough (Series 12) is removing two.

---

## Series 08: Reward Modeling — Teaching the Algorithm What Good Means

**Act 3 — RL Meets LLMs**
*Connects backward to: Series 07 (PPO, the KL penalty). Connects forward to: Series 09 (GRPO/RLVR — eliminating the reward model), Series 12 (DPO — implicit reward), Series 13 (RLAIF — AI as labeler)*

---

### The Most Underappreciated Component

In any RL system, the reward function determines what the agent optimizes for. In RLHF, the reward model IS the alignment. The policy optimization algorithm (PPO, GRPO, whatever) is a search procedure. The reward model defines what it searches for.

A perfect RL algorithm with a bad reward model produces a perfectly optimized terrible model. The reward model is where human values enter the system, and it is where they get distorted.

### How Reward Models Are Trained

**Step 1 — Collect preference data**: humans are shown a prompt and two (or more) model responses. They select which response is better. This generates preference pairs: (prompt, chosen response, rejected response).

**Step 2 — Train the model**: the reward model is typically the same base architecture as the policy LLM, but with the language modeling head replaced by a regression head that outputs a single scalar. Given a prompt-response pair, it outputs a score.

The training objective is based on the **Bradley-Terry model** for pairwise preferences:

```
Loss = -log( σ( RM(prompt, chosen) - RM(prompt, rejected) ) )
```

Where σ is the sigmoid function. This says: the RM should score the chosen response higher than the rejected response, and the loss is low when this gap is large.

The RM does not learn absolute scores — it learns relative rankings. "A is better than B" is the training signal, not "A scores 8.5."

### Why Reward Modeling Is Hard

**Human inconsistency**: different annotators rank the same pair differently. Inter-annotator agreement on preference tasks is typically 60-75%. The RM is trained on noisy, contradictory labels.

**Context dependence**: "better" depends on the task. A concise answer is better for a simple factual question. A detailed answer is better for an explanation request. The RM must learn these contextual distinctions from data.

**Distribution shift**: the RM is trained on responses from the SFT model. During RL, the policy generates responses that are increasingly different from SFT outputs. The RM is now scoring out-of-distribution inputs. Its accuracy degrades. It starts assigning high scores to responses that superficially match patterns it associates with "good" but are actually low quality.

**Verbosity bias**: human annotators tend to prefer longer responses (more information seems more helpful). The RM learns this bias. During RL, the policy learns to be verbose — rambling to increase the RM score. This is why RLHF-trained models tend to be wordier than their SFT predecessors.

**Sycophancy**: annotators tend to prefer responses that agree with the premise of the question. The RM learns this. The policy learns to agree with the user even when the user is wrong. This is one of the most well-documented failure modes of RLHF.

### Goodhart's Law in RL

> "When a measure becomes a target, it ceases to be a good measure."

The RM is a measure of response quality. When it becomes the optimization target (via PPO or GRPO), it ceases to be a good measure. The policy finds ways to maximize the RM score that do not correspond to actual quality improvement.

This is **reward hacking**, and specific examples include:
- Generating responses with formatting that the RM associates with quality (bullet points, headers) regardless of content
- Including phrases that tend to score well ("I'd be happy to help!", "Great question!") regardless of whether they add value
- Generating slightly modified versions of high-scoring training examples

The KL penalty (Series 07) is the primary defense: by preventing the policy from drifting too far from the reference, you limit how much the policy can exploit the RM. But it is an imperfect defense — it trades off alignment quality against reward hacking risk.

### The Reward Model Overoptimization Curve

There is a consistent empirical finding (Gao et al., 2023): as you increase the KL budget (allow more RL optimization), the RM score increases monotonically — but actual quality (as judged by humans or a gold-standard evaluator) first increases, then decreases.

```
                    Actual Quality
                   ↑
                  /  \
                 /    \
                /      \
               /        \________
              /
    ─────────/──────────────────── → KL from reference
             Sweet spot   Overoptimized
```

There is a sweet spot where RL has improved the model but has not yet overoptimized against the RM. Finding this sweet spot is one of the key practical challenges of RLHF.

### Process Reward Models (PRMs) vs. Outcome Reward Models (ORMs)

**Outcome RM (ORM)**: scores the final complete response. This is the standard approach. Problem: for multi-step reasoning, you do not know which step was wrong. A math solution that gets the wrong answer might have been correct for 9 steps and wrong on step 10. The ORM gives a single score for the entire thing.

**Process RM (PRM)**: scores each intermediate step. "Step 1 is correct. Step 2 is correct. Step 3 has an error." This provides denser supervision for learning.

PRMs are more powerful but much harder to build:
- Labeling intermediate steps requires domain expertise (math, code, reasoning)
- Automated step verification is only possible for domains with verifiers (math, code)
- For open-ended tasks, step-level evaluation is ambiguous

PRMs show up prominently in reasoning model training (Series 11) and agentic RL (Series 14), where scoring intermediate tool calls and reasoning steps is essential.

### Where We Are Heading

The reward model is the bottleneck of RLHF — expensive to train, prone to hacking, degrades under distribution shift. The next two major innovations in RL for LLMs both address this:

- **GRPO + RLVR** (Series 09): for tasks with verifiable answers (math, code), replace the learned RM with a programmatic checker. No learned reward model = no reward hacking.
- **DPO** (Series 12): eliminate the RM entirely by reparameterizing the RL objective so the policy itself implicitly acts as the reward model.
- **RLAIF** (Series 13): replace human labelers with AI labelers, making RM data collection scalable.

### What You Should Carry Forward

The reward model is where human values enter the system and where they get distorted. It is trained on noisy human preferences via Bradley-Terry pairwise comparisons. Key failure modes: distribution shift, verbosity bias, sycophancy, reward hacking (Goodhart's Law). The overoptimization curve means more RL is not always better — there is a sweet spot. PRMs (process rewards) score each step, ORMs (outcome rewards) score only the end. The weakness of learned reward models drives the innovations in the next act.

---

---

# ACT 4 — THE MODERN ERA

---

## Series 09: GRPO — Killing the Critic, Scaling Reasoning

**Act 4 — The Modern Era**
*Connects backward to: Series 07 (PPO's four-model problem), Series 08 (reward model limitations). Connects forward to: Series 10 (DeepSeek-R1), Series 11 (test-time compute), Series 12 (algorithm comparison)*

---

### The Insight: The Group Is the Baseline

Recall from Series 07: PPO needs a value model (critic) to compute advantages. The advantage tells you how much better an action is than average. The value model estimates that average — V(s).

GRPO (Group Relative Policy Optimization, Shao et al. 2024, DeepSeek) asks: what if we could compute advantages without learning V(s)?

The answer is deceptively simple. Instead of estimating V(s) with a neural network:

1. For each prompt, generate **G responses** (G is the group size, typically 8-64)
2. Score each response with a reward function: r_1, r_2, ..., r_G
3. Compute the advantage for response i: **A_i = (r_i - mean(r)) / std(r)**

That is it. The group mean is the baseline. Response better than the group average → positive advantage → increase its probability. Response worse than the group average → negative advantage → decrease its probability.

No learned critic. No value model. The group of sampled responses provides the baseline for free.

### Why This Works — And Why It Took So Long

The group-relative advantage is a natural baseline that has two important properties:

**Low variance**: because you are comparing within a group sampled from the same prompt, many sources of noise cancel out. All G responses share the same prompt, the same prompt difficulty, the same implicit task requirements. The only variation is in the response itself. This makes the advantage estimate cleaner than Monte Carlo returns (which are noisy single-trajectory estimates).

**No learning required**: the PPO value model must be trained alongside the policy, adding complexity and instability. The value model can diverge, provide bad advantage estimates, and cascade failures through the system. GRPO sidesteps all of this.

Why did it take so long to discover? It didn't — GRPO is closely related to **REINFORCE Leave-One-Out (RLOO)**, where you use the other N-1 trajectories as the baseline for the Nth trajectory. The ideas have been in the RL literature for decades. What GRPO contributed was:
1. Combining group-relative baselines with PPO's clipping mechanism
2. Demonstrating it at LLM scale
3. Pairing it with verifiable rewards for reasoning tasks

The hype around GRPO as a "new algorithm" is partly overstated. The engineering contribution — making it work at scale for LLMs — is what matters.

### The GRPO Loss Function

GRPO keeps PPO's clipping and KL penalty:

```
L_GRPO = E[ min( r_t · A_group, clip(r_t, 1-ε, 1+ε) · A_group ) ] - β · KL(π_θ || π_ref)
```

Where:
- r_t = π_θ(a|s) / π_θ_old(a|s) (probability ratio, same as PPO)
- A_group = (r_i - mean(r)) / std(r) (group-relative advantage, replaces PPO's GAE)
- The KL penalty against the reference model (same purpose as PPO)
- Clipping (same purpose as PPO — prevent large updates)

Everything is the same as PPO except the advantage computation. That one change removes an entire model from the pipeline.

### Memory and Compute Implications

| Method | Models in GPU Memory | Relative Cost |
|---|---|---|
| PPO for RLHF | Policy + Reference + Reward + Value (4) | Baseline |
| GRPO with RM | Policy + Reference + Reward (3) | ~75% |
| GRPO with RLVR | Policy + Reference (2) | ~50% |

The ~25% memory reduction from removing the value model is significant. But the real game-changer is what comes next.

### RLVR — When the Reward Is Verifiable

**Reinforcement Learning with Verifiable Rewards (RLVR)** is what happens when you pair GRPO with a programmatic reward function instead of a learned reward model.

For certain tasks, you can check whether the answer is correct without a neural network:
- **Math**: does the answer equal the correct answer? Compare strings or numerical values. Binary: 1 or 0.
- **Code**: does the code pass the test suite? Run it. Binary: pass or fail.
- **Formal verification**: does the proof check? Run the verifier.
- **Constrained generation**: does the output satisfy the constraint (word count, format, specific structure)?

When you can verify the answer programmatically, you do not need a reward model at all. The reward function is a deterministic checker. Now you only need **two models**: the policy and the reference.

### Why RLVR Changes Everything

**No reward hacking**: you cannot hack a deterministic verifier the way you can hack a learned reward model. The math answer is either correct or it is not. No Goodhart's Law. No sycophancy. No verbosity bias. The reward signal is clean, honest, and unbounded in its capacity to train the model.

**No distribution shift**: a learned RM degrades when the policy generates out-of-distribution text. A math verifier works regardless of how the model formats its answer. The reward signal never degrades.

**No human labels for reward**: you need problems with known answers, but you do not need humans to rank model outputs. Math competition problems, coding challenges, formal proofs — these have verifiable answers by nature.

**The limitation**: RLVR only works for tasks with checkable outputs. Open-ended generation (creative writing, summarization, general conversation) does not have a deterministic verifier. For these tasks, you still need a learned RM or DPO.

This creates a natural split in the LLM post-training world:
- **Reasoning capabilities** (math, code, logic): train with GRPO + RLVR
- **General alignment** (helpfulness, safety, tone): train with PPO + RM, DPO, or RLAIF

Most modern frontier models use both.

### What You Should Carry Forward

GRPO removes the value model from PPO by using the group of sampled responses as the baseline. Closely related to RLOO (not truly new, but scaled effectively). RLVR replaces the learned reward model with a deterministic verifier — no reward hacking, no distribution shift, but only works for verifiable tasks. GRPO + RLVR = just two models (policy + reference). This is the architecture behind DeepSeek-R1.

---

## Series 10: DeepSeek-R1 — What Pure RL Actually Produces

**Act 4 — The Modern Era**
*Connects backward to: Series 09 (GRPO, RLVR). Connects forward to: Series 11 (test-time compute), Series 12 (algorithm comparison), Series 15 (production implications)*

---

### The Experiment That Changed the Field

In early 2024, DeepSeek ran an experiment that should not have worked as well as it did.

**DeepSeek-R1-Zero**: Take a base language model (DeepSeek-V3-Base). Apply GRPO with only verifiable rewards — math and code correctness. No supervised fine-tuning. No human-written demonstrations. No reward model. No human labels of any kind.

Just a base model and a verifier. Let RL do the rest.

### What Happened

The model's math performance on AIME 2024 (a notoriously difficult American math competition):

| Checkpoint | AIME 2024 pass@1 |
|---|---|
| DeepSeek-V3-Base (before RL) | 15.6% |
| After thousands of RL steps | 71.0% |
| With majority voting (consensus@64) | 86.7% |
| OpenAI o1-0912 for comparison | ~80-85% |

From 15.6% to 71.0% on a hard math benchmark. No human demonstrations. No labeled data. Just RL with a binary reward: is the math answer correct or not.

### The Emergent Behaviors — This Is the Important Part

During RL training, R1-Zero spontaneously developed behaviors that no one trained it to exhibit:

**Self-verification**: the model began checking its own work. "Let me verify this by substituting back into the original equation..." This was not in any training data. The model discovered that checking work improves the probability of correct answers, so RL reinforced it.

**Reflection and backtracking**: the model began recognizing its own errors mid-solution. "Wait, that doesn't seem right. Let me reconsider..." It learned to abandon incorrect reasoning paths and restart. This was not demonstrated or instructed.

**Extended reasoning**: the model's response length grew dramatically during RL training. It learned that longer, more careful reasoning produces better answers. The average response length increased from hundreds to thousands of tokens.

**"Aha moments"**: the model occasionally generates text like "Hmm, wait, I realize I was approaching this wrong. Let me try a completely different method." These are genuine strategy shifts discovered through RL, not memorized patterns.

### Why These Behaviors Emerge

RL with verifiable rewards creates a powerful selection pressure: strategies that lead to correct answers get reinforced. Strategies that lead to incorrect answers get suppressed.

Self-verification leads to catching errors before submitting → more correct answers → positive reward → behavior gets reinforced.

Reflection leads to recovering from mistakes → more correct answers → positive reward → behavior gets reinforced.

Extended reasoning leads to more careful solutions → more correct answers → positive reward → behavior gets reinforced.

The model did not learn these as rules. It learned them as patterns that correlate with reward. RL discovered that these cognitive strategies are useful, the same way a human student might discover that double-checking their work improves test scores.

This is the most important empirical result in LLM training since RLHF. It demonstrates that **RL can unlock capabilities that were latent in the base model** without any human demonstration of those capabilities.

### R1-Zero's Failure Modes

R1-Zero was not production-ready:

- **Language mixing**: it would switch between English and Chinese mid-response, sometimes mid-sentence. The base model was bilingual; without SFT to enforce language consistency, RL did not penalize mixing.
- **Poor readability**: reasoning traces were dense, repetitive, and hard for humans to follow. RL optimized for correctness, not readability.
- **Format inconsistency**: no consistent structure to responses. No clear separation between reasoning and final answer.

These are problems that supervised fine-tuning solves — formatting, style, consistency. R1-Zero showed that RL alone can produce capability but not polish.

### DeepSeek-R1 (Full Pipeline)

To make R1-Zero production-ready, DeepSeek used a multi-stage pipeline:

**Stage 1 — Cold-start SFT**: fine-tune the base model on a small dataset of high-quality chain-of-thought examples. This does not teach the model to reason — it teaches it the format. "Here is what a clean, readable reasoning trace looks like."

**Stage 2 — GRPO**: apply RL with verifiable rewards (math, code). The model now has both the format from SFT and the capability boost from RL.

**Stage 3 — Rejection sampling**: use the RL-trained model to generate many reasoning traces. Keep the ones that are both correct and well-formatted. Use these as new SFT data.

**Stage 4 — Second GRPO round**: another round of RL on the SFT-refreshed model.

The pipeline: **SFT → RL → SFT → RL**.

Each stage addresses a different problem:
- SFT provides format and readability
- RL provides capability and emergent reasoning strategies
- Rejection sampling bridges them — using RL's capability to generate SFT data

Result: DeepSeek-R1 matches OpenAI o1-1217 on most reasoning benchmarks.

### Distillation — Reasoning in Smaller Models

DeepSeek took R1's reasoning traces and used them as supervised training data for smaller models (7B, 14B, 32B parameters).

The results were striking: the distilled 32B model matched or exceeded much larger non-distilled models on reasoning tasks. The reasoning capability that RL discovered in the large model transferred to smaller models via standard supervised training on the reasoning traces.

This has major practical implications: you do not need to run RL on every model. You can run RL on one large model, generate reasoning data, and distill the capability down to smaller, deployable models.

### The Cost Asymmetry

DeepSeek reportedly trained R1 for a fraction of what OpenAI spent on o1. GRPO + RLVR is cheaper than PPO + learned RM:
- Fewer models in memory
- No reward model training pipeline
- No human preference data collection
- Verifiable rewards are free to compute

This democratized reasoning model training. Open-source projects replicated aspects of R1 within months.

### What You Should Carry Forward

R1-Zero proved that RL with verifiable rewards can unlock emergent reasoning capabilities (self-verification, reflection, extended thinking) from a base model with no human demonstration. R1's full pipeline (SFT → RL → SFT → RL) shows that supervised and RL training are complementary, not competing. Distillation transfers RL-discovered reasoning to smaller models. This is the blueprint for how reasoning models are built.

---

## Series 11: Test-Time Compute and Reasoning Models

**Act 4 — The Modern Era**
*Connects backward to: Series 10 (DeepSeek-R1, emergent reasoning). Connects forward to: Series 12 (algorithm comparison), Series 15 (production cost implications)*

---

### Two Ways to Make AI Smarter

For years, the recipe was simple: bigger model, more data, more training compute. Scale up pre-training. This is **training-time compute scaling**.

Reasoning models introduce a second axis: **test-time compute scaling**. Instead of making the model bigger, let it think longer on each query. For a fixed set of model weights, more thinking = better answers on hard problems.

This is a paradigm shift. The model's intelligence is no longer fixed at deployment — it is variable at inference, controlled by how many thinking tokens you allocate.

### How Reasoning Models Work

The architecture is straightforward:

1. The model receives a prompt
2. It generates a long internal chain-of-thought (CoT) — the "thinking" or "extended thinking" tokens
3. It generates the final answer based on its reasoning

The thinking tokens are where the work happens. The model breaks the problem into steps, considers approaches, checks work, backtracks on errors, and synthesizes a conclusion. This is exactly the behavior that R1-Zero learned emergently (Series 10), but now trained deliberately at scale.

**How the thinking is trained**: RL. The model is trained with RL to generate reasoning traces that lead to correct final answers. The reward signal is answer correctness. The model learns that certain reasoning patterns (checking work, considering edge cases, trying multiple approaches) correlate with correct answers.

### The Practical Compute Tradeoff

| Query Type | Standard Model | Reasoning Model | Worth It? |
|---|---|---|---|
| "What's the capital of France?" | Fast, correct | Slow, correct, overthinks | No |
| "Solve this competitive math problem" | Fast, often wrong | Slow, much more accurate | Yes |
| "Debug this complex race condition" | Misses subtle issues | Traces through execution paths | Yes |
| "Summarize this paragraph" | Fast, good | Slow, same quality | No |

Reasoning models cost more per query (more tokens generated = more compute = higher API cost = higher latency). The cost is justified only when the problem is hard enough that additional thinking actually improves the answer.

**The engineering decision**: route complex queries to reasoning models, simple queries to standard models. This is **adaptive compute** — dynamically allocating inference resources based on query difficulty. Most production systems need this routing to control costs.

### Test-Time Search Strategies

Beyond simple extended CoT, there are more sophisticated ways to spend test-time compute:

**Best-of-N sampling**: generate N complete responses. Score each with a verifier or reward model. Return the best one. Simple. Effective. Embarrassingly parallel. The downside: N times the compute, and the responses are independently sampled — no learning between attempts.

**Process reward model (PRM) guided search**: generate reasoning step by step. After each step, score it with a PRM. If a step scores low, backtrack and try a different step. This is more compute-efficient than best-of-N because it prunes bad paths early.

**Monte Carlo Tree Search (MCTS) for LLMs**: the same algorithm that powered AlphaGo. Build a tree of possible reasoning paths. Each node is a reasoning step. Expand the most promising branches. Backpropagate quality scores. Choose the path with the highest accumulated quality.

MCTS for LLMs is conceptually powerful but practically challenging:
- The branching factor is enormous (many possible next reasoning steps)
- Evaluating a node requires running the model forward
- The interaction between tree structure and autoregressive generation is complex

This is active research (2025-2026), with multiple labs exploring how to make tree search practical for LLM reasoning.

### The Connection to RL — Test-Time Compute Is RL at Inference

All of these strategies share a common structure: you are searching over the model's output distribution to find the best trajectory. This is exactly what RL does during training — except now you are doing it at inference without gradient updates.

- Best-of-N = sampling multiple rollouts and taking the best (like collecting trajectories in RL, but keeping only the best)
- PRM-guided search = using a value function to evaluate intermediate states (like the critic in actor-critic RL)
- MCTS = planning via simulation and evaluation (like model-based RL with a learned world model)

Test-time compute scaling is the inference-time counterpart of RL training. The model is not getting smarter (weights are frozen) — it is getting more attempts and better search.

### What This Means for AI Engineers

When you choose to use a reasoning model (o1, o3, Claude with extended thinking, Gemini with thinking), you are making a compute allocation decision:

- **You are paying for RL-trained test-time compute**. The "thinking tokens" are generated by a model whose thinking patterns were shaped by RL. The model learned to think this way because it got higher rewards for correct answers.
- **The cost scales with thinking time**. 10,000 thinking tokens costs 10× more than 1,000. For hard problems, this is worth it. For easy problems, it is waste.
- **The quality improvement is real but bounded**. More thinking helps up to a point, then plateaus. There is a ceiling — the model's fundamental capabilities do not change, only its thoroughness.

### What You Should Carry Forward

Test-time compute is the second scaling axis: instead of making models bigger, let them think longer. Reasoning models use RL-trained extended chain-of-thought before answering. Worth the cost for hard problems, wasteful for simple ones. Test-time search strategies (Best-of-N, PRM-guided search, MCTS) are RL-like search at inference time. The engineering decision is adaptive routing: send hard queries to reasoning models, easy ones to standard models.

---

## Series 12: RLHF vs DPO vs GRPO — The Alignment Algorithm Landscape

**Act 4 — The Modern Era** (also connects to Act 3)
*Connects backward to: Series 07 (PPO), Series 08 (reward modeling), Series 09 (GRPO). Connects forward to: Series 13 (RLAIF), Series 15 (production implications)*

---

### The Map

By mid-2026, there are multiple paths to post-training alignment. Each makes different tradeoffs between quality, cost, complexity, and applicability. Here is the full landscape.

### RLHF with PPO — The Original

**How it works**: SFT → train reward model on human preferences → optimize policy with PPO using RM as reward signal.

**Models required**: 4 (policy, reference, reward, value)

**Strengths**:
- Most battle-tested approach at frontier scale
- Fine-grained control over optimization (KL penalty, clipping, GAE)
- Established theoretical foundations

**Weaknesses**:
- Highest memory and compute cost
- Complex engineering (4 models, many hyperparameters)
- Reward model degrades under distribution shift
- Still used by some frontier labs for general alignment

### DPO — Direct Preference Optimization

**The key insight**: the standard RLHF objective (maximize reward minus KL penalty) has a closed-form solution. You can derive what the optimal policy would look like without ever training a reward model or running RL.

Instead of: train RM → run PPO with RM → get aligned policy
DPO says: directly train the policy on preference data with a modified loss function.

**How it works**: given preference pairs (prompt, chosen response, rejected response), DPO trains the policy with:

```
Loss = -log σ( β · [log π_θ(chosen)/π_ref(chosen) - log π_θ(rejected)/π_ref(rejected)] )
```

This loss increases the probability of the chosen response relative to the rejected response, scaled by how much these probabilities have shifted from the reference model. The β parameter controls the strength of the KL constraint — same role as in PPO.

**Models required**: 2 (policy, reference)

**What DPO eliminates**:
- No reward model (reward is implicit in the policy)
- No RL training loop (standard supervised training with a modified loss)
- No value model (no advantages to compute)

**Strengths**:
- Simple to implement — just a loss function on preference data
- 2 models instead of 4 (major cost reduction)
- No RL infrastructure required (no rollouts, no online generation during training)
- Matches RLHF quality on most general alignment benchmarks

**Weaknesses**:
- **Offline only**: trains on a fixed preference dataset. Cannot generate new responses during training to explore policy space. If the optimal behavior is far from what is in the training data, DPO may not find it.
- **May underperform at extreme scale**: there is an active debate about whether DPO matches PPO quality at frontier model scale. Current evidence suggests PPO may retain an edge for the largest models, but DPO is sufficient for most practical applications.
- **Not suited for reasoning/verifiable tasks**: DPO optimizes based on preference pairs, not binary correctness. For math and code where RLVR works, GRPO + RLVR is more natural and effective.

### KTO — Kahneman-Tversky Optimization

**The limitation of DPO/RLHF**: they require **paired** preference data — "A is better than B for this prompt." Collecting paired comparisons is expensive and logistically complex.

**KTO** (Ethayarajh et al., 2024) works with **unpaired** data: you just need examples labeled as "good" or "bad" independently. No need to compare two responses to the same prompt.

The loss function is inspired by prospect theory (from behavioral economics): humans are loss-averse — they weigh losses more heavily than equivalent gains. KTO bakes this asymmetry into the training objective.

**Practical advantage**: much easier to get training data. Any feedback signal that says "this response is good" or "this response is bad" is sufficient. Thumbs-up/thumbs-down from users. Automated quality filters. Binary classifiers.

**Where it fits**: resource-constrained settings where paired preference data is hard to collect. Increasingly used in production fine-tuning.

### GRPO + RLVR — For Reasoning and Verifiable Tasks

(Covered in depth in Series 09)

**Models required**: 2 (policy, reference) with verifiable rewards; 3 with learned RM

**Strengths**:
- Most effective approach for math, code, and formal reasoning
- No reward hacking (with verifiable rewards)
- Emergent reasoning capabilities (self-verification, reflection)
- Lower cost than PPO

**Weaknesses**:
- Only applicable to tasks with checkable outputs
- Requires generating G responses per prompt (compute-intensive during training)
- Group size is a hyperparameter that affects quality

### ORPO — Odds Ratio Preference Optimization

**ORPO** combines SFT and preference optimization into a single training stage. Instead of first doing SFT then doing DPO/RLHF, ORPO modifies the SFT loss to simultaneously teach the model good behavior and penalize bad behavior.

**Advantage**: simpler pipeline, fewer stages, lower total compute. **Disadvantage**: fewer control knobs, less flexibility.

Suitable for: quick fine-tuning when you want alignment without the full RLHF or multi-stage pipeline.

### The Decision Framework

| Your Situation | Use This |
|---|---|
| Frontier model, general alignment, maximum quality | RLHF (PPO) or DPO |
| Math, code, logic — verifiable answers | GRPO + RLVR |
| Open-source fine-tuning, limited compute | DPO or KTO |
| Unpaired good/bad data only | KTO |
| Quick fine-tuning, simple pipeline | ORPO |
| Reasoning model training (DeepSeek-R1 style) | GRPO + RLVR with multi-stage pipeline |

### The Hybrid Reality

In practice, frontier models use multiple methods:
- **Stage 1**: SFT on high-quality demonstrations
- **Stage 2**: DPO or RLHF for general alignment (helpfulness, safety, tone)
- **Stage 3**: GRPO + RLVR for reasoning capabilities (math, code)
- **Stage 4**: possibly another DPO/RLHF round for final polish

The methods are complementary. DPO handles the tasks where human judgment matters (is this response helpful?). RLVR handles the tasks where correctness can be verified (is this answer right?).

### The Active Debate

**Does eliminating the reward model via DPO sacrifice quality at extreme scale?**

Arguments for "yes":
- PPO with a good RM can explore beyond the preference dataset — it generates new responses and improves based on RM feedback. DPO is limited to the offline dataset.
- At frontier scale, the RM may capture nuances of quality that a fixed preference dataset does not.

Arguments for "no":
- DPO results are competitive on nearly every published benchmark
- The engineering simplicity of DPO means more iterations, faster experimentation
- Online variants of DPO (generate new data, relabel, retrain) close the exploration gap

Current consensus (mid-2026): for models up to ~70B, DPO is sufficient and preferred for its simplicity. At frontier scale (hundreds of billions of parameters), labs still experiment with PPO-based RLHF for potential marginal gains.

### What You Should Carry Forward

The alignment algorithm landscape has four main options: RLHF (PPO), DPO, GRPO+RLVR, and KTO. Each eliminates different components (reward model, value model, paired data). The choice depends on your task (verifiable vs. open-ended), your resources (compute budget), and your data (paired preferences vs. binary feedback). Most production systems combine multiple methods across training stages.

---

---

# ACT 5 — AGENTIC RL AND THE BIGGER PICTURE

---

## Series 13: Constitutional AI and RLAIF

**Act 5 — Agentic RL and the Bigger Picture**
*Connects backward to: Series 08 (reward modeling limitations), Series 12 (alignment landscape). Connects forward to: Series 14 (agentic RL), Series 15 (production implications)*

---

### The Human Labeler Bottleneck

RLHF requires human preference data. Humans rank model responses. This data trains the reward model. The reward model guides RL.

At frontier scale, this bottleneck becomes severe:
- Models generate millions of responses per day during training
- Human labelers can process hundreds per day
- Annotation quality varies between individuals, shifts, and contractors
- Annotation cost scales linearly with volume
- Certain domains (medicine, law, advanced science) require expensive domain experts

The question: can AI replace human labelers?

### Constitutional AI — The Anthropic Approach

**Constitutional AI** (Anthropic, Bai et al. 2022): instead of asking humans "which response is better?", give the AI model a set of principles — a **constitution** — and have it evaluate its own outputs.

The process:

**Step 1 — Self-critique**: the model generates a response, then critiques its own response according to the constitution. "The constitution says to be helpful. Was my response helpful? The constitution says not to be harmful. Could my response cause harm?"

**Step 2 — Self-revision**: the model revises its response based on its own critique. This generates (original, revised) pairs.

**Step 3 — AI preference labeling**: use the critiques and revisions to create preference data. The revised response is "chosen," the original is "rejected." Or use a separate AI model to judge which is better according to the principles.

**Step 4 — Train as usual**: use this AI-generated preference data to train a reward model or do DPO. The rest of the pipeline is identical to standard RLHF.

### RLAIF — Generalizing AI Feedback

**RLAIF** (Reinforcement Learning from AI Feedback) is the generalization: replace human labelers with AI labelers for any part of the feedback pipeline.

Variants:
- **AI labelers for RM training data**: use a capable model (e.g., GPT-4, Claude) to rank responses instead of human annotators
- **AI labelers for direct preference data**: generate DPO training pairs using AI judgment
- **Constitutional self-improvement**: the model critiques and improves itself in a loop

### Quality: RLAIF vs. RLHF

Recent research (2024-2026) shows AI feedback approaches human feedback quality for many tasks:

**Where RLAIF works well**:
- Factual accuracy (AI can verify facts)
- Code quality (AI can reason about correctness)
- Following instructions (AI can check constraint satisfaction)
- Harmfulness detection (AI is calibrated on safety guidelines)

**Where RLAIF still struggles**:
- Cultural nuance that the AI does not share
- Novel harm categories the AI has not been trained on
- Tasks where "better" is deeply subjective (humor, creativity, emotional resonance)
- Edge cases where AI preferences systematically differ from human preferences

### The Self-Improvement Loop

There is a recursive dynamic here that is both exciting and concerning:

```
Better model → generates better feedback → trains even better model → generates even better feedback → ...
```

If model capability improves, the quality of AI feedback improves, which improves the next model version, which generates better feedback. Alignment becomes a capability that **scales with model capability**.

**The risk**: if AI preferences systematically differ from human preferences in subtle ways, these differences **compound** across iterations. Each generation of the model drifts slightly further from human values, and each generation generates training data for the next that is slightly more drifted. This is the "AI value drift" concern.

In practice: human-in-the-loop checkpoints remain standard. AI generates the bulk of feedback data, but humans validate samples and set the constitutional principles. Pure unsupervised self-improvement without human checkpoints is not deployed at frontier labs (as of mid-2026).

### The Practical Implication for Teams

RLAIF makes custom alignment **financially accessible**. Previously, custom RLHF required hiring annotators, building annotation interfaces, managing quality control. Now:

1. Write a constitution (a set of principles for your use case)
2. Use a capable AI to generate preference data according to the constitution
3. Run DPO (or GRPO, or PPO) on the AI-generated preferences

This puts alignment customization within reach of small teams and individual developers. The constitution is the lever — it encodes what "good" means for your specific application.

### What You Should Carry Forward

RLAIF replaces expensive human labelers with AI feedback, making custom alignment financially accessible. Constitutional AI provides principles-based self-evaluation. AI feedback quality approaches human quality for many tasks but has blind spots in cultural nuance and novel harm categories. The self-improvement loop is powerful but requires human checkpoints to prevent value drift.

---

## Series 14: Agentic RL — Training Agents End-to-End

**Act 5 — Agentic RL and the Bigger Picture**
*Connects backward to: Series 02 (MDP formulation), Series 09 (GRPO), Series 10 (emergent behaviors). Connects forward to: Series 15 (production), Series 16 (synthesis)*

---

### The Formulation — Same Math, New Context

Everything in this series is the MDP from Series 02 with a different skin:

| MDP Component | Agentic RL Instantiation |
|---|---|
| **State** | Conversation history + tool outputs + memory |
| **Action** | Next tool call (function name + arguments) |
| **Transition** | Tool returns output → appended to state |
| **Reward** | Task completion: did the agent achieve the goal? |
| **Episode** | One complete task attempt |
| **Policy** | The LLM agent |
| **Environment** | The tool ecosystem + external services |

An LLM agent deciding which tool to call next is mathematically identical to an RL agent deciding which action to take. The algorithms from previous series (PPO, GRPO) apply directly. The difficulty is in the environment, not the math.

### Why Agentic RL Is Harder Than Single-Turn RL

Single-turn RLHF: one prompt → one response → one reward. Clean. Fast. Easy to collect data for.

Agentic RL: one task → 20-50 steps → sparse reward at the end. Multiple things make this harder:

**1. Long horizons and credit assignment**

An agent working on a coding task might:
1. Read the issue description
2. Search the codebase
3. Read 5 files
4. Plan an approach
5. Make changes to 3 files
6. Run tests
7. Fix a bug
8. Run tests again
9. Submit

If the tests pass at step 9, which of the 9 steps was responsible for success? If the tests fail, which step caused the failure? Was it a bad plan (step 4)? Wrong file identified (step 3)? Bad code change (step 5)?

Credit assignment over long trajectories is one of the hardest problems in RL. In single-turn RLHF, the response is short enough that credit assignment is manageable. In agent trajectories, it is often intractable.

**2. Sparse rewards**

In single-turn RLHF, every response gets a reward score. In agentic RL, reward comes only at the end — when the task is completed or abandoned. Steps 1 through 8 get zero reward. Only step 9 produces a signal.

This means most of the trajectory is "dark" — the agent receives no feedback during execution. Learning from sparse rewards is slow and sample-inefficient. The agent needs many complete trajectories to learn which intermediate actions are good.

**3. Non-stationary environment**

The tools and services the agent interacts with change over time:
- Web pages update
- API responses change
- Code repositories evolve
- Other agents or users modify shared state

The transition function P(s'|s,a) is not fixed. The same action in the same state might produce different results at different times. This violates the stationarity assumption that most RL algorithms rely on.

**4. Partial observability**

The agent cannot see the full state. It sees tool outputs — which are incomplete views of reality:
- A search result is not the full codebase
- An API response is not the full server state
- A web page is not the full website
- An error message is not the full program state

This is a POMDP (Series 02). The agent must infer missing state from partial observations, maintain beliefs about what it cannot see, and act under uncertainty about the true environment state.

### Process Reward Models for Agents

The solution to sparse rewards: score intermediate steps, not just the final outcome.

**Process Reward Models (PRMs)** for agents evaluate each tool call and reasoning step:
- "Reading this file was useful — it contained the relevant code" (positive)
- "This search query returned irrelevant results" (negative)
- "The plan is reasonable given the information so far" (positive)
- "This code change introduced a new bug" (negative)

PRMs provide dense reward signals that make learning tractable. Instead of waiting 50 steps for a single reward, the agent gets feedback at every step.

**The challenge**: building PRMs for agent tasks is hard. Who labels whether an intermediate step was good? Options:
- **Automated verification**: run tests after each code change, check if search results are relevant
- **AI evaluation**: use a capable model to judge step quality
- **Hindsight labeling**: after the trajectory is complete, go back and label which steps contributed to the outcome

This is an active research area. No one has fully solved dense reward for general agent tasks.

### What Is Actually Deployed (2025-2026)

Several production systems use forms of agentic RL:

**Coding agents**: trained or evaluated on trajectories of issue → code change → test results. Tools include file read/write, terminal execution, search. Reward is test passage or human acceptance.

**Research agents**: trained on trajectories of question → web search → document reading → synthesis. Tools include search, browser, file operations. Reward is answer quality or factual accuracy.

**AlphaProof** (DeepMind): an RL-trained system that proved mathematical theorems at IMO 2024 competition level. Actions are proof steps. Reward is proof verification. Pure RL on a formal environment.

### Multi-Agent RL

When multiple LLM agents work together, each with its own policy, you enter **multi-agent RL** territory:

- A planning agent decides what to do
- A coding agent implements it
- A review agent checks the work
- A testing agent validates

Each agent is a separate policy. They must coordinate. Their actions affect each other's states. The emergent dynamics can be complex:

**Coordination**: agents must learn to communicate effectively, divide work, and avoid conflicts
**Competition**: if agents are optimized independently with different reward functions, they may work at cross purposes
**Emergent behavior**: agent groups can develop unexpected communication protocols, role specialization, and collaborative strategies

Multi-agent RL for LLM systems is early-stage research becoming applied engineering. The challenges are both technical (how to train multiple policies that interact) and architectural (how to design the communication and coordination infrastructure).

### The Harness Is the Environment

This is the critical insight for AI engineers:

**The harness (tool infrastructure, APIs, environment setup) IS the RL environment.** When you build an agent harness, you are designing the MDP:
- The tools you provide determine the **action space**
- The information you return from tools determines the **state transitions**
- The success criteria you define determine the **reward function**
- The context management determines the **observation space**

Bad harness design = bad agent behavior, regardless of RL training quality. If the tools return uninformative outputs, the state transitions are opaque. If the success criteria are misspecified, the reward function is wrong. If the context fills up too fast, the agent loses important state information.

**Designing a good agent harness is RL environment design.** The same principles apply: informative observations, clear action effects, well-defined rewards, manageable horizon length.

### What You Should Carry Forward

Agentic RL is the same MDP framework applied to multi-step tool use. It is harder than single-turn RL due to long horizons, sparse rewards, non-stationary environments, and partial observability. PRMs provide dense rewards for intermediate steps but are hard to build. The harness is the environment — harness design is RL environment design. Multi-agent RL is the frontier of agent systems research.

---

## Series 15: RL in Production — What It Means When You Call an API

**Act 5 — Agentic RL and the Bigger Picture**
*Connects backward to: everything. Connects forward to: Series 16 (synthesis)*

---

### Everything You Interact With Was Shaped by RL

Every frontier model you call via API — GPT-4, Claude, Gemini, DeepSeek — went through RL post-training. The model's behavior, quirks, strengths, and failure modes are products of that RL training. Understanding RL helps you understand why models behave the way they do.

### RL Artifacts in API Behavior

**Sycophancy**: the model agrees with you even when you are wrong.
→ *RL explanation*: the reward model was trained on human preferences. Humans prefer responses that agree with them. The RM learned this bias. PPO/DPO optimized the policy to maximize agreement. The model learned that "agreeing = high reward."

**Verbosity bias**: the model gives longer responses than necessary.
→ *RL explanation*: human annotators tend to prefer longer responses (more detail = more helpful, in their annotation heuristic). The RM learned "longer = better." The policy learned to be verbose.

**Safety over-refusal**: the model refuses harmless requests that look superficially dangerous.
→ *RL explanation*: the RM heavily penalizes any response that could be construed as harmful. The penalty for refusing a harmless request is small. The penalty for producing a harmful response is large. The policy learned to over-refuse because the asymmetric cost function favors caution.

**Formatting preferences**: bullet points, headers, structured responses.
→ *RL explanation*: annotators preferred well-structured responses. The RM associates formatting with quality. The policy learned that formatting increases reward, sometimes applying it where it does not help.

**"I'd be happy to help!" and similar phrases**: you see these constantly.
→ *RL explanation*: these phrases correlate with higher RM scores (perceived helpfulness). The policy learned to include them. They are RL reward-hacking artifacts — superficial signals of helpfulness that got reinforced.

### Why Different Providers Feel Different

GPT-4 feels different from Claude, which feels different from Gemini. Same architecture family (transformer). Similar pre-training approaches. The difference is primarily in RL post-training:

- **Different reward models**: trained on different annotator populations, with different guidelines, different definitions of "better"
- **Different KL budgets**: how much the policy was allowed to diverge from the base model
- **Different alignment methods**: PPO vs DPO vs GRPO vs hybrids
- **Different constitutions**: different principles for safety, helpfulness, harmlessness tradeoffs

When you notice that Claude is more cautious about safety refusals, or GPT-4 is more willing to engage with edge cases, or Gemini has a different conversational style — you are observing the outputs of different RL training configurations.

### Model Updates That Change Behavior Without Changing Architecture

You use a model for months. One day, the same prompt gives a different response. The model version has not changed (or changed only with a patch). What happened?

Often: **another round of RL post-training**. The lab collected more preference data, updated the RM, ran more PPO/DPO, and deployed the updated weights. The model's capabilities may be identical, but its RL-shaped behaviors shifted.

This is why model behavior can change between API versions in ways that are not captured by benchmark scores. Benchmarks measure capabilities. RL post-training shapes behaviors, tone, refusal boundaries, verbosity, and style. These are harder to benchmark and more noticeable to users.

### Understanding Reasoning Model Costs

When you use o1, o3, Claude with extended thinking, or Gemini with thinking mode:

**What you are paying for**: RL-trained test-time compute. The "thinking tokens" are generated by a model whose reasoning patterns were optimized by RL to produce correct answers. Each thinking token costs compute.

**When to use it**: complex multi-step problems where the model is likely to get it wrong without extended reasoning. Code debugging with subtle issues. Mathematical proofs. Complex planning with many constraints.

**When not to use it**: simple factual questions, formatting tasks, summarization, translation. The reasoning model will produce a correct answer, but so would a standard model — at a fraction of the cost and latency.

**Budget tokens matter**: some APIs let you control the maximum thinking tokens. More thinking generally helps up to a point, then plateaus or adds noise. The optimal budget depends on problem difficulty. This is an engineering decision that requires experimentation.

### Fine-Tuning Is RL (Whether You Call It That or Not)

When you fine-tune a model with DPO on your preference data, you are doing RL. The DPO loss function is a reparameterization of the RLHF objective. You are optimizing a policy to maximize implicit reward from preference data under a KL constraint against a reference model.

When you fine-tune with KTO, same thing — RL with a different loss function.

When you do rejection sampling (generate many responses, keep the best, fine-tune on those), you are doing a simple form of RL — selecting high-reward trajectories and increasing their probability.

The library may call it "fine-tuning." The mathematical operation is reinforcement learning. Understanding this helps you:
- Choose the right method for your task (Series 12)
- Set hyperparameters that make physical sense (KL penalty β, clip range ε)
- Debug training failures (is the policy collapsing? Is it reward hacking? Is the reference model too constraining?)
- Know when your fine-tuning is working vs. when it is overfitting to reward artifacts

### Prompt Engineering as Reward Shaping

When you write a system prompt that says "Be concise. Give direct answers. Do not use bullet points unless asked," you are **shaping the reward landscape** within the model's existing RL-trained behavior space.

The model's policy was trained with RL to satisfy a general reward model. Your prompt constrains the behavior within the space of policies the model has learned. You are not retraining — you are conditioning the policy on specific state (the system prompt) that activates different behavioral modes.

Understanding this helps you write better prompts:
- The model has RL-trained "modes" — you are selecting among them
- Fighting against RL-trained behaviors (e.g., trying to make a safety-tuned model be less cautious) is fighting against the reward function. You will generally lose.
- Working with RL-trained behaviors (e.g., activating the model's reasoning mode by asking for step-by-step thinking) is leveraging the reward function.

### What You Should Carry Forward

Every model behavior you observe is an artifact of RL post-training. Sycophancy, verbosity, over-refusal, formatting preferences — all products of the reward model and optimization process. Different providers feel different because their RL configurations differ. Model updates can change behavior via RL re-training without changing architecture. Reasoning model costs are test-time compute costs for RL-trained thinking. Fine-tuning with DPO/KTO is RL. Prompt engineering is reward shaping within RL-trained behavioral space.

---

## Series 16: Synthesis — RL as the Engine of Self-Improvement in AI

**Act 5 — Agentic RL and the Bigger Picture**
*Connects backward to: everything.*

---

### One Story, Told Across Five Acts

This guide covered 15 series of material. Here is the single thread that runs through all of it:

**RL is the mechanism by which AI systems improve beyond what human demonstration can provide.**

Supervised learning teaches models to imitate. Pre-training teaches models to predict the next token. These create capable base models — but base models do not follow instructions, do not refuse harmful requests, do not reason carefully, and do not use tools effectively.

Everything that turns a base model into the product you use is RL:
- **Instruction following**: RL (PPO/DPO) shaped the model to follow user intent
- **Safety and alignment**: RL drew the refusal boundaries and calibrated helpfulness
- **Reasoning capability**: RL (GRPO+RLVR) unlocked emergent self-verification and reflection
- **Extended thinking**: RL trained the model to generate useful reasoning traces
- **Agent behavior**: RL (or RL-like trajectory optimization) trains tool use and multi-step planning

### The Full Timeline

```
Q-Learning (1989)
     ↓
DQN — Neural networks meet RL, Atari from pixels (2013)
     ↓
PPO — Stable policy gradients via clipping (2017)
     ↓
RLHF + PPO — Aligned language models, InstructGPT (2022)
     ↓
DPO — Eliminate reward model and RL loop (2023)
     ↓
GRPO + RLVR — Eliminate value model, verifiable rewards (2024)
     ↓
DeepSeek-R1 — Emergent reasoning from pure RL (2024)
     ↓
Reasoning models — Test-time compute scaling (2024-2025)
     ↓
Agentic RL — End-to-end agent training (2025-2026)
     ↓
Multi-agent RL — Coordinating autonomous agent systems (frontier)
```

Each step used the same mathematical foundation — the MDP. State, action, transition, reward, policy. The application context changed. The algorithms evolved. The core framework never changed.

### What Is True Right Now (Mid-2026)

**Reasoning models trained with RLVR are the frontier.** DeepSeek-R1, OpenAI o3, Claude with extended thinking, Gemini with thinking — all use RL-trained extended reasoning. The capability gap between reasoning and non-reasoning models on hard problems is large and consistent.

**Agentic RL is the next wave.** Training LLM agents end-to-end on multi-step trajectories is moving from research to production. Coding agents, research agents, and planning agents are being trained with RL-style optimization on real task trajectories.

**The alignment method landscape has stabilized.** DPO for general alignment, GRPO+RLVR for reasoning, RLAIF for scalable feedback. Frontier labs use hybrids. The old RLHF (PPO + four models) is increasingly a reference implementation rather than the default choice.

**Test-time compute is reshaping infrastructure.** The engineering of inference systems now accounts for variable compute per query. Routing, adaptive compute allocation, and budget management for thinking tokens are production concerns.

**Distillation is the deployment strategy.** Train one large model with RL, generate high-quality reasoning data, distill into smaller models. The RL-trained large model is the teacher. The distilled small model is the deployment target.

### What an AI Systems Engineer Needs to Carry From All of This

**1. The behavior of every model you call is a product of its RL post-training.** When the model does something surprising — good or bad — the RL reward function is often the explanation. Sycophancy, verbosity, over-refusal, formatting quirks: all RL artifacts.

**2. When you choose a reasoning model, you are choosing to pay for RL-trained test-time compute.** The thinking tokens are not free exploration — they are the output of a policy that was RL-trained to think in ways that lead to correct answers. This is worth the cost for hard problems and waste for easy ones.

**3. When you build agents, you are building RL environments.** The harness is the MDP. Tools define the action space. Tool outputs define state transitions. Success criteria define the reward function. Bad environment design produces bad agent behavior regardless of model quality.

**4. When you fine-tune with DPO, KTO, or GRPO, you are doing RL.** Whether the library calls it "fine-tuning" or "alignment" or "preference optimization," the underlying operation is reinforcement learning — optimizing a policy under a reward signal with a KL constraint against a reference. Understanding this helps you choose methods, set hyperparameters, and debug failures.

**5. RL is not a separate topic from the rest of AI engineering.** It is the backbone. Pre-training creates the raw material. RL creates the product. The frontier of AI capability — reasoning, agency, self-improvement — is the frontier of RL applied to language models.

### The One Sentence Summary

Supervised learning teaches models what humans do. Reinforcement learning teaches models to do it better than humans demonstrated — and that is where every frontier capability comes from.

---

*End of the 16-series guide.*
*The story of RL in AI is one story: an agent, an environment, a reward, and the relentless optimization that turns capable base models into the systems that are reshaping how software is built.*
