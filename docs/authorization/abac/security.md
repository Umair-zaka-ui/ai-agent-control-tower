# ABAC security model (Phase 4.3.5 §40, §42)

## Guarantees

1. **Default deny is unchanged.** ABAC layers *restrictions* over the baseline;
   with no applicable policy the baseline decision stands, and ABAC can never
   grant what RBAC/resource authorization denied (§4).
2. **No code execution.** Policies are data; conditions resolve through the
   fixed `OperatorRegistry`; unregistered operators never match; dynamic
   evaluation of any kind is absent by construction.
3. **Only registered attributes.** Validation rejects unknown attribute names
   (`ABAC_ATTRIBUTE_NOT_FOUND`), so a policy cannot probe arbitrary object
   fields.
4. **Subject attributes cannot be spoofed.** `identity.*` keys are stripped
   from request-supplied context on every live path; they come only from the
   server-side provider. The simulator (permission-gated, read-only) is the
   sole exception.
5. **ReDoS-guarded regex.** Patterns are length-capped, compile-checked and
   nested-quantifier-rejected at validation *and* re-checked at runtime;
   input is length-capped.
6. **Tenant isolation.** Policy resolution loads only the caller's org +
   platform policies; cross-org policy reads 404; evaluations are org-scoped;
   attribute providers never load another tenant's data.
7. **Platform supremacy.** Platform-scoped policies require platform
   administration to create/publish and cannot be overridden by organization
   policies (they sort first and deny-overrides applies).
8. **Publication is privileged and separable.** `authorization.abac.publish`
   is distinct from create/update, supporting segregation of duties (§37).
9. **Immutable, versioned history.** Published versions are snapshotted and
   cannot be edited or deleted; rollback publishes a *new* version.
10. **Redaction.** RESTRICTED attribute values never appear in user-facing
    reasons or logs; full explanations require `authorization.abac.audit`.
11. **Exceptions are constrained.** Time-boxed (mandatory expiry), approved,
    audited, auto-expiring, and disabled unless explicitly created.
12. **Everything is audited.** 17 §38 event types plus one `abac_evaluations`
    row per decision with request/correlation ids (§43).

## Security test coverage (§42)

`tests/authorization/test_abac.py` + `test_abac_unit.py` cover: cross-tenant
policy/evaluation isolation, injection-shaped operators never matching,
ReDoS pattern rejection + bounded runtime, unauthorized publication (403),
subject-attribute spoofing dropped, malformed policy payloads rejected,
expired-exception behavior, and stale-cache invalidation on publish/disable.
