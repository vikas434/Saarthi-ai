"""The admin's Insights: adoption, feature use, outcomes, cost, service health and alerts."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from app import alerts, insights
from app.deps import Admin

router = APIRouter(prefix="/api/admin")


@router.get("/insights")
def admin_insights(admin: Admin, days: int = Query(default=7)) -> dict:
    if days not in insights.WINDOWS:
        raise HTTPException(status_code=422, detail="days must be 7 or 30")
    now = datetime.now(UTC)
    # The admin's own clicks and test calls would inflate adoption.
    business = insights.business(days, now, exclude=frozenset({admin.user_id}))
    engineering = insights.engineering(days, now)
    firing = alerts.evaluate(
        spend=engineering["spend"],
        voice_budget=engineering["voice_budget"],
        day=insights.last_24h(now),
        last_call_at=business["last_call_at"],
        now=now,
    )
    return {
        "days": days,
        "generated_at": now.isoformat(timespec="seconds"),
        "alerts": firing,
        "business": business,
        "engineering": engineering,
    }
