# Content Specification

Question bank tiers and governance, AI-assisted authoring, moderation, the search system, and the knowledge base.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md) · [DATA_SPEC.md](DATA_SPEC.md) · [DECISIONS.md](DECISIONS.md)

---

# 1. The Three Tiers

| Tier | Who writes | Visible to | Source required | Enters interview selection |
|---|---|---|---|---|
| `verified` | Admins only, via the Admin page | Everyone | **Yes**, enforced by CHECK constraint | Always |
| `community` | Any signed-in user | Everyone once `published` | Encouraged, not required | Only if the user opts in |
| `private` | Owner only | Owner only | No | Only for the owner |

**`verification_level` is displayed as a badge on every question card in every tier.** A user must always be able to tell at a glance whether they are practicing a real reported interview question, a question derived from official research topics, or something an AI made up ten seconds ago. Blurring that line destroys the bank's value.

Governance (`tier`) and provenance (`verification_level`) are independent axes — see [DATA_SPEC §1](DATA_SPEC.md#1-enums).

---

# 2. Lifecycle

```
AI-assisted draft, or manual entry
        ↓
   tier=private, status=draft            owner's private workspace
        ↓  "publish to community"
   tier=community, status=published      public, upvotable, reportable
        ↓  admin promotes, having added or validated a source
   tier=verified, status=published       canonical
```

**Reverse transitions** (`verified → flagged → archived`) are admin-only and **never delete rows**. Archived questions must remain resolvable so that historical interview turns stay interpretable — though note that turns store their own `question_text` snapshot precisely so they don't depend on this ([DATA_SPEC §4.2](DATA_SPEC.md#42-interview_turns)).

---

# 3. Moderation

- Any signed-in user may report a published community question with a reason: `inaccurate`, `no_source`, `duplicate`, `offensive`, `other`.
- **Three open reports auto-flag** the question via trigger, hiding it from browse and from interview selection until an admin acts.
- The Admin page holds a report queue: resolve (unflag), archive, or promote to verified.
- **Verified questions cannot be user-flagged** — they can only be reported for admin review, since auto-hiding canonical content on three reports would be trivially abusable.

---

# 4. Git Seed and Snapshot

Postgres is the live bank ([D5](DECISIONS.md#d5--postgres-is-source-of-truth-for-all-question-tiers)); Git holds a validated, reviewable snapshot.

| Script | Purpose |
|---|---|
| `scripts/seed_db.py` | `content/questions/seed/*.json` → Postgres. Idempotent upsert on `ref`. Bootstraps a fresh database. |
| `scripts/export_questions.py` | Verified-tier Postgres rows → `content/questions/seed/`. **Run before every release** or the snapshot goes stale. |
| `scripts/validate_content.py` | CI gate over the seed files. |

## 4.1 What CI validates

`validate_content.py` fails the build on any of:

- Schema non-conformance against the Pydantic `Question` model.
- Duplicate or non-continuous `ref` values.
- A `module` or `topic` outside the controlled vocabulary ([DATA_SPEC §9](DATA_SPEC.md#9-controlled-vocabularies)).
- A verified-tier question missing `source_url`, or with a malformed one.
- Near-duplicate questions (trigram similarity > 0.85 against any other question).

**URL liveness checking is a separate, non-blocking scheduled job.** Link rot is real and constant; it must not block an unrelated merge. Dead links surface in the Admin page's bank-health view.

---

# 5. Search System

## 5.1 Level 1 — full-text (v1)

Postgres `tsvector` over question text, module, topic, and institutions, ranked by `ts_rank_cd`. When full-text returns fewer than 5 results, a `pg_trgm` similarity fallback runs — this handles typos and partial institution names, which is most of what users actually type.

## 5.2 Level 2 — metadata filters (v1)

`QuestionFilters` translates to a parameterized query. Filters are AND-composed; multi-valued fields use array overlap (`&&`).

**Filters are reflected in the URL query string** so that a filtered view is shareable and — importantly on Streamlit — survives a rerun.

## 5.3 Level 3 — semantic (Phase 4)

`pgvector`, with embeddings in a `question_embeddings` table (`question_id`, `embedding vector(1536)`, `model`, `created_at`). Generation is an **admin-triggered batch job using the admin's own key, never on the request path**. Hybrid ranking: `0.6 * semantic + 0.4 * ts_rank`.

Permanently out of scope: in-process FAISS or ChromaDB. A vector index in a shared 1GB container is how every concurrent user gets an OOM restart simultaneously ([D7](DECISIONS.md#d7--keyword--metadata-filtering-in-v1-pgvector-in-phase-4)).

---

# 6. AI-Assisted Authoring

`core/engine/authoring.py` with `prompts/question_author.v1.md`, using the requesting user's own key.

**Input:** module, topic, difficulty, target role, optional institution and seed context.

**Output:** `QuestionDraftSchema`, always written with `verification_level='ai_generated'`.

## 6.1 Anti-fabrication rules

> The original question-generation prompt's core principle was *never invent sources*. That principle is now enforced structurally, not just requested.

- The prompt forbids fabricating `source_url` or interview provenance.
- Drafts arrive with `source_url = null`. The UI **requires the user to supply a real source** before the question can be promoted beyond `community`.
- The CHECK constraint on `questions` makes it impossible to write a verified-tier row without a source at all ([DATA_SPEC §3.1](DATA_SPEC.md#31-constraints)).
- A near-duplicate check against the existing bank (trigram similarity > 0.75) runs before save and warns the user.

## 6.2 Bulk authoring (admin)

The Admin page supports batch drafting for bank growth: specify a module/topic/difficulty distribution, generate N drafts, review each in a queue, accept or discard. Accepted drafts land as `community`/`draft` for sourcing, never directly as verified.

---

# 7. Knowledge Base

Markdown in `content/knowledge/`, read at runtime and rendered by the Knowledge page. **Not in the database** — this content is authored in Git and changes with releases.

Every document carries frontmatter and a fixed section structure:

```markdown
---
slug: yield_curve
title: The Yield Curve
modules: [Rates & Yield Curve, Monetary Policy]
topics: [term_premium, inversion, forward_rates]
related: [monetary_policy, global_liquidity]
---

## Definition
## Framework
## Key Indicators
## Market Implications
## Common Interview Traps
## Further Reading
```

- `slug` is the join key used by `evaluations.suggested_readings`, which is what lets the evaluator point a weak answer at a specific document rather than a vague topic.
- `related` builds the cross-link graph between concepts.
- CI validates that every referenced slug exists, that `modules` and `topics` use the controlled vocabulary, and that all six sections are present.

## 7.1 Initial coverage

Phase 3 target set: inflation · monetary policy · fiscal policy · yield curve · FX framework · balance of payments · business cycle · credit cycle · global liquidity · sovereign debt · China macro · US macro · EM framework · commodities.
