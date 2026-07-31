-- 0004_knowledge_and_social.sql
-- Phase 2: the knowledge bank (D12), comments, review requests, notifications.
-- See docs/DATA_SPEC.md #5.6-5.9.
--
-- No explicit BEGIN/COMMIT here: scripts/apply_migrations.py runs each file
-- inside its own transaction and commits after recording it in schema_migrations.

-- ── New enums ────────────────────────────────────────────────────────────
CREATE TYPE review_status     AS ENUM ('pending', 'approved', 'rejected', 'withdrawn');
CREATE TYPE content_kind      AS ENUM ('question', 'knowledge');
CREATE TYPE notification_kind AS ENUM (
  'submission_approved',
  'submission_rejected',
  'comment_on_content',
  'reply_to_comment'
);

-- ── knowledge_docs ──────────────────────────────────────────────────────
-- question_tier / question_status are reused verbatim as the governance
-- vocabulary for both banks (D12) — read them as content_tier / content_status.
CREATE OR REPLACE FUNCTION knowledge_search_document(
  p_title    text,
  p_summary  text,
  p_modules  text[],
  p_topics   text[]
) RETURNS tsvector
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT setweight(to_tsvector('pg_catalog.english'::regconfig,
                               coalesce(p_title, '')), 'A')
      || setweight(to_tsvector('pg_catalog.english'::regconfig,
                               coalesce(p_summary, '')), 'B')
      || setweight(to_tsvector('pg_catalog.english'::regconfig,
                               coalesce(array_to_string(p_modules, ' '), '')), 'B')
      || setweight(to_tsvector('pg_catalog.english'::regconfig,
                               coalesce(array_to_string(p_topics, ' '), '')), 'C')
$$;

CREATE TABLE knowledge_docs (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug                  text UNIQUE NOT NULL,
  tier                  question_tier NOT NULL,
  status                question_status NOT NULL DEFAULT 'draft',
  title                 text NOT NULL,
  summary               text NOT NULL,
  body_md               text NOT NULL,
  modules               text[] NOT NULL DEFAULT '{}',
  topics                text[] NOT NULL DEFAULT '{}',
  related_slugs         text[] NOT NULL DEFAULT '{}',
  verification_level    verification_level NOT NULL,
  source_url            text,
  origin                text NOT NULL DEFAULT 'uploaded'
                          CHECK (origin IN ('uploaded', 'ai_generated', 'seeded')),
  author_id             uuid REFERENCES profiles(id) ON DELETE SET NULL,
  owner_id              uuid REFERENCES profiles(id) ON DELETE CASCADE,
  source_doc_id         uuid REFERENCES knowledge_docs(id) ON DELETE SET NULL,
  upvotes               integer NOT NULL DEFAULT 0,
  downvotes             integer NOT NULL DEFAULT 0,
  token_estimate        integer GENERATED ALWAYS AS (char_length(body_md) / 4) STORED,
  search_tsv            tsvector GENERATED ALWAYS AS (
                          knowledge_search_document(title, summary, modules, topics)
                        ) STORED,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT knowledge_private_needs_owner
    CHECK (tier <> 'private' OR owner_id IS NOT NULL),
  CONSTRAINT knowledge_clone_is_verified
    CHECK (source_doc_id IS NULL OR tier = 'verified'),
  CONSTRAINT knowledge_slug_shape
    CHECK (slug ~ '^[a-z0-9_]{3,64}$'),
  CONSTRAINT knowledge_title_length
    CHECK (char_length(title) BETWEEN 3 AND 200),
  CONSTRAINT knowledge_summary_length
    CHECK (char_length(summary) <= 500),
  CONSTRAINT knowledge_body_length
    CHECK (char_length(body_md) <= 200000)
);

CREATE INDEX knowledge_docs_tsv_idx     ON knowledge_docs USING GIN (search_tsv);
CREATE INDEX knowledge_docs_modules_idx ON knowledge_docs USING GIN (modules);
CREATE INDEX knowledge_docs_topics_idx  ON knowledge_docs USING GIN (topics);
CREATE INDEX knowledge_docs_browse_idx  ON knowledge_docs (tier, status);

-- ── knowledge_votes ─────────────────────────────────────────────────────
-- Mirrors question_votes exactly (±1, dislikes never hide anything).
CREATE TABLE knowledge_votes (
  doc_id       uuid NOT NULL REFERENCES knowledge_docs(id) ON DELETE CASCADE,
  user_id      uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  value        smallint NOT NULL CHECK (value IN (-1, 1)),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (doc_id, user_id)
);

-- SECURITY DEFINER for the same reason as sync_question_upvotes() in
-- 0003_content_governance.sql: a voter is rarely the document's own owner or
-- author, and an invoker-rights trigger would have its UPDATE silently
-- filtered by knowledge_docs_update RLS.
CREATE OR REPLACE FUNCTION sync_knowledge_votes()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.value = 1 THEN
      UPDATE knowledge_docs SET upvotes = upvotes + 1 WHERE id = NEW.doc_id;
    ELSE
      UPDATE knowledge_docs SET downvotes = downvotes + 1 WHERE id = NEW.doc_id;
    END IF;
  ELSIF TG_OP = 'UPDATE' THEN
    IF OLD.value <> NEW.value THEN
      IF NEW.value = 1 THEN
        UPDATE knowledge_docs SET upvotes = upvotes + 1, downvotes = downvotes - 1 WHERE id = NEW.doc_id;
      ELSE
        UPDATE knowledge_docs SET upvotes = upvotes - 1, downvotes = downvotes + 1 WHERE id = NEW.doc_id;
      END IF;
    END IF;
  ELSIF TG_OP = 'DELETE' THEN
    IF OLD.value = 1 THEN
      UPDATE knowledge_docs SET upvotes = upvotes - 1 WHERE id = OLD.doc_id;
    ELSE
      UPDATE knowledge_docs SET downvotes = downvotes - 1 WHERE id = OLD.doc_id;
    END IF;
  END IF;
  RETURN NULL;
END;
$$;

CREATE TRIGGER knowledge_votes_sync
  AFTER INSERT OR UPDATE OR DELETE ON knowledge_votes
  FOR EACH ROW EXECUTE FUNCTION sync_knowledge_votes();

-- ── review_requests ─────────────────────────────────────────────────────
-- An explicit record, not a status flag, so the author can be notified of the
-- outcome and the decision is auditable. See docs/DECISIONS.md D14.
CREATE TABLE review_requests (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            content_kind NOT NULL,
  question_id     uuid REFERENCES questions(id) ON DELETE CASCADE,
  doc_id          uuid REFERENCES knowledge_docs(id) ON DELETE CASCADE,
  requester_id    uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  note            text,
  status          review_status NOT NULL DEFAULT 'pending',
  decided_by      uuid REFERENCES profiles(id) ON DELETE SET NULL,
  decision_note   text,
  promoted_id     uuid,
  created_at      timestamptz NOT NULL DEFAULT now(),
  decided_at      timestamptz,

  CONSTRAINT review_requests_exactly_one_target
    CHECK (num_nonnulls(question_id, doc_id) = 1),
  CONSTRAINT review_requests_target_matches_kind
    CHECK (
      (kind = 'question'  AND question_id IS NOT NULL) OR
      (kind = 'knowledge' AND doc_id      IS NOT NULL)
    )
);

-- An author cannot queue the same item twice while a decision is pending.
CREATE UNIQUE INDEX review_requests_one_pending_question
  ON review_requests (question_id) WHERE status = 'pending' AND question_id IS NOT NULL;
CREATE UNIQUE INDEX review_requests_one_pending_doc
  ON review_requests (doc_id) WHERE status = 'pending' AND doc_id IS NOT NULL;
CREATE INDEX review_requests_status_idx ON review_requests (status, created_at);

-- ── comments ────────────────────────────────────────────────────────────
-- One-level threading: top-level comments plus a single reply depth.
CREATE TABLE comments (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind          content_kind NOT NULL,
  question_id   uuid REFERENCES questions(id) ON DELETE CASCADE,
  doc_id        uuid REFERENCES knowledge_docs(id) ON DELETE CASCADE,
  parent_id     uuid REFERENCES comments(id) ON DELETE CASCADE,
  author_id     uuid REFERENCES profiles(id) ON DELETE SET NULL,
  body          text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
  is_deleted    boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT comments_exactly_one_target
    CHECK (num_nonnulls(question_id, doc_id) = 1),
  CONSTRAINT comments_target_matches_kind
    CHECK (
      (kind = 'question'  AND question_id IS NOT NULL) OR
      (kind = 'knowledge' AND doc_id      IS NOT NULL)
    )
);

CREATE INDEX comments_question_idx ON comments (question_id, created_at) WHERE question_id IS NOT NULL;
CREATE INDEX comments_doc_idx      ON comments (doc_id, created_at) WHERE doc_id IS NOT NULL;

-- Depth is capped at "reply to a top-level comment" via a BEFORE trigger
-- rather than a CHECK constraint. A CHECK that queries another row is not
-- re-validated if that row later changes (Postgres explicitly recommends a
-- trigger or FK for constraints spanning rows) — a trigger is the correct
-- tool here, not a documented shortcut.
CREATE OR REPLACE FUNCTION enforce_comment_depth()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.parent_id IS NOT NULL THEN
    IF EXISTS (
      SELECT 1 FROM comments WHERE id = NEW.parent_id AND parent_id IS NOT NULL
    ) THEN
      RAISE EXCEPTION 'comments may only be one level deep (reply-to-reply is not allowed)';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER comments_depth_guard
  BEFORE INSERT OR UPDATE ON comments
  FOR EACH ROW EXECUTE FUNCTION enforce_comment_depth();

-- ── notifications ───────────────────────────────────────────────────────
-- Trigger-written only (see 0005_phase2_rls.sql — no client INSERT policy
-- exists for this table at all). A notification written in Python is a
-- notification some future code path forgets to write.
CREATE TABLE notifications (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  kind         notification_kind NOT NULL,
  title        text NOT NULL,
  body         text,
  link_kind    content_kind,
  link_id      uuid,
  read_at      timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX notifications_user_unread_idx ON notifications (user_id, read_at, created_at DESC);
