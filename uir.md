# UIR: the interchange format

> This syllabus will outline the spec, but not the implementation. The implementation and choice of programming language is up to the student. There is no starter code. We will establish a universal, simple, interchange format for UOps.
>
> — the syllabus

UIR is a text form of a UOp graph. Tests are written in it, and your compiler reads it. This page defines the format and the conventions every chapter shares, and lists every op with the chapter that introduces it. The chapters define what each op means.

> **Interpretation.** The syllabus shows UIR only by example. A few rules below also cite *the draft course page*, an earlier web version of the syllabus with short UIR examples per week; where it disagrees with the syllabus, the syllabus wins. The rules below follow tinygrad's UIR parser, `tinygrad/uop/uir.py`, whose docstring says it reads "studentgrad's hand-written UIR". tinygrad has no `assert` op; it is specific to the course.

## A first program

```text
# 2 + 3 should be 5
%sum  = add 2 3
%test = assert %sum 5
```

Each line binds a name to a value. `add 2 3` is the op `add` with two sources, the literals `2` and `3`. `assert` compares its two sources.

## Lines

A program is a sequence of assignments:

```text
%name = op src src ... key=value key=value
```

- **`%name`** is any word after `%`. Each name is assigned once, and can be used only after its line.
- **`op`** is an op name in lowercase: `add`, `reduce`, `buffer`.
- **Sources** come first, separated by spaces. A source is a `%name`, a literal, a `[stack]`, or a nested `(op ...)`.
- **Arguments** come after all sources, as `key=value`, for example `dtype=f32`, `slot=0`, `op=add`, `pop=1`.
- The right side may also be a single value: `%a = 3`, `%v = [1 2 3]`.
- **`#`** starts a comment that runs to the end of the line.
- The last assignment is the program's root.

The syllabus's own example (it uses ops from chapters 2–5; read it for the syntax only):

```text
# gemm_256x256.uir
%0 = buffer 65536 dtype=f32 slot=0
%1 = buffer 65536 dtype=f32 slot=1
%2 = reshape %0 [256 256 1]
%3 = reshape %1 [256 1 256]
%4 = mul %2 %3
%5 = reduce %4 op=add pop=1
```

## Values

| Form | Example | Meaning |
|------|---------|---------|
| Integer literal | `3`, `-7`, `0x2a` | A `CONST`; must fit in `i32` |
| Float literal | `2.5`, `1e-3`, `-inf`, `nan` | A `CONST` |
| Bool literal | `true`, `false` | A `CONST` of dtype `bool` |
| Stack | `[1 2 3]`; `[[1 2] [3 4]]` from chapter 5 | A `STACK` of the values inside, which adds a leading axis |
| Nested op | `(index %v 1)` | The same as a separate line, written inline |
| Name | `%sum` | The value bound to that name |
| Scoped block | `{ %a = ...  %b = ... }` | The value of its last assignment; its names are not visible outside |

Nested ops and stacks are shorthand. These two programs build the same graph, because UOps are hash-consed (chapter 1):

```text
%x = add (index [10 20 30] 1) 1
```

```text
%v = index [10 20 30] 1
%x = add %v 1
```

> **Interpretation.** The draft course page introduces scoped blocks with week 6's "syntactic sugar and lexical scopes". Earlier chapters do not need them.

## Arguments

| Value form | Example |
|------------|---------|
| Literal | `slot=0`, `pop=2` |
| Bare word | `dtype=f32`, `op=add` |
| List | `slot=[1 2]` |
| Quoted string | `name='my kernel'` |

Each op accepts a fixed set of keys. Repeating a key, or using a key the op does not have, is an error.

## Conventions

The syllabus leaves the following open. This course settles each one once, here, so that every chapter and every test agrees. All of them are **interpretations**; the reason for each is given.

### Literals

A `CONST`'s dtype is determined by its arg (the syllabus: "type determined by the arg"): a bool arg is `bool`, an integer arg is `i32`, a float arg is `f32`. The parser picks each literal's arg from the typed value it must match:

| Literal | Must match an `i32` | Must match an `f32` | Matches nothing typed |
|---------|---------------------|---------------------|-----------------------|
| `3` | `3`, an `i32` | `3.0`, an `f32` | `i32`, or `f32` if a float literal is among the values it must match (`add 2 2.5`, `[1 2.5]`) |
| `2.5` | error | `2.5`, an `f32` | `f32` |
| `true` | error | error | `bool` |

"Must match" means: the other operand of a binary ALU op, the other branch of `where`, the target of a `store`, the actual value of an `assert`, the PARAM a `call` argument binds to, and the other elements of a stack. Indices are always `i32`. From chapter 4, an `expand` of a literal written inline, `(expand 1 4)`, is matched like the literal: next to an `f32` vector it is `[1.0 1.0 1.0 1.0]`.

A literal on its own line (`%a = 3`) is typed there, by the last column, so `%a` is `i32`. A float literal's value is rounded to the nearest `f32` when parsed (`0.1` becomes `0.100000001490116…`).

So `add %x 1` works whether `%x` is `i32` or `f32`, `add 2 3` is `i32`, and `add 2 2.5` is `f32`. Because the dtype lives in the arg, an `i32` 3 and an `f32` 3.0 are different UOps, and hash-consing stays correct. *Why:* tinygrad gets the same behavior from "weak" literal dtypes (`tinygrad/dtype.py`), which the syllabus's four dtypes do not include; the draft course page relies on it ("promote i32 to f32" for `[42 27]` next to an `f32` value).

### Mixing dtypes

Two typed operands of different dtypes are an error: write a `cast`. `add (cast %i dtype=f32) %f` is fine; `add %i %f` is not. *Why:* tinygrad's op spec rejects it (`tinygrad/uop/spec.py`); its front end inserts the casts.

### Arithmetic

Your interpreter and the code you generate must agree bit for bit (except NaN payloads; ASSERT treats every NaN as unequal anyway), so the edge cases are fixed here.

| Case | Rule | Why |
|------|------|-----|
| `i32` overflow | wraps (two's complement) | tinygrad's constant folding wraps; C needs `-fwrapv` to match |
| `div`, `mod` | **floor** division and modulo, like Python: `div -7 2` is `-4`, `mod -7 2` is `1` | tinygrad's DIV/MOD are floor; its TRUNCDIV/TRUNCMOD are C's `/` and `%` |
| `shl a b`, 0 ≤ b < 32 | a × 2^b, wrapped; also for negative a | C makes left shifts of negative values undefined, so render them on unsigned values |
| `f32` results | rounded to the nearest `f32` (ties to even) after every op | IEEE 754 single precision; C's `float` gives it when `FLT_EVAL_METHOD` is 0 and contraction is off (`-ffp-contract=off`, no `-ffast-math`), otherwise `a * b + c` may fuse into one rounding |
| `cast` `i32` → `f32` | nearest `f32`, ties to even | the usual C behavior |
| `cast` `f32` → `i32` | truncates toward zero | C's conversion |
| `cast` to `bool` | `x != 0` | tinygrad rewrites it this way |
| `cast` from `bool` | `false` is 0, `true` is 1 | C's conversion |
| `recip` | `f32` only (`cast` an `i32` first); `recip 0.0` is `inf`, `recip -0.0` is `-inf` | tinygrad's op spec rejects `recip` on ints |
| ALU ops on rank-1 values (chapter 4) | element by element, each element by the rules above | the syllabus: "ALU can be rank 1 now" |
| `reduce` (chapter 4) | starts from the identity (`add`: 0; `mul`: 1; `max`: −2147483648 for `i32`, `-inf` for `f32`) and combines the elements in index order, each step by the rules above | tinygrad's `lower_reduce`; `f32` addition is not associative, so the order is part of the result |
| Undefined: tests never do these, not even in the branch a `where` does not pick | `div`/`mod` by zero; `div`/`mod` of −2147483648 by −1; `shl` by < 0 or ≥ 32; `max` with a NaN, or of `0.0` and `-0.0`; `cast` `f32` → `i32` of NaN, ±inf or out-of-range values | C leaves them undefined, or C and Python disagree |

### Bounds

`bounds` is an interval `[vmin, vmax]` for `i32` and `bool` values (`false` = 0, `true` = 1). `f32` values have no bounds. Validation depends on bounds, so every compiler must compute exactly these, no tighter and no looser:

| Node | Bounds of `a op b` (a in `[a0, a1]`, b in `[b0, b1]`) |
|------|------------------------------------------------------|
| All sources exact (`vmin = vmax`) | Exact: the op applied to those values |
| `CONST` | Its value |
| `PARAM` | The dtype's full range (`bool`: `[0, 1]`) |
| `STACK` | Smallest `vmin` to largest `vmax` of its elements |
| `INDEX` | The indexed value's bounds |
| `CALL` | The body's bounds |
| `RANGE` (chapter 3) | `[0, end − 1]`; the end is a constant ≥ 1 |
| `AFTER` (chapter 2) | The value's bounds |
| `LOAD` (chapter 2) | The dtype's full range |
| `EXPAND` (chapter 4) | The source's bounds |
| `REDUCE`, `STAGE` (chapter 4) | The dtype's full range: a STAGE is read back from memory when compiled |
| `ADD` | `[a0 + b0, a1 + b1]` |
| `MUL` | Smallest to largest of the four products of ends |
| `MAX` | `[max(a0, b0), max(a1, b1)]` |
| `DIV` by b with exact bounds c > 0 | `[a0 div c, a1 div c]` |
| `MOD` by b with exact bounds c > 0 | `[a0 mod c, a1 mod c]` if `a0 div c = a1 div c`, else `[0, c − 1]` |
| `SHL` by b with exact bounds 0 ≤ c < 32 | `[a0 × 2^c, a1 × 2^c]` |
| `CMPLT` (`i32` operands) | `[1, 1]` if `a1 < b0`; `[0, 0]` if `a0 ≥ b1`; else `[0, 1]` |
| `WHERE c x y` | `x`'s if c is `[1, 1]`; `y`'s if c is `[0, 0]`; else smallest to largest of both |
| `CAST` `bool` → `i32` | The source's bounds |
| `CAST` `i32` → `bool` | `[0, 0]` if the source is `[0, 0]`; `[1, 1]` if 0 is outside the source's bounds; else `[0, 1]` |
| Anything else | The dtype's full range |

An `i32` result whose interval leaves the `i32` range widens to the full `i32` range. *Why:* the spec types bounds as `tuple[int, int]`. The rules are tinygrad's (`tinygrad/uop/ops.py`, `_min_max`), trimmed to the course's ops, except STAGE: tinygrad passes its source's bounds through, and the course widens them because a staged value is read back from memory (chapter 4). tinygrad's bounds assume signed overflow never happens; because this course defines overflow to wrap, it must widen.

### Validation

Programs are checked as written, before any rewriting. Every line is checked on its own (its op, args, dtypes, shapes and bounds), whether or not the root reaches it; whole-program checks (ordering, loops, parameters) cover the graph the root reaches. A program has exactly one `assert` line, its last, wherever other lines are. A check that uses bounds (in-range indices; from chapter 2, also loads and stores) passes only if the bounds of the program as written prove it. *Why:* a compiler that rejects programs only after optimizing would accept or reject the same program depending on which rules it implements.

### Evaluation

A node is computed once for each combination of values of the loops (RANGEs) it depends on, and of every loop enclosing one of those. Loop `o` encloses loop `k` when `o` is still open where `k` ends: `o` is in the `ranges` of `k`'s END (and, transitively, anything enclosing `o`). So a node that uses only `k` still runs once per value of `o` and `k`. A node that depends on no loop is computed once, before the loops, even if a node inside a loop uses it. Chapters 1 and 2 have no loops, so there every node is computed once and, because loads and stores are fully ordered, any topological order gives the same result. *Why:* this is what tinygrad does: its linearizer makes each inner loop's bound depend on the enclosing RANGE, so everything inside the inner loop depends on the outer one too, and then places each node at the depth of its loops (`tinygrad/codegen/late/linearizer.py`). Loop-invariant code is hoisted for free.

### Programs and ASSERT

- **The root.** A test program has exactly one `assert`, on its last line, which is the root. Nodes the root does not reach are checked ([Validation](#validation)) but never evaluated or rendered: UOps form a graph, not a list of statements.
- **`assert actual expected`.** Two sources of the same shape. Passes when every element is numerically equal (`-0.0` equals `0.0`; NaN equals nothing). The expected value is usually a literal, which takes the actual value's dtype.
- **Memory (from chapter 2).** When `actual` is a buffer (`after %buf %done`), ASSERT compares the buffer's contents.

*Why:* the draft course page writes one assert per example ("Each assert pairs a result with its expected value"). Exact comparison is enough while tests use small integers and halves, which `f32` represents exactly.

### Slots

`slot=` numbers things of one kind: the arguments of a CALL (PARAM), the buffers of a program (BUFFER, ALLOC), and the loops of a program (RANGE). A buffer and a range may both be `slot=0`. *Why:* tinygrad's ParamArg and RANGE each carry their own slot.

## Ops by chapter

Each chapter introduces the ops of one syllabus week and defines them; this table is the index.

| Chapter | Op | Srcs | Args | Details |
|------|----|------|------|---------|
| 1 | `const` | none; written as a literal | the value | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `param` | shape: `[]` for `()`, or `n` for `(n,)` | `slot` `dtype` | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `call` | body, then one value per param | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `stack` | values of one shape; written `[a b c]` | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `index` | value, then one index per axis to pop | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `cast` | value | `dtype` | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `recip` | value | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `add` `mul` `max` `xor` | a, b | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `cmplt` | a, b | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `shl` `div` `mod` | a, b (`i32`) | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `where` | condition, then-value, else-value | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `assert` | actual, expected | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 2 | `buffer` | shape: `[]` or `n` | `slot` `dtype` | [2](02-memory-and-shape/README.md#ops-introduced) |
| 2 | `alloc` | shape: `[]` or `n` | `slot` `dtype` | [2](02-memory-and-shape/README.md#ops-introduced) |
| 2 | `shrink` | buffer, offset, size | | [2](02-memory-and-shape/README.md#ops-introduced) |
| 2 | `load` | address | | [2](02-memory-and-shape/README.md#ops-introduced) |
| 2 | `store` | address, value | | [2](02-memory-and-shape/README.md#ops-introduced) |
| 2 | `after` | value, then the effects it waits for | | [2](02-memory-and-shape/README.md#ops-introduced) |
| 3 | `range` | end | `slot` | [3](03-loops/README.md#ops-introduced) |
| 3 | `end` | effect, range | | [3](03-loops/README.md#ops-introduced) |
| 4 | `reduce` | value | `op` `pop` | [4](04-rangeify/README.md#ops-introduced) |
| 4 | `expand` | value, shape: `[]` or `n` | | [4](04-rangeify/README.md#ops-introduced) |
| 4 | `stage` | value | | [4](04-rangeify/README.md#ops-introduced) |
| 5 | `reshape` `permute` `pad` | | | not written yet |
| 6 | `gradient` `detach` | | | not written yet |
