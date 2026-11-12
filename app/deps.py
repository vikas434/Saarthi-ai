"""Who is calling, for every signed-in route: the person, and the admin-only variant."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app import auth, limits
from app.auth import Principal


def current_user(
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Principal:
    user = auth.authenticate(authorization, x_dev_user)
    limits.check_rate(user.user_id)
    return user


def admin_user(user: Annotated[Principal, Depends(current_user)]) -> Principal:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the admin can change Setup.")
    return user


User = Annotated[Principal, Depends(current_user)]
Admin = Annotated[Principal, Depends(admin_user)]
