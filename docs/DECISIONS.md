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
| [D10](#d10--answer-keys-are-structured-bullets-never-prose) | Answer keys are structured bullets, never prose | Accepted |
| [D11](#d11--verified-means-admin-approved-quality-not-traceable-provenance) | `verified` means admin-approved quality, not traceable provenance | Accepted |
| [D12](#d12--the-knowledge-base-is-a-three-tier-postgres-bank) | The knowledge base is a three-tier Postgres bank | Accepted |
| [D13](#d13--question-authoring-is-an-agentic-loop-with-tools) | Question authoring is an agentic loop with tools | Accepted |
| [D14](#d14--promotion-to-verified-clones-the-row) | Promotion to `verified` clones the row | Accepted |
| [D15](#d15--in-app-notifications-only-no-email) | In-app notifications only, no email | Accepted |

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

**Decision.** Postgres full-text search plus trigram fallback and typed metadata filters. Semantic search deferred to `pgvector`.

> **The "Phase 4" in this decision's title is the *old* numbering** — semantic search is now Phase 5 after the 2026-07-30 renumbering. The heading is left alone deliberately: several documents anchor-link to `#d7--keyword--metadata-filtering-in-v1-pgvector-in-phase-4`, and silently breaking those links is worse than a stale number. The decision itself is unchanged, and now covers **both** banks.

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

## D10 — Answer keys are structured bullets, never prose

**Context.** Questions are far more useful with a reference answer attached, and users asked for one. But [PROJECT_SPEC §1.2](../PROJECT_SPEC.md#12-what-this-is-not) states the product is *"not a model-answer library"*, and [AI_SPEC §3.3](AI_SPEC.md#33-what-the-evaluator-must-and-must-not-return) forbids the evaluator from returning a memorizable answer. A prose reference answer on every question would hand candidates exactly the script the product exists to prevent.

**Decision.** Every question may carry an **answer key**: five labelled sections of short bullets, mirroring the scoring dimensions.

| Section | Rubric dimension it prepares |
|---|---|
| `framework` | Macro Framework |
| `mechanism` | Economic Logic |
| `indicators` | Evidence |
| `market_implication` | Market Connection |
| `common_traps` | *(no dimension — this is the trap list, replacing Communication, which is a delivery property and cannot be pre-written)* |

**The structure is the enforcement.** Each section holds **at most 8 bullets of at most 240 characters each**, validated by Pydantic and by a CHECK constraint. A candidate cannot memorize a bulleted skeleton and recite it as an answer — they still have to build the prose, which is the skill being trained. This is the same technique the anchored rubric uses in [D6](#d6--anchored-04-rubric-across-five-dimensions-weighted-to-0100): constrain the shape, and the desired behavior follows structurally rather than by request.

**Rationale.** Preserves the central guardrail while delivering what users actually need. As a bonus, a rubric-aligned key is per-question grading context the evaluator can consume in a later phase without any reshaping.

**Consequences.**
- [PROJECT_SPEC §1.2](../PROJECT_SPEC.md#12-what-this-is-not) is amended, not abandoned — "no model answers" now means "no prose answers", enforced by schema.
- The authoring agent must be prompted and schema-constrained to emit bullets. A bullet that is a run-on paragraph is a validation failure, not a warning.
- The golden suite's "no complete model answer" assertion ([IMPLEMENTATION_GUIDE §5.4](IMPLEMENTATION_GUIDE.md#54-golden-evaluation-set-testsgolden)) extends to answer keys: a test asserts no section can be concatenated into a coherent standalone essay.
- Answer keys are hidden during an active interview turn ([UI_SPEC §1.3](UI_SPEC.md#13-interview--3_interviewpy)).

**Rejected alternatives.** Full prose gated behind an attempt (the gate is a UI convention, and any UI convention on a public app eventually leaks). Full prose always visible (abandons the guardrail outright).

---

## D11 — `verified` means admin-approved quality, not traceable provenance

**Context.** The `verified_needs_source` CHECK constraint ([DATA_SPEC §3.1](DATA_SPEC.md#31-constraints)) required a real `source_url` on every verified-tier row. AI-authored questions have no source by design, because [CONTENT_SPEC §6.1](CONTENT_SPEC.md#61-anti-fabrication-rules) forbids inventing one. Under the original rules, an AI-authored question could **never** be promoted, no matter how good it was — the admin queue would deadlock permanently.

**Decision.** Drop `verified_needs_source`. `tier = 'verified'` now means **an admin reviewed this and vouches for its quality**. Provenance moves entirely onto `verification_level`.

**Rationale.** Quality and traceability are genuinely different properties, and the schema was conflating them. An excellent AI-authored question and a mediocre sourced one should not be ranked by which one happens to have a URL.

**Consequences.**
- **The verification badge becomes the only place provenance is communicated, so it is now load-bearing rather than decorative.** It must be visible on every card in every context, never truncated, never behind a hover on mobile. A user must be able to tell a real reported interview question from an AI-written one without clicking. [UI_SPEC §4](UI_SPEC.md#4-visual-conventions) makes this a hard requirement.
- The anti-fabrication rules are **unchanged and still absolute**. Dropping the constraint permits a *null* source. It never permits an *invented* one.
- Filtering by `verification_level` moves from a nice-to-have filter to a prominent, default-visible control.
- `validate_content.py` no longer fails a verified question for a missing source; it still fails one for a malformed source.

**Rejected alternatives.** Requiring the admin to source every promotion (correct in principle, but the queue stalls and the feature dies). Splitting into `verified_sourced` / `verified_curated` (honest, but users do not read taxonomies carefully, and it duplicates what `verification_level` already encodes).

---

## D12 — The knowledge base is a three-tier Postgres bank

**Context.** [CONTENT_SPEC §7](CONTENT_SPEC.md#7-knowledge-base) specified knowledge as Markdown in `content/knowledge/`, explicitly **not in the database**, authored in Git and shipped with releases. Users must now be able to upload their own documents, generate them with AI, share them, and vote on them — none of which a Git-authored corpus can do, since [ARCHITECTURE §3](ARCHITECTURE.md#3-deployment-constraints) forbids runtime Git writes.

**Decision.** Knowledge documents live in a `knowledge_docs` table with the **same three-tier governance model as questions** — private, community, verified — the same voting, commenting, reporting, submission, and admin-promotion flows, and the same soft-delete rule. `content/knowledge/` and its CI frontmatter validation are deleted.

**Rationale.** Two banks with identical governance means one mental model for users, one RLS pattern, one set of components, and one moderation surface. The alternative — canonical docs in Git, user docs in Postgres — needs two read paths everywhere and still cannot let an admin promote anything.

**Consequences.**
- `slug` remains the join key for `evaluations.suggested_readings`, but now lives on a database row rather than a file.
- **Knowledge docs therefore inherit the never-hard-delete rule.** A stored evaluation may reference a slug for years; deleting the row would strand it. Admin "delete" archives, exactly as for questions ([CONTENT_SPEC §3](CONTENT_SPEC.md#3-moderation)).
- The reviewable-in-a-pull-request workflow for canonical content is lost. Accepted deliberately: admin promotion is the review workflow now.
- Knowledge is the grounding corpus for authoring ([D13](#d13--question-authoring-is-an-agentic-loop-with-tools)), which makes it a product surface rather than a documentation folder.

**Rejected alternatives.** Hybrid Git/Postgres (two read paths, and promotion cannot write to Git at runtime). Keeping knowledge in Git only (cannot satisfy the requirement at all).

---

## D13 — Question authoring is an agentic loop with tools

**Context.** [CONTENT_SPEC §6](CONTENT_SPEC.md#6-ai-assisted-authoring) specified one-shot drafting via `question_author.v1.md`. The requirement is now a genuine assistant: it should read a URL or an uploaded file, ground itself in selected knowledge documents, and accept iterative feedback — while still producing a good question from a couple of button clicks for a user who wants nothing to do with any of that.

**Decision.** A multi-turn agent loop in `core/agent/`, with a bounded tool set, over **all three providers**.

**Rationale.** Iterative refinement is how question quality actually gets to a usable level; one-shot generation produces plausible-but-generic questions. Grounding in user-selected knowledge is what makes output specific enough to be worth reviewing.

**Consequences.**
- `LLMProvider` gains a second method, `complete_with_tools`. Tool-calling diverges across providers far more than structured output does — different tool-result message shapes, different malformed-argument behavior. **This is the single largest work item in Phase 2.** The adapter boundary is written so one provider can ship first if the other two drag.
- **Every tool is a security boundary.** URL fetching means the server makes outbound requests on a stranger's instruction; unconstrained, that is an SSRF hole pointed at the cloud metadata endpoint. The bounds in [AI_SPEC §7](AI_SPEC.md#7-agent-tools--safety) are hard requirements with tests, not guidance.
- Agent turns, tool calls, and tokens are capped per draft. Under [D4](#d4--byo-llm-api-key-session-memory-only) the user pays, but a runaway loop silently burning someone's credit is still our bug.
- The one-click path is a first-class requirement, not a fallback: pick module and topic, press Generate, get a reviewable draft with no conversation at all.

---

## D14 — Promotion to `verified` clones the row

**Context.** If promotion simply flipped `tier` on the author's row, the author would lose their question to the canonical bank, and any later edit by them would silently rewrite canonical content.

**Decision.** Admin promotion **inserts a new row** at `tier='verified'`, owned by the system and editable only by admins, carrying `source_question_id` back to the original. The community original stays where it is, still owned and editable by its author, who may later flip it back to `private`.

**Rationale.** Cleanly separates "the author's work" from "the canonical artifact". Canonical content becomes immutable-by-default and cannot be edited out from under the users practicing it.

**Consequences.**
- **A user cannot withdraw a promoted question.** Flipping their original back to private does not retract the verified clone. This must be stated in an explicit confirmation *before* submission, never discovered afterwards.
- Duplicate detection must exclude a clone's own lineage, or every promotion trips the near-duplicate warning.
- The same model applies to knowledge documents.
- Submission is an explicit act with its own record ([DATA_SPEC §5.7](DATA_SPEC.md#57-review_requests)), not merely a status change, so the author can be notified of the outcome.

---

## D15 — In-app notifications only, no email

**Context.** [D14](#d14--promotion-to-verified-clones-the-row) and threaded comments both create events the author needs to learn about. Email is the obvious channel and the wrong one here: Supabase's built-in mailer is rate-limited to a handful of messages an hour and gates template editing behind custom SMTP — the exact wall that already forced the switch away from magic-link auth ([DEPLOYMENT.md §4.3.1](DEPLOYMENT.md)).

**Decision.** A `notifications` table and an Inbox page with an unread badge. Events: submission approved, submission rejected, comment on your content, reply to your comment. No email, no digest.

**Rationale.** Ships immediately on the free tier with no external dependency, no deliverability surface, and no unsubscribe obligations.

**Consequences.**
- Users only see outcomes when they return to the app. Acceptable for this audience and scale.
- **Vote events are deliberately excluded.** Upvote notifications get noisy immediately, and downvote notifications are actively demoralizing on a small user base.
- Notifications are generated by database triggers, not application code, so no write path can forget to emit one.
- Email remains available later behind custom SMTP without schema change — the `notifications` row is the record either way.

---

# 2. Open Questions

Each must be resolved before the phase noted.

| # | Question | Resolve by | Current default |
|---|---|---|---|
| 1 | **Anonymous trial.** Login is required for everything beyond a read-only preview. Does that suppress adoption enough to justify an anonymous mode? | Phase 3 | Login required |
| 2 | **Institution profiles.** Should each institution have a curated profile (focus areas, style, known process) driving mode and selection, or is the `institutions[]` tag sufficient? | Phase 5 | Tag only |
| 3 | **Answer length limits.** Cap answer input to bound token cost? A hard cap is arguably good interview discipline in its own right. | Phase 3 | No cap |
| 4 | **Free-tier idle pause.** Ship a keep-alive ping, or accept the ~30s wake and design the loading state well? | Phase 1 | Resolved — loading state |
| 5 | **Community quality floor.** Should community questions require N upvotes before entering interview selection? | Phase 4 | Opt-in toggle, no floor |
| 6 | **Voice interview.** Streamlit audio input plus Whisper is feasible but substantially changes the answer-capture path. | Phase 6 | Deferred |
| 7 | **Answer keys as evaluator context.** Should `evaluator.v1` receive a question's answer key as grading reference? It would sharpen scoring on bank questions, but scores would stop being comparable between questions that have a key and questions that don't — and it needs a new prompt version plus full golden re-calibration. | Phase 3 | Not passed to the evaluator |
| 8 | **Practicing a question whose key you've read.** A user can save a question with its answer key privately and then practice it. Should those attempts be excluded from mastery, or flagged in Progress? | Phase 4 | Counted normally, no flag |
| 9 | **Submission rate limits.** [AI_SPEC §7.3](AI_SPEC.md#73-usage-bounds) caps drafting. Should community *submission* also be capped, to stop one user flooding the review queue? | Phase 2 | 20 submissions/user/day |
| 10 | **Knowledge doc size.** Uploaded Markdown is capped at 1 MB, but injecting a large doc into a prompt is a token-cost problem, not a storage one. Is a hard per-doc token ceiling needed, or is the total grounding budget sufficient? | Phase 2 | Total budget only |

---

# 3. Decision Log Convention

New decisions get the next `D<n>` and the same structure: **Context → Decision → Rationale → Consequences → Rejected alternatives**. Superseded decisions are marked `Superseded by Dn` and kept — never deleted. The reasoning that was wrong is as useful as the reasoning that was right.
