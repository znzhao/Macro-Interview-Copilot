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

## 5.3a Agent and tools — `tests/agent/`

No network. `fetch_url` is tested against a local stub server plus a patched resolver.

- **SSRF, exhaustively:** loopback, RFC1918, `169.254.169.254`, CGNAT, multicast, IPv6 equivalents, `file:`/`gopher:`/`data:` schemes, a public URL redirecting to a private one, and **DNS rebinding** — a hostname resolving to a public IP at validation and a private one at connect. Each must raise `ToolBlocked`.
- Size and time caps enforced *while streaming*, not after; a chunked infinite response must not exhaust memory.
- Cap exhaustion returns an incomplete draft, never raises.
- Malformed tool arguments are fed back once; two consecutive failures end the loop cleanly.
- `search_knowledge` run as user A never returns user B's private document — the agent is not a privilege-escalation path.
- **No API key and no fetched URL appears in any log record, tool result, or exception message.**

## 5.3b Answer-key guardrail — `tests/unit/test_answer_key.py`

[D10](DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose) is only real if it is tested. Assert: >8 bullets rejected · >240 characters rejected · embedded newline rejected · unknown section rejected (`extra="forbid"`) · the SQL CHECK rejects the same payloads the Pydantic model does, so no write path is softer than another.

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

## Phase 2 — Content Creation & Community

> **Renumbered.** This phase did not exist when the roadmap was written; it absorbs the LLM plumbing formerly in Phase 2 and the community/admin half of Phase 3, and pushes interview and evaluation to Phase 3. The reason is sequencing, not preference: **a 40-question bank is too thin for the interviewer to be worth using**, and an authoring pipeline is the only realistic way to reach a few hundred. Build the content engine, then the thing that consumes content.

**Ships:** BYO-key flow with validation · LLM adapters for all three providers, structured output **and** tool use · the agentic authoring loop with its four tools and safety bounds · answer keys · the knowledge bank as a three-tier Postgres bank · community tier with ±1 voting, one-level comments, and reports · review-request submission and admin promotion by clone · the notification inbox · the full Admin page.

**Done when:**
- A user with no API key can browse both banks, vote, and comment; with a key, they can generate a question and answer key **in two clicks** and save it privately.
- A refinement conversation grounded in a selected knowledge document and a fetched URL produces a materially different draft, and the user's manual edits survive the next turn.
- `fetch_url` **refuses** loopback, RFC1918, and link-local addresses, including via redirect and via DNS rebinding — asserted by tests, not by inspection.
- Answer keys that violate the shape limits are rejected at the Pydantic layer **and** at the database CHECK.
- A user shares a question to community; a second user finds it, downvotes it, comments, and gets a reply notification; the author submits it for review; an admin approves it; the verified clone appears while the original stays with the author; the author sees the outcome in their Inbox.
- The author flips their original back to private and the verified clone **remains public** — the behavior the pre-submission warning promised.
- RLS isolation tests pass for `knowledge_docs`, `comments`, `review_requests`, and `notifications`, including the "cannot forge a notification" case.

## Phase 3 — Interview & Evaluation

**Ships:** `evaluator.v1` with the anchored rubric · interview state machine with persistence · Interview and Review pages · single-question practice.

**Done when:** a user completes a 5-question interview with follow-ups; every answer is persisted before evaluation; an **induced API failure loses no data**; the golden set meets the §5.4 thresholds; answer keys are provably unreachable during an active turn.

## Phase 4 — Adaptivity & Progress

**Ships:** `topic_mastery` triggers · adaptive selector · Progress page with per-dimension trends.

**Done when:** after 15 evaluated answers the system **measurably** concentrates selection on the user's weakest topics.

## Phase 5 — Depth

**Ships:** `pgvector` semantic search over both banks · session coaching synthesis · retry-and-compare · export/import · institution-specific interview profiles.

## Phase 6 — Exploration (unscheduled)

Voice interview · FRED integration for live-data questions · news-driven question generation · research-paper RAG · multi-agent interview panel · resume analysis.

---

# 7. Build Order Within Phase 2

Dependencies are real here; this order keeps each step verifiable before the next depends on it.

**Schema first** — everything else writes to it.
1. Migration `0003`: drop `verified_needs_source`; add `answer_key` + `answer_key_is_valid()`, `downvotes`, `source_question_id`; widen votes to ±1.
2. Migration `0004`: `knowledge_docs`, `knowledge_votes`, `comments`, `review_requests`, `notifications`, new enums.
3. Migration `0005`: RLS for all new tables, `can_view_content()`, the promotion procedure, and the notification triggers.
4. **RLS isolation tests before any UI.** Retrofitting them is how policy gaps ship — and [PHASE_TRACKER.md](../PHASE_TRACKER.md) still lists the *existing* RLS suite as never having been executed. Run that first, against a real Postgres, before stacking new policies on top of unverified ones.

**Models and data access.**
5. `AnswerKey`, `KnowledgeDoc`, `Comment`, `Notification`, `ReviewRequest` + unit tests. The `AnswerKey` limit tests matter more than they look — they are [D10](DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose)'s enforcement.
6. Repositories: `knowledge`, `comments`, `notifications`, `reviews`, `votes`, with integration tests.

**LLM layer** — the largest item.
7. `core/llm/base.py` message and tool types, `registry.py` capability reporting, `api_key_gate.py`.
8. `complete_structured` for all three providers, against recorded fixtures.
9. `complete_with_tools` for one provider end to end, then the other two against the *same* shared scenario table.

**Agent.**
10. `core/agent/tools/fetch.py` **first, with its SSRF tests**, before anything can call it.
11. `tools/knowledge.py`, `tools/uploads.py`, `limits.py`.
12. `loop.py`, then `authoring.py` — one-click path first, refinement second.

**UI**, once the layers beneath are green.
13. Grouped navigation; `verification_badge`, `vote_buttons`, `comment_thread`, `answer_key_view`.
14. Knowledge page, Questions page rework with tier tabs.
15. Author page: one-click, then grounding, then refinement.
16. Inbox, My Drafts.
17. Admin: review queue → reports → bank management → bulk authoring → bank health.
18. Seed the verified knowledge bank ([CONTENT_SPEC §7.4](CONTENT_SPEC.md#74-initial-coverage)); grow the question bank with the tool you just built.

---

# 8. Deploying Phase 2

Phase 2 code is complete (Schema, Models & repositories, LLM layer, Agent, UI — see [PHASE_TRACKER.md](../PHASE_TRACKER.md)). This is a single checklist covering your whole deployment lifecycle: the Phase 1 items you already did are checked off for context, and everything unchecked is what's left to do now. Work top to bottom — each step assumes the previous one succeeded.

## 8.0 Already done (Phase 1 — for reference, nothing to run here)

- [x] Supabase project created ([DEPLOYMENT.md §1](DEPLOYMENT.md#1-create-the-supabase-project))
- [x] `0001_init.sql` and `0002_rls.sql` applied ([DEPLOYMENT.md §2](DEPLOYMENT.md#2-create-the-schema))
- [x] Question bank seeded — 40 verified questions ([DEPLOYMENT.md §3](DEPLOYMENT.md#3-seed-the-question-bank))
- [x] Auth configured — URLs, "Confirm email" off ([DEPLOYMENT.md §4](DEPLOYMENT.md#4-configure-authentication))
- [x] `.streamlit/secrets.toml` created locally ([DEPLOYMENT.md §5](DEPLOYMENT.md#5-create-your-local-secrets-file))
- [x] Verified running locally ([DEPLOYMENT.md §6](DEPLOYMENT.md#6-run-it-locally)) and made yourself admin
- [x] Deployed to Streamlit Community Cloud ([DEPLOYMENT.md §7](DEPLOYMENT.md#7-deploy-to-streamlit-community-cloud))

You will touch **none** of the above again for this upgrade — no new Supabase project, no auth changes, no secrets changes. The only thing all of it gave you that you need now is a working `DATABASE_URL` in your local `.env` from §3.

## 8.1 What is — and isn't — changing

| Changes | Doesn't change |
|---|---|
| 3 new SQL migrations (`0003`–`0005`) — 5 new tables, altered `questions`/`question_votes`, new RLS policies and procedures | Your Supabase project, its URL, its `anon` key |
| `requirements.txt` gained `openai`, `anthropic`, `google-genai`, `httpx` | `.streamlit/secrets.toml` / Streamlit Cloud secrets — **no new secrets are needed** |
| 4 new pages (Knowledge, Author, My Drafts, Inbox) and a reworked Admin page | Auth configuration (§4 of DEPLOYMENT.md) — sign-in works exactly as before |
| Nothing writes an LLM key to the database or to Streamlit secrets at any point | |

The important point on that last row: every user (including you) types their own OpenAI/Anthropic/Gemini key into **Settings** *after* signing in, and it lives only in that browser tab's session state ([D4](DECISIONS.md#d4--byo-llm-api-key-session-memory-only)). There is nothing to add to Supabase or Streamlit Cloud for this — if you don't have an LLM key handy yet, everything except the Author page and Admin's bulk-authoring tab still works.

## 8.2 Apply migrations `0003`–`0005` — step by step

Same tool, same pattern as before, just three more files. Reuses the `.env` with `DATABASE_URL` you already have from §3 above.

- [x] **Step 1 — pull the latest code.** Confirm these three files exist:
  ```
  core/db/migrations/0003_content_governance.sql
  core/db/migrations/0004_knowledge_and_social.sql
  core/db/migrations/0005_phase2_rls.sql
  ```
- [x] **Step 2 — confirm `.env` still points at the right database.** Open `.env` at the repo root and check `DATABASE_URL` is the same Session pooler connection string you used in [DEPLOYMENT.md §3](DEPLOYMENT.md#3-seed-the-question-bank). If that file is missing (new machine, fresh clone), redo that step first — copy `.env.example` to `.env`, paste in the connection string with your database password substituted in.
- [x] **Step 3 — run the migration script:**
  ```bash
  ./.venv/Scripts/python.exe scripts/apply_migrations.py
  ```
- [x] **Step 4 — check the output line by line.** You should see exactly this shape:
  ```
  skip  0001_init (already applied)
  skip  0002_rls (already applied)
  apply 0003_content_governance
  apply 0004_knowledge_and_social
  apply 0005_phase2_rls
  Done.
  ```
  If you see `skip` for all five, migrations were already applied — nothing more to do in this section. If you see `apply` for all five and no errors, it worked. Anything else, see the two boxes below.

> **If Step 4 instead shows an error like `type "question_tier" already exists`:** this means `0001`/`0002` were applied manually via the SQL Editor back in Phase 1 (exactly what [DEPLOYMENT.md §2](DEPLOYMENT.md#2-create-the-schema) told you to do) and were never recorded in `schema_migrations`, so the script tried to redo them. Fix once — compute the file's **real** SHA-256 and record that, not a placeholder string, since the script hard-fails on a checksum mismatch by design (that's what stops anyone from silently editing an applied migration):
> ```bash
> ./.venv/Scripts/python.exe -c "
> import hashlib
> from pathlib import Path
> for name in ['0001_init', '0002_rls']:
>     p = Path('core/db/migrations') / f'{name}.sql'
>     print(f\"insert into schema_migrations (version, checksum) values ('{name}', '{hashlib.sha256(p.read_text(encoding='utf-8').encode('utf-8')).hexdigest()}') on conflict (version) do nothing;\")
> "
> ```
> Paste the two `insert` statements this prints into the Supabase SQL Editor and run them. Then re-run Step 3. This time it should `skip` both and move straight to applying `0003`–`0005`.
>
> **If you already ran the version of this guide that used `'applied-manually'` as the checksum:** that value doesn't match the real file hash, so Step 3 now fails with `FATAL: ... checksum no longer matches` instead of `already exists`. Same fix — run the command above, but change `on conflict (version) do nothing` to `on conflict (version) do update set checksum = excluded.checksum` so it overwrites the bad placeholder instead of skipping.

> **If you'd rather not run a local script at all** (no working Postgres tooling, or you just prefer the SQL Editor): open each of `0003_content_governance.sql`, `0004_knowledge_and_social.sql`, `0005_phase2_rls.sql` in order, paste the **entire file** into a new SQL Editor query, click **Run**, one file at a time.
> - On `0004`, Supabase will show the same *"creates tables without enabling Row Level Security"* warning as `0001` did — choose **Run and enable RLS**, same reasoning as [DEPLOYMENT.md §2's note](DEPLOYMENT.md#2-create-the-schema): `0005`'s own `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` lines are harmless no-ops once it runs after.
> - Afterward, record all three with their real checksums, the same way as above but for the three new files:
>   ```bash
>   ./.venv/Scripts/python.exe -c "
>   import hashlib
>   from pathlib import Path
>   for name in ['0003_content_governance', '0004_knowledge_and_social', '0005_phase2_rls']:
>       p = Path('core/db/migrations') / f'{name}.sql'
>       print(f\"insert into schema_migrations (version, checksum) values ('{name}', '{hashlib.sha256(p.read_text(encoding='utf-8').encode('utf-8')).hexdigest()}') on conflict (version) do nothing;\")
>   "
>   ```

## 8.3 Verify the migration

- [ ] **Table count and RLS.** Run in the Supabase SQL Editor:
  ```sql
  select tablename, rowsecurity
  from pg_tables
  where schemaname = 'public'
  order by tablename;
  ```
  Expect **16 rows** (the 11 from Phase 1 plus `comments`, `knowledge_docs`, `knowledge_votes`, `notifications`, `review_requests`). All `rowsecurity = true` except `schema_migrations` — same rule as [DEPLOYMENT.md §2](DEPLOYMENT.md#2-create-the-schema).

- [ ] **Functions and the vote-sync fix.** Run:
  ```sql
  select proname, prosecdef
  from pg_proc
  where proname in (
    'approve_review_request', 'reject_review_request',
    'sync_question_upvotes', 'sync_knowledge_votes', 'notify_on_comment'
  );
  ```
  Expect all 5 rows, `prosecdef = true` on every one. `prosecdef` is Postgres's internal column name for `SECURITY DEFINER`. If `sync_question_upvotes.prosecdef` is `false`, `0003` didn't apply — this is the exact bug described in [PHASE_TRACKER.md](../PHASE_TRACKER.md)'s "Real bug found and fixed" note: votes from anyone but a question's own author would silently stop moving the upvote count.

## 8.4 Install dependencies and redeploy

- [ ] **Local:**
  ```bash
  ./.venv/Scripts/pip.exe install -r requirements.txt
  ```
  Pulls in `openai`, `anthropic`, `google-genai`, `httpx` — needed for Settings, Author, and Admin to import at all.
- [ ] **Streamlit Community Cloud:** push to `main`. A connected app auto-redeploys and reinstalls `requirements.txt` (watch **Manage app**'s log for `pip install` output). If it doesn't pick it up within a couple minutes, use **⋮ → Reboot app**. No secrets change needed — see §8.1.

## 8.5 Smoke test

Once redeployed (or running locally), walk through the whole loop once:

- [ ] Sign in. Sidebar now shows grouped sections — **Practice**, **Library** (Question Bank, Knowledge), **Create** (Author, My Drafts), **Account** (Inbox, Settings, Admin if you're an admin).
- [ ] **Settings** → add your own LLM key (OpenAI, Anthropic, or Gemini) → **Save and test key** → expect "Key is valid."
- [ ] **Author** → "Question" → fill module/topic/difficulty → **Generate now (one click)** → expect a draft with a bulleted answer key, never prose (enforced twice — Pydantic and a DB `CHECK`).
- [ ] **Save to my private bank** → **Question Bank** → private-tier view → confirm it's there, with vote/comment controls hidden (private content has neither).
- [ ] On that question: **Share with community**, then **Submit for review** (confirms via the permanent-submission warning — check the box, click through).
- [ ] **My Drafts** → confirm the submission shows `pending`.
- [ ] As an admin: **Admin → Review queue** → **Approve → verified** → expect a success message.
- [ ] **Question Bank → Verified** → confirm the clone appears with `verification_level = ai_generated`. **Inbox** (as the submitter) → expect a `submission_approved` notification, unread marker, and "Inbox (1)" in the sidebar.
- [ ] Repeat briefly for **Knowledge** (Author → "Knowledge document") — identical flow, both banks exercised.

If every box above checks out, Phase 2 is live and verified end-to-end — not just "code complete." Expect the Author step to be the first time any of the three LLM provider adapters has ever made a real network call in this project (see the "No live API key was available" caveat in [PHASE_TRACKER.md](../PHASE_TRACKER.md)'s LLM layer section) — if it fails with a schema or parsing error rather than an auth/network error, that caveat is the first place to look, particularly on Gemini (caveat 2 there, on `response_schema` shape).

## 8.6 What you do *not* need to do

- [x] ~~Seed the knowledge bank~~ / ~~grow the question bank past 40~~ — you're doing both manually once this is live. Tooling (Author page, Admin's bulk-authoring tab) is ready whenever you want it.
- [x] ~~Reconfigure Supabase Auth~~ — §4 of DEPLOYMENT.md is untouched by Phase 2.
- [x] ~~Set up per-day usage caps~~ — not yet implemented (see [PHASE_TRACKER.md](../PHASE_TRACKER.md)'s Agent caveats); nothing to configure because the enforcement itself doesn't exist yet.
