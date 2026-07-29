# Architecture

System shape, layer boundaries, deployment constraints, repository layout, and failure handling.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md) · Decisions: [DECISIONS.md](DECISIONS.md)

---

# 1. System Architecture

```
                          ┌──────────────────────────────┐
                          │      Git Repository          │
                          │                              │
                          │  content/questions/seed/     │  bootstrap + snapshot
                          │  content/knowledge/*.md      │  read at runtime
                          │  prompts/*.vN.md             │  read at runtime
                          │  core/db/migrations/*.sql    │  applied via script
                          └──────────────┬───────────────┘
                                         │ deployed
                                         ↓
   ┌────────────────────────────────────────────────────────────────────┐
   │            Streamlit Community Cloud (single container)            │
   │                                                                    │
   │   app/pages/*          UI only. No business logic, no SQL.         │
   │        │                                                           │
   │   core/engine/         Interview state machine, evaluator,         │
   │        │               adaptive selector. Pure Python.             │
   │        │                                                           │
   │   core/llm/            Provider adapters, structured output.       │
   │        │                                                           │
   │   core/db/repositories The only place SQL or PostgREST calls       │
   │        │               are allowed to exist.                       │
   └────────┼────────────────────────────────┬──────────────────────────┘
            │                                │
            ↓ user's own key                 ↓ anon key + user JWT, RLS enforced
   ┌──────────────────┐         ┌────────────────────────────────────┐
   │  OpenAI /        │         │        Supabase                    │
   │  Anthropic /     │         │  Auth: magic link, Google OAuth    │
   │  Gemini          │         │  Postgres: questions, sessions,    │
   └──────────────────┘         │  turns, evaluations, notes,        │
                                │  favorites, mastery, reports       │
                                │  RLS: per-user isolation           │
                                └────────────────────────────────────┘
```

---

# 2. Layer Rules

Dependencies point downward only. These are enforced by `import-linter` in CI — violations are build failures, not style nits.

```
app/pages  ──►  core/engine  ──►  core/llm
     │                │               │
     └────────────────┴───────────────┴──►  core/db/repositories  ──►  core/models
```

| Layer | May import | Must not |
|---|---|---|
| `app/pages`, `app/components` | `core.engine`, `core.db.repositories`, `core.models`, `streamlit` | Contain SQL, prompt text, or scoring arithmetic |
| `core/engine` | `core.llm`, `core.models`, `core.prompts` | Import `streamlit`; must be runnable headlessly |
| `core/llm` | `core.models` | Import `streamlit` or any repository |
| `core/db/repositories` | `core.models`, `supabase` | Import `streamlit`; caching is applied by callers |
| `core/models` | stdlib, `pydantic` | Import anything else from the project |

**Why `core/engine` must not import Streamlit:** everything that decides a number — selection, scoring, mastery — has to be testable without a browser or a network. If the engine reaches into `st.session_state`, that testability is gone and the golden calibration suite becomes impossible.

---

# 3. Deployment Constraints

Every constraint here has already invalidated a design in this project. Treat them as hard requirements, not warnings.

| Constraint | Implication |
|---|---|
| **Ephemeral filesystem** — reset on redeploy, idle sleep, and platform restarts | Never write user data to disk. `/tmp` is for within-request scratch only. |
| **No Git write access at runtime** | The app cannot commit questions. Admin authoring writes to Postgres ([D5](DECISIONS.md#d5--postgres-is-source-of-truth-for-all-question-tiers)). |
| **~1GB RAM shared across all concurrent users** | No in-process vector indexes. Never load the full bank unbounded — paginate. Cache with explicit `ttl` and `max_entries`. |
| **Single shared process** | Module-level mutable state leaks *across users*. All per-user state lives in `st.session_state` or the database. |
| **App sleeps when idle; cold start ~30s** | Cold-start work must be lazy. No eager loads at import time. |
| **Public URL** | Assume every page is reachable by anyone. Authorization is RLS, not hidden UI. |
| **Supabase free tier pauses after ~7 days idle** | Render a clear "waking the database" state, never a stack trace (§5). |
| **`st.secrets` holds project config only** | Never a user's LLM key ([D4](DECISIONS.md#d4--byo-llm-api-key-session-memory-only)). |

---

# 4. Repository Layout

```
macro-interview-copilot/
│
├── streamlit_app.py              # Entry point. Auth gate + navigation only.
│
├── app/
│   ├── pages/
│   │   ├── 1_Dashboard.py
│   │   ├── 2_Question_Bank.py
│   │   ├── 3_Interview.py
│   │   ├── 4_Review.py
│   │   ├── 5_Knowledge.py
│   │   ├── 6_Progress.py
│   │   ├── 7_Settings.py
│   │   └── 9_Admin.py            # gated on profiles.is_admin AND RLS
│   ├── components/
│   │   ├── question_card.py
│   │   ├── score_radar.py        # 5-dimension radar (Plotly)
│   │   ├── rubric_breakdown.py
│   │   ├── filters.py            # shared filter sidebar
│   │   ├── api_key_gate.py       # BYO-key prompt + validation
│   │   └── empty_states.py
│   └── state.py                  # st.session_state keys + typed accessors
│
├── core/
│   ├── config.py                 # Settings from st.secrets, validated at startup
│   ├── auth.py                   # Supabase Auth wrapper, current_user()
│   ├── models/                   # Pydantic v2. No I/O.
│   │   ├── question.py
│   │   ├── session.py
│   │   ├── evaluation.py
│   │   ├── profile.py
│   │   └── enums.py              # controlled vocabularies live here
│   ├── db/
│   │   ├── client.py             # cached Supabase client factory
│   │   ├── repositories/
│   │   │   ├── base.py
│   │   │   ├── questions.py
│   │   │   ├── sessions.py
│   │   │   ├── turns.py
│   │   │   ├── evaluations.py
│   │   │   ├── notes.py
│   │   │   ├── favorites.py
│   │   │   ├── profiles.py
│   │   │   ├── mastery.py
│   │   │   └── reports.py
│   │   └── migrations/
│   │       ├── 0001_init.sql
│   │       ├── 0002_rls.sql
│   │       └── ...
│   ├── llm/
│   │   ├── base.py               # LLMProvider protocol
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   ├── gemini_provider.py
│   │   ├── registry.py           # provider resolution + key validation
│   │   ├── schemas.py            # JSON schemas for structured output
│   │   └── errors.py
│   ├── engine/
│   │   ├── interviewer.py        # follow-up generation
│   │   ├── evaluator.py          # answer → Evaluation, weight tables
│   │   ├── selector.py           # adaptive selection (pure)
│   │   ├── session.py            # interview state machine (pure)
│   │   ├── mastery.py            # EWMA updates (pure)
│   │   └── authoring.py          # AI-assisted question drafting
│   ├── search/
│   │   ├── keyword.py            # Postgres FTS + trigram
│   │   └── filters.py            # typed filters → query
│   └── prompts/
│       └── loader.py             # load + hash + version prompt files
│
├── prompts/
│   ├── interviewer.v1.md
│   ├── evaluator.v1.md
│   ├── coach.v1.md
│   ├── question_author.v1.md
│   └── summarizer.v1.md
│
├── content/
│   ├── questions/seed/           # versioned snapshot; NOT the live bank
│   └── knowledge/*.md
│
├── scripts/
│   ├── validate_content.py       # schema, dedup, ID continuity, source URLs
│   ├── seed_db.py                # Git seed → Postgres (idempotent upsert)
│   ├── export_questions.py       # Postgres → Git snapshot
│   └── apply_migrations.py
│
├── tests/
│   ├── unit/                     # models, selector, mastery, session FSM
│   ├── integration/              # repositories + RLS against test Postgres
│   ├── llm/                      # adapters against recorded fixtures
│   ├── golden/                   # evaluator calibration regression set
│   └── fixtures/
│
├── docs/                         # this specification
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── .github/workflows/ci.yml
├── requirements.txt
├── CLAUDE.md
└── PROJECT_SPEC.md
```

---

# 5. Error Handling & Failure Modes

| Failure | Detection | Behavior |
|---|---|---|
| No API key set | `session_state` check before any AI action | Non-blocking banner + Settings link. Browsing, notes, favorites, knowledge base stay fully functional. |
| Invalid / rejected key | 401 from provider | "Your API key was rejected." Clear from session. **No retry.** |
| Rate limited (429) | Provider error | One backoff retry, then: "Provider is rate-limiting you — your answer is saved, retry evaluation." |
| LLM timeout | `timeout_s` exceeded | Same as 429. The answer is already persisted (§5.1). |
| Schema-invalid LLM output | Pydantic validation of the structured result | One repair retry, then store the turn unevaluated and offer manual re-evaluation. |
| Supabase paused (free-tier idle) | Connection error on first query | Dedicated full-page state: "Waking the database, this takes about 30 seconds" + retry button. Never a stack trace. |
| Supabase transient error | Typed `BackendUnavailable` | Inline error with retry; unsaved form input preserved in session state. |
| Session interrupted / tab closed | `status='active'` found on load | Dashboard offers "resume session." |
| Concurrent edit conflict | `updated_at` mismatch on question update | Show both versions; user chooses. |
| Double form submit | `(session_id, ordinal)` uniqueness | Second write rejected; no duplicate turn, no duplicate charge. |

## 5.1 Global rules

1. **The user's typed answer is written to the database before any LLM call.** An API failure must never cost someone a five-minute answer. Covered by an integration test.
2. **No raw exception ever reaches the user.** `streamlit_app.py` installs a top-level handler rendering a friendly error with a correlation id.
3. **Nothing user-typed is lost to any error, ever.**
4. **Logs never contain** API keys, JWTs, or answer text.
5. **Typed errors only** across layer boundaries — `NotFound`, `PermissionDenied`, `ConflictError`, `BackendUnavailable`, `LLMSchemaError`, `LLMAuthError`, `LLMRateLimited`. Raw `postgrest` or provider SDK exceptions never propagate upward.
