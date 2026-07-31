"""Load, hash, and version prompt files. See docs/AI_SPEC.md #2.1, #2.3,
docs/DECISIONS.md D8.

Prompts live in prompts/<name>.v<N>.md — never as inline strings in Python.
Templating is explicit str.format-style with a declared variable list read
straight off the template's own `{placeholder}` markers; render() raises if
the caller failed to supply every one of them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

# Matches {name} but not the {{ / }} used to escape a literal brace.
_VAR_PATTERN = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: str
    template: str
    sha256: str
    variables: frozenset[str]

    def render(self, **kwargs: str) -> str:
        missing = self.variables - kwargs.keys()
        if missing:
            raise ValueError(
                f"prompt {self.name}.{self.version} is missing required variables: "
                f"{sorted(missing)}"
            )
        # Only the declared variables are substituted — an extra kwarg the
        # caller passed but the template never mentions is silently unused,
        # same as str.format's own behavior with **kwargs.
        return self.template.format(**{k: kwargs[k] for k in self.variables})


class PromptNotFound(FileNotFoundError):
    pass


@cache
def load_prompt(name: str, version: str) -> PromptSpec:
    """Cached by (name, version) — i.e. by file, since the two together are
    the filename.
    """
    path = _PROMPTS_DIR / f"{name}.{version}.md"
    if not path.exists():
        raise PromptNotFound(f"prompt file not found: {path}")

    template = path.read_text(encoding="utf-8")
    variables = frozenset(_VAR_PATTERN.findall(template))
    sha256 = hashlib.sha256(template.encode("utf-8")).hexdigest()
    return PromptSpec(
        name=name, version=version, template=template, sha256=sha256, variables=variables
    )
