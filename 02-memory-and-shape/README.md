# Chapter 2: Memory & Shape

> Students write a renderer and a runtime capable of compiling and executing C programs.
>
> Recursive properties introduced:
> ```
> addrspace(GLOBAL,ALU)
> accesses:dict[UOp, tuple[UOp, ...]] <-- a list of UOps that access a buffer
> storage_base:UOp
> ```
>
> Ops introduced:
> ```
> BUFFER(ParamArg) -- global persistent buffer (never in call)
> ALLOC(ParamArg) -- call scope storage, example "float a[10]"
> SHRINK(offset, shape) -- offset can be symbolic, shape must be integer
> LOAD/STORE -- load has 1 src, store has 2, we load/store from/to GLOBAL buffer
> AFTER -- AFTER(buf, <store>)
> ```
>
> This can render (loopless) C functions that act on memory and immediates. Loads and stores must be fully ordered for programs to be valid. Loads and stores are bounds checked to never be out of range.
>
> Lectures:
> * wed - toposort and rendering, C refresher
> * fri - memory management and runtime
> * mon - type systems for shape, dtype, and addrspace
>
> — the syllabus, week 2

**Builds on:** [Chapter 1](../01-uops-and-rewrites/README.md). **By the end you can:** compile a UIR program with memory to a C function, load it into your compiler's process, run it, and check its result.

## Contents

- [Lectures](#lectures)
  - [Lesson 1: toposort and rendering, C refresher](#lesson-1-toposort-and-rendering-c-refresher)
  - [Lesson 2: memory management and runtime](#lesson-2-memory-management-and-runtime)
  - [Lesson 3: type systems for shape, dtype, and addrspace](#lesson-3-type-systems-for-shape-dtype-and-addrspace)
- [Ops introduced](#ops-introduced)
- [Properties introduced](#properties-introduced)
- [Assignment](#assignment)
- [Example programs](#example-programs)
- [Spec notes](#spec-notes)
- [Quiz](#quiz)
- [Sources](#sources)

## Lectures

### Lesson 1: toposort and rendering, C refresher

**Memory enters the graph.** Chapter 1's programs were pure values. This chapter adds memory: a `BUFFER` is an array that outlives the program, `STORE` writes it, `LOAD` reads it, and `AFTER` says what must happen first. The smallest example, from the draft course page:

```text
%buf   = buffer [] slot=0 dtype=i32
%write = store %buf 7
%ready = after %buf %write
%value = load %ready
%test  = assert %value 7
```

`after %buf %write` is the buffer itself, with a promise attached: anything that uses `%ready` happens after `%write`. The load uses `%ready`, so it reads 7. There are still no statements. Order is just more edges in the graph.

**Rendering is a walk in topological order.** To emit C, list the nodes so that every node comes after its sources, using the `toposort` from [chapter 0](../00-prerequisites/README.md#lesson-3-graphs-substitution-and-intervals) ([Kahn 1962](#sources) gives another algorithm). Each node appears once, however many nodes use it: the toposort's `seen` set does that, so a shared subexpression is computed once. Any topological order is valid; Lesson 3 explains why.

Then emit one line per node. Most nodes become a C variable; a few become text that other lines use:

```python
C_EXPR = {"ADD": "{} + {}", "MUL": "{} * {}", "CMPLT": "{} < {}", "WHERE": "{} ? {} : {}"}

def render(order: list, ctype) -> str:
    names, lines = {}, []
    for n, u in enumerate(order):
        a = [names[s] for s in u.src]
        if u.op == "CONST":
            names[u] = repr(u.arg)           # i32 here; f32 and bool need the table below
        elif u.op == "STACK":
            names[u] = None                  # here only a BUFFER's shape source, []: not rendered
        elif u.op == "BUFFER":               # a pointer parameter; rank-0 memory is element 0
            names[u] = f"buf{u.arg}" if u.src[0].op == "CONST" else f"buf{u.arg}[0]"
        elif u.op == "INDEX":
            names[u] = f"{a[0]}[{a[1]}]"     # an lvalue that LOAD and STORE use
        elif u.op == "AFTER":
            names[u] = a[0]                  # ordering only: the toposort already placed it
        elif u.op == "STORE":
            names[u] = None                  # an effect: it has no value
            lines.append(f"{a[0]} = {a[1]};")
        else:
            names[u] = f"v{n}"
            expr = a[0] if u.op == "LOAD" else C_EXPR[u.op].format(*a)
            lines.append(f"{ctype(u)} v{n} = {expr};")
    return "\n".join(lines)
```

(A sketch: here a BUFFER's arg is just its slot, its source is its shape (`[]` or a length), memory is accessed through `INDEX` or is rank 0, and `ctype` maps a node to `int32_t`, `float` or `bool`. Rank-1 values and `f32` and `bool` constants need the table below.) Naming every value is the simple choice. It produces more lines than needed, but the C compiler removes the extra variables, and you never have to decide whether an expression may be duplicated.

Two kinds of node are statements rather than values: a `STORE` must appear exactly once and in the right place, and a `LOAD` must read memory at its position, not later. Topological order puts each after everything it depends on. Lesson 3 shows why that is enough.

For [examples/chained_stores.uir](examples/chained_stores.uir), which sets `b[0] = 1` and then `b[1] = b[0] + 1`, `render` produces the body of this function:

```c
#include <stdint.h>

void kernel(int32_t *buf0) {
    buf0[0] = 1;
    int32_t v9 = buf0[0];
    int32_t v10 = v9 + 1;
    buf0[1] = v10;
}
```

The syllabus calls this "loopless C functions that act on memory and immediates". Loops arrive in chapter 3.

**C refresher: exact translations.** The C you emit must compute exactly what your chapter-1 interpreter computes ([uir.md](../uir.md#arithmetic)). Most ops map directly; these need care:

| UIR | C |
|-----|---|
| `i32`, `f32`, `bool` | `int32_t`, `float`, `bool` (`<stdint.h>`, `<stdbool.h>`) |
| `add`, `mul` on `i32` | `a + b`, `a * b`, compiled with `-fwrapv` so they wrap |
| `div`, `mod`, `shl` | helper functions, below |
| `max` | `a < b ? b : a` |
| `recip` | `1.0f / a` |
| `cast` to `bool` | `a != 0` |
| `f32` constant | `repr(x) + "f"`, such as `0.5f`; `INFINITY` and `NAN` from `<math.h>` |
| `store %buf [10 20 30]` | `buf0[0] = 10; buf0[1] = 20; buf0[2] = 30;`: one statement per element, since there are no loops yet |
| `bool` constant | `true`, `false` |

```c
#include <assert.h>
#include <stdint.h>

static int32_t idiv(int32_t a, int32_t b) {  // floor division
    int32_t q = a / b;
    return (a % b != 0 && (a < 0) != (b < 0)) ? q - 1 : q;
}

static int32_t imod(int32_t a, int32_t b) {  // floor modulo: the result takes b's sign
    int32_t r = a % b;
    return (r != 0 && (r < 0) != (b < 0)) ? r + b : r;
}

static int32_t ishl(int32_t a, int32_t b) {  // shifting a negative int is undefined, so shift as unsigned
    return (int32_t)((uint32_t)a << b);
}

int main(void) {
    assert(idiv(-7, 2) == -4 && imod(-7, 2) == 1 && idiv(7, -2) == -4 && imod(7, -2) == -1);
    assert(idiv(-8, 2) == -4 && imod(-8, 2) == 0 && ishl(-1, 4) == -16);
    return 0;
}
```

Converting the shifted `uint32_t` back to `int32_t` is implementation-defined in C11 ([N1570](#sources) §6.3.1.3); GCC and Clang wrap, which is what you want. The `f32` constant rule works because the literal was already rounded to `f32` when parsed: `repr` prints a decimal that C reads back as exactly that `float`.

Compile with `-std=c11 -fwrapv -ffp-contract=off`. The last flag stops the compiler from fusing `a * b + c` into one fused multiply-add, which rounds once instead of twice and would disagree with your interpreter.

### Lesson 2: memory management and runtime

**Two kinds of memory.** The syllabus gives two:

- **`BUFFER`** is "global persistent": memory that exists before the program runs and after it ends. Your runtime allocates it and passes it in. In C, each buffer is a pointer parameter.
- **`ALLOC`** is "call scope storage, example `float a[10]`": scratch memory that lives for one call. In C, a local array declared in the function.

> **Interpretation.** The syllabus does not fix a calling convention. This chapter uses the simplest one: the function takes one pointer per BUFFER, in increasing slot order, and nothing else.

Both start with undefined contents. There is no way to pass input data in yet, so a test writes its inputs with `STORE` first, and reading an element that was never stored is an error (the interpreter reports it; C cannot). An ALLOC outside any call belongs to the program, which counts as one call.

> **Interpretation.** "Never in call" is read two ways at once: a `CALL` body cannot contain a `BUFFER`, and memory cannot be passed to or returned from a call. A call's arguments and body are values; scratch data lives in ALLOCs. The oracle enforces both.

**Scratch memory and inlining.** Two calls of one body are two separate scratch areas, but after hash-consing, the body's ALLOC is one UOp. So the inliner must give each inlined ALLOC a fresh slot, as tinygrad's does (`tinygrad/schedule/prepare.py`). See [examples/alloc_in_call.uir](examples/alloc_in_call.uir).

**Windows into memory.** `shrink %buf %offset %size` is the part of a rank-1 buffer starting at `offset`, `size` elements long. The offset may be an expression ("symbolic"); the size must be a constant, so the window's shape is known. In C a window is a pointer, `buf0 + offset`. See [examples/shrink_window.uir](examples/shrink_window.uir).

**The runtime.** A runtime turns rendered source into something you can call. The simplest one uses the system C compiler and the dynamic loader ([dlopen(3)](#sources); [CS:APP](#sources) ch. 7):

```python
import ctypes
import hashlib
import subprocess
from pathlib import Path

CFLAGS = ["-std=c11", "-O2", "-fwrapv", "-ffp-contract=off", "-shared", "-fPIC"]

def compile_c(src: str, cache: Path = Path("kernels")) -> ctypes.CDLL:
    # one file per source and flags: dlopen caches by path
    name = hashlib.sha256((" ".join(CFLAGS) + src).encode()).hexdigest()[:16]
    lib = cache / f"{name}.so"
    if not lib.exists():  # keep the cache out of /tmp: some systems forbid running code from it
        cache.mkdir(exist_ok=True)
        (cache / f"{name}.c").write_text(src)
        # shortcut: an interrupted build leaves a partial .so; compile to a temp name and rename if that matters
        subprocess.run(["cc", *CFLAGS, f"{name}.c", "-o", lib.name], cwd=cache, check=True)
    return ctypes.CDLL(str(lib.resolve()))
```

Naming the file after a hash of the source and flags does two jobs. It caches: a test suite compiles the same kernel many times, and the second time costs nothing. And it avoids a real bug: the loader caches libraries by path, so loading a new `kernel.so` over an old one can silently return the old code.

Calling the result needs memory for each BUFFER, sized from its shape and dtype. With `ctypes`, `buf0 = (ctypes.c_int32 * 2)()` allocates two zeroed `i32`s, and `compile_c(src).kernel(buf0)` runs the kernel and fills them: `[1, 2]` for `chained_stores.uir`. Other languages have the same three steps: write a file, run `cc`, and load it through the language's foreign function interface.

**Running a test.** The program's root is an `ASSERT`. It is simplest to render it into the function too: the function returns 1 if every element matches and 0 otherwise, and the runtime checks the return value. For `chained_stores.uir` the last line becomes `return buf0[0] == 1 && buf0[1] == 2;`, with the function returning `int` instead of `void`.

**Interpreting memory.** Rewriting alone cannot run a `STORE`. The simplest interpreter walks the graph in topological order with one array per BUFFER or ALLOC: `STORE` writes the array, `LOAD` reads it, `AFTER` passes its first source through, and each inlined call gets fresh ALLOCs. Reading an element no `STORE` wrote is an error. Because loads and stores are fully ordered (Lesson 3), any topological order gives the same answer. The [oracle](../oracle/README.md) works this way.

**Two implementations, one answer.** Keep your chapter-1 interpreter, extended to memory. Every test can now run twice: interpreted and compiled. When they disagree, one of them has a bug, and the program that shows it is a new test. This is *differential testing*, and it is the cheapest way to find semantic bugs in the renderer.

### Lesson 3: type systems for shape, dtype, and addrspace

**A type system rejects programs before they run.** Your chapter-1 checks were already one: rules over `dtype` and `shape` that every node must satisfy. This chapter adds `addrspace`, extends shape and dtype to memory, and adds two analyses over memory.

**Address spaces.** Every node is either memory or a value:

| `addrspace` | Nodes | Can be used by |
|-------------|-------|----------------|
| `GLOBAL` | `BUFFER`, `ALLOC`, and `INDEX`, `SHRINK`, `AFTER` of memory | `LOAD`, `STORE` (as the target), `INDEX`, `SHRINK`, `AFTER`, `ASSERT` |
| `ALU` | everything else, including `LOAD` | ALU ops, `STORE` (as the value), `INDEX`, `ASSERT` |

`LOAD` is the only way from memory to a value. So `add %buf 1` is a type error: write `add (load %buf) 1`. This keeps every memory access visible as a node, which is what makes the next two analyses possible.

> **Interpretation.** The syllabus gives the two address spaces but not their rules. These follow tinygrad, whose `LOAD` "brings things into the ALU" (`tinygrad/uop/ops.py`, `addrspace`). ALLOC is GLOBAL too: tinygrad describes it as "unbound global storage" (`tinygrad/uop/__init__.py`).

Shapes and dtypes extend naturally. `INDEX` on rank-1 memory gives a rank-0 address. A `SHRINK` window has shape `(size,)`. A `STORE`'s value has the same shape and dtype as its target; literals take the target's dtype, so `store %fb [1 2]` into an `f32` buffer stores `[1.0 2.0]`.

**`storage_base` and `accesses`.** To reason about memory, find which buffer each access touches. `storage_base` strips addresses back to the BUFFER or ALLOC they point into. `accesses` is a recursive property like the others: a node's accesses are its sources' accesses, plus itself if it is a LOAD or STORE, grouped by buffer. The program's accesses are the root's.

```python
import functools

def storage_base(u: UOp) -> UOp:
    while u.op in ("INDEX", "SHRINK", "AFTER"):
        u = u.src[0]
    return u

@functools.cache
def accesses(u: UOp) -> dict:  # buffer -> the LOADs and STOREs u depends on, u included
    out: dict = {}
    for s in u.src:
        for buf, acc in accesses(s).items():
            out[buf] = out.get(buf, frozenset()) | acc
    if u.op in ("LOAD", "STORE"):
        buf = storage_base(u.src[0])
        out[buf] = out.get(buf, frozenset()) | {u}
    return out
```

(The spec types the accesses as a tuple; a set is simpler here, since their order does not matter.)

**Fully ordered.** The syllabus: "Loads and stores must be fully ordered for programs to be valid." For each buffer, take every pair of accesses where at least one is a `STORE`. One of the two must depend on the other, directly or through other nodes:

```python
@functools.cache
def reach(u: UOp) -> frozenset:  # every node u depends on, directly or not
    return frozenset().union(*(reach(s) | {s} for s in u.src))

def check_ordered(acc: frozenset) -> None:  # the LOADs and STOREs of one buffer
    acc = list(acc)
    for i, a in enumerate(acc):
        for b in acc[i + 1:]:
            if "STORE" in (a.op, b.op) and a not in reach(b) and b not in reach(a):
                raise TypeError(f"{a.op} and {b.op} of one buffer are not ordered: use AFTER")
```

This rule is what makes rendering simple. Any topological order keeps every dependency, and the rule turns every order that matters into a dependency, so *every* topological order gives the same result. Your interpreter and your C agree without either needing to know about time. (This holds for programs without loops; chapter 3 adds one more rule, [when a node inside a loop runs](../uir.md#evaluation).) A program that loads `%buf` without waiting for the store is rejected; see [the oracle's test](../oracle/tests/invalid/unordered.uir).

The check is deliberately coarse: it treats two accesses to *different* elements of one buffer as a pair too. That rejects some programs that would be fine, but it needs no reasoning about indices. (Storing each node's full `reach` set is quadratic in memory; fine for tests, slow for big graphs.)

> **Interpretation.** Read literally, "fully ordered" could mean one total order over all memory accesses. This chapter orders only the pairs whose order can change a result: two accesses to one buffer, at least one a STORE. Two loads, or accesses to different buffers, may stay unordered.

**Bounds checks.** "Loads and stores are bounds checked to never be out of range." With [uir.md's bounds rules](../uir.md#bounds), an `INDEX` into memory of length `n` must have bounds inside `[0, n − 1]`, and a `SHRINK` window must have `offset.vmin ≥ 0` and `offset.vmax + size ≤ n`. As in chapter 1, the check runs on the program as written and must succeed from bounds alone. A symbolic offset is fine when its bounds prove the window fits: `shrink %buf (mod %v 3) 2`, where `%v` is any `i32` (a loaded value, say), has offset bounds `[0, 2]`, and `2 + 2 ≤ 4` for a buffer of 4.

## Ops introduced

| Op | Srcs | Arg | Shape | Dtype | addrspace | Meaning |
|----|------|-----|-------|-------|-----------|---------|
| `BUFFER` | shape: `[]` or `n` | `slot`, `dtype` | `()` or `(n,)` | `dtype` | `GLOBAL` | Global persistent memory: a pointer parameter |
| `ALLOC` | shape: `[]` or `n` | `slot`, `dtype` | `()` or `(n,)` | `dtype` | `GLOBAL` | Call-scope memory: a local array |
| `SHRINK` | rank-1 memory, offset (`i32`), size (constant ≥ 1) | none | `(size,)` | memory's | `GLOBAL` | A window into memory |
| `LOAD` | address | none | address's | address's | `ALU` | Read memory |
| `STORE` | address, value | none | `()` | `void` | `ALU` | Write memory (an effect) |
| `AFTER` | value, effects… | none | value's | value's | value's | The value, used only after the effects |

`INDEX` (chapter 1) now also applies to memory: `index %buf %i` is the address of element `i`. Rules your compiler checks, in addition to chapter 1's:

- **Address spaces** as in the table in Lesson 3: ALU ops take `ALU` sources; `LOAD` and `STORE` targets are `GLOBAL`.
- **STORE matches its target**: the value is an `ALU` value with the target's shape and dtype.
- **Rank-1 loads stay data.** Loading a whole rank-1 buffer or window gives a rank-1 value: it can be indexed, stored or asserted, but no ALU op can use it.
- **No BUFFER in a CALL body**, and a call's arguments and body are `ALU` values.
- **Slots.** BUFFER and ALLOC share one slot numbering, unique across the program including call bodies.
- **Fully ordered**: every load–store and store–store pair on one buffer is ordered by the graph.
- **In bounds**: every memory `INDEX` and `SHRINK` is proven in range by bounds.
- **AFTER waits for effects**: its sources after the first are `STORE`s or other effects (`void` values).
- **ASSERT reads defined memory**: every element it compares must have been stored. The interpreter reports this when it runs; the compiled C cannot.

## Properties introduced

| Property | Type | Rule |
|----------|------|------|
| `addrspace` | `GLOBAL` or `ALU` | `GLOBAL` for `BUFFER`, `ALLOC`, and `INDEX`/`SHRINK`/`AFTER` of `GLOBAL`; `ALU` otherwise |
| `storage_base` | UOp | Through `INDEX`, `SHRINK` and `AFTER` to the `BUFFER` or `ALLOC` |
| `accesses` | `dict[UOp, tuple[UOp, ...]]` | The sources' accesses merged, plus the node itself under its `storage_base` if it is a `LOAD` or `STORE` |

> **Interpretation.** tinygrad has `storage_base` but no `accesses`. The reading above is the one the syllabus's comment gives ("a list of UOps that access a buffer"), and the ordering check is what it is for.

## Assignment

Start by writing ten tests of your own in UIR (the syllabus asks for ten each week), and check them with the [oracle](../oracle/README.md).

1. **Check** the new rules above.
2. **Render** every valid program from chapters 1 and 2 to one C function: buffers become pointer parameters in increasing slot order, ALLOCs local arrays, the ASSERT a return value.
3. **Run** it: compile with `cc -std=c11 -O2 -fwrapv -ffp-contract=off -shared -fPIC`, load it, allocate each BUFFER from its shape and dtype (zeroed is fine; tests store before they load), call it, and report pass or fail.
4. **Keep your interpreter** working on memory too, and run every test both ways. They must agree.

Render the program after inlining calls (with fresh ALLOC slots), but without constant folding or symbolic rules, so the C really computes every op; the interpreter is the folding side of the comparison. Once both agree, you may fold before rendering in later chapters. The renderer must handle every chapter-1 op, using the helpers from Lesson 1.

Restrictions this chapter: memory and values are at most rank 1; ALU ops take rank-0 sources; there are no loops, so rank-1 stores render one statement per element.

## Example programs

All in [examples/](examples/). Each file's comments show the hand calculation. The [oracle](../oracle/README.md) passes all of them.

| File | Exercises |
|------|-----------|
| [store_load.uir](examples/store_load.uir) | The draft course page's example: `STORE`, `AFTER`, `LOAD` |
| [index_buffer.uir](examples/index_buffer.uir) | Storing a stack, loading one element |
| [chained_stores.uir](examples/chained_stores.uir) | A load and store that depend on an earlier store |
| [shrink_window.uir](examples/shrink_window.uir) | `SHRINK` as a window |
| [f32_buffer.uir](examples/f32_buffer.uir) | Literals typed by an `f32` target |
| [alloc_in_call.uir](examples/alloc_in_call.uir) | `ALLOC` scratch memory, one per call |

## Spec notes

> **Spec note.** The draft course page puts "render and execute C programs" in week 3; the syllabus puts the renderer and runtime in week 2. This chapter follows the syllabus.

> **Interpretation.** "SHRINK(offset, shape)" is written in UIR as `shrink memory offset size`, following tinygrad (`tinygrad/uop/ops.py`). Until chapter 5, SHRINK applies only to rank-1 memory (tinygrad's program spec allows it only on a buffer or an AFTER), so its offset and size are single numbers; the size is a constant ≥ 1.

> **Interpretation.** A `STORE` has dtype `void` and shape `()`: it is an effect, not a value. tinygrad gives STORE its target's shape; nothing in this course uses a STORE's shape.

> **Interpretation.** `AFTER(buf, <store>)` takes one value and any number of effects, as tinygrad's AFTER does, so one access can wait for several stores. Its first source may also be an `ALU` value or an effect, as tinygrad's AFTER spec allows (`tinygrad/uop/spec.py`). Chapter 3 also allows a RANGE among the effects.

> **Interpretation.** The rules above that the syllabus does not state (rank-1 loads, shared slots, defined memory for ASSERT) come from the oracle; see [oracle/README.md](../oracle/README.md#decisions-not-in-uirmd) for its reasons.

## Quiz

1. What is `%ready` in `%ready = after %buf %write`, and why does the load use it instead of `%buf`?
   <details><summary>Answer</summary>The same buffer, with a promise that its users run after <code>%write</code>. Loading <code>%buf</code> directly would leave the load and store unordered, which is invalid.</details>
2. Why must the renderer compile with `-ffp-contract=off`?
   <details><summary>Answer</summary>Otherwise the C compiler may fuse <code>a * b + c</code> into one fused multiply-add, which rounds once instead of twice, so the C result could differ from the interpreter's.</details>
3. Write C for `mod a b` on `i32` without a helper function.
   <details><summary>Answer</summary><code>(a % b != 0 && (a % b < 0) != (b < 0)) ? a % b + b : a % b</code>.</details>
4. Two calls of a body that uses an ALLOC are inlined. What goes wrong if the inliner keeps the ALLOC's slot?
   <details><summary>Answer</summary>Hash-consing makes both inlined ALLOCs one node, so both calls share one scratch area. Their accesses are then no longer ordered: the fully-ordered check rejects the program, and a topological order could interleave them.</details>
5. Why does "fully ordered" mean that any topological order of the graph gives the same result?
   <details><summary>Answer</summary>Every pair of accesses whose order matters (one is a store, same buffer) is connected by a dependency, and every topological order respects every dependency.</details>
6. Is `shrink %buf (mod (load %n) 4) 2` valid on a buffer of 4 elements, for an `i32` buffer `%n`?
   <details><summary>Answer</summary>No. A load's bounds are the full <code>i32</code> range, so the offset's bounds are <code>[0, 3]</code>, and the window can reach element <code>3 + 2 − 1 = 4</code>, past the end.</details>

## Sources

1. ISO C11 committee draft N1570. https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf — §6.3.1.3 for converting to a signed type, §6.5.5 for `/` and `%`, §6.5.7 for shifts.
2. Linux man-pages, dlopen(3). https://man7.org/linux/man-pages/man3/dlopen.3.html — loading a shared library and finding a function in it.
3. Bryant & O'Hallaron, *Computer Systems: A Programmer's Perspective*, 3rd ed. https://csapp.cs.cmu.edu/ — ch. 7, linking and shared libraries.
4. Kahn, "Topological Sorting of Large Networks", CACM 1962. https://doi.org/10.1145/368996.369025 — topological order.
5. tinygrad, commit 07821cae. https://github.com/tinygrad/tinygrad — `tinygrad/renderer/cstyle.py` (a C renderer), `tinygrad/runtime/ops_cpu.py` (a CPU runtime), `tinygrad/uop/ops.py` (`addrspace`, `storage_base`).
