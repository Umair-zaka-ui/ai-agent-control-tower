"""Phase 2.3.1 SRS ACT-INT-FR-183 — IdP group/role claim → platform role
mapping.

Pure, no database, no I/O. Given the normalized group/role values a
verified assertion carried (an OIDC ``groups``/``roles`` claim, a SAML
group attribute) and an organization's own configured mapping rules,
returns the platform role *names* that apply — configuration, not code,
exactly as ``ACT-INT-FR-183`` requires. ``service.py`` resolves those
names to real ``Role`` rows and assigns them via the existing
``RoleEngine``; this module never touches the ORM."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def resolve_role_names(
    idp_values: Sequence[str], claim_mappings: Mapping[str, Any], *, default_role_name: str | None = None,
) -> list[str]:
    """``claim_mappings`` shape: ``{"rules": [{"idp_value": "AI-Admins",
    "role_name": "ADMIN"}, ...]}``. Returns every platform role name whose
    rule's ``idp_value`` appears in ``idp_values``, deduplicated and in
    rule-declaration order (the first matching rule for a given role name
    wins, but multiple *distinct* role names can all match — a user in
    two IdP groups mapped to two different platform roles gets both).
    Falls back to ``[default_role_name]`` only when nothing matched at
    all; returns ``[]`` (never a guessed role) when nothing matched and
    no default is configured — the caller decides what an empty result
    means (``UserProvisioningService`` already defaults an unset role to
    the safe, non-privileged ``VIEWER``, so this module does not need to
    guess one itself)."""
    rules = claim_mappings.get("rules") or []
    idp_value_set = set(idp_values)
    matched: list[str] = []
    for rule in rules:
        idp_value = rule.get("idp_value")
        role_name = rule.get("role_name")
        if not idp_value or not role_name:
            continue
        if idp_value in idp_value_set and role_name not in matched:
            matched.append(role_name)
    if matched:
        return matched
    if default_role_name:
        return [default_role_name]
    return []
