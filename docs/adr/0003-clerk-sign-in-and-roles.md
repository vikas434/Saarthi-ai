# 0003: Clerk sign-in, an env allow-list, and two roles

- Status: accepted
- Date: 2026-11-12

## Context
Saarthi is going on a public URL with a paid model key behind it. Only two people should get in for now (the same two as Idli AI), and nobody else should be able to start calls or see transcripts.

## Decision
- Sign-in is Clerk, the same Clerk application as Idli AI (its live development instance). The page loads Clerk's own script from the instance's Frontend API and sends the session token as `Authorization: Bearer` on every call.
- The server verifies the token itself (`app/auth.py`): RS256 against Clerk's JWKS (fetched with the secret key, cached for an hour), expiry with 30 s clock skew, and `azp` against `CLERK_AUTHORIZED_PARTIES` when set. The email comes from the token or Clerk's user API (cached ten minutes).
- Access is an env allow-list, not a database table: `TEACHER_EMAIL` is the **admin** (every call, Setup, access requests); `STUDENT_EMAILS` are **agents** (own calls only). Changing who gets in means changing env and restarting. No email is hardcoded anywhere in the repo.
- Anyone else who signs in gets 403 with exactly "Your request is received. We will review and approve." on every `/api` route; the page shows only that sentence. Each such email is kept once in `access_requests` (first seen, last seen, attempts counted at most once a minute) and listed for the admin in Setup.
- `sessions.user_id` (migration 0003) owns each call. An agent asking for someone else's call gets 404, not 403, so ids reveal nothing.
- `AUTH_DEV_BYPASS=1` lets tests and local runs send `X-Dev-User: <email>` instead of a token. It is off by default and ignored when `RAILWAY_ENVIRONMENT` or `RENDER` is set. It skips the token check only; the allow-list still decides the role.
- With no Clerk keys and no bypass, every `/api` route answers 503 "Sign-in is not configured": the server fails closed.

## Consequences
- New dependency: `pyjwt[crypto]`.
- The sign-in box says "Idli AI" and shows Clerk's "Development mode" badge, because the Clerk app and instance are shared. A separate Clerk application, or production keys on a custom domain, removes both.
- Idli's root `.env` holds a stale publishable key for a deleted instance; Saarthi uses the live one that Idli's web apps use.
