# Tests for the Python snippets in 01-uops-and-rewrites/README.md.
# check_snippets.py appends this file to the chapter's snippets, so their names are in scope.

const = lambda v: UOp("CONST", arg=v)  # noqa: E731
x, y = UOp("PARAM", arg=0), UOp("PARAM", arg=1)

# hash-consing: same structure is the same object; True, 1 and 1.0 stay distinct
assert UOp("ADD", (x, const(1))) is UOp("ADD", (x, const(1)))
assert len({const(True), const(1), const(1.0)}) == 3

# constant folding wraps i32, and x + (2 + -2) rewrites to x
assert rewrite(UOp("ADD", (const(2**31 - 1), const(1))), [fold_add], {}) is const(-2**31)
assert rewrite(UOp("ADD", (x, UOp("ADD", (const(2), const(-2))))), [fold_add, add_zero], {}) is x

# a shared node is rewritten once
calls = []
def count(u):
    calls.append(u)
shared = UOp("ADD", (x, const(1)))
rewrite(UOp("MUL", (shared, shared)), [count], {})
assert calls.count(shared) == 1

# inlining substitutes by slot and leaves inner bodies alone
f = UOp("ADD", (UOp("MUL", (x, x)), y))
assert inline(UOp("CALL", (f, const(3), const(4)))) is UOp("ADD", (UOp("MUL", (const(3), const(3))), const(4)))
inner = UOp("CALL", (UOp("ADD", (x, x)), y))
assert inline(UOp("CALL", (inner, const(2), const(3)))) is UOp("CALL", (UOp("ADD", (x, x)), const(3)))

# bounds: exact for constants, corners for MUL, full range when unknown or possibly wrapping
assert bounds(UOp("MUL", (const(2), const(-4)))) == (-8, -8)
assert bounds(UOp("ADD", (x, const(2)))) == I32
assert bounds(UOp("MUL", (const(2**30), const(4)))) == I32

# review additions: wrap edges, float keys, simultaneous substitution, shared nodes, MOD bounds
assert wrap32(-2**31 - 1) == 2**31 - 1 and wrap32(2**32) == 0
assert const(-0.0) is not const(0.0)
assert const(float("nan")) is const(float("nan"))
assert inline(UOp("CALL", (UOp("ADD", (x, y)), y, x))) is UOp("ADD", (y, x))
s = UOp("MUL", (x, x))  # shared between the outer body and an inner body
assert inline(UOp("CALL", (UOp("ADD", (s, UOp("CALL", (s, const(5))))), const(2)))) \
    is UOp("ADD", (UOp("MUL", (const(2), const(2))), UOp("CALL", (s, const(5)))))
assert bounds(UOp("ADD", (const(-2**31), const(-1)))) == I32
assert bounds(UOp("MOD", (y, const(4)))) == (0, 3)
assert rewrite(UOp("ADD", (const(0.5), const(0.25))), [fold_add], {}).op == "ADD"  # fold_add leaves f32 alone
# the symbolic example: x = a mod 100, then (x*4 + y mod 4) is in [0, 399], within i32
xa = UOp("MOD", (x, const(100)))
assert bounds(UOp("ADD", (UOp("MUL", (xa, const(4))), UOp("MOD", (y, const(4)))))) == (0, 399)
# f32: rounds after every op, overflows to inf; rule testing finds the wrap at 2^29
assert f32(f32(16777216.0 + 1.0) + 1.0) == 16777216.0 and f32(16777216.0 + 1.0 + 1.0) == 16777218.0
assert f32(1e40) == float("inf") and f32(-1e40) == float("-inf")
assert counterexample(lambda x: wrap32(x * 2) + 0, lambda x: wrap32(x * 2), 1) is None
assert counterexample(lambda x: wrap32(x + 1), lambda x: x + 1, 1) == (2**31 - 1,)
print("chapter 1 snippet tests passed")
