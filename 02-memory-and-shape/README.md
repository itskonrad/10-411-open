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

**Builds on:** [Chapter 1](../01-uops-and-rewrites/README.md). **By the end you can:** compile a UIR program with memory to a C function, load it into your compiler's process, run it, check its result, and reject programs whose memory accesses are unordered or out of range.

## Contents

- [What you build](#what-you-build)
- [How to start](#how-to-start)
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

## What you build

In chapter 1 your compiler ran every test by rewriting it down to constants. In this chapter it becomes a compiler in the full sense: it prints the program as C, hands that to the system's C compiler, loads the result into its own process, calls it, and reads back the verdict. Programs also gain memory: buffers they store into and load from.

Here is [store_load.uir](examples/store_load.uir), the smallest program with memory (`buffer []` is a buffer of shape `()`, one element):

```text
%buf   = buffer [] slot=0 dtype=i32
%write = store %buf 7
%ready = after %buf %write
%value = load %ready
%test  = assert %value 7
```

and the C function your compiler generates for it:

```c
#include <stdint.h>

int kernel(int32_t *buf0) {
    buf0[0] = 7;
    int32_t v5 = buf0[0];
    return v5 == 7;
}
```

The runtime allocates one `int32_t` for `buf0`, calls `kernel`, and gets 1 back: PASS. Verdicts are the same three words as before. ERROR now also covers the new rules, such as a load that is not ordered after the store it should see:

```text
$ mycc store_load.uir
PASS
$ mycc unordered.uir
ERROR line 4: load (line 5) and store (line 4) of %buf are not ordered: use after
```

Inside, the compiler now has two ways to run a test, and they must agree:

```text
                              ┌─▶ interpret (one array per buffer) ─────────────────────┐
 .uir ─▶ parse, check, props ─┤                                                         ├─▶ verdict
                              └─▶ inline ─▶ toposort ─▶ render ─▶ cc ─▶ load ─▶ call ───┘
```

**Why two paths?** The interpreter is short and obviously right; the compiled path is where the speed will come from, and where the bugs will be. Running every test both ways turns each disagreement into a bug report with a test case attached. This is *differential testing* ([McKeeman 1998](#sources) used it to test C compilers), and it is how you will trust your generated code for the rest of the course: from chapter 3 it has loops, from chapter 7 it runs on a GPU, and the interpreter stays the reference.

**Why C?** The syllabus: "Students write a renderer and a runtime capable of compiling and executing C programs." Printing C instead of machine code hands register allocation, instruction selection and much of the low-level optimization to a mature C compiler. Your compiler's job is the part only it can do: deciding what to compute and in what order. Chapter 7 does the same with HIP for AMD GPUs.

## How to start

You have a chapter 1 compiler that passes every chapter 1 example. This section grows it into a chapter 2 compiler. Each step ends with a check; commit after each one, and run every command from the repo root.

**Step 0: three modes.** Give your command flags of your own:

- `--interpret`: chapter 1's path. Step 4 extends it to memory.
- `--emit-c`: print the generated C and stop. You will use it constantly.
- No flag: interpret first. If that gives ERROR, report it: reading memory that was never stored (like chapter 1's undefined arithmetic) is an ERROR only a run can see, and compiled C cannot see it. Otherwise compile, run, and compare the two verdicts. If they differ, print a line that is not a verdict, such as `MISMATCH interpreter PASS, C FAIL`, and exit non-zero, so the checker reports it.

Until the compiled path exists, let the default fall back to `--interpret`. Check both modes:

```sh
python3 -I tools/check_compiler.py --chapter 2 -- python3 compiler/mycc.py --interpret
python3 -I tools/check_compiler.py --chapter 2 -- python3 compiler/mycc.py
```

At this point the chapter 1 files should all match, and the chapter 2 examples will not until steps 4–6.

**Step 1: the thinnest compiled slice.** Compile a chapter 1 program before touching memory. For [add.uir](../01-uops-and-rewrites/examples/add.uir), render the `add` as a C variable and the `assert` as the return value:

```c
#include <stdint.h>

int kernel(void) {
    int32_t v2 = 2 + 3;
    return v2 == 5;
}
```

Write it to a file, compile it to a shared library, load it, call `kernel`, and print PASS if it returns 1. That is the whole runtime in miniature (Lesson 2 has the code). If you did [chapter 0's shared-library exercise](../00-prerequisites/README.md#lesson-4-c-index-arithmetic-and-loop-nests), you have done this once already. Check:

```sh
python3 -I tools/check_compiler.py 01-uops-and-rewrites/examples/add.uir -- python3 compiler/mycc.py
```

**Steps 2–7: grow it.**

| Step | Add | Read | Done when |
|------|-----|------|-----------|
| 2 | Render every chapter 1 op, with exact C translations and the `idiv`/`imod`/`ishl` helpers. Render after inlining calls, without folding: run your rewrite engine with only the inline rule | Lesson 1 | Every chapter 1 example gives the same verdict compiled as interpreted |
| 3 | Parse the new ops; compute `addrspace`, `shape` and `dtype` for them; check the rules that need no bounds or ordering: address spaces, stores, slots, no BUFFER in a call, rank-1 loads, AFTER's effects | Lesson 3, [Ops introduced](#ops-introduced) | The oracle's [alu_on_global](../oracle/tests/invalid/alu_on_global.uir), [store_shape](../oracle/tests/invalid/store_shape.uir), [buffer_in_call](../oracle/tests/invalid/buffer_in_call.uir), [buffer_alloc_slot](../oracle/tests/invalid/buffer_alloc_slot.uir) and [after_value_dep](../oracle/tests/invalid/after_value_dep.uir) give ERROR. Copy them into `tests/chapter2/` as your first tests |
| 4 | Interpret memory: walk the graph in topological order with one array per BUFFER | Lesson 2 | [store_load](examples/store_load.uir), [index_buffer](examples/index_buffer.uir), [chained_stores](examples/chained_stores.uir) and [f32_buffer](examples/f32_buffer.uir) give PASS with `--interpret`, and [load_never_stored](../oracle/tests/invalid/load_never_stored.uir) gives ERROR |
| 5 | Render memory: buffers as pointer parameters, `INDEX`, `LOAD`, `STORE`, `AFTER`, rank-1 stores; allocate buffers in the runtime | Lessons 1 and 2 | The same four give PASS compiled |
| 6 | `SHRINK` and `ALLOC`, and fresh ALLOC slots when inlining | Lesson 2 | [shrink_window](examples/shrink_window.uir), [symbolic_offset](examples/symbolic_offset.uir) and [alloc_in_call](examples/alloc_in_call.uir) give PASS both ways |
| 7 | `storage_base`, `accesses`, the fully-ordered check, and bounds checks for memory | Lesson 3 | [unordered.uir](../oracle/tests/invalid/unordered.uir) and [shrink_oob.uir](../oracle/tests/invalid/shrink_oob.uir) give ERROR |

The chapter is done when `check_compiler.py --chapter 2` matches the oracle in both modes, on every example and every test under `tests/`.

**Habits that pay off.**

- **Read the C.** When a compiled test fails, print the C first. Most renderer bugs are obvious in the text.
- **Keep the generated files.** The runtime writes each kernel to a file before compiling it; keep them in a cache folder (Lesson 2), so you can open and recompile the exact source that failed.
- **Debug outside your process.** A bad pointer in generated code crashes your compiler with it. To investigate, render a standalone file with a `main` that allocates the buffers and calls `kernel`, and compile it with `gcc -g -fsanitize=address,undefined` to get a report instead of a crash.
- **Every disagreement is a test.** When the two modes disagree, shrink the program until the disagreement is one line, and keep it in `tests/chapter2/`.

## Lectures

### Lesson 1: toposort and rendering, C refresher

**Memory enters the graph.** Chapter 1's programs were pure values: any node could be computed at any time once its sources were ready, and the answer was the same. Memory breaks that. A `STORE` changes what a later `LOAD` sees, so *when* things happen now matters. The course's answer is not to add statements, but to add edges.

- A `BUFFER` is an array that outlives the program.
- `STORE` writes it, and `LOAD` reads it.
- `AFTER` says what must happen first: `after %buf %write` is the buffer itself, with a promise attached that anything using it happens after `%write`.

In [store_load.uir](examples/store_load.uir), the load reads `%ready`, not `%buf`:

```text
           ASSERT
          /      \
       LOAD    CONST 7
        |         |
      AFTER       |        (%ready: %buf, after %write)
      /    \      |
 BUFFER ◀── STORE ┘        (%write: stores the 7)
```

The load depends on the `AFTER`, which depends on the `STORE`, so every order of the nodes that respects the edges puts the store first. The `7` is one node shared by the store and the assert, as hash-consing promises. There are still no statements: order is just more edges in the graph.

> **Predict.** What changes if the load reads `%buf` directly?
> <details><summary>Answer</summary>Nothing connects the load to the store, so an order that loads first is as valid as one that stores first, and they read different values. The program is rejected as not fully ordered (Lesson 3).</details>

**Rendering is a walk in topological order.** To emit C, list the nodes so that every node comes after its sources, using the `toposort` from [chapter 0](../00-prerequisites/README.md#lesson-3-graphs-substitution-and-intervals) with each UOp's `src` as its inputs ([Kahn 1962](#sources) gives another algorithm). Each node appears once, however many nodes use it: the toposort's `seen` set does that, so a shared subexpression is computed once. Any topological order is valid; Lesson 3 explains why.

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

(A sketch: a BUFFER's arg is just its slot here, where yours also holds the dtype; its source is its shape, `[]` or a length `n`; a rank-0 buffer is element 0 of its pointer; `ctype` maps a node to `int32_t`, `float` or `bool`. Stacks and other rank-1 values, `f32` and `bool` constants, and the remaining ops come from the table below, and the ASSERT from Lesson 2.) Naming every value is the simple choice. It produces more lines than needed, but the C compiler removes the extra variables, and you never have to decide whether an expression may be duplicated.

Here is the walk for [examples/chained_stores.uir](examples/chained_stores.uir), which sets `b[0] = 1` and then `b[1] = b[0] + 1`:

| n | Node | Name other lines use | Line emitted |
|---|------|----------------------|--------------|
| 0 | `CONST 2` (the shape) | `2` | |
| 1 | `BUFFER slot=0` | `buf0` | |
| 2 | `CONST 0` | `0` | |
| 3 | `INDEX %b 0` | `buf0[0]` | |
| 4 | `CONST 1` | `1` | |
| 5 | `STORE` (`%s0`) | | `buf0[0] = 1;` |
| 6 | `AFTER %b %s0` (`%b1`) | `buf0` | |
| 7 | `INDEX %b1 1` | `buf0[1]` | |
| 8 | `INDEX %b1 0` | `buf0[0]` | |
| 9 | `LOAD` | `v9` | `int32_t v9 = buf0[0];` |
| 10 | `ADD … 1` | `v10` | `int32_t v10 = v9 + 1;` |
| 11 | `STORE` (`%s1`) | | `buf0[1] = v10;` |
| 12 | `AFTER %b %s1` | `buf0` | |

Variables are named by their position in the order, which is why the load is `v9`. Row 4 is one node used three times: the stored value, the index `1`, and the `+ 1`. Rows 6 and 12 emit nothing: an `AFTER` has done its job once the toposort has placed everything it waits for before everything that uses it. The rendered body, before the ASSERT is added as a return value (Lesson 2):

```c
#include <stdint.h>

void kernel(int32_t *buf0) {
    buf0[0] = 1;
    int32_t v9 = buf0[0];
    int32_t v10 = v9 + 1;
    buf0[1] = v10;
}
```

Two kinds of node are statements rather than values: a `STORE` must appear exactly once and in the right place, and a `LOAD` must read memory at its position, not later. That is why a LOAD gets its own variable even though `buf0[0]` would be a valid C expression: written inline into a later line, it could read memory after a later store. Topological order puts each statement after everything it depends on. Lesson 3 shows why that is enough. The syllabus calls the result "loopless C functions that act on memory and immediates"; loops arrive in chapter 3.

**C refresher: exact translations.** The C you emit must compute exactly what your chapter-1 interpreter computes ([uir.md](../uir.md#arithmetic)). If pointers and flat arrays are rusty, read [chapter 0, Lesson 4](../00-prerequisites/README.md#lesson-4-c-index-arithmetic-and-loop-nests) first. Most ops map directly; these need care:

| UIR | C |
|-----|---|
| `i32`, `f32`, `bool` | `int32_t`, `float`, `bool` (`<stdint.h>`, `<stdbool.h>`) |
| `add`, `mul` on `i32` | `a + b`, `a * b`, compiled with `-fwrapv` so they wrap |
| `xor` | `a ^ b` |
| `div`, `mod`, `shl` | helper functions, below |
| `max` | `a < b ? b : a` |
| `recip` | `1.0f / a` |
| `cast` to `bool` | `a != 0` |
| other `cast` | `(int32_t)a`, `(float)a`: truncation and rounding as uir.md requires |
| `f32` constant | `repr(x) + "f"`, such as `0.5f`; `INFINITY` and `NAN` from `<math.h>` |
| `bool` constant | `true`, `false` |

Rank-1 values need a convention too, since C cannot assign whole arrays and there are no loops yet:

| UIR | C |
|-----|---|
| `store %buf [10 20 30]` | `buf0[0] = 10; buf0[1] = 20; buf0[2] = 30;`: one statement per element |
| a stack used as a value, `index [10 20 30] %i` | a local array, `int32_t v4[3] = {10, 20, 30};`, then `v4[i]` |
| a rank-1 `load %buf` | a local copy, `int32_t v5[3] = {buf0[0], buf0[1], buf0[2]};`, read at its place in the order |
| a rank-1 `assert` | `return a[0] == 10 && a[1] == 20 && …;` |

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

Converting the shifted `uint32_t` back to `int32_t` is implementation-defined in C11 ([N1570](#sources) §6.3.1.3); GCC and Clang wrap, which is what you want. The `f32` constant rule works because the literal was already rounded to `f32` when parsed ([chapter 0, Lesson 2](../00-prerequisites/README.md#lesson-2-numbers-in-a-machine) explains why `repr` round-trips).

Walk `idiv(-7, 2)` through: C's `-7 / 2` truncates to `-3`, and `-7 % 2` is `-1`. The remainder is not zero and the signs of `a` and `b` differ, so the true quotient was negative and not whole, and truncation rounded it up: subtract one to get the floor, `-4`. When the signs agree, truncation and floor are the same, and the helper returns C's answer unchanged.

Here is the table at work on [examples/f32_buffer.uir](examples/f32_buffer.uir), which stores `[1 2]` into an `f32` buffer and multiplies element 1 by `0.5`. A renderer that follows it produces (variable names will differ):

```c
int kernel(float *buf0) {
    buf0[0] = 1.0f;
    buf0[1] = 2.0f;
    float x = buf0[1];
    float y = x * 0.5f;
    return y == 1.0f;
}
```

The stack `[1 2]` became one store per element, the literals took the buffer's dtype (`1.0f`, not `1`), and every float constant carries its `f`.

Compile with `-std=c11 -fwrapv -ffp-contract=off`. The last flag stops the compiler from fusing `a * b + c` into one fused multiply-add, which rounds once instead of twice and would disagree with your interpreter.

**Common mistakes.**

- Emitting C's `/` and `%` for `div` and `mod`, or `<<` on a negative value. All three pass most tests and fail on negative numbers.
- Forgetting `-fwrapv` or `-ffp-contract=off`. The results are usually right, which makes the rare wrong one hard to find.
- Printing an `f32` constant with too few digits, or without the `f` suffix: `0.1` in C is a `double`, and `x * 0.1` computes in double precision before rounding.
- Writing a LOAD inline into the expression that uses it, so it reads memory after a later store.
- Missing headers: `bool` needs `<stdbool.h>`, `INFINITY` and `NAN` need `<math.h>`.

### Lesson 2: memory management and runtime

**Two kinds of memory.** The syllabus gives two, and they differ in who owns them and how long they live:

- **`BUFFER`** is "global persistent": memory that exists before the program runs and after it ends. Your runtime allocates it and passes it in. In C, each buffer is a pointer parameter. Buffers are a program's inputs and outputs: in later chapters they hold a model's weights and activations.
- **`ALLOC`** is "call scope storage, example `float a[10]`": scratch memory that lives for one call. In C, a local array declared in the function.

> **Interpretation.** The syllabus does not fix a calling convention. This chapter uses the simplest one: the function takes one pointer per BUFFER, in increasing slot order, and nothing else.

Both start with undefined contents. There is no way to pass input data in yet, so a test writes its inputs with `STORE` first, and reading an element that was never stored is an error (the interpreter reports it; C cannot). An ALLOC outside any call belongs to the program, which counts as one call.

> **Interpretation.** "Never in call" is read two ways at once: a `CALL` body cannot contain a `BUFFER`, and memory cannot be passed to or returned from a call. A call's arguments and body are values; scratch data lives in ALLOCs. The oracle enforces both.

**Scratch memory and inlining.** [examples/alloc_in_call.uir](examples/alloc_in_call.uir) calls one body twice, and the body uses scratch memory:

```text
%x    = param [] slot=0 dtype=i32
%tmp  = alloc [] slot=0 dtype=i32
%put  = store %tmp %x
%f    = add (load (after %tmp %put)) 1
%sum  = add (call %f 4) (call %f 10)
%test = assert %sum 16
```

Each call stores its argument into `%tmp` and reads it back, so the answer is `(4 + 1) + (10 + 1) = 16`. Two calls of one body are two separate scratch areas. But after hash-consing, the body's ALLOC is one UOp.

> **Predict.** Inline both calls and keep the ALLOC as it is. What can the two loads read?
> <details><summary>Answer</summary>Both inlined bodies store into the same node, one 4 and one 10, and nothing orders the two halves. An order that runs both stores before both loads reads 10 twice: <code>11 + 11 = 22</code>. The checks ran on the program as written, before inlining, so nothing reports it.</details>

So the inliner must give each inlined ALLOC a fresh slot, as tinygrad's does (`tinygrad/schedule/prepare.py`, which draws it from a global counter). Here, take one past the highest slot in use, since BUFFER and ALLOC slots are unique across the program. Then each call has its own scratch memory, and the rendered C shows it, with one local array per inlined call (variable names will differ):

```c
#include <stdint.h>

int kernel(void) {
    int32_t alloc1[1];
    alloc1[0] = 4;
    int32_t x = alloc1[0];
    int32_t y = x + 1;
    int32_t alloc2[1];
    alloc2[0] = 10;
    int32_t z = alloc2[0];
    int32_t w = z + 1;
    int32_t sum = y + w;
    return sum == 16;
}
```

**Windows into memory.** Kernels often work on part of a buffer: a row, a tile, the half one call owns. SHRINK names that part without copying it, and chapter 5's movement ops build on it.

`shrink %buf %offset %size` is the part of a rank-1 buffer starting at `offset`, `size` elements long. The offset may be an expression ("symbolic"); the size must be a constant, so the window's shape is known. In [examples/shrink_window.uir](examples/shrink_window.uir), storing `[7 8]` into `shrink %buf 1 2` of a zeroed four-element buffer gives `[0 7 8 0]`.

In C a window is a pointer, `buf0 + offset`, and its element `i` is `(buf0 + offset)[i]`. In [examples/symbolic_offset.uir](examples/symbolic_offset.uir) the offset is computed from a value loaded at run time:

```c
#include <stdint.h>

static int32_t imod(int32_t a, int32_t b) {  // from Lesson 1
    int32_t r = a % b;
    return (r != 0 && (r < 0) != (b < 0)) ? r + b : r;
}

int kernel(int32_t *buf0, int32_t *buf1) {
    buf0[0] = 5;
    buf1[0] = 0; buf1[1] = 0; buf1[2] = 0; buf1[3] = 0;
    int32_t n = buf0[0];
    int32_t off = imod(n, 3);
    int32_t *win = buf1 + off;
    win[0] = 7;
    win[1] = 8;
    return buf1[0] == 0 && buf1[1] == 0 && buf1[2] == 7 && buf1[3] == 8;
}
```

The compiler does not know `off`, but Lesson 3 shows how it proves that `win[0]` and `win[1]` stay inside `buf1`.

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

Line by line:

1. **Name the file after a hash of the source and flags.** It caches: a test suite compiles the same kernel many times, and the second time costs nothing. And it avoids a real bug: the loader caches libraries by path, so loading a new `kernel.so` over an old one can silently return the old code.
2. **Write the source and run `cc`** with `-shared -fPIC`, which makes a shared library rather than a program. `check=True` turns a C compile error into an exception, so a renderer bug is loud.
3. **Load it** with an absolute path. With a name that has no `/`, the loader searches system directories, not the current one.

Calling the result needs memory for each BUFFER, sized from its shape and dtype: one element for a rank-0 buffer, `n` for shape `(n,)`. With `ctypes`, `buf0 = (ctypes.c_int32 * 2)()` allocates two zeroed `i32`s, and `compile_c(src).kernel(buf0)` runs the kernel and fills them: `[1, 2]` for `chained_stores.uir`. Other languages have the same three steps: write a file, run `cc`, and load it through the language's foreign function interface. In C or C++, the loader is called directly ([dlopen(3)](#sources)):

```c
#define _POSIX_C_SOURCE 200809L
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>

typedef int (*kernel_fn)(int32_t *);

// load a compiled kernel and call it on one buffer; -1 if it cannot be loaded
int run_kernel(const char *path, int32_t *buf0) {
    void *lib = dlopen(path, RTLD_NOW);
    if (lib == NULL) {
        fprintf(stderr, "dlopen: %s\n", dlerror());
        return -1;
    }
    kernel_fn kernel = (kernel_fn)dlsym(lib, "kernel");  // POSIX allows this cast
    if (kernel == NULL) {
        fprintf(stderr, "dlsym: %s\n", dlerror());
        dlclose(lib);
        return -1;
    }
    return kernel(buf0);
}
```

The library stays loaded for later calls, which is what the cache wants. With glibc older than 2.34, link your compiler with `-ldl`. Rust and other languages have libraries that wrap these two calls.

**Running a test.** The program's root is an `ASSERT`. It is simplest to render it into the function too: the function returns 1 if every element matches and 0 otherwise, and the runtime checks the return value. For `chained_stores.uir`, the kernel becomes:

```c
#include <stdint.h>

int kernel(int32_t *buf0) {
    buf0[0] = 1;
    int32_t v9 = buf0[0];
    int32_t v10 = v9 + 1;
    buf0[1] = v10;
    return buf0[0] == 1 && buf0[1] == 2;
}
```

A rank-1 assert compares element by element. To report FAIL with the actual values, take them from the interpreter, which the default mode has already run.

**Interpreting memory.** Rewriting alone cannot run a `STORE`, so the interpreter gains a second part: after inlining, a walk over the graph in topological order, with one array per BUFFER or ALLOC.

- `BUFFER` and `ALLOC` make a new array, with every element marked "never stored". Inlining already gave each call its own ALLOC slot, so one array per slot is enough.
- `STORE` writes the array, and `LOAD` reads it. Reading an element marked "never stored" is an ERROR.
- `AFTER` passes its first source through.
- Every other node is computed from its sources' values with the same folding table as chapter 1, so the two parts agree on arithmetic.

For `chained_stores.uir`:

| Node | Action | `b` afterwards |
|------|--------|----------------|
| `buffer 2` | new array | `[?, ?]` |
| `%s0` | write 1 at index 0 | `[1, ?]` |
| `%b1` | pass `b` through | |
| `load (index %b1 0)` | read index 0: 1 | |
| `add … 1` | fold: 2 | |
| `%s1` | write 2 at index 1 | `[1, 2]` |
| `assert (after %b %s1) [1 2]` | compare | PASS |

Because loads and stores are fully ordered (Lesson 3), any topological order gives the same answer. The [oracle](../oracle/README.md) works this way. This interpreter is the reference your compiled C is checked against, in every chapter from here on.

**Common mistakes.**

- Reusing one file name for every kernel, so the loader returns a stale library.
- Building in `/tmp`. Some systems mount it `noexec`, and loading a library from it then fails with "failed to map segment from shared object".
- Allocating buffers of the wrong size or element type. Too small, and the kernel writes past the end of the allocation. A `float` buffer allocated as `c_int32` has the right size, so the verdict still comes out right, but the values you read back for a FAIL report are garbage.
- Inlining a body with an ALLOC twice without fresh slots.
- Passing buffers in the wrong order. The calling convention is "increasing slot order"; sort, do not rely on the order you met them.

### Lesson 3: type systems for shape, dtype, and addrspace

**A type system rejects programs before they run.** Your chapter-1 checks were already one: rules over `dtype` and `shape` that every node must satisfy. This chapter needs more of them, for a practical reason: C does not check memory. An index past the end of an array, or a load that runs before the store it needed, is undefined behavior in C. It may crash, return garbage, or appear to work. Your compiler is the last place where such a program can be rejected with a clear message. This lesson adds `addrspace`, extends shape and dtype to memory, and adds two analyses over memory.

**Address spaces.** Every node is either memory or a value:

| `addrspace` | Nodes | Can be used by |
|-------------|-------|----------------|
| `GLOBAL` | `BUFFER`, `ALLOC`, and `INDEX`, `SHRINK`, `AFTER` of memory | `LOAD`, `STORE` (as the target), `INDEX`, `SHRINK`, `AFTER`, `ASSERT` |
| `ALU` | everything else, including `LOAD` | ALU ops, `STORE` (as the value), `INDEX`, `AFTER` (as the value), CALL arguments, `ASSERT` |

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

For `chained_stores.uir`, the walk from the leaves up:

| Node | `storage_base` of its address | `accesses` |
|------|-------------------------------|------------|
| `%s0 = store (index %b 0) 1` | `%b` | `{%b: {%s0}}` |
| `load (index %b1 0)` | `index %b1 0` → `%b1` → `%b` | `{%b: {%s0, load}}`, through `%b1`'s source `%s0` |
| `%s1 = store (index %b1 1) …` | `%b` | `{%b: {%s0, load, %s1}}` |

One buffer, three accesses, and the root's accesses cover the program.

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

In `chained_stores.uir` every pair is ordered: the load reaches `%s0` through `%b1`, and `%s1` reaches the load through its value. Here is a program that fails, from the oracle's tests ([unordered.uir](../oracle/tests/invalid/unordered.uir)):

```text
%buf   = buffer [] slot=0 dtype=i32
%write = store %buf 7
%value = load %buf
%test  = assert (add %value (load (after %buf %write))) 14
```

`%value` loads `%buf` directly, so nothing connects it to `%write`. Two topological orders are both valid, and they disagree:

| Order | C | `%value` | Assert |
|-------|---|----------|--------|
| store first | `buf0[0] = 7; x = buf0[0]; …` | 7 | `7 + 7 == 14`: holds |
| load first | `x = buf0[0]; buf0[0] = 7; …` | whatever was there: 0 if the runtime zeroed the buffer | fails |

The chapter's own `toposort` picks the second order: it visits `%value`, the first source of the `add`, before anything that leads to the store. A different toposort, or the same one after you reorder some sources, would pick the first. The rule makes the program invalid instead. Writing `load (after %buf %write)` for `%value` fixes it.

This rule is what makes rendering simple. Any topological order keeps every dependency, and the rule turns every order that matters into a dependency, so *every* topological order gives the same result. Your interpreter and your C agree without either needing to know about time. (This holds for programs without loops; chapter 3 adds one more rule, [when a node inside a loop runs](../uir.md#evaluation).)

The check is deliberately coarse: it treats two accesses to *different* elements of one buffer as a pair too. That rejects some programs that would be fine, but it needs no reasoning about indices. (Storing each node's full `reach` set is quadratic in memory; fine for tests, slow for big graphs.)

> **Interpretation.** Read literally, "fully ordered" could mean one total order over all memory accesses. This chapter orders only the pairs whose order can change a result: two accesses to one buffer, at least one a STORE. Two loads, or accesses to different buffers, may stay unordered.

**Bounds checks.** "Loads and stores are bounds checked to never be out of range." With [uir.md's bounds rules](../uir.md#bounds), an `INDEX` into memory of length `n` must have bounds inside `[0, n − 1]`, and a `SHRINK` window must have `offset.vmin ≥ 0` and `offset.vmax + size ≤ n`. As in chapter 1, the check runs on the program as written and must succeed from bounds alone. For [symbolic_offset.uir](examples/symbolic_offset.uir):

| Node | Bounds | Why |
|------|--------|-----|
| `load (after %n %sn)` | `[-2^31, 2^31 − 1]` | a loaded value can be anything |
| `mod … 3` | `[0, 2]` | floor mod by 3 |
| `shrink … %off 2` on a buffer of 4 | window `[0, 3]` | `offset.vmin = 0 ≥ 0`, and `offset.vmax + 2 = 4 ≤ 4` |

The window fits for every possible loaded value, so the program is valid, although the compiler never knows the value (it is 5 at run time, so the offset is 2).

> **Predict.** What if the offset were `mod … 4`?
> <details><summary>Answer</summary>Its bounds would be <code>[0, 3]</code>, and <code>3 + 2 = 5 &gt; 4</code>: the window could reach element 4, past the end. ERROR, even though the actual value, 5 mod 4 = 1, would fit.</details>

**The new rules at a glance.** One invalid program per rule, with what the oracle says about it:

| Rule | Invalid program (the line that breaks it) | Oracle |
|------|-------------------------------------------|--------|
| ALU ops take values | `%x = add %b 1`, with `%b` a buffer ([alu_on_global](../oracle/tests/invalid/alu_on_global.uir)) | `addrspace`: load it first |
| A store matches its target | `%s = store %b 5`, with `%b` of shape `(2,)` ([store_shape](../oracle/tests/invalid/store_shape.uir)) | `shape`: storing `()` into `(2,)` |
| Rank-1 loads stay data | `%x = add (load (after %b %s)) 1`, with `%b` of shape `(2,)` | `rank`: ALU ops are rank 0 |
| No BUFFER in a call body | a body that stores into a `buffer` | `call`: BUFFER is never in a call |
| One slot numbering | `%a = buffer [] slot=0 …` and `%b = alloc [] slot=0 …` | `arg`: slot 0 is already used |
| AFTER waits for effects | `load (after %b 5)` | `dtype`: after waits for effects |
| In bounds | `store (index %b 3) 1`, with `%b` of shape `(3,)` | `bounds`: index range `[3, 3]` is not inside `[0, 2]` |
| Fully ordered | [unordered.uir](../oracle/tests/invalid/unordered.uir) above | `order` |
| Defined memory (at run time) | `assert (after %b %s) [1 0]`, where only element 0 was stored ([load_never_stored](../oracle/tests/invalid/load_never_stored.uir) does it with a LOAD) | `undefined`: reads memory that was never stored |

Write your own versions of these as tests: each is a few lines, and each pins down one rule.

**Common mistakes.**

- Checking order or bounds after rewriting, when constant folding has made an index exact. The check must pass on the program as written ([why](../uir.md#validation)).
- Not following `AFTER` in `storage_base`, so a load through `%b1` is filed under `%b1` instead of `%b`, and the ordering check never compares it with `%b`'s stores.
- Counting the ASSERT as an access. It is the root: it comes after everything.
- Letting a STORE's value be memory (`store %a %b`, with `%b` a buffer). The value must be an ALU value; write `load %b`.

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
- **Loads and asserts read defined memory**: every element a LOAD reads or an ASSERT compares must have been stored. The interpreter reports this when it runs; the compiled C cannot.

## Properties introduced

| Property | Type | Rule |
|----------|------|------|
| `addrspace` | `GLOBAL` or `ALU` | `GLOBAL` for `BUFFER`, `ALLOC`, and `INDEX`/`SHRINK`/`AFTER` of `GLOBAL`; `ALU` otherwise |
| `storage_base` | UOp | Through `INDEX`, `SHRINK` and `AFTER` to the `BUFFER` or `ALLOC` |
| `accesses` | `dict[UOp, tuple[UOp, ...]]` | The sources' accesses merged, plus the node itself under its `storage_base` if it is a `LOAD` or `STORE` |

> **Interpretation.** tinygrad has `storage_base` but no `accesses`. The reading above is the one the syllabus's comment gives ("a list of UOps that access a buffer"), and the ordering check is what it is for.

## Assignment

Start by writing ten tests of your own in UIR (the syllabus asks for ten each week), and check them with the [oracle](../oracle/README.md). [How to start](#how-to-start) gives an order to build things in.

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
| [symbolic_offset.uir](examples/symbolic_offset.uir) | A `SHRINK` offset loaded at run time, proven in range by bounds |
| [f32_buffer.uir](examples/f32_buffer.uir) | Literals typed by an `f32` target |
| [alloc_in_call.uir](examples/alloc_in_call.uir) | `ALLOC` scratch memory, one per call |

## Spec notes

> **Spec note.** The draft course page puts "render and execute C programs" in week 3; the syllabus puts the renderer and runtime in week 2. This chapter follows the syllabus.

> **Interpretation.** "SHRINK(offset, shape)" is written in UIR as `shrink memory offset size`, following tinygrad (`tinygrad/uop/ops.py`). Until chapter 5, SHRINK applies only to rank-1 memory (tinygrad's program spec allows it only on a buffer or an AFTER), so its offset and size are single numbers; the size is a constant ≥ 1.

> **Interpretation.** A `STORE` has dtype `void` and shape `()`: it is an effect, not a value. tinygrad gives STORE its target's shape; nothing in this course uses a STORE's shape.

> **Interpretation.** `AFTER(buf, <store>)` takes one value and any number of effects, as tinygrad's AFTER does, so one access can wait for several stores. Its first source may also be an `ALU` value or an effect, as tinygrad's AFTER spec allows (`tinygrad/uop/spec.py`). Chapter 3 also allows a RANGE among the effects.

> **Interpretation.** The rules above that the syllabus does not state (rank-1 loads, shared slots, defined memory) come from the oracle; see [oracle/README.md](../oracle/README.md#decisions-not-in-uirmd) for its reasons.

## Quiz

1. What is `%ready` in `%ready = after %buf %write`, and why does the load use it instead of `%buf`?
   <details><summary>Answer</summary>The same buffer, with a promise that its users run after <code>%write</code>. Loading <code>%buf</code> directly would leave the load and store unordered, which is invalid.</details>
2. Why must the renderer compile with `-ffp-contract=off`?
   <details><summary>Answer</summary>Otherwise the C compiler may fuse <code>a * b + c</code> into one fused multiply-add, which rounds once instead of twice, so the C result could differ from the interpreter's.</details>
3. Write C for `mod a b` on `i32` without a helper function.
   <details><summary>Answer</summary><code>(a % b != 0 && (a % b < 0) != (b < 0)) ? a % b + b : a % b</code>.</details>
4. In [alloc_in_call.uir](examples/alloc_in_call.uir) the body's ALLOC has slot 0. Which slots do the two inlined ALLOCs get, and why not 0 again?
   <details><summary>Answer</summary>1 and 2: each fresh slot is one past the highest in use. Reusing 0 would rebuild the same hash-consed node, so both calls would share one scratch area again.</details>
5. Why does "fully ordered" mean that any topological order of the graph gives the same result?
   <details><summary>Answer</summary>Every pair of accesses whose order matters (one is a store, same buffer) is connected by a dependency, and every topological order respects every dependency.</details>
6. A rank-0 buffer renders as `buf0[0]` and a rank-1 buffer as `buf0`. Why the difference?
   <details><summary>Answer</summary>Both are pointer parameters. A rank-0 buffer is used as one value, so the renderer names its only element, <code>buf0[0]</code>; a rank-1 buffer is indexed, so <code>INDEX</code> appends <code>[i]</code> to the pointer's name.</details>
7. Why does the renderer give every LOAD its own variable, instead of writing `buf0[0]` straight into the expression that uses it?
   <details><summary>Answer</summary>The LOAD must read memory at its place in the order. Written inline into a later line, it would read after any store emitted in between.</details>
8. Why does the runtime name each library file after a hash of its source and flags?
   <details><summary>Answer</summary>So a kernel compiled before is reused, and because the loader caches libraries by path: a new library written over an old path could load the old code.</details>

## Sources

1. ISO C11 committee draft N1570. https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf — §6.3.1.3 for converting to a signed type, §6.5.5 for `/` and `%`, §6.5.7 for shifts.
2. Linux man-pages, dlopen(3). https://man7.org/linux/man-pages/man3/dlopen.3.html — loading a shared library and finding a function in it.
3. Bryant & O'Hallaron, *Computer Systems: A Programmer's Perspective*, 3rd ed. https://csapp.cs.cmu.edu/ — ch. 7, linking and shared libraries.
4. Kahn, "Topological Sorting of Large Networks", CACM 1962. https://doi.org/10.1145/368996.369025 — topological order.
5. McKeeman, "Differential Testing for Software", Digital Technical Journal 10(1), 1998, pp. 100–107. https://www.cs.tufts.edu/comp/150FP/archive/bill-mckeeman/DifferentailTesting.pdf — testing compilers by running one input through two implementations and comparing.
6. tinygrad, commit 07821cae. https://github.com/tinygrad/tinygrad — `tinygrad/renderer/cstyle.py` (a C renderer), `tinygrad/runtime/ops_cpu.py` (a CPU runtime), `tinygrad/uop/ops.py` (`addrspace`, `storage_base`).
