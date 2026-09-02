"""Guardrails for the skill set itself: size, frontmatter, router rows, referenced files."""
import glob, os, re
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = sorted(glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")))


def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "missing frontmatter"
    keys = [line.split(":", 1)[0] for line in m.group(1).splitlines() if line and not line.startswith(" ")]
    return keys, m.group(1)


def test_skills_exist():
    assert len(SKILLS) >= 16


def test_skill_size_and_frontmatter():
    for path in SKILLS:
        text = open(path, encoding="utf-8").read()
        lines = text.count("\n") + (0 if text.endswith("\n") else 1)
        assert lines < 120, f"{path}: {lines} lines (limit 120)"
        keys, fm = _frontmatter(text)
        assert keys == ["name", "description"], f"{path}: frontmatter keys {keys}"
        # `gh skill install` parses this block as strict YAML: an unquoted value containing ": " is a nested mapping
        data = yaml.safe_load(fm)
        assert isinstance(data, dict) and list(data) == ["name", "description"], f"{path}: frontmatter must be YAML with name, description"
        assert data["name"] == os.path.basename(os.path.dirname(path)), f"{path}: name != folder"
        assert isinstance(data["description"], str) and data["description"].strip(), f"{path}: empty description"
        desc_line = re.search(r"^description:\s*(.*)$", fm, re.M).group(1)
        assert desc_line.startswith('"'), f"{path}: quote the description (it may contain ': ' or '#')"


def test_router_rows_resolve():
    text = open(os.path.join(ROOT, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    folders = {os.path.basename(os.path.dirname(p)) for p in SKILLS}
    rows = re.findall(r"^\|[^|]*\|\s*`([a-z0-9\-]+)`\s*\|$", text, re.M)
    assert rows, "router table not found"
    for skill in rows:
        assert skill in folders, f"router points at missing skill {skill}"


def test_referenced_reference_files_exist():
    for path in SKILLS:
        text = open(path, encoding="utf-8").read()
        for ref in re.findall(r"`references/([\w\-./]+)`", text):
            assert os.path.exists(os.path.join(os.path.dirname(path), "references", ref)), f"{path}: missing references/{ref}"
