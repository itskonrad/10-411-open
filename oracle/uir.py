#!/usr/bin/env python3
"""Reference interpreter ("oracle") for UIR, weeks 1-4 of the course.

  python3 -I oracle/uir.py [--week N] [--lowered] FILE.uir [FILE.uir ...]

Prints one line per file on stdout, `<OUTCOME> <file>`, as the released week 1 reference's `./compile` does:
MATCH (the program is valid and its assert holds), MISMATCH (valid, the assert does not hold), REJECTED (invalid
before execution) or OVERBUDGET (a limit is hit). The reason goes to stderr. Exits non-zero unless every file MATCHes.

--week N (default 4): week 1 is the released reference, plus the interpretations in uir.md (flat grammar, i32 and bool, week 1 ops, the limits);
from week 2 on, the course syntax of chapters 2-4 is allowed too (nested `(op ...)`, f32, rank-1 PARAMs), with the
ops introduced up to week N.
--lowered also rejects what rangeify must remove (chapter 4): REDUCE, EXPAND, STAGE and rank-1 ALU ops.

Pipeline: tokens -> hash-consed UOps, each checked as it is built -> whole-program checks -> evaluation -> ASSERT.
Comments name the source of each rule: [uir.md <section>], [ch1] chapter 1, [week1] the released week 1 reference
(summarized in the notes outside the repo), [spec] syllabus/syllabus.md, [ch4] chapter 4, [oracle] a decision listed in
oracle/README.md.
"""
from __future__ import annotations
import math, re, struct, sys
from bisect import bisect_right
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Callable

sys.setrecursionlimit(20000)  # parsing, toposort and evaluation recurse along the graph

I32_MIN, I32_MAX = -2**31, 2**31 - 1
MAX_BYTES, MAX_NODES, MAX_EDGES, MAX_COST = 4096, 100, 300, 1_000_000  # [week1] the limits
ALU_DTYPES = {  # [ch1 ALU table]
  "add": {"i32", "f32", "bool"}, "mul": {"i32", "f32", "bool"}, "max": {"i32", "f32", "bool"},  # bool: OR, AND, OR [oracle]
  "cmplt": {"i32", "f32", "bool"},  # false < true
  "xor": {"i32", "bool"}, "shl": {"i32"}, "div": {"i32"}, "mod": {"i32"}, "recip": {"f32"},
}
ALU_OPS = {*ALU_DTYPES, "cast", "where"}
BINARY: dict[str, Callable[[Any, Any], Any]] = {  # floor // and %, and the zero and shift rules of [week1]
  "add": lambda a, b: a + b, "mul": lambda a, b: a * b, "max": max, "xor": lambda a, b: a ^ b,
  "cmplt": lambda a, b: a < b, "shl": lambda a, b: a * 2**(b % 32),
  "div": lambda a, b: -1 if b == 0 else a // b, "mod": lambda a, b: a if b == 0 else a % b,
}
WEEK1_OPS = {"const", "param", "call", "stack", "index", "assert", "cast", "where",
             "add", "mul", "max", "xor", "cmplt", "shl", "div", "mod"}  # [week1]; `const` is never written
OPS_BY_WEEK = {1: WEEK1_OPS}
OPS_BY_WEEK[2] = OPS_BY_WEEK[1] | {"recip", "buffer", "alloc", "shrink", "load", "store", "after"}  # recip: [ch2]
OPS_BY_WEEK[3] = OPS_BY_WEEK[2] | {"range", "end"}
OPS_BY_WEEK[4] = OPS_BY_WEEK[3] | {"reduce", "stage", "expand"}
ARITY = {"buffer": 1, "alloc": 1, "cast": 1, "recip": 1, "where": 3, "assert": 2, "shrink": 3,
         "load": 1, "store": 2, "range": 1, "end": 2, "reduce": 1, "stage": 1, "expand": 2, **{op: 2 for op in BINARY}}
MIN_ARITY = {"call": 1, "index": 2, "after": 2}
ARG_KEYS = {"param": {"slot", "dtype", "addrspace"}, "buffer": {"slot", "dtype"}, "alloc": {"slot", "dtype"},
            "cast": {"dtype"}, "range": {"slot"}, "reduce": {"op", "pop"}}
REDUCE_OPS = ("add", "mul", "max")  # tinygrad's GroupOp.Reduce [ch4]
LITERALS_MATCH = {*BINARY, "assert", "store", "stack"}  # ops whose sources must match [uir.md Literals]

LOWERED = False  # --lowered: the program must be rangeified [ch4]
WEEK = 4         # --week N
STRICT = False   # week 1: the released reference

def set_week(week: int) -> None:
  global WEEK, STRICT
  WEEK, STRICT = week, week == 1

def dtypes() -> tuple[str, ...]: return ("bool", "i32") if STRICT else ("bool", "i32", "f32")  # [week1]

class UIRError(Exception):
  """An invalid program, or undefined behaviour found while running it."""
  def __init__(self, line: int, kind: str, msg: str):
    super().__init__(msg)
    self.line, self.kind = line, kind

class AssertFailed(Exception): pass

class Overbudget(Exception): pass

def f32(x: float) -> float:
  """Round to the nearest IEEE single, ties to even [uir.md Arithmetic]."""
  try: return struct.unpack("<f", struct.pack("<f", x))[0]
  except OverflowError: return math.copysign(math.inf, x)  # rounds past the largest f32

def wrap32(x: int) -> int: return (x + 2**31) % 2**32 - 2**31

def fit32(lo: int, hi: int) -> tuple[int, int]:
  """An i32 interval that could wrap widens to the full range [uir.md Bounds]."""
  return (lo, hi) if I32_MIN <= lo and hi <= I32_MAX else (I32_MIN, I32_MAX)

def full_bounds(dtype: str) -> tuple[int, int] | None:
  return {"i32": (I32_MIN, I32_MAX), "bool": (0, 1)}.get(dtype)

def show(v: Any) -> str:
  if isinstance(v, list): return "[" + " ".join(map(show, v)) + "]"
  return str(v).lower() if isinstance(v, bool) else repr(v)

# ***** the UOp *****

@dataclass(eq=False)  # identity equality: UOps are hash-consed
class UOp:
  op: str
  src: tuple[UOp, ...]
  arg: Any
  line: int                               # first line that built it, for error messages
  dtype: str = "void"
  shape: tuple[int, ...] = ()
  space: str = "ALU"                      # addrspace: GLOBAL (memory) or ALU (values) [spec week 2]
  bounds: tuple[int, int] | None = None   # i32 and bool only [uir.md Bounds]
  ranges: frozenset = frozenset()         # open RANGEs [spec week 3]
  ended: frozenset = frozenset()          # RANGEs closed by an END below this node
  params: frozenset = frozenset()         # PARAMs not bound by a CALL

  def __repr__(self) -> str: return f"<{self.op} line {self.line}>"

def fail(u: UOp, kind: str, msg: str): raise UIRError(u.line, kind, msg)

def is_length(u: UOp) -> bool: return u.op == "const" and type(u.arg) is int and u.arg >= 1

def storage(u: UOp) -> UOp:
  """storage_base [spec week 2]: the BUFFER or ALLOC under INDEX, SHRINK and AFTER."""
  while u.op not in ("buffer", "alloc"): u = u.src[0]
  return u

def toposort(root: UOp, enter_calls: bool) -> list[UOp]:
  """`root` and everything it depends on, sources first."""
  order: list[UOp] = []
  seen: set[UOp] = set()
  def visit(u: UOp) -> None:
    if u in seen: return
    seen.add(u)
    for s in (u.src if enter_calls or u.op != "call" else u.src[1:]): visit(s)
    order.append(u)
  visit(root)
  return order

# ***** properties and checks of one UOp, run once, when it is first built *****

def check(u: UOp) -> None:
  if u.op == "param" and len(u.src) not in (1, 2): fail(u, "op", f"param takes a shape and optional limits, got {len(u.src)} sources")
  if u.op in ARITY and len(u.src) != ARITY[u.op]: fail(u, "op", f"{u.op} takes {ARITY[u.op]} sources, got {len(u.src)}")
  if len(u.src) < MIN_ARITY.get(u.op, 0): fail(u, "op", f"{u.op} takes at least {MIN_ARITY[u.op]} sources")
  for s in u.src:
    if s.op == "assert": fail(u, "root", "assert is only allowed as the root [uir.md Programs and ASSERT]")
    if s.op == "stack" and not s.src and u.op not in ("param", "buffer", "alloc", "expand"):
      fail(u, "shape", "[] is only a shape, for param, buffer, alloc and expand [oracle]")
  u.ranges = frozenset().union(*(s.ranges for s in u.src))
  u.ended = frozenset().union(*(s.ended for s in u.src))
  u.params = frozenset().union(*(s.params for s in u.src))
  (check_alu if u.op in ALU_OPS else CHECKS[u.op])(u)
  if LOWERED and (u.op in ("reduce", "expand", "stage") or (u.op in ALU_OPS and u.shape)):
    fail(u, "lowered", f"{u.op} of shape {u.shape} is left for rangeify to lower [ch4]")
  if u.ranges & u.ended: fail(u, "range", "uses a loop's RANGE after its END [notes ranges]")

def check_const(u: UOp) -> None:
  u.dtype = {bool: "bool", int: "i32", float: "f32"}[type(u.arg)]  # [uir.md Literals]
  if u.dtype == "i32" and not I32_MIN <= u.arg <= I32_MAX:
    fail(u, "dtype", f"{u.arg} does not fit in i32 [uir.md Literals]")
  if u.dtype != "f32": u.bounds = (int(u.arg), int(u.arg))

def check_stack(u: UOp) -> None:
  if not u.src: u.shape = (0,); return  # the empty shape `[]`, checked by its user
  for s in u.src:
    if s.op == "stack": fail(u, "rank", "rank 2 stacks arrive in week 5 [spec week 4]")
    if s.op != "const": fail(u, "stack", "stack inputs must be constants until week 5 [spec week 1, week 5; ch4 Spec notes]")
  u.dtype, u.shape = same_dtype(u, u.src), (len(u.src),)
  if u.dtype != "f32": u.bounds = (min(s.bounds[0] for s in u.src), max(s.bounds[1] for s in u.src))

def same_dtype(u: UOp, srcs: tuple[UOp, ...]) -> str:
  dtypes = {s.dtype for s in srcs}
  if len(dtypes) > 1:
    fail(u, "dtype", f"mixed dtypes {' and '.join(s.dtype for s in srcs)}: write a cast [uir.md Mixing dtypes]")
  return srcs[0].dtype

def need_value(u: UOp, s: UOp, what: str) -> None:
  """`s` must be an ALU value [spec week 2 addrspace]."""
  if s.op == "stack" and not s.src: fail(u, "shape", f"{what} is [], which is only a shape [oracle]")
  if s.dtype == "void": fail(u, "dtype", f"{what} has no value (it is an effect)")
  if s.space != "ALU": fail(u, "addrspace", f"{what} is GLOBAL memory: load it first [spec week 2]")

def need_index(u: UOp, s: UOp, what: str) -> None:
  need_value(u, s, what)
  if s.shape != (): fail(u, "rank", f"{what} has shape {s.shape}; an index is rank 0 [spec week 1]")
  if s.dtype != "i32": fail(u, "dtype", f"{what} must be i32, not {s.dtype} [uir.md Literals]")

def check_alu(u: UOp) -> None:
  """ALU ops are elementwise; from week 4 they may be rank 1, with every source of one shape [spec week 4, ch4]."""
  for i, s in enumerate(u.src): need_value(u, s, f"source {i} of {u.op}")
  if len({s.shape for s in u.src}) > 1:
    fail(u, "shape", f"{u.op} of shapes {' and '.join(str(s.shape) for s in u.src)}: broadcast with expand [ch4]")
  u.shape = u.src[0].shape
  if WEEK < 4 and u.shape: fail(u, "shape", f"{u.op} of shape {u.shape}: ALU ops take scalars until chapter 4 [week1, spec week 1]")
  if u.op == "cast": u.dtype = u.arg
  elif u.op == "where":
    if u.src[0].dtype != "bool": fail(u, "dtype", "where's condition must be bool [ch1]")
    u.dtype = same_dtype(u, u.src[1:])
  else:
    dtype = same_dtype(u, u.src)
    if dtype not in ALU_DTYPES[u.op]: fail(u, "dtype", f"{u.op} does not take {dtype} [ch1 ALU table]")
    u.dtype = "bool" if u.op == "cmplt" else dtype
  if u.dtype in ("i32", "bool"): u.bounds = alu_bounds(u)

def alu_bounds(u: UOp) -> tuple[int, int]:
  """Exactly the table in uir.md Bounds, no tighter and no looser: validation depends on it. A bool sum, product or max
  is normalized to bool: only zero [0, 0], never zero [1, 1], else [0, 1] [week1]."""
  lo, hi = ops_bounds(u)
  if u.dtype == "bool" and u.op in ("add", "mul", "max"):
    return (0, 0) if (lo, hi) == (0, 0) else (1, 1) if lo > 0 or hi < 0 else (0, 1)
  return (lo, hi)

def ops_bounds(u: UOp) -> tuple[int, int]:
  if all(s.bounds and s.bounds[0] == s.bounds[1] for s in u.src): return fold(u)
  if u.op == "where":
    c, x, y = (s.bounds for s in u.src)
    return x if c == (1, 1) else y if c == (0, 0) else (min(x[0], y[0]), max(x[1], y[1]))
  if u.op == "cast": return cast_bounds(u.src[0], u.dtype)
  if u.src[0].dtype == "f32": return full_bounds(u.dtype)  # cmplt of f32s
  (a0, a1), (b0, b1) = u.src[0].bounds, u.src[1].bounds  # from here on, a binary op on i32s or bools
  if u.op == "cmplt": return (1, 1) if a1 < b0 else (0, 0) if a0 >= b1 else (0, 1)
  if u.op == "add": return fit32(a0 + b0, a1 + b1)
  if u.op == "max": return (max(a0, b0), max(a1, b1))
  if u.op == "mul":
    ends = [a0 * b0, a0 * b1, a1 * b0, a1 * b1]
    return fit32(min(ends), max(ends))
  c = b0 if b0 == b1 else None  # "fixed y" [week1]
  if u.op == "div" and c is not None:
    ends = [-1, -1] if c == 0 else [a0 // c, a1 // c]
    return fit32(min(ends), max(ends))
  if u.op == "mod" and c is not None:
    if c == 0: return (a0, a1)
    if a0 // c == a1 // c: return (min(a0 % c, a1 % c), max(a0 % c, a1 % c))
    return (0, c - 1) if c > 0 else (c + 1, 0)
  if u.op == "shl":
    ends = [x * 2**k for x in (a0, a1) for k in shift_amounts(b0, b1)]
    return fit32(min(ends), max(ends))
  return full_bounds(u.dtype)

def shift_amounts(lo: int, hi: int) -> range | list[int]:
  """The values of y mod 32 for y in [lo, hi] [week1 shl]."""
  return range(32) if hi - lo >= 31 else sorted({y % 32 for y in range(lo, hi + 1)})

def cast_bounds(s: UOp, dtype: str) -> tuple[int, int]:
  if s.dtype == dtype or (s.dtype, dtype) == ("bool", "i32"): return s.bounds  # B_x, normalized to the target [week1 cast]
  if (s.dtype, dtype) == ("i32", "bool"):
    lo, hi = s.bounds
    return (0, 0) if (lo, hi) == (0, 0) else (1, 1) if lo > 0 or hi < 0 else (0, 1)
  return full_bounds(dtype)

def fold(u: UOp) -> tuple[int, int]:
  """All sources exact: the bounds are the op applied to them."""
  vals = [bool(s.bounds[0]) if s.dtype == "bool" else s.bounds[0] for s in u.src]
  try: v = int(alu(u, vals))
  except UIRError: return full_bounds(u.dtype)  # undefined; running the program reports it
  return (v, v)

def shape_src(u: UOp, s: UOp) -> tuple[int, ...]:
  """A shape source: `[]` for (), or a length n for (n,) [uir.md Ops by chapter]."""
  if s.op == "stack" and not s.src: return ()
  if is_length(s): return (s.arg,)
  fail(u, "shape", f"{u.op}'s shape must be [] or a length")

def check_define(u: UOp) -> None:
  """PARAM, BUFFER, ALLOC: src[0] is the shape; a PARAM may have src[1], its limits; arg is (slot, dtype)."""
  u.shape = shape_src(u, u.src[0])
  u.dtype = u.arg[1]
  if u.op == "param":
    if STRICT and u.shape: fail(u, "shape", "a week 1 param is a scalar: its shape is [] [week1]")
    u.params, u.bounds = frozenset({u}), full_bounds(u.dtype)
    if len(u.src) == 2: u.bounds = param_limits(u)
  else: u.space = "GLOBAL"

def param_limits(u: UOp) -> tuple[int, int]:
  """`[l h]`: two literals of the param's dtype, l <= h; the param's bounds [week1 param]."""
  lim = u.src[1]
  if lim.op != "stack" or len(lim.src) != 2 or any(e.op != "const" for e in lim.src):
    fail(u, "arg", "a param's limits are a stack of two literals, [l h] [week1]")
  if u.dtype == "f32": fail(u, "dtype", "limits are for i32 and bool params [week1]")
  if lim.dtype != u.dtype: fail(u, "dtype", f"limits are {lim.dtype}, the param is {u.dtype} [week1]")
  lo, hi = (int(e.arg) for e in lim.src)
  if lo > hi: fail(u, "arg", f"limits [{lo} {hi}]: l must be at most h [week1]")
  return (lo, hi)

def check_index(u: UOp) -> None:
  value, idx = u.src[0], u.src[-1]
  if value.dtype == "void": fail(u, "dtype", "index of an effect")
  if len(value.shape) != 1: fail(u, "rank", f"index needs a rank-1 value, got shape {value.shape}")
  if len(u.src) > 2: fail(u, "rank", "one index per axis, and shapes are at most rank 1 [spec week 4]")
  need_index(u, idx, "the index")
  in_bounds(u, idx.bounds, 1, value.shape[0])
  u.dtype, u.space = value.dtype, value.space
  u.bounds = value.bounds if value.space == "ALU" else None

def in_bounds(u: UOp, bounds: tuple[int, int], size: int, n: int) -> None:
  """Elements [lo, hi + size - 1] must provably lie in [0, n-1] [ch1 INDEX, spec week 2, uir.md Validation]."""
  if bounds[0] < 0 or bounds[1] + size > n:
    fail(u, "bounds", f"index range [{bounds[0]}, {bounds[1] + size - 1}] is not inside [0, {n - 1}]")

def check_shrink(u: UOp) -> None:
  """SHRINK(buffer, offset, size) [notes SHRINK]: a window of `size` elements starting at `offset`."""
  buf, offset, size = u.src
  if buf.space != "GLOBAL": fail(u, "addrspace", "shrink takes memory [oracle]")
  if len(buf.shape) != 1: fail(u, "rank", "shrink takes rank-1 memory [oracle]")
  need_index(u, offset, "shrink's offset")
  if not is_length(size): fail(u, "shape", "shrink's size must be a constant >= 1 [spec week 2]")
  in_bounds(u, offset.bounds, size.arg, buf.shape[0])
  u.dtype, u.shape, u.space = buf.dtype, (size.arg,), "GLOBAL"

def check_load(u: UOp) -> None:
  addr = u.src[0]
  if addr.space != "GLOBAL": fail(u, "addrspace", "load reads GLOBAL memory [spec week 2]")
  u.dtype, u.shape, u.bounds = addr.dtype, addr.shape, full_bounds(addr.dtype)

def check_store(u: UOp) -> None:
  addr, value = u.src
  if addr.space != "GLOBAL": fail(u, "addrspace", "store writes GLOBAL memory [spec week 2]")
  if value.dtype == "void": fail(u, "dtype", "store's value is an effect")
  if value.space != "ALU": fail(u, "addrspace", "store's value is GLOBAL memory: load it first [spec week 2]")
  if value.shape != addr.shape: fail(u, "shape", f"storing shape {value.shape} into shape {addr.shape} [oracle]")
  same_dtype(u, u.src)

def check_after(u: UOp) -> None:
  """AFTER(value, deps...) [notes AFTER]: passes value through; its users run after the deps."""
  for d in u.src[1:]:
    if d.dtype != "void" and d.op != "range":
      fail(u, "dtype", "after waits for effects (store, end) or a range [oracle]")
  v = u.src[0]
  u.dtype, u.shape, u.space, u.bounds = v.dtype, v.shape, v.space, v.bounds

def check_range(u: UOp) -> None:
  if not is_length(u.src[0]): fail(u, "range", "a range's end must be a constant >= 1 [uir.md Bounds]")
  u.dtype, u.bounds, u.ranges = "i32", (0, u.src[0].arg - 1), frozenset({u})

def check_end(u: UOp) -> None:
  effect, r = u.src
  if r.op != "range": fail(u, "range", "end's second source must be a range [spec week 3]")
  if effect.dtype != "void": fail(u, "dtype", "end's first source must be an effect (store, end) [notes END]")
  if r not in effect.ranges: fail(u, "range", "end's effect does not use its range [oracle]")
  u.ranges, u.ended = u.ranges - {r}, u.ended | {r}

def check_call(u: UOp) -> None:
  """CALL(body, args...) binds PARAM slot i to args[i] [ch1 lesson 3]. The body is closed and checked like a program."""
  body, args = u.src[0], u.src[1:]
  if body.dtype == "void" or body.space != "ALU": fail(u, "call", "a call's body must be a value [oracle]")
  if any(n.op == "buffer" for n in toposort(body, enter_calls=True)):
    fail(u, "call", "BUFFER is never in a call [spec week 2]")
  if body.ranges: fail(u, "range", "a call's body has an open range [notes ranges]")
  slots: dict[int, UOp] = {}
  for p in sorted(body.params, key=lambda p: (p.arg[0], p.line)):
    if slots.setdefault(p.arg[0], p) is not p: fail(u, "call", f"two different PARAMs use slot {p.arg[0]}")
  needed = max(slots, default=-1) + 1  # an unused slot below the highest still takes an argument [oracle]
  if len(args) < needed: fail(u, "call", f"the body needs {needed} arguments, got {len(args)} [ch1]")  # more is fine: unused slots
  if STRICT and (body.shape != () or any(a.shape != () for a in args)):
    fail(u, "rank", "a week 1 call takes and returns scalars [week1]")
  for i, a in enumerate(args):
    if a.dtype == "void" or a.space != "ALU": fail(u, "call", f"argument {i} must be a value, not an effect or memory")
    p = slots.get(i)
    if p is not None and (a.dtype, a.shape) != (p.dtype, p.shape):
      fail(u, "call", f"argument {i} must be {p.dtype} {p.shape}, got {a.dtype} {a.shape} [ch1]")
    if p is not None and p.bounds and a.bounds and not (p.bounds[0] <= a.bounds[0] and a.bounds[1] <= p.bounds[1]):
      fail(u, "bounds", f"argument {i} has bounds {list(a.bounds)}, outside the param's limits {list(p.bounds)} [week1]")
  check_scope(body)
  u.dtype, u.shape, u.bounds = body.dtype, body.shape, body.bounds
  # the body's PARAMs are bound here, and its loops are its own
  u.params = frozenset().union(*(a.params for a in args))
  u.ended = frozenset().union(*(a.ended for a in args))

def check_reduce(u: UOp) -> None:
  """REDUCE(x) op=add|mul|max pop=n: combines the n leading axes of x into one value per remaining element [spec week 4]."""
  x, (op, pop) = u.src[0], u.arg
  need_value(u, x, "reduce's source")
  if pop > len(x.shape): fail(u, "shape", f"reduce pops {pop} axes from shape {x.shape} [ch4]")
  if x.dtype not in ("i32", "f32"): fail(u, "dtype", f"reduce takes i32 and f32 sources, not {x.dtype} [ch4]")
  u.dtype, u.shape, u.bounds = x.dtype, x.shape[pop:], full_bounds(x.dtype)  # [uir.md Bounds]

def check_expand(u: UOp) -> None:
  """EXPAND(x, shape): x repeated along new leading axes [spec week 4, ch4]."""
  x = u.src[0]
  need_value(u, x, "expand's source")
  if x.shape: fail(u, "rank", f"expand of shape {x.shape}: its source is rank 0 until week 5 [spec week 4, ch4]")
  u.shape = shape_src(u, u.src[1])
  u.dtype, u.bounds = x.dtype, x.bounds

def check_stage(u: UOp) -> None:
  """STAGE(x): the value x, kept in a temp buffer when compiled [spec week 4, ch4]. Its bounds are those of a value
  loaded back from memory, the dtype's full range [uir.md Bounds]."""
  need_value(u, u.src[0], "stage's source")
  u.dtype, u.shape, u.bounds = u.src[0].dtype, u.src[0].shape, full_bounds(u.src[0].dtype)

def check_assert(u: UOp) -> None:
  actual, expected = u.src
  for s in u.src:
    if s.dtype == "void": fail(u, "dtype", "assert compares values, not effects")
  if expected.op != "const" and not (expected.op == "stack" and expected.src and all(e.op == "const" for e in expected.src)):
    fail(u, "root", "assert's expected value is a literal or a stack of literals [week1 assert]")
  if STRICT and actual.shape != (): fail(u, "rank", "a week 1 assert returns a scalar: ALU returns are scalar [week1]")
  if u.src[0].shape != u.src[1].shape: fail(u, "shape", f"assert compares shapes {u.src[0].shape} and {u.src[1].shape}")
  same_dtype(u, u.src)

CHECKS = {"const": check_const, "stack": check_stack, "param": check_define, "buffer": check_define,
          "alloc": check_define, "index": check_index, "shrink": check_shrink, "load": check_load,
          "store": check_store, "after": check_after, "range": check_range, "end": check_end,
          "call": check_call, "assert": check_assert, "reduce": check_reduce, "expand": check_expand,
          "stage": check_stage}

# ***** whole-program checks, on the graph the root reaches [uir.md Validation] *****

def check_scope(root: UOp) -> None:
  """Checks on a program or call body, not entering inner call bodies (each is checked at its CALL)."""
  nodes = toposort(root, enter_calls=False)
  ends: dict[UOp, UOp] = {}
  for u in nodes:
    if u.op == "end" and ends.setdefault(u.src[1], u) is not u:
      fail(u, "range", f"the range on line {u.src[1].line} is ended twice; group effects with after [oracle]")
  loops = {u for u in nodes if u.op == "range"}
  for call in (u for u in nodes if u.op == "call"):
    for r in toposort(call.src[0], enter_calls=True):
      if r in loops:
        fail(call, "range", f"the range on line {r.line} is used both in a call body and outside it [oracle]")
  check_order(nodes)

def check_order(nodes: list[UOp]) -> None:
  """Every load/store pair on one buffer, at least one a store, must be ordered by src edges [spec week 2]."""
  accesses: dict[UOp, list[UOp]] = {}
  for u in nodes:
    if u.op in ("load", "store"): accesses.setdefault(storage(u.src[0]), []).append(u)
  for group in accesses.values():
    below = {a: set(toposort(a, enter_calls=False)) for a in group}
    for a, b in combinations(group, 2):
      if "store" in (a.op, b.op) and a not in below[b] and b not in below[a]:
        fail(b, "order", f"{a.op} (line {a.line}) and {b.op} (line {b.line}) of one buffer are not ordered: use after")

def check_program(root: UOp, asserts: list[UOp], last_line: int, bound: list[UOp]) -> None:
  def fail_root(kind: str, msg: str): raise UIRError(last_line, kind, msg)
  if root.op != "assert": fail_root("root", "the last line must be an assert [uir.md Programs and ASSERT]")
  for a in asserts:
    if a is not root: fail(a, "root", "a program has one assert, on its last line [uir.md Programs and ASSERT]")
  reach = set(toposort(root, enter_calls=True))  # call bodies and unused arguments count [week1]
  for u in bound:
    if u not in reach: fail(u, "root", "this line is not reachable from the assert: every node must be [week1]")
  if root.params: fail(min(root.params, key=lambda p: p.line), "call", "a PARAM is used outside a call [oracle]")
  if root.ranges: fail_root("range", "the root uses a range that is never ended [notes ranges]")
  check_scope(root)
  slots: dict[tuple[str, int], UOp] = {}  # buffers (BUFFER, ALLOC) and loops are numbered per kind [uir.md Slots]
  for u in sorted(toposort(root, enter_calls=True), key=lambda u: u.line):
    if u.op not in ("buffer", "alloc", "range"): continue
    key = ("range", u.arg) if u.op == "range" else ("buffer", u.arg[0])
    if (other := slots.setdefault(key, u)) is not u:
      fail(u, "arg", f"{key[0]} slot {key[1]} is already used on line {other.line}")

# ***** parsing *****

TOKEN = re.compile(r"""#.*|%\w+\s*=|\w+=|%\w+|[\[\](){}]|'(?:[^'\\]|\\.)*'|[^\s\[\](){}#]+""", re.ASCII)

@dataclass
class Token:
  text: str
  line: int
  col: int = 0
  end: int = 0

def literal(t: str) -> bool | int | float | None:
  """true false 0x2a -3 1.5 1e+20 -inf nan, as tinygrad's uir.py reads them; None if `t` is not a literal."""
  if t in ("true", "false"): return t == "true"
  if re.fullmatch(r"0x[0-9a-fA-F]+", t): return int(t, 16)
  if re.fullmatch(r"-?[0-9]+", t):
    digits = t.lstrip("-").lstrip("0")
    return int(t) if len(digits) <= 12 else (-1 if t.startswith("-") else 1) * 2**40  # too big for i32 either way
  if not STRICT and re.fullmatch(r"-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?|-?inf|nan", t): return float(t)  # no floats in week 1
  return None

def is_assign(t: str) -> bool: return re.fullmatch(r"%\w+\s*=", t, re.ASCII) is not None

class Parser:
  """`%name = op srcs key=value` lines [uir.md Lines]. A source is a %name, a literal, a [stack] or nested (op ...)."""
  def __init__(self, text: str, checking: bool = True):
    starts = [0] + [m.end() for m in re.finditer("\n", text)]  # a DEF may span lines: tokenize the whole text
    def where(offset: int) -> tuple[int, int]:
      line = bisect_right(starts, offset)
      return line, offset - starts[line - 1]
    self.toks = [Token(m[0], where(m.start())[0], where(m.start())[1], where(m.start())[1] + len(m[0]))
                 for m in TOKEN.finditer(text) if not m[0].startswith("#")]
    self.pos = 0
    self.cache: dict[tuple, UOp] = {}
    self.asserts: list[UOp] = []
    self.checking = checking  # False: only parse, to count nodes and edges before validating [week1 limits]

  def peek(self) -> str | None: return self.toks[self.pos].text if self.pos < len(self.toks) else None

  def next(self, what: str) -> Token:
    if self.pos == len(self.toks):
      raise UIRError(self.toks[-1].line if self.toks else 1, "parse", f"expected {what}, got end of file")
    self.pos += 1
    return self.toks[self.pos - 1]

  def at_end(self) -> bool:
    t = self.peek()
    return t is None or t in (")", "]", "}") or is_assign(t)

  def program(self) -> UOp:
    names: dict[str, UOp] = {}
    root, last_line, bound = None, 1, []
    while self.peek() is not None:
      t = self.next("'%name ='")
      if not is_assign(t.text): raise UIRError(t.line, "parse", f"expected '%name =', got {t.text!r}")
      name = t.text[:-1].rstrip()
      if name in names: raise UIRError(t.line, "parse", f"{name} is already defined")
      root, last_line = self.value(names, bare=True), t.line
      names[name] = root
      bound.append(root)
    if root is None: raise UIRError(1, "parse", "empty program")
    if not self.checking:
      nodes, edges = len(self.cache), sum(len(u.src) for u in self.cache.values())
      if nodes >= MAX_NODES or edges >= MAX_EDGES:
        raise Overbudget(f"{nodes} nodes and {edges} source edges after parsing; the limits are {MAX_NODES - 1} and {MAX_EDGES - 1} [week1]")
      return root
    check_program(root, self.asserts, last_line, bound)
    return root

  def value(self, names: dict[str, UOp], bare: bool = False) -> UOp:
    t = self.next("a value")
    if t.text == "{": raise UIRError(t.line, "parse", "scoped blocks arrive in week 6")
    if t.text == "(":
      if STRICT: raise UIRError(t.line, "parse", "nested (op ...) is not in the week 1 grammar: give the op its own line [week1]")
      return self.expr(names, self.next("an op"), ")")
    if t.text == "[":
      srcs, inline = self.sources(names)
      if self.next("']'").text != "]": raise UIRError(t.line, "parse", "expected ']'")
      return self.build("stack", self.type_literals("stack", srcs, inline, t.line), None, t.line)
    if is_assign(t.text): raise UIRError(t.line, "parse", f"expected a value, got {t.text!r}")
    if t.text.startswith("%"):
      if t.text not in names: raise UIRError(t.line, "parse", f"{t.text} is not defined")
      return names[t.text]
    if (v := literal(t.text)) is not None: return self.build("const", (), f32(v) if type(v) is float else v, t.line)
    if bare and re.fullmatch(r"[a-z_0-9]+", t.text): return self.expr(names, t, None)  # `%x = add ...`
    raise UIRError(t.line, "parse", f"{t.text!r} is not a %name or a literal")

  def sources(self, names: dict[str, UOp]) -> tuple[tuple[UOp, ...], list[bool]]:
    """Sources up to a closing bracket, a key= or the next line, and whether each is inline (a literal or [stack])."""
    srcs, inline = [], []
    while not self.at_end() and not self.peek().endswith("="):
      inline.append(self.peek() == "[" or literal(self.peek()) is not None or self.inline_expand())
      srcs.append(self.value(names))
    return tuple(srcs), inline

  def inline_expand(self) -> bool:
    """`(expand <literal> ...)` is matched like its literal [uir.md Literals]."""
    t = [tok.text for tok in self.toks[self.pos:self.pos + 3]]
    return len(t) == 3 and t[:2] == ["(", "expand"] and literal(t[2]) is not None

  def expr(self, names: dict[str, UOp], op: Token, close: str | None) -> UOp:
    if op.text == "const": raise UIRError(op.line, "op", "a constant is written as its literal, not as const [week1]")
    if op.text not in OPS_BY_WEEK[WEEK]:
      raise UIRError(op.line, "op", f"unknown op {op.text!r} (week {WEEK} has {' '.join(sorted(OPS_BY_WEEK[WEEK] - {'const'}))})")
    srcs, inline = self.sources(names)
    kv: dict[str, Any] = {}
    while not self.at_end():
      k = self.next("key=")
      if not k.text.endswith("="):
        raise UIRError(k.line, "parse", f"sources come before key=value args, got {k.text!r}")
      if k.text[:-1] in kv: raise UIRError(k.line, "arg", f"{k.text} appears twice")
      kv[k.text[:-1]] = self.arg_value(k)
    if close is not None and self.next(repr(close)).text != close:
      raise UIRError(op.line, "parse", f"expected {close!r}")
    return self.build(op.text, self.type_literals(op.text, srcs, inline, op.line), make_arg(op, kv), op.line)

  def arg_value(self, key: Token) -> Any:
    t = self.next("a value")
    if STRICT and (t.line, t.col) != (key.line, key.end):
      raise UIRError(t.line, "parse", f"{key.text}{t.text}: key=value is one token, with no spaces [week1]")
    if STRICT and key.text == "slot=" and not re.fullmatch(r"[0-9]+", t.text):
      raise UIRError(t.line, "arg", f"slot is an unsigned decimal number, got {t.text!r} [week1]")
    if t.text == "[":
      if STRICT: raise UIRError(t.line, "parse", "an attribute value is one token, not a list [week1]")
      items = []
      while self.peek() not in ("]", None): items.append(self.arg_value(key))
      self.next("']'")
      return tuple(items)
    if t.text in ("(", ")", "]", "{", "}") or is_assign(t.text):
      raise UIRError(t.line, "parse", f"unexpected {t.text!r} in an arg")
    v = literal(t.text)
    return t.text if v is None else v

  def build(self, op: str, srcs: tuple[UOp, ...], arg: Any, line: int) -> UOp:
    """The hash-consed UOp(op, srcs, arg), checked the first time it is built [ch1 hash-consing]."""
    key = (op, srcs, type(arg), repr(arg))  # repr keeps 0.0 and -0.0 apart and makes all NaNs one key
    if key not in self.cache:
      u = UOp(op, srcs, arg, line)
      if self.checking: check(u)
      self.cache[key] = u
      if op == "assert": self.asserts.append(u)
    return self.cache[key]

  def type_literals(self, op: str, srcs: tuple[UOp, ...], inline: list[bool], line: int) -> tuple[UOp, ...]:
    """An inline int literal that must match an f32 is read as a float [uir.md Literals].
    check() reports the other mismatches."""
    if not self.checking: return srcs  # no dtypes yet; only counting
    if op == "where" and len(srcs) == 3: return (srcs[0], *self.match(srcs[1:], inline[1:], line))
    if op == "call" and srcs:
      dtypes = {p.arg[0]: p.arg[1] for p in srcs[0].params}
      args = (self.as_dtype(a, dtypes.get(i), line) if inline[1 + i] else a for i, a in enumerate(srcs[1:]))
      return (srcs[0], *args)
    return self.match(srcs, inline, line) if op in LITERALS_MATCH and srcs else srcs

  def match(self, srcs: tuple[UOp, ...], inline: list[bool], line: int) -> tuple[UOp, ...]:
    typed = [s.dtype for s, lit in zip(srcs, inline) if not lit] or [s.dtype for s in srcs]
    dtype = "f32" if "f32" in typed else typed[0]
    for s, lit in zip(srcs, inline):  # only an inline literal adopts a dtype; a named one is already typed
      if lit and dtype == "i32" and s.op in ("const", "expand") and s.dtype == "f32":
        raise UIRError(line, "dtype", f"float literal {show(lit_value(s))} cannot be i32 [uir.md Literals]")
    return tuple(self.as_dtype(s, dtype, line) if lit else s for s, lit in zip(srcs, inline))

  def as_dtype(self, u: UOp, dtype: str | None, line: int) -> UOp:
    if dtype != "f32" or u.dtype != "i32": return u
    if u.op == "const": return self.build("const", (), f32(float(u.arg)), line)
    if u.op == "stack": return self.build("stack", tuple(self.as_dtype(s, dtype, line) for s in u.src), None, line)
    if u.op == "expand": return self.build("expand", (self.as_dtype(u.src[0], dtype, line), u.src[1]), None, line)
    return u

def lit_value(u: UOp) -> Any: return u.arg if u.op == "const" else u.src[0].arg

def make_arg(op: Token, kv: dict[str, Any]) -> Any:
  """Each op has a fixed set of keys [uir.md Arguments]; all of them are required."""
  keys = ARG_KEYS.get(op.text, set())
  if set(kv) != keys:
    raise UIRError(op.line, "arg", f"{op.text} takes args {sorted(keys) or 'none'}, got {sorted(kv) or 'none'}")
  if "slot" in kv and (type(kv["slot"]) is not int or kv["slot"] < 0):
    raise UIRError(op.line, "arg", f"slot must be an integer >= 0, got {kv['slot']!r}")
  if "dtype" in kv and kv["dtype"] not in dtypes():
    raise UIRError(op.line, "arg", f"dtype must be one of {' '.join(dtypes())}, got {kv['dtype']!r}")
  if op.text == "param" and kv["addrspace"] != "ALU":
    raise UIRError(op.line, "arg", f"a param's addrspace is ALU, got {kv['addrspace']!r} [week1]")
  if op.text == "reduce":
    if kv["op"] not in REDUCE_OPS:
      raise UIRError(op.line, "arg", f"reduce op must be one of {' '.join(REDUCE_OPS)}, got {kv['op']!r}")
    if type(kv["pop"]) is not int or kv["pop"] < 0:
      raise UIRError(op.line, "arg", f"pop must be an integer >= 0, got {kv['pop']!r}")
    return (kv["op"], kv["pop"])
  if op.text == "cast": return kv["dtype"]
  if op.text == "range": return kv["slot"]
  return (kv["slot"], kv["dtype"]) if kv else None

# ***** evaluation [uir.md Evaluation] *****

@dataclass
class View:
  """An address: `size` elements of `mem` from `offset`, or one element when size is None (rank 0)."""
  mem: list
  offset: int
  size: int | None

  def cells(self) -> slice: return slice(self.offset, self.offset + (self.size or 1))

def enclosing_loops(root: UOp) -> dict[UOp, frozenset]:
  """For each RANGE, the loops around it: loop o encloses loop k when k's END uses o, transitively.
  This is how tinygrad's CFGContext nests loops [uir.md Evaluation]."""
  outer: dict[UOp, frozenset] = {}
  for end in reversed([u for u in toposort(root, enter_calls=False) if u.op == "end"]):  # outer ENDs first
    outer[end.src[1]] = end.ranges.union(*(outer[o] for o in end.ranges))
  return outer

class Frame:
  """One activation, of the program or of one CALL body: its PARAM values and a memo of evaluated nodes.

  A node is evaluated once per assignment of the loops it uses and the loops around those (the memo key), so a node
  that uses no loop is evaluated once, before the loops. BUFFER and ALLOC are nodes too, so the memo also holds this
  frame's memory.
  """
  def __init__(self, args: list[Any], root: UOp):
    self.args = args
    self.outer = enclosing_loops(root)
    self.memo: dict[tuple, Any] = {}

  def eval(self, u: UOp, env: dict[UOp, int]) -> Any:
    loops = u.ranges.union(*(self.outer[r] for r in u.ranges))
    key = (u, frozenset((r, env[r]) for r in loops))
    if key not in self.memo: self.memo[key] = self.compute(u, env)
    return self.memo[key]

  def compute(self, u: UOp, env: dict[UOp, int]) -> Any:
    if u.op == "end":  # run the effect for each value of the range, in order
      for i in range(u.src[1].src[0].arg): self.eval(u.src[0], {**env, u.src[1]: i})
      return None
    if u.op == "call": return Frame([self.eval(a, env) for a in u.src[1:]], u.src[0]).eval(u.src[0], {})
    if u.op == "after":  # the effects first, then the value
      for d in u.src[1:]: self.eval(d, env)
      return self.eval(u.src[0], env)
    vals = [self.eval(s, env) for s in u.src]
    if u.op == "const": return u.arg
    if u.op == "stack": return vals
    if u.op == "range": return env[u]
    if u.op == "param": return self.args[u.arg[0]]
    if u.op in ("buffer", "alloc"):  # contents are undefined until stored [oracle]
      size = u.shape[0] if u.shape else None
      return View([None] * (size or 1), 0, size)
    if u.op == "index":
      v, i = vals
      return View(v.mem, v.offset + i, None) if isinstance(v, View) else v[i]
    if u.op == "shrink": return View(vals[0].mem, vals[0].offset + vals[1], vals[2])
    if u.op == "load": return read(u, vals[0])
    if u.op == "store": return write(*vals)
    if u.op == "assert": return check_equal(u, *(read(u, v) if isinstance(v, View) else v for v in vals))
    if u.op == "stage": return vals[0]
    if u.op == "expand": return [vals[0]] * u.shape[0] if u.shape != u.src[0].shape else vals[0]
    if u.op == "reduce": return reduce(u, vals[0])
    if u.shape: return [alu(u, list(elems)) for elems in zip(*vals)]  # elementwise [ch4]
    return alu(u, vals)

def read(u: UOp, v: View) -> Any:
  items = v.mem[v.cells()]
  if None in items: raise UIRError(u.line, "undefined", "reads memory that was never stored [oracle]")
  return items if v.size is not None else items[0]

def write(v: View, value: Any) -> None:
  v.mem[v.cells()] = value if v.size is not None else [value]

def undefined(u: UOp, why: str):
  raise UIRError(u.line, "undefined", f"{why} is undefined; tests never do it [uir.md Arithmetic]")

def alu(u: UOp, vals: list[Any]) -> Any:
  if u.op == "cast": return cast(u, vals[0])
  if u.op == "where": return vals[1] if vals[0] else vals[2]
  if u.op == "recip": return f32(1 / vals[0]) if vals[0] != 0 else math.copysign(math.inf, vals[0])
  return binary(u, u.op, *vals)

def binary(u: UOp, op: str, a: Any, b: Any) -> Any:
  if op == "max" and u.dtype == "f32":
    if math.isnan(a) or math.isnan(b) or (a == b == 0 and math.copysign(1, a) != math.copysign(1, b)):
      undefined(u, f"max {a} {b}")
  r = BINARY[op](a, b)
  return wrap32(r) if u.dtype == "i32" else f32(r) if u.dtype == "f32" else bool(r)

def reduce(u: UOp, x: Any) -> Any:
  """Fold the popped axis from the identity, in index order, as the lowered loop does [ch4]."""
  op, pop = u.arg
  if pop == 0: return x
  acc = {"add": 0, "mul": 1, "max": I32_MIN if u.dtype == "i32" else -math.inf}[op]
  if u.dtype == "f32": acc = float(acc)
  for v in x: acc = binary(u, op, acc, v)
  return acc

def cast(u: UOp, v: Any) -> Any:
  if u.dtype == "bool": return v != 0
  if u.dtype == "f32": return f32(float(v))
  if isinstance(v, float) and not (math.isfinite(v) and I32_MIN <= math.trunc(v) <= I32_MAX):
    undefined(u, f"cast {v} to i32")
  return int(v)  # truncates toward zero

def check_equal(u: UOp, actual: Any, expected: Any) -> None:
  """Exact, numeric equality: -0.0 equals 0.0 and NaN equals nothing [uir.md Programs and ASSERT]. Element by
  element, because list == treats a NaN object as equal to itself."""
  pairs = zip(actual, expected) if isinstance(actual, list) else [(actual, expected)]
  if not all(a == e for a, e in pairs):
    raise AssertFailed(f"line {u.line}: got {show(actual)}, expected {show(expected)}")

# ***** cost [week1] *****

def own_cost(u: UOp, bodies: dict[UOp, int]) -> int:
  """What one node costs: N result elements for an ALU op, CAST and STACK; 1 for INDEX and `[]`; 0 for CONST, PARAM and
  ASSERT; 1 + C(body) for CALL. Ops from later weeks have no released cost: 0."""
  n = math.prod(u.shape)
  if u.op == "stack": return n if u.src else 1
  if u.op == "index": return 1
  if u.op == "call": return 1 + scope_cost(u.src[0], bodies)
  return n if u.op in ALU_OPS else 0

def scope_cost(root: UOp, bodies: dict[UOp, int] | None = None) -> int:
  """C(root): the cost of each node `root` reaches, once; a CALL's arguments are followed, its body is charged as C(f)."""
  bodies = {} if bodies is None else bodies
  if root not in bodies: bodies[root] = sum(own_cost(u, bodies) for u in toposort(root, enter_calls=False))
  return bodies[root]

# ***** driver *****

OUTCOMES = ("MATCH", "MISMATCH", "REJECTED", "OVERBUDGET")

@dataclass
class Outcome:
  status: str  # one of OUTCOMES
  kind: str = ""
  line: int = 0
  message: str = ""

  def report(self, path: str) -> str: return f"{self.status} {path}"

  def detail(self, path: str) -> str:
    """Why, for stderr."""
    if self.status == "MATCH": return ""
    if self.status == "MISMATCH": return f"{path}: {self.message}"
    return f"{path}:{self.line}: {self.kind}: {self.message}"

def run(text: str, size: int | None = None) -> Outcome:
  try:
    if STRICT:
      if (len(text.encode()) if size is None else size) > MAX_BYTES:
        raise Overbudget(f"more than {MAX_BYTES} bytes before parsing [week1]")
      Parser(text, checking=False).program()
    root = Parser(text).program()
    if STRICT and (cost := scope_cost(root)) >= MAX_COST:
      raise Overbudget(f"static cost {cost}; the limit is {MAX_COST - 1} [week1]")
    Frame([], root).eval(root, {})
  except Overbudget as e: return Outcome("OVERBUDGET", "budget", 0, str(e))
  except UIRError as e: return Outcome("REJECTED", e.kind, e.line, str(e))
  except AssertFailed as e: return Outcome("MISMATCH", "fail", 0, str(e))
  except RecursionError: return Outcome("REJECTED", "limit", 0, "the graph is too deep for this oracle")
  return Outcome("MATCH")

def main(args: list[str]) -> int:
  global LOWERED
  paths = list(args)
  while paths and paths[0].startswith("--"):
    flag = paths.pop(0)
    if flag == "--lowered": LOWERED = True
    elif flag == "--week" and paths and paths[0] in ("1", "2", "3", "4"): set_week(int(paths.pop(0)))
    else: paths = []; break
  if not paths:
    print("usage: python3 -I oracle/uir.py [--week 1|2|3|4] [--lowered] FILE.uir [FILE.uir ...]", file=sys.stderr)
    return 2
  outcomes = []
  for path in paths:
    try:
      with open(path, "rb") as f: data = f.read()
      outcomes.append(run(data.decode(errors="replace"), len(data)))
    except OSError as e: outcomes.append(Outcome("REJECTED", "file", 0, str(e)))
    print(outcomes[-1].report(path))
    if detail := outcomes[-1].detail(path): print(detail, file=sys.stderr)
  return 0 if all(o.status == "MATCH" for o in outcomes) else 1

if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
