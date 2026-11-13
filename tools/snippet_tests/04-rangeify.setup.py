# Definitions from earlier chapters that the chapter 4 snippets build on: chapter 3's setup,
# then chapter 3's own snippets (ranges, ended_ranges, nest, render), run from its README.
import re
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
exec((_root / "tools" / "snippet_tests" / "03-loops.setup.py").read_text())
for _block in re.findall(r"^```python\n(.*?)^```$", (_root / "03-loops" / "README.md").read_text(), re.DOTALL | re.MULTILINE):
    exec(_block)
