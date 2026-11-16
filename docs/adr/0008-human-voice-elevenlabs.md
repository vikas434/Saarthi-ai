# 0008: Human voice for the customer (ElevenLabs Flash v2.5)

- Status: accepted
- Date: 2026-11-12
- Amends: [0005](0005-hands-free-voice-calls.md) (the customer's voice no longer has to be the browser's)

## Context
The browser's speech synthesis sounds robotic, which breaks the feeling of a real call. The owner chose ElevenLabs' cheapest model on the free plan (about 10,000 credits a month, non-commercial), standard American voices, and the human voice for everyone until the month's budget is used.

## Decision
- The server turns the customer's line into speech with ElevenLabs `eleven_flash_v2_5` (MP3, 22.05 kHz, 32 kbps) at `GET /api/sessions/{sid}/voice/{idx}`. Only the call's owner (or the admin) can ask, and only for that call's own customer lines, so the key can't be used to voice arbitrary text.
- Only the AI customer's words go to ElevenLabs. The agent's words, emails and names never do.
- Voices are ElevenLabs premade American voices listed in `config/voices.json` (5 female, 4 male). A customer's `voice` (female or male, on built-in customers, templates, personas and the builder) picks the pool; the name picks the voice, so a customer always sounds the same. Tense moods get a less steady, more expressive delivery.
- Budget: characters are recorded in `usage` (kind `voice`, priced 0 on the free plan) and capped by `ELEVENLABS_MONTHLY_CHAR_CAP` (default 18,000). If ElevenLabs refuses (bad key, quota, rate limit), the server stops asking until next month. Repeated lines (opening lines) are cached in memory.
- Whenever there is no human voice (no key, cap reached, refusal, network error, playback blocked), the route answers 204 and the page speaks with the browser voice, so a call never stops. `/api/config` says `voice: "elevenlabs" | "browser"`.
- Tutor "Read aloud" stays on the browser voice to keep the monthly budget for calls.
- The CSP allows `media-src 'self' blob:` for playback.

## Consequences
- About 10 to 20 human-voiced calls a month on the free plan; after that, the browser voice. A paid ElevenLabs plan only needs a bigger `ELEVENLABS_MONTHLY_CHAR_CAP` (and a price in `config/pricing.json` so it counts toward the daily spend cap).
- Free-plan audio is for non-commercial use; a paid plan is needed before TalkWise is sold.
- New secret: `ELEVENLABS_API_KEY`, in `.env` and Render only.

## Amendment (2026-11-13): no robotic voice
The owner asked that the customer never speak with a robotic voice. The browser's speech synthesis is no longer used: the customer speaks through the video customer (Anam, ElevenLabs voices; [ADR 0010](0010-video-customer-anam.md)) or the ElevenLabs voice. If neither is available, the reply is shown as text with a short note. Tutor mode's "Read aloud" button, which used the browser voice, was removed.

