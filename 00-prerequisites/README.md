# Chapter 0: Prerequisites

> Prerequisites: This course has no formal prerequisites, but it is designed for someone who is deeply familiar with the material in 15-213 or equivalent, highly skilled in the language they choose to implement their compiler in, capable of managing programming projects that are long in timeline, and comfortable with C and some GPU programming. …
>
> — the syllabus

This chapter is not part of the syllabus. It collects what the syllabus assumes you already know, so you can check yourself before chapter 1 and know where to read up. Nothing here is graded.

**By the end you can:** tell whether you are ready for chapter 1, and fill any gaps with the readings in [Where to learn more](#where-to-learn-more).

## Contents

- [Before you start](#before-you-start)
- [Lessons](#lessons)
  - [Lesson 1: what a compiler is](#lesson-1-what-a-compiler-is)
  - [Lesson 2: numbers in a machine](#lesson-2-numbers-in-a-machine)
  - [Lesson 3: graphs, substitution and intervals](#lesson-3-graphs-substitution-and-intervals)
  - [Lesson 4: C, index arithmetic and loop nests](#lesson-4-c-index-arithmetic-and-loop-nests)
  - [Lesson 5: what models compute](#lesson-5-what-models-compute)
  - [Lesson 6: hardware and performance](#lesson-6-hardware-and-performance)
- [Self-check](#self-check)
- [Glossary](#glossary)
- [Where to learn more](#where-to-learn-more)
- [Sources](#sources)

## Before you start

**Your implementation language.** Whatever you pick, you must be able to:

- key a hash map by a tuple of objects compared by identity;
- write recursive functions over a graph, and get around the recursion limit when graphs are deep;
- build text and run a C compiler from your program;
- load a shared library and call a function in it (a foreign function interface).

**Working on a long project.** Every chapter's compiler must still pass every earlier chapter's tests, so set this up before chapter 1: version control with a commit after each working step; one command that runs every `.uir` file from every week and reports failures; and the habit of deleting code that later chapters make unnecessary. Style is graded too ("can it be simpler?"), and complexity added early costs you every week after.


## Lessons

### Lesson 1: what a compiler is

**A translator with a middle.** A compiler turns a program in one language into an equivalent program in another, usually faster or closer to the hardware. It works in three stages:

1. **Front end:** read the source text (parse it) and check it. Chapter 1 starts with a parser for UIR: split each line into tokens (names, numbers, brackets), then parse with one recursive function per construct; on `(` or `[`, call yourself until the matching `)` or `]`. If you have never written a recursive-descent parser, write one for arithmetic expressions first ([Aho et al. 2006](#sources), ch. 2).
2. **Middle:** turn it into an *intermediate representation* and improve it with a series of *passes*.
3. **Back end:** print the result in the target language (*code generation*).

Why not translate source straight to target? Because the interesting work, finding facts about the program and rewriting it into a better one, needs a form that makes those facts easy to see. Source text is written for people, and machine code for hardware; neither is convenient to reason about. The middle form also decouples the two ends: one IR can be fed by several front ends and printed by several back ends.

**What an IR is.** An intermediate representation (IR) is the data structure a compiler uses to represent a program while it works on it. Every pass reads it and writes it, so its design decides how easy each pass is. A good IR has:

- **Explicit data flow:** for every value, you can find what it is computed from and what uses it.
- **Explicit effects:** reads and writes of memory, and the order they must happen in, are visible, not implied by statement order.
- **Types:** each value carries what the compiler needs to know about it (here: dtype, shape, bounds).
- **One way to say each thing:** if two programs mean the same, they should look the same as often as possible, so that rules only have to match one form.
- **A text form**, for writing tests and reading what the compiler did. This course's text form is [UIR](../uir.md).

**Three shapes of IR.** Here is the same expression, `(a + b) * (a + b)`, in the three common styles:

```text
tree (an abstract syntax tree)     linear (three-address code, SSA)     graph (this course)
  mul                                t0 = add a b                          %s = add %a %b
  ├── add                            t1 = mul t0 t0                        %p = mul %s %s
  │   ├── a
  │   └── b
  └── add
      ├── a
      └── b
```

- **A tree** mirrors the source. It is easy to build from a parser, but a value used twice appears twice.
- **Linear code** is a list of instructions, each computing one value from named inputs. In *static single assignment* form (SSA) every name is assigned exactly once, so each name *is* a value, and data flow is just name lookup (the standard construction is [Cytron et al. 1991](#sources)). LLVM's IR is SSA ([Lattner & Adve 2004](#sources)). Where control flow merges, SSA needs φ-nodes to pick a value; this course's IR has no branches, so you never need them.
- **A graph** keeps only the data flow: nodes are operations, edges point at inputs, and there is no order beyond what the edges force. This is close to the "sea of nodes" used in Java's HotSpot compiler ([Click & Paleczny 1995](#sources)), and it is what UOps are. Written as text, a graph looks like SSA; the difference is that the order of the lines means nothing, only the `%` references do. Any order that puts definitions before uses is the same graph.

Moving between them is mechanical. Lowering a tree to SSA, giving equal subtrees one name, is a few lines, and the result is already a graph (giving equal values one name is *value numbering*; chapter 1's hash-consing does the same for UOps):

```python
def to_ssa(tree, code: list, names: dict) -> str:
    """Lower an expression tree to three-address code; equal subtrees get one name."""
    # shortcut: assumes no input variable is named like a temporary (t0, t1, ...)
    if isinstance(tree, str):            # a variable or constant is already a name
        return tree
    op, *args = tree
    key = (op, *(to_ssa(a, code, names) for a in args))
    if key not in names:                 # compute each distinct value once
        names[key] = f"t{len(names)}"
        code.append(f"{names[key]} = {' '.join(key)}")
    return names[key]

code: list[str] = []
to_ssa(("mul", ("add", "a", "b"), ("add", "a", "b")), code, {})
assert code == ["t0 = add a b", "t1 = mul t0 t0"]
```

**Passes.** A pass is one step over the IR. An *analysis* computes facts without changing anything (the type of every value, the range of an index, which loads read which buffer). A *transformation* rewrites the program into an equivalent one (fold `2 + 3` into `5`, move a computation out of a loop). Compilers run many small passes, often repeating them until nothing changes (a *fixed point*). The rule every transformation must keep: **the program's meaning does not change**, including at the numeric edges of Lesson 2.

**Levels and lowering.** An ML compiler starts from a high-level program ("multiply these two `256 × 256` tensors") and ends at C or GPU code with loops and index arithmetic. Each step down is *lowering*: replacing an operation by a more detailed equivalent, which loses structure (it is no longer obvious that this is a matrix multiply) and gains control (now the compiler can choose loop order). Many compilers use a different IR at each level. This course uses one, the UOp graph, at every level: chapter 4–5 programs have shapes and tensor operations, rangeify lowers them to the loops and memory of chapters 2–3, and the renderer prints those as C or HIP.

**What an ML compiler decides.** A model is a graph of tensor operations. Running it fast means deciding:

- **Kernels:** which operations run together as one loop nest, so that intermediate results stay in registers or cache (*fusion*), and which results are written to memory (*materialized*).
- **Schedule:** for each kernel, the loop order, the tile sizes, which loops become vector lanes, threads or GPU workgroups.
- **Code:** printing each kernel, compiling it, and having a *runtime* allocate buffers and launch kernels in order.

Halide made the split between *what* to compute (the algorithm) and *how* (the schedule) explicit ([Ragan-Kelley et al. 2013](#sources)); TVM applies it to deep learning ([Chen et al. 2018](#sources)); tinygrad, which this course follows, does all three with rewrites on one graph IR.

**Interpreters and compilers.** An interpreter walks the program and computes values directly. A compiler translates the program into another language, here C and later HIP, and lets another compiler produce machine code. Both start from the same graph; the difference is whether the walk produces values or text. A *JIT* (just-in-time) compiler compiles while the program runs, which is what your runtime does from chapter 2. Your compiler will do both: it folds what it can at compile time, and generates code for the rest.

### Lesson 2: numbers in a machine

Lesson 1 was about the program; this lesson is about the values it computes. Your compiler will compute with `i32` and `f32` values in two places: in its own constant folding, and in the C and HIP code it generates. The two must agree exactly. That requires knowing what the hardware does, not what mathematics says.

**Integers are two's complement.** An `i32` is 32 bits. Bit patterns `0` to `2^31 − 1` mean themselves; a pattern `x` above that means `x − 2^32`. So the range is `[−2^31, 2^31 − 1]`, and adding 1 to the largest value gives the smallest one: arithmetic wraps around modulo `2^32`. The same bits serve signed and unsigned values; only comparisons, division, right shifts, and widening or conversion differ ([CS:APP](#sources) ch. 2).

C makes signed overflow *undefined behavior*: the compiler may assume it never happens and optimize on that assumption ([N1570](#sources) §6.5p5). GCC and Clang make it wrap if you pass `-fwrapv`. This course defines `i32` arithmetic to wrap, so your generated C must be compiled that way, or written to use unsigned arithmetic.

**Division truncates in C and floors in Python.** C rounds the quotient toward zero: `-7 / 2` is `-3`, and the remainder takes the sign of the dividend, so `-7 % 2` is `-1` ([N1570](#sources) §6.5.5). Python's `//` rounds toward negative infinity: `-7 // 2` is `-4`, and `-7 % 2` is `1`, always non-negative for a positive divisor. Each language's own `/` and `%` satisfy `(a / b) * b + a % b == a`; the two languages differ only when the signs differ and the division is not exact. This course uses floor division; chapter 1 explains why.

**Floats are IEEE 754.** An `f32` has a sign bit, 8 exponent bits and 23 fraction bits. A normal value is `(−1)^sign × 1.fraction × 2^(exponent − 127)` ([Goldberg 1991](#sources)). Consequences you will meet:

- **Rounding.** Every operation rounds its exact result to the nearest representable value. `0.1` has no exact binary form. Addition is not associative: `(a + b) + c` and `a + (b + c)` can differ, so a compiler may not reorder float sums without accepting a different result. Later weeks make that trade deliberately, for speed.
- **Integers run out.** With 24 bits of precision, `f32` represents every integer up to `2^24 = 16777216`, but not `16777217`: `16777216 + 1` rounds back to `16777216`.
- **Special values.** `inf` and `−inf` come from overflow or dividing a non-zero value by zero. `NaN` ("not a number") comes from `0/0` or `inf − inf`, and is not equal to anything, itself included. There are two zeros: `0.0 == −0.0`, yet `1 / −0.0` is `−inf`.
- **Precision of the host language.** Python floats are 64-bit. To mimic `f32`, round after every single operation, not once at the end.

The C program below checks each of these claims. Compile it with `gcc -std=c11 -fwrapv` on x86-64 or ARM64 (where `float` math is done in single precision) and run it; every `assert` should pass.

```c
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

int main(void) {
    int32_t big = INT32_MAX;
    assert(big + 1 == INT32_MIN);          // wraps only because we compile with -fwrapv
    assert(-7 / 2 == -3 && -7 % 2 == -1);  // C division truncates toward zero

    float f = 16777216.0f;                 // 2^24: above it, floats skip odd integers
    assert(f + 1.0f == f);

    uint32_t bits;
    memcpy(&bits, &f, sizeof bits);        // look at the encoding
    assert(bits == 0x4B800000);            // sign 0, exponent 127 + 24, fraction 0

    float zero = 0.0f, neg_zero = -0.0f;
    assert(zero == neg_zero && 1.0f / neg_zero == -INFINITY);
    float nan = NAN;
    assert(nan != nan);
    return 0;
}
```

In Python, which has only 64-bit floats, you get `f32` behavior by rounding after every operation:

```python
import struct

def f32(x: float) -> float:  # round a Python (64-bit) float to the nearest 32-bit float
    return struct.unpack("f", struct.pack("f", x))[0]

assert f32(f32(16777216.0 + 1.0) + 1.0) == 16777216.0  # round after every op
assert f32(16777216.0 + 1.0 + 1.0) == 16777218.0        # rounding once at the end differs
```

**Conversions.** Converting `f32` to `i32` in C truncates toward zero, and is undefined if the value does not fit, including NaN and infinities. Converting `i32` to `f32` rounds to a nearby float (the nearest, on every mainstream target): large integers lose their low bits. Converting to a boolean tests for non-zero.

**Functions are polynomials.** There is no `exp` or `sin` instruction a compiler can rely on everywhere; chapter 5 builds them from `+` and `×`. For example, `exp2(x)` splits `x` into an integer part, which goes straight into the float's exponent bits, and a small fractional part, where a short polynomial (a Taylor or minimax approximation) is accurate enough ([Muller 2016](#sources)).

If any of this is new, read CS:APP chapter 2 before chapter 1. Most chapter-1 bugs are here.

### Lesson 3: graphs, substitution and intervals

**Sharing matters.** Lesson 1's graph computes `a + b` once. In a chain of `n` such squarings the graph (a DAG: nodes with inputs, no cycles) has `n + 1` nodes, but the tree has `2^(n+1) − 1`. Any algorithm that walks a DAG as if it were a tree does exponential work. The fix is **memoization**: remember each node's result the first time and look it up afterwards; in Python, a dict keyed by node, or `functools.cache`. Giving each distinct expression exactly one node in the first place, with a table from (operation, inputs, constant) to node, is *interning*; chapter 1 calls it hash-consing.

**Order of evaluation.** A node can be computed once its inputs are. A **topological order** lists every node after all its inputs. A depth-first search that appends each node after visiting its inputs produces one ([Kahn 1962](#sources) gives the other classic algorithm, by counting inputs):

```python
def toposort(graph: dict[str, list[str]], root: str) -> list[str]:
    order, seen = [], set()

    def visit(node: str) -> None:
        if node not in seen:
            seen.add(node)
            for src in graph[node]:
                visit(src)
            order.append(node)  # after all its sources

    visit(root)
    return order

# d = (a + b) * (a + b) shares the node c = a + b
graph = {"a": [], "b": [], "c": ["a", "b"], "d": ["c", "c"]}
assert toposort(graph, "d") == ["a", "b", "c", "d"]
```

Recursion is the clearest way to write this, but each nested call uses stack space, and Python stops at about 1,000 levels. Deep graphs need an explicit stack. Know how to convert one to the other.

**Substitution.** Calling a function means replacing its parameters with the arguments: `f(x) = x * x + 1` applied to `3` is `3 * 3 + 1`. This is the lambda calculus's *beta reduction* ([Rojas 2015](#sources)). Inside `f`, `x` is a *bound* variable; a name used inside but defined outside is *free*. Substituting by name can go wrong when an argument's free variable has the same name as a variable bound inside the function (*capture*): in `g(y) = x + y`, substituting an outer `y` for `x` gives `g(y) = y + y`, and the outer `y` has been captured by `g`'s parameter. Naming parameters by position instead (parameter 0, parameter 1), with each function body using only its own parameters, avoids the problem; that is what chapter 1's `PARAM slot=0` with closed bodies does.

**Reasoning with intervals.** A compiler often needs facts about values it does not know, such as "this index is never negative". Track an interval `[lo, hi]` for each value: if `x` is in `[0, 3]` and `y` in `[0, 3]`, then `4x + y` is in `[0, 15]`. Addition adds the ends; multiplication takes the smallest and largest of the four products of ends, because signs can flip the order. The result is always true but may be loose: `x − x` gets `[−3, 3]`, not `0`. This is the simplest case of *abstract interpretation* ([Cousot & Cousot 1977](#sources)); chapter 1 calls the intervals `bounds`.

**Pattern matching.** Optimizations are written as rules: "if a node is `x + 0`, replace it with `x`". Practice writing small functions that match on a node's operation and inputs and return a new node or nothing, for example a `simplify(node)` that returns `x` for `x + 0` and `None` otherwise.

### Lesson 4: C, index arithmetic and loop nests

**C as a target.** Generated code is plain C, so you need to read and write it fluently:

- **Arrays are pointers plus offsets.** A 2-D matrix is one flat array; element `[i][j]` of an `n`-column matrix is at `i * n + j` (row-major order).
- **Functions take pointers to buffers** and write results through them.
- **Compilation and linking.** `gcc -c` turns a `.c` file into an object file; `gcc -shared -fPIC` produces a shared library that a running program can load with `dlopen` and call through a function pointer ([dlopen(3)](#sources); [CS:APP](#sources) ch. 7). This is one simple way to build chapter 2's runtime: generate C, compile it to a shared library, load it, and call it.

**Tensors are flat memory plus a shape.** A tensor of shape `(2, 3, 4)` is 24 numbers in one buffer. In row-major order the last axis is contiguous, and each earlier axis steps over a whole block of the later ones. The step per axis is its **stride**:

```python
def strides(shape: tuple[int, ...]) -> tuple[int, ...]:
    # row-major: the last axis is contiguous, each earlier axis skips a whole block
    out, step = [], 1
    for n in reversed(shape):
        out.append(step)
        step *= n
    return tuple(reversed(out))

assert strides((2, 3, 4)) == (12, 4, 1)   # element [i, j, k] lives at 12*i + 4*j + k
```

Going back from a flat offset to an index per axis takes `div` and `mod`, peeling off the last axis first:

```python
def unflatten(offset: int, shape: tuple[int, ...]) -> tuple[int, ...]:
    # the inverse of the stride formula: the last axis is the remainder, the rest the quotient
    idx = []
    for n in reversed(shape):
        idx.append(offset % n)
        offset //= n
    return tuple(reversed(idx))

assert unflatten(45, (4, 5, 6)) == (1, 2, 3)   # 30*1 + 6*2 + 3 = 45
```

**Movement is index arithmetic.** These two formulas are how a compiler moves data without moving it:

- **Reshape** keeps the flat order. Element `[i, j]` of a `(2, 3)` tensor reshaped to `(3, 2)` is flat offset `2i + j` of the original, which is the original's `[(2i + j) div 3, (2i + j) mod 3]`.
- **Transpose** permutes the index: element `[i, j]` of the transpose of a `(2, 3)` tensor is the original's `[j, i]`, at flat offset `3j + i`. Transposing swaps the strides.
- **Slice and pad** add an offset to the index, and check it against a range.

Chapters 3–5 build exactly these expressions, and chapter 1's symbolic rules simplify them back.

**Broadcasting.** Elementwise operations on tensors of different shapes align the shapes from the right; each pair of sizes must be equal, or one of them must be 1, which is stretched ([NumPy](#sources)). In this course broadcasting arrives in chapter 4, as an explicit `EXPAND` op.

```python
def broadcast(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, ...]:
    # align from the right; each pair of sizes must match, or one of them must be 1
    a, b = (1,) * (len(b) - len(a)) + a, (1,) * (len(a) - len(b)) + b
    assert all(x == y or 1 in (x, y) for x, y in zip(a, b)), "shapes do not broadcast"
    return tuple(y if x == 1 else x for x, y in zip(a, b))

assert broadcast((2, 2), (2,)) == (2, 2)
assert broadcast((3, 1), (1, 4)) == (3, 4)
```

**Three kinds of loop nest.** Almost every kernel is one of these, or a combination:

- **Elementwise:** one loop per output axis, each output element computed from inputs at the same index (`c[i] = a[i] + b[i]`).
- **Reduction:** an accumulator, set before an inner loop and updated in it (`s += x[i]`). (In floating point the result depends on the order of the additions; see Lesson 6.)
- **Contraction:** a reduction over a product of two inputs. A matrix multiply is a broadcasted multiply followed by a sum; that is exactly the syllabus's [gemm example](../uir.md#lines). A convolution is a sliding window of multiplies and sums, and can be rewritten as a matrix multiply ([Chellapilla et al. 2006](#sources)).

```c
#include <assert.h>

// C = A @ B for row-major n x n matrices stored as flat arrays
static void matmul(int n, const float *a, const float *b, float *c) {
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++) {
            float acc = 0.0f;
            for (int k = 0; k < n; k++)
                acc += a[i * n + k] * b[k * n + j];
            c[i * n + j] = acc;
        }
}

int main(void) {
    float a[4] = {1, 2, 3, 4}, b[4] = {5, 6, 7, 8}, c[4];
    matmul(2, a, b, c);
    assert(c[0] == 19 && c[1] == 22 && c[2] == 43 && c[3] == 50);
    return 0;
}
```

You should be able to write this loop nest without thinking, and say which array the inner loop reads at consecutive addresses and which it reads `n` elements apart.

### Lesson 5: what models compute

**A model is a function with weights.** A neural network maps an input tensor to an output tensor through layers. The workhorse is the *linear layer*, `y = x W + b`: a matrix multiply plus a broadcast add. Between linear layers sits a cheap elementwise *activation*, such as ReLU, `max(x, 0)`. An MNIST digit classifier ([LeCun et al. 1998](#sources)) can be just that: a `28 × 28` image flattened to 784 numbers, a linear layer, ReLU, and a linear layer to 10 scores, one per digit.

**Scores become probabilities with softmax**, `p_i = exp(x_i) / Σ_j exp(x_j)`, and the loss for a correct label `t` is the *cross-entropy* `−log p_t`. Computed directly, `exp` overflows for large scores; subtracting the largest score first changes nothing mathematically and keeps every `exp` at most 1 ([Goodfellow et al. 2016](#sources), ch. 4):

```python
import math

def softmax(xs: list[float]) -> list[float]:
    m = max(xs)                                  # subtract the max so exp cannot overflow
    es = [math.exp(x - m) for x in xs]
    total = sum(es)
    return [e / total for e in es]

def cross_entropy(logits: list[float], label: int) -> float:
    return -math.log(softmax(logits)[label])

assert softmax([1000.0, 1000.0]) == [0.5, 0.5]   # math.exp(1000.0) alone raises OverflowError

# the gradient of cross-entropy with respect to the scores is softmax - one_hot(label)
logits, label, eps = [2.0, 1.0, 0.1], 0, 1e-6
p = softmax(logits)
for i in range(3):
    bumped = [x + (eps if j == i else 0.0) for j, x in enumerate(logits)]
    numeric = (cross_entropy(bumped, label) - cross_entropy(logits, label)) / eps
    assert abs(numeric - (p[i] - (i == label))) < 1e-4
```

(Taking the log of a softmax can still underflow to `log 0`; production code computes log-softmax directly with the same max trick.)

**Training is gradient descent.** Training moves each weight a small step against the gradient of the loss with respect to that weight. The chain rule gives the gradient, and **reverse-mode automatic differentiation** applies it backwards through the computation graph ([Baydin et al. 2018](#sources)): each node knows the derivative of its output with respect to each input (its *local gradient*), and the gradient of the loss flows from the output back to every input, multiplied along each path and summed where paths meet. The whole idea fits in a few lines on scalars ([micrograd](#sources) is a complete version):

```python
class Value:
    def __init__(self, data: float, srcs: tuple = (), local_grads: tuple = ()):
        self.data, self.srcs, self.local_grads, self.grad = data, srcs, local_grads, 0.0

    def __add__(self, other: "Value") -> "Value":
        return Value(self.data + other.data, (self, other), (1.0, 1.0))

    def __mul__(self, other: "Value") -> "Value":
        return Value(self.data * other.data, (self, other), (other.data, self.data))

    def backward(self) -> None:
        order, seen = [], set()

        def visit(v: "Value") -> None:  # the toposort from Lesson 3
            if v not in seen:
                seen.add(v)
                for s in v.srcs:
                    visit(s)
                order.append(v)

        visit(self)
        self.grad = 1.0
        for v in reversed(order):  # outputs before inputs
            for s, g in zip(v.srcs, v.local_grads):
                s.grad += g * v.grad  # chain rule; += sums over paths

# loss = (w*x - y)^2 with w = 1, x = 3, y = 6: d loss / d w = 2 (w*x - y) x = 2 * (3 - 6) * 3
w = Value(1.0)
d = w * Value(3.0) + Value(-6.0)
loss = d * d
loss.backward()
assert w.grad == -18.0
```

A training loop repeats this: step `w` against `w.grad`, recompute the loss, and go again.

Chapter 6 builds the same thing as a rewrite on UOps: `GRADIENT` of a loss with respect to a buffer becomes a new graph.

**Attention.** The layer that makes a transformer is attention: `softmax(Q Kᵀ / √d) V`, where `Q`, `K` and `V` are linear layers of the input ([Vaswani et al. 2017](#sources)). It is two matrix multiplies with a softmax between, which is why chapters 8–10 care so much about fast matrix multiplies and about fusing the softmax into them.

### Lesson 6: hardware and performance

**Memory is slower than arithmetic.** A processor can do many arithmetic operations in the time one value arrives from main memory. Caches hide this when a program reuses data that is already close: registers, then L1, L2 and L3 caches, then DRAM, each larger and slower than the last ([Drepper 2007](#sources); [CS:APP](#sources) ch. 6). Memory moves in *cache lines*, typically 64 bytes, so reading consecutive addresses is far cheaper than jumping:

```c
#include <assert.h>

#define N 512
static float m[N][N];

int main(void) {
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            m[i][j] = (float)(i % 7 - j % 5);  // small integers: every partial sum below is exact
    float by_rows = 0.0f, by_cols = 0.0f;
    for (int i = 0; i < N; i++)                // consecutive addresses: one line serves 16 floats
        for (int j = 0; j < N; j++)
            by_rows += m[i][j];
    for (int j = 0; j < N; j++)                // N floats apart: a new cache line for every read
        for (int i = 0; i < N; i++)
            by_cols += m[i][j];
    assert(by_rows == by_cols);
    return 0;
}
```

Both loops compute the same sum; time them with a larger `N` and the column order is much slower. Your compiler generates loop nests from chapter 4 (rangeify), and chooses their order for speed from chapter 6 on.

**Arithmetic intensity** is operations per byte moved. The roofline model says a kernel's speed is capped by whichever is lower, the peak compute rate or memory bandwidth times intensity ([Williams et al. 2009](#sources)). An `f32` elementwise add does one operation per 12 bytes moved (two 4-byte reads and one write) and is bandwidth-bound. An `n × n` matrix multiply does `2n³` operations on `3n²` values, so with good reuse it can be compute-bound. **Fusion** raises intensity for free: `relu(x * w + b)` computed as three loops writes and re-reads two temporary arrays; as one loop, the temporaries stay in registers. Deciding what to fuse and what to keep in memory is chapter 4's job.

Much of the speed work in chapters 6–8 is about reuse: blocking loops so that a tile of data is used many times while it is in cache ([Goto & van de Geijn 2008](#sources)).

**Parallelism comes in three sizes.**

- **SIMD vectors:** one instruction operates on several values at once, for example 8 `f32`s in a 256-bit register. C compilers vectorize simple loops themselves; chapter 8's *upcasting* makes the vector width explicit ([CS:APP](#sources) ch. 5).
- **Threads:** several cores run parts of a loop at once. Each thread should write its own outputs. Two threads updating one location without coordination is a *data race*, and the result is undefined ([CS:APP](#sources) ch. 12).


- **GPUs:** thousands of threads run one function, the *kernel*. Threads are grouped into blocks (AMD: *workgroups*) that can share fast on-chip memory, and the hardware executes threads in fixed-size groups in lockstep. GPUs also have matrix units (AMD: *matrix cores*, used through WMMA and MFMA instructions) that multiply small tiles of matrices in one instruction ([AMD WMMA](#sources)); chapter 7 uses them. Before chapter 7, it helps to have written and launched one simple GPU kernel in any GPU language.

> **AMD.** AMD calls a hardware thread group a *wavefront*: 64 threads on CDNA (Instinct) GPUs; 32 by default on RDNA (Radeon) GPUs, which also support 64 ([AMD HIP programming model](#sources)). The syllabus says "CUDA/HIP"; this recreation targets AMD GPUs only, through HIP, AMD's C++ dialect for GPU kernels.

A sum split across threads is computed as partial sums combined at the end, which reorders the additions:

```python
# f32 is the helper from Lesson 2
def sum_f32(xs: list[float]) -> float:  # sequential, rounding after every add as f32 does
    total = 0.0
    for x in xs:
        total = f32(total + x)
    return total

xs = [1e8, 1.0, -1e8, 1.0]
assert sum_f32(xs) == 1.0                                  # one thread, left to right
assert f32(sum_f32(xs[:2]) + sum_f32(xs[2:])) == 0.0       # two threads, then combine
# the exact sum is 2: neither order is right, they are just different
```

**Measuring.** Performance claims need numbers: time a kernel over several runs after a warm-up run, then report achieved operations per second and bytes per second, and compare them with the machine's peaks. The roofline tells you which of the two you should be close to.

## Self-check

Questions 1–8 are what chapters 1–3 need: answer them without looking anything up before you start. Questions 9 and 10 can wait until chapters 5–6.

1. What is `INT32_MAX + 1` in C without `-fwrapv`, and with it?
   <details><summary>Answer</summary>Without it, undefined behavior: the compiler may assume it does not happen. With it, <code>INT32_MIN</code> (−2147483648).</details>
2. What are `-7 / 2` and `-7 % 2` in C, and `-7 // 2` and `-7 % 2` in Python?
   <details><summary>Answer</summary>C: <code>-3</code> and <code>-1</code> (truncation). Python: <code>-4</code> and <code>1</code> (floor).</details>
3. Why can't a compiler turn `(a + b) + c` into `a + (b + c)` for floats?
   <details><summary>Answer</summary>Each addition rounds, so the two orders can round differently and give different results. For example, with <code>a = 16777216</code>, <code>b = c = 1</code> in <code>f32</code>, the first gives <code>16777216</code> and the second <code>16777218</code>.</details>
4. A row-major tensor has shape `(4, 5, 6)`. At what offset is element `[1, 2, 3]`?
   <details><summary>Answer</summary>The strides are <code>(30, 6, 1)</code>, so <code>30 + 12 + 3 = 45</code>.</details>
5. What shape does broadcasting give for `(5, 1, 3)` and `(4, 1)`?
   <details><summary>Answer</summary><code>(5, 4, 3)</code>: align from the right as <code>(5, 1, 3)</code> and <code>(1, 4, 1)</code>, then take the size that is not 1 in each position.</details>
6. Walking a DAG of `n` shared squarings as a tree visits how many nodes? How do you avoid that?
   <details><summary>Answer</summary><code>2^(n+1) − 1</code>, about twice the <code>2^n</code> leaves. Memoize: compute each node once and look it up afterwards.</details>
7. If `x` is in `[−2, 3]`, what interval does interval arithmetic give for `x * x`? What is the true range?
   <details><summary>Answer</summary>The four products of ends are 4, −6, −6 and 9, so <code>[−6, 9]</code>. The true range is <code>[0, 9]</code>: the interval is safe but loose, because it treats the two <code>x</code>s as independent.</details>
8. A `(2, 3)` tensor is reshaped to `(3, 2)`. Which element of the original is element `[0, 1]` of the result? Which is element `[0, 1]` of the original's transpose?
   <details><summary>Answer</summary>Reshape keeps the flat order: offset <code>0*2 + 1 = 1</code> is the original's <code>[0, 1]</code>. The transpose swaps the index: its <code>[0, 1]</code> is the original's <code>[1, 0]</code>.</details>
9. Why does softmax subtract the largest score before calling `exp`?
   <details><summary>Answer</summary><code>exp</code> of a large score overflows to infinity. Subtracting the same number from every score does not change the result, and after subtracting the maximum every <code>exp</code> is at most 1.</details>
10. In reverse-mode differentiation, why are gradients added (`+=`) rather than assigned?
    <details><summary>Answer</summary>A value used in several places affects the loss along several paths; by the chain rule its gradient is the sum over those paths.</details>

## Glossary

Terms the course uses, defined in this chapter or the chapter shown.

| Term | Meaning |
|------|---------|
| IR | The compiler's data structure for a program |
| Pass | One analysis or transformation over the IR |
| Normal form | The form a set of rewrite rules leaves a program in, when no rule applies |
| Lowering | Rewriting into a more detailed, lower-level form |
| SSA | Linear IR where every name is assigned exactly once |
| DAG | Directed acyclic graph: nodes with inputs, no cycles |
| Effect | An operation that changes the world (a store), not just a value |
| Kernel | One compiled function, usually a loop nest, launched as a unit |
| Fusion | Putting several operations in one kernel |
| Schedule | The choices of loop order, tiling and parallel mapping for a kernel |
| Code generation | Printing the IR as target code |
| Runtime | The code that loads compiled kernels, owns buffers and calls kernels |
| Hash-consing | Building each distinct node once, so equal nodes are the same object (chapter 1) |
| Memoization | Remembering a function's result for each input, so it is computed once |
| Bounds | The interval of values a node can take (chapter 1) |
| Hoisting | Computing something once before a loop instead of in every iteration (chapter 3) |
| Accumulator | Memory a loop reads and updates on every iteration, as in a sum (chapter 3) |
| Materialize | Write an intermediate result to memory instead of recomputing or fusing it (chapter 4) |

## Where to learn more

| If this is shaky | Read |
|------------------|------|
| Two's complement, overflow, shifts, floating point | [CS:APP](#sources) ch. 2; [Goldberg 1991](#sources) |
| Pointers, arrays, how C maps to machine code | [CS:APP](#sources) ch. 3 |
| Caches, locality, why loop order matters | [CS:APP](#sources) ch. 6; [Drepper 2007](#sources) |
| Object files, shared libraries, `dlopen` | [CS:APP](#sources) ch. 7; [dlopen(3)](#sources) |
| What a compiler and an IR are; SSA | [Aho et al. 2006](#sources) ch. 1, 6; [Cytron et al. 1991](#sources); [Lattner & Adve 2004](#sources) |
| ML compilers: kernels, fusion, schedules | [Ragan-Kelley et al. 2013](#sources); [Chen et al. 2018](#sources) |
| Parsing, DAGs, topological sort, value numbering | [Aho et al. 2006](#sources): ch. 2 (a small parser), ch. 6 and §8.5 (DAGs, value numbering) |
| Broadcasting and tensor shapes | [NumPy broadcasting](#sources) |
| Interval reasoning | Chapter 1's bounds section; for the theory, [Cousot & Cousot 1977](#sources) |
| Substitution and the lambda calculus | [Rojas 2015](#sources) |
| Neural network basics, softmax, numerical stability | [Goodfellow et al. 2016](#sources), ch. 4 and 6; [LeCun et al. 1998](#sources) |
| Gradients and automatic differentiation | [Baydin et al. 2018](#sources); [micrograd](#sources) |
| Attention and transformers | [Vaswani et al. 2017](#sources) |
| Loop optimizations, vectors, threads | [CS:APP](#sources) ch. 5 and 12; [Goto & van de Geijn 2008](#sources) |
| GPU threads, blocks and wavefronts on AMD | [AMD HIP programming model](#sources) |

The CS:APP lab handouts are available to self-study students on the book's site: the data lab covers Lesson 2, and the cache lab covers the memory part of Lesson 6.

## Sources

1. Bryant & O'Hallaron, *Computer Systems: A Programmer's Perspective*, 3rd ed., Pearson 2016. https://csapp.cs.cmu.edu/ — the 15-213 textbook the syllabus assumes; labs at https://csapp.cs.cmu.edu/3e/labs.html.
2. ISO C11 committee draft N1570. https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf — §6.5.5 for division, §6.5p5 for signed overflow.
3. Goldberg, "What Every Computer Scientist Should Know About Floating-Point Arithmetic", ACM Computing Surveys 23(1), 1991. https://doi.org/10.1145/103162.103163 — free reprint at https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html.
4. Kahn, "Topological Sorting of Large Networks", CACM 5(11), 1962. https://doi.org/10.1145/368996.369025 — the in-degree algorithm for topological order.
5. Aho, Lam, Sethi, Ullman, *Compilers: Principles, Techniques, and Tools*, 2nd ed., Addison-Wesley 2006 (print). https://www.pearson.com/en-us/subject-catalog/p/compilers-principles-techniques-and-tools/P200000003472/9780133002140 — parsing, DAGs for expressions, value numbering.
6. Linux man-pages, dlopen(3). https://man7.org/linux/man-pages/man3/dlopen.3.html — loading a shared library at run time.
7. NumPy Manual, "Broadcasting". https://numpy.org/doc/stable/user/basics.broadcasting.html — the broadcasting rules.
8. Chellapilla, Puri, Simard, "High Performance Convolutional Neural Networks for Document Processing", IWFHR 2006. https://inria.hal.science/inria-00112631 — convolution as matrix multiply.
9. Baydin, Pearlmutter, Radul, Siskind, "Automatic Differentiation in Machine Learning: a Survey", JMLR 2018. https://arxiv.org/abs/1502.05767 — forward and reverse mode.
10. Drepper, "What Every Programmer Should Know About Memory", 2007. https://www.akkadia.org/drepper/cpumemory.pdf — caches and memory performance.
11. Williams, Waterman, Patterson, "Roofline: An Insightful Visual Performance Model for Multicore Architectures", CACM 2009. https://doi.org/10.1145/1498765.1498785 — arithmetic intensity.
12. AMD, "Introduction to the HIP programming model". https://rocm.docs.amd.com/projects/HIP/en/latest/understand/programming_model.html — threads, blocks, grids and wavefronts on AMD GPUs.
13. Click & Paleczny, "A Simple Graph-Based Intermediate Representation", IR '95. https://doi.org/10.1145/202529.202534 — a statement-free graph IR ("sea of nodes").
14. Rojas, "A Tutorial Introduction to the Lambda Calculus", 2015. https://arxiv.org/abs/1503.09060 — substitution, free and bound variables.
15. Cousot & Cousot, "Abstract Interpretation", POPL 1977. https://doi.org/10.1145/512950.512973 — the theory behind interval reasoning.
16. LeCun, Bottou, Bengio, Haffner, "Gradient-Based Learning Applied to Document Recognition", Proc. IEEE 1998. https://doi.org/10.1109/5.726791 — MNIST and convolutional networks; dataset at https://yann.lecun.org/exdb/mnist/index.html.
17. Goodfellow, Bengio, Courville, *Deep Learning*, MIT Press 2016. https://www.deeplearningbook.org/contents/numerical.html — ch. 4, overflow and the stable softmax.
18. Karpathy, micrograd. https://github.com/karpathy/micrograd — a complete scalar reverse-mode autograd engine in about 100 lines.
19. Vaswani et al., "Attention Is All You Need", NeurIPS 2017. https://arxiv.org/abs/1706.03762 — the transformer and attention.
20. Goto & van de Geijn, "Anatomy of High-Performance Matrix Multiplication", ACM TOMS 2008. https://doi.org/10.1145/1356052.1356053 — blocking for caches.
21. Muller, *Elementary Functions: Algorithms and Implementation*, 3rd ed., Birkhäuser 2016. https://doi.org/10.1007/978-1-4899-7983-4 — range reduction and polynomial approximation of `exp`, `log`, `sin`.
22. AMD GPUOpen, "How to accelerate AI applications on RDNA 3 using WMMA". https://gpuopen.com/learn/wmma_on_rdna3/ — matrix instructions on Radeon GPUs.
23. Cytron, Ferrante, Rosen, Wegman, Zadeck, "Efficiently Computing Static Single Assignment Form and the Control Dependence Graph", ACM TOPLAS 1991. https://doi.org/10.1145/115372.115320 — SSA.
24. Lattner & Adve, "LLVM: A Compilation Framework for Lifelong Program Analysis & Transformation", CGO 2004. https://llvm.org/pubs/2004-01-30-CGO-LLVM.pdf — a typed SSA IR with a pass pipeline.
25. Ragan-Kelley et al., "Halide: A Language and Compiler for Optimizing Parallelism, Locality, and Recomputation in Image Processing Pipelines", PLDI 2013. https://doi.org/10.1145/2491956.2462176 — separating the algorithm from the schedule.
26. Chen et al., "TVM: An Automated End-to-End Optimizing Compiler for Deep Learning", OSDI 2018. https://arxiv.org/abs/1802.04799 — fusion and schedules for deep learning.
