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

## Update 2026-11-11: verified with a real model
- Model `claude-haiku-5-5`. It thinks by default, and thinking shares `max_tokens`, so the old 500-token limit left no room for the reply. Every model call now sends a JSON schema (`output_config.format`, see `app/schemas.py`), has a token budget that fits thinking plus the answer, and treats `stop_reason` `max_tokens` or `refusal` as an unusable reply.
- Replies use effort `low` (fast, cheap). The scorecard uses `medium`: at `low` the judge sometimes let forbidden promises through.
- An unusable reply is retried once, then the offline fallback answers. The reply, coach note and scorecard carry a `fallback` flag and the page labels them, so a backup answer is never mistaken for coaching.
- One call per reply is kept. Across three scenarios in the browser and repeated evals the customer stayed in character and no coach wording leaked into the customer's lines, so the turn was not split.
