"""Answer key domain model. See docs/DATA_SPEC.md #3.3, #10.1 and docs/DECISIONS.md D10.

Five sections of short bullets, never prose. The limits ARE the guardrail: at
most 8 bullets of at most 240 characters each, no embedded newlines. A bulleted
skeleton that tight cannot be recited as an interview answer — the candidate
still has to build the argument. The same shape is enforced independently by
answer_key_is_valid() in core/db/migrations/0003_content_governance.sql, so no
write path — Python bug or direct SQL — can produce a prose answer.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# No \n or \r anywhere in a bullet — that's what keeps a "bullet" from being a
# smuggled paragraph.
Bullet = Annotated[
    str,
    StringConstraints(min_length=1, max_length=240, pattern=r"^[^\n\r]*$"),
]
Section = Annotated[tuple[Bullet, ...], Field(max_length=8)]


class AnswerKey(BaseModel):
    """extra="forbid" matters: a model that invents a sixth section is a
    validation failure, not a silently dropped field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    framework: Section = ()
    mechanism: Section = ()
    indicators: Section = ()
    market_implication: Section = ()
    common_traps: Section = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.framework
            or self.mechanism
            or self.indicators
            or self.market_implication
            or self.common_traps
        )
