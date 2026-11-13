# Tests for the code in 04-rangeify/README.md.
# check_snippets.py runs: the .setup.py file, then the chapter's snippets, then this file.
import ctypes
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "04-rangeify" / "README.md").read_text()

# --- Lesson 1: evaluate ---
def scalar(op, a, b=None):  # chapter 1's folding, enough for these tests
    return {"ADD": lambda: a + b, "MUL": lambda: a * b, "MAX": lambda: max(a, b)}[op]()

const = lambda v: UOp("CONST", arg=v)  # noqa: E731
assert evaluate(UOp("EXPAND", (const(1),), 3), [1], scalar) == [1, 1, 1]
values = evaluate(UOp("ADD"), [[1, 2, 3], [1, 1, 1]], scalar)
assert values == [2, 3, 4] and evaluate(UOp("REDUCE", arg="ADD"), [values], scalar) == 9
assert evaluate(UOp("REDUCE", arg="MAX"), [[-3.5, -1.5]], scalar) == -1.5
assert evaluate(UOp("STAGE"), [[4, 5]], scalar) == [4, 5]

# --- Lesson 2: elem ---
r = UOp("RANGE", (const(4),), 0)
x, y = UOp("BUFFER", (const(4),), 0), UOp("BUFFER", (const(4),), 1)
v = UOp("ADD", (UOp("MUL", (UOp("LOAD", (x,)), UOp("EXPAND", (const(0.5),), 4))), UOp("EXPAND", (const(1.0),), 4)))
vr = elem(v, r)
xr = UOp("LOAD", (UOp("INDEX", (x, r)),))
assert vr is UOp("ADD", (UOp("MUL", (xr, const(0.5))), const(1.0)))  # the trace table's result
stack = UOp("STACK", (const(1), const(2), const(3)))
assert elem(stack, r) is UOp("INDEX", (stack, r))
assert elem(UOp("INDEX", (stack, const(2))), None) is UOp("INDEX", (stack, const(2)))
assert elem(UOp("EXPAND", (const(7),), 3), r) is const(7)
# lower the rank-1 store y = x * 0.5 + 1 to a loop, render it with chapter 3's nest + render, run it
done = UOp("END", (UOp("STORE", (UOp("INDEX", (y, r)), vr)), r))
order = nest(toposort(UOp("AFTER", (y, done))))
src = "#include <stdint.h>\nvoid kernel(float *buf0, float *buf1) {\n"
src += render(order, lambda u: "int32_t" if u.op == "RANGE" else "float") + "\n}\n"
xb, yb = (ctypes.c_float * 4)(1, 2, 3, 4), (ctypes.c_float * 4)()
compile_c(src).kernel(xb, yb)
assert list(yb) == [1.5, 2.0, 2.5, 3.0], list(yb)

# --- every C kernel shown returns 1 (its assert holds) ---
kernels = [b for b in re.findall(r"^```c\n(.*?)^```$", README, re.DOTALL | re.MULTILINE) if "int kernel(" in b]
assert len(kernels) == 3
for code in kernels:
    params = re.findall(r"(int32_t|float) \*buf\d+", code.split("int kernel(")[1].split(")")[0])
    bufs = [((ctypes.c_float if t == "float" else ctypes.c_int32) * 16)() for t in params]
    assert compile_c(code).kernel(*bufs) == 1, code

# --- every complete UIR program shown passes the oracle, or fails as its first comment says ---
programs = [b for b in re.findall(r"^```text\n(.*?)^```$", README, re.DOTALL | re.MULTILINE) if "%test = assert" in b]
assert len(programs) >= 8
for n, text in enumerate(programs):
    (Path(f"shown{n}.uir")).write_text(text)
    out = subprocess.run([sys.executable, "-I", str(ROOT / "oracle" / "uir.py"), f"shown{n}.uir"],
                         capture_output=True, text=True).stdout
    expected = "FAIL" if text.startswith("# FAIL") else "PASS"
    assert out.startswith(expected), (text, out)
print("chapter 4 snippet tests passed")
