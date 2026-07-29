# Architectural Decisions

Binding decisions for Macro Interview Copilot. Changing one requires updating this file and auditing every document that references it.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md)

---

# 1. Decision Register

| # | Decision | Status |
|---|---|---|
| [D1](#d1--streamlit-multipage-app-on-streamlit-community-cloud) | Streamlit multipage app on Streamlit Community Cloud | Accepted |
| [D2](#d2--supabase-postgres-is-the-sole-persistence-layer) | Supabase Postgres is the sole persistence layer | Accepted |
| [D3](#d3--supabase-auth-magic-link--google-oauth) | Supabase Auth (magic link + Google OAuth) | Accepted |
| [D4](#d4--byo-llm-api-key-session-memory-only) | BYO LLM API key, session-memory only | Accepted |
| [D5](#d5--postgres-is-source-of-truth-for-all-question-tiers) | Postgres is source of truth for all question tiers | Accepted |
| [D6](#d6--anchored-04-rubric-across-five-dimensions-weighted-to-0100) | Anchored 0–4 rubric across five dimensions, weighted to 0–100 | Accepted |
| [D7](#d7--keyword--metadata-filtering-in-v1-pgvector-in-phase-4) | Keyword + metadata filtering in v1; pgvector in Phase 4 | Accepted |
| [D8](#d8--prompts-are-versioned-markdown-files) | Prompts are versioned Markdown files, never inline strings | Accepted |
| [D9](#d9--bank-seeded-interviews-with-ai-follow-ups-and-adaptive-selection) | Bank-seeded interviews with AI follow-ups and adaptive selection | Accepted |

---

## D1 — Streamlit multipage app on Streamlit Community Cloud

**Context.** The app must be publicly shareable via a URL with no infrastructure cost and no ops burden.

**Decision.** Streamlit, deployed on Streamlit Community Cloud from the GitHub repo.

**Rationale.** Zero-cost public hosting, Python-native (matching the macro/data tooling this project will grow into), fastest path from repo to shareable link.

**Consequences.**
- Ephemeral filesystem, shared ~1GB container, whole-script rerun execution model.
- Directly forces [D2](#d2--supabase-postgres-is-the-sole-persistence-layer) and [D7](#d7--keyword--metadata-filtering-in-v1-pgvector-in-phase-4).
- Requires the discipline rules in [UI_SPEC §3](UI_SPEC.md#3-streamlit-runtime-discipline) — Streamlit's rerun model will otherwise cause duplicate paid API calls and cross-user state leaks.

**Rejected alternatives.** React/Vite SPA (better UX, far more work, still needs a backend for keys). Local desktop app (contradicts the shareability requirement).

---

## D2 — Supabase Postgres is the sole persistence layer

**Context.** Streamlit Cloud's disk is wiped on redeploy, on idle sleep, and at platform discretion. Any user data written to disk is silently lost.

**Decision.** All user data and all questions live in Supabase Postgres. No SQLite, no on-disk JSON for user data, no IndexedDB.

**Rationale.** Managed Postgres survives redeploys, supports multi-user, provides Row Level Security for per-user isolation, and has a free tier adequate for this scale.

**Consequences.**
- A hosted dependency and a migration discipline ([DATA_SPEC §7](DATA_SPEC.md#7-migrations--versioning)).
- Free tier pauses after ~7 days of inactivity — the app must render a wake-up state, not a stack trace ([ARCHITECTURE §5](ARCHITECTURE.md#5-error-handling--failure-modes)).
- Aggregation must happen in SQL, not by pulling rows into a 1GB shared process.

**Rejected alternatives.** IndexedDB via a custom component — the only other coherent option, since it is free and per-user. Rejected because it has no cross-device story, is destroyed by a cache clear, fights the rerun model on every read, and provides nowhere to host the community question tier.

---

## D3 — Supabase Auth (magic link + Google OAuth)

**Decision.** Supabase Auth, with RLS policies bound to `auth.uid()`.

**Rationale.** Auth and data in one system means authorization is enforced at the row level in the database rather than in application code. No password handling.

**Consequences.**
- No anonymous mode in v1 — see [Open Question 1](#open-questions).
- Every user-owned row carries `user_id`.
- The app uses the anon key plus the user's JWT. **The service-role key is never used in the Streamlit app**, since it bypasses all RLS.

---

## D4 — BYO LLM API key, session-memory only

**Context.** A public URL with a project-owned API key is an unbounded liability.

**Decision.** Users supply their own OpenAI / Anthropic / Gemini key. It is held in `st.session_state` for the browser session and never persisted.

**Rationale.** Eliminates cost and abuse risk entirely. No rate limiting, quota tracking, or spend alarms needed.

**Consequences.**
- Friction: casual visitors will bounce at the key prompt. Mitigated by keeping browsing, notes, favorites, and the knowledge base fully functional without a key.
- The key must never reach the database, logs, error messages, or `raw_response` payloads.
- Cost transparency shifts to the user: token usage is surfaced after every AI action ([AI_SPEC §1.3](AI_SPEC.md#13-cost-transparency)).

---

## D5 — Postgres is source of truth for all question tiers

**Context.** In-app admin authoring (a product requirement) is incompatible with a Git-only verified bank, because Streamlit Cloud cannot write to Git at runtime.

**Decision.** All three tiers — `verified`, `community`, `private` — live in one `questions` table. Git holds `content/questions/seed/` as (a) the bootstrap seed and (b) a versioned snapshot refreshed by an export script.

**Rationale.** One schema, one query path, one set of filters. Admin authoring writes live. Version history and CI validation are preserved through the export/validate scripts.

**Consequences.**
- `scripts/export_questions.py` must be run before releases or the Git snapshot goes stale.
- CI validates the seed files, not the live bank; a nightly job can validate live rows.
- See [CONTENT_SPEC §4](CONTENT_SPEC.md#4-git-seed-and-snapshot).

---

## D6 — Anchored 0–4 rubric across five dimensions, weighted to 0–100

**Context.** An LLM asked for "a score out of 100" produces numbers that drift run to run, making every progress chart noise.

**Decision.** Five dimensions, each scored 0–4 against **written anchor descriptions embedded verbatim in the prompt**. The 0–100 total is computed in Python from those dimensions.

**Rationale.** Anchors are the mechanism that makes LLM scoring reproducible. Computing the total in code removes the last determinism leak.

**Consequences.**
- Per-dimension scores are stored, never just the total — this is also what makes weakness detection possible.
- Weight changes require a new `prompt_version`, and trend charts must warn when a range spans versions.
- A golden calibration set gates any rubric change ([IMPLEMENTATION_GUIDE §5.4](IMPLEMENTATION_GUIDE.md#54-golden-evaluation-set-testsgolden)).

---

## D7 — Keyword + metadata filtering in v1; pgvector in Phase 4

**Decision.** Postgres full-text search plus trigram fallback and typed metadata filters. Semantic search deferred to `pgvector` in Phase 4.

**Rationale.** Semantic search is unjustified below roughly 1,000 questions, and Postgres FTS handles the real query patterns (institution, module, topic, keyword) well.

**Consequences.**
- **In-process FAISS or ChromaDB is permanently out of scope.** A vector index loaded into a shared 1GB container is how every concurrent user gets an OOM restart at once.
- Phase 4 embeddings are generated by an admin-triggered batch job, never on the request path.

---

## D8 — Prompts are versioned Markdown files

**Decision.** Prompts live in `prompts/<name>.v<N>.md`. No prompt text appears in Python source. Every persisted AI artifact records `prompt_version` and `model`.

**Rationale.** A score is only comparable to another score if you know which rubric produced it. Without prompt versioning, every prompt edit silently invalidates all historical data.

**Consequences.**
- A behavior-changing prompt edit requires a **new file**, not an edit to an existing one.
- Released prompt files are immutable.

---

## D9 — Bank-seeded interviews with AI follow-ups and adaptive selection

**Decision.** Sessions draw N real questions from the bank, the LLM generates adaptive follow-ups from the candidate's actual answers, and once sufficient history exists the selector concentrates on weak topics.

**Rationale.** Grounds sessions in verified material, bounds token cost, and keeps interviewer behavior testable. A fully AI-driven interviewer drifts off the target institution and costs unpredictably.

**Consequences.**
- The selector is a **pure function** — no I/O, fully unit-testable, deterministic under a fixed seed ([AI_SPEC §5](AI_SPEC.md#5-adaptive-question-selection)).
- Adaptive mode cannot be the day-one default; it needs history first, so a non-adaptive fallback path must exist.

---

# 2. Open Questions

Each must be resolved before the phase noted.

| # | Question | Resolve by | Current default |
|---|---|---|---|
| 1 | **Anonymous trial.** Login is required for everything beyond a read-only preview. Does that suppress adoption enough to justify an anonymous mode? | Phase 2 | Login required |
| 2 | **Institution profiles.** Should each institution have a curated profile (focus areas, style, known process) driving mode and selection, or is the `institutions[]` tag sufficient? | Phase 4 | Tag only |
| 3 | **Answer length limits.** Cap answer input to bound token cost? A hard cap is arguably good interview discipline in its own right. | Phase 2 | No cap |
| 4 | **Free-tier idle pause.** Ship a keep-alive ping, or accept the ~30s wake and design the loading state well? | Phase 1 | Design the loading state |
| 5 | **Community quality floor.** Should community questions require N upvotes before entering interview selection? | Phase 3 | Opt-in toggle, no floor |
| 6 | **Voice interview.** Streamlit audio input plus Whisper is feasible but substantially changes the answer-capture path. | Phase 5 | Deferred |

---

# 3. Decision Log Convention

New decisions get the next `D<n>` and the same structure: **Context → Decision → Rationale → Consequences → Rejected alternatives**. Superseded decisions are marked `Superseded by Dn` and kept — never deleted. The reasoning that was wrong is as useful as the reasoning that was right.
