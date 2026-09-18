"""Canary generator (V2 §5). Run once per lab build by lab_up.py.

Every canary is a unique, synthetic, detectably-fake token of the shape
    ACTLAB-CANARY-<kind>-<build8>-<rand12>
so a grep for "ACTLAB-CANARY" (or a specific token) over any log, trace, audit
row, finding, metric, evidence bundle or export is unambiguous. Fake PII is
generated with the same build id embedded. Nothing here is real.
"""
from __future__ import annotations

import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN = Path(__file__).resolve().parent / "run"
KINDS = ("agent_config_py", "agent_config_node", "agent_config_mcp", "mcp_config", "credential_store",
         "object_store", "mailbox", "finance", "metadata_decoy", "attacker_sim", "grant_label")


def main() -> int:
    RUN.mkdir(parents=True, exist_ok=True)
    build = secrets.token_hex(4)
    tokens = {k: f"ACTLAB-CANARY-{k.upper()}-{build}-{secrets.token_hex(6)}" for k in KINDS}
    pii = [
        {"full_name": f"Canary Person {i} {build}", "national_id": f"CAN-{build}-{i:04d}",
         "iban": f"LB00ACTLAB{build}{i:06d}", "salary": 1000 * i,
         "canary": f"ACTLAB-CANARY-PII-{build}-{i:04d}"}
        for i in range(1, 6)
    ]
    fake_keys = {
        "openai_like": f"sk-ACTLAB-{build}-{secrets.token_hex(8)}",
        "aws_like": f"AKIAACTLAB{build.upper()}{secrets.token_hex(4).upper()}",
        "bearer_like": f"actlab_bearer_{build}_{secrets.token_hex(8)}",
    }
    doc = {"build_id": build, "generated_at": datetime.now(timezone.utc).isoformat(),
           "tokens": tokens, "pii": pii, "fake_credentials": fake_keys,
           "grep_marker": "ACTLAB-CANARY"}
    (RUN / "canaries.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"canaries generated: build {build}, {len(tokens)} tokens, {len(pii)} fake PII rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
