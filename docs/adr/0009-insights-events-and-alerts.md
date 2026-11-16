# 0009: Insights for the admin: an events table, metrics and alerts

- Status: accepted
- Date: 2026-11-12

## Context
The owner wants to decide what to build next from evidence: are people trying TalkWise and coming back, which features they use, where they drop off, whether scores improve, what each active person costs, and whether the service is healthy. Calls, replies, scores and model spend are already stored. Request timings, errors and fallbacks (the offline coach after a model error, the browser voice after ElevenLabs fails) were only written to the host's logs, which are short-lived.

## Decision
- A new `events` table (migration 0008) with two kinds:
  - `request`: one row per `/api/*` request with the route template (`POST /api/sessions/{sid}/turns`, never the concrete path), status, time taken and the sign-in id. Recorded by a plain ASGI middleware (`app/telemetry.py`).
  - `fallback`: one row when a model or voice call answered with its backup (`coach.turn`, `coach.report`, `coach.survey`, `tutor.lesson`, `tutor.grade`, `builder.draft`, `voice.elevenlabs`), with the exception class or HTTP status as the reason.
- No call text, prompts or emails go into events. The sign-in id is already stored on sessions and usage.
- Events are kept 30 days; old rows are pruned on write at most once an hour. Recording never breaks a request.
- An admin-only `GET /api/admin/insights` computes business and engineering numbers and alerts from `sessions`, `turns`, `usage` and `events`. The thresholds are in `config/alerts.json`.
- Alerts show on the admin's Insights tab. If `SLACK_WEBHOOK_URL` is set, a newly firing alert is posted to Slack at most once a day per alert. Alerts are checked when the Insights page loads and on API requests (at most every few minutes), because the free host has no scheduled jobs.

## Consequences
- One extra small insert per API request. At demo traffic (hundreds of requests a day) this is well within the free Postgres plan; 30-day retention bounds the table.
- Latency is measured inside the app, so it excludes network time and the host's cold starts.
- Alerts can be late when nobody uses the app, which is also when they matter least. A real scheduler or an uptime monitor is needed before customers depend on TalkWise.
- `SLACK_WEBHOOK_URL` is a secret: in `.env` and Render only.
