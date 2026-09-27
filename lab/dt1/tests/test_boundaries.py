"""Architecture guard and product-boundary gate (§3, §11, §15)."""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from conftest import ART, DT1, ROOT

PRODUCTION_PATHS = ["backend/app", "backend/migrations", "backend/requirements.txt", "backend/tests", "frontend", ".github"]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_production_act_imports_nothing_from_dt1():
    offenders = []
    for p in (ROOT / "backend" / "app").rglob("*.py"):
        if any(m == "dt1" or m.startswith(("dt1.", "lab.dt1", "lab.")) for m in _imports(p)):
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, offenders


def test_dt1_generator_and_validator_import_nothing_from_act():
    """grounding.py is the ONE justified exception (read-only metadata introspection, run once before generation)."""
    offenders = {}
    for p in DT1.glob("*.py"):
        if p.name == "grounding.py":
            continue
        bad = {m for m in _imports(p) if m == "app" or m.startswith("app.")}
        if bad:
            offenders[p.name] = sorted(bad)
    assert not offenders, offenders
    ground = {m for m in _imports(DT1 / "grounding.py") if m == "app" or m.startswith("app.")}
    assert ground == {"app.main", "app.core.database"}, ground


def test_dt1_tree_has_no_database_access():
    banned = ("sqlalchemy", "psycopg2", "alembic")
    offenders = {p.name: sorted(m for m in _imports(p) if m.split(".")[0] in banned) for p in DT1.glob("*.py")}
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, offenders


def test_empty_production_diff_against_base_commit():
    base = (DT1 / "BASE_COMMIT").read_text(encoding="utf-8").strip()
    p = subprocess.run(["git", "diff", "--quiet", base, "--", *PRODUCTION_PATHS], cwd=str(ROOT))
    assert p.returncode == 0, f"production paths differ from {base}"


def test_no_migration_added(grounding):
    head = sorted(p.stem for p in (ROOT / "backend" / "migrations" / "versions").glob("*.py"))[-1]
    assert head == grounding["repository"]["migration_files_head"] == "0061_assurance_evidence"


def test_nothing_written_into_backend_keys_or_outside_lab():
    for p in ART.glob("*"):
        assert p.suffix == ".json"
    assert not list((ROOT / "backend" / ".keys").glob("dt1*"))


def test_no_forbidden_markers_in_dt1():
    forbidden = ("TO" + "DO", "FIX" + "ME", "pytest.mark." + "skip", "pytest.mark." + "xfail")
    for p in list(DT1.glob("*.py")) + list((DT1 / "tests").glob("*.py")):
        text = p.read_text(encoding="utf-8")
        assert not [t for t in forbidden if t in text], p.name
