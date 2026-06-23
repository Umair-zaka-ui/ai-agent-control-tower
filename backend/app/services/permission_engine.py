"""Permission engine.

Answers a single question: *is this agent allowed to perform this action on
this resource?* A permission is granted only when an explicit rule exists with
``allowed = True``. Missing rules and ``allowed = False`` rules both deny.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.permission import Permission


@dataclass(frozen=True)
class PermissionResult:
    allowed: bool
    reason: str


def check_permission(
    db: Session,
    agent_id: uuid.UUID,
    resource: str,
    action: str,
) -> PermissionResult:
    """Look up the permission rule for ``(agent, resource, action)``."""
    stmt = select(Permission).where(
        Permission.agent_id == agent_id,
        Permission.resource == resource,
        Permission.action == action,
    )
    permission = db.execute(stmt).scalar_one_or_none()

    if permission is None:
        return PermissionResult(
            allowed=False,
            reason=(
                f"No permission rule exists for resource '{resource}' "
                f"and action '{action}'."
            ),
        )

    if not permission.allowed:
        return PermissionResult(
            allowed=False,
            reason=(
                f"Permission for resource '{resource}' and action '{action}' "
                "is explicitly denied."
            ),
        )

    return PermissionResult(
        allowed=True,
        reason=(
            f"Permission granted for resource '{resource}' and action '{action}'."
        ),
    )
