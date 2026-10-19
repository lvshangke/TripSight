import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "merge_nanobot_config", Path(__file__).resolve().parent.parent / "scripts" / "merge_nanobot_config.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def test_merge_adds_entry_without_touching_other_settings():
    cfg = {"channels": {"weixin": {"enabled": True}}, "tools": {"mcpServers": {"other": {"url": "x"}}}}
    new, note = m.merge(cfg, "/py", Path("/repo"))
    assert new["tools"]["mcpServers"]["other"] == {"url": "x"} and new["channels"] == cfg["channels"]
    e = new["tools"]["mcpServers"]["tripcore"]
    assert e["command"] == "/py" and e["cwd"] == "/repo" and e["env"] == {} and "新增" in note
    assert "tripcore" not in cfg["tools"]["mcpServers"]          # 不修改传入的对象


def test_existing_entry_not_overwritten_unless_forced_and_env_kept():
    cfg = {"tools": {"mcpServers": {"tripcore": {"command": "old", "env": {"AMAP_KEY": "SECRET"}}}}}
    same, note = m.merge(cfg, "/py", Path("/repo"))
    assert same == cfg and "未改动" in note
    forced, _ = m.merge(cfg, "/py", Path("/repo"), force=True)
    assert forced["tools"]["mcpServers"]["tripcore"]["command"] == "/py"
    assert forced["tools"]["mcpServers"]["tripcore"]["env"] == {"AMAP_KEY": "SECRET"}


def test_cli_dry_run_then_apply_backs_up_and_never_writes_keys(tmp_path, capsys):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"tools": {}}), encoding="utf-8")
    assert m.main(["--config", str(cfg), "--python", "/py"]) == 0
    assert json.loads(cfg.read_text()) == {"tools": {}}               # 预览不写
    assert m.main(["--config", str(cfg), "--python", "/py", "--apply"]) == 0
    assert (tmp_path / "config.json.bak").exists()
    written = json.loads(cfg.read_text())
    assert written["tools"]["mcpServers"]["tripcore"]["env"] == {}
    assert "AMAP_KEY" not in cfg.read_text()


def test_invalid_json_config_is_left_alone(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{not json", encoding="utf-8")
    assert m.main(["--config", str(cfg), "--apply"]) == 1
    assert cfg.read_text() == "{not json"
