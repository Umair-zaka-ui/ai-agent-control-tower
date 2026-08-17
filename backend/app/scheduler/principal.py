"""Phase 3.8 -- the principal scheduled handlers act under.

Phases 3.5 and 3.7 both expose bounded operations that take an ``actor: User``
and use ``actor.organization_id`` to scope Phase 3.1's idempotency contract.
A scheduler has no human, so it needs a principal -- and the choice of which
one is a decision about audit integrity, not plumbing.

**What this does:** one non-human ``users`` row per organization, created on
demand, and passed as the actor for that organization's scheduled work.

**Why not the alternatives**, both of which were considered and rejected:

- *Reusing an existing privileged user* (the org owner, say) needs no new rows
  and no new code, but it makes the audit trail state that a specific real
  person triggered every scheduled canary advance and rollback. Phase 3.7
  deliberately writes ``initiated_by = NULL`` for automatic rollbacks for
  exactly this reason -- the trail must never claim a person acted when none
  did -- and borrowing a human's identity here would undo that on the very
  path 3.7 was protecting.
- *Widening the bounded operations to accept ``actor=None``* is arguably the
  cleanest semantics, but it modifies ``canary.py``, which Phases 3.6 and 3.7
  both pin byte-identical to ``main`` by test. Those files stay untouched.

So the principal is real (satisfying every existing signature unchanged) and
visibly not a person (satisfying the audit-integrity property).

**It cannot authenticate.** ``password_hash`` is set to a value no hashing
scheme this platform uses can ever produce, and ``is_active`` is false, so
every credential-verification path rejects it before any comparison. It exists
to be an *attributable* principal, never a usable login -- a test asserts both
properties rather than trusting the construction.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.models.user import User

#: Local-part of the automation principal's address. The domain is
#: ``.invalid``, which RFC 2606 reserves precisely so it can never resolve --
#: no mail this platform sends can reach it, deliberately.
AUTOMATION_EMAIL_TEMPLATE = "scheduler+{organization_id}@automation.invalid"
AUTOMATION_NAME = "Platform Scheduler (automation)"

#: Not a hash of anything. Every verifier this platform uses (argon2id, and
#: legacy bcrypt) rejects a string of this shape outright, so there is no
#: password that validates against it -- including the empty string.
_UNUSABLE_PASSWORD_HASH = "!scheduler-automation-no-login!"


def automation_email(organization_id: uuid.UUID) -> str:
    return AUTOMATION_EMAIL_TEMPLATE.format(organization_id=organization_id)


def is_automation_principal(user: User | None) -> bool:
    return user is not None and user.email.endswith("@automation.invalid")


def get_or_create(db: Session, organization_id: uuid.UUID) -> User:
    """The automation principal for one organization, created on first use.

    Created lazily rather than seeded for every organization at migration
    time: most organizations never schedule anything, and a migration that
    manufactured a user row for all 4,500+ of them would be a large, silent
    write in service of a feature they may never enable.

    Safe under concurrency -- two scheduler instances calling this at the same
    moment race to ``INSERT`` and the loser reads the winner's row, the same
    claim-then-fall-back-to-read pattern Phase 3.1's idempotency service
    already uses rather than a check-then-act that has a window between the
    two."""
    existing = db.execute(
        select(User).where(User.organization_id == organization_id,
                           User.email == automation_email(organization_id))
    ).scalars().first()
    if existing is not None:
        return existing

    principal = User(
        organization_id=organization_id,
        name=AUTOMATION_NAME,
        email=automation_email(organization_id),
        password_hash=_UNUSABLE_PASSWORD_HASH,
        # SUPER_ADMIN because a scheduled handler must be able to do whatever
        # the job it runs requires, and the platform's permission catalog is
        # granted wholesale to that role. The safety property here is *not*
        # that the principal is weak -- it is that it cannot log in at all, so
        # its authority is only ever exercised by code paths the platform
        # itself dispatches.
        role=UserRole.SUPER_ADMIN,
        is_active=False,
        status="ACTIVE",
    )
    db.add(principal)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.execute(
            select(User).where(User.organization_id == organization_id,
                               User.email == automation_email(organization_id))
        ).scalars().one()
    db.refresh(principal)
    return principal
