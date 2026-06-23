"""Shared FastAPI dependencies: DB session, authentication and role checks."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole
from app.core.security import decode_access_token
from app.models.user import User

# HTTPBearer renders an "Authorize" button in Swagger where you paste a token.
bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the bearer JWT."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise credentials_error

    subject = payload.get("sub")
    if not subject:
        raise credentials_error

    try:
        user_id = uuid.UUID(subject)
    except (ValueError, TypeError):
        raise credentials_error

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive."
        )
    return user


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    """Dependency factory that restricts a route to the given roles."""
    allowed: Iterable[UserRole] = roles

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return _checker
