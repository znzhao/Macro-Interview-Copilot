# Phase Tracker

Tracks implementation progress against [docs/IMPLEMENTATION_GUIDE.md §6](docs/IMPLEMENTATION_GUIDE.md#6-roadmap--acceptance-criteria). Update this file as steps complete — it is the single place to check "what state is the build in."

**Current phase: Phase 1 — Foundation** (code complete, pending live Supabase verification — see Caveats)

---

## Phase 1 — Foundation

Acceptance: a new user signs up, browses and filters the bank, favorites and annotates questions, logs out, logs back in on another device, and sees their data. RLS integration tests pass. No AI features exist yet.

Build order per [IMPLEMENTATION_GUIDE §7](docs/IMPLEMENTATION_GUIDE.md#7-build-order-within-phase-1):

- [x] Repo scaffold: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.gitignore`, `.streamlit/config.toml`, `.streamlit/secrets.toml.example`
- [x] `core/models/enums.py` — controlled vocabularies (modules, topics, difficulty, tiers, etc.)
- [x] `core/models/*` — Pydantic models with validators (`question.py`, `session.py`, `evaluation.py`, `profile.py`, `common.py`)
- [x] Unit tests for models — 13 tests, passing
- [x] `core/db/migrations/0001_init.sql` — schema, enums, tables, indexes, triggers
- [x] `core/db/migrations/0002_rls.sql` — RLS policies for every table
- [x] `core/config.py` — validated Settings from `st.secrets`
- [x] `core/db/client.py` — cached Supabase client factory (anon key only)
- [x] `core/auth.py` — Supabase Auth wrapper (magic link + Google OAuth, PKCE code exchange)
- [x] `core/db/repositories/*` — questions, profiles, notes, favorites (Phase 1 scope only)
- [x] Integration tests for repositories, including RLS isolation tests (12 tests, run against real Postgres — see Caveats)
- [x] `scripts/apply_migrations.py`
- [x] `scripts/seed_db.py`
- [x] `scripts/export_questions.py` (bonus — keeps the Git snapshot in sync per D5)
- [x] `scripts/validate_content.py`
- [x] Initial seed content — **40 questions**, not the ≥100 target (see Caveats)
- [x] `streamlit_app.py` — auth gate + navigation
- [x] `app/state.py` — typed session state
- [x] Settings page (`7_Settings.py`) — profile live; LLM key UI functional (session-state) ahead of Phase 2 provider wiring
- [x] Question Bank page (`2_Question_Bank.py`) — search, filters, favorites, notes, pagination
- [x] Dashboard page (`1_Dashboard.py`) — shell + onboarding empty state
- [x] Admin page placeholder (`9_Admin.py`) — nav target only, full build is Phase 3
- [x] CI workflow (`.github/workflows/ci.yml`) — ruff, mypy --strict, import-linter, unit + integration tests, content validation

**Verified locally:** `ruff check`, `mypy --strict` (0 errors across `core/`, `app/`, `streamlit_app.py`, `scripts/`), `import-linter` (all 5 layer contracts kept), all 13 unit tests pass, `validate_content.py` passes on the seed bank.

### Caveats — read before treating Phase 1 as done

1. **Seed bank is 40 questions, not ≥100.** All 40 use `verification_level: synthesized_from_official_topics` with real, stable institutional source URLs (IMF, Fed, ECB, BIS, OECD, World Bank, BoJ landing pages) rather than claimed real interview reports — fabricating "verified interview" provenance with invented Glassdoor/candidate-report URLs would violate the anti-fabrication principle in [CONTENT_SPEC §6.1](docs/CONTENT_SPEC.md#61-anti-fabrication-rules). Growing this to ≥100 with genuinely verified interview questions is a content task, not a code task — it needs a human sourcing real reports.
2. **No live Supabase project exists yet.** Nothing has been run end-to-end against real Postgres/Auth. **Follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — it covers project creation, migrations, seeding, auth URL configuration, secrets handling, and the Streamlit Cloud deploy.
3. **RLS integration tests are written but unverified on this machine** — no Docker available here. They're designed to run against a real Postgres (see `tests/integration/conftest.py`) and are wired into CI, but that's the first time they'll actually execute. Run `pytest tests/integration -m integration` locally with a Postgres container before trusting them.
4. **The PKCE auth code exchange (`core/auth.py:complete_session_from_code`) is implemented against the supabase-py API surface but not exercised against a real auth flow.** One `type: ignore` there flags a TypedDict mismatch worth re-checking once real sign-in is tested.
5. **`app/pages/2_Question_Bank.py`'s "Favorites only" filter is client-side** on the current page of results, not a database-level filter — fine at this scale, worth revisiting if the bank grows large.

---

## Phase 2 — Interview & Evaluation

Not started. See [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#phase-2--interview--evaluation).

- [ ] BYO-key flow with validation (`api_key_gate.py`)
- [ ] `core/llm/*` provider adapters (OpenAI, Anthropic, Gemini) + structured output
- [ ] `prompts/evaluator.v1.md` + `core/engine/evaluator.py`
- [ ] `core/engine/session.py` — interview state machine
- [ ] `prompts/interviewer.v1.md` + `core/engine/interviewer.py`
- [ ] Interview page (`3_Interview.py`)
- [ ] Review page (`4_Review.py`)
- [ ] Golden evaluation set (`tests/golden/`)

## Phase 3 — Adaptivity & Community

Not started. See [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#phase-3--adaptivity--community).

- [ ] `topic_mastery` triggers + `core/engine/mastery.py`
- [ ] `core/engine/selector.py` — adaptive selection
- [ ] Progress page (`6_Progress.py`)
- [ ] Community tier: publish, upvote, report
- [ ] AI-assisted authoring (`core/engine/authoring.py`)
- [ ] Admin page (`9_Admin.py`) full build — moderation queue, tier promotion, bulk authoring, bank-health stats
- [ ] Knowledge base content + Knowledge page (`5_Knowledge.py`)

## Phase 4 — Depth

Not started. See [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#phase-4--depth).

- [ ] `pgvector` semantic search
- [ ] Session coaching synthesis
- [ ] Retry-and-compare
- [ ] Export/import
- [ ] Institution-specific interview profiles

## Phase 5 — Exploration

Unscheduled. See [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#phase-5--exploration-unscheduled).

---

## Log

| Date | Note |
|---|---|
| 2026-07-28 | Spec finalized (PROJECT_SPEC.md + docs/). Phase 1 implementation started. |
| 2026-07-28 | Phase 1 code complete: models, migrations, RLS, repositories, scripts, 40-question seed bank, auth-gated Streamlit app with Dashboard/Question Bank/Settings/Admin-placeholder, CI workflow. Lint/type/unit checks green locally. Not yet verified against a live Supabase project or a local Postgres for integration/RLS tests — see Caveats above. |
