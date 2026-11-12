"""Who is calling, for every signed-in route: the person, and the admin-only variant."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app import auth, limits
from app.auth import Principal
from app.telemetry import USER_STATE_KEY


def current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Principal:
    user = auth.authenticate(authorization, x_dev_user)
    # For the request's telemetry event: the sign-in id, never the email.
    request.scope.setdefault("state", {})[USER_STATE_KEY] = user.user_id
    limits.check_rate(user.user_id)
    return user


def admin_user(user: Annotated[Principal, Depends(current_user)]) -> Principal:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the admin can change Setup.")
    return user


User = Annotated[Principal, Depends(current_user)]
Admin = Annotated[Principal, Depends(admin_user)]
