# Macro Interview Copilot

> AI-powered interview training for global macro hedge funds, central banks, and international financial institutions.
> Web-hosted on Streamlit Community Cloud, backed by Supabase, powered by user-supplied LLM keys.

**Spec version:** 2.0 · **Status:** Approved for implementation · **Last updated:** 2026-07-28

---

## Documentation Map

This file is the entry point. Detailed specifications live in [`docs/`](docs/).

| Document | Covers | Read it when |
|---|---|---|
| [docs/DECISIONS.md](docs/DECISIONS.md) | The nine binding architectural decisions, their rationale and consequences; open questions | You want to change something structural |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram, layer rules, deployment constraints, repository layout, error handling | Starting any work, or debugging a failure mode |
| [docs/DATA_SPEC.md](docs/DATA_SPEC.md) | Postgres schema, enums, constraints, indexes, RLS policies, Pydantic models, repository contracts, migrations, privacy | Touching the database or data access |
| [docs/AI_SPEC.md](docs/AI_SPEC.md) | LLM provider abstraction, prompt architecture, the anchored evaluation rubric, interview state machine, adaptive selection | Touching anything that calls a model or produces a score |
| [docs/CONTENT_SPEC.md](docs/CONTENT_SPEC.md) | Question bank tiers and governance, AI-assisted authoring, moderation, search system, knowledge base | Working on questions, search, or content pipeline |
| [docs/UI_SPEC.md](docs/UI_SPEC.md) | Page-by-page specification, shared components, Streamlit runtime discipline | Building or changing a page |
| [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md) | Local setup, config and secrets, coding standards, testing strategy, CI, phased roadmap with acceptance criteria | Setting up, writing tests, or planning a phase |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Creating the Supabase project, running migrations, seeding, auth configuration, deploying to Streamlit Cloud, secrets handling | Standing up the backend or shipping to production |

---

# 1. Product Definition

## 1.1 What this is

A web application that trains candidates to **think like professional macro investors and economists**, not to memorize answers.

Three capabilities, in order of importance:

1. **Mock interview** — an AI interviewer seeded with real, sourced interview questions that asks adaptive follow-ups based on what the candidate actually said.
2. **Structured evaluation** — every answer scored against a five-dimension anchored rubric, with per-dimension history that reveals genuine weaknesses.
3. **Curated question bank** — a traceable, source-verified repository of macro interview questions, extended by a community tier and by AI-assisted authoring.

## 1.2 What this is not

- Not a flashcard app or trivia bank.
- Not a general-purpose chatbot wrapper.
- Not a model-answer library. **The system must never let a candidate substitute a memorized script for reasoning.** This is the product's central guardrail; see [AI_SPEC §3.3](docs/AI_SPEC.md#33-what-the-evaluator-must-and-must-not-return).

## 1.3 Target roles

Global macro hedge funds (discretionary), central bank economists, IMF / World Bank / BIS / OECD economists, sell-side macro research, fixed income and FX research, sovereign wealth funds.

Reference institutions: Brevan Howard, Rokos, Millennium Macro, Point72 Macro, Citadel Global Fixed Income, Bridgewater, Tudor, Caxton, Balyasny, Capula, BlueCrest, AQR, BlackRock, PIMCO, GS/MS/JPM economics, IMF, World Bank, BIS, OECD, ECB, Federal Reserve, BoE, BoJ, ADB, AIIB.

## 1.4 Training philosophy

| Emphasize | Over |
|---|---|
| Framework | Memorization |
| Reasoning | Recall |
| Evidence and indicators | Opinion |
| Market implication | Textbook definition |
| Concise structure | Exhaustive coverage |

These are not decoration — they are literally the five scoring dimensions in [AI_SPEC §3](docs/AI_SPEC.md#3-evaluation-framework).

---

# 2. Architecture at a Glance

```
   Git ──────────────► Streamlit Community Cloud ──────────► Supabase
   prompts/           app/pages   (UI only)                  Auth (magic link, Google)
   content/           core/engine (pure Python)              Postgres + RLS
   migrations/        core/llm    (provider adapters)        questions, sessions, turns,
                      core/db     (repositories)             evaluations, notes, mastery
                            │
                            └──────► OpenAI / Anthropic / Gemini
                                     using the user's own API key
```

The nine decisions behind this shape — and what each one costs — are in [docs/DECISIONS.md](docs/DECISIONS.md). The short version:

- **Streamlit Cloud** means an ephemeral filesystem and a shared ~1GB container, which forces managed Postgres and rules out in-process vector indexes.
- **Supabase** provides auth and per-user isolation via Row Level Security, which is the authorization boundary — not the UI.
- **BYO API key** eliminates unbounded cost on a public app; keys live in session memory and are never persisted.
- **Anchored 0–4 rubric, totals computed in Python** is what makes scores comparable enough to trend over time.

---

# 3. Glossary

| Term | Meaning |
|---|---|
| **Tier** | Governance level of a question: `verified` / `community` / `private`. See [CONTENT_SPEC §1](docs/CONTENT_SPEC.md#1-the-three-tiers). |
| **Verification level** | Trust level of a question's provenance, independent of tier. See [DATA_SPEC §1](docs/DATA_SPEC.md#1-enums). |
| **Turn** | One question–answer–evaluation unit within a session. |
| **Seed question** | A bank question chosen by the selector, as opposed to an AI-generated follow-up. |
| **Mastery** | EWMA estimate of a user's skill in a `(module, topic)` pair. See [AI_SPEC §5.2](docs/AI_SPEC.md#52-mastery-update-ewma). |
| **Anchor** | The written description defining a specific rubric score. See [AI_SPEC §3.1](docs/AI_SPEC.md#31-the-five-dimensions-and-their-anchors). |
| **BYO key** | Bring Your Own Key — the user supplies their own LLM credentials. |
| **Module / Topic** | Controlled-vocabulary taxonomy for questions. Free-text drift here silently breaks mastery tracking. See [DATA_SPEC §9](docs/DATA_SPEC.md#9-controlled-vocabularies). |

---

# 4. Long-Term Goal

Evolve from an interview preparation tool into a personal macro research and learning assistant supporting interview preparation, macro education, research organization, investment thinking, and continuous learning — without ever compromising the core principle that the system trains reasoning rather than supplying answers.

Speculative directions are tracked as Phase 5 in [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#6-roadmap--acceptance-criteria).
