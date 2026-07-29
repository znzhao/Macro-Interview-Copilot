#!/usr/bin/env python
"""CI gate over content/questions/seed/*.json.

Fails the build on: schema non-conformance, duplicate or non-continuous `ref`
values, a module/topic outside the controlled vocabulary, a verified-tier
question missing source_url, or near-duplicate questions.
See docs/CONTENT_SPEC.md #4.1.

URL liveness checking is deliberately NOT here — it's a separate, non-blocking
scheduled job. Link rot must not block an unrelated merge.

Usage:
    python scripts/validate_content.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError
from rapidfuzz import fuzz

# Make `core` importable when this file is run directly (e.g. from an IDE's Run
# button) without requiring PYTHONPATH to be set by the caller.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from core.models.question import QuestionDraft  # noqa: E402

SEED_DIR = _REPO_ROOT / "content" / "questions" / "seed"

_REF_PATTERN = re.compile(r"^Q(\d{4,})$")
_NEAR_DUPLICATE_THRESHOLD = 85.0


def _load_all_records() -> list[tuple[Path, dict[str, object]]]:
    records: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(SEED_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        questions = payload.get("questions", payload if isinstance(payload, list) else [])
        for record in questions:
            records.append((path, record))
    return records


def main() -> int:
    if not SEED_DIR.exists():
        print(f"FATAL: seed directory does not exist: {SEED_DIR}", file=sys.stderr)
        return 1

    records = _load_all_records()
    if not records:
        print("No seed records found — nothing to validate.")
        return 0

    errors: list[str] = []
    seen_refs: dict[str, Path] = {}
    seen_questions: list[tuple[str, str]] = []  # (ref, question text)

    for path, record in records:
        ref = str(record.get("ref", "<missing ref>"))

        # Schema conformance, including the tier/source and module/topic rules
        # already enforced by the Pydantic model.
        try:
            draft = QuestionDraft.model_validate(record)
        except ValidationError as exc:
            errors.append(f"{path.name}: {ref}: schema invalid:\n{exc}")
            continue

        # ref uniqueness
        if ref in seen_refs:
            errors.append(f"{path.name}: duplicate ref {ref!r} (also in {seen_refs[ref].name})")
        else:
            seen_refs[ref] = path

        # ref shape, for the verified-tier sequential numbering convention
        if draft.tier.value == "verified" and not _REF_PATTERN.match(ref):
            errors.append(f"{path.name}: {ref}: verified questions must match Q<digits>")

        # near-duplicate detection against everything seen so far
        for other_ref, other_text in seen_questions:
            score = fuzz.token_set_ratio(draft.question, other_text)
            if score >= _NEAR_DUPLICATE_THRESHOLD:
                errors.append(
                    f"{path.name}: {ref}: near-duplicate of {other_ref} "
                    f"(similarity {score:.0f})"
                )
        seen_questions.append((ref, draft.question))

    # ref continuity for verified questions specifically
    verified_numbers = sorted(
        int(m.group(1))
        for ref in seen_refs
        if (m := _REF_PATTERN.match(ref))
    )
    for expected, actual in enumerate(verified_numbers, start=1):
        if expected != actual:
            errors.append(
                f"verified ref numbering is not continuous: expected Q{expected:04d}, "
                f"found gap before Q{actual:04d}"
            )
            break

    if errors:
        print(f"Content validation FAILED with {len(errors)} error(s):\n", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Content validation passed: {len(records)} question(s), {len(seen_refs)} unique refs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
