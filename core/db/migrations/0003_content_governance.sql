-- 0003_content_governance.sql
-- Phase 2: answer keys, verified-tier semantics change, vote widening.
-- See docs/DECISIONS.md D10, D11, D14 and docs/DATA_SPEC.md #3, #5.2.
--
-- No explicit BEGIN/COMMIT here: scripts/apply_migrations.py runs each file
-- inside its own transaction and commits after recording it in schema_migrations.

-- ── D11: verified no longer requires a source ──────────────────────────────
-- This constraint made AI-authored questions permanently un-promotable, since
-- CONTENT_SPEC #6.1 forbids inventing a source_url. Dropping it means `verified`
-- now signals "an admin reviewed this and vouches for its quality", not
-- traceable provenance. Provenance lives entirely in verification_level from
-- here on — the anti-fabrication rules on *inventing* a source are unchanged.
ALTER TABLE questions DROP CONSTRAINT verified_needs_source;

-- ── D10: answer keys — structured bullets, never prose ─────────────────────
-- Enforced in the schema, not just the prompt or the Pydantic model, because a
-- guardrail that lives only in application code is a suggestion. Mirrors the
-- shape enforced by core.models.answer_key.AnswerKey.
CREATE OR REPLACE FUNCTION answer_key_is_valid(p_answer_key jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  allowed_keys text[] := ARRAY['framework','mechanism','indicators','market_implication','common_traps'];
  k text;
  v jsonb;
  bullet text;
BEGIN
  IF p_answer_key IS NULL THEN
    RETURN false;
  END IF;
  IF p_answer_key = '{}'::jsonb THEN
    RETURN true;
  END IF;
  IF jsonb_typeof(p_answer_key) <> 'object' THEN
    RETURN false;
  END IF;

  -- No keys outside the allowed five (extra="forbid" on the Python side too).
  FOR k IN SELECT jsonb_object_keys(p_answer_key) LOOP
    IF NOT (k = ANY(allowed_keys)) THEN
      RETURN false;
    END IF;
  END LOOP;

  FOR k, v IN SELECT * FROM jsonb_each(p_answer_key) LOOP
    IF jsonb_typeof(v) <> 'array' THEN
      RETURN false;
    END IF;
    IF jsonb_array_length(v) > 8 THEN
      RETURN false;
    END IF;
    FOR bullet IN SELECT jsonb_array_elements_text(v) LOOP
      IF bullet IS NULL OR char_length(bullet) < 1 OR char_length(bullet) > 240 THEN
        RETURN false;
      END IF;
      IF bullet ~ '[\n\r]' THEN
        RETURN false;
      END IF;
    END LOOP;
  END LOOP;

  RETURN true;
END;
$$;

ALTER TABLE questions ADD COLUMN answer_key jsonb NOT NULL DEFAULT '{}';
ALTER TABLE questions ADD CONSTRAINT answer_key_shape CHECK (answer_key_is_valid(answer_key));

-- ── D14: promotion clones the row ───────────────────────────────────────────
ALTER TABLE questions ADD COLUMN downvotes integer NOT NULL DEFAULT 0;
ALTER TABLE questions ADD COLUMN source_question_id uuid REFERENCES questions(id) ON DELETE SET NULL;
ALTER TABLE questions ADD CONSTRAINT clone_is_verified
  CHECK (source_question_id IS NULL OR tier = 'verified');

-- ── Votes widen to ±1 ────────────────────────────────────────────────────────
-- Dislikes never hide anything (that's question_reports' job); they only sort
-- and inform admin triage. See docs/DATA_SPEC.md #5.2.
ALTER TABLE question_votes ALTER COLUMN value DROP DEFAULT;
ALTER TABLE question_votes DROP CONSTRAINT question_votes_value_check;
ALTER TABLE question_votes ADD CONSTRAINT question_votes_value_check CHECK (value IN (-1, 1));
ALTER TABLE question_votes ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

-- Changing your mind is now an UPDATE of the existing row (the PK is still
-- (question_id, user_id)), so the sync trigger must handle vote flips, not
-- just insert/delete.
--
-- SECURITY DEFINER, and this matters: a plain-invoker trigger runs with the
-- voter's own privileges, so its UPDATE on `questions` would itself be
-- subject to questions_update RLS — which only the question's owner, author,
-- or an admin may pass. A voter who is none of those would have their vote
-- recorded but silently fail to move the denormalized count, with no error.
-- This was a latent bug carried over from Phase 1's original (non-DEFINER)
-- version, caught only once a test exercised a vote from a non-owner voter.
CREATE OR REPLACE FUNCTION sync_question_upvotes()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.value = 1 THEN
      UPDATE questions SET upvotes = upvotes + 1 WHERE id = NEW.question_id;
    ELSE
      UPDATE questions SET downvotes = downvotes + 1 WHERE id = NEW.question_id;
    END IF;
  ELSIF TG_OP = 'UPDATE' THEN
    IF OLD.value <> NEW.value THEN
      IF NEW.value = 1 THEN
        UPDATE questions SET upvotes = upvotes + 1, downvotes = downvotes - 1 WHERE id = NEW.question_id;
      ELSE
        UPDATE questions SET upvotes = upvotes - 1, downvotes = downvotes + 1 WHERE id = NEW.question_id;
      END IF;
    END IF;
  ELSIF TG_OP = 'DELETE' THEN
    IF OLD.value = 1 THEN
      UPDATE questions SET upvotes = upvotes - 1 WHERE id = OLD.question_id;
    ELSE
      UPDATE questions SET downvotes = downvotes - 1 WHERE id = OLD.question_id;
    END IF;
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS question_votes_sync ON question_votes;
CREATE TRIGGER question_votes_sync
  AFTER INSERT OR UPDATE OR DELETE ON question_votes
  FOR EACH ROW EXECUTE FUNCTION sync_question_upvotes();
