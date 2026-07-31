"""Upload handling for the authoring agent. See docs/AI_SPEC.md #7.2.

Uploads are never persisted — held in memory for the request and discarded,
per docs/DATA_SPEC.md #11. This module never touches the filesystem and never
imports streamlit: the UI page reads bytes from st.file_uploader, calls
parse_upload() to validate and decode them, and holds the resulting Upload
objects in st.session_state itself. read_upload() then looks them up from
that in-memory mapping — core.agent has no I/O of its own here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.agent.errors import ToolBlocked

_ALLOWED_EXTENSIONS = (".md", ".txt")
_MAX_BYTES = 1 * 1024 * 1024  # 1 MB
_MAX_UPLOADS_PER_DRAFT = 3


@dataclass(frozen=True)
class Upload:
    filename: str
    text: str


def parse_upload(filename: str, raw_bytes: bytes) -> Upload:
    """Validate and decode one uploaded file. Raises ToolBlocked on anything
    that violates docs/AI_SPEC.md #7.2's limits — deliberately not a silent
    truncation or best-effort decode, since a partially-read file handed to
    the model as if it were complete is worse than a clear refusal.
    """
    lower = filename.lower()
    if not lower.endswith(_ALLOWED_EXTENSIONS):
        raise ToolBlocked(f"unsupported file type for {filename!r}; only .md and .txt are accepted")
    if len(raw_bytes) > _MAX_BYTES:
        raise ToolBlocked(f"{filename!r} is larger than the 1 MB limit")

    text = raw_bytes.decode("utf-8", errors="replace")
    return Upload(filename=filename, text=text)


def check_upload_count(existing_count: int) -> None:
    if existing_count >= _MAX_UPLOADS_PER_DRAFT:
        raise ToolBlocked(f"at most {_MAX_UPLOADS_PER_DRAFT} uploads are allowed per draft")


def read_upload(uploads: Mapping[str, Upload], upload_id: str) -> dict[str, str]:
    upload = uploads.get(upload_id)
    if upload is None:
        raise ToolBlocked(f"no upload with id {upload_id!r} in this conversation")
    return {"filename": upload.filename, "text": upload.text}
