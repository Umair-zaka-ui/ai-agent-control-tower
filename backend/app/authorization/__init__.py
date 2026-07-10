"""Enterprise Authorization Platform (Phase 4.3).

Part 4.3.1 — the RBAC foundation: roles (with category/status/priority),
permission groups, a resource.action permission catalog, scoped role assignments,
an acyclic role hierarchy, and an authorization audit trail.

This package *extends* the existing flat RBAC (``app/models/rbac.py``,
``app/services/rbac_service.py``) rather than replacing it — the legacy
``roles``/``rbac_permissions``/``user_roles`` tables gain columns, and everything
that already resolves ``IdentityContext.permissions`` keeps working.
"""
