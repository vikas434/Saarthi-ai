# 0006: Roleplay builder, private roleplays and personas

- Status: accepted
- Date: 2026-11-12

## Context
MVP step M3 (docs/mvp-plan.md) lets everyone build their own roleplays, like the reference product's builder: describe it or pick a template, then edit description, persona, context, goals, hidden objections and conversation settings. With open sign-up (0004), a person's roleplays must stay private, and hidden objections must still never reach the person practising (rule from the handoff).

## Decision
- A roleplay is still a scenario (same JSON body), extended with `customer.role`, `minutes` and `goals` (up to 6, each with a weight 1 to 5). Built-in roleplays stay in `config/scenarios.json`.
- Migration 0006 adds `scenarios.owner_id`, `scenarios.visibility` (`private` or `published`) and `updated_at`, and a `personas` table (owner, body). Existing saved scenarios were made by the admin for everyone, so they default to `published`.
- Anyone can draft (AI, counted in the daily spend cap), save, edit and delete their own roleplays; they are private. Only the admin publishes or unpublishes. The admin can also edit published ones.
- The full roleplay, with hidden objections, is returned only by `GET /api/roleplays/{id}` to someone allowed to edit it. Everyone else, including people practising a published roleplay, only gets the public card. Starting a call on a roleplay you can't see answers 404.
- A roleplay's goals become an extra rubric marker, "Roleplay goals", scored on that roleplay's calls only. Global markers are unchanged. It works offline like any rubric.
- Templates (`config/templates.json`) and built-in personas (`config/personas.json`) are config, not data. People can save their own personas.
- Caps: `MAX_ROLEPLAYS_PER_USER` and `MAX_PERSONAS_PER_USER` (default 20 each).
- The old admin-only "New customer scenario" box and `POST /api/scenarios` are removed; the Build tab replaces them.
- Shared sign-in dependencies moved to `app/deps.py` so the roleplay routes can live in their own router (`app/roleplay_routes.py`).

## Consequences
- What a builder writes in their roleplay goes into the model prompt for their own calls only, until the admin publishes it. The admin should read a roleplay before publishing it.
- The coach still judges product claims only against the product facts; a roleplay cannot add product facts.
