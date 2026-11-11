#!/usr/bin/env python3
"""Reference interpreter ("oracle") for UIR, weeks 1-3 of the course.

  python3 -I oracle/uir.py FILE.uir [FILE.uir ...]

prints `PASS file`, `FAIL file: <why>` (the assert does not hold) or `ERROR file:line: <kind>: <why>` (the program is
invalid, or does something undefined), and exits non-zero unless every file passes.

Pipeline: tokens -> hash-consed UOps, each checked as it is built -> whole-program checks -> evaluation -> ASSERT.
Comments name the source of each rule: [uir.md <section>], [ch1] chapter 1, [spec] syllabus/syllabus.md,
[notes] the weeks 1–3 research notes (kept outside the repo), [oracle] a decision listed in oracle/README.md.
"""
from __future__ import annotations
import math, re, struct, sys
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Callable

sys.setrecursionlimit(20000)  # parsing, toposort and evaluation recurse along the graph

I32_MIN, I32_MAX = -2**31, 2**31 - 1
DTYPES = ("bool", "i32", "f32")
ALU_DTYPES = {  # [ch1 ALU table]
  "add": {"i32", "f32"}, "mul": {"i32", "f32"}, "max": {"i32", "f32"}, "cmplt": {"i32", "f32"},
  "xor": {"i32", "bool"}, "shl": {"i32"}, "div": {"i32"}, "mod": {"i32"}, "recip": {"f32"},
}
ALU_OPS = {*ALU_DTYPES, "cast", "where"}
BINARY: dict[str, Callable[[Any, Any], Any]] = {  # floor // and %, like uir.md Arithmetic
  "add": lambda a, b: a + b, "mul": lambda a, b: a * b, "max": max, "xor": lambda a, b: a ^ b,
  "cmplt": lambda a, b: a < b, "shl": lambda a, b: a * 2**b, "div": lambda a, b: a // b, "mod": lambda a, b: a % b,
}
OPS = {"const", "param", "call", "stack", "index", "assert", *ALU_OPS,      # week 1
       "buffer", "alloc", "shrink", "load", "store", "after",               # week 2
       "range", "end"}                                                      # week 3
ARITY = {"param": 1, "buffer": 1, "alloc": 1, "cast": 1, "recip": 1, "where": 3, "assert": 2, "shrink": 3,
         "load": 1, "store": 2, "range": 1, "end": 2, **{op: 2 for op in BINARY}}
MIN_ARITY = {"call": 1, "index": 2, "after": 2}
ARG_KEYS = {"param": {"slot", "dtype"}, "buffer": {"slot", "dtype"}, "alloc": {"slot", "dtype"},
            "cast": {"dtype"}, "range": {"slot"}}
LITERALS_MATCH = {*BINARY, "assert", "store", "stack"}  # ops whose sources must match [uir.md Literals]

class UIRError(Exception):
  """An invalid program, or undefined behaviour found while running it."""
  def __init__(self, line: int, kind: str, msg: str):
    super().__init__(msg)
    self.line, self.kind = line, kind

class AssertFailed(Exception): pass

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
  if u.op in ARITY and len(u.src) != ARITY[u.op]: fail(u, "op", f"{u.op} takes {ARITY[u.op]} sources, got {len(u.src)}")
  if len(u.src) < MIN_ARITY.get(u.op, 0): fail(u, "op", f"{u.op} takes at least {MIN_ARITY[u.op]} sources")
  for s in u.src:
    if s.op == "assert": fail(u, "root", "assert is only allowed as the root [uir.md Programs and ASSERT]")
    if s.op == "stack" and not s.src and u.op not in ("param", "buffer", "alloc"):
      fail(u, "shape", "[] is only a shape, for param, buffer and alloc [oracle]")
  u.ranges = frozenset().union(*(s.ranges for s in u.src))
  u.ended = frozenset().union(*(s.ended for s in u.src))
  u.params = frozenset().union(*(s.params for s in u.src))
  (check_alu if u.op in ALU_OPS else CHECKS[u.op])(u)
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
    if s.op != "const": fail(u, "stack", "stack inputs must be constants until week 4 [spec week 1]")
  u.dtype, u.shape = same_dtype(u, u.src), (len(u.src),)
  if u.dtype != "f32": u.bounds = (min(s.bounds[0] for s in u.src), max(s.bounds[1] for s in u.src))

def same_dtype(u: UOp, srcs: tuple[UOp, ...]) -> str:
  dtypes = {s.dtype for s in srcs}
  if len(dtypes) > 1:
    floats = [s for s in srcs if s.op == "const" and s.dtype == "f32"]
    if floats and "i32" in dtypes:
      fail(u, "dtype", f"float constant {show(floats[0].arg)} cannot be i32 [uir.md Literals]")
    fail(u, "dtype", f"mixed dtypes {' and '.join(s.dtype for s in srcs)}: write a cast [uir.md Mixing dtypes]")
  return srcs[0].dtype

def need_value(u: UOp, s: UOp, what: str) -> None:
  """`s` must be a rank-0 ALU value [spec week 1 'ALU ops must be rank 0', spec week 2 addrspace]."""
  if s.dtype == "void": fail(u, "dtype", f"{what} has no value (it is an effect)")
  if s.space != "ALU": fail(u, "addrspace", f"{what} is GLOBAL memory: load it first [spec week 2]")
  if s.shape != (): fail(u, "rank", f"{what} has shape {s.shape}; ALU ops are rank 0 [spec week 1]")

def need_index(u: UOp, s: UOp, what: str) -> None:
  need_value(u, s, what)
  if s.dtype != "i32": fail(u, "dtype", f"{what} must be i32, not {s.dtype} [uir.md Literals]")

def check_alu(u: UOp) -> None:
  for i, s in enumerate(u.src): need_value(u, s, f"source {i} of {u.op}")
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
  """Exactly the table in uir.md Bounds, no tighter and no looser: validation depends on it."""
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
  c = b0 if b0 == b1 else None  # "by b with exact bounds c"
  if u.op == "div" and c is not None and c > 0: return (a0 // c, a1 // c)
  if u.op == "mod" and c is not None and c > 0: return (a0 % c, a1 % c) if a0 // c == a1 // c else (0, c - 1)
  if u.op == "shl" and c is not None and 0 <= c < 32: return fit32(a0 * 2**c, a1 * 2**c)
  return full_bounds(u.dtype)

def cast_bounds(s: UOp, dtype: str) -> tuple[int, int]:
  if (s.dtype, dtype) == ("bool", "i32"): return s.bounds
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

def check_define(u: UOp) -> None:
  """PARAM, BUFFER, ALLOC: src is the shape, `[]` or a length; arg is (slot, dtype) [uir.md Ops by week]."""
  shape = u.src[0]
  if shape.op == "stack" and not shape.src: u.shape = ()
  elif is_length(shape): u.shape = (shape.arg,)
  else: fail(u, "shape", f"{u.op}'s shape must be [] or a length")
  u.dtype = u.arg[1]
  if u.op == "param": u.params, u.bounds = frozenset({u}), full_bounds(u.dtype)
  else: u.space = "GLOBAL"

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
  if len(args) != needed: fail(u, "call", f"the body needs {needed} arguments, got {len(args)} [ch1]")
  for i, a in enumerate(args):
    if a.dtype == "void" or a.space != "ALU": fail(u, "call", f"argument {i} must be a value, not an effect or memory")
    p = slots.get(i)
    if p is not None and (a.dtype, a.shape) != (p.dtype, p.shape):
      fail(u, "call", f"argument {i} must be {p.dtype} {p.shape}, got {a.dtype} {a.shape} [ch1]")
  check_scope(body)
  u.dtype, u.shape, u.bounds = body.dtype, body.shape, body.bounds
  # the body's PARAMs are bound here, and its loops are its own
  u.params = frozenset().union(*(a.params for a in args))
  u.ended = frozenset().union(*(a.ended for a in args))

def check_assert(u: UOp) -> None:
  for s in u.src:
    if s.dtype == "void": fail(u, "dtype", "assert compares values, not effects")
  if u.src[0].shape != u.src[1].shape: fail(u, "shape", f"assert compares shapes {u.src[0].shape} and {u.src[1].shape}")
  same_dtype(u, u.src)

CHECKS = {"const": check_const, "stack": check_stack, "param": check_define, "buffer": check_define,
          "alloc": check_define, "index": check_index, "shrink": check_shrink, "load": check_load,
          "store": check_store, "after": check_after, "range": check_range, "end": check_end,
          "call": check_call, "assert": check_assert}

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

def check_program(root: UOp, asserts: list[UOp], last_line: int) -> None:
  def fail_root(kind: str, msg: str): raise UIRError(last_line, kind, msg)
  if root.op != "assert": fail_root("root", "the last line must be an assert [uir.md Programs and ASSERT]")
  for a in asserts:
    if a is not root: fail(a, "root", "a program has one assert, on its last line [uir.md Programs and ASSERT]")
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

def literal(t: str) -> bool | int | float | None:
  """true false 0x2a -3 1.5 1e+20 -inf nan, as tinygrad's uir.py reads them; None if `t` is not a literal."""
  if t in ("true", "false"): return t == "true"
  if re.fullmatch(r"0x[0-9a-fA-F]+", t): return int(t, 16)
  if re.fullmatch(r"-?[0-9]+", t): return int(t)
  if re.fullmatch(r"-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?|-?inf|nan", t): return float(t)
  return None

def is_assign(t: str) -> bool: return t.startswith("%") and t.endswith("=")

class Parser:
  """`%name = op srcs key=value` lines [uir.md Lines]. A source is a %name, a literal, a [stack] or nested (op ...)."""
  def __init__(self, text: str):
    self.toks = [Token(m[0], n) for n, line in enumerate(text.splitlines(), 1)
                 for m in TOKEN.finditer(line) if not m[0].startswith("#")]
    self.pos = 0
    self.cache: dict[tuple, UOp] = {}
    self.asserts: list[UOp] = []

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
    root, last_line = None, 1
    while self.peek() is not None:
      t = self.next("'%name ='")
      if not is_assign(t.text): raise UIRError(t.line, "parse", f"expected '%name =', got {t.text!r}")
      name = t.text[:-1].rstrip()
      if name in names: raise UIRError(t.line, "parse", f"{name} is already defined")
      root, last_line = self.value(names, bare=True), t.line
      names[name] = root
    if root is None: raise UIRError(1, "parse", "empty program")
    check_program(root, self.asserts, last_line)
    return root

  def value(self, names: dict[str, UOp], bare: bool = False) -> UOp:
    t = self.next("a value")
    if t.text == "{": raise UIRError(t.line, "parse", "scoped blocks arrive in week 6")
    if t.text == "(": return self.expr(names, self.next("an op"), ")")
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
      inline.append(self.peek() == "[" or literal(self.peek()) is not None)
      srcs.append(self.value(names))
    return tuple(srcs), inline

  def expr(self, names: dict[str, UOp], op: Token, close: str | None) -> UOp:
    if op.text not in OPS:
      raise UIRError(op.line, "op", f"unknown op {op.text!r} (weeks 1-3 have {' '.join(sorted(OPS - {'const'}))})")
    srcs, inline = self.sources(names)
    kv: dict[str, Any] = {}
    while not self.at_end():
      k = self.next("key=")
      if not k.text.endswith("="):
        raise UIRError(k.line, "parse", f"sources come before key=value args, got {k.text!r}")
      if k.text[:-1] in kv: raise UIRError(k.line, "arg", f"{k.text} appears twice")
      kv[k.text[:-1]] = self.arg_value()
    if close is not None and self.next(repr(close)).text != close:
      raise UIRError(op.line, "parse", f"expected {close!r}")
    return self.build(op.text, self.type_literals(op.text, srcs, inline, op.line), make_arg(op, kv), op.line)

  def arg_value(self) -> Any:
    t = self.next("a value")
    if t.text == "[":
      items = []
      while self.peek() not in ("]", None): items.append(self.arg_value())
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
      check(u)
      self.cache[key] = u
      if op == "assert": self.asserts.append(u)
    return self.cache[key]

  def type_literals(self, op: str, srcs: tuple[UOp, ...], inline: list[bool], line: int) -> tuple[UOp, ...]:
    """An inline int literal that must match an f32 is read as a float [uir.md Literals].
    check() reports the other mismatches."""
    if op == "where" and len(srcs) == 3: return (srcs[0], *self.match(srcs[1:], inline[1:], line))
    if op == "call" and srcs:
      dtypes = {p.arg[0]: p.arg[1] for p in srcs[0].params}
      args = (self.as_dtype(a, dtypes.get(i), line) if inline[1 + i] else a for i, a in enumerate(srcs[1:]))
      return (srcs[0], *args)
    return self.match(srcs, inline, line) if op in LITERALS_MATCH and srcs else srcs

  def match(self, srcs: tuple[UOp, ...], inline: list[bool], line: int) -> tuple[UOp, ...]:
    typed = [s.dtype for s, lit in zip(srcs, inline) if not lit] or [s.dtype for s in srcs]
    dtype = "f32" if "f32" in typed else typed[0]
    return tuple(self.as_dtype(s, dtype, line) if lit else s for s, lit in zip(srcs, inline))

  def as_dtype(self, u: UOp, dtype: str | None, line: int) -> UOp:
    if dtype != "f32" or u.dtype != "i32": return u
    if u.op == "const": return self.build("const", (), f32(float(u.arg)), line)
    if u.op == "stack": return self.build("stack", tuple(self.as_dtype(s, dtype, line) for s in u.src), None, line)
    return u

def make_arg(op: Token, kv: dict[str, Any]) -> Any:
  """Each op has a fixed set of keys [uir.md Arguments]; all of them are required."""
  keys = ARG_KEYS.get(op.text, set())
  if set(kv) != keys:
    raise UIRError(op.line, "arg", f"{op.text} takes args {sorted(keys) or 'none'}, got {sorted(kv) or 'none'}")
  if "slot" in kv and (type(kv["slot"]) is not int or kv["slot"] < 0):
    raise UIRError(op.line, "arg", f"slot must be an integer >= 0, got {kv['slot']!r}")
  if "dtype" in kv and kv["dtype"] not in DTYPES:
    raise UIRError(op.line, "arg", f"dtype must be one of {' '.join(DTYPES)}, got {kv['dtype']!r}")
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
  a, b = vals
  if u.op in ("div", "mod") and (b == 0 or (a, b) == (I32_MIN, -1)): undefined(u, f"{u.op} {a} {b}")
  if u.op == "shl" and not 0 <= b < 32: undefined(u, f"shl by {b}")
  if u.op == "max" and u.dtype == "f32":
    if math.isnan(a) or math.isnan(b) or (a == b == 0 and math.copysign(1, a) != math.copysign(1, b)):
      undefined(u, f"max {a} {b}")
  r = BINARY[u.op](a, b)
  return wrap32(r) if u.dtype == "i32" else f32(r) if u.dtype == "f32" else r

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

# ***** driver *****

@dataclass
class Outcome:
  status: str  # PASS, FAIL or ERROR
  kind: str = ""
  line: int = 0
  message: str = ""

  def report(self, path: str) -> str:
    if self.status == "PASS": return f"PASS {path}"
    if self.status == "FAIL": return f"FAIL {path}: {self.message}"
    return f"ERROR {path}:{self.line}: {self.kind}: {self.message}"

def run(text: str) -> Outcome:
  try:
    root = Parser(text).program()
    Frame([], root).eval(root, {})
  except UIRError as e: return Outcome("ERROR", e.kind, e.line, str(e))
  except AssertFailed as e: return Outcome("FAIL", "fail", 0, str(e))
  except RecursionError: return Outcome("ERROR", "limit", 0, "the graph is too deep for this oracle")
  return Outcome("PASS")

def main(paths: list[str]) -> int:
  if not paths:
    print("usage: python3 -I oracle/uir.py FILE.uir [FILE.uir ...]", file=sys.stderr)
    return 2
  outcomes = []
  for path in paths:
    try:
      with open(path) as f: outcomes.append(run(f.read()))
    except OSError as e: outcomes.append(Outcome("ERROR", "file", 0, str(e)))
    print(outcomes[-1].report(path))
  return 0 if all(o.status == "PASS" for o in outcomes) else 1

if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
