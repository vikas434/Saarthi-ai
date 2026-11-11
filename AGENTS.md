# Rules for coding agents

Read README.md, GLOSSARY.md, docs/design.md and docs/plan.md first.

- One small step at a time; each ends with `pytest` and `python -m app.evals` passing and one commit.
- The sales agent must never see a scenario's hidden objections (`public_scenario` is the only shape sent to the browser).
- The coach judges product claims only against the product facts. Don't add product knowledge to prompts.
- Secrets come from env vars. Never commit `.env`.
- Keep it one FastAPI app with one static page until a decision in docs/adr says otherwise.
- A survey marker is answered by the customer persona in its own model call, never by the coach.
- New marker kinds go through `load_markers` and `build_report`; every kind must work offline too.
