# Deploying Saarthi (free demo track)

Staging only, on free tiers: Render runs the Docker image, Neon holds Postgres, Clerk signs people in. Decisions: [production plan](production-plan.md), ADRs [0002](adr/0002-postgres-behind-database-url.md) and [0003](adr/0003-clerk-sign-in-and-roles.md).

| Piece | Where | Name |
|---|---|---|
| App | Render, free plan, Singapore | service `saarthi-staging`, https://saarthi-staging.onrender.com |
| Database | Neon, free plan, AWS Singapore | project `saarthi`, branch `staging`, database `saarthi`, role `saarthi_app` |
| Sign-in | Clerk | application `Saarthi`, development instance |
| Model | Anthropic | `claude-haiku-5-5`, capped at $0.50/day |

## How a change reaches staging
Push to `main` → GitHub Actions (`ci`) → when every check passes, Render builds the Dockerfile and deploys (auto-deploy trigger "after CI checks pass"). The new instance runs migrations on start and must answer `/health` before it takes traffic; if it fails, the old one keeps serving.

## Settings on Render (Environment tab)
Secrets, never in the repo: `DATABASE_URL` (Neon pooled URL), `ANTHROPIC_API_KEY`, `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `TEACHER_EMAIL`, `STUDENT_EMAILS`.
Plain settings: `CLERK_AUTHORIZED_PARTIES=https://saarthi-staging.onrender.com`, `FORCE_HTTPS=1`, `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-haiku-5-5`, `LLM_EFFORT=low`, `DAILY_SPEND_CAP_USD=0.50`, `MAX_CALLS_PER_USER_PER_DAY=20`, `RATE_LIMIT_PER_MINUTE=60`. Render sets `PORT` and `RENDER` itself; `RENDER` also switches off the dev sign-in bypass.

## First deploy (already done, for a rebuild from scratch)
1. Neon: create a project in AWS Singapore; copy the **pooled** connection string of the `staging` branch.
2. Render: New → Web Service → this repo, runtime Docker, plan Free, region Singapore, health check path `/health`, auto-deploy "After CI checks pass". Add the settings above.
3. Clerk: create an application; put its keys in Render. Sign-in methods: Google and email code.
4. Open the URL, sign in with `TEACHER_EMAIL`, run one call, check Setup and History.

## Roll back
Render → `saarthi-staging` → Events → pick the last good deploy → **Rollback**. Or revert the commit on `main` and push; CI then redeploys. Migrations only add tables and columns so far, so older code runs on a newer schema.

## Rotate a key
- Anthropic: make a new key in the Anthropic console, put it in Render's `ANTHROPIC_API_KEY` and the repo secret (`gh secret set ANTHROPIC_API_KEY`), then delete the old key.
- Clerk: Clerk dashboard → API keys → roll the secret key; update `CLERK_SECRET_KEY` on Render.
- Neon: Neon console → Roles → `saarthi_app` → reset password; update `DATABASE_URL` on Render.
Each Render change restarts the service with the new value.

## Restore the database
Neon keeps 6 hours of history on the free plan. Neon console → branch `staging` → Restore → pick a time before the problem (it makes a backup branch of the current state first). For anything older, there is no backup on the free plan: export with `pg_dump "$DATABASE_URL" > saarthi.sql` before risky changes.

## Free-tier behaviour to expect
- The app sleeps after 15 minutes without visitors; the first page then takes about a minute. Open it a minute before a demo.
- Neon sleeps after 5 minutes idle and wakes in about a second.
- The in-memory rate limit resets when the app restarts or sleeps.
