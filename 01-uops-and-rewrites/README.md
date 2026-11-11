# Week 1: UOps & Rewrites & Renderer?

> **`uops` · `elementwise ops` · `symbolic` · `rewrites` · `renderer`**
>
> Students become familiar with the `UOp` and write a compiler capable of compiling and simplifying elementwise programs. We introduce the graph structure and rewriting. The UOp is hash consed. All shapes are rank 0. We allow rank 1 shapes here, but ALU ops must be rank 0.
>
> ```
> UOp(op, src:tuple[UOp, ...], arg)
> ```
>
> Recursive properties introduced:
> ```
> dtype(void,bool,i32,f32)
> shape:tuple[int, ...]
> cost:int
> bounds:tuple[int, int]
> ```
>
> Ops introduced:
> ```
> CONST -- type determined by the arg
>
> lambda calculus:
> PARAM(ParamArg) -- arg input to the call
> CALL(CallArg) -- src[0] is the function body, src[1:] are the params...
>
> lil movement:
> STACK(src, ...) -- new leading axis, all src has same shape. until week 4, inputs can only be STACK/CONST.
> INDEX -- shape from (n,) -> (), pop axes off the left with srcs
>
> ALU:
> CAST/RECIP
> ADD/MUL/MAX/XOR
> CMPLT -- returns bool
> SHL/DIV/MOD -- i32 only
> WHERE
>
> ASSERT -- for tests only
> ```
>
> The graph rewrite engine should be capable of "running" these programs via an interpreter.
>
> Lectures:
> * wed - Course intro, turing completeness, the UOp, the format, the first assignment
> * fri - ALU stuff, bottom up greedy rewrite engines, const folding
> * mon - call/param stuff, symbolic simplification, computer algebra systems
>
> Compilers must be handed in by Wednesday every week before 10 AM class.
>
> — the syllabus, week 1

**Builds on:** nothing in the syllabus; [Chapter 0](../00-prerequisites/README.md) lists what it assumes you know. **By the end you can:** read a UIR program into a hash-consed graph, compute its properties, and run it by rewriting it to constants.

## Contents

- [Lectures](#lectures)
  - [Lesson 1: course intro, Turing completeness, the UOp, the format, the first assignment](#lesson-1-course-intro-turing-completeness-the-uop-the-format-the-first-assignment)
  - [Lesson 2: ALU ops, bottom-up greedy rewrite engines, constant folding](#lesson-2-alu-ops-bottom-up-greedy-rewrite-engines-constant-folding)
  - [Lesson 3: call/param, symbolic simplification, computer algebra systems](#lesson-3-callparam-symbolic-simplification-computer-algebra-systems)
- [Ops introduced](#ops-introduced)
- [Properties introduced](#properties-introduced)
- [Assignment](#assignment)
- [Example programs](#example-programs)
- [Spec notes](#spec-notes)
- [Quiz](#quiz)
- [Sources](#sources)

## Lectures

Intervals are written `[lo, hi]` throughout, both ends included.

### Lesson 1: course intro, Turing completeness, the UOp, the format, the first assignment

**What the course builds.** A compiler takes a program and produces a faster equivalent one. Ours takes small tensor programs and, by week 9, trains a language model on a GPU. Every week adds a few ops and one new idea, and the syllabus grades each week's compiler against all student and teacher tests. It calls the course "an exercise in slop management": shortcuts taken now get harder to undo each week.

**The UOp.** Everything in the compiler is one data structure, `UOp(op, src, arg)`:

- `op` says what the node does: `ADD`, `CONST`, `INDEX`.
- `src` holds its inputs, which are other UOps.
- `arg` holds anything that is not a UOp: a constant's value, a dtype for `CAST`, a slot and dtype for `PARAM`.

There are no statements, variables or instructions, only a graph of values. Since `src` points at nodes that already exist, the graph is a **DAG** (directed acyclic graph): a node can be used many times, but nothing can depend on itself.

**Hash-consing.** The syllabus says "the UOp is hash consed": constructing a UOp that already exists returns the existing object. Two UOps are equal exactly when they are the same object, so equality is a pointer comparison, and identical subexpressions are stored once ([Filliâtre & Conchon 2006](#sources)). Applied to a whole program, the same idea is called *value numbering* ([Alpern et al. 1988](#sources)).

```python
class UOp:
    cache: dict[tuple, "UOp"] = {}

    def __new__(cls, op: str, src: tuple["UOp", ...] = (), arg=None):
        # floats are keyed by repr: 0.0 == -0.0 and nan != nan, but each must be its own UOp
        key = (op, src, type(arg), repr(arg) if isinstance(arg, float) else arg)
        if key not in cls.cache:
            u = super().__new__(cls)
            u.op, u.src, u.arg = op, src, arg
            cls.cache[key] = u
        return cls.cache[key]

two, three = UOp("CONST", arg=2), UOp("CONST", arg=3)
assert UOp("ADD", (two, three)) is UOp("ADD", (two, three))
```

The key can use `src` directly because its elements are already unique objects, so comparing them is cheap. The rest of the key must tell apart values your language considers equal. In Python, `True == 1 == 1.0`, so the key includes `type(arg)`; floats have two more traps, which the `repr` handles.

**Recursive properties.** UOps never change, so anything computed from a node and its sources is fixed forever. The syllabus calls these *recursive properties*: `dtype`, `shape`, `cost` and `bounds` this week (rules in [Properties introduced](#properties-introduced)). Compute each once and cache it on the node. For `%x = add (index [10 20 30] 2) 1`:

| Node | dtype | shape | cost | bounds |
|------|-------|-------|------|--------|
| `[10 20 30]` | `i32` | `(3,)` | 0 | `[10, 30]` |
| `index … 2` | `i32` | `()` | 0 | `[10, 30]` |
| `add … 1` | `i32` | `()` | 1 | `[11, 31]` |

Each row uses only the rows above it.

**Turing completeness.** A language is Turing complete if it can express any computation, including ones that never finish. The lambda calculus is, because a function can be applied to itself ([Rojas 2015](#sources)). Our IR is not:

> **Interpretation.** The syllabus lists the topic without a conclusion. A UOp graph is acyclic, so a function body cannot contain the call to itself. Parameters hold only `i32`, `f32` and `bool` values, never functions, so a body cannot receive itself as an argument either. With no recursion, and with week 3's loops having bounds fixed before they start, every program terminates. tinygrad reaches Turing completeness only through `BACKEDGE`, a while loop the course does not include.

This is a feature. A compiler that can see a whole program, with all its loop bounds, can decide how to split, fuse and schedule it.

**The format.** Tests are written in UIR, a text form of the graph. Read [uir.md](../uir.md) now. In short:

```text
# [10 20 30][2] + 1 should be 31
%v    = [10 20 30]
%x    = add (index %v 2) 1
%test = assert %x 31
```

Each line binds a name; sources come first, then `key=value` args; `(op ...)` nests; the last line is the root.

Parsing is direct: each line, and each nested `(op ...)`, is one UOp constructor call, and hash-consing makes a nested op and a named line build the same node. Literals take their dtype from what they meet: `add %x 1` is `f32` if `%x` is ([rules](../uir.md#literals)).

**The first assignment** (details [below](#assignment)): parse UIR, build hash-consed UOps, compute the four properties, reject invalid programs, and run valid ones by rewriting them until the `assert` has constant inputs.

### Lesson 2: ALU ops, bottom-up greedy rewrite engines, constant folding

**The ALU ops.** The ALU ops and their dtypes are in [Ops introduced](#ops-introduced). This week they take rank-0 sources only. The set is small on purpose; other operations are combinations:

| You want | Write |
|----------|-------|
| −a | `mul a -1` |
| a − b | `add a (mul b -1)` |
| a > b | `cmplt b a` |
| not c (`bool`) | `xor c true` |
| a ≠ b (`bool`) | `xor a b` |
| min(a, b) | `where (cmplt a b) a b` |
| a / b (`f32`) | `mul a (recip b)` |

`mul a (recip b)` rounds twice, so it can differ from a true `a / b` in the last bit. Fewer ops means fewer rewrite rules, a smaller renderer next week, and fewer derivative rules in week 6.

**Exact semantics.** An interpreter and the C code you generate next week must agree bit for bit, so the edge cases are fixed in [uir.md](../uir.md#arithmetic). The ones that catch everyone:

- **`i32` wraps.** `add 2147483647 1` is `-2147483648`. Python integers do not wrap, so wrap explicitly after every `i32` op. In C, signed overflow is undefined behavior ([N1570 §6.5p5](#sources)); GCC and Clang make it wrap with `-fwrapv`.
- **`DIV` and `MOD` floor.** `div -7 2` is `-4` and `mod -7 2` is `1`, matching Python's `//` and `%`. C's `/` truncates toward zero and gives `-3` ([N1570 §6.5.5](#sources)). Floor division keeps index arithmetic regular: `mod x 4` is always in `[0, 3]`, even for negative `x`. Lesson 3 shows why that matters.
- **`f32` rounds after every op.** Python floats are 64-bit. `add (add 16777216.0 1.0) 1.0` is `16777216.0` in `f32`, because each `+ 1` rounds away, but adding in 64-bit and rounding once at the end gives `16777218.0`.
- **Division by zero.** Python raises an exception for `1 / 0.0`; `recip 0.0` must give `inf`.

**Rewriting.** A rewrite rule is a function from a UOp to a replacement UOp, or `None` if it does not apply. A rewrite engine applies rules until none apply, at which point the graph is in *normal form*.

The engine below is **bottom-up**: it rewrites a node's sources before the node itself, so when a rule sees a node, its sources are already in normal form. It is **greedy**: at each node, the first rule that fires wins, and its result is rewritten again. The `memo` dict means each distinct node is rewritten once, which matters in a DAG where nodes are shared.

```python
def rewrite(u: UOp, rules: list, memo: dict) -> UOp:
    # shortcut: recursion is limited to ~1000 levels; deep graphs need an explicit stack
    if u not in memo:
        new = UOp(u.op, tuple(rewrite(s, rules, memo) for s in u.src), u.arg)
        for rule in rules:  # greedy: the first rule that fires wins
            if (out := rule(new)) is not None:
                new = rewrite(out, rules, memo)  # the result may simplify further
                break
        memo[u] = new
    return memo[u]
```

Greedy rewriting has two hazards. When two rules match the same node, list order decides which fires, so order your list on purpose. And two rules that undo each other (x + 3 → 3 + x and back) loop forever. Every rule should make the graph smaller, or move it toward one fixed ordering (Lesson 3). [Baader & Nipkow 1998](#sources) is the theory of when rewriting terminates and gives a unique answer.

**Constant folding.** The most important rule: an ALU op whose sources are all constants becomes a constant.

```python
def wrap32(x: int) -> int:
    return (x + 2**31) % 2**32 - 2**31

def fold_add(u: UOp):  # i32 only: an f32 add must round its result to f32 instead
    if u.op == "ADD" and all(s.op == "CONST" and type(s.arg) is int for s in u.src):
        return UOp("CONST", arg=wrap32(u.src[0].arg + u.src[1].arg))

def add_zero(u: UOp):
    if u.op == "ADD" and u.src[1] is UOp("CONST", arg=0):
        return u.src[0]
```

`add_zero` shows why hash-consing helps rewriting: "is this the constant 0?" is an `is` check.

**The interpreter is the rewrite engine.** The syllabus asks that the engine can "run" programs. A program with no unknown inputs rewrites all the way down to constants if you have three kinds of rule: constant folding for every ALU op (with the exact semantics above), `INDEX` of a constant stack by a constant picks the element, and `CALL` inlines (Lesson 3). Then the `ASSERT` compares two constants, and running the program is checking them.

### Lesson 3: call/param, symbolic simplification, computer algebra systems

**Functions as graphs.** `PARAM` is a placeholder for an argument; its `slot` says which one. `CALL` applies a body to arguments: `src[0]` is the body, and `src[1 + i]` fills `PARAM slot=i`. This is the lambda calculus's application, and running a call is its *beta reduction*: substitute the arguments for the parameters.

```python
import functools

def inline(call: UOp) -> UOp:
    body, args = call.src[0], call.src[1:]

    @functools.cache
    def sub(u: UOp) -> UOp:
        if u.op == "PARAM":
            return args[u.arg]  # here a PARAM's arg is just its slot
        if u.op == "CALL":  # an inner body is closed: only its arguments change
            return UOp("CALL", (u.src[0], *map(sub, u.src[1:])), u.arg)
        return UOp(u.op, tuple(map(sub, u.src)), u.arg)

    return sub(body)
```

Two rules keep this correct:

- **Bodies are closed.** A body may use only its own PARAMs. So substitution stops at an inner CALL's body: those PARAMs belong to the inner function.
- **Arguments match.** A call passes exactly one argument per slot, each with the PARAM's dtype and shape. Check this when building the CALL, not when inlining.

UIR names like `%x` are not part of a UOp; a PARAM is just its slot and dtype. So f(x) = x + 1 and g(y) = y + 1 are the same UOp: hash-consing gives you what the lambda calculus calls *alpha-equivalence* for free.

Inlining is a rewrite rule like any other: `CALL` becomes `inline(call)`. Add it to your rule list and calls disappear before folding.

**Symbolic simplification.** A body with PARAMs cannot fold to a constant, but it can still simplify, using rules that hold for *every* value of the unknowns:

| Family | Example |
|--------|---------|
| Identities | x + 0 → x, x × 1 → x, x × 0 → 0 |
| Reassociation | (x + 3) + 5 → x + 8 |
| Combining terms | x + x → x × 2, x × 2 + x × 3 → x × 5 |
| Canonical order | 3 + x → x + 3, so equal sums hash-cons to one UOp |
| Bounds | `cmplt %x 10` → `true` when `%x`'s bounds say it is at most 9 |

All of these are exact for `i32`, because wrapping arithmetic still obeys the usual algebra. For `f32`, only `x × 1 → x` and canonical order are safe: reassociating or combining terms changes rounding, `x + 0 → x` is wrong for `x = -0.0`, and `x × 0` is NaN when `x` is NaN or infinite.

The last family needs **bounds**, the interval `[vmin, vmax]` a value can take. Constants have exact bounds, ALU ops combine their sources' bounds, and anything unknown gets the full range of its dtype ([Cousot & Cousot 1977](#sources) is the general theory, *abstract interpretation*):

```python
import functools

I32 = (-2**31, 2**31 - 1)

@functools.cache
def bounds(u: UOp) -> tuple[int, int]:  # i32 values; covers only CONST, MOD, ADD and MUL
    if u.op == "CONST":
        return (u.arg, u.arg)
    if u.op == "MOD" and u.src[1].op == "CONST" and u.src[1].arg > 0:
        return (0, u.src[1].arg - 1)  # floor mod by c > 0 is always in [0, c-1]
    if u.op in ("ADD", "MUL"):
        (a0, a1), (b0, b1) = bounds(u.src[0]), bounds(u.src[1])
        ends = [a0 + b0, a1 + b1] if u.op == "ADD" else [a0 * b0, a0 * b1, a1 * b0, a1 * b1]
        if I32[0] <= min(ends) and max(ends) <= I32[1]:
            return (min(ends), max(ends))
    return I32  # unknown, or the result might wrap
```

Bounds pay off with `DIV` and `MOD`. In

```text
%x = mod %a 100                          # bounds [0, 99]
%g = div (add (mul %x 4) (mod %y 4)) 4
```

`mul %x 4` is in `[0, 396]`, so it cannot wrap, and `mod %y 4` is in `[0, 3]`, so it never carries into the quotient: `%g` is just `%x`. A rule for this must check both facts from bounds; if `%x` were an unbounded PARAM, `mul %x 4` could wrap (at `x = 2^29`) and the rule must not fire.

The rule also needs floor semantics: with C's `%`, `y = -1` gives a remainder of `-1`, and for `x = 1` C's quotient is `0`, not `1`. Index arithmetic in weeks 3–5 is full of `div` and `mod` by shape sizes, with loop indices whose bounds are known; rules like this turn it back into simple loops.

**Computer algebra systems.** A symbolic simplifier is a small computer algebra system (CAS): it rewrites expressions toward a canonical form, so that equal expressions become identical UOps. A full CAS cannot always decide whether two expressions are equal, and neither can yours. That is fine: a missed simplification makes code slower, never wrong. What is never fine is the opposite mistake: **a rewrite must never change a program's meaning**, including at the edges (wrapping, NaN, `-0.0`, negative numbers).

Greedy rules commit to one rewrite at a time. *Equality saturation* instead keeps every equivalent form in an *e-graph* (a graph whose nodes are sets of equal expressions) and picks the cheapest at the end ([Tate et al. 2009](#sources); [Willsey et al. 2021](#sources)). It avoids rule-order problems at a cost in memory. The `cost` property is the kind of measure such a choice needs; this week you only compute it.

## Ops introduced

| Op | Srcs | Arg | Shape | Dtype | Meaning |
|----|------|-----|-------|-------|---------|
| `CONST` | none | value | `()` | from the arg ([literals](../uir.md#literals)) | A constant |
| `PARAM` | shape: `[]` for `()`, or `n` for `(n,)` | `slot`, `dtype` | the shape | `dtype` | Argument `slot` of the enclosing call: `param [] slot=0 dtype=i32` |
| `CALL` | body, args… | none | body's | body's | The body with `PARAM slot=i` bound to `src[1+i]` |
| `STACK` | constants | none | `(n,)` | the elements' | New leading axis |
| `INDEX` | value, indices… | none | value's, minus one leading axis per index | value's | Picks elements; indices are `i32` |
| `CAST` | rank-0 value, not `void` | `dtype`, not `void` | `()` | `dtype` | Dtype conversion |
| `RECIP` | `f32` | none | `()` | `f32` | 1 / a ([edge cases](../uir.md#arithmetic)) |
| `ADD` `MUL` `MAX` | a, b | none | `()` | the operands' (`i32` or `f32`) | a + b, a × b, the larger |
| `XOR` | a, b | none | `()` | the operands' (`i32` or `bool`) | Bitwise exclusive or |
| `CMPLT` | a, b (`i32` or `f32`) | none | `()` | `bool` | a < b |
| `SHL` `DIV` `MOD` | a, b (`i32`) | none | `()` | `i32` | a × 2^b, floor division, floor modulo |
| `WHERE` | cond (`bool`), a, b | none | `()` | the branches' | cond ? a : b |
| `ASSERT` | actual, expected | none | `()` | `void` | Test check, the program's root ([conventions](../uir.md#programs-and-assert)) |

Your compiler rejects programs that break these rules, checked on the program as written ([why](../uir.md#validation)):

- **ALU ops are rank 0.** Every source of `CAST`, `RECIP`, `ADD`, `MUL`, `MAX`, `XOR`, `CMPLT`, `SHL`, `DIV`, `MOD` and `WHERE` has shape `()`.
- **STACK sources are constants**, and values are at most rank 1 (rank 2 arrives in week 5). `[1 2 3]` is allowed; `[[1 2] [3 4]]` (rank 2) and `[%x 2]` (not a constant) are not.
- **INDEX stays in bounds.** Each index's bounds must lie inside `[0, n − 1]`. A PARAM's bounds are its dtype's full range, so a body that indexes by a parameter writes `index [1 2 3] (mod %p 3)`.
- **Dtypes match.** Typed operands of an ALU op have the same dtype ([conventions](../uir.md#mixing-dtypes)).
- **PARAMs live in bodies.** A PARAM the root reaches outside any CALL body is an error: nothing binds it.
- **Every line counts.** A line the root never reaches is still checked, and an invalid one is still an error.

> **Interpretation.** The syllabus gives no dtypes per op. `XOR` excludes `f32` and `RECIP` requires it because tinygrad's op spec does (`tinygrad/uop/spec.py`). tinygrad also accepts `bool` for `ADD`, `MUL`, `MAX` and `CMPLT` (as OR, AND, OR, and false < true); this course leaves those out to keep the rules small, since `WHERE` and `XOR` cover `bool` logic.

> **Interpretation.** Week 1 of the syllabus does not mention bounds checks; the draft course page lists "bounds checking" for week 1. tinygrad uses the same `vmin`/`vmax` test for load and store indices (`validate_index`, `tinygrad/uop/spec.py`), but only when `CHECK_OOB=1`, falls back to a solver, and does not check INDEX into a STACK. This course always checks, and rejects anything bounds cannot prove.

## Properties introduced

| Property | Type | Rule |
|----------|------|------|
| `dtype` | `void`, `bool`, `i32`, `f32` | From the arg for `CONST`, `CAST` and `PARAM`; `bool` for `CMPLT`; `f32` for `RECIP`; `void` for `ASSERT`; the body's for `CALL`; the value's for `INDEX`; the elements' for `STACK`; otherwise the operands' |
| `shape` | `tuple[int, ...]` | `()` for `CONST`, ALU ops and `ASSERT`; from its source for `PARAM`; `(n,)` for `STACK`; `INDEX` drops one leading axis per index; the body's for `CALL` |
| `cost` | `int` | 1 for an ALU op, 0 otherwise, plus the costs of all sources |
| `bounds` | `tuple[int, int]` | For `i32` and `bool` values: the exact per-op rules in [uir.md](../uir.md#bounds) |

> **Interpretation.** tinygrad has no `cost` property. The rule above is the simplest one that fits "recursive property". It counts work as if the graph were a tree, so shared nodes count once per use: for `%a = add %x 1` and `%b = mul %a %a`, `cost(%b)` is 3, though only two ops run. Treat it as an upper bound on work.

## Assignment

Due Wednesday of week 2, before the 10 AM class. Your ten tests, in UIR, are due the Monday before.

Write a program that takes a `.uir` file and:

1. **Parses** it into hash-consed UOps ([uir.md](../uir.md)), typing each literal ([rules](../uir.md#literals)).
2. **Checks** it: known ops, valid args, and every rule in [Ops introduced](#ops-introduced). Report the line of the first problem.
3. **Computes** `dtype`, `shape`, `cost` and `bounds` for every node.
4. **Runs** it by rewriting to normal form with call inlining, constant folding and constant indexing, then checks the root `ASSERT`.
5. **Reports** pass, or the actual and expected values.

Also implement the identity, reassociation and canonical-order rules, and the two bounds rules from Lesson 3 (`cmplt` against a bound, and the `div`/`mod` rule). No assert can tell whether a correct rule fired, since every program folds to constants. Check them by printing the rewritten body of [examples/symbolic.uir](examples/symbolic.uir) before inlining, in UIR or any readable form: it should be `mod %a 100`. An assert can catch a wrong rule, though: a test whose body is `div (add (mul %a 4) (mod %y 4)) 4` with an unbounded `%a`, called with `a = 536870912` and `y = 0`, must give `-536870912` (`mul` wraps to −2^31), not `a`.

Restrictions this week: ALU ops take rank-0 sources; values are at most rank 1; stack sources are constants. Keep the rewrite rules in a list you can extend: weeks 2–6 add to it. The renderer comes next week; this week, rewriting is the whole compiler.

## Example programs

All in [examples/](examples/). Each file's comments show the hand calculation.

| File | Exercises |
|------|-----------|
| [add.uir](examples/add.uir) | The smallest program: `ADD`, `ASSERT` |
| [floor_div.uir](examples/floor_div.uir) | `DIV` floors: `div -7 2` is `-4` |
| [wrap.uir](examples/wrap.uir) | `i32` overflow wraps |
| [where_min.uir](examples/where_min.uir) | `WHERE` and `CMPLT` as min |
| [index_stack.uir](examples/index_stack.uir) | `STACK`, `INDEX`, rank 1 to rank 0 |
| [recip.uir](examples/recip.uir) | `CAST` to `f32`, then `RECIP` |
| [call.uir](examples/call.uir) | `PARAM` and `CALL` |
| [symbolic.uir](examples/symbolic.uir) | A call body that bounds reasoning simplifies to `mod %a 100` |

## Spec notes

> **Spec note.** The week's title ends "Renderer?" and its tags include `renderer`, but the text asks only for an interpreter, and week 2 says "Students write a renderer". This chapter follows the text: rendering starts in week 2.

> **Spec note.** "All shapes are rank 0" and "We allow rank 1 shapes here" conflict. This chapter reads the second sentence as the rule: values may be rank 1 (stacks, params), ALU ops may not.

> **Spec note.** Week 1 says STACK inputs are limited "until week 4", but week 5 is where "STACK supports arbitrary inputs". This chapter only needs the week-1 rule; the week-4 and week-5 chapters will follow week 5's wording.

> **Interpretation.** The spec names the arg types `ParamArg` and `CallArg` without defining them. Here a PARAM's arg is its `slot` and `dtype`, and its `src[0]` is its shape, as in tinygrad (`[]` is an empty stack used only as a shape). A CALL needs no arg this week.

> **Interpretation.** The spec's "src[1:] are the params" is read as the argument values bound to the PARAMs, as tinygrad's `resolve_function` binds `args[slot]` (`tinygrad/schedule/prepare.py`). In tinygrad a CALL body is always a kernel; the syllabus's "lambda calculus" heading suggests any value can be a body, which is what this chapter does.

> **Interpretation.** "Via an interpreter" could also mean a separate evaluator. This chapter evaluates by rewriting, as tinygrad does: `UOp.simplify()` rewrites with its symbolic rules, and `int(u)` then requires a single value (`tinygrad/uop/ops.py`).

> **Interpretation.** tinygrad's `graph_rewrite` (`tinygrad/uop/ops.py`) works like the engine in Lesson 2 in its default mode, except that it does not enter CALL bodies unless asked (`enter_calls=True`). Its `bottom_up=True` flag means the opposite order (root first), because tinygrad draws the root at the bottom of its graphs.

## Quiz

1. `CONST 1` and `CONST 1.0` must be different UOps. What must a hash-cons key include besides the op, the sources and the arg's value, and why?
   <details><summary>Answer</summary>The arg's type. Many languages treat <code>1</code> and <code>1.0</code> as equal (Python also <code>True</code>), so a key with only the value would merge them, and the dtype of a CONST comes from its arg.</details>
2. What are `div -7 2` and `mod -7 2`? What does C's `-7 / 2` give?
   <details><summary>Answer</summary><code>-4</code> and <code>1</code> (floor). C gives <code>-3</code> (truncation toward zero), with remainder <code>-1</code>.</details>
3. Write `a - b` for `i32` values using only week-1 ops.
   <details><summary>Answer</summary><code>add a (mul b -1)</code>.</details>
4. If `%x` has bounds `[0, 3]`, what are the bounds of `add (mul %x 4) (mod %y 4)`, for any `%y`?
   <details><summary>Answer</summary><code>mul %x 4</code> is <code>[0, 12]</code> and <code>mod %y 4</code> is <code>[0, 3]</code>, so the sum is <code>[0, 15]</code>.</details>
5. Why can't a function in this IR call itself?
   <details><summary>Answer</summary>The body would have to contain the CALL that contains it, which is a cycle, and UOps form a DAG. It cannot receive itself as an argument either, because PARAMs hold data (<code>i32</code>, <code>f32</code>, <code>bool</code>), not functions.</details>
6. A bottom-up engine rewrites sources before their node. What does that guarantee to a rule?
   <details><summary>Answer</summary>When a rule sees a node, all its sources are already in normal form, so the rule only needs to handle simplified inputs (for example, a folded constant rather than <code>add 2 3</code>).</details>

## Sources

1. Filliâtre & Conchon, "Type-Safe Modular Hash-Consing", ACM SIGPLAN Workshop on ML 2006. https://usr.lmf.cnrs.fr/~jcf/publis/hash-consing2.pdf — hash-consing, in eight pages.
2. Alpern, Wegman, Zadeck, "Detecting Equality of Variables in Programs", POPL 1988. https://doi.org/10.1145/73560.73561 — value numbering: hash-consing for whole programs.
3. Rojas, "A Tutorial Introduction to the Lambda Calculus", 2015. https://arxiv.org/abs/1503.09060 — substitution, reduction, and recursion through the Y combinator.
4. ISO C11 committee draft N1570. https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf — §6.5.5 for truncating `/` and `%`; §6.5p5 for signed overflow being undefined.
5. Baader & Nipkow, *Term Rewriting and All That*, Cambridge University Press 1998. https://doi.org/10.1017/CBO9781139172752 — when rewriting terminates and gives a unique result.
6. Cousot & Cousot, "Abstract Interpretation", POPL 1977. https://doi.org/10.1145/512950.512973 — the theory behind bounds (interval analysis).
7. Tate, Stepp, Tatlock, Lerner, "Equality Saturation: A New Approach to Optimization", POPL 2009. https://doi.org/10.1145/1480881.1480915 — the alternative to greedy rewriting.
8. Willsey et al., "egg: Fast and Extensible Equality Saturation", POPL 2021. https://arxiv.org/abs/2004.03082 — e-graphs in practice.
9. tinygrad, commit 07821cae. https://github.com/tinygrad/tinygrad — `tinygrad/uop/ops.py` (UOp, hash-consing, bounds), `tinygrad/uop/symbolic.py` and `divandmod.py` (symbolic rules), `tinygrad/uop/uir.py` (the format).
