"""Unit tests guarding the controlled vocabulary's internal consistency."""

from __future__ import annotations

from core.models.enums import TOPICS_BY_MODULE, Module


def test_every_module_has_topics() -> None:
    for module in Module:
        assert module in TOPICS_BY_MODULE
        assert len(TOPICS_BY_MODULE[module]) > 0


def test_no_duplicate_topics_within_a_module() -> None:
    for module, topics in TOPICS_BY_MODULE.items():
        assert len(topics) == len(set(topics)), f"duplicate topic in {module}"
