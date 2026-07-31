"""Question authoring: the one-click path and the agentic refinement path.
See docs/AI_SPEC.md #6.1, docs/CONTENT_SPEC.md #6.

Both paths produce a QuestionDraftSchema. The one-click path is the default,
not a fallback (docs/AI_SPEC.md #6.1) — a single complete_structured call,
no tools, no conversation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core.agent.limits import DEFAULT_CAPS, UsageCaps, check_grounding_budget
from core.agent.loop import AgentOutcome, run_agent_loop
from core.agent.tools.registry import ToolContext
from core.llm.base import LLMProvider, Message
from core.llm.schemas import QuestionDraftSchema
from core.models.enums import Difficulty, Module, TargetRole
from core.models.knowledge import KnowledgeDoc
from core.prompts.loader import load_prompt

# Authoring temperature per docs/AI_SPEC.md #1.2's temperature policy table.
_AUTHORING_TEMPERATURE = 0.7


@dataclass(frozen=True)
class AuthoringRequest:
    module: Module
    topic: str
    difficulty: Difficulty
    target_role: TargetRole | None = None
    institution: str = ""
    seed_context: str = ""


def one_click_question_draft(
    *, provider: LLMProvider, model: str, request: AuthoringRequest
) -> QuestionDraftSchema:
    """Module + topic + Generate, no tools, no conversation. This is the
    default path, not a degraded fallback — see docs/AI_SPEC.md #6.1.
    """
    system = load_prompt("question_author", "v1").render(
        module=request.module.value,
        topic=request.topic,
        difficulty=request.difficulty.value,
        target_role=request.target_role.value if request.target_role else "",
        institution=request.institution,
        seed_context=request.seed_context,
    )
    result = provider.complete_structured(
        system=system,
        user="Produce the question and its answer key now, following the schema exactly.",
        schema=QuestionDraftSchema.model_json_schema(),
        model=model,
        temperature=_AUTHORING_TEMPERATURE,
    )
    return QuestionDraftSchema.model_validate(result.data)


def _render_grounding(docs: Sequence[KnowledgeDoc]) -> str:
    if not docs:
        return ""
    sections = "\n\n".join(f"### {doc.title}\n\n{doc.body_md}" for doc in docs)
    return f"\n\n# Selected knowledge documents\n\n{sections}"


def _render_request(request: AuthoringRequest) -> str:
    lines = [
        f"Draft a {request.difficulty.value}-difficulty question for module "
        f"{request.module.value!r}, topic {request.topic!r}.",
    ]
    if request.target_role:
        lines.append(f"Target role: {request.target_role.value}.")
    if request.institution:
        lines.append(f"Institution focus: {request.institution}.")
    if request.seed_context:
        lines.append(f"Additional context from the user: {request.seed_context}")
    return " ".join(lines)


def start_question_refinement(
    *,
    provider: LLMProvider,
    model: str,
    request: AuthoringRequest,
    grounding_docs: Sequence[KnowledgeDoc] = (),
    tool_context: ToolContext,
    caps: UsageCaps = DEFAULT_CAPS,
) -> AgentOutcome[QuestionDraftSchema]:
    """The refinement path: grounding plus iterative feedback, via the
    agentic loop. See docs/AI_SPEC.md #6.1, #6.2.
    """
    check_grounding_budget(
        sum(doc.token_estimate for doc in grounding_docs), cap=caps.max_grounding_tokens
    )
    system = load_prompt("author_agent", "v1").render()
    opening = _render_request(request) + _render_grounding(grounding_docs)
    return run_agent_loop(
        provider=provider,
        model=model,
        system=system,
        messages=[Message(role="user", text=opening)],
        tool_context=tool_context,
        target_schema=QuestionDraftSchema,
        caps=caps,
    )


def continue_question_refinement(
    *,
    provider: LLMProvider,
    model: str,
    transcript: Sequence[Message],
    feedback: str,
    edited_draft: QuestionDraftSchema | None = None,
    tool_context: ToolContext,
    caps: UsageCaps = DEFAULT_CAPS,
) -> AgentOutcome[QuestionDraftSchema]:
    """Continues an existing conversation with the user's feedback.

    If the user edited the last shown draft, pass it as edited_draft: their
    edited text is what goes into context, not the model's own last version —
    the invariant in docs/AI_SPEC.md #6.2 that a refinement turn must never
    silently revert a correction the user made.
    """
    system = load_prompt("author_agent", "v1").render()
    feedback_text = feedback
    if edited_draft is not None:
        feedback_text = (
            "Here is the draft with my own edits applied — treat this, not your "
            "previous version, as the current draft:\n\n"
            f"{edited_draft.model_dump_json(indent=2)}\n\n{feedback}"
        )
    return run_agent_loop(
        provider=provider,
        model=model,
        system=system,
        messages=[*transcript, Message(role="user", text=feedback_text)],
        tool_context=tool_context,
        target_schema=QuestionDraftSchema,
        caps=caps,
    )
