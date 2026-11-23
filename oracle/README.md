# UIR oracle (chapters 1–4)

A reference interpreter for UIR programs of chapters 1–4. It decides whether a test program is valid and whether its assert holds, with the outcomes, limits and rules of the course's released week 1 reference. It is slow and simple on purpose: it is a reference, not a compiler. It does no rewriting, no rendering and no optimisation.

## Running it

```sh
python3 -I oracle/uir.py [--week N] FILE.uir [FILE.uir ...]   # one line per file; exit status 1 unless all MATCH
python3 -I oracle/uir.py --week 1 FILE.uir                    # exactly the week 1 reference
python3 -I oracle/uir.py --lowered FILE.uir                   # also REJECTED if rangeify left anything to lower (chapter 4)
python3 -I oracle/test_oracle.py                              # the oracle's own tests
```

**`--week N`** (default 4) picks what a file may use. Week 1 is the released reference, plus the interpretations [uir.md](../uir.md#test-files-and-outcomes) lists: the flat grammar of [uir.md](../uir.md#lines) (no nested `(op ...)`, no float literals, one-token attributes), dtypes `i32` and `bool`, the week 1 ops, scalar parameters, calls and asserts, and the limits below. From week 2 on, the oracle also accepts the *course syntax* chapters 2–4 use (nested ops, `f32` and `recip`, rank-1 parameters, calls and asserts), with the ops introduced up to that week. The limits and the static cost are checked only with `--week 1`, because the reference gives no costs for later ops.

Each file prints exactly one line on stdout, `<OUTCOME> <file>`, as the reference's `./compile` does, and the reason on stderr:

- `MATCH`: the program is valid and its assert holds.
- `MISMATCH`: a valid program whose assert does not hold (stderr: `file: line N: got X, expected Y`).
- `REJECTED`: an invalid program (stderr: `file:line: kind: reason`). `kind` is one of `parse`, `op`, `arg`, `dtype`, `shape`, `rank`, `stack`, `bounds`, `addrspace`, `order`, `call`, `range`, `root`, `undefined` (an `f32` operation or a memory read with no defined value) and, with `--lowered`, `lowered` (a REDUCE, EXPAND, STAGE or rank-1 ALU op is left). Two more kinds are not about the program: `file` (it cannot be read) and `limit` (the graph is too deep for Python's recursion).
- `OVERBUDGET` (`--week 1`): a limit is hit, kind `budget`: more than 4096 bytes before parsing; 100 or more nodes, or 300 or more source edges, after parsing; or a static cost of 1,000,000 or more after validation. The checks run in that order, and a file that hits one never runs.

Python 3 standard library only (tested with 3.12.3). `test_oracle.py` runs every chapter's `examples/*.uir` at that chapter's week, and `tests/valid/*.uir` (week 4), which must MATCH. It runs `tests/invalid/*.uir` (week 4), which must end as their `# expect: <kind>` or `# expect: <kind>: <part of the message>` line says; the kind `fail` means a valid program whose assert must fail, and `budget` an OVERBUDGET. And it runs `tests/week1/*.uir` at week 1: those are named like a student's tests, by outcome (no prefix, `mismatch_`, `rejected_`, `overbudget_`), and the test checks that each ends as its name says. They are also good extra tests for your own compiler.

## How it works

**Parse and check.** The parser follows tinygrad's `uop/uir.py` grammar. It builds hash-consed `UOp(op, src, arg)` nodes one line at a time. The first time a node is built, it computes the node's properties from its sources: `dtype`, `shape`, addrspace, `bounds`, open `ranges`, ended ranges and free PARAMs. Then it checks the rules for its op, so an error points at the line that first wrote the node. Every line is checked this way (uir.md, Validation). Literals are typed as they are parsed (uir.md, Literals). With `--week 1`, the file is first parsed once without any checks, only to count nodes and edges for the limits; then it is parsed and checked.

After the last line come the whole-program checks: the root is the only assert, every line is reachable from it (call bodies and unused arguments count), there are no free PARAMs and no open ranges, each RANGE is ended once, slots are unique, and loads and stores are fully ordered. A CALL body gets the same checks when its CALL is built.

**Evaluate** (uir.md, Evaluation). A `Frame` is one activation: the program, or one CALL of a body. It holds the PARAM values and a memo. Evaluation is demand-driven, sources first.

- **Loops nest.** Loop `o` encloses loop `k` when `k`'s END uses `o` (`o` is open at that END), and nesting is transitive. This is how tinygrad's CFGContext nests loops: an inner RANGE's bound is made to depend on the outer RANGE. The frame computes these enclosing loops once, from the END structure.
- **Memo key.** A node is evaluated once for each combination of values of the loops in its `ranges` and of every loop enclosing them. That combination is part of the memo key.
- **END(effect, r)** runs `effect` for `r = 0 … N−1`, in order.
- **Loop-invariant nodes.** A node that uses no loop is evaluated once, before the loops, even if a node inside a loop uses it. For example, a gemm's accumulator init uses only `(i, j)`, so it runs once per `(i, j)`, before the `k` loop reads it through `after %C %init %k`. Likewise, a LOAD that does not use `k` reads memory once, before the `k` loop (`tests/valid/hoisted_load.uir`).
- **Nodes in an inner loop.** A node that uses only an inner loop `k` still runs once per value of the outer loop too (`tests/valid/enclosing_loops.uir`).
- `AFTER(value, deps...)` evaluates its deps, then returns the value.
- Memory is a Python list per BUFFER or ALLOC node. It is created when the node is first evaluated in a frame. Each CALL gets its own frame, and so its own ALLOCs. An address (`INDEX` or `SHRINK` of memory) is a view into that list.

In chapters 1 and 2 there are no loops, and the ordering check makes sure every load/store pair on one buffer is ordered by the graph. So any topological order gives the same result. In chapter 3, the result is the one defined by the rule above.

## Decisions not in uir.md

These are choices that uir.md, chapter 1 and the research notes leave open. Chapters 2 and 3 should state them, or the oracle should change.

- **Inline literals.** Only literals written inline (a literal token, or `[...]`) take the dtype they must match. A `%name` bound to a literal is already typed. An inline stack converted to `f32` converts all its elements.
- **INDEX** takes exactly one index, because shapes are at most rank 1. The index is a rank-0 `i32` ALU value. On memory, INDEX gives a rank-0 address. On a value (a stack, a rank-1 PARAM or LOAD, or from chapter 4 any rank-1 value), it gives the element.
- **The all-sources-exact bounds row** applies to ALU ops only. If the op's result is undefined on those values (only `f32` ops, such as `max` with a NaN or a `cast` of NaN), the bounds are the dtype's full range, and running the program reports it. (`div 1 0` is `-1`, never an error.)
- **BUFFER and ALLOC are both GLOBAL** and start undefined. Chapters 1–4 have no way to load input data, so tests write their inputs with STOREs first. Reading an element that was never stored is `undefined`.
- **SHRINK(buffer, offset, size)** takes rank-1 memory only. The offset is a rank-0 `i32` and may be symbolic. The size is a constant ≥ 1. The window `[offset.vmin, offset.vmax + size − 1]` must lie in `[0, n − 1]`.
- **LOAD of a rank-1 address** (a whole buffer or a SHRINK) gives a rank-1 ALU value. It can be indexed, stored or asserted, but until chapter 4 no ALU op can use it.
- **STORE.** The value is an ALU value (not memory, not an effect), and its shape equals the target's. A STORE has dtype `void` and shape `()`.
- **AFTER's deps** are effects or RANGEs. An effect is `void`: a STORE, an END, or an AFTER of an effect. A RANGE dep is tinygrad's "inside loop r" idiom. AFTER's value may itself be an effect, which is how several stores become one effect for an END: `end (after %s2 %s1) %i`.
- **END(effect, r).** The effect must be `void` and must use `r`. An effect that does not use `r` is loop-invariant, so it would run once (uir.md, Evaluation), while the END reads as "N times". The oracle rejects that ambiguity.
- **Enclosing loops.** "`o` encloses `k`" means `k`'s END has `o` open (tinygrad's CFGContext rule). It does not mean "`k` is in the ended ranges of `o`'s effect". That reading would also count a sibling loop that `o`'s effect reaches through AFTER (`after %a %done_k`), which runs before loop `o` and not inside it.
- **One END per RANGE** per program or call body. A second END would be a second loop over the same RANGE, and the oracle could not order the two loops' stores. Group the effects with AFTER instead.
- **A RANGE used after its END** is an error: a node whose sources have `r` both open and ended. Each loop needs its own RANGE.
- **A RANGE belongs to one scope.** A RANGE reached both inside a CALL body and in the scope around that CALL is an error. One RANGE inside a body that is called twice, or inside two different bodies, is fine: each call is its own activation. A compiler that inlines calls must give inlined RANGEs fresh slots, as it does for ALLOCs.
- **The ordering check** has no alias analysis. Any LOAD and STORE of the same buffer, at any index, form a pair. A pair is ordered if either one reaches the other through `src` edges. ASSERT is not counted: as the root, it comes after everything.
- **Slots.** BUFFER and ALLOC share one slot numbering. Buffer slots and RANGE slots are each unique across the whole program, call bodies included. Building the same node again yields the same UOp (hash-consing), so it is not a reuse.
- **CALL.** A call passes at least (highest PARAM slot + 1) arguments, so an unused slot below the highest still takes one, and extra trailing arguments (unused slots) are allowed. Every argument is an ALU value; memory and effects cannot be passed. The body is an ALU value with no open ranges, and it may contain its own loops and ALLOCs. Two different PARAMs with one slot in one body are an error. A CALL whose arguments use a range is evaluated once per iteration.
- **ASSERT** reads memory contents when either side is memory, and every element it reads must be defined.
- **Undefined behaviour** (uir.md, Arithmetic) is reported as `REJECTED … undefined` when evaluation reaches it. This covers both branches of a WHERE, because both are evaluated. Constants alone never make a program invalid. With `i32` and `bool` there is none: `div`, `mod` and `shl` are defined for every input ([uir.md](../uir.md#arithmetic)), and only `f32` (`max` with a NaN, casts of NaN or infinities) and memory reads with no stored value remain.
- **Week 1 reference rules** that the oracle checks and a student's compiler must too: the expected value of an assert is a literal or a stack of literals (a node that is a CONST or a STACK of CONSTs, however written); `param` has the attribute `addrspace=ALU` (all weeks) and, in week 1, the scalar shape `[]`; a PARAM's optional second source is `[l h]`, two literals of its dtype with `l ≤ h`, and becomes its bounds; every argument of a CALL has bounds inside the PARAM's limits; a `const` op is never written; every line must be reachable from the assert; in week 1 a call's arguments and result and an assert's actual value are scalar.
- **Counting for the limits.** Nodes are the distinct hash-consed nodes the file builds (literals and `[]` shape markers included); edges are the sum of their source counts. Cost is [uir.md's](../uir.md#cost): each distinct node once, a CALL charged `1 + C(body)`.
- **`-2147483648 div -1`** wraps to `-2147483648`; the reference does not spell it out.
- **STACK inputs** are constants through chapter 4: week 1 says "until week 4", week 5 says "STACK supports arbitrary inputs", and the course follows week 5.
- **Rank-1 ALU ops (chapter 4)** need every source to have the same shape; nothing is broadcast implicitly. Indices and SHRINK offsets stay rank 0.
- **EXPAND(value, shape)** takes a value (not memory, not an effect) and a shape source written like a BUFFER's, `[]` or a length. It adds its axes on the left; its source is rank 0 until week 5, so the result is at most rank 1. An inline `(expand <literal> …)` takes the dtype it must match, like its literal; a named one is typed where it is written.
- **REDUCE(value) op= pop=** takes a value whose dtype its op takes (`add`, `mul`, `max` on `i32` and `f32`), and `0 ≤ pop ≤ rank`. It folds from the identity in index order; each step is checked for undefined behaviour like the ALU op. Its bounds are the dtype's full range.
- **STAGE(value)** is the identity on values. It only matters to a compiler. Its bounds are the dtype's full range, like a value loaded from memory, which is what it becomes when compiled; so a staged value cannot be proven in range as an index.
- **Whole values (chapter 4).** A rank-1 LOAD reads the whole address at its place in the order, and a rank-1 STORE writes the whole value. So a store whose value loads from its own target sees the old contents (`04-rangeify/examples/shift.uir`).
- **Tokens.** Comments, `%name =`, `key=value`, nested `(op ...)` and `[stacks]` follow tinygrad's `uir.py`. The oracle rejects scoped blocks `{}` (chapter 6), backtick objects and `invalid`. Every key an op takes is required. Unknown keys and repeated keys are errors.
