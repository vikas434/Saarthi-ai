# TalkWise: product design

TalkWise means the charioteer who guides. The product coaches agents on any quality marker through realistic practice. The shape follows Yoodli: a left-nav app, one job per screen, a report after every session.

## The model: markers sit above behaviours
Markers such as tNPS and ProSat are outcomes. An agent can't practise an outcome; they practise the behaviours that drive it.

| Layer | Example | In the product |
|---|---|---|
| Marker | SQS, tNPS, ProSat, compliance checklist | Marker library; three kinds (rubric, survey, checklist) |
| Driver | tNPS: empathy, listening, objection handling, clear next step | Each survey marker lists its driver behaviours |
| Evidence | The agent's own words | Quotes on the scorecard |

The customer answers the survey. After each call the AI customer, still in character, answers each survey marker with a score and a reason. The scorecard puts that answer next to the coach's scores for the driver behaviours.

## Screens
| Screen | Yoodli equivalent | What it does | Status |
|---|---|---|---|
| Home | Home | Greeting, your markers with trend, weakest behaviour, one Start button, assigned drills | Next |
| Roleplays | Roleplays | Customer scenarios, filtered by marker, product and difficulty | Built (list) |
| Builder | Builder | One sentence becomes a scenario; upload product facts and real transcripts to create scenarios | Partly built |
| Call | Practice | Customer on one side, live coach notes on the other; voice or text; whisper hints when stuck | Built (browser voice) |
| Scorecard | Report | Marker tiles, customer's survey answers, behaviours with quotes and "say instead", checklist results | Built |
| Replay a moment | Practice again | Retry one weak reply from a past call | Next |
| Recordings | My Recordings | Past calls with transcript and coach notes | Built (History) |
| Learning | My Learning | A drill path per marker, e.g. "Raise tNPS: 5 calls on ownership and effort" | Later |
| Team dashboard | Dashboard | Markers by agent, weakest behaviours, assign scenarios, compare practice with real scores | Later |
| Admin | Org settings | Marker library, weights, product facts, models, sign-in | Partly built (Setup) |

## Marker library
- **Rubric:** behaviours with a description and weight. Coach scores 1 to 5, or leaves it unscored when the call gave no chance.
- **Survey:** question, scale, driver behaviours. Answered by the customer.
- **Checklist:** items, each optionally critical. Yes, no or not applicable.
- Any marker can be added from Setup or `config/markers.json` and is scored from the next call. This is how a team's own quality checklist goes in.

## Rules
- The agent never sees a scenario's hidden concerns.
- Product claims are judged only against the product facts.
- A survey answer comes from the customer persona, never from the coach.
- Scores show their evidence. No score without a quote or a reason.

## Build order
1. Marker library, customer survey, scorecard by marker. Done.
2. Home by marker; scenarios tagged with target markers.
3. Builder with transcript upload.
4. Replay-a-moment drills and Learning paths.
5. Sign-in, teams, manager dashboard.
6. Natural voice with interruptions (reuse Idli AI's voice loop).
7. Evals per marker with labelled calls; compare predicted tNPS with real survey results.
