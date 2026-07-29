"""Fixtures for integration tests against a real local Postgres instance.

These tests exercise the actual schema and RLS policies from
core/db/migrations/*.sql, not the Supabase-hosted PostgREST layer (that would
require the full Supabase local dev stack, out of scope for this test tier).

Setup (see docs/IMPLEMENTATION_GUIDE.md #1):
    docker run -d --name mic-pg -e POSTGRES_PASSWORD=postgres -p 5433:5432 postgres:16

Tests in this package are skipped automatically if no Postgres is reachable.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/postgres"
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "core" / "db" / "migrations"

# Minimal stand-in for the parts of Supabase's `auth` schema our migrations
# reference: an auth.users table to satisfy the FK on profiles, and an
# auth.uid() function whose result RLS policies read from a per-connection
# session variable we set in `as_user()`.
_AUTH_STUB_SQL = """
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text
);

CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE
AS $$
  SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;

-- A non-superuser role, mirroring Supabase's `authenticated` role. RLS is a
-- no-op for the table owner and for superusers, so the RLS tests must run
-- as this role or they would silently pass regardless of policy correctness.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END
$$;
"""

_GRANTS_SQL = """
GRANT USAGE ON SCHEMA public TO app_user;
GRANT USAGE ON SCHEMA auth TO app_user;
GRANT SELECT ON auth.users TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
"""


def _reset_database(conn: psycopg.Connection) -> None:
    conn.execute("DROP SCHEMA IF EXISTS public CASCADE;")
    conn.execute("DROP SCHEMA IF EXISTS auth CASCADE;")
    conn.execute("CREATE SCHEMA public;")
    conn.commit()


def _apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(_AUTH_STUB_SQL)
    conn.commit()
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = migration.read_text(encoding="utf-8")
        conn.execute(sql)
        conn.commit()
    conn.execute(_GRANTS_SQL)
    conn.commit()


@pytest.fixture(scope="session")
def _pg_available() -> bool:
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


@pytest.fixture()
def pg_conn(_pg_available: bool) -> Iterator[psycopg.Connection]:
    if not _pg_available:
        pytest.skip("no local Postgres reachable at TEST_DATABASE_URL")

    conn = psycopg.connect(TEST_DATABASE_URL, autocommit=False)
    _reset_database(conn)
    _apply_schema(conn)

    yield conn

    conn.rollback()
    conn.close()


@pytest.fixture()
def make_user(pg_conn: psycopg.Connection):
    """Insert an auth.users row (and its profile, via the signup trigger) and
    return the new user's id.
    """

    def _make(email: str | None = None) -> uuid.UUID:
        user_id = uuid.uuid4()
        pg_conn.execute(
            "INSERT INTO auth.users (id, email) VALUES (%s, %s)",
            (user_id, email or f"{user_id}@example.com"),
        )
        pg_conn.commit()
        return user_id

    return _make


@contextmanager
def as_user(conn: psycopg.Connection, user_id: uuid.UUID | None) -> Iterator[None]:
    """Scope subsequent queries on `conn` to run as `user_id` for RLS purposes,
    mirroring how PostgREST sets request.jwt.claim.sub from the caller's JWT and
    executes as the `authenticated` role. Pass None for the anonymous role.

    Runs as the non-superuser `app_user` role so RLS policies actually apply —
    the table-owning superuser bypasses RLS entirely and would make every test
    here pass regardless of whether the policies are correct.
    """
    claim = "" if user_id is None else str(user_id)
    conn.execute("SET ROLE app_user")
    conn.execute("SELECT set_config('request.jwt.claim.sub', %s, false)", (claim,))
    try:
        yield
    finally:
        conn.execute("SELECT set_config('request.jwt.claim.sub', '', false)")
        conn.execute("RESET ROLE")
