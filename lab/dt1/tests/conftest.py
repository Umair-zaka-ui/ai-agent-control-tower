"""DT1-local test fixtures. Run with the backend venv's pytest by explicit path:

    backend/.venv/Scripts/python -m pytest lab/dt1/tests -q

Nothing here imports ACT; the production suite under backend/tests is untouched.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

DT1 = Path(__file__).resolve().parents[1]
ROOT = DT1.parents[1]
ART = DT1 / "artifacts"
sys.path.insert(0, str(DT1))

import validator  # noqa: E402
from canonical import canonical_bytes  # noqa: E402


@pytest.fixture(scope="session")
def grounding() -> dict:
    return json.loads((ART / "schema_grounding.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sealed() -> dict:
    return {name: json.loads((ART / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("estate_truth", "observability_contract", "agent_property_matrix", "anchor")}


@pytest.fixture()
def variant(tmp_path, sealed):
    """Write a (possibly mutated) copy of the artifacts to a temp dir and validate it."""
    def _make(*, truth=None, contract=None, matrix=None, keep_anchor=False, raw_edit=None, check_regeneration=False,
              base_commit=None, repo_root=None):
        d = tmp_path / "art"
        d.mkdir()
        shutil.copy2(ART / "schema_grounding.json", d / "schema_grounding.json")
        t = truth if truth is not None else copy.deepcopy(sealed["estate_truth"])
        c = contract if contract is not None else copy.deepcopy(sealed["observability_contract"])
        m = matrix if matrix is not None else copy.deepcopy(sealed["agent_property_matrix"])
        (d / "estate_truth.json").write_bytes(canonical_bytes(t))
        (d / "observability_contract.json").write_bytes(canonical_bytes(c))
        (d / "agent_property_matrix.json").write_bytes(canonical_bytes(m))
        if keep_anchor:
            shutil.copy2(ART / "anchor.json", d / "anchor.json")
        if raw_edit:
            name, old, new = raw_edit
            b = (d / name).read_bytes()
            assert old in b
            (d / name).write_bytes(b.replace(old, new, 1))
        return validator.validate(d, check_regeneration=check_regeneration, base_commit=base_commit, repo_root=repo_root)
    return _make


def failed(report) -> set[str]:
    return {r["check"] for r in report.failures()}
