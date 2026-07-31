"""RLS isolation tests for the Phase 2 tables (migrations 0003-0005).

Same discipline as test_rls_policies.py: real local Postgres, real migrations,
the non-superuser app_user role so RLS actually applies. See
docs/IMPLEMENTATION_GUIDE.md #5.2 and docs/DATA_SPEC.md #6.3.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.conftest import as_user

pytestmark = pytest.mark.integration


def _insert_question(
    conn: psycopg.Connection,
    *,
    tier: str,
    status: str,
    owner_id: uuid.UUID | None,
    author_id: uuid.UUID | None,
    ref: str,
    answer_key: str = "{}",
) -> uuid.UUID:
    row = conn.execute(
        """
        INSERT INTO questions
            (ref, tier, status, module, topic, question, difficulty,
             verification_level, owner_id, author_id, answer_key)
        VALUES (%s, %s, %s, 'Inflation', 'Inflation Dynamics',
                'Why can inflation remain persistent despite restrictive policy?',
                'hard', 'ai_generated', %s, %s, %s::jsonb)
        RETURNING id
        """,
        (ref, tier, status, owner_id, author_id, answer_key),
    ).fetchone()
    conn.commit()
    return row[0]


def _insert_knowledge_doc(
    conn: psycopg.Connection,
    *,
    tier: str,
    status: str,
    owner_id: uuid.UUID | None,
    author_id: uuid.UUID | None,
    slug: str,
) -> uuid.UUID:
    row = conn.execute(
        """
        INSERT INTO knowledge_docs
            (slug, tier, status, title, summary, body_md, verification_level,
             owner_id, author_id)
        VALUES (%s, %s, %s, 'The Yield Curve', 'A short summary.',
                'Body text.', 'ai_generated', %s, %s)
        RETURNING id
        """,
        (slug, tier, status, owner_id, author_id),
    ).fetchone()
    conn.commit()
    return row[0]


def _make_admin(conn: psycopg.Connection, make_user) -> uuid.UUID:  # noqa: ANN001
    admin_id = make_user()
    conn.execute("UPDATE profiles SET is_admin = true WHERE id = %s", (admin_id,))
    conn.commit()
    return admin_id


class TestKnowledgeDocsVisibility:
    def test_private_doc_not_visible_to_other_users(self, pg_conn, make_user) -> None:
        owner = make_user()
        viewer = make_user()
        doc_id = _insert_knowledge_doc(
            pg_conn, tier="private", status="draft", owner_id=owner, author_id=owner, slug="doc_a"
        )

        with as_user(pg_conn, viewer):
            rows = pg_conn.execute(
                "SELECT id FROM knowledge_docs WHERE id = %s", (doc_id,)
            ).fetchall()

        assert rows == []

    def test_published_verified_doc_visible_to_everyone(self, pg_conn, make_user) -> None:
        viewer = make_user()
        doc_id = _insert_knowledge_doc(
            pg_conn,
            tier="verified",
            status="published",
            owner_id=None,
            author_id=None,
            slug="doc_b",
        )

        with as_user(pg_conn, viewer):
            rows = pg_conn.execute(
                "SELECT id FROM knowledge_docs WHERE id = %s", (doc_id,)
            ).fetchall()

        assert len(rows) == 1

    def test_only_admin_can_insert_verified_tier(self, pg_conn, make_user) -> None:
        non_admin = make_user()

        with as_user(pg_conn, non_admin), pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg_conn.execute(
                """
                INSERT INTO knowledge_docs
                    (slug, tier, status, title, summary, body_md, verification_level, author_id)
                VALUES ('doc_c', 'verified', 'published', 'Title', 'Summary', 'Body',
                        'ai_generated', %s)
                """,
                (non_admin,),
            )


class TestVotesRequirePublishedTarget:
    def test_cannot_vote_on_a_private_question(self, pg_conn, make_user) -> None:
        owner = make_user()
        voter = make_user()
        qid = _insert_question(
            pg_conn, tier="private", status="draft", owner_id=owner, author_id=owner, ref="N-vote-1"
        )

        with as_user(pg_conn, voter), pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg_conn.execute(
                "INSERT INTO question_votes (question_id, user_id, value) VALUES (%s, %s, -1)",
                (qid, voter),
            )

    def test_changing_a_vote_is_an_update(self, pg_conn, make_user) -> None:
        author = make_user()
        voter = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=None,
            author_id=author,
            ref="N-vote-2",
        )

        with as_user(pg_conn, voter):
            pg_conn.execute(
                "INSERT INTO question_votes (question_id, user_id, value) VALUES (%s, %s, 1)",
                (qid, voter),
            )
            pg_conn.execute(
                "UPDATE question_votes SET value = -1 WHERE question_id = %s AND user_id = %s",
                (qid, voter),
            )

        counts = pg_conn.execute(
            "SELECT upvotes, downvotes FROM questions WHERE id = %s", (qid,)
        ).fetchone()
        assert counts == (0, 1)


class TestCommentVisibility:
    def test_cannot_comment_on_a_private_question(self, pg_conn, make_user) -> None:
        owner = make_user()
        commenter = make_user()
        qid = _insert_question(
            pg_conn, tier="private", status="draft", owner_id=owner, author_id=owner, ref="N-cmt-1"
        )

        with as_user(pg_conn, commenter), pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg_conn.execute(
                "INSERT INTO comments (kind, question_id, author_id, body) "
                "VALUES ('question', %s, %s, 'nice question')",
                (qid, commenter),
            )

    def test_comment_on_published_question_visible_to_others(self, pg_conn, make_user) -> None:
        author = make_user()
        commenter = make_user()
        other_viewer = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=None,
            author_id=author,
            ref="N-cmt-2",
        )

        with as_user(pg_conn, commenter):
            pg_conn.execute(
                "INSERT INTO comments (kind, question_id, author_id, body) "
                "VALUES ('question', %s, %s, 'nice question')",
                (qid, commenter),
            )

        with as_user(pg_conn, other_viewer):
            rows = pg_conn.execute(
                "SELECT body FROM comments WHERE question_id = %s", (qid,)
            ).fetchall()

        assert rows == [("nice question",)]

    def test_reply_to_reply_is_rejected(self, pg_conn, make_user) -> None:
        author = make_user()
        commenter = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=None,
            author_id=author,
            ref="N-cmt-3",
        )

        with as_user(pg_conn, commenter):
            top = pg_conn.execute(
                "INSERT INTO comments (kind, question_id, author_id, body) "
                "VALUES ('question', %s, %s, 'top level') RETURNING id",
                (qid, commenter),
            ).fetchone()[0]
            reply = pg_conn.execute(
                "INSERT INTO comments (kind, question_id, parent_id, author_id, body) "
                "VALUES ('question', %s, %s, %s, 'a reply') RETURNING id",
                (qid, top, commenter),
            ).fetchone()[0]

            with pytest.raises(psycopg.errors.RaiseException):
                pg_conn.execute(
                    "INSERT INTO comments (kind, question_id, parent_id, author_id, body) "
                    "VALUES ('question', %s, %s, %s, 'reply to a reply')",
                    (qid, reply, commenter),
                )

    def test_cannot_edit_another_users_comment(self, pg_conn, make_user) -> None:
        author = make_user()
        commenter = make_user()
        intruder = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=None,
            author_id=author,
            ref="N-cmt-4",
        )

        with as_user(pg_conn, commenter):
            pg_conn.execute(
                "INSERT INTO comments (kind, question_id, author_id, body) "
                "VALUES ('question', %s, %s, 'original') RETURNING id",
                (qid, commenter),
            )

        with as_user(pg_conn, intruder):
            pg_conn.execute("UPDATE comments SET body = 'hijacked' WHERE question_id = %s", (qid,))

        rows = pg_conn.execute(
            "SELECT body FROM comments WHERE question_id = %s", (qid,)
        ).fetchall()
        assert rows == [("original",)]


class TestReviewRequests:
    def test_cannot_submit_content_you_do_not_own(self, pg_conn, make_user) -> None:
        owner = make_user()
        intruder = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=owner,
            author_id=owner,
            ref="N-rr-1",
        )

        with as_user(pg_conn, intruder), pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg_conn.execute(
                "INSERT INTO review_requests (kind, question_id, requester_id) "
                "VALUES ('question', %s, %s)",
                (qid, intruder),
            )

    def test_requester_cannot_see_another_users_review_request(self, pg_conn, make_user) -> None:
        owner_a = make_user()
        owner_b = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=owner_a,
            author_id=owner_a,
            ref="N-rr-2",
        )

        with as_user(pg_conn, owner_a):
            pg_conn.execute(
                "INSERT INTO review_requests (kind, question_id, requester_id) "
                "VALUES ('question', %s, %s)",
                (qid, owner_a),
            )

        with as_user(pg_conn, owner_b):
            rows = pg_conn.execute(
                "SELECT id FROM review_requests WHERE question_id = %s", (qid,)
            ).fetchall()

        assert rows == []

    def test_non_admin_cannot_call_approve_review_request(self, pg_conn, make_user) -> None:
        owner = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=owner,
            author_id=owner,
            ref="N-rr-3",
        )

        with as_user(pg_conn, owner):
            req_id = pg_conn.execute(
                "INSERT INTO review_requests (kind, question_id, requester_id) "
                "VALUES ('question', %s, %s) RETURNING id",
                (qid, owner),
            ).fetchone()[0]

            with pytest.raises(psycopg.errors.RaiseException, match="only an admin"):
                pg_conn.execute("SELECT approve_review_request(%s)", (req_id,))

    def test_admin_approval_clones_and_notifies(self, pg_conn, make_user) -> None:
        admin = _make_admin(pg_conn, make_user)
        owner = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=owner,
            author_id=owner,
            ref="N-rr-4",
            answer_key='{"framework": ["a bullet"]}',
        )

        with as_user(pg_conn, owner):
            req_id = pg_conn.execute(
                "INSERT INTO review_requests (kind, question_id, requester_id) "
                "VALUES ('question', %s, %s) RETURNING id",
                (qid, owner),
            ).fetchone()[0]

        with as_user(pg_conn, admin):
            new_id = pg_conn.execute(
                "SELECT approve_review_request(%s, 'good question')", (req_id,)
            ).fetchone()[0]

        clone_tier, source_id = pg_conn.execute(
            "SELECT tier, source_question_id FROM questions WHERE id = %s", (new_id,)
        ).fetchone()
        original_tier = pg_conn.execute(
            "SELECT tier FROM questions WHERE id = %s", (qid,)
        ).fetchone()[0]

        with as_user(pg_conn, owner):
            notif = pg_conn.execute(
                "SELECT title, link_id FROM notifications WHERE user_id = %s", (owner,)
            ).fetchone()

        assert clone_tier == "verified"
        assert source_id == qid
        assert original_tier == "community"  # the original is never mutated
        assert notif == ("Your question was promoted to the verified bank", new_id)

    def test_rejection_requires_a_decision_note(self, pg_conn, make_user) -> None:
        admin = _make_admin(pg_conn, make_user)
        owner = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=owner,
            author_id=owner,
            ref="N-rr-5",
        )

        with as_user(pg_conn, owner):
            req_id = pg_conn.execute(
                "INSERT INTO review_requests (kind, question_id, requester_id) "
                "VALUES ('question', %s, %s) RETURNING id",
                (qid, owner),
            ).fetchone()[0]

        with (
            as_user(pg_conn, admin),
            pytest.raises(psycopg.errors.RaiseException, match="decision note"),
        ):
            pg_conn.execute("SELECT reject_review_request(%s, NULL)", (req_id,))


class TestNotifications:
    def test_client_cannot_forge_a_notification(self, pg_conn, make_user) -> None:
        """The single most important test in this file: notifications are
        trigger-written only, so a forged 'your question was approved, click
        here' notification must be structurally impossible, not merely
        discouraged. See docs/DECISIONS.md D15.
        """
        victim = make_user()
        attacker = make_user()

        with as_user(pg_conn, attacker), pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg_conn.execute(
                "INSERT INTO notifications (user_id, kind, title) "
                "VALUES (%s, 'submission_approved', 'Click here to claim your prize')",
                (victim,),
            )

    def test_user_cannot_read_another_users_notifications(self, pg_conn, make_user) -> None:
        admin = _make_admin(pg_conn, make_user)
        owner = make_user()
        intruder = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=owner,
            author_id=owner,
            ref="N-notif-1",
        )

        with as_user(pg_conn, owner):
            req_id = pg_conn.execute(
                "INSERT INTO review_requests (kind, question_id, requester_id) "
                "VALUES ('question', %s, %s) RETURNING id",
                (qid, owner),
            ).fetchone()[0]

        with as_user(pg_conn, admin):
            pg_conn.execute("SELECT approve_review_request(%s)", (req_id,))

        with as_user(pg_conn, intruder):
            rows = pg_conn.execute(
                "SELECT id FROM notifications WHERE user_id = %s", (owner,)
            ).fetchall()

        assert rows == []

    def test_comment_notifies_the_content_author_but_not_self(self, pg_conn, make_user) -> None:
        author = make_user()
        commenter = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="published",
            owner_id=None,
            author_id=author,
            ref="N-notif-2",
        )

        # The author commenting on their own question generates no self-notification.
        with as_user(pg_conn, author):
            pg_conn.execute(
                "INSERT INTO comments (kind, question_id, author_id, body) "
                "VALUES ('question', %s, %s, 'self comment')",
                (qid, author),
            )
        with as_user(pg_conn, author):
            self_notifs = pg_conn.execute(
                "SELECT id FROM notifications WHERE user_id = %s", (author,)
            ).fetchall()
        assert self_notifs == []

        # A different user's comment does notify the author.
        with as_user(pg_conn, commenter):
            pg_conn.execute(
                "INSERT INTO comments (kind, question_id, author_id, body) "
                "VALUES ('question', %s, %s, 'a real comment')",
                (qid, commenter),
            )
        with as_user(pg_conn, author):
            notifs = pg_conn.execute(
                "SELECT kind FROM notifications WHERE user_id = %s", (author,)
            ).fetchall()
        assert notifs == [("comment_on_content",)]
