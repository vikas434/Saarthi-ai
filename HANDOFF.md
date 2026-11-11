# Handoff to Claude Code

You are taking over Saarthi, a local prototype. Your job is to make it tested, pushed, signed-in, observable, cost-aware and deployed on Railway. Read `AGENTS.md`, `README.md`, `GLOSSARY.md`, `docs/design.md`, `docs/plan.md` and `docs/adr/` first.

## What exists (commit 17f8878 and this file)
- One FastAPI app (`app/`) serving the API and one static page (`app/static/index.html`). SQLite via `app/store.py`. No sign-in.
- `app/coach.py`: the AI customer, the live coach note (one model call per reply), the scorecard (coach call and customer-survey call in parallel), marker library (rubric, survey, checklist), scenario drafting, progress.
- `app/offline.py`: scripted customer and rule-of-thumb scoring when no model key is set.
- `app/llm.py`: provider seam (`anthropic`, `openai_compatible`), `set_llm_for_tests`.
- `config/`: `markers.json` (SQS, tNPS, ProSat, call checklist), `scenarios.json` (3), `product.md` (sample product "LedgerLeaf").
- `tests/` (9 tests, no key needed), `app/evals.py` (strong vs weak agent on every marker), `Dockerfile`, `docker-compose.yml`, `run.sh`.

## What is NOT verified
- **The real model path has never run.** Only a scripted fake and offline mode were tested. Expect prompt and JSON-shape fixes.
- Browser voice (Web Speech API) was not tested with a real microphone.
- The Docker image was never built.
- The rubric, checklist and product are samples. tNPS (0 to 10, would recommend after this conversation) and ProSat (1 to 5, product satisfaction) scales are confirmed by Vikas.

## Rules
- One step at a time. Each step ends with `pytest`, `ruff check`, `python -m app.evals` passing, then one commit and push.
- Never commit `.env` or keys. Before every push, scan the diff for secrets and personal data. The GitHub repo must be **private**. Ask Vikas before making anything public.
- The agent must never receive a scenario's hidden objections (`public_scenario` only).
- A survey marker is answered by the customer persona in its own call, never by the coach.
- Every marker kind must keep working in offline mode.
- A stack or data-model change needs an ADR in `docs/adr/`.
- Ask Vikas for everything you need from him (keys, Railway and GitHub access, sign-in choice) in one message, up front.
- Show evidence for each step: command output or a screenshot.

## Steps, in order

### 1. Verify the real model path
- Put `ANTHROPIC_API_KEY` in `.env`. Run `./run.sh`, do one full call in Chrome per scenario, end it, read the scorecard.
- Run `.venv/bin/python -m app.evals`. With a key it must pass: strong beats weak on SQS by 15+ points, on tNPS and ProSat, the weak agent misses critical checklist items, and its accuracy score is 2 or lower.
- Fix what breaks: JSON parsing, the customer breaking character, the coach leaking into the customer's line (if so, split the turn into two calls and record it in ADR 0001), survey answers that are too generous.
- Add a retry-once on unparseable model JSON before falling back to offline, and show in the UI when a reply or score came from the fallback.
- Done when: evals pass with a key three runs in a row; screenshots of one real call and scorecard are in `docs/screenshots/`.

### 2. Git and CI
- Create a private GitHub repo `saarthi`, push `main`.
- GitHub Actions on push and PR: `ruff check`, `ruff format --check`, `pytest`, `python -m app.evals` (offline), `docker build`. Add a second eval job that runs with `ANTHROPIC_API_KEY` from repo secrets when it is set.
- Add a Playwright smoke test: load the page, run an offline call to the scorecard, open History and Setup, fail on any console error.
- Done when: CI is green on `main`.

### 3. Storage for deployment
- SQLite on Railway needs a volume; Postgres is safer for more than one instance. Move `app/store.py` to Postgres (keep SQLite for local and tests behind `DATABASE_URL`), with a small migration step. Write the ADR.
- Tests and evals must use their own database, never the app's.
- Done when: the same tests pass on SQLite and on Postgres in CI.

### 4. Sign-in and roles
- Roles: **agent** (own calls only), **manager** (all calls, team view), **admin** (markers, product facts, scenarios, users).
- Verify OIDC JWTs in the API (issuer, audience, JWKS from env) so any identity provider works, including company SSO. For the hosted demo use one provider Vikas picks (Clerk, Auth0 or Google). Invite-only by email.
- Every `/api` route checks the user and role. `sessions` gets a `user_id`; agents can only read their own. Setup routes (`PUT /api/product`, `POST/DELETE /api/markers`, `POST /api/scenarios`) are admin only.
- Add a dev bypass that only works when an explicit env flag is set, for tests.
- Done when: tests cover 401, 403, own-calls-only and admin-only routes.

### 5. Observability
- OpenTelemetry traces: one trace per reply (`turn`: model call, parse, fallback) and per scorecard (`report`: coach call, survey call). Attributes: session id, scenario, model, prompt version, tokens in and out, latency, fallback used. Exporter by env: `none`, `console`, `otlp`.
- Structured JSON logs with a request id. `/health` (alive) and `/ready` (database reachable).
- Never put transcript text or emails in span attributes or logs by default; add an env flag for local debugging.
- Done when: a console-exported trace of one call is pasted in the PR, and `/ready` fails when the database is down.

### 6. Cost
- Record token usage from every model response (the provider returns it) in a `usage` table: session, call kind (turn, report, survey, draft), model, tokens in and out, cost. Prices per model come from config, not code.
- Show cost per call on the scorecard footer for admins, and a cost panel on the dashboard: per day, per agent, per call kind.
- Limits by env: max replies per call (exists, 14), max calls per agent per day, a daily spend cap that switches new calls to a clear "limit reached" message. Rate-limit the API per user.
- Cut cost where it is free: prompt caching for the long system prompt (product facts, rubric) and a cheaper model for the survey call if evals still pass.
- Done when: tests cover the caps, and the dashboard shows real numbers after three calls.

### 7. Deploy to Railway
- One service from the Dockerfile plus Railway Postgres. Listen on `$PORT`. Health check on `/health`. All config by env vars; list them in `.env.example` and the README.
- Set secrets in Railway, never in the repo. HTTPS only. Restrict CORS to the app's own origin. Add basic security headers.
- Deploy `main` automatically after CI passes. Write `docs/deploy.md`: first deploy, rollback, rotating keys, restoring the database.
- Voice needs HTTPS for the microphone; check Speak works on the Railway URL in Chrome.
- Done when: a full call with a real key works on the Railway URL, signed in as an agent, and the manager sees it.

### 8. Product steps from `docs/design.md` (after 1 to 7)
Home by marker; scenarios tagged with target markers; Builder with transcript upload; replay-a-moment drills; manager dashboard; natural voice with interruptions (see the voice loop in `vikas434/idli-ai`); per-marker evals with labelled calls; simulated agents of different skill; flag a bad coach note into the eval set.

## Decisions to ask Vikas (once, at the start)
1. Identity provider for the demo, and the email addresses for admin, manager and agents.
2. Railway account access and the project name; GitHub account for the private repo.
3. Daily spend cap and max calls per agent per day.
4. The real SQS behaviours and weights, checklists and product facts, or permission to demo with the samples.
5. Whether call transcripts may be stored on a hosted service, and for how long. If the product or call data belongs to an employer, get approval before putting it on a personal Railway account.

## Known weak spots
- Customer and coach share one prompt per reply (fast, but may leak).
- Offline survey scores are estimates from behaviours, not a customer's answer.
- No conversation limits per user, no sign-in, no cost tracking yet.
- The page is one file of plain JavaScript; fine for now, move to a framework only when the manager dashboard needs it (ADR first).
