"""Positive validation of the sealed artifacts, and the determinism proof."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import ART, DT1, ROOT

sys.path.insert(0, str(DT1))
import dt1_versions as V  # noqa: E402
import validator  # noqa: E402
from canonical import canonical_bytes, content_hash  # noqa: E402
from contract import build_contract  # noqa: E402
from estate import build_estate  # noqa: E402
from matrix import build_matrix  # noqa: E402


def test_sealed_artifacts_validate_completely(grounding, sealed):
    rep = validator.validate(ART, grounding=grounding, base_commit=sealed["anchor"]["base_commit"], repo_root=ROOT, check_regeneration=True)
    assert rep.ok, rep.failures()
    assert len(rep.results) >= 60
    assert {"seal.hashes_match_anchor", "boundary.empty_production_diff", "determinism.regenerate_estate_identical"} <= {r["check"] for r in rep.results}


def test_estate_shape_matches_the_brief(sealed):
    t = sealed["estate_truth"]
    assert 50 <= len(t["agents"]) <= 60
    assert 10 <= len(t["control_group_agent_ids"]) <= 15
    # overlapping properties: at least one agent carries 4+ serious conditions at once, not additive cohorts
    assert any(a["serious_condition_count"] >= 4 for a in t["agents"])
    # both distributions of "risk" exist
    assert any(a["serious_condition_count"] == 0 for a in t["agents"])
    # every agent has exactly one reality class from the fixed vocabulary
    assert all(a["reality_class"] in ("ACTIVE_REAL_PROCESS_REQUIRED_STAGE2", "REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2",
                                      "SIMULATED_ASSET", "DORMANT_ASSET") for a in t["agents"])
    assert t["truthful_refusal_subject_agent_ids"]
    assert t["identifier_collisions"]
    assert t["a2a_handoffs"] and t["agent_authority"]


def test_generic_sensitive_resources_not_phi(sealed):
    names = " ".join(r["name"] for r in sealed["estate_truth"]["resources"])
    assert "Employee Payroll Database" in names and "Employee Compensation Records" in names and "Financial Records" in names
    assert "patient" not in names.lower() and "PHI" not in names


def test_regeneration_is_byte_identical_three_times(grounding, sealed):
    seed = sealed["anchor"]["seed"]
    outs = []
    for _ in range(3):
        truth = build_estate(seed, grounding, generator_version=V.GENERATOR_VERSION, schema_version=V.ESTATE_TRUTH_SCHEMA_VERSION)
        contract = build_contract(truth, grounding, contract_version=V.OBSERVABILITY_CONTRACT_VERSION)
        matrix = build_matrix(truth, matrix_version=V.AGENT_PROPERTY_MATRIX_VERSION)
        outs.append((canonical_bytes(truth), canonical_bytes(contract), canonical_bytes(matrix)))
    assert outs[0] == outs[1] == outs[2]
    assert outs[0][0] == (ART / "estate_truth.json").read_bytes()
    assert content_hash(json.loads(outs[0][0])) == sealed["anchor"]["estate_truth_sha256"]


def test_different_seed_changes_every_hash(grounding, sealed):
    truth = build_estate(sealed["anchor"]["seed"] + "-x", grounding, generator_version=V.GENERATOR_VERSION,
                         schema_version=V.ESTATE_TRUTH_SCHEMA_VERSION)
    assert content_hash(truth) != sealed["anchor"]["estate_truth_sha256"]
    # the SHAPE is stable across seeds (same agents, same properties); only identifiers move
    assert len(truth["agents"]) == len(sealed["estate_truth"]["agents"])


def test_no_wall_clock_or_random_in_hashed_content(sealed):
    blob = json.dumps(sealed["estate_truth"]) + json.dumps(sealed["observability_contract"]) + json.dumps(sealed["agent_property_matrix"])
    assert sealed["anchor"]["created_at"] not in blob
    assert "created_at" not in sealed["estate_truth"] and "generated_at" not in sealed["estate_truth"]
    for k in ("estate_truth_sha256", "combined_root_sha256"):
        assert sealed["anchor"][k] not in blob


def test_cli_determinism_command(tmp_path):
    p = subprocess.run([sys.executable, str(DT1 / "cli.py"), "determinism", "--runs", "3"], capture_output=True, text=True, cwd=str(ROOT))
    assert p.returncode == 0, p.stdout + p.stderr
    out = json.loads(p.stdout[p.stdout.index("{"):])
    assert out["identical"] and out["different_seed_differs"]
