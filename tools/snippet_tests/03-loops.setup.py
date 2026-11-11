# Definitions from earlier chapters that the chapter 3 snippets build on.
import ctypes
import hashlib
import subprocess
from pathlib import Path


class UOp:  # chapter 1
    cache: dict = {}

    def __new__(cls, op: str, src: tuple = (), arg=None):
        key = (op, src, type(arg), repr(arg) if isinstance(arg, float) else arg)
        if key not in cls.cache:
            u = super().__new__(cls)
            u.op, u.src, u.arg = op, src, arg
            cls.cache[key] = u
        return cls.cache[key]


def toposort(root: UOp) -> list:  # chapter 0, on UOps
    order, seen = [], set()

    def visit(u: UOp) -> None:
        if u not in seen:
            seen.add(u)
            for s in u.src:
                visit(s)
            order.append(u)

    visit(root)
    return order


CFLAGS = ["-std=c11", "-O2", "-fwrapv", "-ffp-contract=off", "-shared", "-fPIC"]


def compile_c(src: str, cache: Path = Path("kernels")) -> ctypes.CDLL:  # chapter 2
    name = hashlib.sha256((" ".join(CFLAGS) + src).encode()).hexdigest()[:16]
    lib = cache / f"{name}.so"
    if not lib.exists():
        cache.mkdir(exist_ok=True)
        (cache / f"{name}.c").write_text(src)
        subprocess.run(["cc", *CFLAGS, f"{name}.c", "-o", lib.name], cwd=cache, check=True)
    return ctypes.CDLL(str(lib.resolve()))
