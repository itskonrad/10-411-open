# Compilers for Machine Learning

A hands-on one semester course where students build their own compiler from scratch, starting from elementwise programs and ending with training SOTA LLMs on GPUs. This course aggressively builds on the previous week, and is an exercise in slop management. If you let any slop in early, it will compound and you will not finish the class.

Course description: This course covers the design and implementation of a modern machine learning compiler, and examines the interaction between IR design, hardware capabilities, and the structure of machine learning programs. Topics covered include term rewriting, code generation, movement operators, kernel fusion, memory hierarchies, GPU architecture, automatic differentiation, and flash attention. It is a project course, providing experience with performance-oriented programming, managing a codebase that grows all semester, and working in 1 or 2 person teams, culminating in a compiler capable of training modern LLMs.

Prerequisites: This course has no formal prerequisites, but it is designed for someone who is deeply familiar with the material in 15-213 or equivalent, highly skilled in the language they choose to implement their compiler in, capable of managing programming projects that are long in timeline, and comfortable with C and some GPU programming. There will be frequent in-person quizzes and lectures will not be posted online, so only sign up if you plan to attend class.

This syllabus will outline the spec, but not the implementation. The implementation and choice of programming language is up to the student. There is no starter code. We will establish a universal, simple, interchange format for UOps.

```
# gemm_256x256.uir
%0 = buffer 65536 dtype=f32 slot=0
%1 = buffer 65536 dtype=f32 slot=1
%2 = reshape %0 [256 256 1] 
%3 = reshape %1 [256 1 256]
%4 = mul %2 %3
%5 = reduce %4 op=add pop=1
```

---

* 55% -- compiler (weeks 1-10)
  * 5% -- 10 tests -- due every monday (weeks 1-10), judged on correctness by openly accessible binary oracle
  * 25% -- correctness -- due every wednesday, passing *all* student tests + teacher tests + basic performance gates
  * 15% -- style (did you write slop? can I read your code? can it be simpler?)
  * 10% -- performance (weeks 6-10, graded on a curve)
* 25% -- final project (weeks 11-14)
* 20% -- in person quizzes at the start of class (will be at least 20 of them)

No midterm or final. < 70 = F, 70-80 = C, 80-90 = B, 90+ = A.

---

## Week 1: UOps & Rewrites & Renderer?
**`uops` · `elementwise ops` · `symbolic` · `rewrites` · `renderer`**

Students become familiar with the `UOp` and write a compiler capable of compiling and simplifying elementwise programs. We introduce the graph structure and rewriting. The UOp is hash consed. All shapes are rank 0. We allow rank 1 shapes here, but ALU ops must be rank 0.

```
UOp(op, src:tuple[UOp, ...], arg)
```

Recursive properties introduced:
```
dtype(void,bool,i32,f32)
shape:tuple[int, ...]
cost:int
bounds:tuple[int, int]
```

Ops introduced:
```
CONST -- type determined by the arg 

lambda calculus:
PARAM(ParamArg) -- arg input to the call
CALL(CallArg) -- src[0] is the function body, src[1:] are the params...

lil movement:
STACK(src, ...) -- new leading axis, all src has same shape. until week 4, inputs can only be STACK/CONST.
INDEX -- shape from (n,) -> (), pop axes off the left with srcs

ALU:
CAST/RECIP
ADD/MUL/MAX/XOR
CMPLT -- returns bool
SHL/DIV/MOD -- i32 only
WHERE

ASSERT -- for tests only
```

The graph rewrite engine should be capable of "running" these programs via an interpreter.

Lectures:
* wed - Course intro, turing completeness, the UOp, the format, the first assignment
* fri - ALU stuff, bottom up greedy rewrite engines, const folding
* mon - call/param stuff, symbolic simplification, computer algebra systems

Compilers must be handed in by Wednesday every week before 10 AM class.

## Week 2: Memory & Shape

Students write a renderer and a runtime capable of compiling and executing C programs.

Recursive properties introduced:
```
addrspace(GLOBAL,ALU)
accesses:dict[UOp, tuple[UOp, ...]] <-- a list of UOps that access a buffer
storage_base:UOp
```

Ops introduced:
```
BUFFER(ParamArg) -- global persistent buffer (never in call)
ALLOC(ParamArg) -- call scope storage, example "float a[10]"
SHRINK(offset, shape) -- offset can be symbolic, shape must be integer
LOAD/STORE -- load has 1 src, store has 2, we load/store from/to GLOBAL buffer
AFTER -- AFTER(buf, <store>)
```

This can render (loopless) C functions that act on memory and immediates. Loads and stores must be fully ordered for programs to be valid. Loads and stores are bounds checked to never be out of range.

Lectures:
* wed - toposort and rendering, C refresher
* fri - memory management and runtime
* mon - type systems for shape, dtype, and addrspace

## Week 3: Loops
**`loops` · `gemms` · `convs`**

Recursive properties introduced:
```
ranges:dict[UOp, None]
ended_ranges:dict[UOp, UOp]
```

Ops introduced:
```
RANGE -- src is the end of the range (3 means 0,1,2) and arg is the range name
END -- srcs are (passthrough, range)
```

Should be simple, and we can write gemms and convs in this language. If you still have an interpreter at this point, it's time to write a renderer.

Also, this is the first week you will (likely) require a rewrite engine, in order to order the ranges properly.

## Week 4: Rangeify + Kernel Fusion/Fission
**`broadcasting` · `reduction` · `rangeify`**

We still keep the rank < 2 restriction on shapes, but ALU can be rank 1 now.

Ops introduced:
```
REDUCE (axis count / op)
STAGE -- temp buffer
EXPAND
```

Rangeify removes shapes from all ops. We have to confront questions about materialization here.

## Week 5: Movement Ops
**`movement ops`**

Now we introduce movement ops and loops, allowing rank >= 2 shapes for the first time. Note how you can derive gemms and convs from the basic movement ops. 

Ops introduced:
```
RESHAPE/PERMUTE/PAD
```

STACK supports arbitrary inputs, SHRINK supports STACKs in the params.

FLIP is a composite op here. This compiler is now capable of compiling *any* model, splitting it into kernels to avoid repeated compute, and compiling it to C.

Autodiff only works on pure shape graphs, not STORE, CALL, AFTER, RANGE, END.

Here you will run Qwen, you'll also learn about Taylor expansion for SIN/LOG2/EXP2/SQRT.

## Week 6: Autodiff & Speed
**`autodiff`  · `FLOPS counting` · `fast GEMMs`**

Ops introduced:
```
GRADIENT/DETACH
```

You'll add GRADIENT/DETACH ops and train MNIST. You'll also add a lot of syntactic sugar and make things fast.

Add support for url= and sha256= in BUFFER.

In week 6, timing starts to really matter.

## Weeks 7:  GPUs & Threads & Hardware Accelerators
**`parallel` · `threads` · `GPUs` · `hardware accelerators` · `tensor cores`**

```
axistype(LOOP,GLOBAL,LOCAL)
addrspace(GLOBAL,LOCAL,ALU)
```

Here we add kernels, GPUs, axis mappings, and tensor cores. This can produce decent torch-competitive CUDA/HIP code now.


## Week 8: Memory Hierarchies & Multithreading & Fast Kernels
**`upcasting` · `flash attention`**

Now things get fast. Still only on CPU, but we can now produce SOTA-competitive C code for GEMMs, reduces, and convs.

Ranges can have axis type LOOP, UPCAST, or THREAD.



## Weeks 9–10: Real Models
**`real models` · `symbolic`**

Here we implement a real LLM and train models.

## Weeks 11–End: Student Projects

Use your compiler to implement a paper, port it to strange hardware, mostly anything

---

## At a Glance

| Weeks | Topics | Milestone |
|-------|--------|-----------|
| 1–2 | UOps, elementwise ops, symbolic, rewrites | Compile & simplify elementwise programs to C |
| 3–4 | Loops, movement ops, reduction, rangeify | Compile any model to C (slow, but correct) |
| 5–6 | Memory hierarchies, upcasting, GEMMs, convs | SOTA-competitive CPU code |
| 7–8 | Call, GPUs, accelerators, tensor cores | Torch-competitive CUDA/HIP code |
| 9–10 | Real models, autodiff | Train a real LLM |
| 11+ | Student projects | Choose a project and extend your compiler |
