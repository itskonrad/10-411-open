# UIR oracle (chapters 1–3)

A reference interpreter for UIR programs of chapters 1–3. It decides whether a test program is valid and whether its assert holds. It is slow and simple on purpose: it is a reference, not a compiler. It does no rewriting, no rendering and no optimisation, and does not compute `cost`.

## Running it

```sh
python3 -I oracle/uir.py FILE.uir [FILE.uir ...]   # one line per file, exit status 1 unless all pass
python3 -I oracle/test_oracle.py                   # the oracle's own tests
```

Each file prints one of:

- `PASS file`
- `FAIL file: line N: got X, expected Y`: a valid program whose assert does not hold.
- `ERROR file:line: kind: reason`: an invalid program, or one that does something undefined. `kind` is one of `parse`, `op`, `arg`, `dtype`, `shape`, `rank`, `stack`, `bounds`, `addrspace`, `order`, `call`, `range`, `root` and `undefined`. Two more kinds are not about the program: `file` (it cannot be read) and `limit` (the graph is too deep for Python's recursion).

Python 3 standard library only (tested with 3.12.3). `test_oracle.py` runs every chapter's `examples/*.uir` and `tests/valid/*.uir`, which must pass. It also runs `tests/invalid/*.uir`, which must be rejected. Each invalid test starts with `# expect: <kind>` or `# expect: <kind>: <part of the message>`. The kind `fail` means a valid program whose assert must fail.

## How it works

**Parse and check.** The parser follows tinygrad's `uop/uir.py` grammar. It builds hash-consed `UOp(op, src, arg)` nodes one line at a time. The first time a node is built, it computes the node's properties from its sources: `dtype`, `shape`, addrspace, `bounds`, open `ranges`, ended ranges and free PARAMs. Then it checks the rules for its op, so an error points at the line that first wrote the node. Every line is checked this way, whether or not the root reaches it (uir.md, Validation). Literals are typed as they are parsed (uir.md, Literals).

After the last line come the whole-program checks, on the graph the root reaches: the root is the only assert, there are no free PARAMs and no open ranges, each RANGE is ended once, slots are unique, and loads and stores are fully ordered. A CALL body gets the same checks when its CALL is built.

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
- **INDEX** takes exactly one index, because shapes are at most rank 1. The index is a rank-0 `i32` ALU value. On memory, INDEX gives a rank-0 address. On a value (a stack, or a rank-1 PARAM or LOAD), it gives the element.
- **The all-sources-exact bounds row** applies to ALU ops only. If the op is undefined on those values (`div 1 0`), the bounds are the dtype's full range, and running the program reports the error.
- **BUFFER and ALLOC are both GLOBAL** and start undefined. Chapters 1–3 have no way to load input data, so tests write their inputs with STOREs first. Reading an element that was never stored is `undefined`.
- **SHRINK(buffer, offset, size)** takes rank-1 memory only. The offset is a rank-0 `i32` and may be symbolic. The size is a constant ≥ 1. The window `[offset.vmin, offset.vmax + size − 1]` must lie in `[0, n − 1]`.
- **LOAD of a rank-1 address** (a whole buffer or a SHRINK) gives a rank-1 ALU value. It can be indexed, stored or asserted, but no ALU op can use it.
- **STORE.** The value is an ALU value (not memory, not an effect), and its shape equals the target's. A STORE has dtype `void` and shape `()`.
- **AFTER's deps** are effects or RANGEs. An effect is `void`: a STORE, an END, or an AFTER of an effect. A RANGE dep is tinygrad's "inside loop r" idiom. AFTER's value may itself be an effect, which is how several stores become one effect for an END: `end (after %s2 %s1) %i`.
- **END(effect, r).** The effect must be `void` and must use `r`. An effect that does not use `r` is loop-invariant, so it would run once (uir.md, Evaluation), while the END reads as "N times". The oracle rejects that ambiguity.
- **Enclosing loops.** "`o` encloses `k`" means `k`'s END has `o` open (tinygrad's CFGContext rule). It does not mean "`k` is in the ended ranges of `o`'s effect". That reading would also count a sibling loop that `o`'s effect reaches through AFTER (`after %a %done_k`), which runs before loop `o` and not inside it.
- **One END per RANGE** per program or call body. A second END would be a second loop over the same RANGE, and the oracle could not order the two loops' stores. Group the effects with AFTER instead.
- **A RANGE used after its END** is an error: a node whose sources have `r` both open and ended. Each loop needs its own RANGE.
- **A RANGE belongs to one scope.** A RANGE reached both inside a CALL body and in the scope around that CALL is an error. One RANGE inside a body that is called twice, or inside two different bodies, is fine: each call is its own activation. A compiler that inlines calls must give inlined RANGEs fresh slots, as it does for ALLOCs.
- **The ordering check** has no alias analysis. Any LOAD and STORE of the same buffer, at any index, form a pair. A pair is ordered if either one reaches the other through `src` edges. ASSERT is not counted: as the root, it comes after everything.
- **Slots.** BUFFER and ALLOC share one slot numbering. Buffer slots and RANGE slots are each unique across the whole program, call bodies included. Building the same node again yields the same UOp (hash-consing), so it is not a reuse.
- **CALL.** A call passes exactly (highest PARAM slot + 1) arguments, so an unused slot below the highest still takes one. Every argument is an ALU value; memory and effects cannot be passed. The body is an ALU value with no open ranges, and it may contain its own loops and ALLOCs. Two different PARAMs with one slot in one body are an error. A CALL whose arguments use a range is evaluated once per iteration.
- **ASSERT** reads memory contents when either side is memory, and every element it reads must be defined.
- **Undefined behaviour** (uir.md, Arithmetic) is reported as `ERROR … undefined` when evaluation reaches it. This covers both branches of a WHERE, because both are evaluated. Constants alone never make a program invalid.
- **Tokens.** Comments, `%name =`, `key=value`, nested `(op ...)` and `[stacks]` follow tinygrad's `uir.py`. The oracle rejects scoped blocks `{}` (chapter 6), backtick objects and `invalid`. Every key an op takes is required. Unknown keys and repeated keys are errors.
