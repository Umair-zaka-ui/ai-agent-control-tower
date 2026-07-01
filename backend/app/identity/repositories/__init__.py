"""Identity repository layer — all database access lives here (SRS §9, §16)."""

from app.identity.repositories.department_repository import DepartmentRepository
from app.identity.repositories.organization_repository import OrganizationRepository
from app.identity.repositories.permission_repository import PermissionRepository
from app.identity.repositories.role_repository import RoleRepository
from app.identity.repositories.session_repository import SessionRepository
from app.identity.repositories.user_repository import UserRepository

__all__ = [
    "UserRepository",
    "RoleRepository",
    "PermissionRepository",
    "OrganizationRepository",
    "DepartmentRepository",
    "SessionRepository",
]
