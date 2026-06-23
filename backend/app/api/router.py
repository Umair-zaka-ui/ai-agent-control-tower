"""Aggregates every route module into a single API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    agent_actions,
    agents,
    approvals,
    audit_logs,
    auth,
    organizations,
    permissions,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(users.router)
api_router.include_router(agents.router)
api_router.include_router(permissions.router)
api_router.include_router(agent_actions.router)
api_router.include_router(approvals.router)
api_router.include_router(audit_logs.router)
