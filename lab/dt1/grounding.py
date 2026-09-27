"""DT1 Stage 1 - SCHEMA GROUNDING (run once by the executing session).

    backend/.venv/Scripts/python lab/dt1/grounding.py

Produces the machine-readable field/enum map every other DT1 artifact must use:
``lab/dt1/artifacts/schema_grounding.json`` (canonical bytes) and a rendered
``docs/dt1/SCHEMA_GROUNDING.md``. Its content hash is the
``schema_grounding_version`` that feeds determinism.

Two inspection methods, both read-only:
  * **AST scan of the source files** for module-level constant vocabularies
    (tuples / dicts / frozensets of strings) - the preferred method, no import.
  * **`Base.metadata` introspection** for exact column names, types, nullability,
    defaults and constraints. Justification: SQLAlchemy models are declarative
    Python, so the only exact, mechanical way to read every column with its
    constraints is the metadata the models register; this module is the ONLY
    DT1 module allowed to import ``app`` (the architecture guard asserts that
    the generator, contract, matrix, seal and validator import nothing from it),
    it opens no database connection, and it runs once, before generation.

Also records the gap re-verification evidence (F6-1, I-1, I-2, F-2, V9-1) with
file:line references, and the repository state at grounding time.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
APP = BACKEND / "app"
ART = ROOT / "lab" / "dt1" / "artifacts"
DOCS = ROOT / "docs" / "dt1"

CONSTANT_FILES = [
    "app/models/agent.py", "app/models/graph.py", "app/models/discovery.py", "app/models/bridge.py",
    "app/models/threat.py", "app/models/posture.py", "app/models/runtime.py",
    "app/runtime/registry/control.py", "app/runtime/registry/services.py", "app/runtime/registry/schemas.py",
    "app/runtime/services.py", "app/bridge/modes.py", "app/bridge/capabilities.py", "app/graph/traversal.py",
    "app/graph/dependencies.py", "app/graph/service.py", "app/discovery/reconciliation.py",
    "app/threat/containment.py", "app/threat/rules.py", "app/posture/rules.py",
    "app/discovery/adapters/http_agent_registry.py", "app/discovery/adapters/aws_bedrock_agents.py",
]
TABLES = [
    "organizations", "users", "agents", "agent_identities", "service_accounts", "external_clients",
    "federated_identities", "delegations", "tools", "tool_credentials", "provider_credentials",
    "connector_credentials", "mcp_servers", "resources", "control_graph_edges", "discovery_sources",
    "discovery_runs", "discovery_observations", "discovery_findings", "posture_findings", "threat_findings",
    "containment_actions", "external_capability_grants", "external_gateway_calls", "external_request_nonces",
    "agent_executions", "runtime_governance_decisions", "agent_ownership_history",
]


def canonical_bytes(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _lit(node):
    """Evaluate a constant-vocabulary expression without importing anything."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        vals = [_lit(e) for e in node.elts]
        return vals if all(v is not None for v in vals) else None
    if isinstance(node, ast.Dict):
        out = {}
        for k, v in zip(node.keys, node.values):
            kk, vv = _lit(k), _lit(v)
            if kk is None or vv is None:
                return None
            out[str(kk)] = vv
        return out
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("frozenset", "set", "tuple", "list") and len(node.args) == 1:
        return _lit(node.args[0])
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Decimal" and len(node.args) == 1:
        return _lit(node.args[0])   # Decimal("0.75") -> "0.75" (kept as the literal string)
    return None


def scan_constants() -> dict:
    found: dict = {}
    for rel in CONSTANT_FILES:
        p = BACKEND / rel
        if not p.exists():
            found[rel] = {"ABSENT": True}
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        entries = {}
        for node in tree.body:
            targets = []
            value = None
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets, value = [node.target.id], node.value
            for name in targets:
                if not name.isupper() or value is None:
                    continue
                v = _lit(value)
                if v is None:
                    continue
                if isinstance(v, (list, dict)) or (isinstance(v, (str, int, float)) and name.endswith(("_DEPTH", "_THRESHOLD", "_KEY", "_STATE", "_NAME", "_PATH", "_METHOD"))):
                    entries[name] = {"value": v, "line": node.lineno}
        found[rel] = entries
    return found


def scan_metadata() -> dict:
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    import app.main  # noqa: F401 - registers every model; no connection is opened
    from app.core.database import Base
    out = {}
    for t in TABLES:
        tbl = Base.metadata.tables.get(t)
        if tbl is None:
            out[t] = {"ABSENT": True}
            continue
        cols = {}
        for c in tbl.columns:
            d = None
            if c.default is not None:
                arg = getattr(c.default, "arg", None)
                d = "<callable>" if callable(arg) else (arg.value if hasattr(arg, "value") else arg)
                if not isinstance(d, (str, int, float, bool, type(None))):
                    d = str(d)
            cols[c.name] = {"type": str(c.type), "nullable": bool(c.nullable), "default": d,
                            "fk": sorted(f"{f.column.table.name}.{f.column.name}" for f in c.foreign_keys)}
        checks = sorted(str(k.sqltext) for k in tbl.constraints if type(k).__name__ == "CheckConstraint")
        uniques = sorted([c.name for c in k.columns] for k in tbl.constraints if type(k).__name__ == "UniqueConstraint")
        uniques = [list(u) for u in uniques]
        out[t] = {"columns": cols, "check_constraints": checks, "unique_constraints": uniques}
    return out


def grep(pattern: str, paths: list[str], *, flags=0) -> list[dict]:
    hits = []
    rx = re.compile(pattern, flags)
    for rel in paths:
        p = BACKEND / rel
        files = sorted(p.rglob("*.py")) if p.is_dir() else ([p] if p.exists() else [])
        for f in files:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if rx.search(line):
                    hits.append({"file": str(f.relative_to(BACKEND)).replace("\\", "/"), "line": i, "text": line.strip()[:160]})
    return hits


def gap_evidence() -> dict:
    return {
        "F6-1": {
            "claim": "threat detection keys off ACT-run execution signals; gateway-enforced agents' denials (external_gateway_calls) are never read by any threat rule",
            "threat_rules_reading_execution_tables": grep(r"AgentExecution|RuntimeGovernanceDecision|ToolCall", ["app/threat/rules.py"])[:12],
            "threat_package_reading_gateway_calls": grep(r"external_gateway_calls|ExternalGatewayCall", ["app/threat"]),
            "gateway_records_written_at": grep(r"ExternalGatewayCall\(", ["app/bridge/gateway.py"]),
        },
        "I-1": {
            "claim": "no table/model represents an agent's runtime memory or context state (the first scan pattern also matched "
                     "`RequestContextMiddleware`, an HTTP middleware, and was tightened to ORM models and memory-state columns)",
            "memory_or_context_models": grep(r"class \w*Memory\w*\(Base|^\s+(memory_state|agent_memory|conversation_memory|context_state)\w*\s*:\s*Mapped", ["app/models", "app/identity/models"]),
            "nearest_related_field_not_a_state_model": grep(r"^\s+memory_requirements\s*:\s*Mapped", ["app/models/runtime.py"]),
        },
        "I-2": {
            "claim": "AGENT_DELEGATES_TO is declared but no code path creates such an edge (no producer, no ingestion)",
            "references_outside_models": grep(r"AGENT_DELEGATES_TO", ["app/graph", "app/bridge", "app/discovery", "app/runtime", "app/threat", "app/posture"]),
            "edge_creation_with_agent_delegates_to": grep(r"edge_type\s*=\s*['\"]AGENT_DELEGATES_TO['\"]", ["app"]),
        },
        "F-2": {
            "claim": "authority-chain reconstruction starts from agent_executions; external agents produce none",
            "reconstruct_reads_executions": grep(r"FROM agent_executions|def reconstruct_authority_chain|def _delegation_prefix", ["app/graph/traversal.py"]),
        },
        "V9-1": {
            "claim": "reachability CTE uses a path-array cycle guard (enumerates simple paths; exponential on branching graphs); default depth 16, cap 32",
            "path_array_guard": grep(r"ANY\(r\.path\)|r\.path \|\||^MAX_TRAVERSAL_DEPTH|^DEFAULT_TRAVERSAL_DEPTH", ["app/graph/traversal.py"]),
        },
    }


def repo_state() -> dict:
    def g(*a):
        return subprocess.run(["git", *a], cwd=str(ROOT), capture_output=True, text=True).stdout.strip()
    return {
        "head": g("rev-parse", "HEAD"), "branch": g("rev-parse", "--abbrev-ref", "HEAD"),
        "main": g("rev-parse", "main"), "origin_main": g("rev-parse", "origin/main"),
        "head_is_ancestor_of_main": subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "main"], cwd=str(ROOT)).returncode == 0,
        "migration_files_head": sorted(p.stem for p in (BACKEND / "migrations" / "versions").glob("*.py"))[-1],
        "instruction_sha256": {p.name: sha256(p.read_bytes()) for p in sorted((BACKEND / "instructions").glob("*.md"))},
    }


def render_md(g: dict) -> str:
    L = ["# SCHEMA_GROUNDING — DT1 Stage 1 (live inspection, read-only)", "",
         f"`schema_grounding_version` = `{g['schema_grounding_version']}` (SHA-256 of the canonical JSON in "
         f"`lab/dt1/artifacts/schema_grounding.json`, which excludes this hash and the timestamp).", "",
         "## Repository state at grounding", ""]
    for k, v in g["repository"].items():
        L.append(f"- **{k}**: `{v}`" if not isinstance(v, dict) else f"- **{k}**: " + ", ".join(f"`{a}` = `{b[:16]}…`" for a, b in v.items()))
    L += ["", "## Constant vocabularies (AST scan of source, file:line)", ""]
    for rel, entries in g["constants"].items():
        if entries.get("ABSENT"):
            L.append(f"- `{rel}`: **ABSENT**")
            continue
        for name, e in entries.items():
            v = e["value"]
            shown = json.dumps(v, ensure_ascii=False) if not isinstance(v, (list, dict)) or len(json.dumps(v)) < 400 else json.dumps(v, ensure_ascii=False)[:400] + "…"
            L.append(f"- `{rel}:{e['line']}` **{name}** = `{shown}`")
    L += ["", "## Tables (Base.metadata introspection — columns, constraints)", ""]
    for t, info in g["tables"].items():
        if info.get("ABSENT"):
            L.append(f"### `{t}` — ABSENT")
            continue
        L.append(f"### `{t}` ({len(info['columns'])} columns)")
        L.append("| column | type | nullable | default | fk |")
        L.append("|---|---|---|---|---|")
        for c, m in info["columns"].items():
            L.append(f"| `{c}` | {m['type']} | {m['nullable']} | {m['default']!r} | {', '.join(m['fk']) or ''} |")
        if info["check_constraints"]:
            L.append("CHECK: " + " · ".join(f"`{x[:140]}`" for x in info["check_constraints"]))
        if info["unique_constraints"]:
            L.append("UNIQUE: " + " · ".join("`" + ",".join(u) + "`" for u in info["unique_constraints"]))
        L.append("")
    L += ["## Gap re-verification (evidence with file:line)", ""]
    for gid, ev in g["gaps"].items():
        L.append(f"### {gid} — {ev['claim']}")
        for k, hits in ev.items():
            if k == "claim":
                continue
            L.append(f"- `{k}`: " + (f"{len(hits)} hit(s)" if hits else "**0 hits**"))
            for h in hits[:8]:
                L.append(f"    - `{h['file']}:{h['line']}` `{h['text'][:110]}`")
        L.append("")
    return "\n".join(L) + "\n"


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    constants = scan_constants()
    gaps = gap_evidence()
    repo = repo_state()
    tables = scan_metadata()
    content = {"constants": constants, "tables": tables, "gaps": gaps,
               "gap_status": {g: "PRESENT" for g in gaps}}
    # the gap statuses are derived mechanically from the evidence, not asserted
    content["gap_status"]["F6-1"] = "PRESENT" if gaps["F6-1"]["threat_rules_reading_execution_tables"] and not gaps["F6-1"]["threat_package_reading_gateway_calls"] else "CHANGED"
    content["gap_status"]["I-1"] = "PRESENT" if not gaps["I-1"]["memory_or_context_models"] else "CHANGED"
    content["gap_status"]["I-2"] = "PRESENT" if not gaps["I-2"]["edge_creation_with_agent_delegates_to"] else "CHANGED"
    content["gap_status"]["F-2"] = "PRESENT" if gaps["F-2"]["reconstruct_reads_executions"] else "CHANGED"
    content["gap_status"]["V9-1"] = "PRESENT" if any("ANY(r.path)" in h["text"] for h in gaps["V9-1"]["path_array_guard"]) else "CHANGED"
    version = sha256(canonical_bytes(content))
    full = {**content, "schema_grounding_version": version, "repository": repo}
    (ART / "schema_grounding.json").write_bytes(canonical_bytes(full))
    (DOCS / "SCHEMA_GROUNDING.md").write_text(render_md(full), encoding="utf-8")
    print(json.dumps({"schema_grounding_version": version, "gap_status": content["gap_status"],
                      "tables": len([t for t in tables if not tables[t].get("ABSENT")]),
                      "absent_tables": [t for t in tables if tables[t].get("ABSENT")],
                      "constant_files_absent": [f for f, e in constants.items() if e.get("ABSENT")]}, indent=1))


if __name__ == "__main__":
    main()
