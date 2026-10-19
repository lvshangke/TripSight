import json

from tripcore import doctor
from tripcore.doctor import FAIL, OK, WARN


def _by(checks, name):
    return next(c for c in checks if c.name == name)


def test_keys_never_printed_and_placeholders_not_counted(monkeypatch, tmp_path):
    monkeypatch.delenv("AMAP_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"tools": {"mcpServers": {"tripcore": {"env": {
        "AMAP_KEY": "SECRETVALUE123456", "GOOGLE_MAPS_KEY": "在这里填你自己的 key"}}}}}), encoding="utf-8")
    monkeypatch.setenv("NANOBOT_CONFIG", str(cfg))
    monkeypatch.setenv("NANOBOT_SKILLS_DIR", str(tmp_path / "skills"))
    checks = doctor.run_checks()
    assert _by(checks, "高德 key").status == OK
    assert _by(checks, "Google Maps key").status == WARN
    assert "SECRETVALUE" not in doctor.format_report(checks)


def test_missing_skills_reported_with_fix(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOBOT_CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setenv("NANOBOT_SKILLS_DIR", str(tmp_path / "skills"))
    checks = doctor.run_checks()
    c = _by(checks, "技能 trip-planner")
    assert c.status == FAIL and "install_skills" in c.fix


def test_installed_skill_ok(monkeypatch, tmp_path):
    import shutil
    dest = tmp_path / "skills"
    shutil.copytree(doctor.REPO / "skills", dest)
    monkeypatch.setenv("NANOBOT_SKILLS_DIR", str(dest))
    monkeypatch.setenv("NANOBOT_CONFIG", str(tmp_path / "none.json"))
    assert _by(doctor.run_checks(), "技能 trip-planner").status == OK


def test_main_exit_code_follows_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOBOT_CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setenv("NANOBOT_SKILLS_DIR", str(tmp_path / "skills"))
    out = []
    assert doctor.main(out.append) == 1
    assert "自检" in out[0]


def test_doctor_subcommand_registered(monkeypatch, tmp_path, capsys):
    from tripcore.cli import main
    monkeypatch.setenv("NANOBOT_CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setenv("NANOBOT_SKILLS_DIR", str(tmp_path / "skills"))
    assert main(["doctor"]) in (0, 1)
    assert "自检" in capsys.readouterr().out


def test_demo_without_examples_gives_friendly_message(monkeypatch, tmp_path, capsys):
    from tripcore import cli
    monkeypatch.setattr(cli, "_DEMO_FILE", tmp_path / "nope.json")
    assert cli.main(["demo"]) == 1
    assert "pip install -e ." in capsys.readouterr().out
