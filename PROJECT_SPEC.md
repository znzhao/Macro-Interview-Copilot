# Macro Interview Copilot

> AI-powered interview training for global macro hedge funds, central banks, and international financial institutions.
> Web-hosted on Streamlit Community Cloud, backed by Supabase, powered by user-supplied LLM keys.

**Spec version:** 3.0 · **Status:** Phase 1 shipped; Phase 2 approved for implementation · **Last updated:** 2026-07-30

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

Four capabilities:

1. **Mock interview** — an AI interviewer seeded with real interview questions that asks adaptive follow-ups based on what the candidate actually said.
2. **Structured evaluation** — every answer scored against a five-dimension anchored rubric, with per-dimension history that reveals genuine weaknesses.
3. **Question bank** — a governed repository of macro interview questions across three tiers, extended by an AI authoring agent and curated by admin review.
4. **Knowledge bank** — user-uploaded and AI-drafted macro reference documents under the same three-tier governance, which double as **grounding material the authoring agent reads** when generating questions.

Capabilities 3 and 4 are built first ([Phase 2](docs/IMPLEMENTATION_GUIDE.md#phase-2--content-creation--community)). A thin bank makes a good interviewer worthless, so the content engine precedes the thing that consumes content.

## 1.2 What this is not

- Not a flashcard app or trivia bank.
- Not a general-purpose chatbot wrapper.
- **Not a model-answer library.** The system must never let a candidate substitute a memorized script for reasoning. This is the product's central guardrail — see [AI_SPEC §3.3](docs/AI_SPEC.md#33-what-the-evaluator-must-and-must-not-return).

> **How answer keys coexist with that guardrail.** Questions carry an *answer key*: five labelled sections of at most eight short bullets, mirroring the scoring dimensions. Those limits are the enforcement, not a formatting preference — a bulleted skeleton cannot be recited as an interview answer, so the candidate still has to build the argument. The constraint is imposed by the prompt, the JSON schema, a Pydantic model, and a database CHECK, because a guardrail that lives only in a prompt is a suggestion. See [D10](docs/DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose).

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
   prompts/           app/pages   (UI only)                  Auth (email + password)
   content/  (seed)   core/engine (pure Python)              Postgres + RLS
   migrations/        core/agent  (tool loop, bounded)       questions, knowledge,
                      core/llm    (provider adapters)        sessions, turns, evaluations,
                      core/db     (repositories)             votes, comments, reports,
                            │                                review_requests, notifications
                            └──────► OpenAI / Anthropic / Gemini
                                     using the user's own API key
```

The fifteen decisions behind this shape — and what each one costs — are in [docs/DECISIONS.md](docs/DECISIONS.md). The short version:

- **Streamlit Cloud** means an ephemeral filesystem and a shared ~1GB container, which forces managed Postgres and rules out in-process vector indexes.
- **Supabase** provides auth and per-user isolation via Row Level Security, which is the authorization boundary — not the UI.
- **BYO API key** eliminates unbounded cost on a public app; keys live in session memory and are never persisted.
- **Anchored 0–4 rubric, totals computed in Python** is what makes scores comparable enough to trend over time.
- **Both banks are governed identically** — private → community → verified, with votes, comments, reports, and admin promotion. One model to learn, one RLS pattern to get right.
- **`verified` means an admin vouched for it, not that it is sourced** ([D11](docs/DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance)). Provenance lives entirely in the verification badge, which makes that badge load-bearing rather than decorative.
- **The authoring agent has tools and therefore an attack surface.** It fetches URLs on a stranger's instruction from a public app; the SSRF containment in [AI_SPEC §7.1](docs/AI_SPEC.md#71-url-fetching--ssrf-containment) is a hard requirement. It holds no privilege its operator lacks, and it never writes to the database.

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
| **Answer key** | Five sections of short bullets attached to a question, mirroring the scoring dimensions. Deliberately not prose. See [D10](docs/DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose). |
| **Knowledge bank** | The second governed bank: Markdown reference documents, uploaded or AI-drafted, which also serve as grounding for the authoring agent. See [D12](docs/DECISIONS.md#d12--the-knowledge-base-is-a-three-tier-postgres-bank). |
| **Grounding** | Knowledge documents the user selects to inject into an authoring prompt, capped at 8,000 tokens. |
| **Clone** | The verified copy created when an admin approves a submission. The community original stays with its author. See [D14](docs/DECISIONS.md#d14--promotion-to-verified-clones-the-row). |
| **Review request** | An author asking an admin to promote their content to verified. Irreversible once approved. |

---

# 4. Long-Term Goal

Evolve from an interview preparation tool into a personal macro research and learning assistant supporting interview preparation, macro education, research organization, investment thinking, and continuous learning — without ever compromising the core principle that the system trains reasoning rather than supplying answers.

Speculative directions are tracked as Phase 5 in [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#6-roadmap--acceptance-criteria).
