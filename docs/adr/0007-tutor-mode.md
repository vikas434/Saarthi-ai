# 0007: Tutor mode

- Status: accepted
- Date: 2026-11-12

## Context
MVP step M4 (docs/mvp-plan.md): before a roleplay, an optional tutor teaches the product facts that matter for that call and checks understanding with three questions, like the reference product's AI tutor. It uses the model, so it must count toward the daily limits.

## Decision
- A tutor session is a row in `sessions` with `kind = 'tutor'` (migration 0007; existing rows are `roleplay`). Because it is a session, it counts as one practice call in `MAX_CALLS_PER_USER_PER_DAY`, and its model calls are recorded against it in `usage`.
- The lesson and the answer keys live in the new `sessions.plan` column, which `store.get_session` never returns. The browser gets the questions only; an answer's model answer is shown after that question is answered.
- The tutor teaches only from the product facts and the roleplay's public brief. It never sees the hidden objections.
- Each answer is graded on its own (one model call) for immediate feedback; finishing saves a report `{type: "tutor", score, total, ready, answers}`. Two of three right is "ready".
- Offline (no key): the lesson is the product facts as written (bullets under headings, or sentences for plain text), the questions come from the facts most related to the roleplay, and grading checks that an answer contains at least half of the key words of the fact.
- Tutor sessions are excluded from roleplay progress and refuse the call endpoints (turns, end). History lists them as "Learn: <roleplay>" with the quiz score.

## Consequences
- About four small model calls per tutor session (lesson plus three grades), under a cent on Haiku.
- Offline grading by key words is rough; it is for demos without a key, not for judging real people.
