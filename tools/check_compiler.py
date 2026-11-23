"""Check your compiler against the oracle.

Usage: python3 -I tools/check_compiler.py [--chapter N] [FILE.uir ...] -- COMMAND [ARG ...]

Runs `COMMAND ARG ... FILE.uir` for every test program and compares its outcome with the oracle's.
Like the released week 1 reference's `./compile`, your compiler prints one line per file on stdout,
`<OUTCOME> <file>`, with one space and the path as it was given. Put anything else on stderr.

  MATCH       the program is valid and its assert holds
  MISMATCH    the program is valid and its assert does not hold
  REJECTED    the program is invalid, and was rejected before execution
  OVERBUDGET  a limit is hit (week 1: file size, node, edge or cost limits); nothing runs

The oracle runs at the week of the chapter: `--chapter 1` is the week 1 reference's grammar and rules. A test under
`tests/chapterK/` is always run at week K, so tests you wrote for chapter 1 keep their meaning in later chapters.

Without FILEs, it checks the examples of chapters 1 to N (default: every chapter that has
examples) and every .uir file under tests/, where your own tests go. A test's filename says what
it should do, as in the reference: no prefix MATCH, `mismatch_` MISMATCH, `rejected_` REJECTED,
`overbudget_` OVERBUDGET. A test the oracle disagrees with is reported as MISLABELLED.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTCOMES = ("MATCH", "MISMATCH", "REJECTED", "OVERBUDGET")
PREFIXES = {"mismatch_": "MISMATCH", "rejected_": "REJECTED", "overbudget_": "OVERBUDGET"}
ORACLE = [sys.executable, "-I", str(ROOT / "oracle" / "uir.py")]


def named_outcome(path: Path) -> str:
    return next((outcome for prefix, outcome in PREFIXES.items() if path.name.startswith(prefix)), "MATCH")


def outcome(command: list[str], path: Path) -> str:
    try:
        result = subprocess.run([*command, str(path)], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "timeout"
    lines = result.stdout.splitlines()
    words = lines[0].split() if lines else []
    if not words or words[0] not in OUTCOMES:
        return f"no outcome (exit {result.returncode}, output {result.stdout.strip()[:60]!r})"
    if lines != [f"{words[0]} {path}"]:
        return f"{words[0]}, but the output is not exactly one line `{words[0]} {path}`: {result.stdout.strip()[:60]!r}"
    return words[0]


def default_files(chapter: int) -> list[Path]:
    examples = [p for p in sorted(ROOT.glob("[0-9][0-9]-*/examples/*.uir")) if int(p.parts[-3][:2]) <= chapter]
    return examples + sorted((ROOT / "tests").rglob("*.uir"))


def main(argv: list[str]) -> int:
    if "--" not in argv or argv.index("--") == len(argv) - 1:
        sys.exit(__doc__)
    split = argv.index("--")
    options, command = argv[:split], argv[split + 1:]
    chapter = 99
    if options[:1] == ["--chapter"]:
        if len(options) < 2 or not options[1].isdigit():
            sys.exit(__doc__)
        chapter, options = int(options[1]), options[2:]
    files = [Path(f).resolve() for f in options] or default_files(chapter)

    def oracle_for(path: Path) -> list[str]:
        folder = re.fullmatch(r"chapter(\d+)", path.parent.name)
        week = int(folder[1]) if folder and path.is_relative_to(ROOT / "tests") else chapter
        return [*ORACLE, "--week", str(min(max(week, 1), 4))]

    mismatches = 0
    for path in files:
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        expected, got = outcome(oracle_for(path), path), outcome(command, path)
        if expected.startswith(("no outcome", "timeout")):
            mismatches += 1
            print(f"ORACLE FAILED {shown}: {expected}")
            continue
        if got != expected:
            mismatches += 1
            print(f"DIFFERS {shown}: oracle says {expected}, your compiler says {got}")
        elif path.is_relative_to(ROOT / "tests") and expected != named_outcome(path):
            mismatches += 1
            print(f"MISLABELLED {shown}: its name says {named_outcome(path)}, the oracle says {expected}")
    print(f"{len(files) - mismatches}/{len(files)} match the oracle")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
