# Saarthi

Practise customer calls with an AI customer. A coach comments on every reply, and when the call ends the customer answers a survey in character. The scorecard covers every quality marker the team cares about: SQS, tNPS, ProSat, call checklists, and any marker you add.

**Status:** staging demo at **https://saarthi-staging.onrender.com** (sign-in required; free hosting sleeps after 15 idle minutes, so the first load can take a minute). Demo script: [docs/demo.md](docs/demo.md).

![A practice call with live coach notes](docs/screenshots/real-call.jpg)

## What it does

1. **Pick a customer.** Each scenario has a short brief for the agent; the customer's real concerns stay hidden. Press **Learn first** for a short lesson on the product facts this call needs and three check questions (it counts as one of the day's calls).
   **Or build your own** in the Build tab: describe the call and the AI drafts it, or start from a template (cold call, inbound discovery, upset customer, renewal, support escalation). Edit the persona, context, goals (scored on the scorecard), hidden objections and time limit. Your roleplays are private; the admin can publish one to everyone.
2. **Talk.** Hands-free by default in Chrome: the phone rings, the customer speaks first, and Saarthi listens after each line; pause to send. Typing always works. Each call has a time limit (6 minutes unless the roleplay sets one) and ends itself when time runs out.
3. **Get coached live.** After each reply the coach names one behaviour (good, mixed or improve), quotes you, and suggests a better line. Product claims are checked against the product facts.
4. **End the call.** The coach scores every behaviour and checklist item while the customer answers the survey, in parallel. The scorecard opens with one overall score, then two tabs: **Coaching** (summary, next drill, every marker, questions to prepare for, and the transcript with a better line under each reply that needed one) and **Analytics** (filler and weak words, sentence starters, reply length, talk time, longest reply, questions asked, and pace for spoken replies; worked out in code, no model cost).
5. **Track progress.** The Dashboard shows your practice streak, calls this week, two or three plain insights, and up to four focus metrics you choose (overall score, filler words, pace, talk time, questions, any marker) over time against a target. The admin also sees a team table: each person's calls, average, and first-to-latest score. Every call is listed below.

![Scorecard by marker](docs/screenshots/real-scorecard.jpg)

## Who can use it

Sign-in is [Clerk](https://clerk.com), on Clerk's hosted sign-in page (Google or an emailed code). Roles come from server settings, never from code. On staging, sign-up is open: anyone who signs in practises as an agent ([ADR 0004](docs/adr/0004-open-sign-up.md)).

| Role | Who | Can |
|---|---|---|
| Admin | `TEACHER_EMAIL` | Every call, Setup (product facts, markers, scenarios), access requests, cost per call |
| Agent | `STUDENT_EMAILS` (comma-separated) | Own calls only |
| Anyone else, with `OPEN_SIGNUP=1` | | Same as an agent; listed for the admin as "People who joined" |
| Anyone else, sign-up closed | | Sees only "Your request is received. We will review and approve." and is listed for the admin |

With sign-up closed, let someone in by adding their email to `STUDENT_EMAILS` and restarting. Details: [ADR 0003](docs/adr/0003-clerk-sign-in-and-roles.md).

## Markers

A marker is anything you want agents coached on. Every call is scored on all of them.

| Kind | Who scores it | Example |
|---|---|---|
| Rubric | The coach scores each behaviour 1 to 5 with a quote; weights give a percentage | SQS |
| Survey | The customer answers in character, with a reason; the scorecard shows the behaviours that drive it | tNPS (0 to 10), ProSat (1 to 5) |
| Checklist | The coach marks each item yes, no or not applicable; a missed critical item is called out | Call checklist |

Add markers in Setup or in `config/markers.json`: a checklist is one item per line (`!` marks it critical), rubric behaviours are `Name - what good looks like`, a survey is a question and a scale.

## Run it locally

Needs Python 3.11+ and Chrome.

```bash
./run.sh
```

The first run creates `.venv` and copies `.env.example` to `.env`. Then edit `.env`:

- **Sign-in without Clerk:** `AUTH_DEV_BYPASS=1` and `TEACHER_EMAIL=` your email; type that email on the sign-in screen. The bypass is refused on any hosted server.
- **Real coaching:** `ANTHROPIC_API_KEY=`. Without a key Saarthi runs offline: a scripted customer and rule-of-thumb scores, enough to show the flow.

Open http://localhost:8100. Data goes to `data/saarthi.db` (SQLite) unless `DATABASE_URL` points at Postgres.

With Docker instead: `docker compose up --build`.

## Settings

All configuration is environment variables; `.env.example` lists every one.

| Variable | What it does |
|---|---|
| `ANTHROPIC_API_KEY`, `LLM_MODEL`, `LLM_EFFORT` | Model for customer, coach and survey (default `claude-haiku-5-5`, effort `low`; the scorecard always uses `medium`) |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL` | `openai_compatible` for a company gateway |
| `DATABASE_URL` | Postgres URL; empty means SQLite at `SAARTHI_DB` |
| `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_AUTHORIZED_PARTIES` | Clerk application keys and the site origin allowed to use them |
| `TEACHER_EMAIL`, `STUDENT_EMAILS` | The admin and the allow-listed agents |
| `OPEN_SIGNUP` | `1` lets anyone who signs in practise as an agent |
| `AUTH_DEV_BYPASS` | Local sign-in by typing an allow-listed email |
| `DAILY_SPEND_CAP_USD`, `MAX_CALLS_PER_USER_PER_DAY`, `RATE_LIMIT_PER_MINUTE` | Cost guards (staging: $2, 10, 60) |
| `MAX_REPLIES_PER_CALL` | Agent replies per call before it must be scored (default 14) |
| `MAX_ROLEPLAYS_PER_USER`, `MAX_PERSONAS_PER_USER` | Saved roleplays and personas per person (default 20 each) |
| `FORCE_HTTPS`, `PORT` | Hosting: HTTPS redirect and HSTS behind a proxy; the port to listen on |
| `CLERK_JS_VERSION`, `CLERK_UI_VERSION` | Majors of Clerk's browser script (6) and sign-in screens (1) |

## Cost and limits

Every model call's tokens and cost go into the `usage` table, priced from `config/pricing.json`. A practice call on Haiku 5.5 costs about $0.0034. When today's spend reaches `DAILY_SPEND_CAP_USD`, or a person reaches `MAX_CALLS_PER_USER_PER_DAY`, new calls stop with a clear message; calls in progress finish. Each person sees how many calls they have left today. The admin sees each call's cost on its scorecard. If a model reply can't be used, Saarthi retries once, then falls back to the scripted customer and labels it "backup".

## How it is built

One FastAPI app serves the API and a single static page ([ADR 0001](docs/adr/0001-one-app-one-call-per-turn.md)); voice is in the browser ([ADR 0005](docs/adr/0005-hands-free-voice-calls.md)).

```
app/
  main.py          routes; /api needs sign-in (except /api/auth/config)
  deps.py          who is calling: signed-in person, admin only
  roleplays.py, roleplay_routes.py  roleplay builder, templates, personas, publishing
  tutor.py, tutor_routes.py         tutor mode: lesson from the product facts, three graded questions
  dashboard.py, dashboard_routes.py focus metrics over time, streak, insights, team view
  auth.py          Clerk token check, allow-list, roles
  coach.py         customer, live coach, scorecard, survey, scenario drafting
  schemas.py       JSON schemas the model must answer in
  llm.py           model providers (Anthropic, OpenAI-compatible)
  offline.py       scripted customer and rule-of-thumb scoring
  delivery.py      call analytics from the transcript: filler words, talk time, pace
  store.py, db.py  storage on SQLite or Postgres; Alembic migrations in migrations/
  usage.py         tokens and cost per model call
  limits.py        spend cap, calls per day, rate limit
  web_security.py  security headers, HTTPS redirect
  static/index.html  the whole front end
  static/voice.js    ring, customer voice, hands-free listening (browser speech, no keys)
  static/report.js   the scorecard: banner, Coaching and Analytics tabs
  static/builder.js  the Build tab: describe or template, edit, save, publish
  static/tutor.js    Learn first: lesson, questions, result
  static/dashboard.js  the Dashboard tab: stats, insights, focus charts, team table
config/            markers, scenarios, roleplay templates, personas, sample product facts, model prices
evals/             strong and weak agent scripts for python -m app.evals
tests/, e2e/       unit tests and the browser smoke test
```

Storage is Postgres in deployment and SQLite locally, behind `DATABASE_URL` ([ADR 0002](docs/adr/0002-postgres-behind-database-url.md)). The schema migrates on start; by hand: `python -m app.db upgrade`.

## Check it

```bash
.venv/bin/pytest -q
```

```bash
.venv/bin/python -m app.evals
```

```bash
.venv/bin/pytest e2e -q
```

Unit tests need no key. The eval plays a strong and a weak agent through the real path; the strong one must win on every marker, and with a key any backup reply or score fails it. The browser test needs `pip install -e ".[e2e]"` and `playwright install chromium` once.

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs lint, format, unit tests and offline evals on SQLite and on Postgres, the browser test, a Docker build and a secret scan on every push. The real-model eval runs only when started by hand (Actions → ci → Run workflow).

## Deploy

Push to `main`; once CI passes, Render deploys automatically. Staging runs free: Render (app), Neon (Postgres), Clerk (sign-in). First deploy, rollback, key rotation and database restore: [docs/deploy.md](docs/deploy.md).

## Secrets and personal data

Keys and emails live only in `.env` (git-ignored) and in the host's settings. A pre-commit hook runs [gitleaks](https://github.com/gitleaks/gitleaks) with `.gitleaks.toml`, which also blocks email addresses, and CI scans the full history. `run.sh` turns the hook on (needs `brew install gitleaks`).

## More

- [docs/design.md](docs/design.md): product design and screens
- [docs/production-plan.md](docs/production-plan.md): what is done and what waits for paid hosting
- [docs/mvp-plan.md](docs/mvp-plan.md): the open demo and the roleplay-platform MVP (M0 to M5)
- [GLOSSARY.md](GLOSSARY.md): terms
- [AGENTS.md](AGENTS.md): rules for coding agents
