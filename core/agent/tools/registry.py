"""The closed tool set. See docs/AI_SPEC.md #7.

Exactly four tools, no dynamic registration, no user-supplied tools — the
set itself is part of the safety boundary. execute_tool() is the only place
that turns a model's ToolCall into a Python call and a plain-text result;
core/agent/loop.py never calls a tool implementation directly.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.agent.tools.fetch import fetch_url
from core.agent.tools.knowledge import read_knowledge, search_knowledge
from core.agent.tools.uploads import Upload, read_upload
from core.db.repositories.knowledge import KnowledgeRepository
from core.llm.base import ToolSpec
from core.llm.errors import LLMToolArgError

# A fetched or read document can easily run to tens of thousands of
# characters; the tool RESULT handed back to the model is capped separately
# from fetch.py's own 2MB byte cap, which exists to bound memory and network
# time, not token spend. Truncating here is what actually protects the
# per-draft token budget in docs/AI_SPEC.md #7.3.
_MAX_TOOL_TEXT_CHARS = 20_000


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_TOOL_TEXT_CHARS:
        return text, False
    return text[:_MAX_TOOL_TEXT_CHARS], True


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="search_knowledge",
        description=(
            "Search the user's visible knowledge bank by keyword. Returns summaries, not full text."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords to search for."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="read_knowledge",
        description="Read one knowledge document's full text by its slug.",
        parameters={
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    ),
    ToolSpec(
        name="fetch_url",
        description=(
            "Fetch and extract the text of a real, public web page. May refuse a URL "
            "for safety reasons (private/internal addresses, unsupported schemes, "
            "disallowed content types) — if refused, do not retry the same URL."
        ),
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
    ToolSpec(
        name="read_upload",
        description="Read a file the user attached to this conversation, by its upload id.",
        parameters={
            "type": "object",
            "properties": {"upload_id": {"type": "string"}},
            "required": ["upload_id"],
        },
    ),
)

TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOOL_SPECS)


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool implementation needs, bundled once per authoring
    session rather than threaded through every call individually.
    """

    knowledge_repo: KnowledgeRepository
    uploads: Mapping[str, Upload]


def _require_str(arguments: dict[str, Any], key: str, tool_name: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise LLMToolArgError(f"{tool_name} requires a non-empty {key!r} string argument")
    return value


def execute_tool(name: str, arguments: dict[str, Any], context: ToolContext) -> str:
    """Returns the tool result content as a JSON string. Raises LLMToolArgError
    on malformed arguments and lets ToolBlocked / NotFound propagate — the
    agent loop is responsible for catching both and turning them into an
    is_error=True ToolResult the model can read, never a crashed turn.
    """
    if name == "search_knowledge":
        query = _require_str(arguments, "query", name)
        limit = arguments.get("limit", 5)
        if not isinstance(limit, int):
            raise LLMToolArgError("search_knowledge's 'limit' must be an integer")
        results = search_knowledge(context.knowledge_repo, query, limit=limit)
        return json.dumps(results)

    if name == "read_knowledge":
        slug = _require_str(arguments, "slug", name)
        doc = read_knowledge(context.knowledge_repo, slug)
        body, truncated = _truncate(doc["body_md"])
        return json.dumps({"title": doc["title"], "body_md": body, "truncated": truncated})

    if name == "fetch_url":
        url = _require_str(arguments, "url", name)
        result = fetch_url(url)
        text, truncated_further = _truncate(result.text)
        return json.dumps(
            {
                "url": result.url,
                "title": result.title,
                "text": text,
                "truncated": result.truncated or truncated_further,
            }
        )

    if name == "read_upload":
        upload_id = _require_str(arguments, "upload_id", name)
        upload = read_upload(context.uploads, upload_id)
        text, truncated = _truncate(upload["text"])
        return json.dumps({"filename": upload["filename"], "text": text, "truncated": truncated})

    raise LLMToolArgError(f"unknown tool {name!r}; the closed tool set is {TOOL_NAMES}")
