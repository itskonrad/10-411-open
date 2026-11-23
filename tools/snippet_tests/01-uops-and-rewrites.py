# Tests for the Python snippets in 01-uops-and-rewrites/README.md.
# check_snippets.py appends this file to the chapter's snippets, so their names are in scope.

const = lambda v: UOp("CONST", arg=v)  # noqa: E731
x, y = UOp("PARAM", arg=0), UOp("PARAM", arg=1)

# hash-consing: same structure is the same object; True and 1 stay distinct
assert UOp("ADD", (x, const(1))) is UOp("ADD", (x, const(1)))
assert len({const(True), const(1)}) == 2

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

# review additions: wrap edges, simultaneous substitution, shared nodes, MOD bounds
assert wrap32(-2**31 - 1) == 2**31 - 1 and wrap32(2**32) == 0
assert inline(UOp("CALL", (UOp("ADD", (x, y)), y, x))) is UOp("ADD", (y, x))
s = UOp("MUL", (x, x))  # shared between the outer body and an inner body
assert inline(UOp("CALL", (UOp("ADD", (s, UOp("CALL", (s, const(5))))), const(2)))) \
    is UOp("ADD", (UOp("MUL", (const(2), const(2))), UOp("CALL", (s, const(5)))))
assert bounds(UOp("ADD", (const(-2**31), const(-1)))) == I32
assert bounds(UOp("MOD", (y, const(4)))) == (0, 3)
assert rewrite(UOp("ADD", (const(True), const(True))), [fold_add], {}).op == "ADD"  # fold_add leaves bools alone
# the symbolic example: x = a mod 100, then (x*4 + y mod 4) is in [0, 399], within i32
xa = UOp("MOD", (x, const(100)))
assert bounds(UOp("ADD", (UOp("MUL", (xa, const(4))), UOp("MOD", (y, const(4)))))) == (0, 399)
# the released reference's cost box: a shared add counts once; STACK, INDEX and a call's body (charged per call)
a, b = UOp("ADD", (const(2), const(4))), UOp("ADD", (const(3), const(3)))
assert (cost(UOp("MUL", (a, a))), cost(UOp("MUL", (a, b)))) == (2, 3)
vec = UOp("STACK", (const(10), const(20), const(30)))
assert cost(vec) == 3 and cost(UOp("INDEX", (vec, const(2)))) == 4
assert cost(UOp("ADD", (UOp("INDEX", (vec, const(2))), const(1)))) == 5
px = UOp("PARAM", (UOp("STACK"),), 0)  # a PARAM's source is the empty stack `[]`, which costs 1
call = UOp("CALL", (UOp("ADD", (px, px)), const(3)))
assert cost(call) == 1 + (1 + 1) and cost(UOp("ASSERT", (call, const(6)))) == 3
twice = UOp("ADD", (UOp("CALL", (UOp("ADD", (px, px)), const(3))), UOp("CALL", (UOp("ADD", (px, px)), const(4)))))
assert cost(twice) == 1 + 3 + 3  # two calls, each charged for its body (the add and the `[]`)
assert counterexample(lambda x: wrap32(x * 2) + 0, lambda x: wrap32(x * 2), 1) is None
assert counterexample(lambda x: wrap32(x + 1), lambda x: x + 1, 1) == (2**31 - 1,)
print("chapter 1 snippet tests passed")
