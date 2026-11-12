# Tests for the Python snippets in 02-memory-and-shape/README.md.
# check_snippets.py runs: the .setup.py file, then the chapter's snippets, then this file.
import ctypes

const = lambda v: UOp("CONST", arg=v)  # noqa: E731

# examples/chained_stores.uir, with %b as BUFFER slot 0:
#   b[0] = 1; b[1] = b[0] + 1
b = UOp("BUFFER", (const(2),), 0)  # shape source 2: rank 1
s0 = UOp("STORE", (UOp("INDEX", (b, const(0))), const(1)))
b1 = UOp("AFTER", (b, s0))
x = UOp("ADD", (UOp("LOAD", (UOp("INDEX", (b1, const(0))),)), const(1)))
s1 = UOp("STORE", (UOp("INDEX", (b1, const(1))), x))
root = UOp("AFTER", (b, s1))
order = toposort(root)

# the renderer produces the body shown in the chapter, and the C really computes [1, 2]
body = render(order, lambda u: "int32_t")
assert body == "buf0[0] = 1;\nint32_t v9 = buf0[0];\nint32_t v10 = v9 + 1;\nbuf0[1] = v10;", body
# the C block in the chapter is exactly this output, indented
readme = (Path(__file__).resolve().parent.parent / "02-memory-and-shape" / "README.md").read_text()
shown = readme.split("void kernel(int32_t *buf0) {\n")[1].split("\n}\n")[0]
assert [line.strip() for line in shown.splitlines()] == body.splitlines(), body
kernel = compile_c("#include <stdint.h>\nvoid kernel(int32_t *buf0) {\n" + body + "\n}\n").kernel
buf0 = (ctypes.c_int32 * 2)()
kernel(buf0)
assert list(buf0) == [1, 2]

# compiling the same source again reuses the cached library
src = "#include <stdint.h>\nvoid kernel(int32_t *buf0) {\n" + body + "\n}\n"
libs = sorted(Path("kernels").glob("*.so"))
assert compile_c(src)._name == compile_c(src)._name and sorted(Path("kernels").glob("*.so")) == libs

# one buffer, three accesses, all ordered; accesses is recursive, so the root's covers the program
acc = accesses(root)
assert list(acc) == [b] and acc[b] == {s0, x.src[0], s1}
assert accesses(s0) == {b: frozenset({s0})}
check_ordered(acc[b])

# rank-0 memory renders as element 0: examples/store_load.uir
b0 = UOp("BUFFER", (UOp("STACK"),), 0)  # shape source []: rank 0
st = UOp("STORE", (b0, const(7)))
ld = UOp("LOAD", (UOp("AFTER", (b0, st)),))
assert render(toposort(ld), lambda u: "int32_t") == "buf0[0] = 7;\nint32_t v5 = buf0[0];", render(toposort(ld), lambda u: "int32_t")


# a load that does not wait for the store is rejected
store, load = UOp("STORE", (b, const(7))), UOp("LOAD", (b,))
try:
    check_ordered(frozenset({store, load}))
    raise AssertionError("an unordered load and store must be rejected")
except TypeError:
    pass
print("chapter 2 snippet tests passed")

# every other C block in the chapter is the renderer's output too
def shown_block(first_line: str) -> list[str]:
    return [line.strip() for line in readme.split(first_line + "\n")[1].split("\n}\n")[0].splitlines()]

# What you build: examples/store_load.uir, its assert rendered as the return value
assert shown_block("int kernel(int32_t *buf0) {")[:2] == render(toposort(ld), lambda u: "int32_t").splitlines()
assert shown_block("int kernel(int32_t *buf0) {")[2] == "return v5 == 7;"
# How to start: examples/add.uir from chapter 1
v = UOp("ADD", (const(2), const(3)))
assert shown_block("int kernel(void) {") == [render(toposort(v), lambda u: "int32_t"), "return v2 == 5;"]
# Lesson 2: chained_stores with its assert
full = readme.split("int kernel(int32_t *buf0) {\n")[2].split("\n}\n")[0]
assert [line.strip() for line in full.splitlines()] == body.splitlines() + ["return buf0[0] == 1 && buf0[1] == 2;"]
lib = compile_c("#include <stdint.h>\nint kernel(int32_t *buf0) {\n" + full + "\n}\n")
assert lib.kernel((ctypes.c_int32 * 2)()) == 1
# Lesson 2: the alloc_in_call and symbolic_offset kernels compile, run, and pass
import re
c_blocks = re.findall(r"^```c\n(.*?)^```$", readme, re.DOTALL | re.MULTILINE)
alloc_src = next(b for b in c_blocks if "alloc1" in b)
assert compile_c(alloc_src).kernel() == 1
window_src = next(b for b in c_blocks if "int32_t *win" in b)
n, buf = (ctypes.c_int32 * 1)(), (ctypes.c_int32 * 4)()
assert compile_c(window_src).kernel(n, buf) == 1 and list(buf) == [0, 0, 7, 8]
print("chapter 2 extra C-block tests passed")
