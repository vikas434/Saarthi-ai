"""Times every /api request and records its route template, status and signed-in id.

A plain ASGI middleware, so streaming and background work are untouched. The route template
("/api/sessions/{sid}/turns") is recorded, never the concrete path, so ids and text stay out.
The signed-in id comes from scope["state"], set by deps.current_user.
"""

from __future__ import annotations

import time

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import events

API_PREFIX = "/api/"
USER_STATE_KEY = "saarthi_user_id"
UNMATCHED = "(unmatched)"


def route_name(scope: Scope) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None) or UNMATCHED
    return f"{scope.get('method', 'GET')} {template}"


class TelemetryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def send_and_note(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_and_note)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            user_id = (scope.get("state") or {}).get(USER_STATE_KEY)
            await run_in_threadpool(
                events.record,
                "request",
                route_name(scope),
                status=status,
                latency_ms=elapsed_ms,
                user_id=user_id,
            )
