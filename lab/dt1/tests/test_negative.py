"""MANDATORY negative tests (§10): the validator must REJECT malformed artifacts.
Each test mutates a copy of the sealed artifacts and asserts the specific
check fails - proving the validator is capable of failing."""
from __future__ import annotations

import copy
import subprocess

from conftest import failed


def _primary_agents(t):
    prim = next(x["id"] for x in t["tenants"] if x["role"] == "PRIMARY")
    return [a for a in t["agents"] if a["tenant_id"] == prim]


def test_duplicate_canonical_agent(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    t["agents"].append(copy.deepcopy(t["agents"][0]))
    f = failed(variant(truth=t))
    assert {"agents.unique_ids", "ids.globally_unique"} <= f


def test_missing_owner_reference(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    a = next(x for x in t["agents"] if x["owners"]["business_person_id"])
    a["owners"]["business_person_id"] = "per-00000000000000000000"
    assert "references.integrity" in failed(variant(truth=t))


def test_invalid_credential_reference(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    t["agents"][0]["credential_ids"].append("cred-ffffffffffffffffffff")
    assert "references.integrity" in failed(variant(truth=t))


def test_invalid_mcp_reference(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    t["agents"][0]["mcp_server_ids"].append("mcp-ffffffffffffffffffff")
    assert "references.integrity" in failed(variant(truth=t))


def test_cross_tenant_relationship(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    prim = _primary_agents(t)[0]
    other_cred = next(c for c in t["credentials"] if c["tenant_id"] != prim["tenant_id"])
    prim["credential_ids"].append(other_cred["id"])
    assert "tenant.isolation" in failed(variant(truth=t))


def test_control_group_below_ten(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    cg = [a for a in t["agents"] if a["control_group"]]
    for a in cg[:5]:
        a["control_group"] = False
    t["control_group_agent_ids"] = sorted(a["id"] for a in t["agents"] if a["control_group"])
    assert "control_group.count_10_to_15" in failed(variant(truth=t))


def test_control_group_above_fifteen_or_risky(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    risky = [a for a in t["agents"] if not a["control_group"] and a["serious_condition_count"] > 0][:6]
    for a in risky:
        a["control_group"] = True
    t["control_group_agent_ids"] = sorted(a["id"] for a in t["agents"] if a["control_group"])
    f = failed(variant(truth=t))
    assert "control_group.count_10_to_15" in f or "control_group.no_serious_condition" in f


def test_required_adversarial_condition_removed(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    for a in t["agents"]:
        a["estate_conditions"] = [c for c in a["estate_conditions"] if c != "NATIVE_REFERENCE_COLLISION"]
    t["identifier_collisions"] = []
    m = copy.deepcopy(sealed["agent_property_matrix"])
    for r in m["rows"]:
        r["estate_conditions"] = [c for c in r["estate_conditions"] if c != "NATIVE_REFERENCE_COLLISION"]
    f = failed(variant(truth=t, matrix=m))
    assert {"adversarial.required_conditions_present", "collision.represented_objectively"} <= f


def test_truthful_refusal_scenario_removed(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    t["truthful_refusal_subject_agent_ids"] = []
    assert "truthful_refusal.represented" in failed(variant(truth=t))


def test_non_deterministic_artifact(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    t["generated_wall_clock"] = "2026-09-27T19:09:19+00:00"
    f = failed(variant(truth=t, check_regeneration=True))
    assert "determinism.regenerate_estate_identical" in f


def test_estate_truth_tampered_after_sealing(variant, sealed):
    a = sealed["estate_truth"]["agents"][0]["name"].encode()
    f = failed(variant(keep_anchor=True, raw_edit=("estate_truth.json", a, a[:-1] + (b"X" if a[-1:] != b"X" else b"Y"))))
    assert "seal.hashes_match_anchor" in f


def test_observability_contract_tampered_after_sealing(variant, sealed):
    f = failed(variant(keep_anchor=True, raw_edit=("observability_contract.json", b'"classification":"NOT_OBSERVE"', b'"classification":"OBSERVE"')))
    assert "seal.hashes_match_anchor" in f


def test_real_looking_secret_inserted(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    t["credentials"][0]["secret_value"] = "sk-" + "A" * 24          # assembled, never a literal secret shape in source
    f = failed(variant(truth=t))
    assert {"security.no_secret_shapes", "security.credentials_carry_no_value"} <= f


def test_expectation_key_inserted_into_truth(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    t["agents"][0]["EXPECTED_MISS"] = True
    assert "truth.no_expectation_keys" in failed(variant(truth=t))


def test_forbidden_real_data_shapes(variant, sealed):
    t = copy.deepcopy(sealed["estate_truth"])
    t["people"][0]["email"] = "someone@gmail.com"
    t["resources"][0]["name"] = "Patient Diagnosis Records"
    f = failed(variant(truth=t))
    assert {"privacy.fictional_emails", "privacy.no_phi_default"} <= f


def test_production_diff_violation_is_detected(variant, tmp_path):
    """The boundary check itself must fail when production paths differ from the base commit."""
    repo = tmp_path / "repo"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / "backend" / "app" / "x.py").write_text("A = 1\n")
    run = lambda *a: subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True, check=True)  # noqa: E731
    run("init", "-q"); run("config", "user.email", "dt1@lab.example"); run("config", "user.name", "dt1")
    run("add", "."); run("commit", "-q", "-m", "base")
    base = run("rev-parse", "HEAD").stdout.strip()
    (repo / "backend" / "app" / "x.py").write_text("A = 2\n")
    f = failed(variant(base_commit=base, repo_root=repo))
    assert "boundary.empty_production_diff" in f
