"""Permission evaluator (SRS §9).

The authoritative permission logic lives in ``rbac_service``; this evaluator is
the identity-layer facade over it, so identity callers depend only on the
identity package. Permission lookups are namespaced (e.g. ``agent.create``).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import rbac_service


class PermissionEvaluator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def effective_permissions(self, user: User) -> set[str]:
        """All permission codes the user holds (role-derived)."""
        return rbac_service.get_user_permissions(self.db, user)

    def has(self, user: User, code: str) -> bool:
        """Whether the user holds a single namespaced permission."""
        return rbac_service.user_has_permission(self.db, user, code)

    def has_all(self, user: User, codes: list[str]) -> bool:
        granted = self.effective_permissions(user)
        return all(code in granted for code in codes)

    def has_any(self, user: User, codes: list[str]) -> bool:
        granted = self.effective_permissions(user)
        return any(code in granted for code in codes)
