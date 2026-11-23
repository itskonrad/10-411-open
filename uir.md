# UIR: the interchange format

> This syllabus will outline the spec, but not the implementation. The implementation and choice of programming language is up to the student. There is no starter code. We will establish a universal, simple, interchange format for UOps.
>
> — the syllabus

UIR is a text form of a UOp graph. Tests are written in it, and your compiler reads it. This page defines the format and the conventions every chapter shares, and lists every op with the chapter that introduces it. The chapters define what each op means.

> **Interpretation.** For week 1 the course released a two-page reference: the UIR grammar, the rules for test files, the limits, and a table of every op's dtype, shape, bounds and cost. This page follows it for everything it covers, and where it must read between the lines it says so (*Interpretation*); where the syllabus and the reference differ (the reference has only `i32` and `bool` in week 1, and no `recip`), the reference wins. Where chapters 2–4 need more than the reference says, the text calls it *course syntax*: nested `(op ...)`, `f32`, rank-1 parameters. The [oracle](oracle/README.md) has a `--week` flag for this: `--week 1` accepts exactly what the reference accepts. The rest of the rules below follow tinygrad's UIR parser, `tinygrad/uop/uir.py`, whose docstring says it reads "studentgrad's hand-written UIR". tinygrad has no `assert` op; it is specific to the course.

## A first program

```text
# 2 + 3 should be 5
%sum  = add 2 3
%test = assert %sum 5
```

Each line binds a name to a value. `add 2 3` is the op `add` with two sources, the literals `2` and `3`. `assert` compares its two sources.

## Lines

A program is a sequence of bindings, one op each:

```text
%name = op src src ... key=value key=value
```

Reading a file takes six kinds of token:

| Token | Example | Meaning |
|-------|---------|---------|
| definition | `%x=` | A name being defined. `%x=` and `%x =` are one token |
| reference | `%x`, `%0` | A defined name: `%` followed by one or more ASCII letters, digits or underscores |
| integer, bool | `-7`, `0xff`, `007`, `false` | Decimal `-?[0-9]+` or hex `0x[0-9a-fA-F]+`; leading zeros are allowed. `true` and `false` |
| op | `add` | A lowercase op name. A constant is written as its literal, never as `const` |
| attribute | `slot=0` | One `key=value` token, with no spaces inside. Attributes follow all sources; keys are unique and their order does not matter |
| `[`, `]` | `[3 6]` | Brackets around the elements of a stack |

The grammar is four lines:

```text
file    := binding+
binding := DEF rhs
rhs     := OP atom* ATTR* | atom
atom    := REF | INT | BOOL | '[' atom* ']'
```

Hex literals have a lowercase `0x` and no sign, and `slot=` is an unsigned decimal (`slot=00` is fine, `slot=+0` is not). Whitespace is space, tab, carriage return and newline; any other non-ASCII character outside a comment is an error. UIR is case-sensitive, except in comments: `#` starts a comment that runs to the end of the line. A newline is just whitespace, so a binding may span lines. Each name is defined once and used only after its definition. The last binding is the program's root. A right side that is a single atom binds a name to it: `%a = 3`, `%v = [1 2 3]`.

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

> **Interpretation.** *Course syntax.* The reference grammar has no nested ops, no float literals, and no `{…}` blocks: every op has its own line. Chapters 2–4 write many tests with nested ops, `(index %v 1)` for the value of a line `%t = index %v 1` placed inline, because the draft course page and tinygrad's parser do. The oracle accepts them from `--week 2` on, and rejects them with `--week 1`. A nested op is the same graph as the line it replaces (UOps are hash-consed), so a test can always be written flat; if the reference's later weeks turn out to have no nesting, the chapters' examples convert mechanically.

## Values

| Form | Example | Meaning |
|------|---------|---------|
| Integer literal | `3`, `-7`, `0x2a` | A `CONST`; must fit in `i32` (the reference does not say; the oracle rejects `2147483648` and `0xffffffff`) |
| Bool literal | `true`, `false` | A `CONST` of dtype `bool` |
| Stack | `[1 2 3]` or `stack 1 2 3`; `[[1 2] [3 4]]` from chapter 5 | A `STACK` of the values inside, which adds a leading axis. `[]` is the scalar shape marker |
| Name | `%sum` | The value bound to that name |

Course syntax, from chapter 2 on (see the Interpretation above):

| Form | Example | Meaning |
|------|---------|---------|
| Float literal | `2.5`, `1e-3`, `-inf`, `nan` | A `CONST` of dtype `f32` (chapter 2) |
| Nested op | `(index %v 1)` | The same as a separate line, written inline |
| Scoped block | `{ %a = ...  %b = ... }` | Week 6's "lexical scopes": the value of its last assignment, its names not visible outside. Not accepted yet |

Two programs that build the same graph:

```text
%v = [10 20 30]
%e = index %v 1
%x = add %e 1
```

```text
%v = [10 20 30]
%x = add (index %v 1) 1
```

The second is course syntax; because UOps are hash-consed (chapter 1), both give the same root.

## Arguments

| Key | Example | Used by |
|-----|---------|---------|
| `slot` | `slot=0` | `param`, and from chapter 2 `buffer`, `alloc`; from chapter 3 `range`. An unsigned decimal number |
| `dtype` | `dtype=i32`, `dtype=bool` | `param`, `cast`; from chapter 2 `buffer`, `alloc`. `f32` is course syntax from chapter 2 |
| `addrspace` | `addrspace=ALU` | `param` (week 1 requires `ALU`) |
| `op`, `pop` | `op=add pop=1` | `reduce` (chapter 4) |

Each op accepts a fixed set of keys, and requires all of them. Repeating a key, or using a key the op does not have, is an error; so is a space inside `key=value`.

## Test files and outcomes

A test is a file that ends with a single `assert`, and never uses it as an operand. Its left operand is the program's return value (an ALU value is a scalar in week 1); its right operand is the expected value, a literal or a stack of literals of the same dtype and shape. **Every node must be reachable from the assert**, including call bodies and unused arguments. Reachability is about nodes, not lines: a line that rebuilds an existing node (`%b = 3` next to `%a = 3`) is not an error, but a node nothing uses is.

What a compiler prints for a file is one of four outcomes, and a test's filename says which one it is meant to give:

| Filename prefix | Example | Outcome | Meaning |
|-----------------|---------|---------|---------|
| none | `assert 3 3` | `MATCH` | The program is valid and the values match |
| `mismatch_` | `assert 3 4` | `MISMATCH` | The program is valid and the values differ |
| `rejected_` | `assert 3 true` | `REJECTED` | The program is invalid, and is rejected before it runs (here the dtypes differ) |
| `overbudget_` | 100 parsed nodes | `OVERBUDGET` | A limit is hit; nothing runs |

**Limits.** A file of more than 4096 bytes is over budget before it is parsed. After parsing, 100 or more nodes, or 300 or more source edges, is over budget. After validation, a [static cost](#cost) of 1,000,000 or more is over budget. The checks run in that order, so a file that is both too large and invalid is `OVERBUDGET`; one with a parse error is `REJECTED` before any count. A compiler that validates while it builds therefore needs two passes: one that only parses, counting distinct nodes and edges, then one that builds and checks.

**Command line.** The course's compiler is run as `./compile [file ...]`. For each file it prints one line to stdout, `<OUTCOME> <file>`: one space, then the path exactly as it was given. Anything else, such as the reason for a rejection, belongs on stderr. [tools/check_compiler.py](tools/check_compiler.py) and the oracle follow this format.

> **Interpretation.** The reference says "nodes ≥ 100 or source edges ≥ 300 immediately after parsing"; the oracle counts every distinct node the file builds (the `[]` shape markers and the literals too) and the source edges of those nodes. The reference says a week 1 return is a scalar ("ALU returns must be scalar"); the oracle reads that as: a rank-1 `assert` is `REJECTED` in week 1, and accepted from chapter 2 on (chapter 4's vectors, chapter 2's buffers). A STACK's elements are constants, as the syllabus says ("until week 4, inputs can only be STACK/CONST"), although the reference's table says only "ALU inputs". `add`, `mul`, `max` and `cmplt` take `bool` operands as well as `i32`, since the table writes `i32` explicitly only for `div`, `mod` and `shl`; their values are tinygrad's (OR, AND, OR, and false < true), and their bounds are normalized to `bool` (only zero `[0, 0]`, never zero `[1, 1]`, else `[0, 1]`). The reference's ASSERT row says dtype and shape "same"; the oracle gives an assert `void` and `()`, which no outcome can show. A call may pass more arguments than its body's highest used slot ("unused slots allowed"), and fewer is an error. Errors found while parsing (unknown op, missing or repeated attribute, undefined name, bad token) come before the node count; dtype, shape and bounds errors come after it.

## Conventions

The reference and the syllabus leave some things open. This course settles each one once, here, so that every chapter and every test agrees. Rules marked *[reference]* are the released week 1 reference's; the others are **interpretations**, and the reason for each is given.

### Literals

A `CONST`'s dtype is determined by its arg (the syllabus: "type determined by the arg"): a bool arg is `bool`, an integer arg is `i32`. *[reference]* A literal has its own dtype and nothing adapts it: `add 2 3` is `i32`, `xor true false` is `bool`, and `add 1 true` (an `i32` and a `bool`) is an error.

**From chapter 2: `f32` (course syntax).** A float arg is `f32`, and an integer literal next to a float adopts the float's dtype, because that is how tinygrad's "weak" literals behave. The parser picks each literal's arg from the typed value it must match:

| Literal | Must match an `i32` | Must match an `f32` | Matches nothing typed |
|---------|---------------------|---------------------|-----------------------|
| `3` | `3`, an `i32` | `3.0`, an `f32` | `i32`, or `f32` if a float literal is among the values it must match (`add 2 2.5`, `[1 2.5]`) |
| `2.5` | error | `2.5`, an `f32` | `f32` |
| `true` | error | error | `bool` |

"Must match" means: the other operand of a binary ALU op, the other branch of `where`, the target of a `store`, the actual value of an `assert`, the PARAM a `call` argument binds to, and the other elements of a stack. Indices are always `i32`. From chapter 4, an `expand` of a literal written inline, `(expand 1 4)`, is matched like the literal: next to an `f32` vector it is `[1.0 1.0 1.0 1.0]`.

A literal on its own line (`%a = 3`) is typed there, by the last column, so `%a` is `i32`. A float literal's value is rounded to the nearest `f32` when parsed (`0.1` becomes `0.100000001490116…`).

So from chapter 2, `add %x 1` works whether `%x` is `i32` or `f32`, `add 2 3` is `i32`, and `add 2 2.5` is `f32`. Because the dtype lives in the arg, an `i32` 3 and an `f32` 3.0 are different UOps, and hash-consing stays correct. *Why:* tinygrad gets the same behavior from "weak" literal dtypes (`tinygrad/dtype.py`), which the syllabus's four dtypes do not include; the draft course page relies on it ("promote i32 to f32" for `[42 27]` next to an `f32` value).

### Mixing dtypes

Two typed operands of different dtypes are an error: write a `cast`. `add (cast %i dtype=f32) %f` is fine; `add %i %f` is not. *Why:* tinygrad's op spec rejects it (`tinygrad/uop/spec.py`); its front end inserts the casts.

### Arithmetic

Your interpreter and the code you generate must agree bit for bit, so the edge cases are fixed here. *[reference]* rows come from the released week 1 reference.

| Case | Rule | Why |
|------|------|-----|
| `i32` overflow | wraps (two's complement) *[reference]* | tinygrad's constant folding wraps; C needs `-fwrapv` to match |
| `div`, `mod` | **floor** division and modulo, like Python: `div -7 2` is `-4`, `mod -7 2` is `1` *[reference]* | tinygrad's DIV/MOD are floor; its TRUNCDIV/TRUNCMOD are C's `/` and `%` |
| `div x 0`, `mod x 0` | `-1`, and `x`: never an error *[reference]* | the formula `x − y·⌊x/y⌋` with `⌊x/0⌋ = −1` gives `x` |
| `div -2147483648 -1` | `-2147483648`: the quotient 2147483648 wraps | the reference says values wrap on overflow and does not spell this case out |
| `shl a b` | `a × 2^k` wrapped, with `k = b mod 32` (floor mod): any `b`, also negative `a` *[reference]* | C makes left shifts of negative values, and shifts by ≥ 32, undefined, so render them on unsigned values, with `b & 31` |
| `cast` to `bool` | `x != 0` | tinygrad rewrites it this way |
| `cast` from `bool` | `false` is 0, `true` is 1 | C's conversion |
| `xor` | bitwise; on `bool`, logical | |
| `cmplt` | `x < y`, both operands the same dtype *[reference]*; `bool` result; `false < true` | |
| `add`, `mul`, `max` on `bool` | or, and, or (the result is `true` or `false`) | tinygrad's `bool` arithmetic; the reference gives no values |
| `where` | the second operand if the condition is true, else the third | |
| ALU ops on rank-1 values (chapter 4) | element by element, each element by the rules above | the syllabus: "ALU can be rank 1 now" |
| `reduce` (chapter 4) | starts from the identity (`add`: 0; `mul`: 1; `max`: −2147483648 for `i32`, `-inf` for `f32`) and combines the elements in index order, each step by the rules above | tinygrad's `lower_reduce`; `f32` addition is not associative, so the order is part of the result |

**From chapter 2: `f32` (course syntax).**

| Case | Rule | Why |
|------|------|-----|
| `f32` results | rounded to the nearest `f32` (ties to even) after every op | IEEE 754 single precision; C's `float` gives it when `FLT_EVAL_METHOD` is 0 and contraction is off (`-ffp-contract=off`, no `-ffast-math`), otherwise `a * b + c` may fuse into one rounding |
| `cast` `i32` → `f32` | nearest `f32`, ties to even | the usual C behavior |
| `cast` `f32` → `i32` | truncates toward zero | C's conversion |
| `recip` | `f32` only (`cast` an `i32` first); `recip 0.0` is `inf`, `recip -0.0` is `-inf` | tinygrad's op spec rejects `recip` on ints |
| Undefined: tests never do these, not even in the branch a `where` does not pick | `max` with a NaN, or of `0.0` and `-0.0`; `cast` `f32` → `i32` of NaN, ±inf or out-of-range values | C leaves them undefined, or C and Python disagree |

With only `i32` and `bool`, no week 1 program does anything undefined: every op has a value for every input.

### Bounds

`bounds` is an interval `[vmin, vmax]` for `i32` and `bool` values (`false` = 0, `true` = 1), both ends included. `f32` values have no bounds. Validation depends on bounds, so every compiler must compute exactly these, no tighter and no looser:

| Node | Bounds of `a op b` (a in `[a0, a1]`, b in `[b0, b1]`) |
|------|------------------------------------------------------|
| All sources exact (`vmin = vmax`) | Exact: the op applied to those values |
| `CONST` | Its value |
| `PARAM` | Its limits `[l, h]` if it has them, else the dtype's full range (`bool`: `[0, 1]`) *[reference]* |
| `STACK` | Smallest `vmin` to largest `vmax` of its elements |
| `INDEX` | The indexed value's bounds |
| `CALL` | The body's bounds (each argument's bounds must fit the PARAM's limits, [Validation](#validation)) |
| `RANGE` (chapter 3) | `[0, end − 1]`; the end is a constant ≥ 1 |
| `AFTER` (chapter 2) | The value's bounds |
| `LOAD` (chapter 2) | The dtype's full range |
| `EXPAND` (chapter 4) | The source's bounds |
| `REDUCE`, `STAGE` (chapter 4) | The dtype's full range: a STAGE is read back from memory when compiled |
| `ADD` | `[a0 + b0, a1 + b1]` (a `bool` result of `ADD`, `MUL` or `MAX` is normalized: only zero `[0, 0]`, never zero `[1, 1]`, else `[0, 1]`) |
| `MUL` | Smallest to largest of the four products of ends |
| `MAX` | `[max(a0, b0), max(a1, b1)]` |
| `DIV` by b with exact bounds c | Smallest to largest of `a0 div c` and `a1 div c` (c = 0: `[−1, −1]`); the full range if b is not exact *[reference]* |
| `MOD` by b not exact | The full range *[reference]* |
| `MOD` by b with exact bounds c = 0 | `[a0, a1]`, the bounds of a *[reference]* |
| `MOD` by b with exact bounds c ≠ 0 | If `a0 div c = a1 div c`: smallest to largest of `a0 mod c` and `a1 mod c`. Else `[0, c − 1]` for c > 0, `[c + 1, 0]` for c < 0 *[reference]* |
| `SHL` by b in `[b0, b1]` | Smallest to largest of `a0 × 2^k` and `a1 × 2^k`, over every `k = y mod 32` for y in `[b0, b1]` (all of 0 to 31 when `b1 − b0 ≥ 31`) *[reference]* |
| `CMPLT` (`i32` or `bool` operands) | `[1, 1]` if `a1 < b0`; `[0, 0]` if `a0 ≥ b1`; else `[0, 1]` |
| `WHERE c x y` | `x`'s if c is `[1, 1]`; `y`'s if c is `[0, 0]`; else smallest to largest of both |
| `CAST` to the source's own dtype, and `bool` → `i32` | The source's bounds |
| `CAST` `i32` → `bool` | `[0, 0]` if the source is `[0, 0]`; `[1, 1]` if 0 is outside the source's bounds; else `[0, 1]` |
| Anything else | The dtype's full range |

An `i32` result whose interval leaves the `i32` range widens to the full `i32` range *[reference]*. *Why:* the spec types bounds as `tuple[int, int]`. The rules are tinygrad's (`tinygrad/uop/ops.py`, `_min_max`), trimmed to the course's ops, except STAGE: tinygrad passes its source's bounds through, and the course widens them because a staged value is read back from memory (chapter 4). tinygrad's bounds assume signed overflow never happens; because this course defines overflow to wrap, it must widen.

### Cost

`cost` is the work a graph does, **counting each node once**. A node's own cost:

| Node | Cost |
|------|------|
| `CONST`, `PARAM`, `ASSERT` | 0 |
| `INDEX`, the empty stack `[]` | 1 |
| `ADD`, `MUL`, `MAX`, `XOR`, `SHL`, `DIV`, `MOD`, `CMPLT`, `WHERE`, `CAST` | N, the number of elements of the result (1 for a scalar) |
| `STACK` | N, the number of elements of the stack |
| `CALL` | 1 + C(f), where C(f) is the cost of the body, computed the same way |

The cost of a node is the sum of the own costs of every distinct node it reaches. A CALL's arguments are followed, but its body is not: the body is charged once per call, as C(f). The reference's example, for `%a = add 2 4` and `%b = add 3 3`:

| Product | Value | Cost | Why |
|---------|-------|------|-----|
| `mul %a %a` | 36 | 2 | the `add` is shared, so it is counted once |
| `mul %a %b` | 36 | 3 | two different `add`s |

The program's **static cost** is the cost of its root. A bounded program can still be expensive: a function that calls the one below it twice doubles its cost at every level, which is why 1,000,000 is a limit ([Test files and outcomes](#test-files-and-outcomes)). The reference gives no costs for the ops of chapters 2–4, so the oracle checks the limits only with `--week 1`.

> **Interpretation.** The `[]` that gives a PARAM its shape is a node, and the reference's table gives it cost 1; a PARAM's limits `[l h]` are a stack of two, so they cost 2. A PARAM's shape source is `[]` in week 1: `param [3]` is rejected. A body that has PARAMs reaches one `[]`, shared by all of them, so it pays that 1 once: the body of `add %x %x` costs 2, not 1. The reference does not say whether C(f) counts it; the oracle does, because the sum is over every node reached.

### Validation

Programs are checked as written, before any rewriting. Every line is checked (its op, args, dtypes, shapes and bounds), and every line must be reachable from the root *[reference]*, so there is no valid line to ignore. A program has exactly one `assert` line, its last. A check that uses bounds passes only if the bounds of the program as written prove it: an `INDEX` is in range (from chapter 2, loads and stores too), and each argument of a `CALL` fits the limits of the PARAM it binds *[reference]*. *Why:* a compiler that rejects programs only after optimizing would accept or reject the same program depending on which rules it implements.

### Evaluation

A node is computed once for each combination of values of the loops (RANGEs) it depends on, and of every loop enclosing one of those. Loop `o` encloses loop `k` when `o` is still open where `k` ends: `o` is in the `ranges` of `k`'s END (and, transitively, anything enclosing `o`). So a node that uses only `k` still runs once per value of `o` and `k`. A node that depends on no loop is computed once, before the loops, even if a node inside a loop uses it. Chapters 1 and 2 have no loops, so there every node is computed once and, because loads and stores are fully ordered, any topological order gives the same result. *Why:* this is what tinygrad does: its linearizer makes each inner loop's bound depend on the enclosing RANGE, so everything inside the inner loop depends on the outer one too, and then places each node at the depth of its loops (`tinygrad/codegen/late/linearizer.py`). Loop-invariant code is hoisted for free.

### Programs and ASSERT

- **The root.** A test program has exactly one `assert`, on its last line, which is the root. Every node is reachable from it ([Validation](#validation)); UOps form a graph, not a list of statements.
- **`assert actual expected`.** Two sources of the same dtype and shape. The expected value is a literal or a stack of literals *[reference]*. It passes when every element is numerically equal (`-0.0` equals `0.0`; NaN equals nothing). In week 1 the actual value is a scalar.
- **Memory (from chapter 2).** When `actual` is a buffer (`after %buf %done`), ASSERT compares the buffer's contents.

*Why:* the reference and the draft course page write one assert per example ("Each assert pairs a result with its expected value"). Exact comparison is enough while tests use small integers and halves, which `f32` represents exactly.

### Slots

`slot=` numbers things of one kind: the arguments of a CALL (PARAM; a call may leave a slot unused, but a body has one PARAM node per used slot), the buffers of a program (BUFFER, ALLOC), and the loops of a program (RANGE). A buffer and a range may both be `slot=0`. *Why:* tinygrad's ParamArg and RANGE each carry their own slot.

## Ops by chapter

Each chapter introduces the ops of one syllabus week and defines them; this table is the index.

| Chapter | Op | Srcs | Args | Details |
|------|----|------|------|---------|
| 1 | `const` | none; written as a literal | the value | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `param` | shape `[]`, then optional limits `[l h]` | `slot` `dtype` `addrspace=ALU` | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `call` | body, then one value per param | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `stack` | values of one shape; written `[a b c]` or `stack a b c` | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `index` | value, then one index per axis to pop | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `cast` | value | `dtype` | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `add` `mul` `max` `xor` | a, b | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `cmplt` | a, b | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `shl` `div` `mod` | a, b (`i32`) | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `where` | condition, then-value, else-value | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 1 | `assert` | actual, expected | | [1](01-uops-and-rewrites/README.md#ops-introduced) |
| 2 | `recip` | value (`f32`) | | [2](02-memory-and-shape/README.md#ops-introduced) |
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
