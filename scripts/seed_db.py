#!/usr/bin/env python
"""Load content/questions/seed/*.json into Postgres. Idempotent upsert on `ref`.

Bootstraps a fresh database with the verified question bank. Safe to re-run —
existing rows are updated in place, matched by `ref`.
See docs/CONTENT_SPEC.md #4.

Usage:
    python scripts/seed_db.py --database-url postgresql://...
    python scripts/seed_db.py   # uses DATABASE_URL env var
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Json

# Make `core` importable when this file is run directly (e.g. from an IDE's Run
# button) without requiring PYTHONPATH to be set by the caller.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from core.models.question import QuestionDraft  # noqa: E402

SEED_DIR = _REPO_ROOT / "content" / "questions" / "seed"

_UPSERT_SQL = """
INSERT INTO questions (
    ref, tier, status, module, topic, question, difficulty, frequency,
    target_roles, institutions, verification_level, source_description,
    source_url, secondary_sources, follow_up_questions
) VALUES (
    %(ref)s, %(tier)s, 'published', %(module)s, %(topic)s, %(question)s,
    %(difficulty)s, %(frequency)s, %(target_roles)s, %(institutions)s,
    %(verification_level)s, %(source_description)s, %(source_url)s,
    %(secondary_sources)s, %(follow_up_questions)s
)
ON CONFLICT (ref) DO UPDATE SET
    module = EXCLUDED.module,
    topic = EXCLUDED.topic,
    question = EXCLUDED.question,
    difficulty = EXCLUDED.difficulty,
    frequency = EXCLUDED.frequency,
    target_roles = EXCLUDED.target_roles,
    institutions = EXCLUDED.institutions,
    verification_level = EXCLUDED.verification_level,
    source_description = EXCLUDED.source_description,
    source_url = EXCLUDED.source_url,
    secondary_sources = EXCLUDED.secondary_sources,
    follow_up_questions = EXCLUDED.follow_up_questions,
    updated_at = now()
"""


def _load_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(SEED_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        records.extend(payload.get("questions", payload if isinstance(payload, list) else []))
    return records


def seed(database_url: str) -> None:
    records = _load_records()
    if not records:
        print("No seed records found.")
        return

    with psycopg.connect(database_url, autocommit=False) as conn:
        for record in records:
            draft = QuestionDraft.model_validate(record)
            params = {
                "ref": record["ref"],
                "tier": draft.tier.value,
                "module": draft.module.value,
                "topic": draft.topic,
                "question": draft.question,
                "difficulty": draft.difficulty.value,
                "frequency": draft.frequency.value if draft.frequency else None,
                "target_roles": [r.value for r in draft.target_roles],
                "institutions": list(draft.institutions),
                "verification_level": draft.verification_level.value,
                "source_description": draft.source_description,
                "source_url": str(draft.source_url) if draft.source_url else None,
                "secondary_sources": Json(
                    [s.model_dump(mode="json") for s in draft.secondary_sources]
                ),
                "follow_up_questions": list(draft.follow_up_questions),
            }
            conn.execute(_UPSERT_SQL, params)
        conn.commit()

    print(f"Seeded {len(records)} question(s) from {SEED_DIR}.")


def main() -> None:
    load_dotenv(_REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    if not args.database_url:
        print(
            "No database URL found.\n"
            "Set DATABASE_URL in a .env file at the repo root (copy .env.example), "
            "or pass --database-url.",
            file=sys.stderr,
        )
        sys.exit(1)

    seed(args.database_url)


if __name__ == "__main__":
    main()
