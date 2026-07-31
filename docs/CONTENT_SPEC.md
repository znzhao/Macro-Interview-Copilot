# Content Specification

Question bank tiers and governance, AI-assisted authoring, moderation, the search system, and the knowledge base.

← [PROJECT_SPEC.md](../PROJECT_SPEC.md) · [DATA_SPEC.md](DATA_SPEC.md) · [DECISIONS.md](DECISIONS.md)

---

# 1. The Three Tiers

**This model governs both banks identically** — questions and knowledge documents ([D12](DECISIONS.md#d12--the-knowledge-base-is-a-three-tier-postgres-bank)). Everything below reads the same with "question" replaced by "document".

| Tier | Who writes | Visible to | Votes & comments | Enters interview selection |
|---|---|---|---|---|
| `verified` | Admins only | Everyone | Yes | Always |
| `community` | Any signed-in user | Everyone once `published` | Yes | Only if the user opts in |
| `private` | Owner only | Owner only | No — nobody to talk to | Only for the owner |

**A source is no longer required at any tier** ([D11](DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance)). `verified` now means *an admin reviewed this and vouches for its quality*.

> That change makes the **verification badge the sole provenance signal in the product**. A user must always be able to tell at a glance whether they are practicing a real reported interview question, one derived from official research topics, or something an AI wrote ten seconds ago. The badge is therefore non-negotiable on every card in every context — never truncated, never hover-only. Blurring that line destroys the bank's value, and there is no longer a CHECK constraint standing behind it.

Governance (`tier`) and provenance (`verification_level`) are independent axes — see [DATA_SPEC §1](DATA_SPEC.md#1-enums).

---

# 2. Lifecycle

```
agentic draft (AI_SPEC §6), upload, or manual entry
        ↓  Save
   tier=private, status=draft              owner's workspace, invisible to all
        ↓  "Share with the community"      (tier flips — one row, no clone)
   tier=community, status=published        public: votable, commentable, reportable
        ↓  "Submit for verified review"    → review_requests row, admin queue
        ↓  admin approves
   tier=verified, status=published         canonical CLONE; original stays put
```

Three properties of this flow are load-bearing:

1. **Sharing moves; promotion clones.** Flipping private → community is a `tier` update on one row — no duplicate is created, and the author keeps ownership and edit rights. Admin approval instead **inserts a new verified row** with `source_question_id` pointing home ([D14](DECISIONS.md#d14--promotion-to-verified-clones-the-row)).

2. **Submission is irreversible and must say so first.** The author may later flip their community original back to `private`, but the verified clone stays public forever and is admin-owned. The confirmation dialog states this plainly *before* the submit button does anything — discovering it afterwards is a betrayal, not a surprise.

3. **Edit rights follow the tier.** Author or admin may edit a `community` row. Only admins may edit a `verified` row. When a community question is edited *after* votes exist, its card shows "edited since voting" — otherwise a highly-rated question can be quietly rewritten into something else.

**Reverse transitions** (`→ flagged → archived`) are admin-only and **never delete rows**. Admin "Delete" archives. Archived content stays resolvable so historical interview turns and `suggested_readings` slugs remain interpretable — turns additionally store their own `question_text` snapshot ([DATA_SPEC §4.2](DATA_SPEC.md#42-interview_turns)). A true `DELETE` exists only as a double-confirmed admin purge for genuinely illegal content.

---

# 3. Moderation

Two negative signals, deliberately separate, because they mean different things.

| Signal | Meaning | Effect |
|---|---|---|
| **Dislike** (`-1` vote) | "This is weak" | Lowers net score and sort rank; surfaces in the admin low-quality view. **Never hides anything.** |
| **Report** (with a reason) | "This is wrong, unsourced, duplicated, or offensive" | Three open reports auto-flag via trigger, hiding it pending admin action |

Collapsing these into one number would mean five accounts could bury any question, and would throw away the *reason* — which is the only thing that makes an admin queue triageable.

- Any signed-in user may report published content: `inaccurate`, `no_source`, `duplicate`, `offensive`, `other`.
- **Verified content cannot be auto-flagged** — reports on it go to the admin queue only, since auto-hiding canonical content on three reports would be trivially abusable.
- Comments are moderated by tombstone ([DATA_SPEC §5.8](DATA_SPEC.md#58-comments)): author or admin removes the body, the row and its replies survive.
- The Admin page holds one queue spanning both banks: reports, pending review requests, and low-quality content.

---

# 4. Git Seed and Snapshot

Postgres is the live bank ([D5](DECISIONS.md#d5--postgres-is-source-of-truth-for-all-question-tiers)); Git holds a validated, reviewable snapshot.

| Script | Purpose |
|---|---|
| `scripts/seed_db.py` | `content/questions/seed/*.json` and `content/knowledge/*.md` → Postgres. Idempotent upsert on `ref` / `slug`. Bootstraps a fresh database. |
| `scripts/export_questions.py` | Verified-tier Postgres rows → `content/questions/seed/` and `content/knowledge/`. **Run before every release** or the snapshot goes stale. |
| `scripts/validate_content.py` | CI gate over the seed files, both banks. |

Both banks use the same pair of scripts. Knowledge documents round-trip as Markdown with frontmatter — readable in a pull request diff, which is the only part of the old Git-authored design worth keeping.

## 4.1 What CI validates

`validate_content.py` fails the build on any of:

- Schema non-conformance against the Pydantic `Question` model.
- Duplicate or non-continuous `ref` values.
- A `module` or `topic` outside the controlled vocabulary ([DATA_SPEC §9](DATA_SPEC.md#9-controlled-vocabularies)).
- A malformed `source_url`. (A *missing* one is no longer an error at any tier — [D11](DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance).)
- An `answer_key` violating the shape limits in [DATA_SPEC §3.3](DATA_SPEC.md#33-answer-key-shape).
- Near-duplicate questions (trigram similarity > 0.85 against any other question), **excluding clone lineage** — a verified clone is by construction identical to its community original and must not trip the check ([D14](DECISIONS.md#d14--promotion-to-verified-clones-the-row)).

**URL liveness checking is a separate, non-blocking scheduled job.** Link rot is real and constant; it must not block an unrelated merge. Dead links surface in the Admin page's bank-health view.

---

# 5. Search System

## 5.1 Level 1 — full-text (v1)

Postgres `tsvector` over question text, module, topic, and institutions, ranked by `ts_rank_cd`. When full-text returns fewer than 5 results, a `pg_trgm` similarity fallback runs — this handles typos and partial institution names, which is most of what users actually type.

## 5.2 Level 2 — metadata filters (v1)

`QuestionFilters` translates to a parameterized query. Filters are AND-composed; multi-valued fields use array overlap (`&&`).

**Filters are reflected in the URL query string** so that a filtered view is shareable and — importantly on Streamlit — survives a rerun.

## 5.3 Level 3 — semantic (Phase 5)

`pgvector`, with embeddings in a `question_embeddings` table (`question_id`, `embedding vector(1536)`, `model`, `created_at`). Generation is an **admin-triggered batch job using the admin's own key, never on the request path**. Hybrid ranking: `0.6 * semantic + 0.4 * ts_rank`.

Permanently out of scope: in-process FAISS or ChromaDB. A vector index in a shared 1GB container is how every concurrent user gets an OOM restart simultaneously ([D7](DECISIONS.md#d7--keyword--metadata-filtering-in-v1-pgvector-in-phase-4)).

---

# 6. AI-Assisted Authoring

An **agentic loop** ([D13](DECISIONS.md#d13--question-authoring-is-an-agentic-loop-with-tools)) in `core/agent/`, mechanics in [AI_SPEC §6](AI_SPEC.md#6-authoring-agent), using the requesting user's own key.

**Input:** module, topic, difficulty, target role, optional institution, optional grounding (selected knowledge documents, a URL, uploaded `.md`/`.txt`).

**Output:** `QuestionDraftSchema` — the question plus a structured `AnswerKey` — always written with `verification_level='ai_generated'` unless the user replaces it with a genuine source.

Two paths to the same artifact: **one-click** (config → Generate, no tools, no conversation) and **refinement** (grounding plus iterative feedback). The one-click path is the default, not a fallback.

## 6.0 Authoring the answer key

The agent produces the answer key in the same call as the question. It is bound by [DATA_SPEC §3.3](DATA_SPEC.md#33-answer-key-shape): five sections, ≤8 bullets each, ≤240 characters per bullet, no newlines.

> **This is where [D10](DECISIONS.md#d10--answer-keys-are-structured-bullets-never-prose) is won or lost.** A model asked for "an answer" will write prose and then pretend it is a bullet. The prompt states the constraint, the JSON schema encodes it, Pydantic rejects violations, and the database CHECK rejects them again. A bullet that reads as a paragraph fails validation and triggers exactly one repair retry — it is never silently truncated, because truncation produces a half-sentence that looks like a bug in the product rather than a bug in the output.

## 6.1 Anti-fabrication rules

> The original question-generation prompt's core principle was *never invent sources*. That principle is now enforced structurally, not just requested.

- The prompt forbids fabricating `source_url` or interview provenance.
- Drafts arrive with `source_url = null` and `verification_level = 'ai_generated'`. The user may replace both, but **only with something they actually have.**
- A near-duplicate check against the existing bank (trigram similarity > 0.75) runs before save and warns the user.
- A URL the agent *fetched* may be recorded as a source, because it was really retrieved. A URL the agent merely *mentioned* may not — `fetch_url` results are the only machine-supplied provenance the system trusts, and the draft records which tool produced them.

> **The CHECK constraint that used to backstop this is gone** ([D11](DECISIONS.md#d11--verified-means-admin-approved-quality-not-traceable-provenance)). Enforcement is now prompt + schema + UI + review. That is strictly weaker, which is precisely why the verification badge became mandatory everywhere and why `verification_level` may never be edited to a stronger value without a source being supplied in the same action.

## 6.2 Bulk authoring (admin)

The Admin page supports batch drafting for bank growth: specify a module/topic/difficulty distribution, generate N drafts, review each in a queue, accept or discard. A coverage scan over the live bank suggests thin modules and topics, so the distribution is proposed rather than guessed at.

Accepted drafts land as `community`/`published`, never directly as verified — the admin still promotes deliberately, one at a time. Bulk generation growing the bank is a different act from bulk generation blessing it.

## 6.3 Knowledge authoring

The same agent, with `knowledge_author.v1.md`, drafts knowledge documents from a topic, a fetched URL, or an uploaded file. Output is a `KnowledgeDraftSchema` — slug, title, summary, `body_md`, modules, topics — landing at `tier=private`, `origin='ai_generated'`, and travelling the identical lifecycle (§2).

A user may equally upload their own Markdown and skip the agent entirely; that path sets `origin='uploaded'`.

---

# 7. Knowledge Bank

> **Superseded design.** Knowledge was previously Markdown in `content/knowledge/`, authored in Git and explicitly *not* in the database. [D12](DECISIONS.md#d12--the-knowledge-base-is-a-three-tier-postgres-bank) replaced that: users upload, generate, share, and vote on documents, and [ARCHITECTURE §3](ARCHITECTURE.md#3-deployment-constraints) forbids runtime Git writes, so an admin could never have promoted anything. The directory and its CI frontmatter validation are deleted.

Knowledge documents live in `knowledge_docs` ([DATA_SPEC §5.6](DATA_SPEC.md#56-knowledge_docs)) and are governed by §1–§3 above, **identically to questions**: three tiers, votes, comments, reports, review requests, admin promotion by clone, soft delete.

## 7.1 Document shape

| Field | Notes |
|---|---|
| `slug` | `^[a-z0-9_]{3,64}$`, unique, **immutable, never reused** |
| `title`, `summary` | Summary ≤500 chars — this is what the agent's `search_knowledge` returns, so it has to be genuinely descriptive |
| `body_md` | Markdown, ≤200,000 chars |
| `modules`, `topics` | Controlled vocabulary ([DATA_SPEC §9](DATA_SPEC.md#9-controlled-vocabularies)) — same drift hazard as questions |
| `related_slugs` | Cross-link graph. Not an FK, since a target may be archived. |

The old six-section structure (Definition / Framework / Key Indicators / Market Implications / Common Interview Traps / Further Reading) survives as a **template offered in the editor and used by `knowledge_author.v1`**, not as a validated requirement. Enforcing section structure on user uploads would reject most real notes for no benefit.

## 7.2 Knowledge as grounding — "skills for the LLM"

This is what makes the knowledge bank a product surface rather than a reference shelf. In the authoring UI the user ticks documents to ground generation in; their full `body_md` is injected into the prompt, and the agent can also reach them through `search_knowledge` / `read_knowledge` ([AI_SPEC §7](AI_SPEC.md#7-agent-tools--safety)).

- **Selection is explicit and visible.** A live budget meter shows tokens consumed against the 8,000-token grounding cap, using the stored `token_estimate`. Users must be able to see why a generation is expensive.
- **Grounding is recorded on the draft**, so a question can answer "what was this built from?" months later.
- **RLS decides what is reachable**, always through the user's own JWT. The agent must never surface a document its operator could not open themselves.
- Semantic retrieval stays deferred to `pgvector` ([D7](DECISIONS.md#d7--keyword--metadata-filtering-in-v1-pgvector-in-phase-4)) — explicit selection plus full-text search is correct well past the scale this bank will reach soon.

## 7.3 Slugs are permanent

`evaluations.suggested_readings` stores slugs, and an evaluation may be read years after it was written. Slugs are immutable, never reused, and their rows are never hard-deleted — archived documents stay resolvable and render with an "archived" notice rather than a dead link.

## 7.4 Initial coverage

Seeded at `tier=verified` by `scripts/seed_db.py`: inflation · monetary policy · fiscal policy · yield curve · FX framework · balance of payments · business cycle · credit cycle · global liquidity · sovereign debt · China macro · US macro · EM framework · commodities.

`content/knowledge/` remains **only** as a seed and export snapshot, exactly like `content/questions/seed/` (§4) — the bootstrap for a fresh database and a reviewable diff of canonical content, never the live bank.
