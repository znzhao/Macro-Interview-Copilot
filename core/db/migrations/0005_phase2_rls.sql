-- 0005_phase2_rls.sql
-- RLS for every Phase 2 table, plus the SECURITY DEFINER promotion procedures
-- and the comment notification trigger. See docs/DATA_SPEC.md #6.2-6.3.
--
-- No explicit BEGIN/COMMIT here: scripts/apply_migrations.py runs each file
-- inside its own transaction and commits after recording it in schema_migrations.

-- ── knowledge_docs ──────────────────────────────────────────────────────
-- Identical shape to the questions policies (D12: both banks governed alike).
ALTER TABLE knowledge_docs ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_docs_select ON knowledge_docs
  FOR SELECT USING (
    (tier IN ('verified', 'community') AND status = 'published')
    OR owner_id = auth.uid()
    OR is_admin()
  );

CREATE POLICY knowledge_docs_insert ON knowledge_docs
  FOR INSERT WITH CHECK (
    author_id = auth.uid()
    AND (tier <> 'verified' OR is_admin())
  );

CREATE POLICY knowledge_docs_update ON knowledge_docs
  FOR UPDATE USING (
    owner_id = auth.uid() OR author_id = auth.uid() OR is_admin()
  )
  WITH CHECK (
    (tier <> 'verified' OR is_admin())
    AND (owner_id = auth.uid() OR author_id = auth.uid() OR is_admin())
  );

CREATE POLICY knowledge_docs_delete ON knowledge_docs
  FOR DELETE USING (owner_id = auth.uid() OR is_admin());

-- ── knowledge_votes ─────────────────────────────────────────────────────
ALTER TABLE knowledge_votes ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_votes_select ON knowledge_votes
  FOR SELECT USING (true);

CREATE POLICY knowledge_votes_insert ON knowledge_votes
  FOR INSERT WITH CHECK (
    user_id = auth.uid()
    AND EXISTS (
      SELECT 1 FROM knowledge_docs d
      WHERE d.id = knowledge_votes.doc_id
        AND d.tier IN ('verified', 'community') AND d.status = 'published'
    )
  );

CREATE POLICY knowledge_votes_update ON knowledge_votes
  FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY knowledge_votes_delete ON knowledge_votes
  FOR DELETE USING (user_id = auth.uid());

-- ── question_votes: tighten to require a published, non-private target ────
-- and add UPDATE, now that changing your mind (+1 <-> -1) is a legal action.
DROP POLICY IF EXISTS question_votes_insert ON question_votes;
CREATE POLICY question_votes_insert ON question_votes
  FOR INSERT WITH CHECK (
    user_id = auth.uid()
    AND EXISTS (
      SELECT 1 FROM questions q
      WHERE q.id = question_votes.question_id
        AND q.tier IN ('verified', 'community') AND q.status = 'published'
    )
  );

CREATE POLICY question_votes_update ON question_votes
  FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- ── can_view_content() ──────────────────────────────────────────────────
-- Comment visibility is derived from the visibility of the thing being
-- commented on, which differs by kind. A single SECURITY DEFINER helper used
-- by every comment policy, rather than duplicating the predicate inline,
-- because duplicated predicates drift and a drift here leaks discussion on
-- private drafts. See docs/DATA_SPEC.md #6.3.
CREATE OR REPLACE FUNCTION can_view_content(p_kind content_kind, p_id uuid)
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
  SELECT CASE p_kind
    WHEN 'question' THEN EXISTS (
      SELECT 1 FROM questions q
      WHERE q.id = p_id
        AND ((q.tier IN ('verified', 'community') AND q.status = 'published')
             OR q.owner_id = auth.uid() OR is_admin())
    )
    WHEN 'knowledge' THEN EXISTS (
      SELECT 1 FROM knowledge_docs d
      WHERE d.id = p_id
        AND ((d.tier IN ('verified', 'community') AND d.status = 'published')
             OR d.owner_id = auth.uid() OR is_admin())
    )
    ELSE false
  END;
$$;

-- ── comments ────────────────────────────────────────────────────────────
ALTER TABLE comments ENABLE ROW LEVEL SECURITY;

CREATE POLICY comments_select ON comments
  FOR SELECT USING (
    (kind = 'question'  AND can_view_content('question', question_id)) OR
    (kind = 'knowledge' AND can_view_content('knowledge', doc_id))
  );

-- Insert only on published, non-private targets — there is nobody to talk to
-- on a private draft.
CREATE POLICY comments_insert ON comments
  FOR INSERT WITH CHECK (
    author_id = auth.uid()
    AND (
      (kind = 'question' AND EXISTS (
        SELECT 1 FROM questions q WHERE q.id = question_id
          AND q.tier IN ('verified', 'community') AND q.status = 'published'
      ))
      OR
      (kind = 'knowledge' AND EXISTS (
        SELECT 1 FROM knowledge_docs d WHERE d.id = doc_id
          AND d.tier IN ('verified', 'community') AND d.status = 'published'
      ))
    )
  );

-- No DELETE policy: deletion is a tombstone (is_deleted=true) via UPDATE, so
-- replies never end up orphaned. Author may edit their own body; author or
-- admin may set the tombstone.
CREATE POLICY comments_update ON comments
  FOR UPDATE USING (author_id = auth.uid() OR is_admin())
  WITH CHECK (author_id = auth.uid() OR is_admin());

-- ── review_requests ─────────────────────────────────────────────────────
ALTER TABLE review_requests ENABLE ROW LEVEL SECURITY;

CREATE POLICY review_requests_select ON review_requests
  FOR SELECT USING (requester_id = auth.uid() OR is_admin());

-- You may only submit content you actually own.
CREATE POLICY review_requests_insert ON review_requests
  FOR INSERT WITH CHECK (
    requester_id = auth.uid()
    AND (
      (kind = 'question' AND EXISTS (
        SELECT 1 FROM questions q WHERE q.id = question_id AND q.owner_id = auth.uid()
      ))
      OR
      (kind = 'knowledge' AND EXISTS (
        SELECT 1 FROM knowledge_docs d WHERE d.id = doc_id AND d.owner_id = auth.uid()
      ))
    )
  );

-- Decisions (approve/reject) go through approve_review_request() /
-- reject_review_request() below, which run SECURITY DEFINER and therefore
-- bypass this policy entirely — it exists as a backstop against any other
-- write path, not as the primary enforcement mechanism.
CREATE POLICY review_requests_update ON review_requests
  FOR UPDATE USING (is_admin()) WITH CHECK (is_admin());

-- ── notifications ───────────────────────────────────────────────────────
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

CREATE POLICY notifications_select ON notifications
  FOR SELECT USING (user_id = auth.uid());

-- Deliberately no INSERT policy of any kind. With RLS enabled, the absence of
-- an INSERT policy denies that command to every non-owner role — there is no
-- "allow nobody" policy to write, the omission itself is the control. Rows
-- are written exclusively by the SECURITY DEFINER functions below, which
-- bypass RLS as the table owner. A client forging a notification (a phishing
-- vector: "your question was approved, click here") must never succeed.
CREATE POLICY notifications_update ON notifications
  FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- ── D14: promotion clones the row ───────────────────────────────────────
-- One transaction: clone, decide the review request, notify. A partial
-- failure that promotes without notifying (or the reverse) is a bug an
-- integration test covers, not a state this procedure can leave behind.
CREATE OR REPLACE FUNCTION approve_review_request(
  p_request_id    uuid,
  p_decision_note text DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  req         review_requests%ROWTYPE;
  new_id      uuid;
  notif_title text;
BEGIN
  IF NOT is_admin() THEN
    RAISE EXCEPTION 'only an admin may approve a review request';
  END IF;

  SELECT * INTO req FROM review_requests WHERE id = p_request_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'review request % not found', p_request_id;
  END IF;
  IF req.status <> 'pending' THEN
    RAISE EXCEPTION 'review request % is not pending (status=%)', p_request_id, req.status;
  END IF;

  IF req.kind = 'question' THEN
    INSERT INTO questions (
      ref, tier, status, module, topic, question, difficulty, frequency,
      target_roles, institutions, verification_level, source_description,
      source_url, secondary_sources, follow_up_questions, answer_key,
      author_id, source_question_id
    )
    SELECT
      'V' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8),
      'verified', 'published',
      module, topic, question, difficulty, frequency, target_roles,
      institutions, verification_level, source_description, source_url,
      secondary_sources, follow_up_questions, answer_key,
      auth.uid(), id
    FROM questions WHERE id = req.question_id
    RETURNING id INTO new_id;

    notif_title := 'Your question was promoted to the verified bank';
  ELSE
    INSERT INTO knowledge_docs (
      slug, tier, status, title, summary, body_md, modules, topics,
      related_slugs, verification_level, source_url, origin, author_id, source_doc_id
    )
    SELECT
      left(slug || '_v' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8), 64),
      'verified', 'published',
      title, summary, body_md, modules, topics, related_slugs,
      verification_level, source_url, origin, auth.uid(), id
    FROM knowledge_docs WHERE id = req.doc_id
    RETURNING id INTO new_id;

    notif_title := 'Your knowledge document was promoted to the verified bank';
  END IF;

  UPDATE review_requests
    SET status = 'approved', decided_by = auth.uid(), decision_note = p_decision_note,
        promoted_id = new_id, decided_at = now()
    WHERE id = p_request_id;

  INSERT INTO notifications (user_id, kind, title, body, link_kind, link_id)
  VALUES (req.requester_id, 'submission_approved', notif_title, p_decision_note, req.kind, new_id);

  RETURN new_id;
END;
$$;

-- A rejection reason is required — it is shown to the author, and "no" with
-- no reason is not a usable review outcome.
CREATE OR REPLACE FUNCTION reject_review_request(
  p_request_id    uuid,
  p_decision_note text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  req review_requests%ROWTYPE;
BEGIN
  IF NOT is_admin() THEN
    RAISE EXCEPTION 'only an admin may reject a review request';
  END IF;
  IF p_decision_note IS NULL OR length(trim(p_decision_note)) = 0 THEN
    RAISE EXCEPTION 'a decision note is required when rejecting a review request';
  END IF;

  SELECT * INTO req FROM review_requests WHERE id = p_request_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'review request % not found', p_request_id;
  END IF;
  IF req.status <> 'pending' THEN
    RAISE EXCEPTION 'review request % is not pending (status=%)', p_request_id, req.status;
  END IF;

  UPDATE review_requests
    SET status = 'rejected', decided_by = auth.uid(), decision_note = p_decision_note,
        decided_at = now()
    WHERE id = p_request_id;

  INSERT INTO notifications (user_id, kind, title, body, link_kind, link_id)
  VALUES (
    req.requester_id, 'submission_rejected', 'Your submission was not approved',
    p_decision_note, req.kind, coalesce(req.question_id, req.doc_id)
  );
END;
$$;

-- ── Comment notifications ───────────────────────────────────────────────
-- Trigger-written, on the same transaction as the comment, so "commented but
-- never notified" cannot happen. Self-notifications are suppressed.
CREATE OR REPLACE FUNCTION notify_on_comment()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  target_author uuid;
  parent_author uuid;
  preview       text;
BEGIN
  preview := left(NEW.body, 120);

  IF NEW.parent_id IS NOT NULL THEN
    SELECT author_id INTO parent_author FROM comments WHERE id = NEW.parent_id;
    IF parent_author IS NOT NULL AND parent_author <> NEW.author_id THEN
      INSERT INTO notifications (user_id, kind, title, body, link_kind, link_id)
      VALUES (parent_author, 'reply_to_comment', 'Someone replied to your comment',
              preview, NEW.kind, coalesce(NEW.question_id, NEW.doc_id));
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.kind = 'question' THEN
    SELECT author_id INTO target_author FROM questions WHERE id = NEW.question_id;
  ELSE
    SELECT author_id INTO target_author FROM knowledge_docs WHERE id = NEW.doc_id;
  END IF;

  IF target_author IS NOT NULL AND target_author <> NEW.author_id THEN
    INSERT INTO notifications (user_id, kind, title, body, link_kind, link_id)
    VALUES (target_author, 'comment_on_content', 'Someone commented on your content',
            preview, NEW.kind, coalesce(NEW.question_id, NEW.doc_id));
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER comments_notify
  AFTER INSERT ON comments
  FOR EACH ROW EXECUTE FUNCTION notify_on_comment();
