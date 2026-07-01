"""Aggregates identity routes under the versioned prefix (SRS §17)."""

from __future__ import annotations

from fastapi import APIRouter

from app.identity.api.routes import departments, organizations, roles, sessions, users

# All identity endpoints live under /api/v1/identity/*
identity_router = APIRouter(prefix="/api/v1/identity")
identity_router.include_router(users.router)
identity_router.include_router(organizations.router)
identity_router.include_router(departments.router)
identity_router.include_router(roles.router)
identity_router.include_router(sessions.router)
