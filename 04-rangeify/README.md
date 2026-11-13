# Chapter 4: Rangeify + Kernel Fusion/Fission

> **`broadcasting` · `reduction` · `rangeify`**
>
> We still keep the rank < 2 restriction on shapes, but ALU can be rank 1 now.
>
> Ops introduced:
> ```
> REDUCE (axis count / op)
> STAGE -- temp buffer
> EXPAND
> ```
>
> Rangeify removes shapes from all ops. We have to confront questions about materialization here.
>
> — the syllabus, week 4

**Builds on:** [Chapter 3](../03-loops/README.md). **By the end you can:** compile programs written on whole vectors (elementwise arithmetic, broadcasting with `EXPAND`, sums and maxima with `REDUCE`) by lowering them to chapter 3's loops, and decide which intermediate values to keep in memory.

## Contents

- [What you build](#what-you-build)
- [How to start](#how-to-start)
- [Lectures](#lectures)
  - [Lesson 1: broadcasting and reduction](#lesson-1-broadcasting-and-reduction)
  - [Lesson 2: rangeify](#lesson-2-rangeify)
  - [Lesson 3: kernel fusion and fission](#lesson-3-kernel-fusion-and-fission)
- [Ops introduced](#ops-introduced)
- [Assignment](#assignment)
- [Example programs](#example-programs)
- [Spec notes](#spec-notes)
- [Quiz](#quiz)
- [Sources](#sources)

## What you build

In chapter 3 you wrote every loop by hand: a `RANGE`, index arithmetic, an accumulator in an `ALLOC`, an `END`. That is how C works, but not how anyone writes a model. In this chapter, programs say *what* to compute on whole vectors, and your compiler writes the loops.

Here is the draft course page's week 4 example, [expand_add.uir](examples/expand_add.uir):

```text
%values = add [1 2 3] (expand 1 3)
%sum    = reduce %values op=add pop=1
%test   = assert %sum 9
```

`expand 1 3` is the vector `[1 1 1]`, so `%values` is `[2 3 4]`, an `ADD` on rank-1 values: chapter 1 did not allow that. `reduce … op=add pop=1` adds up the elements: 9. There is no loop in the program. Your compiler lowers it to this chapter 3 program:

```text
%r    = range 3 slot=0
%x    = add (index [1 2 3] %r) 1
%acc  = alloc [] slot=0 dtype=i32
%init = store %acc 0
%a    = after %acc %init %r
%step = store %a (add (load %a) %x)
%done = end %step %r
%test = assert (load (after %acc %done)) 9
```

This is chapter 3's [sum.uir](../03-loops/examples/sum.uir) pattern, written by the compiler instead of by you. `%x` is element `r` of `%values`: the `ADD` moved into the loop as a rank-0 add, and the `EXPAND` vanished, because element `r` of `expand 1 3` is just `1`. Chapter 3's `nest` and `render` then print it as C (variable names will differ):

```c
#include <stdint.h>

int kernel(void) {
    int32_t values[3] = {1, 2, 3};
    int32_t acc[1];
    acc[0] = 0;
    for (int32_t r0 = 0; r0 < 3; r0++) {
        int32_t x = values[r0] + 1;
        int32_t a = acc[0];
        acc[0] = a + x;
    }
    int32_t sum = acc[0];
    return sum == 9;
}
```

The lowering is called *rangeify*: it gives every value a `RANGE` for its axis, and so "removes shapes from all ops" (the syllabus). The pipeline gains one stage, between inlining and chapter 3's ordering:

```text
                                      shapes          loops (chapter 3 UIR)
 .uir ─▶ parse, check ─▶ inline ─▶ rangeify ─▶ nest ─▶ render ─▶ cc ─▶ run ─▶ verdict
                                       │
                                       └─▶ --emit-uir: print it, and check it with the oracle
```

The interpreter path from chapter 2 stays as it is, extended to the new ops, and both paths must still agree.

**Why this matters later.** From here on, programs are written with shapes. The syllabus's own gemm is `reduce (mul (reshape %0 …) (reshape %1 …)) op=add pop=1`, with no loops in sight; chapter 5 adds the `RESHAPE` it needs. Every model you compile goes through rangeify.

Rangeify is also where your compiler makes its first performance decision on its own: which intermediate values to keep in memory (*materialize*) and which to recompute inside the loop that needs them (*fuse*). [Chapter 0, Lesson 6](../00-prerequisites/README.md#lesson-6-hardware-and-performance) showed why this matters: fusion raises arithmetic intensity, and memory bandwidth is usually the limit. Two examples from this chapter show both outcomes:

| Program | Compiles to |
|---------|-------------|
| [scale.uir](examples/scale.uir): `store %y (add (mul %xv (expand 0.5 4)) (expand 1 4))` | one loop, `y[r] = x[r] * 0.5 + 1`: everything fused |
| [stage_reuse.uir](examples/stage_reuse.uir): the squares `x*x` used by a sum and by the output | a loop filling a temp buffer `sq[3]`, a loop summing it, a loop building the output |

Lesson 3 is about this decision. And the new checks reject what has no meaning:

```text
$ mycc bad.uir          # %v = add [1 2 3] 1
ERROR line 1: add of shapes (3,) and (): broadcast with expand
```

## How to start

You have a chapter 3 compiler: it checks loops, orders them with `nest`, renders C, and agrees with the oracle on every chapter 1–3 example. Grow it into a chapter 4 compiler in this order, checking each step. Run every command from the repo root.

**Step 0: the interpreter.** Teach `--interpret` the new semantics first, because it is the reference for everything after:

- ALU ops on rank-1 values, element by element.
- `EXPAND`, `REDUCE` and `STAGE` (Lesson 1).
- The new checks ([Ops introduced](#ops-introduced)).

First copy the oracle's tests for the new rules into `tests/chapter4/`, as your first tests: the [invalid](../oracle/tests/invalid/) ones give ERROR, the [valid](../oracle/tests/valid/) ones PASS.

```sh
mkdir -p tests/chapter4
cp oracle/tests/invalid/{alu_shapes,expand_rank2,expand_rank1_source,reduce_pop,reduce_op,reduce_bool,expand_memory,stage_effect,stage_index_bounds,expand_index_oob}.uir tests/chapter4/
cp oracle/tests/valid/{expand_rank0,expand_f32_literal,reduce_pop0,reduce_wraps,reduce_max_f32,reduce_in_call,rank1_where,load_before_overwrite,index_operand}.uir tests/chapter4/
```

Done when this matches everywhere:

```sh
python3 -I tools/check_compiler.py --chapter 4 -- python3 compiler/mycc.py --interpret
```

Until rangeify handles a program, the default (compiled) mode fails on it: that is expected. Chapters 1–3 must keep passing in both modes; the chapter 4 examples start passing compiled one by one in steps 2–6. Commit after each step.

**Step 1: `--emit-uir`.** Add a mode that prints the graph your compiler is about to render, as UIR. Print one line per node in topological order, each node named after its position: `%n7 = add %n5 %n6`. Before rangeify exists, print the inlined graph.

The point is that the oracle reads this output. A lowered program is a chapter 3 program, so the oracle can check the lowering itself, not just the final verdict. Its `--lowered` flag also rejects anything rangeify should have removed (a REDUCE, EXPAND or STAGE, or an ALU op on a rank-1 value), because an unlowered program is valid UIR too:

```sh
mkdir -p kernels
for f in 0[1-4]-*/examples/*.uir tests/*/*.uir; do
  python3 compiler/mycc.py --emit-uir "$f" > kernels/lowered.uir
  echo "$(python3 -I oracle/uir.py "$f" | cut -d' ' -f1) $(python3 -I oracle/uir.py --lowered kernels/lowered.uir | cut -d' ' -f1) $f"
done
```

Each line looks like `PASS PASS 01-uops-and-rewrites/examples/add.uir`, and the two words must be the same. (`kernels/` is the runtime's cache folder, which git ignores.) For a program your compiler rejects, `--emit-uir` prints its ERROR line, the oracle cannot parse that, and the line reads `ERROR ERROR`: only the lines of valid programs say something about the lowering. Done when the words match for chapters 1–3; the chapter 4 examples say `PASS ERROR` until rangeify handles them.

Two details trip people up when printing UIR:

- A literal on its own line takes its dtype from how it is written ([Literals inside EXPAND](#lesson-1-broadcasting-and-reduction) has the rule): print an `f32` constant with a decimal point (`%n3 = 1.0`), or it reads back as `i32`. The same goes for an `f32` stack used as a value: `[1.0 2.0]`, not `[1 2]`.
- A rank-0 shape prints as `[]`, and an `i32` constant as a plain number.

**Step 2: the thinnest slice.** Make [scale.uir](examples/scale.uir) compile: a rank-1 expression stored into a buffer. It needs only the elementwise part of rangeify, `elem` in [Lesson 2](#lesson-2-rangeify), and the rule that turns a rank-1 `STORE` into a loop. Done when its line in the loop above reads `PASS PASS`, and the compiled program passes.

**Steps 3–6: grow it.**

| Step | Add | Read | Done when |
|------|-----|------|-----------|
| 3 | `REDUCE` lowered to an accumulator loop, with its init inside the loops its source uses | Lesson 2 | [expand_add](examples/expand_add.uir), [dot](examples/dot.uir), [max_reduce](examples/max_reduce.uir), [center](examples/center.uir) and [row_sums](examples/row_sums.uir) pass compiled, and read `PASS PASS` in the loop |
| 4 | `STAGE` and rank-1 asserts: compute the value into a temp `ALLOC` in a loop of its own | Lesson 3 | [stage_reuse](examples/stage_reuse.uir) passes both ways |
| 5 | Materialize a rank-1 LOAD that a later store to its buffer depends on (the hazard) | Lesson 3 | [shift](examples/shift.uir) and the oracle's [load_before_overwrite](../oracle/tests/valid/load_before_overwrite.uir) (the cross-loop listing in Lesson 3) pass compiled and read `PASS PASS` in the loop; before this step, the oracle on shift's lowered UIR reports `got [1 1 1 1]` |
| 6 | The automatic materialization rule | Lesson 3 | With the `stage` removed from a copy of stage_reuse, `--emit-c` shows one multiply loop and a temp buffer; for [the chain test](#lesson-3-kernel-fusion-and-fission) in Lesson 3 (save it in `tests/chapter4/`), exactly one STAGE temp buffer besides the accumulator and the assert's buffer; [index_operand](../oracle/tests/valid/index_operand.uir) reads `PASS PASS` (its `%v` feeds indices, so it is not staged) |

The chapter is done when `check_compiler.py --chapter 4` matches the oracle in both modes, and the loop of step 1 prints matching words for every example and every test under `tests/`.

**Habits that pay off.**

- **Read the lowered UIR before the C.** Most rangeify bugs are visible there: a node in the wrong loop, a missing `AFTER`, an init that does not depend on the loop it should run in. The oracle points at the line.
- **Shrink failures to one op.** A failing program that mixes `REDUCE` and `EXPAND` is two bugs or one; write the three-line program that has only one of them.
- **Keep a test for every lowering rule.** `expand_add` alone does not catch an accumulator init in the wrong loop; `row_sums` does.

## Lectures

The syllabus lists no lectures for week 4. The three lessons follow the week's topics: broadcasting and reduction, then rangeify, then the "Kernel Fusion/Fission" of its title.

### Lesson 1: broadcasting and reduction

**Values get a shape.** Since chapter 1, a value could be rank 1 (a stack `[1 2 3]`, a rank-1 `PARAM`, a whole-buffer `LOAD`), but no ALU op could touch it: you could only index it, store it, or assert it. Week 4 lifts that: "ALU can be rank 1 now". An ALU op on rank-1 values works element by element:

| Expression | Shape | Value |
|------------|-------|-------|
| `add [1 2 3] [10 20 30]` | `(3,)` | `[11 22 33]` |
| `cmplt [1 5] [3 3]` | `(2,)` | `[true false]` |
| `cast [1 2] dtype=f32` | `(2,)` | `[1.0 2.0]` |
| `add [1 2 3] [1 2]` | | ERROR: shapes `(3,)` and `(2,)` |
| `add [1 2 3] 1` | | ERROR: shapes `(3,)` and `()` |

The rule: every source of an ALU op has the same shape, and that is the result's shape. Shapes are still at most rank 1 ("We still keep the rank < 2 restriction"), and indices (`INDEX`, a `SHRINK` offset) are still rank 0.

**Broadcasting is explicit.** The last row is the surprise. NumPy would accept `[1 2 3] + 1` and stretch the `1` to `[1 1 1]`: it aligns shapes from the right and stretches missing axes and axes of size 1 ([NumPy](#sources)). This course makes that step an op of its own, `EXPAND`:

```text
%x    = [1 5 2 0]
%c    = expand 2 4        # [2 2 2 2]
%test = assert (where (cmplt %x %c) %c %x) [2 5 2 2]
```

`expand x n` has shape `(n,)` and every element is `x`. It adds a *leading* axis, like `STACK` does, and it is the shape inverse of `REDUCE`, which removes leading axes. Writing the broadcast as a node means every place where one value is reused across a whole axis is visible in the graph, which Lesson 2 relies on.

> **Interpretation.** The syllabus lists `EXPAND` without arguments. This course follows tinygrad, where EXPAND's new axes go on the left (`tinygrad/uop/ops.py`, `_shape`), and writes its shape like a BUFFER's, `[]` or a length, as the draft course page writes `expand 1 3`. ALU ops do not broadcast implicitly; that is left to week 6's "syntactic sugar". With rank ≤ 1, `expand x n` needs a rank-0 `x`; `expand x []` adds no axis and is `x` itself.

**Literals inside EXPAND.** A literal takes the dtype of the value it must match ([uir.md](../uir.md#literals)), and so does an `expand` of a literal written inline: in `add %f (expand 1 4)`, with `%f` an `f32` vector, the `1` is `1.0`. On its own line, `%one = expand 1 4` is typed where it stands, as `i32`, and adding it to `%f` is an error. Write `expand 1.0 4` there.

**REDUCE combines an axis.** `reduce x op=add pop=1` adds up the elements of `x`; `op=mul` multiplies them, and `op=max` takes the largest. "Axis count / op" is the syllabus's description of its two arguments: `pop` is how many leading axes to remove, and `op` is how to combine them. With rank ≤ 1, `pop` is 1 (a vector becomes one value) or 0 (nothing is removed, and the value is unchanged).

The result is defined as a loop: start from the op's *identity*, the value that changes nothing (`0 + x = x`, `1 × x = x`, `max(-inf, x) = x`), and combine the elements in index order.

| `op` | Identity | `reduce [3 -1 7] …` |
|------|----------|---------------------|
| `add` | `0` | `((0 + 3) + -1) + 7 = 9` |
| `mul` | `1` | `((1 × 3) × -1) × 7 = -21` |
| `max` | the smallest value: `-2147483648` for `i32`, `-inf` for `f32` | `7` |

Starting from the identity, rather than from element 0, is what the lowered loop does (the accumulator is initialized before the loop), so the interpreter and the C agree by construction. A max that starts from 0 instead gets `max_reduce.uir` wrong: every input there is negative.

The order matters for `f32`, where addition is not associative ([Goldberg 1991](#sources)):

> **Predict.** `reduce [16777216.0 1.0 1.0] op=add pop=1` in `f32`. What is the result? And for `[1.0 1.0 16777216.0]`?
> <details><summary>Answer</summary>16777216 for the first: <code>16777216 + 1</code> is not representable in <code>f32</code> and rounds back to 16777216 (ties to even), twice. 16777218 for the second: <code>1 + 1 = 2</code> first, and <code>16777216 + 2</code> is exact. The same three numbers give two different sums. That is why the fold order is part of the definition, and why your C must not reorder it.</details>

> **Interpretation.** tinygrad's REDUCE takes `(op, axis count)`, removes the leading axes (`tinygrad/uop/ops.py`, `_shape`), and has the ops ADD, MUL and MAX (`GroupOp.Reduce`). The fold from the identity in index order is how tinygrad lowers it (`lower_reduce` in `tinygrad/codegen/__init__.py`, with `identity_element` in `tinygrad/uop/ops.py`).

**STAGE changes no value.** `stage x` has the same value, shape and dtype as `x`. The one visible difference is its bounds: the dtype's full range, because compiled, it is read back from memory, so `index %v (stage %i)` can fail the bounds check. In the compiled code it changes everything about how `x` is computed: it is the syllabus's "temp buffer". Lesson 3 explains it.

**Interpreting the new ops.** The interpreter needs three new cases and one change: an ALU op whose sources are lists works element by element, with chapter 1's folding for each element.

```python
import math

IDENTITY = {"ADD": 0, "MUL": 1, "MAX": -math.inf}  # an i32 MAX starts at -2**31 instead


def evaluate(u: UOp, vals: list, scalar) -> object:
    """u's value from its sources' values: a number, or a list for rank 1.
    scalar(op, *args) is chapter 1's constant folding for one element."""
    if u.op == "EXPAND":                        # arg: the new axis's length
        return [vals[0]] * u.arg
    if u.op == "REDUCE":                        # arg: the op; pop=1 here
        acc = IDENTITY[u.arg]
        for v in vals[0]:                       # in index order: f32 sums depend on it
            acc = scalar(u.arg, acc, v)
        return acc
    if u.op == "STAGE":
        return vals[0]
    if isinstance(vals[0], list):               # rank 1: one op per element
        return [scalar(u.op, *elems) for elems in zip(*vals)]
    return scalar(u.op, *vals)
```

(A sketch: here an EXPAND's arg is its length and a REDUCE's arg is its op, where yours also carry a shape and `pop`. `scalar` must wrap `i32` and round `f32` exactly as before.)

Here is [center.uir](examples/center.uir), which subtracts the mean, evaluated node by node:

```text
%x    = buffer 4 slot=0 dtype=i32
%y    = buffer 4 slot=1 dtype=i32
%sx   = store %x [2 4 6 8]
%xv   = load (after %x %sx)
%mean = div (reduce %xv op=add pop=1) 4
%sy   = store %y (add %xv (expand (mul %mean -1) 4))
%test = assert (after %y %sy) [-3 -1 1 3]
```

| Node | Shape | Value |
|------|-------|-------|
| `%xv` | `(4,)` | `[2 4 6 8]` |
| `reduce %xv op=add pop=1` | `()` | `0 + 2 + 4 + 6 + 8 = 20` |
| `%mean` | `()` | `20 div 4 = 5` |
| `mul %mean -1` | `()` | `-5` |
| `expand … 4` | `(4,)` | `[-5 -5 -5 -5]` |
| `add %xv …` | `(4,)` | `[-3 -1 1 3]` |

Notice the shape going down to `()` at the REDUCE and back up to `(4,)` at the EXPAND. That round trip, a reduction broadcast back over the axis it came from, is the shape of softmax, layer norm and mean-centering, and Lesson 2 shows what it does to the loops.

> **Predict.** Is `reduce (cmplt [1 2] [2 2]) op=max pop=1` valid? And `reduce %buf op=add pop=1`, with `%buf` a BUFFER?
> <details><summary>Answer</summary>Both are ERRORs. The first reduces <code>bool</code>s, and <code>max</code> takes only <code>i32</code> and <code>f32</code>, like the ALU op. The second reduces memory: a REDUCE's source is a value, so write <code>reduce (load %buf) …</code>, after the stores it should see.</details>

**Common mistakes.**

- Writing `add %v 1` for a vector `%v`. Write `add %v (expand 1 n)`; the shapes must match.
- Starting a `max` from 0, or from the first element in the interpreter but from the identity in C. Both start from the identity.
- Folding an `f32` sum in any order but index order, for example pairwise "for accuracy". It changes the result.
- `%one = expand 1 4` added to an `f32` vector: it is `i32`. Write `1.0`, or write the expand inline.
- Making `STAGE` change the value in the interpreter: it returns its source unchanged.

### Lesson 2: rangeify

**The problem.** Chapter 3's renderer understands loops and rank-0 values: every value is one C variable, computed inside the loops it uses. It does not understand `add [1 2 3] (expand 1 3)`: C has no "add two vectors". Rangeify bridges that gap. After it, every computed value is rank 0 and every loop is an explicit RANGE and END. Only memory and constant stacks keep a shape, and you index them ([an interpretation](#spec-notes)). A rank-1 ASSERT compares a buffer with a stack (Lesson 3).

**The idea: ask for one element.** Instead of computing a whole vector, ask each node for *one element*, element `i`, where `i` is a RANGE (or any rank-0 index). Call the answer `elem(u, i)`: a rank-0 UOp that computes element `i` of `u`. For most ops the rule is one line: element `i` of `add a b` is `add (elem a i) (elem b i)`; element `i` of `expand x n` is `x`, whatever `i` is; element `i` of a rank-1 `load m` is `load (index m i)`, a read of one element. REDUCE and STAGE make new loops, below.

```python
import functools


@functools.cache
def elem(u: UOp, i: UOp | None) -> UOp:
    """The rank-0 UOp that computes element i of u; i is None when u is rank 0."""
    if u.op in ("CONST", "RANGE"):
        return u                                      # already rank 0
    if u.op == "STACK":                               # element i of a constant vector
        return u if i is None else UOp("INDEX", (u, i))
    if u.op == "EXPAND":
        return elem(u.src[0], None)                   # every element is the source
    if u.op == "INDEX":
        return elem(u.src[0], elem(u.src[1], None))   # element j of a rank-1 value
    if u.op == "LOAD":                                # a rank-1 load reads one element
        return u if i is None else UOp("LOAD", (UOp("INDEX", (u.src[0], i)),))
    return UOp(u.op, tuple(elem(s, i) for s in u.src), u.arg)  # ALU: element by element
```

(A sketch: REDUCE, STAGE and the stores an `AFTER` waits for are yours to add, below, and yours lowers the LOAD's address first. The cache lives as long as the process: call `elem.cache_clear()` before lowering the next program.)

**Where the loops come from.** `elem` needs an `i`, and only a few nodes make one. They are the nodes that need a *whole* rank-1 value:

- **A rank-1 `STORE`** writes every element of its target: a new RANGE `r` over the target's length, and `end (store (index target r) (elem value r)) r`.
- **A `REDUCE`** combines every element of its source: a new RANGE over the source's axis, and an accumulator.
- **A rank-1 `ASSERT`**, and a `STAGE`, keep every element in memory: a new RANGE and a temp buffer ([Lesson 3](#lesson-3-kernel-fusion-and-fission)).

Everything else is computed inside the loop of whichever node asks for it. Give each new RANGE a fresh slot, one past the highest RANGE slot in the program, as you already do for inlined loops, and each new ALLOC (accumulators, temp buffers) one past the highest BUFFER or ALLOC slot.

**A worked lowering.** Take [scale.uir](examples/scale.uir), `y = x * 0.5 + 1`:

```text
%x    = buffer 4 slot=0 dtype=f32
%y    = buffer 4 slot=1 dtype=f32
%sx   = store %x [1 2 3 4]
%v    = add (mul (load (after %x %sx)) (expand 0.5 4)) (expand 1 4)
%sy   = store %y %v
%test = assert (after %y %sy) [1.5 2 2.5 3]
```

The root asserts on memory, `after %y %sy`, so rangeify starts from the effect `%sy`, a rank-1 store. It makes `%r = range 4 slot=0` and asks for `elem(%v, %r)`:

```text
elem(%v, %r)                                      → add A B                           (ALU)
  A: elem(mul (load …) (expand 0.5 4), %r)        → mul C 0.5                         (ALU)
    C: elem(load (after %x %sx), %r)              → load (index (after %x %sx) %r)    (rank-1 load)
       elem(expand 0.5 4, %r)                     → 0.5                               (expand)
  B: elem(expand 1 4, %r)                         → 1.0                               (expand; f32)
```

Each call is indented under the call that made it; `A`, `B` and `C` name results used one level up.

The lowered program:

```text
%x    = buffer 4 slot=0 dtype=f32
%y    = buffer 4 slot=1 dtype=f32
%sx   = store %x [1 2 3 4]
%r    = range 4 slot=0
%xr   = load (index (after %x %sx) %r)
%vr   = add (mul %xr 0.5) 1.0
%sy   = end (store (index %y %r) %vr) %r
%test = assert (after %y %sy) [1.5 2 2.5 3]
```

Every computed value in it is rank 0. The input store `%sx` is a rank-1 store too, and your compiler lowers it the same way, into a second loop; it is left as written here to keep the listing short (chapter 2 allows it). The two `EXPAND`s disappeared: a broadcast costs nothing once you ask for one element, because "every element is `x`" means "use `x`".

> **Predict.** In `%v`, the load of `x` was moved inside the loop over `y`. Is that always safe?
> <details><summary>Answer</summary>No. It is safe here because <code>x</code> and <code>y</code> are different buffers. If the store wrote into the buffer the value reads, element <code>r</code> could read something the loop already overwrote. Lesson 3 has the example and the fix.</details>

**Lowering a REDUCE.** A `REDUCE` is chapter 3's accumulator, generated:

1. A new RANGE `r` over the source's axis, and `v = elem(x, r)`.
2. A new `alloc [] … dtype=<the reduce's dtype>`: the accumulator.
3. `init = store acc <identity>`.
4. `a = after acc init r`, then `step = store a (op (load a) v)`: inside the loop, after the init.
5. The result: `load (after acc (end step r))`, a rank-0 value outside loop `r`, because the END closes it.

The [What you build](#what-you-build) listing is exactly these five steps for `expand_add.uir`. One detail is easy to miss. The init must run once per *outer* iteration, not once overall. [row_sums.uir](examples/row_sums.uir) sums each row of a 2×3 matrix, with a chapter 3 loop over the rows and a REDUCE over each row's window:

```text
%m    = buffer 6 slot=0 dtype=i32
%out  = buffer 2 slot=1 dtype=i32
%sm   = store %m [1 2 3 4 5 6]
%i    = range 2 slot=0
%row  = load (shrink (after %m %sm) (mul %i 3) 3)
%s    = store (index %out %i) (reduce %row op=add pop=1)
%done = end %s %i
%test = assert (after %out %done) [6 15]
```

Its source, `elem(%row, %k)`, uses the row loop `%i` as well as the new loop `%k`. So the init must also depend on `%i`, through `after %acc %i`, or the [evaluation rule](../uir.md#evaluation) runs it once, before the row loop:

```text
%m    = buffer 6 slot=0 dtype=i32
%out  = buffer 2 slot=1 dtype=i32
%sm   = store %m [1 2 3 4 5 6]
%i    = range 2 slot=0
%k    = range 3 slot=1
%x    = load (index (shrink (after %m %sm) (mul %i 3) 3) %k)
%acc  = alloc [] slot=2 dtype=i32
%init = store (after %acc %i) 0
%a    = after %acc %init %k
%step = store %a (add (load %a) %x)
%sum  = load (after %acc (end %step %k))
%s    = store (index %out %i) %sum
%done = end %s %i
%test = assert (after %out %done) [6 15]
```

The rule: the init waits for every RANGE that `elem(x, r)` uses, except `r` itself. tinygrad's `lower_reduce` does the same (`acc.after(*input_ranges)`). Chapter 3's `nest` then places the init inside loop `i` and before loop `k`, like the gemm's init in [chapter 3](../03-loops/README.md#lesson-3-gemms-and-convs).

> **Predict.** Write `%init = store %acc 0` instead. What does the program compute?
> <details><summary>Answer</summary><code>[6 21]</code>, a FAIL. The init depends on no loop, so it runs once, before everything. Row 0 sums to 6, and row 1 starts from 6 instead of 0: <code>6 + 4 + 5 + 6 = 21</code>.</details>

**A reduce feeding a broadcast.** In [center.uir](examples/center.uir), the sum's result is used inside the loop over `y`. Lowered and rendered, it becomes three loops (names will differ):

```c
#include <stdint.h>

static int32_t idiv(int32_t a, int32_t b) {  // floor division, from chapter 2
    int32_t q = a / b;
    return (a % b != 0 && (a < 0) != (b < 0)) ? q - 1 : q;
}

int kernel(int32_t *buf0, int32_t *buf1) {
    int32_t input[4] = {2, 4, 6, 8};
    for (int32_t r1 = 0; r1 < 4; r1++) {         // store %x [2 4 6 8]
        buf0[r1] = input[r1];
    }
    int32_t acc[1];
    acc[0] = 0;
    for (int32_t r2 = 0; r2 < 4; r2++) {         // reduce %xv op=add pop=1
        int32_t a = acc[0];
        int32_t x = buf0[r2];
        acc[0] = a + x;
    }
    int32_t sum = acc[0];
    int32_t mean = idiv(sum, 4);
    int32_t neg = mean * -1;
    for (int32_t r0 = 0; r0 < 4; r0++) {         // store %y (add %xv (expand ...))
        int32_t x = buf0[r0];
        buf1[r0] = x + neg;
    }
    return buf1[0] == -3 && buf1[1] == -1 && buf1[2] == 1 && buf1[3] == 3;
}
```

Nobody decided that the sum gets a loop of its own before the output loop. `elem(expand (mul %mean -1) 4, r0)` asks for `%mean` with no index, so the lowered sum depends on no output loop, and the evaluation rule computes it once, before the loop that uses it. `nest` places it there. The `%xv` load appears in two loops, at two indices: re-reading memory is cheap. Lesson 3 is about values that are expensive to recompute, and reads that must not move.

**Effects and memory.** A few more cases complete rangeify:

- An address (a `BUFFER`, `INDEX`, `SHRINK` or `AFTER` of memory) keeps its shape, but the effects an `AFTER` waits for are lowered. In scale.uir, with a new RANGE `%q`:

  ```text
  after %x %sx                                                          # %sx = store %x [1 2 3 4]
  after %x (end (store (index %x %q) (index [1.0 2.0 3.0 4.0] %q)) %q)  # lowered
  ```

  An index or SHRINK offset is lowered with `elem(…, None)`.
- `END`, a rank-0 `STORE`, and an `AFTER` whose first source is an effect keep their form, with their sources lowered: `end %e %i` becomes `end <lowered %e> %i`.
- A chapter 3 RANGE is rank 0 and stays itself.
- `reduce x pop=0` changes nothing: `elem(reduce x pop=0, i)` is `elem(x, i)`.
- An `AFTER` whose first source is a value (a value used only after some effects, as chapter 2 allows): `elem(after v e…, i)` is `after (elem v i) <lowered e…>`.
- `CALL`s are already inlined: rangeify runs after the inliner.

> **Interpretation.** The syllabus does not say how rangeify works. tinygrad walks the graph from the root towards the leaves, giving each node one RANGE per axis, which its consumers pass to it (`run_rangeify` in `tinygrad/schedule/indexing.py`). Elementwise ops pass ranges through, `EXPAND` drops the ones for its new axes, `REDUCE` makes new ones for the axes it removes, and a materialized node gets new ones (its `STAGE` becomes a buffer, a store and an END in `tinygrad/schedule/rangeify.py`, `bufferize_to_store`). `elem` is the same walk written as a recursive function, which is shorter for rank ≤ 1. tinygrad lowers REDUCE in a later pass than rangeify; this chapter does it in one step, because the result is chapter 3 UIR either way.

**Checking a lowering.** Every program rangeify produces is chapter 3 UIR, so the oracle checks it ([How to start](#how-to-start) step 1): differential testing again, one level below chapter 2's.

**Common mistakes.**

- An accumulator init that ignores the outer loops (the Predict above).
- Reusing one RANGE for two loops: two REDUCEs over the same vector need two RANGEs (chapter 3: each RANGE is ended once).
- Forgetting `functools.cache` (or a memo table). Hash-consing keeps ALU nodes shared anyway, but a REDUCE or STAGE lowered twice gets two fresh loops and is computed twice, and lowering a graph with a lot of sharing takes exponential time.
- Lowering a REDUCE's source with the consumer's index. The source needs the REDUCE's *own* new range; the consumer's index does not reach past a REDUCE.
- A new RANGE whose slot collides with one in the program.

### Lesson 3: kernel fusion and fission

**Kernels, fusion and fission.** A *kernel* is one loop nest that runs as a unit. On a GPU, from chapter 7, each kernel is a separate function launched on its own, and a value passes from one kernel to the next only through memory. Two words describe how a compiler draws kernel boundaries:

- **Fusion** merges producer and consumer into one kernel: the producer is computed inside the consumer's loop.
- **Fission** (also called *loop distribution*) splits a computation into separate kernels at a materialized buffer: one fills it, the next reads it.

**Fusion is the default.** Lesson 2 computes each value inside the loop of whoever asks for it. In `scale.uir`, `x * 0.5 + 1` is computed in the store's loop, and no temporary vector exists. That is *loop fusion*: two loops that would each walk the vector (one for the multiply, one for the add) merged into one, so the intermediate value stays in a register ([Kennedy & McKinley 1993](#sources)). [Chapter 0, Lesson 6](../00-prerequisites/README.md#lesson-6-hardware-and-performance) worked out why it pays off: an elementwise `f32` add does one operation per 12 bytes moved. Fusing a chain of them keeps every intermediate value out of memory: only the inputs are read and the final result written.

Fusion is not always right. In three situations a value must, or should, be *materialized*: computed into memory in a loop of its own, then read back.

**1. The program asks for it: STAGE and rank-1 asserts.** `stage x` is the syllabus's "temp buffer". It lowers to a new ALLOC with `x`'s shape, a loop that fills it, and loads after that loop:

```text
%t    = alloc n slot=… dtype=…
%q    = range n slot=…
%fill = end (store (index %t %q) <elem(x, %q)>) %q
# elem(stage x, i) is then: load (index (after %t %fill) i)
```

A rank-0 STAGE stores once, with no loop.

A rank-1 ASSERT needs the same treatment, because it compares every element: materialize its actual value into a temp buffer and assert on the buffer, as chapter 2's `assert (after %buf %done) [...]` does. When the actual value is already memory, as in `scale.uir`, there is nothing to do. A computed rank-1 expected value (rare: it is usually a constant stack) is materialized the same way.

**2. Two loops need the same value.** In [stage_reuse.uir](examples/stage_reuse.uir), the squares are used by the sum and by the output:

```text
%x     = buffer 3 slot=0 dtype=i32
%sx    = store %x [1 2 3]
%xv    = load (after %x %sx)
%sq    = stage (mul %xv %xv)
%total = reduce %sq op=add pop=1
%test  = assert (add %sq (expand %total 3)) [15 18 23]
```

The sum asks for `elem(%sq, k)` with its own loop `k`; the output asks for `elem(%sq, r)` with the assert's loop `r`. Without the `stage`, `mul %xv %xv` would be computed twice, once in each loop. With it, the compiled C computes each square once (names will differ):

```c
#include <stdint.h>

int kernel(int32_t *buf0) {
    int32_t input[3] = {1, 2, 3};
    for (int32_t r2 = 0; r2 < 3; r2++) {         // store %x [1 2 3]
        buf0[r2] = input[r2];
    }
    int32_t sq[3];                               // the STAGE's temp buffer
    for (int32_t r1 = 0; r1 < 3; r1++) {
        int32_t x = buf0[r1];
        sq[r1] = x * x;
    }
    int32_t acc[1];
    acc[0] = 0;
    for (int32_t r3 = 0; r3 < 3; r3++) {         // reduce %sq
        int32_t a = acc[0];
        int32_t s = sq[r3];
        acc[0] = a + s;
    }
    int32_t total = acc[0];
    int32_t out[3];                              // the rank-1 assert's value
    for (int32_t r0 = 0; r0 < 3; r0++) {
        int32_t s = sq[r0];
        out[r0] = s + total;
    }
    return out[0] == 15 && out[1] == 18 && out[2] == 23;
}
```

Here the program asked, with `stage`. The course's rule below makes the compiler do the same without being asked. Which version is faster? Count the work for `n` elements:

| | Multiplies | Temp memory traffic |
|---|------------|---------------------|
| Fused (no `stage`) | `2n` | none |
| Materialized (`stage`) | `n` | `n` stores and `2n` loads of `sq` |

For a multiply, recomputing is usually cheaper than the memory traffic: a multiply costs a cycle, while a store and two loads cost at least three memory operations, and far more once `sq` no longer fits in cache. For an expensive value, such as a REDUCE, a long chain of ops, or an `exp2` built from a Taylor series in chapter 5, materializing wins.

This trade-off between locality, recomputation and parallelism is what Halide's schedules expose ([Ragan-Kelley et al. 2013](#sources)), and finding the best fusion for locality is NP-hard in general ([Kennedy & McKinley 1993](#sources)). So compilers use rules.

**The course's rule.** Materialize a node when consumers ask for it at two or more different indices, unless re-reading it is free: a `LOAD`, `CONST`, `STACK`, `RANGE` or `STAGE` can be asked for again at no extra cost (a STAGE is a load from its temp buffer), and an `EXPAND` computes nothing itself. Without the `stage`, `mul %xv %xv` above is asked for at `k` (by the sum) and at `r` (by the assert): two indices, so it is staged. In center.uir, `%xv` is also asked for at two indices, but it is a LOAD, which is free to re-read. One way to implement the rule:

1. Lower the program, recording for each node the set of indices it was asked for. Leave out nodes that an index or a SHRINK offset depends on: a staged value's bounds are the dtype's full range, so a staged index would fail the bounds check. They are always recomputed.
2. Of the nodes outside the free list with two or more indices, wrap the outermost ones (those no other such node uses) in a `STAGE`. In this chain test, `%v` is used by a sum and by the output:

   ```text
   %x    = buffer 3 slot=0 dtype=i32
   %sx   = store %x [1 2 3]
   %xv   = load (after %x %sx)
   %v    = add (mul %xv %xv) (expand 1 3)
   %test = assert (add %v (expand (reduce %v op=add pop=1) 3)) [19 22 27]
   ```

   Of `%v = add (mul %xv %xv) (expand 1 3)`, the `ADD` and the `MUL` both qualify (the `1` inside the `EXPAND` is a CONST, which is free); staging the `ADD` alone is enough, because the `MUL` is then asked for once, by the fill loop.
3. Lower again. Repeat until nothing new is staged; it settles in a round or two.

The rule is simple, not optimal. It materializes the cheap `mul` above, where recomputing would be faster. Improving it is performance work, and timing starts to matter in chapter 6.

**3. Fusing would be wrong: a load and a later store to the same buffer.** [shift.uir](examples/shift.uir) shifts a buffer right by one, in place:

```text
%x    = buffer 4 slot=0 dtype=i32
%sx   = store %x [1 2 3 4]
%x1   = after %x %sx
%s    = store (shrink %x1 1 3) (load (shrink %x1 0 3))
%test = assert (after %x %s) [1 1 2 3]
```

The value `load (shrink %x1 0 3)` is the whole window `[1 2 3]`, read before the store, so `x` becomes `[1 1 2 3]`. Fused, the read moves into the store's loop:

```text
# FAIL: fused, the loop overwrites x[1] before it reads it
%x    = buffer 4 slot=0 dtype=i32
%sx   = store %x [1 2 3 4]
%x1   = after %x %sx
%r    = range 3 slot=0
%v    = load (index (shrink %x1 0 3) %r)
%s    = end (store (index (shrink %x1 1 3) %r) %v) %r
%test = assert (after %x %s) [1 1 2 3]
```

| `r` | reads `x[r]` | writes `x[r + 1]` | `x` afterwards |
|-----|--------------|-------------------|----------------|
| 0 | 1 | 1 | `[1 1 3 4]` |
| 1 | 1, written at `r = 0` | 1 | `[1 1 1 4]` |
| 2 | 1, written at `r = 1` | 1 | `[1 1 1 1]` |

This is a *hazard*: fusion changed the order of a read and a write to the same memory. The oracle accepts this program as valid, and it computes `[1 1 1 1]`: a FAIL, not an ERROR. The ordering check of chapter 2 is satisfied (the store depends on the load), but it orders *nodes*, not loop iterations. Here the shape program means "read all, then write all", and fusion turned that into "read one, write one". The fix is to materialize the value first:

```text
%x    = buffer 4 slot=0 dtype=i32
%sx   = store %x [1 2 3 4]
%x1   = after %x %sx
%t    = alloc 3 slot=1 dtype=i32
%q    = range 3 slot=1
%fill = end (store (index %t %q) (load (index (shrink %x1 0 3) %q))) %q
%r    = range 3 slot=0
%v    = load (index (after %t %fill) %r)
%s    = end (store (index (shrink %x1 1 3) %r) %v) %r
%test = assert (after %x %s) [1 1 2 3]
```

The same thing can happen across loops. Here `%v` is read before `x` is overwritten, but its second consumer runs after:

```text
%x    = buffer 3 slot=0 dtype=i32
%y    = buffer 3 slot=1 dtype=i32
%z    = buffer 3 slot=2 dtype=i32
%sx   = store %x [1 2 3]
%v    = load (after %x %sx)
%sy   = store %y %v
%s2   = store (after %x %sy) [7 7 7]
%sz   = store (after %z %s2) %v
%test = assert (after %z %sz) [1 2 3]
```

Fused, `z`'s loop would load `x[r]` with nothing ordering it against the `[7 7 7]` store, and the oracle rejects the lowered program as unordered, an ERROR for a program that was valid. A LOAD is free to re-read only while its buffer has not changed.

The rule: **when a STORE to a buffer depends on a rank-1 LOAD of that buffer, materialize the LOAD.** Its consumers then read the temp buffer, wherever their loops end up. In shift.uir the store's value is that load; here `%s2` depends on `%v` through `%sy`. tinygrad realizes a store's value when it reads the target (`realize_store_after_src` in `tinygrad/schedule/indexing.py`); the course materializes the LOAD itself, which also covers later stores reached through `AFTER`. It is conservative: `x = x + 1` would be safe fused, because each iteration reads only the element it writes. Proving that needs index analysis, which this course does not do yet. Unlike the first two situations, this one is about correctness, so tests catch it.

**Where the fission points are.** Every STAGE, temp buffer for an assert, and hazard fix above splits the work into separate loop nests. So does every REDUCE that feeds a broadcast (center.uir): its loop must finish before the consumer's loop starts (tinygrad counts this differently; see below). Everything else is fused.

> **Spec note.** The syllabus titles week 4 "Kernel Fusion/Fission", but week 7 is where "we add kernels".

> **Interpretation.** Everything still renders into one C function (chapter 2's calling convention), and a "kernel" is one top-level loop nest in it. tinygrad, where each materialized buffer is a kernel boundary (`bufferize_to_store` in `tinygrad/schedule/rangeify.py`), keeps a REDUCE that feeds a broadcast in its consumer's kernel. The course's rule is tinygrad's first step (`run_rangeify` marks a node whose consumers give it different ranges); tinygrad then unmarks cheap nodes (`remove_bufferize`), and its free list is not the course's.

**Outside the hazard, results never depend on fusion.** Every materialization choice gives the same answer: values are pure, so computing one twice or reading it from memory gives the same bits. That is why the examples' verdicts cannot tell whether your rule works. Read `--emit-c` instead (step 6 of How to start). It is also why the choice is safe to experiment with: change the rule, and the tests tell you only whether you broke something.

**Common mistakes.**

- Materializing inside the consumer's loop: the fill loop must be its own loop, finished before anyone reads the buffer. Read it through `after %t %fill`.
- A temp ALLOC reused for two STAGEs. Each materialized node needs its own buffer and slot.
- Treating the hazard rule as an optimization to skip. [shift.uir](examples/shift.uir) fails without it.
- Staging a value used as an index. A staged value is read back from memory, so its bounds are the dtype's full range, and the lowered index no longer passes the bounds check. The course's rule leaves index operands alone.
- Expecting a test to show that a value was materialized. Only the C shows it.

## Ops introduced

| Op | Srcs | Arg | Shape | Dtype | Meaning |
|----|------|-----|-------|-------|---------|
| `REDUCE` | value | `op` (`add`, `mul`, `max`), `pop` (axes to remove, 0 ≤ `pop` ≤ rank) | the value's, without its first `pop` axes | the value's: `i32` or `f32` | Combines the leading axes: from the identity (`0`, `1`, the smallest value), in index order |
| `EXPAND` | value (rank 0), shape: `[]` or a length `n` | none | `(n,)`, or the value's for `[]` | the value's | The value repeated along a new leading axis |
| `STAGE` | value | none | the value's | the value's | The value; compiled, it is kept in a temp buffer |

UIR: `reduce %v op=add pop=1`, `expand %x 4`, `stage %v`. ALU ops (chapter 1) may now be rank 1, element by element. The spec adds no recursive properties this week: shape, dtype and bounds extend to the new ops as the table says, and the bounds of `EXPAND` are its source's, those of `REDUCE` and `STAGE` the dtype's full range ([uir.md](../uir.md#bounds)): a staged value is read back from memory.

Rules your compiler checks, in addition to chapters 1–3:

- **ALU sources have one shape**, of rank 0 or 1. A rank-0 value next to a vector must be expanded first.
- **Indices stay rank 0**: the indices of `INDEX` and the offset of `SHRINK`.
- **`REDUCE`**: its source is a value (not memory, not an effect), its op is `add`, `mul` or `max` and takes the source's dtype, and `pop` is at most the source's rank.
- **`EXPAND`**: its source is a rank-0 value, so the result is at most rank 1.
- **`STAGE`**: its source is a value.
- **`STACK` inputs are still constants** ([Spec notes](#spec-notes)).

## Assignment

Start by writing ten tests of your own in UIR (the syllabus asks for ten each week), and check them with the [oracle](../oracle/README.md). [How to start](#how-to-start) gives an order to build things in.

1. **Check** the new rules above.
2. **Interpret** the new ops: elementwise ALU ops on rank-1 values, `EXPAND`, `REDUCE` (from the identity, in index order) and `STAGE` (returns its source).
3. **Rangeify** every program after inlining: lower it to chapter 3 UIR, in which no computed value has a shape and every loop is a RANGE and END. Lower REDUCEs to accumulators with their init in the right loops.
4. **Materialize** into temp ALLOCs: every `STAGE`, the actual value of a rank-1 ASSERT, every rank-1 LOAD that a later STORE to its buffer depends on, and every node the [course's rule](#lesson-3-kernel-fusion-and-fission) selects.
5. **Print** the lowered program with `--emit-uir`; for every example and test, the oracle gives it the same verdict as the original.
6. **Render**, compile and run every program from chapters 1–4 with chapter 3's `nest` and `render`, and keep the interpreter agreeing with the C.

Restrictions this chapter: shapes are at most rank 1; broadcasting is written with `EXPAND`; `STACK` inputs are constants; everything renders into one C function.

## Example programs

All in [examples/](examples/). Each file's comments show the hand calculation. The [oracle](../oracle/README.md) passes all of them, and so does each one's lowering.

| File | Exercises |
|------|-----------|
| [expand_add.uir](examples/expand_add.uir) | The draft course page's example: `EXPAND`, a rank-1 `ADD`, a `REDUCE` |
| [scale.uir](examples/scale.uir) | A rank-1 expression stored to a buffer: one fused loop |
| [dot.uir](examples/dot.uir) | An `f32` dot product: elementwise `MUL`, then `REDUCE` |
| [max_reduce.uir](examples/max_reduce.uir) | `op=max` from the identity, on negative inputs |
| [center.uir](examples/center.uir) | A reduction broadcast back with `EXPAND`: two loops |
| [row_sums.uir](examples/row_sums.uir) | A `REDUCE` inside a chapter 3 loop: the init runs once per row |
| [stage_reuse.uir](examples/stage_reuse.uir) | `STAGE`: one value, two loops, one temp buffer |
| [shift.uir](examples/shift.uir) | A store that reads its own target: fusing it is wrong |

## Spec notes

> **Spec note.** Week 1 says STACK inputs can only be STACK/CONST "until week 4", but week 5 is where "STACK supports arbitrary inputs". As [chapter 1](../01-uops-and-rewrites/README.md#spec-notes) announced, this course follows week 5: STACK inputs stay constants in this chapter.

> **Spec note.** The At a Glance table puts "movement ops, reduction, rangeify" in weeks 3–4 with the milestone "Compile any model to C", while the week sections put movement ops in week 5 and say "This compiler is now capable of compiling *any* model" there. This chapter follows the week sections.

> **Interpretation.** The syllabus's own gemm example writes `reduce %4 op=add pop=1`. That `pop` removes *leading* axes, and that `pop=0` is allowed and changes nothing, follow tinygrad (`_shape` in `tinygrad/uop/ops.py`; tinygrad's `uir.py` defaults `pop` to 0). A REDUCE takes the dtypes its op takes (`i32`, `f32`; not `bool`), and its bounds are the dtype's full range, as tinygrad's bounds rules have no REDUCE case. The spec lists `EXPAND` and `STAGE` without arguments; their forms follow tinygrad and the draft course page ([Lesson 1](#lesson-1-broadcasting-and-reduction)). `stage x` with one source is what tinygrad's `Tensor.contiguous()` builds (`tinygrad/mixin/elementwise.py`); tinygrad's internal STAGE also carries ranges as sources, which this course's does not.

> **Interpretation.** "Rangeify removes shapes from all ops" is read as: from every computed value. Memory keeps its shape and is indexed; a constant STACK stays a stack and is indexed like a C array (chapter 2's rendering), where tinygrad rewrites it into a chain of WHEREs (`convert_stack_to_where` in `tinygrad/schedule/indexing.py`); a rank-1 ASSERT compares whole values, as in chapter 2.

> **Interpretation.** STAGE's bounds are the dtype's full range. tinygrad passes them through from the source (`_min_max` in `tinygrad/uop/ops.py`); the course widens them on purpose, because the compiled value is read back from memory like a LOAD, and the lowered program must pass the same checks.

> **Interpretation.** The rules that ALU sources share one shape, that indices and SHRINK offsets stay rank 0, that an inline `expand` of a literal is typed like the literal, and that a rank-1 load is read whole at its place in the order (so a store that reads its target sees the old values) are listed with the oracle's other decisions in [oracle/README.md](../oracle/README.md#decisions-not-in-uirmd).

## Quiz

1. What are the shape and value of `expand (add 2 3) 3`?
   <details><summary>Answer</summary>Shape <code>(3,)</code>, value <code>[5 5 5]</code>.</details>
2. Why is `add [1 2 3] 1` an error in this course, and how do you fix it?
   <details><summary>Answer</summary>ALU sources must have one shape, and <code>()</code> is not <code>(3,)</code>: broadcasting is explicit. Write <code>add [1 2 3] (expand 1 3)</code>.</details>
3. `reduce [2 -3 4] op=mul pop=1` and `reduce [-8 -2] op=max pop=1` on `i32`: what are they?
   <details><summary>Answer</summary><code>1 × 2 × -3 × 4 = -24</code>, and <code>-2</code> (max starts from <code>-2147483648</code>).</details>
4. What is `elem(add %v (expand %s 4), r)`, where `%v` is a rank-1 load of buffer `%b` and `%s` is rank 0?
   <details><summary>Answer</summary><code>add (load (index %b r)) %s</code>: the load reads element <code>r</code>, and the expand gives <code>%s</code> itself.</details>
5. Your `--emit-uir` output gets PASS from `oracle/uir.py --lowered`, but the compiled program gives FAIL. Which part of your compiler has the bug?
   <details><summary>Answer</summary>Rangeify produced a correct chapter 3 program, so the bug is after it: in <code>nest</code>, <code>render</code> or the runtime. Or the printer: check that <code>--emit-uir</code> prints the same graph you render.</details>
6. Name the three situations in which rangeify materializes a value into a temp buffer instead of fusing it, and say which one is about correctness.
   <details><summary>Answer</summary>The program asks for it (STAGE, a rank-1 assert); consumers need the value at different indices (the course's rule); a store to a buffer depends on a rank-1 load of it (the hazard). The last one is about correctness: fused, it computes a different result.</details>
7. How many loops does `reduce (add %a %b) op=add pop=1` lower to, with `%a` and `%b` rank-1 loads of the same length, and where does the `ADD` run?
   <details><summary>Answer</summary>One loop, the REDUCE's. The <code>ADD</code> is fused into it: <code>elem(add %a %b, r)</code> is <code>add (load a[r]) (load b[r])</code>, computed in the reduce loop.</details>
8. In center.uir, the sum's loop runs before the output loop, once. What in the lowered graph makes that happen?
   <details><summary>Answer</summary>The output loop asks for the expanded mean with no index, so the lowered sum depends on no output range. The evaluation rule computes a node once per value of the loops it depends on, so the sum runs once, before the loop that uses it, and <code>nest</code> places it there.</details>

## Sources

1. NumPy Manual, "Broadcasting". https://numpy.org/doc/stable/user/basics.broadcasting.html — the implicit broadcasting rules that `EXPAND` makes explicit.
2. Goldberg, "What Every Computer Scientist Should Know About Floating-Point Arithmetic", ACM Computing Surveys 23(1), 1991. https://doi.org/10.1145/103162.103163 — why the order of a floating-point sum changes its result.
3. Kennedy & McKinley, "Maximizing Loop Parallelism and Improving Data Locality via Loop Fusion and Distribution", LCPC 1993 (LNCS 768, Springer 1994), pp. 301–321. https://doi.org/10.1007/3-540-57659-2_18 — loop fusion and distribution (fission), and the NP-hardness of fusing for locality.
4. Ragan-Kelley et al., "Halide: A Language and Compiler for Optimizing Parallelism, Locality, and Recomputation in Image Processing Pipelines", PLDI 2013. https://doi.org/10.1145/2491956.2462176 — the trade-off between fusion, recomputation and storing intermediate results.
5. Williams, Waterman, Patterson, "Roofline: An Insightful Visual Performance Model for Multicore Architectures", CACM 52(4), 2009. https://doi.org/10.1145/1498765.1498785 — why fused elementwise code is faster: arithmetic intensity.
6. tinygrad, commit 07821cae. https://github.com/tinygrad/tinygrad — `tinygrad/schedule/indexing.py` (`run_rangeify`, `realize_store_after_src`, `convert_stack_to_where`), `tinygrad/mixin/elementwise.py` (`contiguous` builds a STAGE), `tinygrad/schedule/rangeify.py` (`bufferize_to_store`, `remove_bufferize`), `tinygrad/codegen/__init__.py` (`lower_reduce`), `tinygrad/uop/ops.py` (`_shape` of REDUCE and EXPAND, `identity_element`).
