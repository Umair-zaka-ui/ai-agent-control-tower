# ADVERSARY ZONE — provisioned, IDLE in V2

Nothing in this directory is executed in V2. It exists so that V3+ can add
scenarios into a place that is already inside the lab's disposable, loopback-only
boundary, and so that the V2 reproducibility proof covers its provisioning.

| slot | V2 state | what V3+ may put here (subject to its own authorization) |
|---|---|---|
| `sandbox/` | empty directory | a disposable code-execution sandbox definition |
| `registry/` | empty directory | a malicious-dependency package index (lab-only) |
| `corpora/` | empty directory | injection corpora, never fetched by any V2 process |

Guard rails already in place: the rug-pull MCP server refuses `--phase after`
unless `ACTLAB_ALLOW_ADVERSARIAL=V3` is set (lab/mcp/mcp_server.py), and no V2
harness sets it.
