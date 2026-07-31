# Phase Tracker

Tracks implementation progress against [docs/IMPLEMENTATION_GUIDE.md §6](docs/IMPLEMENTATION_GUIDE.md#6-roadmap--acceptance-criteria). Update this file as steps complete — it is the single place to check "what state is the build in."

**Current phase: Phase 2 — Content Creation & Community** (Schema, Models & repositories, LLM layer, Agent, and UI complete; two Content items — seeding the verified knowledge bank and growing the question bank past 100 — remain, deliberately, pending a real LLM key. See the Content section below.)

> **Roadmap renumbered on 2026-07-30.** What was Phase 2 (Interview & Evaluation) is now Phase 3; the community half of old Phase 3 moved into the new Phase 2; adaptivity became Phase 4. Rationale in [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#phase-2--content-creation--community): a 40-question bank is too thin for the interviewer to be worth using, so the content engine is built before the thing that consumes content.

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
2. ~~**No live Supabase project exists yet.**~~ **Resolved 2026-07-30** — deployed to Streamlit Community Cloud against a live Supabase project; schema, seed, auth, and question browsing all verified in production. Setup steps are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
3. ~~**RLS integration tests are written but unverified.**~~ **Resolved 2026-07-30** — executed against local Postgres 16 on port 5433, **12/12 passing**. Two bugs surfaced on first real execution, both in the test harness rather than the policies:
   - `as_user()` ran its cleanup on an aborted transaction, so any test asserting that a policy *denies* something failed during teardown — the fixture broke on precisely the cases it existed to verify. Now rolls back first when `transaction_status` is `INERROR`.
   - `test_user_cannot_modify_another_users_favorites` assumed a violating INSERT writes zero rows silently. It does not: `USING` filters on read, but **`WITH CHECK` raises** on INSERT/UPDATE. Test corrected to expect `InsufficientPrivilege`.

   Both were latent because the suite had only ever skipped. Re-run with:
   `.venv\Scripts\python.exe -m pytest tests/integration -m integration -v -rs`
   **A result of `12 skipped` means Postgres was unreachable, not that anything passed.**
4. **The PKCE auth code exchange (`core/auth.py:complete_session_from_code`) is still unexercised.** Live sign-in uses email+password, which does not touch it. The `type: ignore` there remains unverified — it only matters if Google OAuth or magic links are enabled later.
5. **`app/pages/2_Question_Bank.py`'s "Favorites only" filter is client-side** on the current page of results, not a database-level filter — fine at this scale, worth revisiting if the bank grows large.

---

## Phase 2 — Content Creation & Community

Spec complete, not started. See [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#phase-2--content-creation--community) and the build order in [§7](docs/IMPLEMENTATION_GUIDE.md#7-build-order-within-phase-2).

New decisions governing this phase: [D10](docs/DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose) answer keys · [D11](docs/DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance) verified semantics · [D12](docs/DECISIONS.md#d12--the-knowledge-base-is-a-three-tier-postgres-bank) knowledge bank · [D13](docs/DECISIONS.md#d13--question-authoring-is-an-agentic-loop-with-tools) agentic authoring · [D14](docs/DECISIONS.md#d14--promotion-to-verified-clones-the-row) promotion by clone · [D15](docs/DECISIONS.md#d15--in-app-notifications-only-no-email) in-app notifications.

**Step 0 — do this before anything else**
- [x] Run the *existing* Phase 1 RLS suite against a real Postgres — **done 2026-07-30, 12/12 passing.** Local Postgres 16 on port 5433. Two harness bugs fixed; no policy defects found. See Phase 1 Caveat 3.
- [x] Audit live Supabase: RLS enabled on all 11 `public` tables, all with policies except `schema_migrations` (deny-all by design — only migration scripts touch it, and they connect as the owning role, which bypasses RLS).

**Schema** — done 2026-07-30
- [x] `0003_content_governance.sql` — drop `verified_needs_source`; add `answer_key` + `answer_key_is_valid()`, `downvotes`, `source_question_id` + `clone_is_verified`; votes widened to ±1 with an `updated_at` column and an UPDATE-aware sync trigger
- [x] `0004_knowledge_and_social.sql` — `knowledge_docs`, `knowledge_votes`, `comments` (with a depth-guard trigger, not a self-referencing CHECK), `review_requests`, `notifications`, new enums (`review_status`, `content_kind`, `notification_kind`)
- [x] `0005_phase2_rls.sql` — RLS for all new tables, `can_view_content()`, `approve_review_request()` / `reject_review_request()` procedures, `notify_on_comment()` trigger
- [x] RLS isolation tests for every new table (17 tests in `test_phase2_rls_policies.py`), including "a client cannot forge a notification"
- [x] Applied against local Postgres and verified with a manual smoke script (answer-key edge cases, full promotion flow) before being folded into the automated suite

**Real bug found and fixed while testing this step:** the vote-sync trigger (`sync_question_upvotes`, and its new `sync_knowledge_votes` counterpart) ran with the *voter's* privileges, not `SECURITY DEFINER`. Its internal `UPDATE questions SET upvotes = ...` was therefore itself subject to `questions_update` RLS, which only the question's owner/author/admin may pass — a vote from anyone else would record correctly but silently fail to move the denormalized count, with no error surfaced anywhere. This bug shipped in Phase 1's original trigger too; nothing caught it there because no Phase 1 test exercised a vote from a non-owner voter. Fixed by adding `SECURITY DEFINER SET search_path = public` to both trigger functions in the migrations above (Phase 1's live `sync_question_upvotes` gets corrected the moment `0003` is applied to production, since it's a `CREATE OR REPLACE`).

**Models & repositories** — done 2026-07-30
- [x] `core/models/answer_key.py` — `AnswerKey` (5 sections × ≤8 bullets × ≤240 chars, `extra="forbid"`)
- [x] `core/models/knowledge.py` — `KnowledgeDoc`, `KnowledgeDraft`, `KnowledgePatch`, `KnowledgeFilters`
- [x] `core/models/social.py` — `Comment`, `CommentDraft`, `ReviewRequest`, `ReviewRequestDraft`, `Notification`, `Vote`, plus `ContentKind`/`ReviewStatus`/`NotificationKind` enums
- [x] `core/models/question.py` updated — `answer_key`, `downvotes`, `source_question_id` added; `_verified_requires_source` validator removed (D11); `QuestionFilters` gained `mine_only`, `has_answer_key`
- [x] Answer-key guardrail tests (`test_answer_key.py`, 12 tests) — Pydantic and SQL checked for parity by the same manual smoke pass used on the migrations
- [x] Model unit tests for the new types (`test_knowledge_model.py`, `test_social_model.py`) plus two existing `test_question_model.py` tests updated for D11 (verified-without-source is now legal, not rejected)
- [x] Repositories: `core/db/repositories/knowledge.py`, `comments.py`, `notifications.py` (deliberately has no insert method — D15), `reviews.py` (approve/reject call the SQL procedures via RPC, never raw table writes), `votes.py` (±1 upsert for both banks)
- [x] `QuestionRepository.upvote()` removed (superseded by `VoteRepository`; had no callers) and `set_tier()` added to both `QuestionRepository` and `KnowledgeRepository` for the share/return-to-private action

**Verified locally (Schema + Models & repositories):** `ruff check` clean, `mypy --strict` clean across `core/` (31 files), `import-linter` all 5 contracts kept, 73/73 tests passing (44 unit + 29 integration), `validate_content.py` still passes on the 40-question seed bank.

`mine_only` on `QuestionFilters`/`KnowledgeFilters` is defined but not wired into `_apply_filters()`, since applying it needs a caller-supplied user id that those query-builder functions don't currently take; noted in code comments at both call sites.

**LLM layer** — done 2026-07-30
- [x] `core/llm/base.py` — `Message`/`ToolSpec`/`ToolCall`/`ToolResult`/`StructuredResult`/`ToolTurnResult`/`ProviderCapabilities`, the `LLMProvider` protocol
- [x] `core/llm/errors.py` — `LLMAuthError`, `LLMRateLimited`, `LLMTimeout`, `LLMSchemaError`, `LLMToolArgError`
- [x] `core/llm/schemas.py` — `QuestionDraftSchema`, `KnowledgeDraftSchema` (Pydantic, `extra="forbid"`, no governance fields — those are assigned by the caller, never the model)
- [x] `core/prompts/loader.py` — `PromptSpec`, variable extraction from `{placeholder}` markers, `.render()` raises on a missing one; 8 unit tests
- [x] `prompts/question_author.v1.md`, `author_agent.v1.md`, `knowledge_author.v1.md` — all with the anti-fabrication and answer-key-bullets rules stated explicitly, `author_agent.v1.md` additionally states fetched/uploaded content is data, not instructions (prompt-injection mitigation)
- [x] `complete_structured` × 3 providers — OpenAI via `response_format=json_schema`; Anthropic via forced tool use (`tool_choice` pinned to a synthetic schema tool, since Anthropic has no native JSON-schema response mode); Gemini via `response_schema` + `response_mime_type="application/json"`
- [x] `complete_with_tools` × 3 providers — **all three from the start**, per your explicit call in the earlier decisions round. `ToolResult` carries an added `tool_name` field alongside `tool_call_id`, because Gemini's function-response protocol is name-keyed, not id-keyed, unlike OpenAI/Anthropic
- [x] `core/llm/registry.py` — provider resolution, capability table, `validate_key()`
- [x] `app/components/api_key_gate.py` — key entry form + "Save and test key" flow calling `registry.validate_key()`. **Not yet wired into the Settings page** — that page still has its Phase-1 stub; wiring it is UI-block work, listed below
- [x] Unit tests: `test_llm_base.py` (Message invariants), `test_llm_schemas.py`, `test_llm_registry.py`

**Caveats on the LLM layer — read before trusting it against real traffic:**
1. **No live API key was available to exercise any provider for real.** Every adapter is implemented against each SDK's documented request/response shapes (openai 1.109, anthropic 0.120, google-genai 0.8, all pinned) and mypy --strict passes against their type stubs, but none of the three has made an actual network call. Treat this the same way Phase 1 treated the untested PKCE flow: implemented correctly per the API, not yet proven against the real service.
2. **Gemini's `response_schema` is given the same plain JSON Schema dict the other two adapters use.** Gemini's documented accepted shape is an OpenAPI 3.0 subset that may not support every JSON Schema construct our Pydantic-generated schemas can produce (`$defs`/`$ref` from the nested `AnswerKey`, in particular). This is the most likely of the three adapters to need adjustment on first real use.
3. **`ToolResult.tool_name` is a real, deliberate abstraction change** (not scope creep) — see the field's docstring in `core/llm/base.py`.

**Agent** — done 2026-07-30
- [x] `core/agent/errors.py` — `ToolBlocked`, `LimitExceeded`
- [x] `core/agent/tools/fetch.py` — SSRF-hardened `fetch_url`: scheme allowlist, DNS-then-validate, redirect revalidation (max 3 hops), streamed 2MB/10s caps, content-type allowlist. **39 tests** in `tests/agent/test_fetch_tool.py` — exhaustive IPv4/IPv6 blocklist coverage including CGNAT and the IPv6-mapped-IPv4 bypass, plus HTTP-level behavior (redirects, size truncation, content-type rejection, redirect-to-metadata-address) against a local stub server
- [x] `core/agent/tools/knowledge.py` — `search_knowledge`/`read_knowledge`, running through the caller's own `KnowledgeRepository` so RLS decides visibility
- [x] `core/agent/tools/uploads.py` — `parse_upload` (`.md`/`.txt` only, ≤1MB, replace-decoded), `read_upload` (in-memory lookup only, never touches disk)
- [x] `core/agent/tools/registry.py` — the closed 4-tool set, `ToolContext`, `execute_tool()` dispatcher with a 20k-char per-result truncation cap (separate from fetch.py's byte cap — this one protects token spend, not memory)
- [x] `core/agent/limits.py` — `UsageCaps`/`UsageTracker` (8 tool calls, 40k tokens, 90s/turn), `check_grounding_budget()` (8k tokens)
- [x] `core/agent/loop.py` — the bounded tool-use loop. The model's "done" signal is a synthetic `submit_draft` tool whose parameters ARE the target Pydantic schema, so the final draft is schema-validated the same way every other tool call's arguments are — no separate closing `complete_structured` call needed
- [x] `core/agent/authoring.py`, `knowledge_authoring.py` — one-click (`complete_structured`, no tools, the default path not a fallback) and refinement (`run_agent_loop`, grounding injected as full text into the opening message per your "explicit picker, inject full text" decision) for both banks. `edited_draft` parameter on the `continue_*` functions is how "the user's manual edits survive a refinement turn" (AI_SPEC §6.2) is actually honored — the caller passes what the user edited, and it replaces the model's own last version in context
- [x] Unit tests: `test_limits.py`, `test_uploads.py`, `test_tool_registry.py`, and `test_loop.py` (9 tests against a scripted fake provider — no network) covering immediate submission, invalid-then-valid retry, two-consecutive-invalid-submissions ending the loop, a real tool call before submission, the model stopping without submitting, tool-budget exhaustion stopping the loop *before* another provider call, two consecutive malformed tool-call arguments ending the loop, and confirming a legitimate `NotFound` does **not** count toward that 2-strikes cap the way a malformed argument does

**Real bug found and fixed while building this:** none new here — the vote-sync `SECURITY DEFINER` bug above was the only one this session surfaced.

**Caveats on the Agent — read before trusting it against real traffic:**
1. **DNS-rebinding TOCTOU gap in `fetch_url`, documented and left open.** `_validate_host` validates the addresses our own `socket.getaddrinfo()` call returns, but `httpx` resolves DNS again itself when it actually connects. A resolver answering differently between those two lookups (a public IP to our check, a private one moments later to httpx's connection) would slip past this check. Closing it fully needs a transport that pins the connection to the address already validated — not implemented this pass. The redirect-revalidation and pre-check together still block the overwhelming majority of real SSRF attempts (an attacker cannot simply request `169.254.169.254` or redirect to it, both of which are tested). See the module docstring in `core/agent/tools/fetch.py`.
2. **Per-day usage caps (50 drafts/user/day, 20 community submissions/user/day) are NOT implemented.** AI_SPEC §7.3 requires them to live in the database — `st.session_state` resets on a new tab — but no table exists yet for that counter in migrations `0003`–`0005`. `core/agent/limits.py` says so explicitly rather than silently only enforcing the per-draft caps. Needs a small new migration plus a repository method when the UI block picks this up.
3. **`submit_draft`'s JSON-schema parameters include Pydantic's `$defs`/`$ref` for the nested `AnswerKey`.** Same caveat as Gemini's `response_schema` above — untested against live tool-calling APIs, most likely to need a follow-up if a provider's function-calling implementation turns out not to accept refs.

**Verified locally (LLM layer + Agent):** `ruff check .` clean, `mypy --strict` clean across `core/`, `app/`, `scripts/`, `streamlit_app.py` (66 files), `import-linter` **8/8** contracts kept (two new: `agent does not import streamlit`, and the peer-relationship pair `engine does not import agent` / `agent does not import engine`), **175/175 tests passing** (146 unit+agent, 29 integration), `validate_content.py` still passes. CI workflow updated with a dedicated `agent tests` step. `requirements.txt` gained `openai`, `anthropic`, `google-genai`, `httpx`.

**UI** — done 2026-07-30
- [x] Grouped navigation (Practice / Library / Create / Account) — `streamlit_app.py` now builds `st.navigation` from a section dict instead of a flat list; the Inbox nav label shows a live unread count
- [x] Components: `badges.py` (`verification_badge`/`tier_badge`, extracted out of `question_card.py` so `knowledge_card.py` reuses the same badge rather than hand-rolling one), `vote_buttons.py`, `comment_thread.py` (one-level only — never offers a reply button on a reply), `answer_key_view.py` (`answer_key_view` read-only render + `answer_key_editor` one-textarea-per-section editor, both driven by the same `AnswerKey` field list), `grounding_picker.py` (search + multiselect against the knowledge bank, live token-budget meter against `DEFAULT_CAPS.max_grounding_tokens`), `knowledge_card.py`, `confirm_dialog.py` (`confirm_action` — a checkbox-then-button gate, not `st.dialog`, so it composes cleanly inside an `st.expander` without a nested-rerun surprise)
- [x] `3_Knowledge.py` (new) — verified/community/mine tier tabs, votes, comments, private→community share, submit-for-review with `confirm_action`
- [x] `2_Question_Bank.py` reworked — answer-key expander, votes/comments on non-private questions, share and submit-for-review actions added alongside the existing favorite/notes flow
- [x] `4_Author.py` (new) — content-type switch (question/knowledge) drives one session-state dict that resets on switch; one-click and refinement paths side by side, `grounding_picker` feeding `start_*_refinement`, `st.file_uploader` feeding `parse_upload`/`check_upload_count` into the `ToolContext`; the editable draft form is what gets passed as `edited_draft` on every subsequent refinement turn, and is also what actually gets saved — the model's last version is never silently re-substituted for what the user typed
- [x] `5_My_Drafts.py`, `6_Inbox.py` (new) — submission-status list and the read/unread notification list; Inbox only ever calls `mark_read`/`mark_all_read`, matching `NotificationRepository` having no insert method
- [x] `9_Admin.py` rewritten — review queue (approve/reject through `ReviewRepository`'s RPC-backed methods, so a stray non-admin session gets `PermissionDenied` from the database, not a UI-level check), bank management (direct tier promotion and archive, bypassing the request/review flow — an intentional admin power per the original ask), bulk AI authoring (loop of `one_click_question_draft` calls straight into the verified tier), bank-health counts
- [x] `7_Settings.py` — the Phase 1 inline key form replaced with `app/components/api_key_gate.render_key_form()`, so Settings and any future key prompt share one implementation

**Verified locally (UI):** `ruff check .` clean, `mypy --strict` clean across `core/`, `app/`, `scripts/`, `streamlit_app.py` (77 files), `import-linter` 8/8 contracts kept, **175/175 tests still passing** (unchanged — no dedicated UI test suite exists for Streamlit pages in this project, Phase 1 included; pages are exercised manually), `validate_content.py` still passes (40 questions).

**Not done, and why:**
1. **No automated UI tests were written.** This mirrors Phase 1: none of the existing pages (`1_Dashboard.py`, old `2_Question_Bank.py`, `7_Settings.py`) have test coverage either — Streamlit page testing in this project has always been manual-only. Manual smoke testing of the new pages against a live Supabase + a real LLM key has **not** been done in this environment (no live key available — see the LLM layer caveats above); only `ruff`/`mypy --strict`/`import-linter` prove the code is well-typed and correctly wired, not that it behaves correctly against a real backend.
2. **Bulk authoring in `9_Admin.py` is a straight loop with no rate limiting or progress streaming** — acceptable for the "keep batches small" caption it ships with, but not the same as a queued background job.

**Content**
- [x] Old Git-authored knowledge design and its CI validation — already absent; `content/knowledge/` was already an empty directory with no CI step referencing it (grepped `.github/workflows/ci.yml` and found no knowledge-validation step). Docs (`CONTENT_SPEC.md`, `DECISIONS.md` D12) already described the directory as reduced to a seed/export snapshot only. No code changes were needed here.
- [ ] **Seed the verified knowledge bank (14 documents) — deliberately not done.** This requires either hand-writing 14 accurate macro/finance reference documents or running the authoring agent against a real LLM key, neither of which belongs in an automated code-writing pass: fabricating "verified" reference content without a real review step would defeat the entire point of the verified tier. Do this from the running app once a key is available, using `4_Author.py` → admin promotion, or `9_Admin.py`'s bulk tab pattern adapted for knowledge docs (not yet built — only questions have a bulk path).
- [ ] **Grow the question bank past 100 — deliberately not done, same reasoning.** The existing 40-question seed bank is untouched. Bulk authoring in `9_Admin.py` exists and is ready to use once a live key is available.

## Phase 3 — Interview & Evaluation

Not started. See [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#phase-3--interview--evaluation).

- [ ] `prompts/evaluator.v1.md` + `core/engine/evaluator.py`
- [ ] `core/engine/session.py` — interview state machine
- [ ] `prompts/interviewer.v1.md` + `core/engine/interviewer.py`
- [ ] Interview page, Review page
- [ ] Golden evaluation set (`tests/golden/`), including "answer keys unreachable during a turn"

## Phase 4 — Adaptivity & Progress

- [ ] `topic_mastery` triggers + `core/engine/mastery.py`
- [ ] `core/engine/selector.py` — adaptive selection
- [ ] Progress page

## Phase 5 — Depth

- [ ] `pgvector` semantic search over both banks
- [ ] Session coaching synthesis · retry-and-compare · export/import · institution profiles

## Phase 6 — Exploration

Unscheduled. See [IMPLEMENTATION_GUIDE §6](docs/IMPLEMENTATION_GUIDE.md#phase-6--exploration-unscheduled).

---

## Log

| Date | Note |
|---|---|
| 2026-07-28 | Spec finalized (PROJECT_SPEC.md + docs/). Phase 1 implementation started. |
| 2026-07-28 | Phase 1 code complete: models, migrations, RLS, repositories, scripts, 40-question seed bank, auth-gated Streamlit app with Dashboard/Question Bank/Settings/Admin-placeholder, CI workflow. Lint/type/unit checks green locally. Not yet verified against a live Supabase project or a local Postgres for integration/RLS tests — see Caveats above. |
| 2026-07-30 | **Phase 1 deployed and working on Streamlit Community Cloud.** Supabase project live, migrations applied, bank seeded, email+password auth functioning end to end. Caveats 2 and 4 are now resolved by live use; Caveat 3 (RLS suite never executed) still stands. |
| 2026-07-30 | **Roadmap renumbered and Phase 2 respecified.** Six new decisions (D10–D15) covering answer keys, verified-tier semantics, the knowledge bank moving to Postgres, agentic authoring with tools, promotion by clone, and in-app notifications. Rewrote DECISIONS, DATA_SPEC, AI_SPEC, CONTENT_SPEC, ARCHITECTURE, UI_SPEC, IMPLEMENTATION_GUIDE. Old Phase 2 → 3, old Phase 3 split across 2 and 4. No code written. |
| 2026-07-30 | **Phase 2 Step 0 done:** existing Phase 1 RLS suite finally executed (12/12 passing), two harness bugs fixed, no Phase 1 policy defects found. **Phase 2 Schema and Models & repositories done:** migrations `0003`–`0005`, 17 new RLS tests, `AnswerKey`/`KnowledgeDoc`/`Comment`/`ReviewRequest`/`Notification` models with unit tests, and five new/updated repositories (`knowledge`, `comments`, `notifications`, `reviews`, `votes`). Found and fixed a real Phase-1-origin bug along the way: the vote-sync trigger wasn't `SECURITY DEFINER`, so a vote from anyone but the question's own owner/author silently failed to move the denormalized count. 73/73 tests passing, ruff/mypy --strict/import-linter all clean. LLM layer, agent, UI, and content growth are not yet started. |
| 2026-07-30 | **Phase 2 LLM layer and Agent done.** Provider-agnostic message/tool types, error taxonomy, three provider adapters (OpenAI/Anthropic/Gemini) each implementing both `complete_structured` and `complete_with_tools`, a capability-reporting registry, and a versioned prompt loader with three new prompt files. On top of that: a fully SSRF-hardened `fetch_url` tool (39 dedicated tests), `search_knowledge`/`read_knowledge`/`read_upload`, a closed tool registry, per-draft usage caps, and the bounded agent loop itself — which terminates via a synthetic `submit_draft` tool rather than a second structured-output call, so the final draft is schema-validated the same way every other tool call is. One-click and refinement authoring paths wired for both banks. No live API key was available, so no provider adapter has made a real network call — everything is built and tested against documented SDK shapes and a scripted fake provider instead; three specific caveats (Gemini schema shape, DNS-rebinding TOCTOU, missing DB-backed daily counters) are logged above rather than glossed over. 175/175 tests passing, ruff/mypy --strict/import-linter (8/8 contracts) all clean, CI updated. UI and content growth remain. |
| 2026-07-30 | **Phase 2 UI done — Phase 2 functionally complete except two Content seeding tasks.** Grouped navigation with a live Inbox unread-count badge; seven new/reworked shared components (badges extracted for reuse, votes, one-level comment threads, the answer-key read/edit pair, the grounding picker with its live token-budget meter, knowledge cards, a checkbox-then-button confirm gate for the irreversible submit-for-review action); `3_Knowledge.py` (new), `2_Question_Bank.py` reworked with tier tabs/votes/comments/share/submit, `4_Author.py` (new — one-click and agentic refinement side by side for both banks, file uploads feeding the agent's tool context, edits surviving every refinement turn), `5_My_Drafts.py`/`6_Inbox.py` (new), `9_Admin.py` rewritten (review queue against the RPC-backed approve/reject, direct bank management, bulk AI authoring, bank-health counts), and `7_Settings.py` now delegates key entry to `api_key_gate` instead of its own inline form. No UI tests exist for this or any prior page in the project — consistent with the existing pattern, not a new gap — and none of it has been smoke-tested against a live backend/LLM key in this environment. `ruff`/`mypy --strict` (77 files)/`import-linter` (8/8) all clean, 175/175 tests still passing, `validate_content.py` still passes. The old Git-authored knowledge design was already fully absent from the codebase — nothing to delete. Left undone on purpose: seeding the 14-document verified knowledge bank and growing the question bank past 100, both of which need a real LLM key and a human review pass, not another automated code-writing session. |
