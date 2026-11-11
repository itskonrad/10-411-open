"""Tests for the UIR oracle: python3 -I oracle/test_oracle.py

- every chapter's examples (NN-*/examples/*.uir) and every program in tests/valid must PASS;
- every program in tests/invalid must be rejected as its `# expect: <kind>` or `# expect: <kind>: <message part>` line
  says (`fail` means a valid program whose assert does not hold).
"""
import importlib.util, re, subprocess, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("uir", HERE / "uir.py")  # -I leaves the script's folder off sys.path
uir = sys.modules["uir"] = importlib.util.module_from_spec(spec)  # dataclasses look their module up there
spec.loader.exec_module(uir)

EXAMPLES = sorted(HERE.parent.glob("[0-9][0-9]-*/examples/*.uir"))
PASSING = EXAMPLES + sorted((HERE / "tests" / "valid").glob("*.uir"))
REJECTED = sorted((HERE / "tests" / "invalid").glob("*.uir"))

class TestOracle(unittest.TestCase):
  def test_programs_pass(self):
    self.assertTrue(EXAMPLES)
    for path in PASSING:
      with self.subTest(str(path.relative_to(HERE.parent))):
        self.assertEqual(uir.run(path.read_text()).report(path.name), f"PASS {path.name}")

  def test_programs_rejected(self):
    self.assertTrue(REJECTED)
    for path in REJECTED:
      with self.subTest(path.name):
        text = path.read_text()
        expect = re.search(r"^# expect: (\w+)(?:: (.+))?$", text, re.M)
        self.assertIsNotNone(expect, "missing '# expect: <kind>' line")
        outcome = uir.run(text)
        self.assertEqual(outcome.kind, expect[1], outcome.report(path.name))
        if expect[2]: self.assertIn(expect[2], outcome.message)

  def test_f32_rounding(self):
    self.assertEqual(uir.f32(0.1), 0.10000000149011612)
    self.assertEqual(uir.f32(16777217.0), 16777216.0)  # ties to even
    self.assertEqual(uir.f32(1e40), float("inf"))

  def test_cli(self):
    def cli(*paths): return subprocess.run([sys.executable, "-I", HERE / "uir.py", *paths], capture_output=True, text=True)
    ok = cli(*PASSING[:2])
    self.assertEqual((ok.returncode, ok.stdout.count("PASS ")), (0, 2))
    bad = cli(PASSING[0], REJECTED[0], HERE / "missing.uir")
    self.assertEqual(bad.returncode, 1)
    self.assertRegex(bad.stdout, r"\nERROR .*:\d+: \w+: ")
    self.assertIn("missing.uir:0: file:", bad.stdout)

if __name__ == "__main__":
  unittest.main()
