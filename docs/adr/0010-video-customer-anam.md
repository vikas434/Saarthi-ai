# 0010: A real-time video customer (Anam)

- Status: accepted (trial)
- Date: 2026-11-13

## Context
The owner wants the AI customer to look and sound like a real person during a call. An SVG avatar drawn in the browser was tried and rejected as unreal. Photoreal real-time avatars need a hosted service. The options compared were Anam, HeyGen LiveAvatar, Simli and Tavus. The owner chose Anam and accepts a subscription.

## Decision
- The customer's face comes from an Anam stock avatar streamed over WebRTC, and it speaks with an Anam voice. A customer's `voice` (female or male) and name pick the avatar and voice pair (`config/avatars.json`), so the same customer always looks the same.
- TalkWise still decides every line. Anam's LLM is switched off (`llmId: CUSTOMER_CLIENT_V1`), and the page calls `talk(text)` with the customer's line from our server. No persona, hidden objections or product facts go to Anam: only the name and each line to speak. The agent's microphone is never sent to Anam (`disableInputAudio`). Speech recognition stays in the browser.
- The API key stays on the server. `POST /api/sessions/{sid}/avatar` (owner only, open calls only) returns a one-session token that expires in 2 minutes. The token's session length is the call's time limit plus 1 minute.
- Budget: each token counts the call's planned seconds against `ANAM_MONTHLY_MINUTE_CAP` (default 30, Anam's free plan). Past the cap, without a key, or if Anam refuses, the route answers 204 and the call runs with voice only (ElevenLabs or the browser), as before.
- Mid-call failures fall back too. If the video doesn't start within 15 seconds, a line isn't spoken, or the stream closes, the page continues with voice.
- The SDK (`@anam-ai/js-sdk`, pinned version) loads from esm.sh. The CSP allows esm.sh and Anam's API and signalling hosts only when `ANAM_API_KEY` is set.
- The agent can switch "Video customer" off; the choice is remembered in the browser.

## Consequences
- Cost: Anam's free plan is 30 minutes a month, 1 session at a time, 3-minute conversations, with a watermark and no commercial use. The free plan is for trying it only. Paid plans run from $12 a month (50 minutes) to $299 a month (2,000 minutes, 5 at a time).
- The customer's lines and their audio go to Anam (Anam's zero data retention is Enterprise only). This is fine for the demo. For an enterprise such as Intuit it conflicts with "no data leaves". The options there are an Anam Enterprise contract with zero data retention, or a self-hosted face model (see docs/enterprise-handoff.md).
- Loading third-party code from esm.sh at run time is a supply-chain risk. Vendoring a pinned bundle into `app/static` would remove it.
- Turn-taking stays as it is (pause to send). Streaming replies and barge-in are a later step.
