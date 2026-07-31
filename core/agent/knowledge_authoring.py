"""Knowledge document authoring: one-click and agentic refinement. See
docs/CONTENT_SPEC.md #6.3. Mirrors core/agent/authoring.py for questions —
same two paths, same submit-tool termination, same "manual edits win" rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core.agent.limits import DEFAULT_CAPS, UsageCaps, check_grounding_budget
from core.agent.loop import AgentOutcome, run_agent_loop
from core.agent.tools.registry import ToolContext
from core.llm.base import LLMProvider, Message
from core.llm.schemas import KnowledgeDraftSchema
from core.models.knowledge import KnowledgeDoc
from core.prompts.loader import load_prompt

_AUTHORING_TEMPERATURE = 0.7


@dataclass(frozen=True)
class KnowledgeAuthoringRequest:
    topic: str
    material: str = ""


def one_click_knowledge_draft(
    *, provider: LLMProvider, model: str, request: KnowledgeAuthoringRequest
) -> KnowledgeDraftSchema:
    system = load_prompt("knowledge_author", "v1").render(
        topic=request.topic, material=request.material
    )
    result = provider.complete_structured(
        system=system,
        user="Produce the knowledge document now, following the schema exactly.",
        schema=KnowledgeDraftSchema.model_json_schema(),
        model=model,
        temperature=_AUTHORING_TEMPERATURE,
    )
    return KnowledgeDraftSchema.model_validate(result.data)


def _render_grounding(docs: Sequence[KnowledgeDoc]) -> str:
    if not docs:
        return ""
    sections = "\n\n".join(f"### {doc.title}\n\n{doc.body_md}" for doc in docs)
    return f"\n\n# Related knowledge documents already in the bank\n\n{sections}"


def start_knowledge_refinement(
    *,
    provider: LLMProvider,
    model: str,
    request: KnowledgeAuthoringRequest,
    grounding_docs: Sequence[KnowledgeDoc] = (),
    tool_context: ToolContext,
    caps: UsageCaps = DEFAULT_CAPS,
) -> AgentOutcome[KnowledgeDraftSchema]:
    check_grounding_budget(
        sum(doc.token_estimate for doc in grounding_docs), cap=caps.max_grounding_tokens
    )
    system = load_prompt("author_agent", "v1").render()
    opening = f"Draft a knowledge document about: {request.topic}."
    if request.material:
        opening += f"\n\nSource material supplied by the user:\n\n{request.material}"
    opening += _render_grounding(grounding_docs)
    return run_agent_loop(
        provider=provider,
        model=model,
        system=system,
        messages=[Message(role="user", text=opening)],
        tool_context=tool_context,
        target_schema=KnowledgeDraftSchema,
        caps=caps,
    )


def continue_knowledge_refinement(
    *,
    provider: LLMProvider,
    model: str,
    transcript: Sequence[Message],
    feedback: str,
    edited_draft: KnowledgeDraftSchema | None = None,
    tool_context: ToolContext,
    caps: UsageCaps = DEFAULT_CAPS,
) -> AgentOutcome[KnowledgeDraftSchema]:
    system = load_prompt("author_agent", "v1").render()
    feedback_text = feedback
    if edited_draft is not None:
        feedback_text = (
            "Here is the document with my own edits applied — treat this, not your "
            "previous version, as the current draft:\n\n"
            f"{edited_draft.model_dump_json(indent=2)}\n\n{feedback}"
        )
    return run_agent_loop(
        provider=provider,
        model=model,
        system=system,
        messages=[*transcript, Message(role="user", text=feedback_text)],
        tool_context=tool_context,
        target_schema=KnowledgeDraftSchema,
        caps=caps,
    )
