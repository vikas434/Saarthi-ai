# Saarthi: path to production

Source: `HANDOFF.md` (steps 1 to 8), reordered so a deploy happens early and every later phase ships through staging.

## Decisions (2026-11-11)
| Topic | Decision |
|---|---|
| Repo | `vikas434/Saarthi-ai`, **private**. Commits use the GitHub noreply address; old history rewritten to it. |
| Database | Supabase project `saarthi`, region ap-south-1 (Mumbai). One project, schemas `staging` and `production`, one DB role per schema. SQLite stays for local and tests. |
| Hosting | Railway, personal workspace, Railway subdomain. Environments `staging` and `production`. |
| Deploy flow | Push to `main` → CI green → auto-deploy to staging → smoke test → promote to production. |
| Auth | Clerk, same app as Idli AI. Admin = `TEACHER_EMAIL`, agents = `STUDENT_EMAILS`. Everyone else sees "Your request is received. We will review and approve." Vikas adds Railway URLs in the Clerk dashboard. |
| Model | Anthropic, `claude-haiku-5-5` for customer, coach and survey. Move up only if evals fail. Key lives in `.env` and Railway only. |
| Limits | $2/day spend cap, 20 calls per agent per day, 14 replies per call, per-user API rate limit. |
| Data | Sample product and rubric only. No employer data. Transcripts deleted after 90 days; scores kept. |

## Guardrails on every phase
- Never commit `.env`, keys, emails or personal data. A gitleaks pre-commit hook, a CI gitleaks job and a manual diff scan run before every push.
- Each phase ends with `ruff check`, `ruff format --check`, `pytest`, `python -m app.evals` passing, one or more commits, push, CI green, staging deploy checked (from Phase 4 on).
- Evidence for each phase (command output or screenshot) goes in its PR or commit body.
- Stack or data-model change → ADR in `docs/adr/`.

## Phases

### Phase 0: Bootstrap the repo safely (done 2026-11-11)
- Unpack the prototype here, rewrite author to the noreply address, add `.gitignore` entries (`.env*` except `.env.example`, `data/`, `*.db`).
- Make the GitHub repo private, add gitleaks (pre-commit + CI), push `main`.
- Local Python 3.12 venv via `uv`.
- **Done when:** repo is private, `main` pushed, secret scan clean.

### Phase 1: Verify the real model path (handoff step 1) (done 2026-11-11)
- Key in `.env`, model `claude-haiku-5-5`. One full call per scenario in Chrome, read each scorecard.
- Fix JSON shape, character breaks, coach leaking into the customer (split into two calls + ADR 0001 update if needed), too-generous surveys.
- Retry once on bad JSON, then offline fallback; the UI marks replies and scores that came from the fallback.
- **Done when:** evals pass with a key 3 runs in a row; screenshots in `docs/screenshots/`.
- **Found:** thinking on Haiku 5.5 ate the 500-token reply budget (every reply fell back silently, and the eval still said PASS); fixed with schemas, larger budgets and a fallback-aware eval. Scorecard takes 15 to 18 s; revisit in Phase 7.

### Phase 2: CI (handoff step 2) (done 2026-11-11)
- GitHub Actions: ruff, format check, pytest, offline evals, docker build, gitleaks. Second eval job with the key from repo secrets when set.
- Playwright smoke test: load page, offline call to scorecard, open History and Setup, fail on console errors.
- **Done when:** CI green on `main`.

### Phase 3: Postgres behind `DATABASE_URL` (handoff step 3)
- `app/store.py` works on SQLite and Postgres; numbered SQL migrations run at startup; ADR 0002.
- Tests and evals use their own throwaway database.
- CI runs the suite on SQLite and on a Postgres service container.
- Create Supabase project, schemas, roles. Connection strings go to Railway only.
- **Done when:** same tests pass on both databases in CI.
- **Status:** code and CI done 2026-11-11 (green on SQLite and Postgres 16). Supabase project creation was refused because of an overdue invoice in another Supabase org on the account; host choice pending.

### Phase 4: Sign-in and roles (handoff step 4)
- Clerk token check reused from Idli's `services/api/app/auth.py`; allow-list from env.
- 401 not signed in; 403 with the request-received message for unlisted users, logged once in `access_requests`; admin sees the list in Setup.
- `sessions.user_id`; agents see own calls only; Setup routes admin-only.
- Dev bypass only with an explicit flag, refused when `RAILWAY_ENVIRONMENT` is set.
- **Done when:** tests cover 401, 403 + record, own-calls-only, admin-only; screenshot of the message page.

### Phase 5: First deploy to Railway (from handoff step 7, moved up)
- Railway project, staging and production envs, service from the Dockerfile, listens on `$PORT`, health check `/health`.
- Env vars set in Railway; `.env.example` and README list them all.
- HTTPS only, CORS to own origin, security headers.
- Auto-deploy staging on green `main`; promotion to production after a smoke test.
- Vikas adds both Railway URLs to Clerk.
- **Done when:** a full call with a real key works on staging and production signed in as an agent, the admin sees it, and Speak works in Chrome over HTTPS.

### Phase 6: Observability (handoff step 5)
- OpenTelemetry traces per reply and per scorecard; exporter `none` / `console` / `otlp` by env.
- JSON logs with request id; `/health` and `/ready` (database reachable).
- No transcript text or emails in spans or logs unless a local debug flag is on.
- **Done when:** a console trace of one call is in the PR; `/ready` fails with the database down.

### Phase 7: Cost and limits (handoff step 6)
- `usage` table from every model response; prices in config.
- Cost on the scorecard footer (admin) and a cost panel per day, agent and call kind.
- Spend cap, calls per agent per day, per-user rate limit; prompt caching for the long system prompt; cheaper survey model only if evals still pass.
- 90-day transcript cleanup job.
- **Done when:** tests cover the caps; dashboard shows real numbers after three calls on staging.

### Phase 8: Production hardening
- `docs/deploy.md`: first deploy, rollback (tested once), key rotation, database restore (tested once from a Supabase backup).
- Dependency pinning, Docker image as non-root (already), basic load check of 10 concurrent calls.
- **Done when:** rollback and restore have each been run once and written up.

### Phase 9: Product steps (handoff step 8, after 0 to 8)
Home by marker, tagged scenarios, Builder with transcript upload, replay-a-moment drills, manager dashboard, natural voice (Idli's voice loop), per-marker evals, simulated agents, flag a bad coach note. Each gets its own short plan when we get there.

## What Vikas does
- Phase 5: add the staging and production Railway URLs to the Clerk app's allowed origins and redirect URLs.
- Approve each production promotion until the flow is trusted.
- Later: real rubric and product facts, and employer approval before any real data goes in.
