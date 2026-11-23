"""Tests for the UIR oracle: python3 -I oracle/test_oracle.py

- every chapter's examples (NN-*/examples/*.uir), run at that chapter's week, must MATCH;
- every program in tests/valid must MATCH (week 4, the course syntax);
- every program in tests/invalid must end as its `# expect: <kind>` or `# expect: <kind>: <message part>` line says
  (`fail` means a valid program whose assert does not hold: MISMATCH; `budget` is OVERBUDGET; any other kind is REJECTED);
- every program in tests/week1 (week 1, the released reference) ends as its filename prefix says, like a student's tests:
  no prefix MATCH, `mismatch_` MISMATCH, `rejected_` REJECTED, `overbudget_` OVERBUDGET. A `# expect:` line, if any,
  also gives the kind.
"""
import importlib.util, re, subprocess, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("uir", HERE / "uir.py")  # -I leaves the script's folder off sys.path
uir = sys.modules["uir"] = importlib.util.module_from_spec(spec)  # dataclasses look their module up there
spec.loader.exec_module(uir)

EXAMPLES = sorted(HERE.parent.glob("[0-9][0-9]-*/examples/*.uir"))
VALID = sorted((HERE / "tests" / "valid").glob("*.uir"))
INVALID = sorted((HERE / "tests" / "invalid").glob("*.uir"))
WEEK1 = sorted((HERE / "tests" / "week1").glob("*.uir"))
PREFIXES = {"mismatch_": "MISMATCH", "rejected_": "REJECTED", "overbudget_": "OVERBUDGET"}

def run(path: Path, week: int = 4):
  uir.set_week(week)
  try: return uir.run(path.read_text(), len(path.read_bytes()))
  finally: uir.set_week(4)

def expected_outcome(name: str) -> str:
  return next((v for k, v in PREFIXES.items() if name.startswith(k)), "MATCH")

class TestOracle(unittest.TestCase):
  def test_programs_match(self):
    self.assertTrue(EXAMPLES and VALID)
    for path in EXAMPLES:
      with self.subTest(str(path.relative_to(HERE.parent))):
        week = min(int(path.parts[-3][:2]), 4)
        self.assertEqual(run(path, week).report(path.name), f"MATCH {path.name}")
    for path in VALID:
      with self.subTest(str(path.relative_to(HERE.parent))):
        self.assertEqual(run(path).report(path.name), f"MATCH {path.name}")

  def test_programs_rejected(self):
    self.assertTrue(INVALID)
    for path in INVALID:
      with self.subTest(path.name):
        text = path.read_text()
        expect = re.search(r"^# expect: (\w+)(?:: (.+))?$", text, re.M)
        self.assertIsNotNone(expect, "missing '# expect: <kind>' line")
        outcome = run(path)
        self.assertEqual(outcome.kind, expect[1], outcome.detail(path.name))
        if expect[2]: self.assertIn(expect[2], outcome.message)

  def test_week1_names(self):
    self.assertTrue(WEEK1)
    seen = set()
    for path in WEEK1:
      with self.subTest(path.name):
        outcome = run(path, 1)
        seen.add(outcome.status)
        self.assertEqual(outcome.status, expected_outcome(path.name), outcome.detail(path.name))
        expect = re.search(r"^# expect: (\w+)", path.read_text(), re.M)
        if expect: self.assertEqual(outcome.kind, expect[1], outcome.detail(path.name))
    self.assertEqual(seen, set(uir.OUTCOMES))  # the set shows every outcome

  def test_week1_is_not_the_course_syntax(self):
    nested = "%x = add (add 1 2) 3\n%t = assert %x 6\n"
    self.assertEqual(uir.run(nested).status, "MATCH")
    uir.set_week(1)
    try: self.assertEqual((uir.run(nested).status, uir.run(nested).kind), ("REJECTED", "parse"))
    finally: uir.set_week(4)

  def test_lowered_flag(self):
    uir.LOWERED = True
    try:
      self.assertEqual(uir.run("%test = assert (reduce [1 2] op=add pop=1) 3").kind, "lowered")
      self.assertEqual(uir.run("%test = assert (add [1 2] [1 1]) [2 3]").kind, "lowered")
      self.assertEqual(uir.run("%test = assert (index [1 2] 1) 2").status, "MATCH")
    finally:
      uir.LOWERED = False

  def test_cost(self):  # the released reference's "same value, same cost?" box, and its per-op costs
    def cost(text):
      uir.set_week(1)
      try: return uir.scope_cost(uir.Parser(text).program())
      finally: uir.set_week(4)
    shared = "%a = add 2 4\n%m = mul %a %a\n%t = assert %m 36\n"
    distinct = "%a = add 2 4\n%b = add 3 3\n%m = mul %a %b\n%t = assert %m 36\n"
    self.assertEqual((cost(shared), cost(distinct)), (2, 3))
    self.assertEqual(cost("%v = [10 20 30]\n%x = index %v 1\n%t = assert %x 20\n"), 3 + 1)  # stack N=3, index 1
    call = "%x = param [] slot=0 dtype=i32 addrspace=ALU\n%f = add %x %x\n%r = call %f 3\n%t = assert %r 6\n"
    self.assertEqual(cost(call), 1 + (1 + 1))  # the call, its body's add, and the `[]` shape marker

  def test_bounds_of_div_mod_shl(self):  # the released reference's bounds column, case by case
    def bounds(op: str, lo: int, hi: int, y: str) -> tuple[int, int]:
      """The bounds of `op x y` in a body whose x is a PARAM with limits [lo hi]; y is a literal or `[a b]` limits."""
      y_def = f"%y = param [] {y} slot=1 dtype=i32 addrspace=ALU\n" if y.startswith("[") else ""
      arg = "1" if y.startswith("[") else ""
      text = (f"%x = param [] [{lo} {hi}] slot=0 dtype=i32 addrspace=ALU\n{y_def}"
              f"%m = {op} %x {'%y' if y_def else y}\n%r = call %m {lo} {y.strip('[]').split()[0] if y_def else ''}\n%t = assert %r 0\n")
      uir.set_week(1)
      try: return uir.Parser(text).program().src[0].src[0].bounds
      finally: uir.set_week(4)
    self.assertEqual(bounds("mod", -5, 5, "3"), (0, 2))      # floor quotients -2 and 1 differ: [0, c - 1]
    self.assertEqual(bounds("mod", 4, 5, "3"), (1, 2))       # both in quotient 1: the remainders 1 and 2
    self.assertEqual(bounds("mod", 0, 5, "-3"), (-2, 0))     # c < 0, quotients differ: [c + 1, 0]
    self.assertEqual(bounds("mod", 2, 9, "0"), (2, 9))       # mod by 0 is x
    self.assertEqual(bounds("mod", 2, 9, "[1 3]"), (-2**31, 2**31 - 1))  # y not fixed: I
    self.assertEqual(bounds("div", 2, 9, "0"), (-1, -1))
    self.assertEqual(bounds("div", -5, 5, "-2"), (-3, 2))   # endpoint quotients 2 and -3, ordered
    self.assertEqual(bounds("div", -5, 5, "2"), (-3, 2))
    self.assertEqual(bounds("div", -2**31, 5, "-1"), (-2**31, 2**31 - 1))  # 2^31 overflows: I
    self.assertEqual(bounds("div", 2, 9, "[1 3]"), (-2**31, 2**31 - 1))
    self.assertEqual(bounds("shl", 1, 2, "[3 4]"), (8, 32))  # k in {3, 4}: 1*8 .. 2*16
    self.assertEqual(bounds("shl", 1, 2, "33"), (2, 4))      # k = 33 mod 32 = 1
    self.assertEqual(bounds("shl", 1, 2, "[0 40]"), (-2**31, 2**31 - 1))  # k reaches 31: 2 * 2^31 overflows
    self.assertEqual(bounds("shl", -1, 1, "[30 33]"), (-2**31, 2**31 - 1))  # k in {30, 31, 0, 1}: -2^31 .. 2^31 overflows

  def test_f32_rounding(self):
    self.assertEqual(uir.f32(0.1), 0.10000000149011612)
    self.assertEqual(uir.f32(16777217.0), 16777216.0)  # ties to even
    self.assertEqual(uir.f32(1e40), float("inf"))

  def test_cli(self):
    def cli(*args): return subprocess.run([sys.executable, "-I", HERE / "uir.py", *args], capture_output=True, text=True)
    ok = cli(*EXAMPLES[:2])
    self.assertEqual((ok.returncode, ok.stdout.splitlines()), (0, [f"MATCH {p}" for p in EXAMPLES[:2]]))
    bad = cli(EXAMPLES[0], INVALID[0], HERE / "missing.uir")
    self.assertEqual(bad.returncode, 1)
    self.assertEqual([line.split()[0] for line in bad.stdout.splitlines()], ["MATCH", "REJECTED", "REJECTED"])
    self.assertEqual(bad.stdout.splitlines()[1], f"REJECTED {INVALID[0]}")  # exactly `<outcome> <path>`
    self.assertRegex(bad.stderr, rf"{INVALID[0]}:\d+: \w+: ")  # the reason is on stderr
    self.assertIn("missing.uir:0: file:", bad.stderr)
    self.assertEqual(cli("--week", "1", WEEK1[0]).stdout.split()[0], expected_outcome(WEEK1[0].name))

if __name__ == "__main__":
  unittest.main()
