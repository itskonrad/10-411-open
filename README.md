# 10-411 Open: Compilers for Machine Learning

My unofficial, self-study version of CMU's 10-411 ([course page](https://10-411.com/)), built from its public syllabus: [geohot's gist](https://gist.github.com/geohot/4768597d9dc536446ee2d5de1f29e89d) (copy in [syllabus/](syllabus/syllabus.md)). The course materials are not public, so these chapters are my own, following the syllabus week by week, with GPU work targeting **AMD GPUs (ROCm/HIP)**.

## Contents

0. [Prerequisites](00-prerequisites/README.md)
   - [Lesson 1: what a compiler is](00-prerequisites/README.md#lesson-1-what-a-compiler-is)
   - [Lesson 2: numbers in a machine](00-prerequisites/README.md#lesson-2-numbers-in-a-machine)
   - [Lesson 3: graphs, substitution and intervals](00-prerequisites/README.md#lesson-3-graphs-substitution-and-intervals)
   - [Lesson 4: C, index arithmetic and loop nests](00-prerequisites/README.md#lesson-4-c-index-arithmetic-and-loop-nests)
   - [Lesson 5: what models compute](00-prerequisites/README.md#lesson-5-what-models-compute)
   - [Lesson 6: hardware and performance](00-prerequisites/README.md#lesson-6-hardware-and-performance)
1. [UOps & rewrites](01-uops-and-rewrites/README.md)
   - [Lesson 1: course intro, Turing completeness, the UOp, the format, the first assignment](01-uops-and-rewrites/README.md#lesson-1-course-intro-turing-completeness-the-uop-the-format-the-first-assignment)
   - [Lesson 2: ALU ops, bottom-up greedy rewrite engines, constant folding](01-uops-and-rewrites/README.md#lesson-2-alu-ops-bottom-up-greedy-rewrite-engines-constant-folding)
   - [Lesson 3: call/param, symbolic simplification, computer algebra systems](01-uops-and-rewrites/README.md#lesson-3-callparam-symbolic-simplification-computer-algebra-systems)
2. [Memory & shape](02-memory-and-shape/README.md)
   - [Lesson 1: toposort and rendering, C refresher](02-memory-and-shape/README.md#lesson-1-toposort-and-rendering-c-refresher)
   - [Lesson 2: memory management and runtime](02-memory-and-shape/README.md#lesson-2-memory-management-and-runtime)
   - [Lesson 3: type systems for shape, dtype, and addrspace](02-memory-and-shape/README.md#lesson-3-type-systems-for-shape-dtype-and-addrspace)
3. [Loops](03-loops/README.md)
   - [Lesson 1: loops as values](03-loops/README.md#lesson-1-loops-as-values)
   - [Lesson 2: ordering the ranges](03-loops/README.md#lesson-2-ordering-the-ranges)
   - [Lesson 3: gemms and convs](03-loops/README.md#lesson-3-gemms-and-convs)
4. [Rangeify](04-rangeify/README.md)
5. [Movement ops](05-movement-ops/README.md)
6. [Autodiff & speed](06-autodiff-and-speed/README.md)
7. [GPUs](07-gpus/README.md)
8. [Memory hierarchies](08-memory-hierarchies/README.md)
9. [Real models](09-10-real-models/README.md), weeks 9–10
10. [Student projects](11-student-projects/README.md), weeks 11+

Reference: [the UIR format and conventions](uir.md).

## Doing the course

1. Fork this repo and write your compiler in [compiler/](compiler/README.md), in any language.
2. Each week, read the chapter, write your own tests in [tests/](tests/README.md), and check them with the [oracle](oracle/README.md): `python3 -I oracle/uir.py tests/week1/*.uir`.
3. Extend your compiler until it agrees with the oracle on every example and test so far:

   ```sh
   python3 -I tools/check_compiler.py --week 1 -- <your compiler command>
   ```

Where the syllabus is silent, the chapters follow [tinygrad](https://github.com/tinygrad/tinygrad) and say so. To read the tinygrad files they cite:

```sh
git clone https://github.com/tinygrad/tinygrad.git
git -C tinygrad checkout 07821caeade16a3e954f28af9263666ab0c1bd53
```

## Progress

| Status | Chapters |
|--------|----------|
| Done | 0 Prerequisites, 1 UOps & rewrites, 2 Memory & shape, 3 Loops, plus the UIR reference and the oracle for weeks 1–3 |
| To do | 4 Rangeify, 5 Movement ops, 6 Autodiff & speed, 7 GPUs, 8 Memory hierarchies, 9 Real models, 10 Student projects |

The syllabus is still a draft. This page and the chapters will be updated as it gets refined.
