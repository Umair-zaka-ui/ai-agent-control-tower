# Semantic conventions — attributes and bounded cardinality

> **Phase 4.1 (ACT-SRS-M4 §12).** The stable attribute vocabulary for
> Milestone 4, and the rule that keeps a metrics backend from falling over.
> Defined in `app/observability/attributes.py`.

## The distinction everything here turns on

There are two different things telemetry does with an identifier, and conflating
them is how an observability stack dies.

**Trace attributes** answer *"which execution was this?"*. They are allowed —
required — to be high-cardinality. An `execution_id` that were not unique per
execution would be useless. They are attached to a trace or a row, both stored
once per occurrence, so their cost is **linear in traffic**.

**Metric labels** answer *"how many, grouped by what?"*. A time-series database
allocates one series per distinct combination of label values. Putting an
`execution_id` on a counter does not produce a counter — it produces one series
per execution, forever. The cost is not linear in traffic; it is **the product of
every label's cardinality**.

So the rule:

> **Every identity is a legal trace attribute. Only the bounded set is a legal
> metric label.**

## The stable attribute names

Defined once, as constants, so renaming one is a change in a single file rather
than an archaeology exercise across six phases.

| Attribute | Meaning | Metric-eligible? |
|---|---|---|
| `organization_id` | The tenant | No — high cardinality |
| `agent_id` | The agent | No — high cardinality |
| `agent_version_id` | The immutable version that ran | No — high cardinality |
| `deployment_id` | The deployment that served it | No — high cardinality |
| `execution_id` | The execution | No — high cardinality |
| `environment` | `DEVELOPMENT` / `STAGING` / `PRODUCTION` / … | **Yes** |
| `provider` | The model provider from the registry | **Yes** |
| `model` | The raw model string, e.g. `gpt-4o-mini` | No — unbounded |
| `model_category` | The vendor family, e.g. `gpt` | **Yes** |
| `tool_id` | The tool invoked | No — high cardinality |
| `worker_id` | The worker process | No — high cardinality |
| `status` | The execution/tool status enumeration | **Yes** |
| `error_class` | The shared `ProviderErrorClass` taxonomy | **Yes** |

Five metric dimensions. That is the whole allowlist:

```python
METRIC_DIMENSIONS = {"environment", "status", "provider", "model_category", "error_class"}
```

Each takes values from a small, closed vocabulary that **does not grow with
traffic**. `environment` is per-tenant configuration (a handful). `status` and
`error_class` are enumerations this codebase already owns. `provider` is the
registry's list.

### Why `model_category` and not `model`

A raw model name is unbounded — vendors ship new ones constantly, and a caller
may pass an arbitrary string into the model configuration. So the metric
dimension is the vendor family, derived by taking the segment before the first
separator:

| Raw `model` | `model_category` |
|---|---|
| `gpt-4o-mini` | `gpt` |
| `gpt-4.1` | `gpt` |
| `claude-opus-4` | `claude` |
| `llama3.2:3b` | `llama3` |

Coarse on purpose. A dimension precise enough to be interesting is usually
precise enough to be unbounded — and "unbounded" is the failure this exists to
prevent. The raw `model` is still on the trace, where it belongs and where it
costs nothing.

## The rule is structural, not remembered

`metric_labels()` is the **only** supported way to build a label dict:

```python
>>> metric_labels(environment="PRODUCTION", status="SUCCEEDED")
{'environment': 'PRODUCTION', 'status': 'SUCCEEDED'}

>>> metric_labels(execution_id="abc-123")
MetricCardinalityError: 'execution_id' is a high-cardinality identity: it belongs
on a trace or a domain row, never on a metric label (ACT-SRS-M4 §12). One series
per distinct value would be created. Allowed labels: ['environment',
'error_class', 'model_category', 'provider', 'status'].
```

Three properties worth noting:

1. **It raises rather than dropping the offending label.** Silently discarding a
   dimension gives a metric that looks right and aggregates wrong — the worst
   possible failure mode for a number someone will page on.

2. **The error says *why*.** An engineer told "`execution_id` is
   high-cardinality" fixes the call. One told "not allowed" files a ticket asking
   for it to be allowed.

3. **Default-deny.** A name nobody thought about is refused, not admitted. Adding
   a dimension means adding it to `METRIC_DIMENSIONS` deliberately, in a diff
   someone reviews — not at a call site.

### Three categories, checked in order

```python
SENSITIVE_ATTRIBUTES        # never a label, in any form — §12 forbids outright
HIGH_CARDINALITY_ATTRIBUTES # legal on a trace, illegal on a metric
METRIC_DIMENSIONS           # the allowlist
```

`SENSITIVE_ATTRIBUTES` covers names that carry a person or a payload rather than
an identity — `email`, `ip_address`, `prompt`, `tool_arguments`, `content`,
`reasoning`. These are not merely unbounded; they must never reach a metrics
backend even if someone decides the cardinality is acceptable.

The sets are asserted disjoint, because a name that were both metric-eligible
and high-cardinality would make the guard's behaviour depend on check order.

## Using the attribute set

```python
attributes = SemanticAttributes.build(
    organization_id=execution.organization_id,
    agent_id=execution.agent_id,
    execution_id=execution.id,
    model="gpt-4o-mini",
    environment="PRODUCTION",
    status="SUCCEEDED",
)

attributes.as_dict()        # everything non-null — for the trace
attributes.metric_labels()  # the bounded five — for a metric
```

`SemanticAttributes` is frozen: an attribute set describes a subject at a
moment, and mutating one after it has been attached to a span would silently
rewrite history.

Every field is optional. A deployment-level event has no `execution_id`; a tool
span has no `provider`. Encoding that as `None` rather than as a
required-everywhere field is what keeps **one** attribute vocabulary usable
across every span kind instead of needing one per kind.

`build()` ignores unknown keys rather than raising, so a caller assembling
attributes from a domain row does not have to filter the row first.

## The metrics surface (Phase 4.6) and SLOs (4.7)

The allowlist landed in 4.1, before anything could misuse it — the cheapest
moment to make a mistake impossible. **Phase 4.6** built the metrics surface on
top of it: `GET /metrics` (Prometheus exposition, authenticated + tenant-scoped)
and `metric_label_set()`, which reuses `HIGH_CARDINALITY_ATTRIBUTES` /
`SENSITIVE_ATTRIBUTES` / `METRIC_DIMENSIONS` here as its denylist and allowlist,
plus a small declared 4.6 extension for two bounded behavioral-finding enums.
There is still no metrics *storage* backend and there will not be one — the
customer's collector stores. SLOs and alerting shipped in **Phase 4.7** on this
allowlist and the domain rows — see [`../operations/slos.md`](../operations/slos.md).

## Testing

The guard tests are **parametrized over the declared sets themselves**:

```python
@pytest.mark.parametrize("name", sorted(HIGH_CARDINALITY_ATTRIBUTES))
def test_ac06_no_high_cardinality_identity_can_be_a_metric_label(name):
    with pytest.raises(MetricCardinalityError):
        metric_labels(**{name: "some-value"})
```

So an identity added to the codebase later cannot be quietly left out of the
guard — adding it to the set adds a test for it.

## See also

- [architecture.md](./architecture.md) — the three-plane model and trace assembly
- [privacy.md](./privacy.md) — capture policy, the four modes, and
  redact-before-persist (Phase 4.8); the metadata attributes here are what
  `METADATA_ONLY` captures, and the denylist above is reused by 4.8's
  classification redaction
- [retention.md](./retention.md) — per-class retention (Phase 4.8)
