"""Phase 4.1 -- the runtime telemetry plane (ACT-SRS-M4, Milestone 4).

A **sibling** of ``app/runtime`` and ``app/integration``, not a module inside
either, and the placement carries the architecture. Telemetry is a *derived*
plane (§5): the domain is authoritative, telemetry observes it, and the
dependency runs one way only. ``app/runtime`` may call into here best-effort;
nothing here may call back into a runtime service. Living beside the runtime
rather than inside it is what makes that direction visible in the import graph
instead of merely stated in a document.

The modules, in dependency order:

- :mod:`~app.observability.scrubbing` -- the isolated secret scrubber. Standard
  library only; no platform imports at all.
- :mod:`~app.observability.attributes` -- semantic attributes and the bounded
  metric-label allowlist (§12).
- :mod:`~app.observability.capture` -- the METADATA_ONLY baseline, the data
  classes, and the structural chain-of-thought exclusion (§7).
- :mod:`~app.observability.trace` -- trace and span context; span ids are
  derived, never stored (§13).
- :mod:`~app.observability.events` -- the runtime-event contract, emitted
  best-effort and never gating (§9).
- :mod:`~app.observability.assembly` -- read-only trace assembly from existing
  domain rows.
"""
