"""RLS isolation tests — mandatory per docs/IMPLEMENTATION_GUIDE.md #5.2.

For each table that carries per-user data, assert that user A cannot read or
write user B's rows. Runs against a real local Postgres with the actual
migrations applied (see conftest.py) — not mocks.
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
) -> uuid.UUID:
    row = conn.execute(
        """
        INSERT INTO questions
            (ref, tier, status, module, topic, question, difficulty,
             verification_level, source_url, owner_id, author_id)
        VALUES (%s, %s, %s, 'Inflation', 'Inflation Dynamics',
                'Why can inflation remain persistent despite restrictive policy?',
                'hard', 'verified_interview', 'https://www.imf.org', %s, %s)
        RETURNING id
        """,
        (ref, tier, status, owner_id, author_id),
    ).fetchone()
    conn.commit()
    return row[0]


class TestProfilesIsolation:
    def test_user_cannot_read_another_users_profile(self, pg_conn, make_user) -> None:
        user_a = make_user()
        user_b = make_user()

        with as_user(pg_conn, user_a):
            rows = pg_conn.execute("SELECT id FROM profiles WHERE id = %s", (user_b,)).fetchall()

        assert rows == []

    def test_user_can_read_own_profile(self, pg_conn, make_user) -> None:
        user_a = make_user()

        with as_user(pg_conn, user_a):
            rows = pg_conn.execute("SELECT id FROM profiles WHERE id = %s", (user_a,)).fetchall()

        assert len(rows) == 1


class TestQuestionsVisibility:
    def test_private_question_not_visible_to_other_users(self, pg_conn, make_user) -> None:
        owner = make_user()
        other = make_user()
        qid = _insert_question(
            pg_conn, tier="private", status="draft", owner_id=owner, author_id=owner, ref="P0001"
        )

        with as_user(pg_conn, other):
            rows = pg_conn.execute("SELECT id FROM questions WHERE id = %s", (qid,)).fetchall()

        assert rows == []

    def test_private_question_visible_to_owner(self, pg_conn, make_user) -> None:
        owner = make_user()
        qid = _insert_question(
            pg_conn, tier="private", status="draft", owner_id=owner, author_id=owner, ref="P0002"
        )

        with as_user(pg_conn, owner):
            rows = pg_conn.execute("SELECT id FROM questions WHERE id = %s", (qid,)).fetchall()

        assert len(rows) == 1

    def test_published_verified_question_visible_to_everyone(self, pg_conn, make_user) -> None:
        admin = make_user()
        pg_conn.execute("UPDATE profiles SET is_admin = true WHERE id = %s", (admin,))
        pg_conn.commit()
        viewer = make_user()

        qid = _insert_question(
            pg_conn,
            tier="verified",
            status="published",
            owner_id=None,
            author_id=admin,
            ref="V0001",
        )

        with as_user(pg_conn, viewer):
            rows = pg_conn.execute("SELECT id FROM questions WHERE id = %s", (qid,)).fetchall()

        assert len(rows) == 1

    def test_draft_community_question_not_visible_until_published(self, pg_conn, make_user) -> None:
        author = make_user()
        viewer = make_user()
        qid = _insert_question(
            pg_conn,
            tier="community",
            status="draft",
            owner_id=None,
            author_id=author,
            ref="C0001",
        )

        with as_user(pg_conn, viewer):
            rows = pg_conn.execute("SELECT id FROM questions WHERE id = %s", (qid,)).fetchall()

        assert rows == []

    def test_only_admin_can_insert_verified_tier(self, pg_conn, make_user) -> None:
        non_admin = make_user()

        with as_user(pg_conn, non_admin), pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg_conn.execute(
                """
                INSERT INTO questions
                    (ref, tier, status, module, topic, question, difficulty,
                     verification_level, source_url, author_id)
                VALUES ('V9999', 'verified', 'published', 'Inflation', 'Inflation Dynamics',
                        'Why can inflation remain persistent despite restrictive policy?',
                        'hard', 'verified_interview', 'https://www.imf.org', %s)
                """,
                (non_admin,),
            )
        pg_conn.rollback()


class TestInterviewDataIsolation:
    def test_user_cannot_read_another_users_sessions(self, pg_conn, make_user) -> None:
        user_a = make_user()
        user_b = make_user()

        with as_user(pg_conn, user_a):
            pg_conn.execute(
                "INSERT INTO interview_sessions (user_id, mode) VALUES (%s, 'hedge_fund')",
                (user_a,),
            )
            pg_conn.commit()

        with as_user(pg_conn, user_b):
            rows = pg_conn.execute(
                "SELECT id FROM interview_sessions WHERE user_id = %s", (user_a,)
            ).fetchall()

        assert rows == []

    def test_user_cannot_read_turns_of_another_users_session(self, pg_conn, make_user) -> None:
        """interview_turns has no user_id column; its policy joins through
        interview_sessions. This is the easiest policy to get wrong.
        """
        user_a = make_user()
        user_b = make_user()

        with as_user(pg_conn, user_a):
            session_row = pg_conn.execute(
                "INSERT INTO interview_sessions (user_id, mode) VALUES (%s, 'hedge_fund') "
                "RETURNING id",
                (user_a,),
            ).fetchone()
            session_id = session_row[0]
            pg_conn.execute(
                "INSERT INTO interview_turns (session_id, ordinal, question_text) "
                "VALUES (%s, 1, 'Sample question text')",
                (session_id,),
            )
            pg_conn.commit()

        with as_user(pg_conn, user_b):
            rows = pg_conn.execute(
                "SELECT id FROM interview_turns WHERE session_id = %s", (session_id,)
            ).fetchall()

        assert rows == []

    def test_user_cannot_read_another_users_evaluations(self, pg_conn, make_user) -> None:
        user_a = make_user()
        user_b = make_user()

        with as_user(pg_conn, user_a):
            session_row = pg_conn.execute(
                "INSERT INTO interview_sessions (user_id, mode) VALUES (%s, 'hedge_fund') "
                "RETURNING id",
                (user_a,),
            ).fetchone()
            turn_row = pg_conn.execute(
                "INSERT INTO interview_turns (session_id, ordinal, question_text) "
                "VALUES (%s, 1, 'Sample question text') RETURNING id",
                (session_row[0],),
            ).fetchone()
            pg_conn.execute(
                """
                INSERT INTO evaluations
                    (turn_id, user_id, score_framework, score_logic, score_evidence,
                     score_market, score_communication, total_score, model, prompt_version)
                VALUES (%s, %s, 3, 3, 2, 3, 4, 70, 'test-model', 'evaluator.v1')
                """,
                (turn_row[0], user_a),
            )
            pg_conn.commit()

        with as_user(pg_conn, user_b):
            rows = pg_conn.execute(
                "SELECT id FROM evaluations WHERE user_id = %s", (user_a,)
            ).fetchall()

        assert rows == []


class TestNotesAndFavoritesIsolation:
    def test_user_cannot_read_another_users_notes(self, pg_conn, make_user) -> None:
        user_a = make_user()
        user_b = make_user()
        qid = _insert_question(
            pg_conn, tier="private", status="draft", owner_id=user_a, author_id=user_a, ref="N0001"
        )

        with as_user(pg_conn, user_a):
            pg_conn.execute(
                "INSERT INTO notes (user_id, question_id, content) VALUES (%s, %s, 'my note')",
                (user_a, qid),
            )
            pg_conn.commit()

        with as_user(pg_conn, user_b):
            rows = pg_conn.execute("SELECT id FROM notes WHERE user_id = %s", (user_a,)).fetchall()

        assert rows == []

    def test_user_cannot_modify_another_users_favorites(self, pg_conn, make_user) -> None:
        user_a = make_user()
        user_b = make_user()
        qid = _insert_question(
            pg_conn, tier="private", status="draft", owner_id=user_a, author_id=user_a, ref="N0002"
        )

        # WITH CHECK *raises* on a violating INSERT, unlike USING, which silently
        # filters rows on read. Favoriting on someone else's behalf is therefore a
        # hard error, not a no-op that quietly writes zero rows.
        with as_user(pg_conn, user_b), pytest.raises(psycopg.errors.InsufficientPrivilege):
            pg_conn.execute(
                "INSERT INTO favorites (user_id, question_id) VALUES (%s, %s)",
                (user_a, qid),
            )

        # Read back as the table owner (RLS bypassed) so this asserts the row is
        # genuinely absent, not merely invisible to the current role.
        rows = pg_conn.execute("SELECT 1 FROM favorites WHERE user_id = %s", (user_a,)).fetchall()
        assert rows == []
