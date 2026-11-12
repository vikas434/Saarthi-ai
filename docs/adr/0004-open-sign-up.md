# 0004: Open sign-up for the demo

- Status: accepted
- Date: 2026-11-12
- Amends: [0003](0003-clerk-sign-in-and-roles.md) (the allow-list is no longer the only way in)

## Context
Stakeholders liked the demo and want other people to try it. Under 0003, everyone outside `TEACHER_EMAIL` and `STUDENT_EMAILS` waits for approval, which means editing env and restarting for each person. The model key is the only real cost, and the daily spend cap already bounds it.

## Decision
- `OPEN_SIGNUP=1` lets anyone who signs in with Clerk practise as an **agent**. Off by default, so local runs and tests keep the 0003 behaviour unless they turn it on.
- Admin stays env-only (`TEACHER_EMAIL`). Open sign-up never grants admin, Setup or other people's calls.
- Newcomers are still written to `access_requests`, at most once every ten minutes per email per process. The admin sees them in Setup as "People who joined". No new table or migration.
- Staging limits: `DAILY_SPEND_CAP_USD=2` for everyone together and `MAX_CALLS_PER_USER_PER_DAY=10` per person. `/api/config` tells each person how many calls they have left today, and the limit messages say when practice opens again.
- On first visit the page says calls are saved and visible to the admin, and asks people not to use real customer names or details.

## Consequences
- Someone can make several Clerk accounts to get more calls per day. The daily spend cap still bounds the total cost, so we accept this for a demo.
- When the spend cap is reached, nobody can start a call until 00:00 UTC. If that happens often, raise the cap or lower the per-person limit.
- Turning sign-up off again is one env change (`OPEN_SIGNUP=` empty) and a restart; everyone not on the allow-list then sees the 0003 "request received" message again.
