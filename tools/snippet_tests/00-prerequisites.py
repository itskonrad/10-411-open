# Tests for the Python snippets in 00-prerequisites/README.md.
# check_snippets.py appends this file to the chapter's snippets, so their names are in scope.
from pathlib import Path

# the toy compiler: precedence, left associativity, folding, sharing, and the chapter's C block
assert parse("a + b * c") == ("add", "a", ("mul", "b", "c"))
assert parse("a * b + c") == ("add", ("mul", "a", "b"), "c")
assert parse("(a + 2*3) * b") == ("mul", ("add", "a", ("mul", "2", "3")), "b")
assert fold(parse("2 * (3 + 4)")) == "14"
readme = (Path(__file__).resolve().parent.parent / "00-prerequisites" / "README.md").read_text()
shown = readme.split("prints:\n\n```c\n")[1].split("```")[0]
assert shown == source + "\n", source

# wrap32 edges; f32 overflows to inf
assert wrap32(-2**31 - 1) == 2**31 - 1 and wrap32(2**32) == 0
assert f32(1e40) == float("inf") and f32(0.1) != 0.1

# toposort_iter agrees with toposort on a DAG with sharing and several roots' inputs
g = {"x": [], "y": ["x"], "z": ["x", "y"], "w": ["z", "y", "x"]}
assert toposort_iter(g, "w") == toposort(g, "w") == ["x", "y", "z", "w"]

# simplify: the or-patterns bind x on both sides
assert simplify(("add", "0", "a")) == "a" and simplify(("mul", "a", "0")) == "0"

# Lesson 5 worked numbers: classifier operation counts, and one gradient step
assert 2 * 32 * 784 * 128 == 6_422_528 and 2 * 32 * 128 * 10 == 81_920
assert abs((1.0 - 0.01 * w.grad) - 1.18) < 1e-12
# Lesson 6 roofline table
assert round(2 * 1024**3 / (3 * 1024**2 * 4)) == 171 and 100 / 12 < 0.01 * 1000
print("chapter 0 snippet tests passed")
