-- 0002_rls.sql
-- Row Level Security policies. This is the authorization boundary — see docs/DATA_SPEC.md #6.
-- The app connects with the anon key plus the user's JWT; the service-role key
-- must never be used from the Streamlit app, since it bypasses everything below.
--
-- No explicit BEGIN/COMMIT here: scripts/apply_migrations.py runs each file
-- inside its own transaction and commits after recording it in schema_migrations.

-- ── is_admin() helper ──────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION is_admin()
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
  SELECT coalesce((SELECT p.is_admin FROM profiles p WHERE p.id = auth.uid()), false);
$$;

-- ── profiles ────────────────────────────────────────────────────────────
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY profiles_select_own ON profiles
  FOR SELECT USING (id = auth.uid() OR is_admin());

CREATE POLICY profiles_update_own ON profiles
  FOR UPDATE USING (id = auth.uid()) WITH CHECK (id = auth.uid());

-- ── questions ───────────────────────────────────────────────────────────
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;

CREATE POLICY questions_select ON questions
  FOR SELECT USING (
    (tier IN ('verified', 'community') AND status = 'published')
    OR owner_id = auth.uid()
    OR is_admin()
  );

CREATE POLICY questions_insert ON questions
  FOR INSERT WITH CHECK (
    author_id = auth.uid()
    AND (tier <> 'verified' OR is_admin())
  );

CREATE POLICY questions_update ON questions
  FOR UPDATE USING (
    owner_id = auth.uid() OR author_id = auth.uid() OR is_admin()
  )
  WITH CHECK (
    -- Only an admin may set or keep tier='verified'.
    (tier <> 'verified' OR is_admin())
    AND (owner_id = auth.uid() OR author_id = auth.uid() OR is_admin())
  );

CREATE POLICY questions_delete ON questions
  FOR DELETE USING (owner_id = auth.uid() OR is_admin());

-- ── question_votes ──────────────────────────────────────────────────────
ALTER TABLE question_votes ENABLE ROW LEVEL SECURITY;

CREATE POLICY question_votes_select ON question_votes
  FOR SELECT USING (true);

CREATE POLICY question_votes_insert ON question_votes
  FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY question_votes_delete ON question_votes
  FOR DELETE USING (user_id = auth.uid());

-- ── question_reports ─────────────────────────────────────────────────────
ALTER TABLE question_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY question_reports_select ON question_reports
  FOR SELECT USING (reporter_id = auth.uid() OR is_admin());

CREATE POLICY question_reports_insert ON question_reports
  FOR INSERT WITH CHECK (reporter_id = auth.uid());

CREATE POLICY question_reports_update ON question_reports
  FOR UPDATE USING (is_admin()) WITH CHECK (is_admin());

-- ── interview_sessions ──────────────────────────────────────────────────
ALTER TABLE interview_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY interview_sessions_all ON interview_sessions
  FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- ── interview_turns ──────────────────────────────────────────────────────
-- No user_id column here; authorization is via the owning session.
ALTER TABLE interview_turns ENABLE ROW LEVEL SECURITY;

CREATE POLICY interview_turns_all ON interview_turns
  FOR ALL USING (
    EXISTS (
      SELECT 1 FROM interview_sessions s
      WHERE s.id = interview_turns.session_id AND s.user_id = auth.uid()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM interview_sessions s
      WHERE s.id = interview_turns.session_id AND s.user_id = auth.uid()
    )
  );

-- ── evaluations ─────────────────────────────────────────────────────────
ALTER TABLE evaluations ENABLE ROW LEVEL SECURITY;

CREATE POLICY evaluations_all ON evaluations
  FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- ── topic_mastery ───────────────────────────────────────────────────────
ALTER TABLE topic_mastery ENABLE ROW LEVEL SECURITY;

CREATE POLICY topic_mastery_all ON topic_mastery
  FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- ── notes ───────────────────────────────────────────────────────────────
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;

CREATE POLICY notes_all ON notes
  FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- ── favorites ───────────────────────────────────────────────────────────
ALTER TABLE favorites ENABLE ROW LEVEL SECURITY;

CREATE POLICY favorites_all ON favorites
  FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
