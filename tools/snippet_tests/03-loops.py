# Tests for the Python snippets in 03-loops/README.md.
# check_snippets.py runs: the .setup.py file, then the chapter's snippets, then this file.
import ctypes

const = lambda v: UOp("CONST", arg=v)  # noqa: E731
add = lambda a, b: UOp("ADD", (a, b))  # noqa: E731
mul = lambda a, b: UOp("MUL", (a, b))  # noqa: E731
index = lambda m, i: UOp("INDEX", (m, i))  # noqa: E731
load = lambda a: UOp("LOAD", (a,))  # noqa: E731
store = lambda a, v: UOp("STORE", (a, v))  # noqa: E731
after = lambda v, *deps: UOp("AFTER", (v, *deps))  # noqa: E731
end = lambda e, r: UOp("END", (e, r))  # noqa: E731

# examples/gemm.uir without the input stores (the test fills A and B from Python)
A, B, C = (UOp("BUFFER", (const(4),), slot) for slot in range(3))
i, j, k = (UOp("RANGE", (const(2),), slot) for slot in range(3))
init = store(index(C, add(mul(i, const(2)), j)), const(0.0))  # the literal 0 next to f32 is 0.0
acc = after(C, init, k)
cij = index(acc, add(mul(i, const(2)), j))
a = load(index(A, add(mul(i, const(2)), k)))
b = load(index(B, add(mul(k, const(2)), j)))
step = store(cij, add(load(cij), mul(a, b)))
done = end(end(end(step, k), j), i)
root = after(C, done)

# ranges: what each node runs inside; ended_ranges: which END closes each loop
assert ranges(step) == {i, j, k} and ranges(init) == {i, j} and ranges(a) == {i, k}
assert ranges(end(step, k)) == {i, j} and ranges(done) == set() and ranges(root) == set()
assert ended_ranges(done) == {k: end(step, k), j: end(end(step, k), j), i: done}

# nest: each loop's body sits between its RANGE and its END, and the init runs before loop k opens
order = nest(toposort(root))
pos = {u: n for n, u in enumerate(order)}
assert len(order) == len(set(order)) == len(toposort(root))
for r in (i, j, k):
    closing = ended_ranges(done)[r]
    assert all(pos[r] < pos[u] < pos[closing] for u in order if r in ranges(u) and u is not r)
assert pos[j] < pos[init] < pos[k]

# a load that does not use the loop is placed before it (hoisted), even though only the loop uses it
x = UOp("BUFFER", (const(1),), 3)
s = load(index(x, const(0)))
loop = end(store(index(C, i), s), i)
assert nest(toposort(loop)).index(s) < nest(toposort(loop)).index(i)

# render the nested order to C, compile it, run it: C = A @ B
f32 = {a, b, load(cij), mul(a, b), step.src[1]}  # the values computed in float; index math is i32
body = render(order, lambda u: "float" if u in f32 else "int32_t")
src = "#include <stdint.h>\nvoid kernel(float *buf0, float *buf1, float *buf2) {\n" + body + "\n}\n"
bufs = [(ctypes.c_float * 4)(*v) for v in ([1, 2, 3, 4], [5, 6, 7, 8], [0, 0, 0, 0])]
compile_c(src).kernel(*bufs)
assert list(bufs[2]) == [19, 22, 43, 50], list(bufs[2])
# the C block in the chapter is exactly this output, indented
readme = (Path(__file__).resolve().parent.parent / "03-loops" / "README.md").read_text()
shown = readme.split("void kernel(float *buf0, float *buf1, float *buf2) {\n")[1].split("\n}\n")[0]
assert [line.strip() for line in shown.splitlines()] == body.splitlines(), body
# examples/enclosing_loops.uir: a store that uses only k runs once per (o, k), so the counter ends at 6
z, y = UOp("BUFFER", (UOp("STACK"),), 0), UOp("BUFFER", (const(6),), 1)
o, kk = UOp("RANGE", (const(2),), 0), UOp("RANGE", (const(3),), 1)
az = after(z, store(z, const(0)), kk)
inc = store(az, add(load(az), const(1)))
mark = store(index(y, add(mul(o, const(3)), kk)), const(1))
outer = end(end(after(inc, mark), kk), o)
order2 = nest(toposort(after(z, outer)))
assert order2.index(o) < order2.index(kk) < order2.index(inc) < order2.index(outer)
src2 = "#include <stdint.h>\nvoid kernel(int32_t *buf0, int32_t *buf1) {\n"
src2 += render(order2, lambda u: "int32_t") + "\n}\n"
zbuf, ybuf = (ctypes.c_int32 * 1)(), (ctypes.c_int32 * 6)()
compile_c(src2).kernel(zbuf, ybuf)
assert zbuf[0] == 6 and list(ybuf) == [1] * 6, (zbuf[0], list(ybuf))
print("chapter 3 snippet tests passed")
