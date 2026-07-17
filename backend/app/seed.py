"""Seed the database with demo data (Phase 1 + Phase 2).

Run with:  python -m app.seed   (from the ``backend`` directory)

Creates:
  * Organization: "Demo Healthcare Org"
  * Users:  admin@example.com / reviewer@example.com  (password: DemoPass!2026)
  * Agents: BillingAgent, SchedulingAgent, ClinicalSummaryAgent (+ an API key each)
  * Permission rules for each agent
  * RBAC roles/permissions (and links users to matching roles)
  * Example policies (e.g. "Large Claim Approval")

The script is idempotent: re-running it will not create duplicates.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

# Register the identity tables on shared SQLAlchemy metadata before the seed
# flushes models (User.department_id references the departments table).
import app.identity.models  # noqa: F401

from app.core.database import SessionLocal
from app.core.enums import ActionDecision, UserRole
from app.core.security import generate_api_key, hash_api_key
from app.identity.security.passwords import hash_user_password
from app.models.agent import Agent
from app.models.organization import Organization
from app.models.permission import Permission
from app.models.policy import Policy
from app.models.user import User
from app.services import api_key_service, rbac_service
from app.authorization.seeding import seed_authorization

DEMO_ORG_NAME = "Demo Healthcare Org"
DEMO_PASSWORD = "DemoPass!2026"

DEMO_USERS = [
    {"name": "Demo Admin", "email": "admin@example.com", "role": UserRole.ADMIN},
    {"name": "Demo Reviewer", "email": "reviewer@example.com", "role": UserRole.REVIEWER},
]

DEMO_AGENTS: dict[str, tuple[str, list[tuple[str, str, bool]]]] = {
    "BillingAgent": (
        "billing",
        [
            ("CLAIM", "READ", True),
            ("CLAIM", "SUBMIT_CLAIM", True),
            ("PATIENT_RECORD", "READ", True),
            ("PATIENT_RECORD", "UPDATE_RECORD", False),
        ],
    ),
    "SchedulingAgent": (
        "scheduling",
        [
            ("APPOINTMENT", "READ", True),
            ("APPOINTMENT", "CREATE", True),
            ("APPOINTMENT", "CANCEL", True),
        ],
    ),
    "ClinicalSummaryAgent": (
        "clinical",
        [
            ("PATIENT_RECORD", "READ", True),
            ("DIAGNOSIS", "CREATE", False),
            ("MEDICATION", "RECOMMEND", False),
        ],
    ),
}

# (name, resource, action, conditions, decision, priority)
DEMO_POLICIES = [
    (
        "Large Claim Approval",
        "CLAIM",
        "SUBMIT_CLAIM",
        {"amount_gt": 10000},
        ActionDecision.PENDING_APPROVAL,
        100,
    ),
    (
        "Block Huge Claim",
        "CLAIM",
        "SUBMIT_CLAIM",
        {"amount_gt": 100000},
        ActionDecision.BLOCK,
        200,
    ),
]


def _get_or_create_org(db: Session) -> Organization:
    org = db.execute(
        select(Organization).where(Organization.name == DEMO_ORG_NAME)
    ).scalar_one_or_none()
    if org is None:
        org = Organization(name=DEMO_ORG_NAME)
        db.add(org)
        db.flush()
        print(f"  + organization: {org.name}")
    else:
        print(f"  = organization already exists: {org.name}")
    return org


def _seed_users(db: Session, org: Organization) -> None:
    for spec in DEMO_USERS:
        existing = db.execute(
            select(User).where(User.email == spec["email"])
        ).scalar_one_or_none()
        if existing is not None:
            print(f"  = user already exists: {spec['email']}")
            continue
        db.add(
            User(
                organization_id=org.id,
                name=spec["name"],
                email=spec["email"],
                password_hash=hash_user_password(DEMO_PASSWORD),
                role=spec["role"],
                is_active=True,
            )
        )
        print(f"  + user: {spec['email']} ({spec['role'].value})")
    db.flush()


def _seed_agents(db: Session, org: Organization) -> None:
    for name, (agent_type, perms) in DEMO_AGENTS.items():
        agent = db.execute(
            select(Agent).where(Agent.organization_id == org.id, Agent.name == name)
        ).scalar_one_or_none()

        if agent is None:
            agent = Agent(
                organization_id=org.id,
                name=name,
                description=f"Demo {name}",
                agent_type=agent_type,
                api_key_hash=hash_api_key(generate_api_key()),  # legacy column
            )
            db.add(agent)
            db.flush()
        else:
            print(f"  = agent already exists: {name}")

        # Ensure every demo agent has at least one Phase 2 API key (shown once).
        if not api_key_service.list_keys(db, agent.id):
            _, raw_key = api_key_service.issue_api_key(db, agent)
            print(f"  + agent API key for {name}: {raw_key}")

        for resource, action, allowed in perms:
            exists = db.execute(
                select(Permission).where(
                    Permission.agent_id == agent.id,
                    Permission.resource == resource,
                    Permission.action == action,
                )
            ).scalar_one_or_none()
            if exists is None:
                db.add(
                    Permission(
                        organization_id=org.id,
                        agent_id=agent.id,
                        resource=resource,
                        action=action,
                        allowed=allowed,
                    )
                )
                print(f"      + permission: {resource}/{action} -> {allowed}")
    db.flush()


def _seed_policies(db: Session, org: Organization) -> None:
    for name, resource, action, conditions, decision, priority in DEMO_POLICIES:
        exists = db.execute(
            select(Policy).where(Policy.organization_id == org.id, Policy.name == name)
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                Policy(
                    organization_id=org.id,
                    name=name,
                    description=f"Demo policy: {name}",
                    resource=resource,
                    action=action,
                    conditions=conditions,
                    decision=decision.value,
                    priority=priority,
                    enabled=True,
                )
            )
            print(f"  + policy: {name} ({resource}/{action} -> {decision.value})")
        else:
            print(f"  = policy already exists: {name}")
    db.flush()


def seed() -> None:
    db = SessionLocal()
    try:
        print("Seeding demo data...")
        org = _get_or_create_org(db)
        _seed_users(db, org)
        _seed_agents(db, org)
        _seed_policies(db, org)
        print("  seeding RBAC roles/permissions...")
        rbac_service.seed_rbac(db, org)
        print("  seeding authorization groups/roles/hierarchy (Phase 4.3.1)...")
        seed_authorization(db)
        db.commit()
        print("Done.")
        print("\nLogin with:")
        print(f"  admin@example.com    / {DEMO_PASSWORD}  (ADMIN)")
        print(f"  reviewer@example.com / {DEMO_PASSWORD}  (REVIEWER)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
