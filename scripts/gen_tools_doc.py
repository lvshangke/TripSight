"""重新生成 docs/TOOLS.md（能力地图）。用法：python scripts/gen_tools_doc.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tripcore.tools_catalog import render_markdown

out = Path(__file__).resolve().parent.parent / "docs" / "TOOLS.md"
out.write_text(render_markdown(), encoding="utf-8")
print("written", out)
