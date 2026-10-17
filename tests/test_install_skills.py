import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install_skills.py"


def _mod():
    spec = importlib.util.spec_from_file_location("install_skills", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_skills_have_frontmatter_and_no_secrets():
    m = _mod()
    dirs = m.skill_dirs()
    assert {d.name for d in dirs} >= {"trip-planner", "flyai-search"}
    for d in dirs:
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---\nname: " + d.name)
        assert "key=" not in text and "/Users/" not in text


def test_install_copy_link_and_check(tmp_path):
    m = _mod()
    dest = tmp_path / "skills"
    m.install(dest, link=False)
    assert m.check(dest) == 0
    (dest / "trip-planner" / "SKILL.md").write_text("changed", encoding="utf-8")
    assert m.check(dest) == 1
    m.install(dest, link=False)                       # 再装一次：旧的备份成 .bak
    assert (dest / "trip-planner.bak").exists() and m.check(dest) == 0
    m.install(tmp_path / "linked", link=True)
    assert (tmp_path / "linked" / "trip-planner").is_symlink()
