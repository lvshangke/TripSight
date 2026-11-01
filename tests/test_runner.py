import json

import pytest

pytest.importorskip("mcp")
pytest.importorskip("pydantic")

from tripcore import cli, runner  # noqa: E402
from tripcore import mcp_server as s  # noqa: E402


def test_run_calls_same_functions_and_coerces_types():
    out = runner.run_tool("new_trip", json.dumps({"name": "测试", "num_days": "2", "city": "杭州"}))
    assert "测试" in out or "杭州" in out
    assert s._load().meta.num_days == 2
    assert "测试" in runner.run_tool("show_trip", "")


def test_run_errors_are_clear():
    with pytest.raises(runner.RunError, match="没有叫"):
        runner.run_tool("nope")
    with pytest.raises(runner.RunError, match="没有这些参数"):
        runner.run_tool("show_trip", '{"x": 1}')
    with pytest.raises(runner.RunError, match="缺少必填"):
        runner.run_tool("add_place", "{}")
    with pytest.raises(runner.RunError, match="JSON"):
        runner.run_tool("show_trip", "{bad")
    with pytest.raises(runner.RunError, match="参数 num_days"):
        runner.run_tool("new_trip", '{"name": "a", "num_days": "三"}')


def test_tool_errors_become_run_errors(tmp_path):
    with pytest.raises(runner.RunError):
        runner.run_tool("scan_videos", json.dumps({"folder": str(tmp_path / "没有")}))


def test_cli_run_and_tools(capsys):
    assert cli.main(["tools", "恢复与手册"]) == 0
    assert "export_handbook" in capsys.readouterr().out
    assert cli.main(["run", "new_trip", '{"name": "甲", "num_days": 1}']) == 0
    assert cli.main(["run", "show_trip"]) == 0
    assert cli.main(["run", "nope"]) == 1


def test_image_results_are_saved(tmp_path, monkeypatch):
    from mcp.types import ImageContent, TextContent
    import base64
    monkeypatch.setattr(runner, "tool_map", lambda: {"fake": lambda: [TextContent(type="text", text="说明"),
                                                                       ImageContent(type="image", data=base64.b64encode(b"x").decode(), mimeType="image/jpeg")]})
    out = runner.run_tool("fake", "", out_dir=tmp_path)
    assert "说明" in out and (tmp_path / "fake-1.jpg").read_bytes() == b"x"
