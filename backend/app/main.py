"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload
Swagger UI is then served at http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.middleware import install_http_middleware
from app.identity.api import identity_router
from app.identity.api.routes.registration import router as registration_router
from app.identity.auth.routes import router as auth_v1_router
from app.identity.credentials.routes import router as credentials_router
from app.identity.credentials.routes import security_router as credentials_security_router
from app.identity.recovery.routes import router as recovery_router
from app.identity.recovery.routes import security_router as recovery_security_router
from app.identity.protection.routes import router as protection_router
from app.authorization.routes import router as authorization_router
from app.identity.errors import register_identity_exception_handlers

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description=(
        "Phase 1 MVP backend that tracks, controls, approves, blocks and "
        "audits actions performed by AI agents."
    ),
)

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Phase 4.2.2.3.5 (§15, §16, §23): request correlation ids + security response
# headers on every response. Registered after CORS so they sit outermost and
# still wrap error responses.
install_http_middleware(app)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Lightweight liveness probe."""
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.API_PREFIX)

# Phase 4: Enterprise Identity Platform — versioned, isolated under /api/v1/identity.
register_identity_exception_handlers(app)
app.include_router(identity_router)

# Phase 4 Part 4.2.2.1: human authentication endpoints under /api/v1/auth.
app.include_router(auth_v1_router)

# Phase 4 Part 4.2.2.3.1: public registration & email verification under /api/v1/auth.
app.include_router(registration_router)

# Phase 4 Part 4.2.2.3.2: credential management (change/reset/validate/policy/expiry)
# and the org-wide password dashboard under /api/v1/security.
app.include_router(credentials_router)
app.include_router(credentials_security_router)

# Phase 4 Part 4.2.2.3.3: password reset, account recovery & email change under
# /api/v1/auth, and the recovery-events dashboard under /api/v1/security.
app.include_router(recovery_router)
app.include_router(recovery_security_router)

# Phase 4 Part 4.2.2.3.4: account protection & risk-based auth admin console under
# /api/v1/security (locks, blocked IPs, protection rules, login attempts, risk events).
app.include_router(protection_router)

# Phase 4.3.1: Enterprise RBAC foundation — roles, permissions, permission groups,
# scoped role assignments, role hierarchy and the authorization audit under /api/v1.
app.include_router(authorization_router)
