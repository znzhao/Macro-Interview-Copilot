# Data Specification

Postgres schema, domain models, repository contracts, authorization, migrations, and data rights.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DECISIONS.md](DECISIONS.md)

**Conventions.** All timestamps are `timestamptz` in UTC. All primary keys are `uuid` defaulting to `gen_random_uuid()` unless stated. All tables have RLS enabled (§6).

---

# 1. Enums

```sql
CREATE TYPE question_tier      AS ENUM ('verified', 'community', 'private');
CREATE TYPE question_status    AS ENUM ('draft', 'published', 'archived', 'flagged');
CREATE TYPE difficulty_level   AS ENUM ('easy', 'medium', 'hard', 'expert');
CREATE TYPE frequency_level    AS ENUM ('low', 'medium', 'high', 'very_high');
CREATE TYPE verification_level AS ENUM (
  'verified_interview',
  'multiple_independent_reports',
  'official_publication',
  'official_job_material',
  'synthesized_from_official_topics',
  'ai_generated',
  'user_submitted'
);
CREATE TYPE experience_level   AS ENUM ('entry', 'intermediate', 'advanced');
CREATE TYPE session_status     AS ENUM ('active', 'completed', 'abandoned');
CREATE TYPE interviewer_mode   AS ENUM ('hedge_fund', 'central_bank', 'ifi', 'sell_side');

-- Added in Phase 2.
CREATE TYPE review_status      AS ENUM ('pending', 'approved', 'rejected', 'withdrawn');
CREATE TYPE content_kind       AS ENUM ('question', 'knowledge');
CREATE TYPE notification_kind  AS ENUM (
  'submission_approved',
  'submission_rejected',
  'comment_on_content',
  'reply_to_comment'
);
```

**`question_tier` and `question_status` are reused verbatim for knowledge documents.** The names keep the `question_` prefix for migration continuity — renaming a live enum type is churn with no benefit — but they are the governance vocabulary for *both* banks ([D12](DECISIONS.md#d12--the-knowledge-base-is-a-three-tier-postgres-bank)). Read them as `content_tier` and `content_status`.

**`tier` and `verification_level` are independent axes.** `tier` is *governance* — who may edit it and who may see it. `verification_level` is *provenance* — where the content actually came from. A community-tier question can legitimately be `verified_interview` if the submitter supplied a real source, and a verified-tier question can legitimately be `ai_generated`.

> Since [D11](DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance) dropped the source requirement on the verified tier, **`verification_level` is now the only signal of provenance anywhere in the system.** It is not optional metadata. Every surface that renders content renders this badge ([UI_SPEC §4](UI_SPEC.md#4-visual-conventions)).

---

# 2. `profiles`

Extends `auth.users`. Created by a trigger on signup.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | FK → `auth.users(id)` ON DELETE CASCADE |
| `display_name` | `text` | |
| `target_roles` | `text[]` | e.g. `{'global_macro_hf','imf_economist'}` |
| `experience_level` | `experience_level` | default `'intermediate'` |
| `preferred_provider` | `text` | `'openai' \| 'anthropic' \| 'gemini'`, nullable |
| `preferred_model` | `text` | nullable |
| `is_admin` | `boolean` | default `false`; grants Admin page access |
| `created_at`, `updated_at` | `timestamptz` | |

> **Never** store `api_key` here or anywhere else ([D4](DECISIONS.md#d4--byo-llm-api-key-session-memory-only)).

---

# 3. `questions`

One table for all three tiers ([D5](DECISIONS.md#d5--postgres-is-source-of-truth-for-all-question-tiers)).

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `ref` | `text` UNIQUE | Human-readable: `Q0001` for verified (sequence-assigned), `C-<short>` for community |
| `tier` | `question_tier` | NOT NULL |
| `status` | `question_status` | NOT NULL, default `'draft'` |
| `module` | `text` | NOT NULL, controlled vocabulary (§9) |
| `topic` | `text` | NOT NULL, controlled vocabulary (§9) |
| `question` | `text` | NOT NULL, length 20–1200 |
| `difficulty` | `difficulty_level` | NOT NULL |
| `frequency` | `frequency_level` | nullable — unknown for most community questions |
| `target_roles` | `text[]` | NOT NULL default `'{}'` |
| `institutions` | `text[]` | NOT NULL default `'{}'` |
| `verification_level` | `verification_level` | NOT NULL |
| `source_description` | `text` | nullable |
| `source_url` | `text` | Required when `tier='verified'` |
| `secondary_sources` | `jsonb` | `[{description, url}]`, default `'[]'` |
| `follow_up_questions` | `text[]` | Seed follow-ups; the LLM may generate others |
| `answer_key` | `jsonb` | Structured answer key, `'{}'` when absent. Shape and limits in §3.3 ([D10](DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose)) |
| `author_id` | `uuid` | FK → `profiles(id)` ON DELETE SET NULL. NULL for seeded verified. |
| `owner_id` | `uuid` | FK → `profiles(id)`. Required when `tier='private'`. |
| `source_question_id` | `uuid` | FK self, ON DELETE SET NULL. Set on a verified clone, pointing at the community original ([D14](DECISIONS.md#d14--promotion-to-verified-clones-the-row)) |
| `upvotes` | `integer` | denormalized count, default 0, trigger-maintained |
| `downvotes` | `integer` | denormalized count, default 0, trigger-maintained |
| `search_tsv` | `tsvector` | GENERATED from `question`, `module`, `topic`, `institutions` |
| `created_at`, `updated_at` | `timestamptz` | |

## 3.1 Constraints

```sql
CONSTRAINT private_needs_owner
  CHECK (tier <> 'private' OR owner_id IS NOT NULL),
CONSTRAINT question_length
  CHECK (char_length(question) BETWEEN 20 AND 1200),
CONSTRAINT answer_key_shape
  CHECK (answer_key_is_valid(answer_key)),
CONSTRAINT clone_is_verified
  CHECK (source_question_id IS NULL OR tier = 'verified')
```

> `verified_needs_source` was **dropped** in Phase 2 — see [D11](DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance). It made AI-authored questions permanently un-promotable, deadlocking the admin queue. The anti-fabrication rules that forbid *inventing* a source are unchanged and still absolute; only the requirement to *have* one is gone.

`answer_key_is_valid` is an `IMMUTABLE` SQL function enforcing §3.3. It lives in the schema rather than in Python because [D10](DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose)'s guardrail is only real if no write path can bypass it.

## 3.3 Answer key shape

```json
{
  "framework":          ["bullet", "bullet"],
  "mechanism":          ["bullet"],
  "indicators":         ["bullet"],
  "market_implication": ["bullet"],
  "common_traps":       ["bullet"]
}
```

Rules, enforced by both `answer_key_is_valid` and the Pydantic `AnswerKey` model:

- Exactly these five keys, or the empty object `{}`. No extra keys.
- Each value is an array of **0–8 strings**.
- Each string is **1–240 characters** and contains **no newline**.
- An empty array is legal; a section may be genuinely unknown.

**These limits are the guardrail, not formatting preference.** Eight short bullets cannot be recited as an interview answer — the candidate still has to construct the argument, which is the skill being trained. Relaxing the length cap re-creates the model-answer library the product exists not to be. The four content sections map onto the four *content* scoring dimensions; Communication has no section because it is a property of delivery and cannot be pre-written.

## 3.2 Indexes

```sql
CREATE INDEX questions_tsv_idx        ON questions USING GIN (search_tsv);
CREATE INDEX questions_institutions_idx ON questions USING GIN (institutions);
CREATE INDEX questions_roles_idx      ON questions USING GIN (target_roles);
CREATE INDEX questions_browse_idx     ON questions (tier, status, module, topic);
CREATE INDEX questions_trgm_idx       ON questions USING GIN (question gin_trgm_ops);
```

Requires `pg_trgm`. The trigram index backs the typo-tolerant fallback in [CONTENT_SPEC §5.1](CONTENT_SPEC.md#51-level-1--full-text-v1).

---

# 4. Interview Data

## 4.1 `interview_sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `user_id` | `uuid` | FK, NOT NULL |
| `mode` | `interviewer_mode` | NOT NULL |
| `institution` | `text` | nullable, e.g. `'Brevan Howard'` |
| `config` | `jsonb` | `{planned_turns, difficulty_target, modules[], adaptive: bool, seed}` |
| `status` | `session_status` | NOT NULL |
| `overall_score` | `smallint` | 0–100, NULL until completed |
| `started_at`, `ended_at` | `timestamptz` | |

`config.seed` makes non-adaptive selection reproducible, which is what allows the selector to be tested deterministically.

## 4.2 `interview_turns`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `session_id` | `uuid` | FK ON DELETE CASCADE |
| `ordinal` | `integer` | 1-based order within the session |
| `question_id` | `uuid` | FK, NULL for AI-generated follow-ups |
| `question_text` | `text` | NOT NULL — denormalized snapshot |
| `is_followup` | `boolean` | default false |
| `parent_turn_id` | `uuid` | FK self; NULL for seed questions |
| `answer_text` | `text` | nullable until answered |
| `answer_seconds` | `integer` | nullable |
| `created_at`, `answered_at` | `timestamptz` | |

`UNIQUE (session_id, ordinal)` — this is also the idempotency guard against double form submits.

> **Why `question_text` is denormalized.** A stored evaluation must stay interpretable even if the source question is later edited, archived, or its author's account is deleted. **Never render a past turn by joining to `questions`.** The snapshot is the record of what was actually asked.

## 4.3 `evaluations`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `turn_id` | `uuid` UNIQUE | FK ON DELETE CASCADE |
| `user_id` | `uuid` | FK — denormalized for RLS and fast aggregation |
| `score_framework` | `smallint` | 0–4 |
| `score_logic` | `smallint` | 0–4 |
| `score_evidence` | `smallint` | 0–4 |
| `score_market` | `smallint` | 0–4 |
| `score_communication` | `smallint` | 0–4 |
| `total_score` | `smallint` | 0–100, computed in Python, stored |
| `justifications` | `jsonb` | one sentence per dimension |
| `strengths` | `text[]` | |
| `gaps` | `text[]` | |
| `improved_outline` | `text` | **Structural skeleton only — never a model answer** |
| `suggested_readings` | `text[]` | knowledge-base slugs |
| `model` | `text` | e.g. `claude-sonnet-5` |
| `prompt_version` | `text` | e.g. `evaluator.v1` |
| `raw_response` | `jsonb` | full structured output, for debugging and re-scoring |
| `created_at` | `timestamptz` | |

CHECK each dimension `BETWEEN 0 AND 4`. Scoring semantics: [AI_SPEC §3](AI_SPEC.md#3-evaluation-framework).

---

# 5. Supporting Tables

## 5.1 `topic_mastery`

Rolling per-user, per-topic skill estimate. Maintained by a trigger on `evaluations` insert.

| Column | Type | Notes |
|---|---|---|
| `user_id` | `uuid` | PK part 1 |
| `module` | `text` | PK part 2 |
| `topic` | `text` | PK part 3 |
| `attempts` | `integer` | |
| `ewma_framework` … `ewma_communication` | `real` | one per dimension, 0–4 |
| `ewma_total` | `real` | 0–100 |
| `last_practiced_at` | `timestamptz` | |

> **This table is a cache, not a source of truth.** It must be fully recomputable from `evaluations` by `scripts/`, and an integration test asserts the trigger result matches a from-scratch recomputation. Math: [AI_SPEC §5.2](AI_SPEC.md#52-mastery-update-ewma).

## 5.2 `question_votes`

`(question_id, user_id)` composite PK, `value smallint CHECK (value IN (-1, 1))`, `created_at`, `updated_at`. A trigger maintains both `questions.upvotes` and `questions.downvotes`.

Changing your mind is an `UPDATE` of the existing row, not a second insert — the composite PK guarantees one vote per user per question. Removing a vote deletes the row.

> **Dislikes never hide anything.** A dislike is a quality signal that sorts content down and surfaces it in the admin's low-quality view. Hiding is driven only by `question_reports` (§5.3), which carries a *reason*. Keeping them separate is what stops five accounts from burying a legitimate question, and it gives the admin queue two genuinely different signals instead of one ambiguous number.

## 5.3 `question_reports`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `question_id`, `reporter_id` | `uuid` | FK |
| `reason` | `text` | `inaccurate` / `no_source` / `duplicate` / `offensive` / `other` |
| `detail` | `text` | nullable |
| `status` | `text` | `open` / `resolved` / `dismissed` |
| `created_at`, `resolved_at` | `timestamptz` | |

Three open reports auto-set `questions.status = 'flagged'` via trigger, hiding the question from browse and selection until an admin acts. See [CONTENT_SPEC §3](CONTENT_SPEC.md#3-moderation).

## 5.4 `notes` and `favorites`

- `notes` — `(id, user_id, question_id, content, created_at, updated_at)`, `UNIQUE (user_id, question_id)`.
- `favorites` — `(user_id, question_id, created_at)`, composite PK.

## 5.5 `schema_migrations`

`(version text PK, applied_at timestamptz, checksum text)`.

## 5.6 `knowledge_docs`

The knowledge bank ([D12](DECISIONS.md#d12--the-knowledge-base-is-a-three-tier-postgres-bank)). Governance mirrors `questions` exactly — same tiers, same statuses, same voting, commenting, reporting, submission, promotion, and soft-delete rules. Anything true of a question's *governance* is true of a knowledge document.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `slug` | `text` UNIQUE | Stable join key for `evaluations.suggested_readings`. Immutable after insert. |
| `tier` | `question_tier` | NOT NULL |
| `status` | `question_status` | NOT NULL, default `'draft'` |
| `title` | `text` | NOT NULL, 3–200 chars |
| `summary` | `text` | NOT NULL, ≤ 500 chars — shown on cards and in agent tool results |
| `body_md` | `text` | NOT NULL, ≤ 200,000 chars. Markdown. |
| `modules` | `text[]` | NOT NULL default `'{}'`, controlled vocabulary (§9) |
| `topics` | `text[]` | NOT NULL default `'{}'`, controlled vocabulary (§9) |
| `related_slugs` | `text[]` | Cross-link graph. Not an FK — a slug may be archived. |
| `verification_level` | `verification_level` | NOT NULL — same provenance axis as questions |
| `source_url` | `text` | nullable |
| `origin` | `text` | `'uploaded'` / `'ai_generated'` / `'seeded'` |
| `author_id`, `owner_id` | `uuid` | FK → `profiles(id)`, same semantics as `questions` |
| `source_doc_id` | `uuid` | FK self — set on a verified clone |
| `upvotes`, `downvotes` | `integer` | trigger-maintained |
| `token_estimate` | `integer` | ≈ `char_length(body_md) / 4`, generated. Powers the grounding budget meter in the authoring UI without re-tokenizing on every render. |
| `search_tsv` | `tsvector` | GENERATED from `title`, `summary`, `modules`, `topics` |
| `created_at`, `updated_at` | `timestamptz` | |

Constraints mirror §3.1: `private_needs_owner`, `clone_is_verified`, plus `slug ~ '^[a-z0-9_]{3,64}$'`.

> **`slug` is never reused and a doc is never hard-deleted.** A stored `evaluations.suggested_readings` may point at a slug for years. Admin "delete" sets `status='archived'`; the row stays resolvable so historical feedback remains interpretable. Same reasoning as `interview_turns.question_text` (§4.2).

`knowledge_votes` mirrors `question_votes` exactly: `(doc_id, user_id)` PK, `value smallint CHECK (value IN (-1,1))`.

## 5.7 `review_requests`

An author asking an admin to promote their content to `verified`. A distinct record rather than a status flag, because the author must be notified of the outcome and the decision must be auditable ([D14](DECISIONS.md#d14--promotion-to-verified-clones-the-row)).

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `kind` | `content_kind` | `'question'` or `'knowledge'` |
| `question_id` | `uuid` | FK, NULL when `kind='knowledge'` |
| `doc_id` | `uuid` | FK, NULL when `kind='question'` |
| `requester_id` | `uuid` | FK → `profiles(id)`, NOT NULL |
| `note` | `text` | optional message to the admin |
| `status` | `review_status` | NOT NULL default `'pending'` |
| `decided_by` | `uuid` | FK → `profiles(id)`, NULL until decided |
| `decision_note` | `text` | shown to the author in their Inbox — required on rejection |
| `promoted_id` | `uuid` | the verified clone created on approval |
| `created_at`, `decided_at` | `timestamptz` | |

```sql
CONSTRAINT exactly_one_target CHECK (num_nonnulls(question_id, doc_id) = 1),
CONSTRAINT target_matches_kind CHECK (
  (kind = 'question'  AND question_id IS NOT NULL) OR
  (kind = 'knowledge' AND doc_id      IS NOT NULL)
)
```

A partial unique index `(question_id) WHERE status = 'pending'` (and the same for `doc_id`) prevents an author from queuing the same item twice.

**Approval is one transaction:** insert the verified clone, set `status='approved'` and `promoted_id`, emit the notification. A partial failure that promotes without notifying, or notifies without promoting, is a bug an integration test covers.

## 5.8 `comments`

One-level threading — top-level comments plus a single reply depth. Enough for a real conversation; no recursive rendering.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `kind` | `content_kind` | |
| `question_id`, `doc_id` | `uuid` | FK, exactly one non-null (same CHECK pair as §5.7) |
| `parent_id` | `uuid` | FK self, NULL for top-level |
| `author_id` | `uuid` | FK → `profiles(id)` ON DELETE SET NULL |
| `body` | `text` | NOT NULL, 1–4000 chars |
| `is_deleted` | `boolean` | default false — tombstone, see below |
| `created_at`, `updated_at` | `timestamptz` | |

```sql
-- Depth is capped structurally: a reply's parent must itself be top-level.
CONSTRAINT no_deep_nesting CHECK (parent_id IS NULL OR NOT is_reply_to_reply(parent_id))
```

- **Deletion is a tombstone.** `is_deleted = true` blanks the rendered body to *"[removed]"* but keeps the row, so replies underneath do not vanish and the thread stays readable. Author or admin may delete.
- Comments are only permitted on content that is **published and non-private**. There is nobody to talk to on a private draft.
- A comment fires a `comment_on_content` notification to the content's author; a reply fires `reply_to_comment` to the parent comment's author. Self-notifications are suppressed in the trigger.

## 5.9 `notifications`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `user_id` | `uuid` | FK, NOT NULL — the recipient |
| `kind` | `notification_kind` | |
| `title` | `text` | NOT NULL, pre-rendered |
| `body` | `text` | nullable — e.g. an admin's rejection note |
| `link_kind` | `content_kind` | nullable, for deep-linking |
| `link_id` | `uuid` | nullable |
| `read_at` | `timestamptz` | NULL = unread |
| `created_at` | `timestamptz` | |

Index `(user_id, read_at, created_at DESC)` — the unread badge count runs on every page load and must never table-scan.

> **Notifications are emitted by triggers, not by application code.** A notification written in Python is a notification some future code path forgets to write. Putting it on the same transaction as the event makes "approved but never told" structurally impossible.

Rows are pruned by a scheduled job at 90 days, or 500 per user, whichever comes first.

---

# 6. Authentication & Authorization

## 6.1 Flow

Supabase Auth with magic link and Google OAuth. `streamlit_app.py` gates access; unauthenticated visitors get a landing page with login and a read-only preview of the verified bank. `core/auth.py` exposes `current_user() -> AuthUser | None` and refreshes the session token before expiry.

## 6.2 Row Level Security

**RLS is enabled on every table. Policies are the authorization boundary; the UI is not.** The app uses the anon key plus the user's JWT so that policies actually apply. The service-role key is never present in the Streamlit app — it bypasses all RLS.

| Table | Select | Insert / Update / Delete |
|---|---|---|
| `profiles` | own row | own row |
| `questions` | `(tier IN ('verified','community') AND status='published')` OR `owner_id = auth.uid()` OR `is_admin()` | insert requires `author_id = auth.uid()`; update/delete by owner or admin; setting `tier='verified'` requires `is_admin()` |
| `interview_sessions` | `user_id = auth.uid()` | `user_id = auth.uid()` |
| `interview_turns` | via join to owning session | via join to owning session |
| `evaluations`, `notes`, `favorites`, `topic_mastery` | `user_id = auth.uid()` | `user_id = auth.uid()` |
| `question_votes`, `knowledge_votes` | all | own row only; target must be published and non-private |
| `question_reports` | own reports or `is_admin()` | insert own; update admin only |
| `knowledge_docs` | same predicate as `questions` | same as `questions`; `tier='verified'` requires `is_admin()` |
| `review_requests` | `requester_id = auth.uid()` OR `is_admin()` | insert own, and only for content you own; update `is_admin()` only |
| `comments` | target is visible to you (§6.3) | insert own on published non-private targets; update own body; delete (tombstone) own or `is_admin()` |
| `notifications` | `user_id = auth.uid()` | **no client insert** — trigger-written only; update limited to `read_at` |

`is_admin()` is a `SECURITY DEFINER` function reading `profiles.is_admin`.

## 6.3 The three policies most likely to be wrong

RLS is the authorization boundary, and three of these carry real leak risk. Each gets explicit isolation tests before the feature is considered done.

1. **`interview_turns`** has no `user_id` column, so its policy joins through `interview_sessions`. Longstanding, already covered.

2. **`comments` visibility is derived, not owned.** Whether you may read a comment depends on whether you may read its *parent content*, which differs by `kind`. Implemented as a `SECURITY DEFINER` helper `can_view_content(kind, id)` used by every comment policy — never as inline duplicated predicates, which drift. A bug here leaks discussion on private drafts.

3. **`notifications` must reject all client inserts.** The table is trigger-written. Without an explicit deny, a user could forge a notification — a phishing surface pointed at your own users ("your question was approved, click here"). The policy is insert-nobody, and a test asserts an authenticated client cannot insert even for itself.

> A fourth trap worth naming: **the verified clone.** `source_question_id` links a verified row to a community row with a different owner. Policies must never let visibility of the clone imply visibility of the original, or a question flipped back to `private` would still be readable through its promoted copy.

---

# 7. Migrations & Versioning

- Numbered SQL files in `core/db/migrations/`, applied by `scripts/apply_migrations.py`, tracked in `schema_migrations` with checksums.
- **Forward-only.** Corrections are new migrations, never edits to applied ones.
- Every migration must be safe to run against a live database with users on it.
- A checksum mismatch on an already-applied migration is a hard failure, not a warning.
- Data schema, prompt versions, and rubric weights version independently — see [AI_SPEC §2.1](AI_SPEC.md#21-rules).

---

# 8. Repository Layer

The only place Supabase is touched.

## 8.1 Representative contract

```python
class QuestionRepository:
    def get(self, question_id: UUID) -> Question | None: ...

    def search(
        self,
        query: str | None = None,
        *,
        filters: QuestionFilters,
        limit: int = 25,
        offset: int = 0,
    ) -> Page[Question]: ...

    def list_for_selection(
        self, *, filters: QuestionFilters, exclude_ids: Collection[UUID], limit: int
    ) -> list[Question]: ...

    def create(self, draft: QuestionDraft, *, author_id: UUID) -> Question: ...
    def update(self, question_id: UUID, patch: QuestionPatch) -> Question: ...
    def set_status(self, question_id: UUID, status: QuestionStatus) -> None: ...
    def upvote(self, question_id: UUID, user_id: UUID) -> int: ...
```

`QuestionFilters` is a frozen model: `tiers`, `modules`, `topics`, `difficulties`, `institutions`, `target_roles`, `verification_levels`, `min_upvotes`, `favorited_only`, `unattempted_only`, `mine_only`, `has_answer_key`.

## 8.3 Phase 2 repositories

| Repository | Responsibilities |
|---|---|
| `knowledge.py` | CRUD and search over `knowledge_docs`; `list_for_grounding(ids)` returning bodies plus a summed token estimate |
| `comments.py` | Threaded fetch for a target (top-level + replies in one query, not N+1), post, edit, tombstone |
| `notifications.py` | `unread_count(user_id)`, paginated list, `mark_read`. Never inserts — the table is trigger-written. |
| `reviews.py` | Submit, list pending (admin), approve, reject. **Approval is a single stored procedure**, not three client calls — see §5.7. |
| `votes.py` | Upsert ±1 and clear, for both banks |

Rule 6, added: **admin-only mutations call `SECURITY DEFINER` procedures, not raw table writes.** Promotion touches three tables atomically; doing that from the client leaves the door open to a half-completed promotion.

## 8.2 Rules

1. **Always paginate.** No repository method returns an unbounded list. `Page[T]` carries `items`, `total`, `offset`, `limit`.
2. **Aggregate in SQL, not Python.** Progress metrics come from aggregate queries or views. A shared 1GB container cannot absorb pulling evaluation history into memory.
3. **Typed errors only** — `NotFound`, `PermissionDenied`, `ConflictError`, `BackendUnavailable`. Never leak `postgrest` exceptions.
4. **Every read returns a Pydantic model**, never a raw dict.
5. **No repository imports `streamlit`.** Caching is applied by callers.

---

# 9. Controlled Vocabularies

`module` and `topic` are constrained to lists defined in `core/models/enums.py` — the single source of truth — and validated in CI.

> **Why this matters more than it looks:** free-text drift here (`"Monetary Policy"` vs `"monetary policy"` vs `"Central Bank Policy"`) silently fragments `topic_mastery` rows, which silently destroys weakness detection and adaptive selection. The failure is invisible until the feature just quietly stops working.

**Modules:** Macro Framework · Business Cycle · Inflation · Monetary Policy · Fiscal Policy · Rates & Yield Curve · FX · Balance of Payments & Capital Flows · Credit & Banking · Financial Stability · Sovereign Debt · Emerging Markets · Commodities · Global Liquidity · Country Analysis · Investment Process · Data & Forecasting

**Topics** are module-scoped; the full mapping lives in `enums.py` as `TOPICS_BY_MODULE`.

---

# 10. Domain Models (Pydantic v2)

`core/models/` mirrors the schema. Rules:

- Every DB read passes through a model.
- Validators enforce what SQL cannot: URL shape, module/topic pairing, tier/source coherence.
- Read models are frozen; writes use explicit `*Draft` / `*Patch` types.

```python
class Question(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    ref: str
    tier: QuestionTier
    status: QuestionStatus
    module: Module
    topic: str
    question: str = Field(min_length=20, max_length=1200)
    difficulty: Difficulty
    frequency: Frequency | None = None
    target_roles: tuple[TargetRole, ...] = ()
    institutions: tuple[str, ...] = ()
    verification_level: VerificationLevel
    source_description: str | None = None
    source_url: HttpUrl | None = None
    secondary_sources: tuple[SecondarySource, ...] = ()
    follow_up_questions: tuple[str, ...] = ()
    author_id: UUID | None = None
    owner_id: UUID | None = None
    upvotes: int = 0
    created_at: datetime
    updated_at: datetime

    answer_key: AnswerKey = AnswerKey()
    source_question_id: UUID | None = None
    downvotes: int = 0

    @model_validator(mode="after")
    def _topic_belongs_to_module(self) -> "Question":
        if self.topic not in TOPICS_BY_MODULE[self.module]:
            raise ValueError(f"topic {self.topic!r} not valid for module {self.module}")
        return self
```

> The `_verified_requires_source` validator was removed alongside the DB constraint ([D11](DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance)).

## 10.1 `AnswerKey`

The Python half of [D10](DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose)'s guardrail. The SQL half is `answer_key_is_valid` (§3.1) — both exist so that neither a repository bug nor a direct SQL write can produce a prose answer.

```python
Bullet = Annotated[str, StringConstraints(min_length=1, max_length=240, pattern=r"^[^\n\r]*$")]
Section = Annotated[tuple[Bullet, ...], Field(max_length=8)]


class AnswerKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    framework: Section = ()
    mechanism: Section = ()
    indicators: Section = ()
    market_implication: Section = ()
    common_traps: Section = ()

    @property
    def is_empty(self) -> bool:
        return not any(astuple_of_sections(self))
```

`extra="forbid"` matters: an LLM that invents a sixth section is a validation failure, not a silently dropped field.

## 10.2 `KnowledgeDoc`

Mirrors `Question` in governance fields (`tier`, `status`, `verification_level`, `author_id`, `owner_id`, `source_doc_id`, `upvotes`, `downvotes`) and adds `slug`, `title`, `summary`, `body_md`, `modules`, `topics`, `related_slugs`, `origin`, `token_estimate`.

Because the two models share so much, the governance fields live in a `GovernedContent` mixin rather than being written twice — divergence between the two banks' governance is a bug class worth designing out.

---

# 11. Privacy & Data Rights

- User data is isolated by RLS (§6.2) and never used for training or analytics beyond the user's own progress views.
- **The LLM API key is never persisted** — not in the database, not in cookies, not in logs. It lives in `st.session_state` for the browser session and dies with it. The Settings page states this plainly.
- Answers and evaluations are sent to the user's chosen LLM provider under the user's own account and are subject to that provider's terms. Disclosed on Settings.
- **Export.** Settings produces a single JSON file: profile, sessions, turns, evaluations, notes, favorites, mastery, private questions, private knowledge documents, and your comments.
- **Delete.** Account deletion cascades all user-owned rows. **Anonymized rather than deleted** (`author_id → NULL`): community questions, community knowledge documents, comments, and votes — so other users' interview history, reading, and discussion threads stay interpretable. Verified clones created from your content are unaffected and remain public; you gave those up at submission time ([D14](DECISIONS.md#d14--promotion-to-verified-clones-the-row)). All of this is stated before confirmation, not after.
- **Uploads are never stored.** A file uploaded for grounding ([AI_SPEC §7](AI_SPEC.md#7-agent-tools--safety)) is parsed in memory for that request and discarded. Only text the user explicitly saves into a knowledge document persists.
- A privacy statement covering all of the above ships on the landing page.
