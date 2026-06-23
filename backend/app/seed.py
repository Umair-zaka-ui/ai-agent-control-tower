"""Seed the database with demo data.

Run with:  python -m app.seed   (from the ``backend`` directory)

Creates:
  * Organization: "Demo Healthcare Org"
  * Users:  admin@example.com / reviewer@example.com  (password: password123)
  * Agents: BillingAgent, SchedulingAgent, ClinicalSummaryAgent
  * Permission rules for each agent

The script is idempotent: re-running it will not create duplicates.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.enums import UserRole
from app.core.security import generate_api_key, hash_api_key, hash_password
from app.models.agent import Agent
from app.models.organization import Organization
from app.models.permission import Permission
from app.models.user import User

DEMO_ORG_NAME = "Demo Healthcare Org"
DEMO_PASSWORD = "password123"

DEMO_USERS = [
    {"name": "Demo Admin", "email": "admin@example.com", "role": UserRole.ADMIN},
    {"name": "Demo Reviewer", "email": "reviewer@example.com", "role": UserRole.REVIEWER},
]

# agent name -> (agent_type, [(resource, action, allowed), ...])
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
                password_hash=hash_password(DEMO_PASSWORD),
                role=spec["role"],
                is_active=True,
            )
        )
        print(f"  + user: {spec['email']} ({spec['role'].value})")


def _seed_agents(db: Session, org: Organization) -> None:
    for name, (agent_type, perms) in DEMO_AGENTS.items():
        agent = db.execute(
            select(Agent).where(
                Agent.organization_id == org.id, Agent.name == name
            )
        ).scalar_one_or_none()

        if agent is None:
            api_key = generate_api_key()
            agent = Agent(
                organization_id=org.id,
                name=name,
                description=f"Demo {name}",
                agent_type=agent_type,
                api_key_hash=hash_api_key(api_key),
            )
            db.add(agent)
            db.flush()
            print(f"  + agent: {name}  (api_key: {api_key})")
        else:
            print(f"  = agent already exists: {name}")

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


def seed() -> None:
    db = SessionLocal()
    try:
        print("Seeding demo data...")
        org = _get_or_create_org(db)
        _seed_users(db, org)
        _seed_agents(db, org)
        db.commit()
        print("Done.")
        print("\nLogin with:")
        print("  admin@example.com    / password123  (ADMIN)")
        print("  reviewer@example.com / password123  (REVIEWER)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
