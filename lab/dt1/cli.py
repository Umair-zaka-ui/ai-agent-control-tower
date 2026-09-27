"""DT1 Stage 1 command line.

    python lab/dt1/cli.py generate   [--seed S] [--out DIR]
    python lab/dt1/cli.py seal       [--out DIR] [--base-commit SHA]
    python lab/dt1/cli.py validate   [--out DIR] [--base-commit SHA]
    python lab/dt1/cli.py determinism [--runs 3] [--seed S]
    python lab/dt1/cli.py render     [--out DIR]     # Markdown renderings into docs/dt1/

Runs without a database and without importing ACT. ``schema_grounding.json``
must already exist (``grounding.py``).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import dt1_versions as V  # noqa: E402
from canonical import canonical_bytes, content_hash  # noqa: E402
from contract import build_contract  # noqa: E402
from estate import build_estate  # noqa: E402
from matrix import build_matrix, render_markdown  # noqa: E402
import seal as seal_mod  # noqa: E402
import validator  # noqa: E402

ART = HERE / "artifacts"
DOCS = ROOT / "docs" / "dt1"


def load_grounding(art: Path) -> dict:
    return json.loads((art / "schema_grounding.json").read_text(encoding="utf-8"))


def generate(seed: str, out: Path, grounding: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    truth = build_estate(seed, grounding, generator_version=V.GENERATOR_VERSION, schema_version=V.ESTATE_TRUTH_SCHEMA_VERSION)
    contract = build_contract(truth, grounding, contract_version=V.OBSERVABILITY_CONTRACT_VERSION)
    matrix = build_matrix(truth, matrix_version=V.AGENT_PROPERTY_MATRIX_VERSION)
    (out / "estate_truth.json").write_bytes(canonical_bytes(truth))
    (out / "observability_contract.json").write_bytes(canonical_bytes(contract))
    (out / "agent_property_matrix.json").write_bytes(canonical_bytes(matrix))
    return {"estate_truth_sha256": content_hash(truth), "observability_contract_sha256": content_hash(contract),
            "agent_property_matrix_sha256": content_hash(matrix), "agents": len(truth["agents"]), "summary": truth["summary"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("generate", "seal", "validate", "determinism", "render"))
    ap.add_argument("--seed", default=V.DT1_CANONICAL_SEED)
    ap.add_argument("--out", default=str(ART))
    ap.add_argument("--base-commit", default=None)
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    out = Path(a.out)
    grounding = load_grounding(ART)
    if a.command == "generate":
        if out != ART:
            shutil.copy2(ART / "schema_grounding.json", out / "schema_grounding.json") if out.exists() else None
        res = generate(a.seed, out, grounding)
        print(json.dumps({k: v for k, v in res.items() if k != "summary"}, indent=1))
        print(json.dumps(res["summary"], indent=1, sort_keys=True))
        return 0
    if a.command == "seal":
        base = a.base_commit or (ROOT / "lab" / "dt1" / "BASE_COMMIT").read_text(encoding="utf-8").strip()
        anchor = seal_mod.seal(out, root=ROOT, seed=a.seed, generator_version=V.GENERATOR_VERSION,
                               schema_grounding_version=grounding["schema_grounding_version"],
                               estate_truth_schema_version=V.ESTATE_TRUTH_SCHEMA_VERSION,
                               observability_contract_version=V.OBSERVABILITY_CONTRACT_VERSION,
                               matrix_version=V.AGENT_PROPERTY_MATRIX_VERSION, base_commit=base)
        print(json.dumps(anchor, indent=1))
        return 0
    if a.command == "validate":
        rep = validator.validate(out, grounding=grounding, base_commit=a.base_commit, repo_root=ROOT)
        for r in rep.results:
            print(("PASS " if r["ok"] else "FAIL ") + r["check"] + (f" -- {r['detail']}" if r["detail"] and not r["ok"] else ""))
        print(f"{'VALID' if rep.ok else 'INVALID'}: {sum(r['ok'] for r in rep.results)}/{len(rep.results)} checks passed")
        return 0 if rep.ok else 1
    if a.command == "determinism":
        hashes = []
        for i in range(a.runs):
            tmp = Path(tempfile.mkdtemp(prefix="dt1-det-"))
            shutil.copy2(ART / "schema_grounding.json", tmp / "schema_grounding.json")
            res = generate(a.seed, tmp, grounding)
            hashes.append({k: res[k] for k in ("estate_truth_sha256", "observability_contract_sha256", "agent_property_matrix_sha256")})
            shutil.rmtree(tmp, ignore_errors=True)
        identical = all(h == hashes[0] for h in hashes)
        tmp = Path(tempfile.mkdtemp(prefix="dt1-det-"))
        shutil.copy2(ART / "schema_grounding.json", tmp / "schema_grounding.json")
        other = generate(a.seed + "-negative-control", tmp, grounding)
        shutil.rmtree(tmp, ignore_errors=True)
        differs = other["estate_truth_sha256"] != hashes[0]["estate_truth_sha256"]
        print(json.dumps({"runs": a.runs, "identical": identical, "hashes": hashes[0], "different_seed_differs": differs}, indent=1))
        return 0 if identical and differs else 1
    if a.command == "render":
        truth = json.loads((out / "estate_truth.json").read_text(encoding="utf-8"))
        matrix = json.loads((out / "agent_property_matrix.json").read_text(encoding="utf-8"))
        contract = json.loads((out / "observability_contract.json").read_text(encoding="utf-8"))
        DOCS.mkdir(parents=True, exist_ok=True)
        (DOCS / "AGENT_PROPERTY_MATRIX.md").write_text(render_markdown(matrix, truth), encoding="utf-8")
        L = ["# OBSERVABILITY_CONTRACT — DT1 Stage 1 (rendered from `lab/dt1/artifacts/observability_contract.json`)", "",
             f"Contract version `{contract['contract_version']}`; generator `{contract['generator']}`; gap status at grounding `{contract['gap_status_at_grounding']}`.", "",
             f"**Derivation rule.** {contract['derivation_rule']}", "", "| id | fact class | applies to | class | evidence / missing evidence / control boundary | precondition | gap | code refs | justification |",
             "|---|---|---|---|---|---|---|---|---|"]
        for e in contract["entries"]:
            ev = e["evidence_source"] or e["missing_evidence"] or e["control_boundary"] or ""
            L.append(f"| {e['id']} | `{e['fact_class']}` | {e['applies_to']} | **{e['classification']}** | {ev} | {e['precondition'] or '—'} | {e['gap_id'] or '—'} | "
                     + ", ".join(f"`{r}`" for r in e["code_refs"]) + f" | {e['justification']} |")
        L += ["", f"Summary: {json.dumps(contract['summary'])}", ""]
        (DOCS / "OBSERVABILITY_CONTRACT.md").write_text("\n".join(L), encoding="utf-8")
        print("rendered AGENT_PROPERTY_MATRIX.md and OBSERVABILITY_CONTRACT.md")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
