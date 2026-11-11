"""Check your compiler against the oracle.

Usage: python3 -I tools/check_compiler.py [--chapter N] [FILE.uir ...] -- COMMAND [ARG ...]

Runs `COMMAND ARG ... FILE.uir` for every test program and compares its verdict with the
oracle's. Your compiler prints one line per file, starting with its verdict, as the oracle does:

  PASS ...    the program is valid and its assert holds
  FAIL ...    the program is valid and its assert does not hold
  ERROR ...   the program is invalid

Only the first word is compared; the rest of the line is for you.

Without FILEs, it checks the examples of chapters 1 to N (default: every chapter that has
examples) and every .uir file under tests/, where your own tests go.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = ("PASS", "FAIL", "ERROR")
ORACLE = [sys.executable, "-I", str(ROOT / "oracle" / "uir.py")]


def verdict(command: list[str], path: Path) -> str:
    try:
        result = subprocess.run([*command, str(path)], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "timeout"
    words = result.stdout.split()
    if words and words[0] in VERDICTS:
        return words[0]
    return f"no verdict (exit {result.returncode}, output {result.stdout.strip()[:60]!r})"


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
        chapter, options = int(options[1]), options[2:]
    files = [Path(f).resolve() for f in options] or default_files(chapter)

    mismatches = 0
    for path in files:
        expected, got = verdict(ORACLE, path), verdict(command, path)
        if got != expected:
            mismatches += 1
            print(f"MISMATCH {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: "
                  f"oracle says {expected}, your compiler says {got}")
    print(f"{len(files) - mismatches}/{len(files)} match the oracle")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
