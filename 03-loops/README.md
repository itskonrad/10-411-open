# Week 3: Loops

> **`loops` · `gemms` · `convs`**
>
> Recursive properties introduced:
> ```
> ranges:dict[UOp, None]
> ended_ranges:dict[UOp, UOp]
> ```
>
> Ops introduced:
> ```
> RANGE -- src is the end of the range (3 means 0,1,2) and arg is the range name
> END -- srcs are (passthrough, range)
> ```
>
> Should be simple, and we can write gemms and convs in this language. If you still have an interpreter at this point, it's time to write a renderer.
>
> Also, this is the first week you will (likely) require a rewrite engine, in order to order the ranges properly.
>
> — the syllabus, week 3

**Builds on:** [Week 2](../02-memory-and-shape/README.md). **By the end you can:** write loops in UIR, place every node inside the loops it belongs to, and render nested C loops, including a matrix multiply and a convolution.

## Contents

- [Lectures](#lectures)
  - [Lesson 1: loops as values](#lesson-1-loops-as-values)
  - [Lesson 2: ordering the ranges](#lesson-2-ordering-the-ranges)
  - [Lesson 3: gemms and convs](#lesson-3-gemms-and-convs)
- [Ops introduced](#ops-introduced)
- [Properties introduced](#properties-introduced)
- [Assignment](#assignment)
- [Example programs](#example-programs)
- [Spec notes](#spec-notes)
- [Quiz](#quiz)
- [Sources](#sources)

## Lectures

### Lesson 1: loops as values

**A loop is two nodes.** `RANGE` is the loop variable: `range 3 slot=0` takes the values 0, 1 and 2, and its slot names the loop. `END` closes the loop: `end %effect %r` runs `%effect` once for every value of `%r`. From the draft course page:

```text
%buf   = buffer 3 slot=0 dtype=i32
%i     = range 3 slot=0
%write = store (index %buf %i) %i
%done  = end %write %i
%test  = assert (after %buf %done) [0 1 2]
```

`%write` uses `%i`, so it is inside the loop. `%done` is the whole loop, and `after %buf %done` is the buffer once the loop has finished. The nodes that use `%i` are ordinary nodes; nothing marks the loop body. What is inside a loop is decided by what each node depends on.

**`ranges`: which loops a node uses.** A node uses every loop whose RANGE it depends on and that has not been closed on the way:

```python
import functools

@functools.cache
def ranges(u: UOp) -> frozenset:  # the loops u uses
    if u.op == "RANGE":
        return frozenset({u})
    inside = frozenset().union(*(ranges(s) for s in u.src))
    return inside - {u.src[1]} if u.op == "END" else inside

@functools.cache
def ended_ranges(u: UOp) -> dict:  # each loop closed in u's graph -> the END that closes it
    out: dict = {}
    for s in u.src:
        out |= ended_ranges(s)
    if u.op == "END":
        out[u.src[1]] = u
    return out
```

In the example, `ranges(%write)` is `{%i}`, `ranges(%done)` is empty, and `ended_ranges(%done)` maps `%i` to `%done`. (The spec types `ranges` as a `dict[UOp, None]`, an ordered set; a set is simpler here.)

**Loops nest the way their ENDs nest.** In `end (end %e %k) %o`, where `%e` uses `%o`, loop `k` is inside loop `o`: `o` is still open where `k` ends, because `o` is in the `ranges` of `end %e %k`. We say `o` *encloses* `k`. (A loop that ends before `o` starts is a sibling, not enclosed, even if `o` waits for it through `AFTER`.)

**When a node runs.** A node runs once for each combination of values of the loops in its `ranges` and of every loop enclosing those ([uir.md](../uir.md#evaluation)). That one rule settles what statement order used to:

- `%write` depends on `%i`, so it runs three times.
- A node with no loop in its `ranges` runs once, before the loops, even if a loop uses it. A `load %scale` needed inside a loop is read once. This is *hoisting*, and here it is the meaning of the program, not an optimization (an [interpretation](../uir.md#evaluation)). Where each computation runs within a loop nest is the central choice in Halide ([Ragan-Kelley et al. 2013](#sources)).
- A node that uses only an inner loop `k` still runs once per value of every loop around `k`: in [examples/enclosing_loops.uir](examples/enclosing_loops.uir), a counter incremented in `k` (3 values) inside `o` (2 values) ends at 6.

**Rules that keep loops well formed.** Your checker rejects a program unless:

- **END closes a loop that its effect uses.** `end %e %r` needs `%r` in `ranges(%e)`, and `%e` is an effect (`void`). For several stores in one loop, group them first: `end (after %s2 %s1) %i` ([examples/two_stores.uir](examples/two_stores.uir)).
- **Each RANGE is ended once**, and its slot is unique in the program, call bodies included. Two loops need two RANGEs.
- **Nothing escapes a loop.** The root's `ranges` is empty, and a value computed inside a loop cannot be used after the loop's END: with `%v = load (index %buf %i)`, using `%v` after `%done` is rejected, because `%v` has a different value on each iteration.
- **Loop bounds are constants** of at least 1, so every loop's trip count is known before it runs.

**Bounds make indexing safe.** A RANGE's bounds are `[0, end − 1]` ([uir.md](../uir.md#bounds)), so the checks from weeks 1 and 2 extend to loops with no new machinery. In [examples/nested.uir](examples/nested.uir), `i` is in `[0, 1]` and `j` in `[0, 2]`, so `i*3 + j` is in `[0, 5]`, inside a buffer of 6.

### Lesson 2: ordering the ranges

**The problem.** A topological order puts every node after its sources, but rendering loops needs more: every node must sit inside its innermost loop, and the loops must nest. A plain toposort of the gemm in Lesson 3 can open loop `k` and then emit the accumulator's initial store inside it, which would reset the accumulator on every step.

**Moving each loop's body.** Take a toposort and move each loop's body to just before the loop's END, recursively:

```python
def nest(nodes: list, open_: frozenset = frozenset()) -> list:
    out = []
    for u in nodes:
        if not ranges(u) <= open_:
            continue  # inside a loop that is not open here: placed with that loop's END
        if u.op == "END":
            effect, r = u.src
            loops = {r} | set(ended_ranges(effect))  # r, loops nested in it, earlier loops it waits for
            inside = [v for v in nodes if ranges(v) & loops and v is not r]
            out += [r, *nest(inside, open_ | {r})]
        out.append(u)
    return out
```

`ended_ranges` of an END's effect lists the loops nested in it, plus any earlier loops whose END the body waits for. Nodes of those earlier loops land in `inside` too, but are skipped there, because their END was already placed. The result is the toposort with each RANGE moved to the start of its loop and each END at its end. Three facts make it correct:

- **Nothing inside a loop is needed outside it** except through its END, so moving the body to just before the END breaks no dependency.
- **A node lands in the innermost loop of its `ranges`**, and so runs once per value of that loop and every loop around it: the [evaluation rule](../uir.md#evaluation). An accumulator init that depends on `i` and `j` lands inside `j` but before `k` opens.
- **Order inside a loop is the toposort's**, so every dependency still points backwards.

`nest` is quadratic or worse; that is fine for test programs.

**Rendering loops.** With nodes in this order, chapter 2's `render` needs two more cases:

```text
        # fragment: add to chapter 2's render, before the final else
        elif u.op == "RANGE":                # open a loop
            names[u] = f"r{u.arg}"
            lines.append(f"for (int32_t r{u.arg} = 0; r{u.arg} < {a[0]}; r{u.arg}++) {{")
        elif u.op == "END":                  # close it
            names[u] = None
            lines.append("}")
```

<details><summary>The whole <code>render</code> with these cases, as tested</summary>

```python
C_EXPR = {"ADD": "{} + {}", "MUL": "{} * {}", "CMPLT": "{} < {}", "WHERE": "{} ? {} : {}"}

def render(order: list, ctype) -> str:
    names, lines = {}, []
    for n, u in enumerate(order):
        a = [names[s] for s in u.src]
        if u.op == "CONST":
            names[u] = repr(u.arg) + ("f" if type(u.arg) is float else "")  # bool needs chapter 2's table
        elif u.op == "STACK":
            names[u] = None                  # here only a BUFFER's shape source, []: not rendered
        elif u.op == "BUFFER":               # a pointer parameter; rank-0 memory is element 0
            names[u] = f"buf{u.arg}" if u.src[0].op == "CONST" else f"buf{u.arg}[0]"
        elif u.op == "INDEX":
            names[u] = f"{a[0]}[{a[1]}]"
        elif u.op == "AFTER":
            names[u] = a[0]
        elif u.op == "STORE":
            names[u] = None
            lines.append(f"{a[0]} = {a[1]};")
        elif u.op == "RANGE":
            names[u] = f"r{u.arg}"
            lines.append(f"for (int32_t r{u.arg} = 0; r{u.arg} < {a[0]}; r{u.arg}++) {{")
        elif u.op == "END":
            names[u] = None
            lines.append("}")
        else:
            names[u] = f"v{n}"
            expr = a[0] if u.op == "LOAD" else C_EXPR[u.op].format(*a)
            lines.append(f"{ctype(u)} v{n} = {expr};")
    return "\n".join(lines)
```

</details>

The syllabus says: "If you still have an interpreter at this point, it's time to write a renderer." From this week, the renderer is your compiler; keep the interpreter only as the other half of your differential tests.

**Inlining loops.** Week 2's inliner gives each inlined ALLOC a fresh slot. Loops need the same: two calls of a body that contains a loop share one RANGE after hash-consing, so the inliner gives each inlined RANGE a fresh slot too. For the same reason, a RANGE may not be used both inside a call body and outside it.

> **Interpretation.** The syllabus expects "a rewrite engine, in order to order the ranges properly". You do not need one: `nest` computes the placement directly. tinygrad uses a rewrite: the first loop nested in `j` takes `j` as a dependency of its bound (`range (after 4 %j)`), and each later sibling loop's bound depends on the earlier sibling's END. Because a RANGE's `ranges` include its bound's, every node inside an inner loop then also depends on the outer loops, and a sort by loop depth places each node (`tinygrad/codegen/late/linearizer.py`).

### Lesson 3: gemms and convs

**The accumulator pattern.** A reduction, such as a sum, needs a value carried from one iteration to the next. With no loop-carried values in the IR, it lives in memory. [examples/sum.uir](examples/sum.uir) sums a buffer:

```text
%x    = buffer 4 slot=0 dtype=i32
%acc  = alloc [] slot=1 dtype=i32
%sx   = store %x [1 2 3 4]
%init = store %acc 0
%i    = range 4 slot=0
%a    = after %acc %init %i
%step = store %a (add (load %a) (load (index (after %x %sx) %i)))
%done = end %step %i
%test = assert (load (after %acc %done)) 10
```

The key line is `%a = after %acc %init %i`: the accumulator, after its initial store, inside loop `i`. Putting `%i` in the AFTER is what puts the load and store inside the loop; without it, `load %acc` would use no loop, and would be hoisted out and read once.

Within one iteration, the read comes before the write because the store's value depends on the load. Successive iterations run in loop order.

**A matrix multiply.** `C[i][j] = Σ_k A[i][k] · B[k][j]` for row-major `n × n` matrices is three loops, with the accumulator pattern on `C[i][j]`. An excerpt of [examples/gemm.uir](examples/gemm.uir):

```text
%init = store (index %C (add (mul %i 2) %j)) 0
%acc  = after %C %init %k
%cij  = index %acc (add (mul %i 2) %j)
%a    = load (index (after %A %sa) (add (mul %i 2) %k))
%b    = load (index (after %B %sb) (add (mul %k 2) %j))
%step = store %cij (add (load %cij) (mul %a %b))
%done = end (end (end %step %k) %j) %i
```

For this excerpt (the stores that fill `A` and `B` are left out; `main` fills them instead), `nest` and `render` produce the function below, indented here for reading:

```c
#include <assert.h>
#include <stdint.h>

void kernel(float *buf0, float *buf1, float *buf2) {
    for (int32_t r0 = 0; r0 < 2; r0++) {
        int32_t v7 = r0 * 2;
        for (int32_t r1 = 0; r1 < 2; r1++) {
            int32_t v9 = v7 + r1;
            buf2[v9] = 0.0f;
            for (int32_t r2 = 0; r2 < 2; r2++) {
                float v15 = buf2[v9];
                int32_t v16 = v7 + r2;
                float v18 = buf0[v16];
                int32_t v19 = r2 * 2;
                int32_t v20 = v19 + r1;
                float v22 = buf1[v20];
                float v23 = v18 * v22;
                float v24 = v15 + v23;
                buf2[v9] = v24;
            }
        }
    }
}

int main(void) {
    float a[4] = {1, 2, 3, 4}, b[4] = {5, 6, 7, 8}, c[4];
    kernel(a, b, c);
    assert(c[0] == 19 && c[1] == 22 && c[2] == 43 && c[3] == 50);
    return 0;
}
```

Notice what placement did by itself: `i*2` is computed once per `i`, `i*2 + j` once per `(i, j)`, and the init runs before the `k` loop. Each node sits in the innermost loop of its `ranges`.

**Loop order is yours to choose.** Loops nest the way their ENDs nest, so the program decides the order. In `i, j, k` order the inner loop reads `B[k][j]` `n` elements apart. In `i, k, j` order it reads `B[k][j]` and writes `C[i][j]` at consecutive addresses, which uses the cache far better; the initial stores then need a loop of their own before `k`, or they would reset `C` on every `k`. The result is identical, because each `C[i][j]` still adds its terms in the same order of `k`. Choosing orders like this automatically is the work of weeks 6–8.

**A convolution** is the same shape of program with different index arithmetic: `y[o] = Σ_k x[o + k] · w[k]` ([examples/conv1d.uir](examples/conv1d.uir)). Bounds keep it honest: with `o` in `[0, 2]` and `k` in `[0, 2]`, `o + k` is in `[0, 4]`, inside `x`. A 2-D convolution adds two more loops and the index `(oy + ky) * W + (ox + kx)`; its reduction to a matrix multiply is a classic ([Chellapilla et al. 2006](#sources)).

**What this does not do yet.** These loops are correct but slow: each `C[i][j]` is loaded and stored on every step of `k`, and nothing is reused from cache on purpose. Week 4 generates such loops from shapes (`REDUCE`), and weeks 6–8 make them fast ([Goto & van de Geijn 2008](#sources)).

## Ops introduced

| Op | Srcs | Arg | Shape | Dtype | Meaning |
|----|------|-----|-------|-------|---------|
| `RANGE` | end (a constant ≥ 1) | `slot` | `()` | `i32` | Loop variable: `0, 1, …, end − 1`; bounds `[0, end − 1]` |
| `END` | effect, range | none | `()` | `void` | Runs the effect once per value of the range |

`AFTER` (week 2) may now also wait for a RANGE: `after %acc %init %i` is `%acc` inside loop `i`. Rules your compiler checks, in addition to weeks 1–2: the loop rules in [Lesson 1](#lesson-1-loops-as-values), and no RANGE used both inside a CALL body and outside it. A CALL whose arguments use a loop runs once per iteration, like any other node.

## Properties introduced

| Property | Type | Rule |
|----------|------|------|
| `ranges` | `dict[UOp, None]` (a set) | `{self}` for `RANGE`; otherwise the union of the sources' `ranges`, minus the loop an `END` closes |
| `ended_ranges` | `dict[UOp, UOp]` | The sources' `ended_ranges` merged; an `END` adds its range, mapped to itself |

> **Interpretation.** tinygrad's `ended_ranges` is a tuple of the ranges a node closes (`tinygrad/uop/ops.py`). The syllabus types it `dict[UOp, UOp]`; this chapter reads that as "each closed loop, mapped to the END that closes it", accumulated over the graph like the other recursive properties, which is what `nest` needs. tinygrad's RANGE also includes its bound's `ranges`, which its ordering rewrite uses; here a RANGE's bound is a constant.

## Assignment

Due Wednesday of week 4, before the 10 AM class. Your ten tests, in UIR, are due the Monday before.

1. **Check** the new rules above.
2. **Compute** `ranges` and `ended_ranges` for every node.
3. **Order** the nodes so that every node is inside the innermost loop of its `ranges` and the loops nest as their ENDs do (Lesson 2).
4. **Render** loops as C `for` loops, compile, run, and check the assert, for every program from weeks 1–3.

Your inliner now gives fresh slots to both ALLOCs and RANGEs. Keep the interpreter for differential tests; the renderer is the compiler. Restrictions this week: memory and values are at most rank 1; ALU ops take rank-0 sources; loop bounds are constants.

## Example programs

All in [examples/](examples/). Each file's comments show the hand calculation. The [oracle](../oracle/README.md) passes all of them.

| File | Exercises |
|------|-----------|
| [fill.uir](examples/fill.uir) | The draft course page's example: one loop |
| [nested.uir](examples/nested.uir) | Two nested loops; bounds of `i*3 + j` |
| [two_stores.uir](examples/two_stores.uir) | Two stores in one loop, grouped with `AFTER` |
| [enclosing_loops.uir](examples/enclosing_loops.uir) | A node that uses only the inner loop still runs for every outer value |
| [sum.uir](examples/sum.uir) | The accumulator pattern in an `ALLOC` |
| [sibling_loops.uir](examples/sibling_loops.uir) | A second loop that reads what the first wrote |
| [gemm.uir](examples/gemm.uir) | A 2×2 matrix multiply |
| [conv1d.uir](examples/conv1d.uir) | A 1-D convolution |

## Spec notes

> **Spec note.** Week 5 says "Now we introduce movement ops and loops", but RANGE and END are introduced here, in week 3. This chapter follows week 3's op list; week 5 is read as introducing movement ops over loops.

> **Spec note.** Week 3 calls this "the first week you will (likely) require a rewrite engine", but week 1 already requires "bottom up greedy rewrite engines". This chapter reads week 3's sentence as the first week the *renderer* may use rewrites, to order the ranges.

> **Interpretation.** The spec writes END's sources as "(passthrough, range)", which suggests END passes a value through. This chapter follows tinygrad, where END's first source is an effect (`void`) and values leave a loop only through memory and `AFTER` (`tinygrad/uop/spec.py`).

> **Interpretation.** "arg is the range name" is written `slot=`, as in the draft course page and tinygrad's UIR (`range 3 slot=0`). tinygrad's RANGE arg also carries an axis type; the syllabus introduces axis types in week 7.

> **Interpretation.** The rules that a loop's end is a constant ≥ 1, that each RANGE is ended once, and that a RANGE cannot be shared between a call body and its caller come from the [oracle](../oracle/README.md#decisions-not-in-uirmd). They keep every loop's trip count known and its placement unambiguous.

## Quiz

1. How many times does a node run if its `ranges` are `{i, j}`, with `i = range 3` and `j = range 4`, and no other loop encloses them?
   <details><summary>Answer</summary>12: once per pair of values.</details>
2. In the gemm, why must the accumulator's initial store not depend on `k`?
   <details><summary>Answer</summary>It would then run inside the <code>k</code> loop and reset <code>C[i][j]</code> on every step.</details>
3. What is wrong with `%step = store %acc (add (load %acc) %x)` inside loop `i` when `%acc` is the ALLOC itself, not `after %acc %init %i`?
   <details><summary>Answer</summary><code>load %acc</code> uses no loop, so it is hoisted out and runs once; it is also not ordered after the init store, so the checker rejects the program.</details>
4. Given `end (end %e %k) %j`, where `%e` uses `j` and `k`, which loop is inside which? A store `%s` inside `%e` uses only `k`; with `j = range 2` and `k = range 3`, how often does `%s` run?
   <details><summary>Answer</summary><code>k</code> is inside <code>j</code>, because <code>j</code> is open where <code>k</code> ends. <code>%s</code> runs 6 times: once per value of <code>k</code> and of the loop <code>j</code> that encloses it.</details>
5. With `o = range 3` and `k = range 3`, is `index %x (add %o %k)` valid on a buffer of 5? Of 4?
   <details><summary>Answer</summary>The index is in <code>[0, 4]</code>: valid for 5 elements, rejected for 4.</details>

## Sources

1. Goto & van de Geijn, "Anatomy of High-Performance Matrix Multiplication", ACM TOMS 2008. https://doi.org/10.1145/1356052.1356053 — why the naive triple loop is slow, and what fast ones do.
2. Chellapilla, Puri, Simard, "High Performance Convolutional Neural Networks for Document Processing", IWFHR 2006. https://inria.hal.science/inria-00112631 — convolution as matrix multiply.
3. Ragan-Kelley et al., "Halide", PLDI 2013. https://doi.org/10.1145/2491956.2462176 — where each computation runs inside a loop nest, as a first-class choice.
4. tinygrad, commit 07821cae. https://github.com/tinygrad/tinygrad — `tinygrad/uop/ops.py` (`ranges`, `ended_ranges`), `tinygrad/codegen/late/linearizer.py` (ordering ranges), `tinygrad/uop/spec.py` (RANGE and END rules).
