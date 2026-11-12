# Saarthi MVP: open demo and a roleplay-platform experience

Goal: let anyone try Saarthi, and make it feel like a full AI roleplay platform (reference: Yoodli, studied 2026-11-12), without recordings or video. We take the experience and feature shape, not their name, look or content.

## Decisions (2026-11-12)
| Topic | Decision |
|---|---|
| Who can use it | Anyone who signs in with Clerk becomes an **agent** at once. `TEACHER_EMAIL` stays the only admin. The approval wait goes away. |
| Spend | `DAILY_SPEND_CAP_USD=2` (about 300 to 600 calls a day, depending on extras). |
| Per person | `MAX_CALLS_PER_USER_PER_DAY=10`. |
| Building roleplays | Everyone can build roleplays; they are **private** to their builder. Only the admin publishes to everyone. |
| Call mode | **Hands-free voice** by default (Chrome speech, no extra cost); typing is the fallback. |
| Out of scope | Recordings, video, camera, eye contact, pronunciation, avatars on video, sharing links, comments, integrations (Gong, Slack, CRM), multi-persona, memory between calls. |

## What the reference does, and where Saarthi stands
| Area | Reference | Saarthi today | MVP |
|---|---|---|---|
| Library | Cards of ready-made roleplays (type, title, persona name and role, Practice) | Three scenario cards | Cards with persona, difficulty, goals; "Yours" and "Published" sections |
| Builder | Describe in a sentence → AI fills it; or a template. Sections: description, context ("You..." directions, AI refine), persona, rubric goals with weights, up to 15 objections, conversation settings (voice or chat, who opens, ring sound, end time), allow redo | Admin types a description, AI drafts a scenario | Same sections, AI draft plus edit form, templates |
| Personas | Library: name, role, temperament tag (curious, blunt, assertive...) | Persona is inside each scenario | Persona library, reusable across roleplays |
| Call | Voice, AI opens after a phone ring, ends itself near the time limit | Typed or press-to-speak; agent opens | Hands-free voice, AI opens, auto end; live coach notes kept (toggle) |
| Report | Overall %, goals 1 to 5 with reasons, strengths, growth areas, follow-up questions to prepare, summary, transcript with per-line AI suggestions; analytics: filler words, weak words, conciseness, sentence starters, talk time, monologues, questions, pace | Scorecard: SQS, tNPS, ProSat, checklist, quotes, "say instead", went well / work on | Add overall %, follow-up questions, summary, per-line "say it better", delivery analytics |
| Learn first | AI tutor teaches, then quizzes | None | Tutor mode on the product facts before a roleplay |
| Dashboard | Focus analytics (pick up to 4) over time against a target, streak, insights | History with trends per marker | Personal dashboard: focus metrics, streak, insights; admin team view |

Saarthi keeps what the reference lacks: hidden objections, survey markers answered by the customer in character, call checklists with critical items, and live coaching per reply.

## Phases
Each phase ships through staging (checks, evals, commit, push, CI green, auto-deploy) before the next starts.

### M0 Open the door (small) (done 2026-11-12)
- Anyone signed in is an agent; remove the approval gate. Keep `access_requests` as a sign-up log for the admin (who joined, when).
- Limits to $2 a day and 10 calls per person; friendly messages when hit ("Today's free practice is used up, back tomorrow").
- First-visit note: practice calls are stored and visible to the admin; don't enter real customer data.
- Clerk: allow sign-ups (Google and email code), check no allow-list is set.
- ADR 0004: open sign-up alongside the allow-list (`OPEN_SIGNUP=1`).
- Note: nothing deletes old transcripts yet, so the first-visit note does not promise it.

### M1 Hands-free voice call (done 2026-11-12)
- Phone-ring intro, the customer speaks first, then the mic opens automatically after each customer line; silence ends your turn.
- The call ends itself near the roleplay's time limit, or when the customer wraps up.
- Typing stays available; Chrome only for voice (other browsers fall back to chat with a note).
- Records speaking time per reply (for pace and talk-time analytics later).

### M2 Richer report
- Overall score %, summary, strengths and growth areas (exists), **follow-up questions to prepare**.
- **Delivery analytics** computed in code from the transcript and timings: filler words, weak words, repeated sentence starters, conciseness, talk-time ratio, longest monologue, questions asked, pace (words per minute). Works offline.
- **Line-by-line "say it better"** on the transcript, produced in the same scorecard model call (no extra call).
- Report layout: score banner with Practise again, then Coaching and Analytics tabs.

### M3 Roleplay builder and personas
- Data model: roleplays with owner and visibility (private or published), personas table. Migration plus ADR 0005.
- "What's your roleplay about?" box → AI drafts description, context, persona, goals, hidden objections; then an edit form with the reference's sections, and AI refine on context.
- Templates: cold sales call, inbound discovery, upset customer, renewal or upsell, support escalation.
- Persona library: name, role, temperament, background; pick one per roleplay.
- Goals become rubric behaviours with weights for that roleplay; markers stay global.
- Hidden objections never reach the browser for anyone except the roleplay's owner while editing.
- Limits: drafts count toward the daily spend; at most 20 private roleplays per person.

### M4 Tutor mode
- Before a roleplay, an optional short tutor session teaches the product facts in chat or voice, then asks 3 check questions and scores them.
- Counts as a call toward the daily limit.

### M5 Personal dashboard
- Pick up to 4 focus metrics (filler words, pace, talk time, questions, any marker) and see them over time against a target.
- Practice streak and two or three plain insights ("11% of your sentences start with 'I'm'").
- Admin team view: people, calls, average scores, who is improving.

## Cost check
Today a call costs about $0.0034. Line-by-line suggestions add output to the scorecard call (about +$0.001); tutor mode adds about $0.002 when used. At about $0.005 a call, $2 a day covers about 400 calls, so 40 people at the 10-call limit.

## Open questions for later
- Custom domain and Clerk production keys once the demo goes beyond a small circle.
- Deleting old transcripts (90 days) applies to open users too; say so in the first-visit note.
