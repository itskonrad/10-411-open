# Chapter 1: UOps & Rewrites & Renderer?

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

**Builds on:** nothing in the syllabus; [Chapter 0](../00-prerequisites/README.md) lists what it assumes you know. **By the end you can:** read a UIR program into a hash-consed graph, compute its properties, reject invalid programs, run valid ones by rewriting them to constants, and simplify functions whose inputs are unknown.

## Contents

- [What you build](#what-you-build)
- [How to start](#how-to-start)
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

## What you build

By the end of this chapter you have a program, called `mycc` here, that reads a test written in UIR and prints a verdict. Three tests:

```text
# add.uir                  # sum_wrong.uir            # oob.uir
%sum  = add 2 3            %sum  = add 2 3            %v    = [10 20 30]
%test = assert %sum 5      %test = assert %sum 6      %test = assert (index %v 3) 0
```

and what `mycc` says about them:

```text
$ mycc add.uir
PASS
$ mycc sum_wrong.uir
FAIL line 2: got 5, expected 6
$ mycc oob.uir
ERROR line 2: index 3 is outside [0, 2]
```

- **PASS:** the program is valid and its `assert` holds.
- **FAIL:** the program is valid, your compiler ran it, and the `assert` does not hold.
- **ERROR:** the program breaks a rule (here, it reads past the end of a three-element stack), so it must not run at all. A run that reaches undefined behavior, such as `div 1 0`, is also an ERROR. Course tests never do that ([uir.md](../uir.md#arithmetic)), but your own tests might.

Only the first word counts when your compiler is checked against the [oracle](../oracle/README.md); the rest of the line is for you, so make it useful.

Inside `mycc`, a test goes through four stages:

```text
 .uir text ──▶ parse, check, compute properties ──▶ UOp graph ──▶ rewrite to normal form ──▶ verdict
               Lesson 1, Ops introduced                          Lessons 2 and 3
```

1. **Parse.** Each line becomes UOps, built through one constructor that hash-conses them.
2. **Check and compute properties**, during parsing. As each node is built, compute its `dtype`, `shape`, `cost` and `bounds` from its sources, and reject it if it breaks a rule. A few checks need the whole program (Lesson 1). An invalid program stops here with ERROR.
3. **Rewrite.** Apply rewrite rules, sources first, until none applies. With rules for folding constants, indexing stacks and inlining calls, every test program ends as an `assert` of two constants (or two stacks of constants, for a rank-1 assert).
4. **Verdict.** Compare them.

**Why rewriting, and not a plain interpreter?** A recursive `eval(u)` that returns a number would run these tests too; the oracle is one. But the syllabus asks the rewrite engine to run them: "The graph rewrite engine should be capable of 'running' these programs." The reason is what comes next.

From chapter 2 the graph gets a second ending: instead of reducing it to constants, you print it as C and run that. Once the C agrees with your interpreter, the rules you write now become the optimizer. Every constant folded at compile time is work the generated code does not do, and Lesson 3's symbolic rules are what simplify the index arithmetic of chapters 3–5.

So the part of this chapter that lasts longest is **the rule list and the engine that applies it**. Every later chapter adds ops to the same graph and rules to the same list. (Running programs lasts too: chapter 2 adds a small graph walker for memory, which rewriting alone cannot run, and checks your C against it.)

## How to start

The syllabus says "There is no starter code." This section is a path from an empty folder to a finished chapter. Each step ends with a check you can run; commit after each one. Run every command from the repo root.

**Step 0: set up.**

1. Fork this repo. Your compiler goes in [compiler/](../compiler/README.md), in any language, behind one command that takes a `.uir` path and prints one line: `python3 compiler/mycc.py FILE`, `./compiler/mycc FILE`, or similar.
2. Choose the language with care; you will live in it for the whole course. It should make these easy:
   - a hash map keyed by (op name, tuple of node references, value), for hash-consing;
   - exact 32-bit integer arithmetic that wraps, or big integers you can wrap;
   - real 32-bit float arithmetic (C, C++, Rust and Zig have it built in; Python needs a small trick, shown in Lesson 2);
   - recursion deep enough for long chains of nodes, or an explicit stack.

   The snippets in this chapter are Python because it is short to read; they illustrate ideas, and your code may look quite different.
3. Read [uir.md](../uir.md) and Lesson 1's "The format". Then make `tests/chapter1/` and write a few tests before any compiler code, copying the shape of [add.uir](examples/add.uir): tests for the ops you understand now, more as you read on, ten by the end of the chapter. Check that each one does what you think with the oracle:

   ```sh
   python3 -I oracle/uir.py tests/chapter1/*.uir
   ```

4. Learn the checker. It runs your command on test files and compares your verdicts with the oracle's:

   ```sh
   python3 -I tools/check_compiler.py --chapter 1 -- python3 compiler/mycc.py
   ```

   Pass files before `--` to check only those.

**Step 1: the thinnest working slice.** Make [add.uir](examples/add.uir) pass before writing anything general. Start from the hash-consing `UOp` constructor in Lesson 1: it is ten lines, and everything later depends on it. Then skip comment lines, split each line at the first `=`, split the right side on spaces, turn `2` and `3` into `CONST` UOps, `add` into an `ADD`, `assert` into an `ASSERT`, fold the `ADD`, compare. It is a few dozen lines.

```sh
python3 -I tools/check_compiler.py 01-uops-and-rewrites/examples/add.uir -- python3 compiler/mycc.py
```

Starting this thin means every later piece plugs into a pipeline that already runs from text to verdict, so you can test each piece the moment you write it. Replace the throwaway parser in step 2; do not grow it.

**Steps 2–7: grow it.**

| Step | Add | Read | Done when |
|------|-----|------|-----------|
| 2 | A real parser: comments, nested `(op ...)`, `[stacks]`, `key=value` args, every literal form, literal typing. And a printer that writes a graph back as UIR, with names it makes up (`%0`, `%1`, …) | Lesson 1, [uir.md](../uir.md) | Parsing a program, printing it, and parsing the output gives the same root UOp object |
| 3 | `dtype` and `shape` for every op, and the checks that use them: unknown ops and keys, mixed dtypes, rank-0 ALU sources, stack rules | Lesson 1, [Ops introduced](#ops-introduced) | Your invalid tests give ERROR, your valid ones do not |
| 4 | The rewrite engine, and constant folding for every ALU op with exact semantics | Lesson 2 | [floor_div](examples/floor_div.uir), [wrap](examples/wrap.uir), [where_min](examples/where_min.uir) and [recip](examples/recip.uir) give PASS |
| 5 | `bounds`, the INDEX bounds check, and a rule that folds INDEX of a stack | Lessons 2 and 3, [uir.md](../uir.md#bounds) | [index_stack](examples/index_stack.uir) gives PASS; `oob.uir` from [What you build](#what-you-build) (make it in `tests/chapter1/`) gives ERROR |
| 6 | `PARAM` and `CALL`: the call rules in [Ops introduced](#ops-introduced), free PARAMs are errors, the inline rule | Lesson 3 | [call](examples/call.uir) gives PASS |
| 7 | `cost`, the symbolic rules, and a way to print a rewritten body | Lesson 3 | [symbolic](examples/symbolic.uir) gives PASS, and its body prints as `mod %a 100` |

The chapter is done when `check_compiler.py --chapter 1` reports every example and every test under `tests/` matching the oracle, and step 7's printed body is right (the checker cannot see that). [oracle/tests/](../oracle/tests) has more small programs in `valid/` and `invalid/`; those that use only this chapter's ops make good extra tests.

**Habits that pay off.**

- **A printer is your debugger.** Print the graph as UIR after parsing and after rewriting, and read it. Most bugs are visible the moment you look.
- **Errors say where and why.** `ERROR line 2: index 3 is outside [0, 2]` beats `ERROR`. You will read thousands of these.
- **Shrink failing tests.** When a test fails, delete lines until it passes; the last line you deleted holds the bug. Keep the small program as a new test.
- **Every rule is a test.** When you add a rewrite rule, add a program it applies to, and one it must not apply to.

## Lectures

Intervals are written `[lo, hi]` throughout, both ends included.

### Lesson 1: course intro, Turing completeness, the UOp, the format, the first assignment

**What the course builds.** A compiler takes a program and produces a faster equivalent one. Ours takes small tensor programs and, by chapter 9, trains a language model on a GPU. Every chapter adds a few ops and one new idea, and your compiler must keep passing every earlier chapter's tests.

The syllabus calls the course "an exercise in slop management". *Slop* is code that passes today's tests without being the simplest correct thing: a special case where a general rule would do, two ways to represent one thing, a check in the wrong place. Each chapter builds on the last, so slop compounds. A second representation costs an hour in chapter 1; by chapter 6, every pass must handle both. This course's advice for chapter 1:

- **One data structure.** Every node is a `UOp`; no class per op, no separate syntax tree.
- **One constructor.** Every UOp is built through the hash-consing constructor, so no node can bypass it.
- **One rule list.** Constant folding, stack indexing and call inlining are all rewrite rules, applied by one engine, not special cases in a separate evaluator (chapter 2 adds memory, which needs a graph walk as well).
- **One place for properties and checks**: when a node is built. The exceptions are the few checks that need the whole program: that the root is the only `assert`, and that no PARAM is used outside a call body. Even the second can be a recursive property: the set of free PARAM slots, which a CALL empties for its body.

**The UOp.** Everything in the compiler is one data structure, `UOp(op, src, arg)`:

- `op` says what the node does: `ADD`, `CONST`, `INDEX`.
- `src` holds its inputs, which are other UOps.
- `arg` holds anything that is not a UOp: a constant's value, a dtype for `CAST`, a slot and dtype for `PARAM`.

There are no statements, variables or instructions, only a graph of values. Here is a program and the graph it builds:

```text
%v    = [10 20 30]                         ASSERT
%x    = add (index %v 2) 1                 /    \
%y    = mul %x %x                        MUL   CONST 961
%test = assert %y 961                    | |
                                         ADD
                                        /   \
                                    INDEX   CONST 1
                                    /    \
                                STACK    CONST 2
                               /  |  \
                              10  20  30
```

`MUL` has two edges to the same `ADD`: `%x` is computed once and used twice. Since `src` can only point at nodes that already exist, nothing can depend on itself, so the graph is a **DAG** (directed acyclic graph).

The names `%v`, `%x`, `%y` are gone: they exist only while parsing, to say which node a line means. Line order is gone too, apart from "defined before use". Later chapters rely on that freedom: they reorder, fuse and split computations, constrained only by the edges.

**Hash-consing.** The syllabus says "the UOp is hash consed": constructing a UOp that already exists returns the existing object. It buys three things:

1. **Equality is identity.** Two UOps are equal exactly when they are the same object, so "are these the same expression?" is a pointer comparison, however large the expressions. Rewrite rules ask this constantly: `x + x → x × 2` must know both sources are the same.
2. **Sharing for free.** Identical subexpressions are stored once. Compilers find the same sharing in whole programs under the name *value numbering* ([Alpern et al. 1988](#sources)).
3. **Cheap caches.** Each node is unique, so a dict keyed by node can cache anything computed about it: properties, rewrite results.

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

The key can use `src` directly because its elements are already unique objects, so comparing them is cheap. The rest of the key must tell apart values your language considers equal. In Python, `True == 1 == 1.0`, so the key includes `type(arg)`; floats have two more traps, which the `repr` handles. [Filliâtre & Conchon 2006](#sources) covers hash-consing in eight pages.

The price is that **UOps never change**. A node is shared by every part of the program that built the same expression, so changing its `src` would silently change all of them. To "change" a node, build a new one.

> **Predict.** Is `UOp("ADD", (two, three)) is UOp("ADD", (three, two))`?
> <details><summary>Answer</summary>No. Sources are ordered, and hash-consing compares structure, not meaning. Lesson 3's canonical-order rule rewrites both into one form, and then they are the same node.</details>

**Recursive properties.** Because UOps never change, anything computed from a node and its sources is fixed forever. The syllabus calls these *recursive properties*: `dtype`, `shape`, `cost` and `bounds` this chapter (rules in [Properties introduced](#properties-introduced)). For the `%x` above:

| Node | dtype | shape | cost | bounds |
|------|-------|-------|------|--------|
| `[10 20 30]` | `i32` | `(3,)` | 0 | `[10, 30]` |
| `index … 2` | `i32` | `()` | 0 | `[10, 30]` |
| `add … 1` | `i32` | `()` | 1 | `[11, 31]` |

Each row uses only the rows above it. That suggests where to compute them: **in the constructor**, the first time a node is built, since its sources already exist and already have theirs. While parsing, the same moment is the right place to check the node's rules: an invalid node never enters the graph, and an error naturally points at the line that first wrote it. Checks belong to the program as written, so run them only while parsing. Nodes the rewrite engine builds later still need their properties, because rules read `bounds`, but not the checks.

**The format.** Tests are written in UIR, a text form of the graph. Read [uir.md](../uir.md) now. In short: each line binds a name; sources come first, then `key=value` args; `(op ...)` nests; `[a b c]` is a stack; the last line is the root.

Parsing is direct: each line, and each nested `(op ...)`, is one UOp constructor call. Take the line `%x = add (index %v 2) 1`:

1. **Tokens:** `%x` `=` `add` `(` `index` `%v` `2` `)` `1`.
2. **Structure:** the op is `add`. Its first source starts with `(`, so parse a nested op until the matching `)`: op `index` with sources `%v` and `2`. The second source is the literal `1`. No `key=value` args follow.
3. **Nodes, innermost first:** look up `%v` (the STACK from the line before); build `CONST 2` and `INDEX(stack, 2)`; build `CONST 1` and `ADD(index, 1)`; bind `%x` to the `ADD`.

One recursive function handles nesting: on `(`, call itself; on `[`, read values until `]` and build a `STACK`. Because of hash-consing, writing `(index %v 2)` inline or on its own line builds the same node.

**Literals take their dtype from what they meet.** `1` is not `i32` or `f32` on its own: in `add %x 1` it is `f32` if `%x` is `f32`, and `i32` if `%x` is `i32` ([rules](../uir.md#literals)). Since the dtype is part of a `CONST`'s arg, the parser must know it before building the `CONST`. So parse an op's sources first, then type its literals from their typed neighbors, then build:

| UIR | Literals become |
|-----|-----------------|
| `add %f 1`, with `%f` `f32` | `CONST 1.0` (`f32`) |
| `add 2 3` | `CONST 2`, `CONST 3` (`i32`; nothing typed to match) |
| `add 2 2.5` | `CONST 2.0`, `CONST 2.5` (`f32`; a float literal is among them) |
| `%a = 3` | `CONST 3` (`i32`; a literal on its own line) |

**Common mistakes.**

- A second way to build UOps that skips the cache: a copy helper, or a deserializer. Identity checks then fail without any error.
- Changing a UOp's fields after building it.
- Leaving the type out of the hash-cons key, so `1`, `1.0` and `true` become one node.
- Treating names as nodes. `%a = 3` and `%b = 3` are the same UOp; the names are only parser bookkeeping.

**Turing completeness.** A language is Turing complete if it can express any computation, including ones that never finish. The lambda calculus is, because a function can be applied to itself ([Rojas 2015](#sources)). Our IR is not:

> **Interpretation.** The syllabus lists the topic without a conclusion. A UOp graph is acyclic, so a function body cannot contain the call to itself. Parameters hold only `i32`, `f32` and `bool` values, never functions, so a body cannot receive itself as an argument either. With no recursion, and with chapter 3's loops having bounds fixed before they start, every program terminates. tinygrad reaches Turing completeness only through `BACKEDGE`, a while loop the course does not include.

This is a feature. A compiler that can see a whole program, with all its loop bounds, can decide how to split, fuse and schedule it. A general-purpose compiler cannot know how often a `while` loop runs; yours always can.

**The first assignment** is in [Assignment](#assignment); [How to start](#how-to-start) breaks it into steps.

### Lesson 2: ALU ops, bottom-up greedy rewrite engines, constant folding

**The ALU ops.** The set is small on purpose: fewer ops means fewer rewrite rules, a smaller renderer in chapter 2, and fewer derivative rules in chapter 6. Other operations are combinations ([Ops introduced](#ops-introduced) has every op's dtypes; this chapter they take rank-0 sources only):

| You want | Write |
|----------|-------|
| −a | `mul a -1` |
| a − b | `add a (mul b -1)` |
| a > b | `cmplt b a` |
| not c (`bool`) | `xor c true` |
| a ≠ b (`bool`) | `xor a b` |
| min(a, b) | `where (cmplt a b) a b` |
| a / b (`f32`) | `mul a (recip b)` |

One cost: `mul a (recip b)` rounds twice, so it can differ from a true `a / b` in the last bit.

**Exact semantics.** Your interpreter and the C code you generate in chapter 2 must agree bit for bit, so the edge cases are fixed in [uir.md](../uir.md#arithmetic). The ones that catch everyone:

- **`i32` wraps.** `add 2147483647 1` is `-2147483648`. Python integers do not wrap, so wrap explicitly after every `i32` op. In C, signed overflow is undefined behavior ([N1570 §6.5p5](#sources)); GCC and Clang make it wrap with `-fwrapv`.
- **`DIV` and `MOD` floor.** `div -7 2` is `-4` and `mod -7 2` is `1`, matching Python's `//` and `%`. C's `/` truncates toward zero and gives `-3` ([N1570 §6.5.5](#sources)). Floor division keeps index arithmetic regular: `mod x 4` is always in `[0, 3]`, even for negative `x`. Lesson 3 shows why that matters.
- **`f32` rounds after every op.** Python floats are 64-bit. `add (add 16777216.0 1.0) 1.0` is `16777216.0` in `f32`, because each `+ 1` rounds away, but adding in 64-bit and rounding once at the end gives `16777218.0`.
- **Division by zero.** Python raises an exception for `1 / 0.0`; `recip 0.0` must give `inf`.

In Python, round to `f32` by storing the value in a 32-bit float array:

```python
from array import array

def f32(x: float) -> float:
    return array("f", [x])[0]  # nearest f32; inf if too large

assert f32(16777216.0 + 1.0) == 16777216.0  # 2^24 + 1 is not an f32: ties to even
assert f32(0.1) != 0.1
```

Compute an `f32` op in 64-bit and round the result at once: `f32(a + b)`, `f32(a * b)`. For `+`, `−`, `×` and `÷` of two `f32` values, that gives exactly the `f32` result, because a 64-bit float has more than twice the precision ([Figueroa 1995](#sources)). Only rounding *once at the end* of several ops is wrong.

**Rewriting.** Simplifying `add (mul 2 3) (add %x 0)` by hand, you would say: `mul 2 3` is `6`; `add %x 0` is `%x`; so the whole thing is `add 6 %x`. Each step looks at one node and replaces it. A **rewrite rule** is exactly that: a function from a UOp to a replacement UOp, or `None` if it does not apply. A **rewrite engine** applies rules until none apply, at which point the graph is in *normal form*.

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

Here is the engine running a whole program, `%min = where (cmplt 3 5) 3 5` then `%test = assert %min 3`, with folding rules for every ALU op:

| Visit | Node | Sources, already rewritten | Rule | Result |
|-------|------|----------------------------|------|--------|
| 1 | `3` | none | none | `3` |
| 2 | `5` | none | none | `5` |
| 3 | `cmplt 3 5` | `3`, `5` | fold `CMPLT` | `true` |
| 4 | `where … 3 5` | `true`, `3`, `5` | fold `WHERE` | `3` |
| 5 | `assert … 3` | `3`, `3` | none: `ASSERT` is not folded | `assert 3 3` |

Every `3` in the program is the same `i32` node, so the engine rewrites it once and the memo answers its other two uses. (The engine also revisits each rule's result, such as `true`, to see if it simplifies further; those visits find nothing to do.) The root ends as `assert 3 3`: two equal constants, so the verdict is PASS.

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

`add_zero` shows why hash-consing helps rewriting: "is this the constant 0?" is an `is` check. You do not need one function per op: one folding rule, driven by a table from op and dtype to a function on values, keeps all the exact semantics in one place, where they are easy to check against [uir.md](../uir.md#arithmetic).

**The interpreter is the rewrite engine.** The syllabus asks that the engine can "run" programs. A program with no unknown inputs rewrites all the way down to constants if you have three kinds of rule:

- constant folding for every ALU op, with the exact semantics above;
- `INDEX` of a constant stack by a constant becomes the element;
- `CALL` becomes its inlined body (Lesson 3).

Then the `ASSERT` compares two constants (or stacks of constants), and running the program is checking them.

**Common mistakes.**

- Using your language's arithmetic unchanged: C's truncating `/`, Python's integers that never wrap, 64-bit floats that never round to `f32`.
- A rule that reads the old node's sources (`u.src`) instead of the rewritten ones (`new.src`), so it never sees folded constants.
- No memo. A chain of 30 lines `%b = add %a %a`, `%c = add %b %b`, … is 31 nodes, but walked as a tree it is over a billion visits.
- Folding to a constant of the wrong dtype: `cmplt` gives `bool`, and folding an `f32` op must give an `f32` constant even when the value is whole, like `2.0`.

### Lesson 3: call/param, symbolic simplification, computer algebra systems

**Functions as graphs.** `PARAM` is a placeholder for an argument; its `slot` says which one. `CALL` applies a body to arguments: `src[0]` is the body, and `src[1 + i]` fills `PARAM slot=i`. This is the lambda calculus's application, and running a call is its *beta reduction*: substitute the arguments for the parameters. [call.uir](examples/call.uir) defines f(x, y) = x × x + y and calls f(3, 4). Here is how the engine runs it:

```text
call (add (mul %x %x) %y) 3 4
  the body is rewritten first: nothing folds, %x and %y are unknown
→ add (mul 3 3) 4         inline: slot 0 is 3, slot 1 is 4
→ add 9 4                 fold MUL
→ 13                      fold ADD
```

```python
import functools

def inline(call: UOp) -> UOp:
    body, args = call.src[0], call.src[1:]

    @functools.cache
    def sub(u: UOp) -> UOp:
        if u.op == "PARAM":
            return args[u.arg]  # simplified: here a PARAM's arg is just its slot; yours also holds the dtype
        if u.op == "CALL":  # an inner body is closed: only its arguments change
            return UOp("CALL", (u.src[0], *map(sub, u.src[1:])), u.arg)
        return UOp(u.op, tuple(map(sub, u.src)), u.arg)

    return sub(body)
```

`functools.cache` plays the role of the engine's memo: a node shared inside the body is substituted once. Two rules keep inlining correct:

- **Bodies are closed.** A body may use only its own PARAMs. So substitution stops at an inner CALL's body: those PARAMs belong to the inner function.
- **Arguments match.** A call passes one argument per slot, each with the PARAM's dtype and shape ([the exact rules](#ops-introduced)). Check this when building the CALL, not when inlining, so that a bad call is an error even if nothing runs it.

UIR names like `%x` are not part of a UOp; a PARAM is just its slot and dtype. So f(x) = x + 1 and g(y) = y + 1 are the same UOp: hash-consing gives you what the lambda calculus calls *alpha-equivalence* for free.

Inlining is a rewrite rule like any other: `CALL` becomes `inline(call)`. Add it to your rule list and calls disappear before folding. Keeping it a rule, rather than evaluating a body with a separate environment, means one engine does all the work, and the body's simplifications are shared by every call to it.

**Symbolic simplification.** A body with PARAMs cannot fold to a constant, but it can still simplify, using rules that hold for *every* value of the unknowns. In this chapter the unknowns are PARAMs. From chapter 2 they are also values loaded from memory, and from chapter 3 loop indices: then expressions like `div (add (mul %i 4) %j) 4` are everywhere, and simplifying them is what turns index arithmetic back into simple loops. The rule families:

| Family | Example |
|--------|---------|
| Identities | x + 0 → x, x × 1 → x, x × 0 → 0 |
| Reassociation | (x + 3) + 5 → x + 8 |
| Combining terms | x + x → x × 2, x × 2 + x × 3 → x × 5 |
| Canonical order | 3 + x → x + 3, so equal sums hash-cons to one UOp |
| Bounds | `cmplt %x 10` → `true` when `%x`'s bounds say it is at most 9 |

Rules work together. With "constants go last" as the canonical order, `(3 + x) + 5` becomes:

```text
add (add 3 %x) 5
→ add (add %x 3) 5        canonical order, on the inner add first (bottom-up)
→ add %x (add 3 5)        reassociate: (x + a) + b → x + (a + b) when a and b are constants
→ add %x 8                fold
```

All of these are exact for `i32`, because wrapping arithmetic still obeys the usual algebra. For `f32`, check each rule on its own. `x × 1 → x`, `x + x → x × 2` and canonical order are safe. Reassociating, and combining terms like `x × 2 + x × 3 → x × 5`, change rounding. `x + 0 → x` is wrong for `x = -0.0`. `x × 0 → 0` is wrong when `x` is NaN or infinite (the result is NaN) or negative (the result is `-0.0`).

**Bounds.** The last family needs **bounds**, the interval `[vmin, vmax]` a value can take. Constants have exact bounds, ALU ops combine their sources' bounds, and anything unknown gets the full range of its dtype ([Cousot & Cousot 1977](#sources) is the general theory, *abstract interpretation*). The exact rules every compiler must use, no tighter and no looser, are in [uir.md](../uir.md#bounds). The snippet below shows the idea for four ops, simplified: it skips uir.md's rule for sources with exact bounds, and its `MOD` is looser than uir.md's. Implement uir.md's rules, not the snippet.

```python
import functools

I32 = (-2**31, 2**31 - 1)

@functools.cache
def bounds(u: UOp) -> tuple[int, int]:  # simplified (see above); i32 values; only CONST, MOD, ADD and MUL
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

Bounds pay off with `DIV` and `MOD`. Take the body of [symbolic.uir](examples/symbolic.uir), where `%a` and `%y` are PARAMs:

```text
%x = mod %a 100
%g = div (add (mul %x 4) (mod %y 4)) 4
```

| Node | Bounds | Why |
|------|--------|-----|
| `%a`, `%y` | `[-2^31, 2^31 − 1]` | unknown: the full `i32` range |
| `mod %a 100` | `[0, 99]` | floor mod by 100 |
| `mul %x 4` | `[0, 396]` | the products of the ends: 0 × 4 and 99 × 4 |
| `mod %y 4` | `[0, 3]` | floor mod by 4 |
| `add …` | `[0, 399]` | add the ends |
| `div … 4` | `[0, 99]` | divide the ends |

Is `%g` just `%x`? For any `x` and any `r` in `[0, 3]`, ⌊(4x + r) / 4⌋ = x + ⌊r / 4⌋ = x. That algebra assumes nothing wraps, and the table proves it: every interval stays inside `i32`. So the rule is: `div (add (mul x c) r) c → x`, for one constant `c > 0` in both places, when the bounds show that neither the `mul` nor the `add` can wrap and that `r` is in `[0, c − 1]`. Test "cannot wrap" on the interval before widening: a full-range result cannot tell "might wrap" from "really spans all of `i32`". If `%x` were an unbounded PARAM, `mul %x 4` could wrap (at `x = 2^29`) and the rule must not fire.

The rule also needs floor semantics: with C's `%`, `y = -1` gives a remainder of `-1`, and for `x = 1` C's quotient is `0`, not `1`. Index arithmetic in chapters 3–5 is full of `div` and `mod` by shape sizes, with loop indices whose bounds are known; rules like this turn it back into simple loops.

**Testing a rule.** A wrong rule is worse than a missing one: it silently changes what programs compute. Before trusting a rule, try to break it. Evaluate both sides on many inputs, with the edge values first (0, ±1, the wrap points), because that is where wrong rules fail:

```python
import itertools
import random

EDGES = [0, 1, 2, 3, -1, -2, 2**29, 2**31 - 1, -2**31]

def counterexample(lhs, rhs, nargs: int, trials: int = 10_000):
    """Arguments where two i32 functions disagree, or None. Edge values first, then random ones."""
    rng = random.Random(0)
    edges = itertools.product(EDGES, repeat=nargs)
    randoms = (tuple(rng.randint(*I32) for _ in range(nargs)) for _ in range(trials))
    return next((args for args in itertools.chain(edges, randoms) if lhs(*args) != rhs(*args)), None)

def g(x: int, y: int) -> int:  # div (add (mul x 4) (mod y 4)) 4, with i32 wrapping
    return wrap32(wrap32(x * 4) + y % 4) // 4

assert counterexample(g, lambda x, y: x, 2) == (2**29, 0)  # unsound: mul wraps
assert counterexample(lambda a, y: g(a % 100, y), lambda a, y: a % 100, 2) is None
```

Finding no counterexample is not a proof, but finding one is: the first assert shows the rule without its bounds condition is wrong. In your compiler you do not need Python copies of each side. Rewrite a body once with your full rule list and once without the new rule, call both with the same arguments, and compare the results. Your interpreter checks your optimizer.

**Computer algebra systems.** A symbolic simplifier is a small computer algebra system (CAS): it rewrites expressions toward a canonical form, so that equal expressions become identical UOps. A full CAS cannot always decide whether two expressions are equal, and neither can yours. That is fine: a missed simplification makes code slower, never wrong. What is never fine is the opposite mistake: **a rewrite must never change a program's meaning**, including at the edges (wrapping, NaN, `-0.0`, negative numbers).

Greedy rules commit to one rewrite at a time. *Equality saturation* instead keeps every equivalent form in an *e-graph* (a graph whose nodes are sets of equal expressions) and picks the cheapest at the end ([Tate et al. 2009](#sources); [Willsey et al. 2021](#sources)). It avoids rule-order problems at a cost in memory. The `cost` property is the kind of measure such a choice needs; for now you only compute it.

**Common mistakes.**

- Applying an `i32` rule to `f32` values.
- Substituting into an inner CALL's body when inlining.
- Checking a CALL's arguments only when it is inlined, so a bad call that nothing runs is not reported.
- Validating with bounds computed after rewriting. Checks use the program as written ([why](../uir.md#validation)); otherwise a program's validity would depend on which rules your compiler happens to have.

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
- **STACK sources are constants**, and values are at most rank 1 (rank 2 arrives in chapter 5). `[1 2 3]` is allowed; `[[1 2] [3 4]]` (rank 2) and `[%x 2]` (not a constant) are not.
- **INDEX stays in bounds.** Each index's bounds must lie inside `[0, n − 1]`. A PARAM's bounds are its dtype's full range, so a body that indexes by a parameter writes `index [1 2 3] (mod %p 3)`.
- **Dtypes match.** Typed operands of an ALU op have the same dtype ([conventions](../uir.md#mixing-dtypes)).
- **PARAMs live in bodies.** A PARAM the root reaches outside any CALL body is an error: nothing binds it.
- **Calls match their bodies.** A CALL passes one argument for every slot from 0 up to the highest PARAM slot in its body, including slots the body never uses (PARAMs inside an inner CALL's body do not count). Each argument has its PARAM's dtype and shape. Two different PARAMs with the same slot in one body are an error.
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

Start by writing ten tests of your own in UIR (the syllabus asks for ten each week), and check them with the [oracle](../oracle/README.md). [How to start](#how-to-start) gives an order to build things in.

Write a program that takes a `.uir` file and:

1. **Parses** it into hash-consed UOps ([uir.md](../uir.md)), typing each literal ([rules](../uir.md#literals)).
2. **Checks** it: known ops, valid args, and every rule in [Ops introduced](#ops-introduced). Report the line of the first problem.
3. **Computes** `dtype`, `shape`, `cost` and `bounds` for every node.
4. **Runs** it by rewriting to normal form with call inlining, constant folding and constant indexing, then checks the root `ASSERT`.
5. **Reports** pass, or the actual and expected values.

Also implement the symbolic rules of Lesson 3:

- **Required:** the identity, reassociation and canonical-order rules, and the two bounds rules (`cmplt` against a bound, and the `div` rule with its bounds conditions). Combining terms is optional.
- **How to see them work:** no assert can tell whether a correct rule fired, since every program folds to constants. Instead, rewrite the body of [examples/symbolic.uir](examples/symbolic.uir) (the CALL's `src[0]`) on its own, before inlining, and print it, in UIR or any readable form, behind a debug flag of your own. It should be `mod` of slot 0 by `100`: `mod %a 100`, whatever names your printer uses.
- **How to catch a wrong rule:** an assert can. A test whose body is `div (add (mul %a 4) (mod %y 4)) 4` with an unbounded `%a`, called with `a = 536870912` and `y = 0`, must give `-536870912` (`mul` wraps to −2^31), not `a`.

Restrictions this chapter: ALU ops take rank-0 sources; values are at most rank 1; stack sources are constants. Keep the rewrite rules in a list you can extend: chapters 2–6 add to it. The renderer comes in chapter 2; for now, rewriting is the whole compiler.

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

> **Spec note.** The week's title ends "Renderer?" and its tags include `renderer`, but the text asks only for an interpreter, and week 2 says "Students write a renderer". This chapter follows the text: rendering starts in chapter 2.

> **Spec note.** "All shapes are rank 0" and "We allow rank 1 shapes here" conflict. This chapter reads the second sentence as the rule: values may be rank 1 (stacks, params), ALU ops may not.

> **Spec note.** Week 1 says STACK inputs are limited "until week 4", but week 5 is where "STACK supports arbitrary inputs". This chapter only needs the week-1 rule; chapters 4 and 5 will follow week 5's wording.

> **Interpretation.** The spec names the arg types `ParamArg` and `CallArg` without defining them. Here a PARAM's arg is its `slot` and `dtype`, and its `src[0]` is its shape, as in tinygrad (`[]` is an empty stack used only as a shape). A CALL needs no arg this week.

> **Interpretation.** The spec's "src[1:] are the params" is read as the argument values bound to the PARAMs, as tinygrad's `resolve_function` binds `args[slot]` (`tinygrad/schedule/prepare.py`). In tinygrad a CALL body is always a kernel; the syllabus's "lambda calculus" heading suggests any value can be a body, which is what this chapter does.

> **Interpretation.** "Via an interpreter" could also mean a separate evaluator. This chapter evaluates by rewriting, as tinygrad does: `UOp.simplify()` rewrites with its symbolic rules, and `int(u)` then requires a single value (`tinygrad/uop/ops.py`).

> **Interpretation.** tinygrad's `graph_rewrite` (`tinygrad/uop/ops.py`) works like the engine in Lesson 2 in its default mode, except that it does not enter CALL bodies unless asked (`enter_calls=True`). Its `bottom_up=True` flag means the opposite order: root first.

## Quiz

1. `CONST 1` and `CONST 1.0` must be different UOps. What must a hash-cons key include besides the op, the sources and the arg's value, and why?
   <details><summary>Answer</summary>The arg's type. Many languages treat <code>1</code> and <code>1.0</code> as equal (Python also <code>True</code>), so a key with only the value would merge them, and the dtype of a CONST comes from its arg.</details>
2. Why must a UOp never be changed after it is built?
   <details><summary>Answer</summary>Hash-consing shares it: every part of the program that built the same expression holds the same object, so changing it changes all of them. Build a new UOp instead.</details>
3. What are `div -7 2` and `mod -7 2`? What does C's `-7 / 2` give?
   <details><summary>Answer</summary><code>-4</code> and <code>1</code> (floor). C gives <code>-3</code> (truncation toward zero), with remainder <code>-1</code>.</details>
4. Write `a - b` for `i32` values using only chapter-1 ops.
   <details><summary>Answer</summary><code>add a (mul b -1)</code>.</details>
5. If `%x` has bounds `[0, 3]`, what are the bounds of `add (mul %x 4) (mod %y 4)`, for any `%y`?
   <details><summary>Answer</summary><code>mul %x 4</code> is <code>[0, 12]</code> and <code>mod %y 4</code> is <code>[0, 3]</code>, so the sum is <code>[0, 15]</code>.</details>
6. Why can't a function in this IR call itself?
   <details><summary>Answer</summary>The body would have to contain the CALL that contains it, which is a cycle, and UOps form a DAG. It cannot receive itself as an argument either, because PARAMs hold data (<code>i32</code>, <code>f32</code>, <code>bool</code>), not functions.</details>
7. A bottom-up engine rewrites sources before their node. What does that guarantee to a rule?
   <details><summary>Answer</summary>When a rule sees a node, all its sources are already in normal form, so the rule only needs to handle simplified inputs (for example, a folded constant rather than <code>add 2 3</code>).</details>
8. Is `x + 0 → x` a correct rule for `f32`? Give a reason.
   <details><summary>Answer</summary>No: for <code>x = -0.0</code>, <code>-0.0 + 0.0</code> is <code>+0.0</code>, so the rule changes the result's sign.</details>

## Sources

1. Filliâtre & Conchon, "Type-Safe Modular Hash-Consing", ACM SIGPLAN Workshop on ML 2006. https://usr.lmf.cnrs.fr/~jcf/publis/hash-consing2.pdf — hash-consing, in eight pages.
2. Alpern, Wegman, Zadeck, "Detecting Equality of Variables in Programs", POPL 1988. https://doi.org/10.1145/73560.73561 — global value numbering: finding equal values across a whole program.
3. Rojas, "A Tutorial Introduction to the Lambda Calculus", 2015. https://arxiv.org/abs/1503.09060 — substitution, reduction, and recursion through the Y combinator.
4. ISO C11 committee draft N1570. https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf — §6.5.5 for truncating `/` and `%`; §6.5p5 for signed overflow being undefined.
5. Figueroa, "When is double rounding innocuous?", ACM SIGNUM Newsletter 30(3) 1995. https://doi.org/10.1145/221332.221334 — why computing an `f32` op in 64-bit and rounding once gives the exact `f32` result.
6. Baader & Nipkow, *Term Rewriting and All That*, Cambridge University Press 1998. https://doi.org/10.1017/CBO9781139172752 — when rewriting terminates and gives a unique result.
7. Cousot & Cousot, "Abstract Interpretation", POPL 1977. https://doi.org/10.1145/512950.512973 — the theory behind bounds (interval analysis).
8. Tate, Stepp, Tatlock, Lerner, "Equality Saturation: A New Approach to Optimization", POPL 2009. https://doi.org/10.1145/1480881.1480915 — the alternative to greedy rewriting.
9. Willsey et al., "egg: Fast and Extensible Equality Saturation", POPL 2021. https://arxiv.org/abs/2004.03082 — e-graphs in practice.
10. tinygrad, commit 07821cae. https://github.com/tinygrad/tinygrad — `tinygrad/uop/ops.py` (UOp, hash-consing, bounds), `tinygrad/uop/symbolic.py` and `divandmod.py` (symbolic rules), `tinygrad/uop/uir.py` (the format).
