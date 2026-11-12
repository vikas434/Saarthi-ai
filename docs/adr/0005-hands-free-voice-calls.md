# 0005: Hands-free voice calls

- Status: accepted
- Date: 2026-11-12

## Context
The MVP (docs/mvp-plan.md, M1) makes a practice call feel like a phone call: the phone rings, the customer speaks first, and the agent just talks. Later analytics (pace, talk time) need to know how long the agent spoke. Open sign-up (0004) also means a single call should not run up cost without end.

## Decision
- Voice stays in the browser: Web Audio for the ring, `speechSynthesis` for the customer, Chrome's `SpeechRecognition` for the agent. No new service, key or cost. Browsers without speech recognition fall back to typing, with a note.
- The voice code lives in `app/static/voice.js`, served at `/voice.js` next to the single page. It is still one page (0001); the split only keeps `index.html` small.
- Hands-free is on by default where the browser can listen, and remembered per browser. A pause of about 1.6 s ends the agent's turn; typing or pressing ■ Done takes over at any time.
- Each roleplay has a time limit, `minutes` in the scenario (default 6). When it runs out, the current exchange finishes and the call is scored. When the customer ends the call in hands-free mode, it is scored straight away.
- Data model: `turns.agent_seconds` (migration 0005), the seconds the agent spoke for a spoken reply; NULL for typed replies. The turn API takes an optional `seconds` (0 to 600).
- Cost guard: at most `MAX_REPLIES_PER_CALL` (default 14) agent replies per call; after that the turn API answers 409 and the call must be scored.

## Consequences
- Speech recognition quality depends on Chrome and the microphone; Chrome sends audio to its own speech service. People who don't want that can turn hands-free off and type.
- Speaking time is measured from the first to the last recognised word, so it is approximate; good enough for pace in words per minute.
