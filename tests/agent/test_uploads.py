"""Unit tests for core.agent.tools.uploads. See docs/AI_SPEC.md #7.2."""

from __future__ import annotations

import pytest

from core.agent.errors import ToolBlocked
from core.agent.tools.uploads import Upload, check_upload_count, parse_upload, read_upload


def test_parse_upload_accepts_md() -> None:
    upload = parse_upload("notes.md", b"# Hello")
    assert upload.filename == "notes.md"
    assert upload.text == "# Hello"


def test_parse_upload_accepts_txt() -> None:
    upload = parse_upload("notes.txt", b"plain text")
    assert upload.text == "plain text"


def test_parse_upload_rejects_disallowed_extension() -> None:
    with pytest.raises(ToolBlocked, match="unsupported file type"):
        parse_upload("document.pdf", b"%PDF-1.4")


def test_parse_upload_rejects_oversized_file() -> None:
    with pytest.raises(ToolBlocked, match="1 MB limit"):
        parse_upload("big.txt", b"x" * (1024 * 1024 + 1))


def test_parse_upload_at_size_limit_is_allowed() -> None:
    upload = parse_upload("exact.txt", b"x" * (1024 * 1024))
    assert len(upload.text) == 1024 * 1024


def test_parse_upload_replaces_invalid_utf8_rather_than_crashing() -> None:
    upload = parse_upload("bad.txt", b"\xff\xfe not valid utf-8")
    assert "not valid utf-8" in upload.text


def test_check_upload_count_within_limit() -> None:
    check_upload_count(0)
    check_upload_count(2)


def test_check_upload_count_at_limit_raises() -> None:
    with pytest.raises(ToolBlocked, match="at most 3"):
        check_upload_count(3)


def test_read_upload_returns_matching_entry() -> None:
    uploads = {"u1": Upload(filename="a.md", text="hello")}
    result = read_upload(uploads, "u1")
    assert result == {"filename": "a.md", "text": "hello"}


def test_read_upload_missing_id_raises() -> None:
    with pytest.raises(ToolBlocked, match="no upload"):
        read_upload({}, "does-not-exist")
