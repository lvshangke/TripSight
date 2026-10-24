"""工具目录必须和真实的 MCP 工具一一对应，docs/TOOLS.md 不能过期。"""

from pathlib import Path

import pytest

pytest.importorskip("mcp")

from tripcore import mcp_server as s  # noqa: E402
from tripcore import tools_catalog as tc  # noqa: E402


def test_every_tool_is_catalogued_and_nothing_extra():
    names = {f.__name__ for f in s.TOOLS}
    assert names == set(tc.CATALOG), (names - set(tc.CATALOG), set(tc.CATALOG) - names)


def test_entries_are_well_formed():
    for n, (cat, kind, summary, example) in tc.CATALOG.items():
        assert cat in tc.CATEGORIES and kind in tc.KINDS, n
        assert summary and example and len(summary) <= 60, n
    assert sum(len(b["tools"]) for b in tc.catalog_rows()) == len(tc.CATALOG)


def test_tools_doc_is_up_to_date():
    doc = Path(__file__).resolve().parent.parent / "docs" / "TOOLS.md"
    assert doc.read_text(encoding="utf-8") == tc.render_markdown(), "请运行 python scripts/gen_tools_doc.py"
