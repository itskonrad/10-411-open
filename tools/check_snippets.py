"""Check that the code in a chapter runs.

Usage: python3 -I tools/check_snippets.py NN-chapter/README.md

- Python: every ```python block is joined in order into one program and run. If they exist,
  tools/snippet_tests/<chapter folder>.setup.py goes first (definitions from earlier chapters)
  and tools/snippet_tests/<chapter folder>.py goes last (the chapter's tests).
- C: every ```c block is compiled on its own with gcc -std=c11 -Wall -Wextra -Werror.
  A block that defines main() is also linked and run, and must exit with status 0.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFLAGS = ["-std=c11", "-O1", "-fwrapv", "-Wall", "-Wextra", "-Werror"]


def blocks(markdown: str, lang: str) -> list[str]:
    # only fences at column 0 count: a block inside a "> " quote (the syllabus) is quoted text
    return re.findall(rf"^```{lang}\n(.*?)^```$", markdown, re.DOTALL | re.MULTILINE)


def run(cmd: list[str], cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"FAILED: {' '.join(cmd)}\n{result.stdout}{result.stderr}")


def check_python(code: list[str], setup: Path, tests: Path, tmp: Path) -> None:
    program = "\n\n".join(code)
    if setup.exists():
        program = setup.read_text() + "\n\n# --- snippets ---\n" + program
    if tests.exists():
        program += "\n\n# --- tests ---\n" + tests.read_text()
    (tmp / "snippets.py").write_text(program)
    run([sys.executable, "-I", "snippets.py"], tmp)


def check_c(code: str, n: int, tmp: Path) -> None:
    source = tmp / f"block{n}.c"
    source.write_text(code)
    if re.search(r"\bint\s+main\s*\(", code):
        run(["gcc", *CFLAGS, source.name, "-o", f"block{n}"], tmp)
        run([f"./block{n}"], tmp)
    else:
        run(["gcc", *CFLAGS, "-c", source.name, "-o", f"block{n}.o"], tmp)


def main() -> None:
    readme = Path(sys.argv[1]).resolve()
    markdown = readme.read_text()
    tests = ROOT / "tools" / "snippet_tests" / f"{readme.parent.name}.py"
    setup = tests.with_suffix(".setup.py")
    python, c = blocks(markdown, "python"), blocks(markdown, "c")
    # build inside the repo: /tmp is often mounted noexec, so test binaries could not run there
    with tempfile.TemporaryDirectory(dir=ROOT, prefix=".check-") as name:
        tmp = Path(name)
        if python:
            check_python(python, setup, tests, tmp)
        for n, code in enumerate(c):
            check_c(code, n, tmp)
    print(f"ok: {len(python)} python blocks, {len(c)} C blocks"
          + (f", tests {tests.relative_to(ROOT)}" if python and tests.exists() else ""))


if __name__ == "__main__":
    main()
