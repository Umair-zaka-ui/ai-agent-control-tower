"""Lab-only evidence for the projection decision (§5): is the reachability cliff
relational (ADR-0017 in doubt) or algorithmic (the query shape)?

Runs, against the loaded fixture and the same chain head, three read-only
queries under a statement timeout:

  A. the product's CTE shape (path-array cycle guard -> enumerates simple paths)
  B. a frontier-dedup shape (``UNION`` on (node, depth) with no path column ->
     each node materialises at most once per depth; cycles die by dedup)
  C. shape B plus a parent pointer, so a shortest path can still be explained

and reports node-set equality (A vs B at a depth where A completes), then the
cost of B/C at depths A cannot reach. NOTHING in the product is changed; this
is measurement of an alternative, recorded for the architecture gate.

    python lab/scale/reach_variant_probe.py --manifest lab/run/results/v9_fixture_worst_100000.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labenv  # noqa: E402

labenv.activate()
import app.main  # noqa: E402,F401
from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

A_SQL = """
WITH RECURSIVE reach(node_type, node_id, depth, path) AS (
    SELECT CAST('AGENT' AS varchar), CAST(:start AS uuid), 0, ARRAY[CAST(:key AS text)]
  UNION ALL
    SELECT e.target_type, e.target_id, r.depth + 1, r.path || (e.target_type || ':' || e.target_id)
    FROM reach r JOIN control_graph_edges e
      ON e.source_type = r.node_type AND e.source_id = r.node_id AND e.organization_id = :org
     AND e.revoked_at IS NULL AND (e.valid_until IS NULL OR e.valid_until > now()) AND e.edge_type = ANY(:types)
    WHERE r.depth < :d AND NOT ((e.target_type || ':' || e.target_id) = ANY(r.path))
)
SELECT DISTINCT ON (node_type, node_id) node_type, node_id, depth FROM reach WHERE depth > 0
ORDER BY node_type, node_id, depth
"""
B_SQL = """
WITH RECURSIVE reach(node_type, node_id, depth) AS (
    SELECT CAST('AGENT' AS varchar), CAST(:start AS uuid), 0
  UNION
    SELECT e.target_type, e.target_id, r.depth + 1
    FROM reach r JOIN control_graph_edges e
      ON e.source_type = r.node_type AND e.source_id = r.node_id AND e.organization_id = :org
     AND e.revoked_at IS NULL AND (e.valid_until IS NULL OR e.valid_until > now()) AND e.edge_type = ANY(:types)
    WHERE r.depth < :d
)
SELECT node_type, node_id, min(depth) AS depth FROM reach WHERE depth > 0 GROUP BY node_type, node_id
"""
C_SQL = """
WITH RECURSIVE reach(node_type, node_id, depth, via_edge, parent_type, parent_id) AS (
    SELECT CAST('AGENT' AS varchar), CAST(:start AS uuid), 0, NULL::uuid, NULL::varchar, NULL::uuid
  UNION
    SELECT e.target_type, e.target_id, r.depth + 1, e.id, r.node_type, r.node_id
    FROM reach r JOIN control_graph_edges e
      ON e.source_type = r.node_type AND e.source_id = r.node_id AND e.organization_id = :org
     AND e.revoked_at IS NULL AND (e.valid_until IS NULL OR e.valid_until > now()) AND e.edge_type = ANY(:types)
    WHERE r.depth < :d
)
SELECT DISTINCT ON (node_type, node_id) node_type, node_id, depth, via_edge, parent_type, parent_id
FROM reach WHERE depth > 0 ORDER BY node_type, node_id, depth
"""


def run(sql: str, params: dict, timeout: str = "60s"):
    db = SessionLocal()
    try:
        db.execute(text(f"SET LOCAL statement_timeout = '{timeout}'"))
        t = time.perf_counter()
        rows = db.execute(text(sql), params).all()
        return {"ms": round((time.perf_counter() - t) * 1000, 1), "rows": len(rows),
                "nodes": sorted((str(r[0]), str(r[1])) for r in rows)}
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__, "detail": str(exc).splitlines()[0][:140]}
    finally:
        db.rollback()
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    a = ap.parse_args()
    mp = Path(a.manifest)
    mp = mp if mp.is_absolute() else labenv.ROOT / mp
    m = json.loads(mp.read_text(encoding="utf-8"))
    meas = m["measured"]
    base = {"start": meas["chain_heads"][0], "key": "AGENT:" + meas["chain_heads"][0], "org": meas["org_id"],
            "types": ["AGENT_DELEGATES_TO", "TRUSTS"]}
    out = {"rung": m["rung"], "dist": m["dist"], "tenant_agents": meas["agents"], "tenant_edges": meas["edges"],
           "equivalence": [], "variant_ladder": []}
    for d in (4, 8):
        ra, rb = run(A_SQL, {**base, "d": d}), run(B_SQL, {**base, "d": d})
        eq = ("nodes" in ra and "nodes" in rb and ra["nodes"] == rb["nodes"])
        out["equivalence"].append({"depth": d, "A_ms": ra.get("ms"), "A_nodes": ra.get("rows"), "A_error": ra.get("error"),
                                   "B_ms": rb.get("ms"), "B_nodes": rb.get("rows"), "identical_node_sets": eq})
        print(f"depth {d}: A={ra.get('ms', ra.get('error'))}ms nodes={ra.get('rows')} | B={rb.get('ms')}ms nodes={rb.get('rows')} | identical={eq}", flush=True)
    for d in (12, 16, 24, 32):
        rb, rc = run(B_SQL, {**base, "d": d}), run(C_SQL, {**base, "d": d})
        out["variant_ladder"].append({"depth": d, "B_ms": rb.get("ms"), "B_nodes": rb.get("rows"), "B_error": rb.get("error"),
                                      "C_ms": rc.get("ms"), "C_nodes": rc.get("rows"), "C_error": rc.get("error")})
        print(f"depth {d}: B={rb.get('ms', rb.get('error'))}ms nodes={rb.get('rows')} | C(with parent)={rc.get('ms', rc.get('error'))}ms nodes={rc.get('rows')}", flush=True)
    # and the product shape at the API default depth, for the record (bounded)
    ra = run(A_SQL, {**base, "d": 16})
    out["A_at_default_depth_16"] = {k: v for k, v in ra.items() if k != "nodes"}
    print(f"A at depth 16: {out['A_at_default_depth_16']}", flush=True)
    dest = labenv.RESULTS / f"v9_reach_variant_{m['dist']}_{m['rung']}.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("wrote", dest)


if __name__ == "__main__":
    main()
