#!/usr/bin/env python
"""Export verified-tier questions from Postgres to content/questions/seed/.

Postgres is the live bank (D5); this script keeps the Git snapshot in sync.
Run before every release, or the snapshot goes stale.
See docs/DECISIONS.md D5, docs/CONTENT_SPEC.md #4.

Usage:
    python scripts/export_questions.py --database-url postgresql://...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

_REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = _REPO_ROOT / "content" / "questions" / "seed"
BATCH_SIZE = 200

_SELECT_SQL = """
SELECT ref, tier, module, topic, question, difficulty, frequency,
       target_roles, institutions, verification_level, source_description,
       source_url, secondary_sources, follow_up_questions
FROM questions
WHERE tier = 'verified' AND status = 'published'
ORDER BY ref
"""


def _row_to_record(row: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in row.items() if v is not None}


def export_questions(database_url: str) -> None:
    SEED_DIR.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(_SELECT_SQL).fetchall()

    if not rows:
        print("No verified/published questions to export.")
        return

    # Clear prior export batches so a shrinking bank doesn't leave stale files.
    for old in SEED_DIR.glob("verified_*.json"):
        old.unlink()

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        records = [_row_to_record(row) for row in batch]
        first_ref, last_ref = records[0]["ref"], records[-1]["ref"]
        out_path = SEED_DIR / f"verified_{first_ref}-{last_ref}.json"
        out_path.write_text(
            json.dumps({"questions": records}, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {out_path.name} ({len(records)} questions)")

    print(f"Exported {len(rows)} verified question(s) to {SEED_DIR}.")


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

    export_questions(args.database_url)


if __name__ == "__main__":
    main()
