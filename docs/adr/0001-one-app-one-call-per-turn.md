# 0001: One FastAPI app, one static page, one model call per reply

- Status: accepted
- Date: 2026-11-11

## Context
A working local prototype was needed in one evening, runnable with one command and deployable as one container.

## Decision
- One FastAPI service serves the API and a single HTML page. SQLite for storage. No sign-in yet.
- Each agent reply makes one model call that returns both the customer's line and the coach note, so the reply stays fast.
- The scorecard is a second call at the end, over the whole transcript.
- Voice uses the browser's own speech recognition and synthesis.
- Without a key the app falls back to a scripted customer and simple scoring.

## Alternatives
Reusing Idli AI's stack (Next.js apps, Postgres, Clerk, Deepgram, ElevenLabs): more capable, but too much setup for a first prototype. Its ideas are reused: provider seam, grounded checks against owned facts, evals.

## Consequences
The customer and coach share a prompt, so a coach note can leak tone into the customer. Split into two calls if that shows up. SQLite and no sign-in must change before more than one team uses it.
