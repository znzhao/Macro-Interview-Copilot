"""Evaluation and mastery domain models. See docs/DATA_SPEC.md #4.3, #5.1, docs/AI_SPEC.md #3."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DIMENSIONS = ("framework", "logic", "evidence", "market", "communication")


class Evaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    turn_id: UUID
    user_id: UUID
    score_framework: int = Field(ge=0, le=4)
    score_logic: int = Field(ge=0, le=4)
    score_evidence: int = Field(ge=0, le=4)
    score_market: int = Field(ge=0, le=4)
    score_communication: int = Field(ge=0, le=4)
    total_score: int = Field(ge=0, le=100)
    justifications: dict[str, str] = Field(default_factory=dict)
    strengths: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    improved_outline: str | None = None
    suggested_readings: tuple[str, ...] = ()
    model: str
    prompt_version: str
    raw_response: dict[str, object] | None = None
    created_at: datetime

    @property
    def dimension_scores(self) -> dict[str, int]:
        return {
            "framework": self.score_framework,
            "logic": self.score_logic,
            "evidence": self.score_evidence,
            "market": self.score_market,
            "communication": self.score_communication,
        }

    @model_validator(mode="after")
    def _justifications_key_check(self) -> Evaluation:
        unknown = set(self.justifications) - set(DIMENSIONS)
        if unknown:
            raise ValueError(f"justifications has unknown dimension keys: {unknown}")
        return self


class TopicMastery(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    module: str
    topic: str
    attempts: int = Field(ge=0)
    ewma_framework: float = Field(ge=0, le=4)
    ewma_logic: float = Field(ge=0, le=4)
    ewma_evidence: float = Field(ge=0, le=4)
    ewma_market: float = Field(ge=0, le=4)
    ewma_communication: float = Field(ge=0, le=4)
    ewma_total: float = Field(ge=0, le=100)
    last_practiced_at: datetime
