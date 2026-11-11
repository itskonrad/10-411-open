# Definitions from earlier chapters that the chapter 2 snippets build on.


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
