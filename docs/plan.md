# Plan

## Goal
Coach agents on any quality marker (SQS, tNPS, ProSat, checklists) through realistic practice: the AI plays the customer, coaches during the call, and scores it afterwards.

## Built (2026-11-11)
- Scenarios with hidden objections; three samples; draft a new one from a sentence.
- Call by text or voice (browser speech recognition and speech synthesis; no keys).
- One model call per reply returns the customer's line and a coach note.
- Scorecard: each SQS behaviour 1 to 5 with a quote, good / improve / say instead, weighted SQS.
- Product-claim checking against editable product facts.
- History, SQS trend and per-behaviour averages.
- Offline mode, 8 tests, a strong-versus-weak eval, Dockerfile and compose.

## Added (2026-11-11, step 1 of docs/design.md)
- Marker library with three kinds: rubric, survey, checklist. Add markers in Setup.
- tNPS and ProSat answered by the customer in character, shown with their driver behaviours.
- Scorecard, history and the eval are per marker.

## Not yet verified
- The model path has only been tested with a scripted fake. Run one call and `python -m app.evals` with a real key before a demo.

## Next
1. Replace the sample rubric and product facts with the real SQS and product.
2. Sign-in and teams: agents see their own calls; a manager sees everyone's.
3. Manager view: weakest behaviour per agent, assigned drills.
4. Voice quality: streaming speech-to-text and a natural voice (Deepgram and ElevenLabs, as in Idli AI).
5. Evals per behaviour with labelled transcripts; simulated agents of different skill.
6. Drill mode: replay one moment of a past call and try a better line.
7. Hosting decision and deploy.
