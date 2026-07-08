"""Phase 4 Part 4.2.2.2 - administrative session-management permissions.

Adds ``session.view`` and ``session.revoke`` to the RBAC catalog and grants them to
every existing SUPER_ADMIN and ADMIN role.

``seed_rbac`` already backfills grants, but it only runs when an organization is
*registered*. Without this migration the new codes would exist for organizations
created after the deploy and be silently missing for every organization created
before it — so admins of existing orgs would get a 403 from the new endpoints.

Idempotent: both statements are guarded, so a re-run is a no-op. Values are bound
parameters, not interpolated (a description containing an apostrophe is otherwise
a syntax error, and interpolating into DDL is a bad habit even in a migration).

Revision ID: 0010_session_admin_permissions
Revises: 0009_session_lifecycle
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010_session_admin_permissions"
down_revision: str | None = "0009_session_lifecycle"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("session.view", "View any user's sessions and devices in the organization"),
    ("session.revoke", "Force-logout another user's sessions (admin force-logout)"),
)

# SUPER_ADMIN holds every permission; ADMIN holds everything except rbac.manage.
_ROLES = ("SUPER_ADMIN", "ADMIN")


def upgrade() -> None:
    conn = op.get_bind()

    insert_permission = sa.text(
        """
        INSERT INTO rbac_permissions (id, code, description)
        SELECT gen_random_uuid(), :code, :description
        WHERE NOT EXISTS (SELECT 1 FROM rbac_permissions WHERE code = :code)
        """
    )
    for code, description in _PERMISSIONS:
        conn.execute(insert_permission, {"code": code, "description": description})

    grant = sa.text(
        """
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
          FROM roles r
          CROSS JOIN rbac_permissions p
         WHERE r.name = ANY(:roles)
           AND p.code = ANY(:codes)
           AND NOT EXISTS (
                 SELECT 1 FROM role_permissions rp
                  WHERE rp.role_id = r.id AND rp.permission_id = p.id
               )
        """
    )
    conn.execute(
        grant,
        {"roles": list(_ROLES), "codes": [code for code, _ in _PERMISSIONS]},
    )


def downgrade() -> None:
    conn = op.get_bind()
    codes = [code for code, _ in _PERMISSIONS]
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
             WHERE permission_id IN (SELECT id FROM rbac_permissions WHERE code = ANY(:codes))
            """
        ),
        {"codes": codes},
    )
    conn.execute(
        sa.text("DELETE FROM rbac_permissions WHERE code = ANY(:codes)"), {"codes": codes}
    )
