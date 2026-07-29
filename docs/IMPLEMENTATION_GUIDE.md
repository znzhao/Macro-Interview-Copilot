# Implementation Guide

Setup, configuration, coding standards, testing, CI, and the phased roadmap.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DATA_SPEC.md](DATA_SPEC.md)

---

# 1. Local Setup

```bash
python -m venv .venv && . .venv/Scripts/activate     # Windows
pip install -r requirements.txt -r requirements-dev.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in Supabase values
python scripts/apply_migrations.py
python scripts/seed_db.py

streamlit run streamlit_app.py
```

Integration tests need a local Postgres with `pgcrypto` and `pg_trgm`:

```bash
docker run -d --name mic-pg -e POSTGRES_PASSWORD=postgres -p 5433:5432 postgres:16
pytest tests/integration
```

---

# 2. Configuration & Secrets

`.streamlit/secrets.toml` — never committed; `.example` is:

```toml
[supabase]
url      = "https://xxxx.supabase.co"
anon_key = "eyJ..."          # anon key ONLY — the service-role key never lives in the app

[app]
environment  = "production"
admin_emails = ["you@example.com"]   # bootstrap only; is_admin lives in the database
```

Rules:

- `core/config.py` loads these into a validated Pydantic `Settings` object **at startup** and **fails loudly** on a missing or malformed value. Silent degradation into a half-working app is worse than not starting.
- **No `os.getenv` anywhere else in the codebase.** Config has exactly one entry point.
- The service-role key must never appear in the Streamlit app — it bypasses all RLS ([DATA_SPEC §6.2](DATA_SPEC.md#62-row-level-security)).
- User LLM keys are never configuration. They live in session state only ([D4](DECISIONS.md#d4--byo-llm-api-key-session-memory-only)).

---

# 3. Coding Standards

## Code
- Strict separation of UI, engine, and data ([ARCHITECTURE §2](ARCHITECTURE.md#2-layer-rules)), enforced by `import-linter` in CI.
- Type hints everywhere; `mypy --strict` clean on `core/`.
- **Pure functions for anything scoreable** — selection, mastery, totals. If it decides a number, it must be testable without a network.
- `ruff` for lint and format, configured in `pyproject.toml`.
- Components over copy-paste: a UI pattern used twice becomes a component.

## Data
- Postgres is the source of truth for user data and questions.
- Git is the source of truth for prompts, knowledge, migrations, and the seed snapshot.
- **Denormalize deliberately and document why** — see `interview_turns.question_text`.
- Never mix static content and user state in one table.

## AI

AI **should**: play a demanding interviewer, produce structured evidence-linked feedback, identify weaknesses across sessions, and draft candidate questions for human review.

AI **must not**: hand out memorizable model answers ([AI_SPEC §3.3](AI_SPEC.md#33-what-the-evaluator-must-and-must-not-return)), fabricate sources or interview provenance ([CONTENT_SPEC §6.1](CONTENT_SPEC.md#61-anti-fabrication-rules)), produce a total score directly ([AI_SPEC §3.2](AI_SPEC.md#32-total-score)), or be trusted without schema validation ([AI_SPEC §1.2](AI_SPEC.md#12-requirements)).

---

# 4. Definition of Done

A change is done when: `mypy --strict` and `ruff` pass · new logic has unit tests · new tables or policies have RLS isolation tests · user-facing errors are typed and handled ([ARCHITECTURE §5](ARCHITECTURE.md#5-error-handling--failure-modes)) · no secret can reach a log · the relevant spec document is updated if behavior changed.

---

# 5. Testing Strategy

## 5.1 Unit — `tests/unit/`
No network, no database.

- Pydantic validators, including the tier/source and module/topic coherence rules.
- `total_score` arithmetic across every mode weight table.
- `weakness()` and the EWMA update, including first-observation and low-`attempts` damping.
- Selector determinism under a fixed seed; composition quota compliance; graceful degradation on empty mastery.
- Session state machine: every transition **and every error edge**.
- Prompt loader: missing variable raises; version and hash are correct.

## 5.2 Integration — `tests/integration/`
Against a real local Postgres.

- Every repository method against the real schema.
- **RLS policy tests are mandatory.** For each table, assert that user A can neither read nor write user B's rows. The `interview_turns` policy (which joins through `interview_sessions` rather than carrying `user_id`) is the easiest one to get wrong and gets explicit coverage.
- Migration apply; checksum-mismatch detection.
- Trigger-driven mastery update matches a from-scratch recomputation from `evaluations`.
- **The persistence invariant:** an induced LLM failure mid-evaluation leaves the answer stored and recoverable ([AI_SPEC §4.2](AI_SPEC.md#42-session-state-machine)).

## 5.3 LLM adapters — `tests/llm/`
Recorded fixtures, no live calls.

Each provider against: happy path, schema-invalid output, 401, 429, timeout. Assert the repair retry fires **exactly once**. Assert that **no API key appears in any log record or exception message** — this is a test, not a code-review hope.

## 5.4 Golden evaluation set — `tests/golden/`

20–30 hand-scored answers spanning the quality range, from incoherent to genuinely strong. On any evaluator prompt or weight change, run the set and assert:

- Mean absolute error per dimension ≤ **0.6**
- Rank correlation with human scores ≥ **0.8**
- **No response contains a complete model answer** — checked by length and structure heuristics on `improved_outline`

This is the regression suite for the product's central claim. It costs money to run, so it runs on demand rather than on every push — but a rubric or prompt change that skips it is not shippable.

## 5.5 CI — `.github/workflows/ci.yml`

```
ruff  →  mypy --strict core/  →  import-linter (layer rules)
      →  unit tests
      →  integration tests (Postgres service container)
      →  scripts/validate_content.py
```

---

# 6. Roadmap & Acceptance Criteria

Each phase ships something usable. Acceptance criteria are testable statements, not vibes.

## Phase 1 — Foundation

**Ships:** Supabase project, schema, and RLS · Supabase Auth · seed script and an initial verified bank (≥100 questions) · Question Bank with search, filters, favorites, notes · Settings · Dashboard shell.

**Done when:** a new user signs up, browses and filters the bank, favorites and annotates questions, logs out, logs back in **on another device**, and sees their data. RLS integration tests pass. No AI features exist yet.

## Phase 2 — Interview & Evaluation

**Ships:** BYO-key flow with validation · LLM adapters for all three providers · `evaluator.v1` with the anchored rubric · interview state machine with persistence · Review page · single-question practice.

**Done when:** a user completes a 5-question interview with follow-ups; every answer is persisted before evaluation; an **induced API failure loses no data**; the golden set meets the §5.4 thresholds.

## Phase 3 — Adaptivity & Community

**Ships:** `topic_mastery` triggers · adaptive selector · Progress page with per-dimension trends · community tier with publish, upvote, report · AI-assisted authoring · Admin page and moderation queue · knowledge base.

**Done when:** after 15 evaluated answers the system **measurably** concentrates selection on the user's weakest topics; a user can publish a question and another user can find and report it; an admin can promote a community question to verified.

## Phase 4 — Depth

**Ships:** `pgvector` semantic search · session coaching synthesis · retry-and-compare · export/import · institution-specific interview profiles.

## Phase 5 — Exploration (unscheduled)

Voice interview · FRED integration for live-data questions · news-driven question generation · research-paper RAG · multi-agent interview panel · resume analysis.

---

# 7. Build Order Within Phase 1

Suggested sequence, since dependencies are real here:

1. `core/models/enums.py` — the controlled vocabularies. Everything else references them.
2. `core/models/*` — Pydantic models with validators, plus unit tests.
3. `core/db/migrations/0001_init.sql` and `0002_rls.sql`.
4. `core/config.py`, `core/db/client.py`, `core/auth.py`.
5. `core/db/repositories/*` with integration tests, **RLS tests included from the start** — retrofitting them is how policy gaps ship.
6. `scripts/apply_migrations.py`, `scripts/seed_db.py`, `scripts/validate_content.py`.
7. Initial seed content: ≥100 verified questions.
8. `streamlit_app.py` auth gate, then Settings, Question Bank, Dashboard shell.
