# Let's Build GPT From Scratch, in Code, Spelled Out

> **Source:** Andrej Karpathy's ~2-hour coding walkthrough  
> **Core Idea:** Build a decoder-only Transformer from zero — character by character — training it on Tiny Shakespeare, covering every building block from tokenization to multi-head attention to residual connections.

---

## 1. Overview & Motivation

ChatGPT is a **language model**: it models the probability distribution over sequences of tokens and generates text by repeatedly predicting "what comes next." Under the hood, it uses a **Transformer** neural network, introduced in the landmark 2017 paper *"Attention Is All You Need."*

This video builds a **character-level GPT** on the Tiny Shakespeare dataset (~1 MB of concatenated Shakespeare works). The architecture is identical in structure to production GPT models — the only differences are scale:

| Dimension | This Video | GPT-3 |
|---|---|---|
| Parameters | ~10 million | 175 billion |
| Tokens trained on | ~300K | 300 billion |
| Vocabulary | 65 characters | ~50,000 subword tokens |
| Training time | ~15 min on A100 | Months on thousands of GPUs |

**nanoGPT** is Karpathy's minimal codebase: just two files (~300 lines each) — `model.py` (the Transformer) and `train.py` (the training loop) — that can reproduce GPT-2's performance when trained on OpenWebText.

---

## 2. Tokenization: From Text to Integers

### What Tokenization Means
Tokenization converts raw text (a string) into a sequence of integers according to some **vocabulary** (codebook). The model never sees characters directly — it operates entirely on integer IDs.

### Character-Level Tokenizer (Used in This Video)
- Extract all unique characters from the dataset → 65 total (space, newline, punctuation, uppercase/lowercase letters).
- Build a simple lookup table: character → integer and integer → character.
- `encode("hi there")` → `[46, 47, ...]`; `decode([46, 47, ...])` → `"hi there"`.

### Subword Tokenizers (Used in Practice)
- **SentencePiece** (Google): encodes text into subword units, not individual characters.
- **tiktoken / Byte Pair Encoding** (OpenAI): GPT-2/GPT-4 use ~50,000 subword tokens.
- Trade-off: larger vocabulary → shorter sequences (more meaning per token) vs. smaller vocabulary → longer sequences.

> [Added context: BPE works by iteratively merging the most frequent pair of adjacent tokens in the training corpus, building up a vocabulary of subword units. This lets the model handle rare/novel words by breaking them into known subword pieces, while common words remain single tokens.]

### Encoding the Dataset
The entire Tiny Shakespeare text is encoded into a single 1D `torch.Tensor` of integers. This tensor is split 90/10 into **training** and **validation** sets to monitor overfitting.

---

## 3. Batching: Chunks of Data for Training

### Block Size (Context Length)
The Transformer never sees the entire dataset at once. Instead, it trains on **chunks** of length `block_size` (e.g., 8 characters). A single chunk of `block_size + 1` characters actually contains `block_size` training examples:

```
Chunk: [18, 47, 56, 57, 58, 1, 15, 47, 58]  (9 chars)

Example 1: context=[18]               → predict 47
Example 2: context=[18, 47]           → predict 56
Example 3: context=[18, 47, 56]       → predict 57
...
Example 8: context=[18, 47, ..., 47]  → predict 58
```

Training on all context lengths from 1 to `block_size` means the Transformer learns to generate starting from just a single character — crucial for inference when we begin generation from scratch.

### Batch Dimension
Multiple independent chunks are stacked into a **batch** (e.g., `batch_size = 4`), yielding a `(B, T)` tensor where B=batch size and T=block size. All sequences in a batch are processed independently and in parallel on the GPU.

---

## 4. The Bigram Language Model (Baseline)

Before building a Transformer, the video starts with the simplest possible model: a **bigram model**.

### How It Works
- A single `nn.Embedding(vocab_size, vocab_size)` table.
- Given a token (integer), it plucks out the corresponding row → a vector of `vocab_size` logits.
- Each logit is the score for what the next character should be.
- These logits are interpreted as *unnormalized log-probabilities* — the model only looks at the **immediately preceding character** and ignores all other context.

### Training
- **Loss function:** Cross-entropy between predicted logits and actual next character.
  - A randomly initialized model with 65 classes should have loss ≈ −ln(1/65) ≈ **4.17** (since every character is equally likely). This serves as a sanity check.
- The model is trained with standard PyTorch: `optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)`.
- After training: loss drops to ~**2.5**, meaning the model has learned basic character statistics (e.g., after a space, vowels are more likely than 'z').

### Generation
- Start with a `(1, 1)` tensor of zeros (a newline token).
- Repeatedly: get logits for the last position → softmax → sample → append sampled token.
- Output: gibberish, but with character-frequency statistics that roughly match English.

### Limitations
The bigram model is **memoryless** — each prediction only depends on the single previous character. For real language, we need tokens to *communicate* across positions. That's where self-attention comes in.

---

## 5. Mathematical Trick: Weighted Aggregation of Past Context

Before implementing attention, the video builds intuition for how tokens can efficiently "look at" previous tokens.

### The Problem
For position `t`, we want to compute some function of all tokens at positions `0..t`. A naive approach: loop over all previous positions. This is slow and wasteful.

### The Matrix Multiplication Trick
Instead, use a **lower-triangular matrix** and matrix multiplication:

```python
# T = block_size (e.g. 8)
tril = torch.tril(torch.ones(T, T))  # lower triangular of 1s
weights = tril / tril.sum(dim=1, keepdim=True)  # normalize rows → each row sums to 1
# Now: weights @ x  gives a running average of all past (including current) tokens
```

- Row `t` of the weight matrix has values `1/(t+1)` in columns `0..t`, and `0` afterwards.
- This computes a **uniform average** of all past token embeddings for each position.
- Crucially, position `t` never sees information from position `t+1` or later → **causal/autoregressive** property.

### Softmax Formulation
The same operation can be expressed using `softmax`:

```python
tril = torch.tril(torch.ones(T, T))
wei = torch.zeros(T, T)
wei = wei.masked_fill(tril == 0, float('-inf'))  # future positions → -∞
wei = F.softmax(wei, dim=-1)                     # -∞ → 0 after softmax; rest normalizes
```

This is the foundation of self-attention: instead of uniform weights, we'll learn **data-dependent** weights.

---

## 6. Self-Attention: The Core Mechanism

### Intuition
Every token at every position emits three vectors:
- **Query (Q):** "What am I looking for?"
- **Key (K):** "What do I contain?"
- **Value (V):** "What information do I provide if you attend to me?"

Attention scores are computed as dot products between queries and keys: if a query and a key align well, that position gets a high weight, meaning its value contributes more to the output.

### Implementation (Single Head)

```python
class Head(nn.Module):
    def __init__(self, head_size):
        super().__init__()
        self.key   = nn.Linear(n_embd, head_size, bias=False)
        self.query = nn.Linear(n_embd, head_size, bias=False)
        self.value = nn.Linear(n_embd, head_size, bias=False)
        self.register_buffer('tril', torch.tril(torch.ones(block_size, block_size)))

    def forward(self, x):
        B, T, C = x.shape
        k = self.key(x)    # (B, T, head_size)
        q = self.query(x)  # (B, T, head_size)
        # Attention scores
        wei = q @ k.transpose(-2, -1)             # (B, T, T)
        wei = wei * (C ** -0.5)                    # SCALED attention
        wei = wei.masked_fill(self.tril[:T, :T] == 0, float('-inf'))  # causal mask
        wei = F.softmax(wei, dim=-1)
        # Weighted aggregation of values
        v = self.value(x)  # (B, T, head_size)
        out = wei @ v      # (B, T, head_size)
        return out
```

### Key Design Decisions

**No bias in Q/K/V projections:** Standard practice — biases are typically omitted.

**`register_buffer` for the triangular mask:** The mask is not a learnable parameter but needs to move to the GPU with the model. PyTorch's `register_buffer` handles this.

**Scaled Attention (÷ √d_k):**
Without scaling, when Q and K are unit Gaussian, their dot product has variance proportional to `head_size`. Large variance → softmax output becomes **one-hot** (peaky), meaning each token only attends to a single other token. Dividing by `√head_size` keeps the variance at ~1, ensuring softmax outputs are **diffuse** — especially important at initialization so the model can learn from distributed gradients.

> [Added context: This "scaled dot-product attention" is one of the most critical numerical stability tricks in Transformers. Without it, gradients through softmax become vanishingly small in the non-max positions, severely slowing training.]

**Causal Masking (the triangular mask):**
Setting future positions to `-inf` before softmax ensures they get weight 0 — a token at position `t` can only attend to positions `0..t`. This is what makes it a **decoder** block (autoregressive). An **encoder** block would delete this line, allowing all positions to attend to all other positions.

### Self-Attention vs. Cross-Attention
- **Self-attention:** Q, K, V all come from the same source `x`. Tokens attend to each other.
- **Cross-attention:** Q comes from `x`, but K and V come from a different source (e.g., an encoder's output). Used in encoder-decoder Transformers for tasks like translation.

### Results After Adding Self-Attention
Training loss drops from ~2.5 (bigram) to ~**2.4**. A modest improvement — tokens are now communicating, but we need more capacity.

---

## 7. Multi-Head Attention

### Concept
Instead of one large attention head, run **multiple smaller heads in parallel** and concatenate their outputs.

```python
class MultiHeadAttention(nn.Module):
    def __init__(self, num_heads, head_size):
        super().__init__()
        self.heads = nn.ModuleList([Head(head_size) for _ in range(num_heads)])
        self.proj = nn.Linear(n_embd, n_embd)  # projection back into residual pathway

    def forward(self, x):
        out = torch.cat([h(x) for h in self.heads], dim=-1)
        out = self.proj(out)
        return out
```

- With `n_embd = 32` and `num_heads = 4`, each head has `head_size = 8`.
- Each head learns to look for different patterns: consonants, vowels, positional relationships, etc.
- Concatenated output: 4 × 8 = 32 = `n_embd`.

> [Added context: This is analogous to "group convolutions" in CNNs — instead of one large convolution filter, multiple smaller filters operate independently, providing a richer representation.]

### Results
Loss drops to ~**2.28**. Multiple communication channels help because tokens have many different types of relationships to discover.

---

## 8. The Feed-Forward Network (Per-Token Computation)

After attention (communication), tokens need time to **think about** the information they've gathered. The feed-forward network (FFN) applies a per-token MLP:

```python
class FeedForward(nn.Module):
    def __init__(self, n_embd):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_embd, 4 * n_embd),
            nn.ReLU(),
            nn.Linear(4 * n_embd, n_embd),  # projection back to residual dim
        )
    def forward(self, x):
        return self.net(x)
```

- **Communication** (multi-head attention) → tokens exchange information.
- **Computation** (feed-forward) → each token independently processes what it learned.
- The inner dimension is 4× `n_embd` (per the original paper: 512 → 2048).

### Results
Loss drops to ~**2.24**.

---

## 9. Transformer Blocks: Interspersing Communication and Computation

A **Block** bundles attention + feed-forward into a repeatable unit:

```python
class Block(nn.Module):
    def __init__(self, n_embd, n_head):
        super().__init__()
        head_size = n_embd // n_head
        self.sa = MultiHeadAttention(n_head, head_size)
        self.ffwd = FeedForward(n_embd)
        self.ln1 = nn.LayerNorm(n_embd)
        self.ln2 = nn.LayerNorm(n_embd)

    def forward(self, x):
        x = x + self.sa(self.ln1(x))    # residual + pre-norm attention
        x = x + self.ffwd(self.ln2(x))  # residual + pre-norm feed-forward
        return x
```

Multiple blocks are stacked sequentially: the Transformer becomes a deep network that alternates communication → computation → communication → computation.

---

## 10. Residual (Skip) Connections

### The Problem with Depth
Stacking many blocks creates a deep network that suffers from **optimization difficulties** — gradients vanish or explode, making training unstable.

### The Solution: Residual Connections
Instead of `x = f(x)`, use `x = x + f(x)`:
- The input `x` flows through a **residual pathway** (the identity shortcut).
- The transformation `f(x)` is added on top.
- During backpropagation, the addition node distributes gradients equally to both branches — creating a **gradient superhighway** from the loss all the way to the input.

### Visualization
```
Input ────────────────────> (+) ──> Output
               |              ↑
               └── f(x) ──────┘
```

- At initialization, `f(x)` contributes ~nothing (weights are small), so gradient flows cleanly through the skip connection.
- Over training, the residual blocks gradually "come online" and start contributing.
- This comes from the 2015 ResNet paper (*Deep Residual Learning for Image Recognition*).

### Results
Loss drops to ~**2.08**. The network is now deep enough that overfitting becomes visible (train loss < val loss).

---

## 11. Layer Normalization

### Batch Norm vs. Layer Norm
- **Batch Norm** (from the "Make More" series): normalizes each feature across the batch dimension → columns of the activation matrix become zero-mean, unit-variance.
- **Layer Norm:** normalizes each example across the feature dimension → **rows** become zero-mean, unit-variance.

Implementation difference is literally changing `dim=0` to `dim=1` in the normalization code.

### Advantages of Layer Norm
- No distinction between training and test time (no running mean/variance buffers needed).
- Works naturally with variable batch sizes and sequence lengths.
- Each token is normalized independently.

### Pre-Norm Formulation (Deviation from Original Paper)
The original "Attention Is All You Need" paper applies LayerNorm **after** the transformation ("post-norm"). Modern practice applies it **before** ("pre-norm"), which is more stable:

```python
# Pre-norm (what we implement):
x = x + self.sa(self.ln1(x))

# Post-norm (original paper):
x = self.ln(x + self.sa(x))
```

### A Final Layer Norm
A LayerNorm is applied at the very end of the Transformer, right before the final linear layer that decodes into vocabulary logits.

### Results
Loss drops to ~**2.06**.

---

## 12. Dropout: Regularization for Deep Networks

**Dropout** (from the 2014 paper by Srivastava et al.) randomly sets a fraction of activations to zero during each forward pass:

- Effectively trains an **ensemble of subnetworks**.
- At test time, all neurons are active — the ensemble is "merged."
- Applied in three places:
  1. After the attention weights (softmax output) — randomly prevents some tokens from communicating.
  2. At the end of multi-head attention (before residual addition).
  3. At the end of the feed-forward network (before residual addition).

---

## 13. Scaling Up: The Final Model

### Hyperparameters

| Parameter | Small (during development) | Scaled Up |
|---|---|---|
| Batch size | 4 | 64 |
| Block size | 8 | 256 |
| Embedding dim (`n_embd`) | 32 | 384 |
| Number of heads | 4 | 6 |
| Head size | 8 | 64 |
| Number of layers | 4 | 6 |
| Dropout | 0.0 | 0.2 |
| Learning rate | 1e-3 | 3e-4 |

### Results
- Validation loss: **1.48** (down from 2.07 before scaling).
- ~10 million parameters total.
- Trained for ~15 minutes on an A100 GPU.
- Generated Shakespeare is recognizably structured: characters speak in turns, words look English, but the text is nonsensical when actually read.

---

## 14. Encoder vs. Decoder Transformers

The original *"Attention Is All You Need"* paper describes an **encoder-decoder** architecture for machine translation (French → English):

### Encoder
- Takes the French sentence.
- Uses self-attention **without** causal masking — all tokens can attend to all other tokens.
- Produces a rich representation of the input.

### Decoder
- Takes the English sentence (generated so far).
- Uses **causal masked** self-attention (lower-triangular mask) — autoregressive.
- Has an additional **cross-attention** layer: queries from the decoder, keys/values from the encoder output.
- This lets the decoder "look at" the encoded French while generating English.

### What We Built
A **decoder-only** Transformer — no encoder, no cross-attention. This is exactly what GPT is: it takes a sequence and autoregressively continues it. There's nothing to "encode" — just a text file to imitate.

---

## 15. From This Video to ChatGPT

### Pre-Training (What We Did)
- Train a decoder-only Transformer on raw text.
- The result is a **document completer** — it babbles text that statistically resembles its training data.
- GPT-3 is architecturally ~identical to what we built, just 10,000–1,000,000× larger.

### Fine-Tuning (What We Didn't Do)
After pre-training, ChatGPT goes through additional stages:
1. **Supervised Fine-Tuning (SFT):** Train on curated question-answer pairs so the model learns to respond helpfully instead of just completing documents.
2. **Reward Modeling:** Humans rank multiple model outputs; a separate model learns to predict human preferences.
3. **RLHF (Reinforcement Learning from Human Feedback):** PPO (Proximal Policy Optimization) fine-tunes the model to generate responses that score high on the reward model.

> [Added context: The fine-tuning data is much smaller than pre-training data (perhaps tens of thousands of examples vs. trillions of tokens), but these models are very "sample efficient" at this stage because the pre-training already built a strong representation of language.]

### nanoGPT
The repository Karpathy released focuses purely on the **pre-training** stage. The `model.py` file is nearly identical to what was built in this video, with two main differences:
1. Multi-head attention is implemented as a single batched operation (adding a "heads" dimension to the tensor) instead of separate `Head` modules concatenated — more efficient, mathematically identical.
2. Uses **GELU** nonlinearity instead of ReLU (to match OpenAI's checkpoints).

---

## 16. Key Takeaways

1. **A Transformer is just a stack of blocks**, each containing multi-head self-attention (communication) followed by a feed-forward network (computation), with residual connections and layer normalization.

2. **Self-attention is a weighted aggregation mechanism.** Each token emits a query, key, and value. Dot-product of query with all keys → softmax → weights → weighted sum of values. The causal mask enforces autoregressive generation.

3. **Scaled attention (÷ √d_k) is critical.** Without it, softmax becomes peaky at initialization, collapsing gradients and preventing learning.

4. **Multi-head attention provides multiple independent communication channels.** Tokens have many different types of relationships to discover, and each head can specialize.

5. **Residual connections are what make deep Transformers trainable.** They create a gradient superhighway from the loss to the input, with residual blocks gradually contributing during training.

6. **Layer Normalization normalizes features per-token.** Pre-norm (before the transformation) is more stable than the original paper's post-norm formulation.

7. **The architecture is scale-invariant.** The same code, with different hyperparameters, spans from a 10M-parameter toy model to GPT-3's 175B parameters.

8. **Character-level modeling is educational but impractical.** Real systems use subword tokenizers (BPE, SentencePiece) with vocabularies of ~50K–100K tokens for efficiency.

9. **Pre-training alone produces a "document completer," not an assistant.** The model babbles in the style of its training data. Turning it into ChatGPT requires fine-tuning stages (SFT, reward modeling, RLHF).

10. **The Transformer is a decoder-only architecture for GPT.** The full encoder-decoder architecture from the original paper is designed for tasks like translation; GPT drops the encoder and cross-attention entirely.
