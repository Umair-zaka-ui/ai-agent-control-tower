# Authorization Context

One immutable object carries everything the pipeline evaluates (Phase 4.3.6
§5). It is built exclusively by the `AuthorizationContextBuilder` — controllers
and enforcement points pass raw request facts and never assemble contexts by
hand (§6).

## Shape

```python
AuthorizationContext(
    request_id="…",            # generated when absent; echoed everywhere
    correlation_id="…",        # defaults to the request id
    identity_id=UUID,          # user / agent / background principal
    identity_kind="USER",      # USER / AGENT / SYSTEM
    organization_id=UUID,
    permission="dataset.export",
    action="dataset.export",
    resource_type="DATASET", resource_id=UUID,   # optional
    session_id="…",            # HTTP paths only
    ip_address="…", user_agent="…",
    source="API",              # API / WORKER / SCHEDULER / WORKFLOW / AGENT
    roles=(…,),
    attributes={…},            # caller-supplied dynamic context (frozen mapping)
    environment={…},
    justification="…",         # satisfies a REQUIRE_JUSTIFICATION challenge
    decision_trace=(…,),       # append-only via with_trace()
)
```

## Immutability (§36)

The dataclass is frozen and `attributes`/`environment` are read-only mapping
proxies. Once built, no pipeline stage — and no business code holding a
reference — can manipulate what another stage already decided on. Appending to
the trace returns a **new** context (`with_trace`), so history cannot be
rewritten. The unit tests assert all of this.

## Spoof protection

`identity.*` keys are stripped from caller-supplied attributes at build time:
subject attributes always come from the server-side providers (4.3.5 §40). The
permission-gated policy simulator is the only surface allowed to override
subject attributes, and it is read-only.
