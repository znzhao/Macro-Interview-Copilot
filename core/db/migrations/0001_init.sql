-- 0001_init.sql
-- Core schema: extensions, enums, tables, indexes, triggers.
-- See docs/DATA_SPEC.md for the authoritative column-by-column spec.
--
-- No explicit BEGIN/COMMIT here: scripts/apply_migrations.py runs each file
-- inside its own transaction and commits after recording it in
-- schema_migrations, so this file and its ledger entry commit atomically.

-- ── Extensions ──────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- trigram fuzzy search

-- ── Enums ───────────────────────────────────────────────────────────────
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

-- ── profiles ────────────────────────────────────────────────────────────
CREATE TABLE profiles (
  id                  uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name        text,
  target_roles        text[] NOT NULL DEFAULT '{}',
  experience_level    experience_level NOT NULL DEFAULT 'intermediate',
  preferred_provider   text,
  preferred_model      text,
  is_admin            boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- Bootstrap trigger: create a profile row when a new auth user signs up.
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.profiles (id, display_name)
  VALUES (new.id, new.email);
  RETURN new;
END;
$$;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ── questions ───────────────────────────────────────────────────────────
-- A STORED generated column requires a strictly IMMUTABLE expression, and two
-- of the pieces we need are not immutable as the planner sees them:
--   * array_to_string(anyarray, text) is only STABLE, because for a polymorphic
--     array the element output function might depend on runtime settings.
--   * a bare 'english' literal resolves to regconfig through search_path.
-- Both are genuinely deterministic for the concrete types used here (text[],
-- and a schema-qualified text search config), so we wrap the whole document in
-- one correctly-typed IMMUTABLE function and generate from that.
CREATE OR REPLACE FUNCTION questions_search_document(
  p_question      text,
  p_module        text,
  p_topic         text,
  p_institutions  text[]
) RETURNS tsvector
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT setweight(to_tsvector('pg_catalog.english'::regconfig,
                               coalesce(p_question, '')), 'A')
      || setweight(to_tsvector('pg_catalog.english'::regconfig,
                               coalesce(p_module, '')), 'B')
      || setweight(to_tsvector('pg_catalog.english'::regconfig,
                               coalesce(p_topic, '')), 'B')
      || setweight(to_tsvector('pg_catalog.english'::regconfig,
                               coalesce(array_to_string(p_institutions, ' '), '')), 'C')
$$;

CREATE TABLE questions (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ref                   text UNIQUE NOT NULL,
  tier                  question_tier NOT NULL,
  status                question_status NOT NULL DEFAULT 'draft',
  module                text NOT NULL,
  topic                 text NOT NULL,
  question              text NOT NULL,
  difficulty            difficulty_level NOT NULL,
  frequency             frequency_level,
  target_roles          text[] NOT NULL DEFAULT '{}',
  institutions          text[] NOT NULL DEFAULT '{}',
  verification_level    verification_level NOT NULL,
  source_description    text,
  source_url            text,
  secondary_sources     jsonb NOT NULL DEFAULT '[]',
  follow_up_questions   text[] NOT NULL DEFAULT '{}',
  author_id             uuid REFERENCES profiles(id) ON DELETE SET NULL,
  owner_id              uuid REFERENCES profiles(id) ON DELETE CASCADE,
  upvotes               integer NOT NULL DEFAULT 0,
  search_tsv            tsvector GENERATED ALWAYS AS (
                          questions_search_document(question, module, topic, institutions)
                        ) STORED,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT verified_needs_source
    CHECK (tier <> 'verified' OR (source_url IS NOT NULL AND length(source_url) > 10)),
  CONSTRAINT private_needs_owner
    CHECK (tier <> 'private' OR owner_id IS NOT NULL),
  CONSTRAINT question_length
    CHECK (char_length(question) BETWEEN 20 AND 1200)
);

CREATE INDEX questions_tsv_idx          ON questions USING GIN (search_tsv);
CREATE INDEX questions_institutions_idx ON questions USING GIN (institutions);
CREATE INDEX questions_roles_idx        ON questions USING GIN (target_roles);
CREATE INDEX questions_browse_idx       ON questions (tier, status, module, topic);
CREATE INDEX questions_trgm_idx         ON questions USING GIN (question gin_trgm_ops);

-- ── question_votes ──────────────────────────────────────────────────────
CREATE TABLE question_votes (
  question_id  uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  user_id      uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  value        smallint NOT NULL DEFAULT 1 CHECK (value = 1),
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (question_id, user_id)
);

CREATE OR REPLACE FUNCTION sync_question_upvotes()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    UPDATE questions SET upvotes = upvotes + 1 WHERE id = NEW.question_id;
  ELSIF TG_OP = 'DELETE' THEN
    UPDATE questions SET upvotes = upvotes - 1 WHERE id = OLD.question_id;
  END IF;
  RETURN NULL;
END;
$$;

CREATE TRIGGER question_votes_sync
  AFTER INSERT OR DELETE ON question_votes
  FOR EACH ROW EXECUTE FUNCTION sync_question_upvotes();

-- ── question_reports ────────────────────────────────────────────────────
CREATE TABLE question_reports (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id   uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  reporter_id   uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  reason        text NOT NULL CHECK (reason IN ('inaccurate','no_source','duplicate','offensive','other')),
  detail        text,
  status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  resolved_at   timestamptz
);

-- Auto-flag a question once it accumulates 3 open reports.
CREATE OR REPLACE FUNCTION auto_flag_question()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  open_count integer;
BEGIN
  SELECT count(*) INTO open_count
  FROM question_reports
  WHERE question_id = NEW.question_id AND status = 'open';

  IF open_count >= 3 THEN
    UPDATE questions SET status = 'flagged' WHERE id = NEW.question_id AND status <> 'archived';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER question_reports_auto_flag
  AFTER INSERT ON question_reports
  FOR EACH ROW EXECUTE FUNCTION auto_flag_question();

-- ── interview_sessions ──────────────────────────────────────────────────
CREATE TABLE interview_sessions (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  mode           interviewer_mode NOT NULL,
  institution    text,
  config         jsonb NOT NULL DEFAULT '{}',
  status         session_status NOT NULL DEFAULT 'active',
  overall_score  smallint CHECK (overall_score BETWEEN 0 AND 100),
  started_at     timestamptz NOT NULL DEFAULT now(),
  ended_at       timestamptz
);

CREATE INDEX interview_sessions_user_idx ON interview_sessions (user_id, started_at DESC);

-- ── interview_turns ─────────────────────────────────────────────────────
CREATE TABLE interview_turns (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id       uuid NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  ordinal          integer NOT NULL,
  question_id      uuid REFERENCES questions(id) ON DELETE SET NULL,
  question_text    text NOT NULL,
  is_followup      boolean NOT NULL DEFAULT false,
  parent_turn_id   uuid REFERENCES interview_turns(id) ON DELETE SET NULL,
  answer_text      text,
  answer_seconds   integer CHECK (answer_seconds IS NULL OR answer_seconds >= 0),
  created_at       timestamptz NOT NULL DEFAULT now(),
  answered_at      timestamptz,

  UNIQUE (session_id, ordinal)
);

CREATE INDEX interview_turns_session_idx ON interview_turns (session_id, ordinal);

-- ── evaluations ──────────────────────────────────────────────────────────
CREATE TABLE evaluations (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  turn_id                uuid UNIQUE NOT NULL REFERENCES interview_turns(id) ON DELETE CASCADE,
  user_id                uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  score_framework        smallint NOT NULL CHECK (score_framework BETWEEN 0 AND 4),
  score_logic            smallint NOT NULL CHECK (score_logic BETWEEN 0 AND 4),
  score_evidence         smallint NOT NULL CHECK (score_evidence BETWEEN 0 AND 4),
  score_market           smallint NOT NULL CHECK (score_market BETWEEN 0 AND 4),
  score_communication    smallint NOT NULL CHECK (score_communication BETWEEN 0 AND 4),
  total_score            smallint NOT NULL CHECK (total_score BETWEEN 0 AND 100),
  justifications         jsonb NOT NULL DEFAULT '{}',
  strengths              text[] NOT NULL DEFAULT '{}',
  gaps                   text[] NOT NULL DEFAULT '{}',
  improved_outline       text,
  suggested_readings     text[] NOT NULL DEFAULT '{}',
  model                  text NOT NULL,
  prompt_version         text NOT NULL,
  raw_response           jsonb,
  created_at             timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX evaluations_user_idx ON evaluations (user_id, created_at DESC);

-- ── topic_mastery ────────────────────────────────────────────────────────
CREATE TABLE topic_mastery (
  user_id              uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  module               text NOT NULL,
  topic                text NOT NULL,
  attempts             integer NOT NULL DEFAULT 0,
  ewma_framework       real NOT NULL DEFAULT 0,
  ewma_logic           real NOT NULL DEFAULT 0,
  ewma_evidence        real NOT NULL DEFAULT 0,
  ewma_market          real NOT NULL DEFAULT 0,
  ewma_communication   real NOT NULL DEFAULT 0,
  ewma_total           real NOT NULL DEFAULT 0,
  last_practiced_at    timestamptz,

  PRIMARY KEY (user_id, module, topic)
);

-- ── notes ───────────────────────────────────────────────────────────────
CREATE TABLE notes (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  question_id   uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  content       text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),

  UNIQUE (user_id, question_id)
);

-- ── favorites ───────────────────────────────────────────────────────────
CREATE TABLE favorites (
  user_id       uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  question_id   uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  created_at    timestamptz NOT NULL DEFAULT now(),

  PRIMARY KEY (user_id, question_id)
);

-- ── schema_migrations ───────────────────────────────────────────────────
-- Bootstrapped separately by scripts/apply_migrations.py before any migration
-- runs (it needs to exist to record this very migration). IF NOT EXISTS makes
-- this declaration here idempotent and keeps the table's definition in the
-- versioned schema history rather than only in the script.
CREATE TABLE IF NOT EXISTS schema_migrations (
  version      text PRIMARY KEY,
  applied_at   timestamptz NOT NULL DEFAULT now(),
  checksum     text NOT NULL
);
