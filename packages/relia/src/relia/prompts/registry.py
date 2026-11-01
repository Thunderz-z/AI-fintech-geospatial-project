"""Versioned prompt registry.

Prompts are first-class versioned artefacts: every evaluation result
records which prompt/configuration produced it
(:class:`relia.evaluations.base.EvalResult.config_version`), and the
registry is the lookup side of that contract.

File format (TOML, stdlib-parsed — no new dependency):

```toml
[[prompts]]
prompt_id = "water-summary"
version = "1.1.0"
description = "Narrative water-area summary for TerraScope reports"
template = \"\"\"
Summarize the observed water dynamics. Input: $input
\"\"\"
```

Templates use :class:`string.Template` (``$variable`` / ``${variable}``)
rather than ``str.format`` braces, because prompt bodies routinely contain
JSON examples with literal braces. Rendering is strict: a missing variable
raises :class:`PromptRenderError` instead of silently producing a broken
prompt.
"""

from __future__ import annotations

import string
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

from relia.providers.base import ReliaError

__all__ = [
    "DuplicatePromptVersionError",
    "PromptNotFoundError",
    "PromptRegistry",
    "PromptRegistryError",
    "PromptRenderError",
    "PromptTemplate",
    "load_prompts_from_file",
]


class PromptRegistryError(ReliaError):
    """A prompt registry problem (bad file, bad template, bad render input)."""


class DuplicatePromptVersionError(PromptRegistryError):
    """The same ``(prompt_id, version)`` pair was registered twice."""


class PromptNotFoundError(PromptRegistryError):
    """The requested prompt id or version is not registered."""


class PromptRenderError(PromptRegistryError):
    """Rendering a prompt failed (missing variable or invalid placeholder)."""


def _version_sort_key(version: str) -> tuple[tuple[int, int, str], ...]:
    """Numeric-aware ordering key: "1.10.0" > "1.9.0", not "1.10.0" < "1.9.0"."""
    parts: list[tuple[int, int, str]] = []
    for raw in version.split("."):
        if raw.isdigit():
            parts.append((0, int(raw), ""))
        else:
            parts.append((1, 0, raw))
    return tuple(parts)


class PromptTemplate(BaseModel):
    """One versioned prompt body with ``$variable`` placeholders."""

    prompt_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    template: str = Field(min_length=1)
    description: str | None = None

    @property
    def variables(self) -> tuple[str, ...]:
        """Placeholder names detected in the template, in first-appearance order."""
        return tuple(string.Template(self.template).get_identifiers())

    def render(self, variables: dict[str, str]) -> str:
        """Strict substitution; missing variables raise :class:`PromptRenderError`."""
        try:
            return string.Template(self.template).substitute(**variables)
        except KeyError as exc:
            missing = exc.args[0]
            raise PromptRenderError(
                f"Prompt {self.prompt_id!r} v{self.version} is missing variable "
                f"{missing!r}; template requires {list(self.variables)}."
            ) from exc
        except ValueError as exc:
            raise PromptRenderError(
                f"Prompt {self.prompt_id!r} v{self.version} has an invalid "
                f"placeholder: {exc}"
            ) from exc

    @property
    def qualified_version(self) -> str:
        """``prompt_id@version`` — the default ``config_version`` label."""
        return f"{self.prompt_id}@{self.version}"


def load_prompts_from_file(path: str | Path) -> list[PromptTemplate]:
    """Parse a TOML file holding a ``[[prompts]]`` array of tables."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PromptRegistryError(f"Cannot read prompt file {path}: {exc}") from exc

    entries = data.get("prompts")
    if not isinstance(entries, list) or not entries:
        raise PromptRegistryError(
            f"Prompt file {path} must contain a non-empty [[prompts]] array."
        )

    templates: list[PromptTemplate] = []
    for index, entry in enumerate(entries):
        try:
            templates.append(PromptTemplate.model_validate(entry))
        except Exception as exc:  # pydantic ValidationError or wrong shape
            raise PromptRegistryError(
                f"Prompt file {path}, entry {index} is not a valid prompt: {exc}"
            ) from exc
    return templates


class PromptRegistry:
    """In-memory registry of prompt versions; lookup by id, latest by default."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], PromptTemplate] = {}

    def register(self, template: PromptTemplate) -> None:
        key = (template.prompt_id, template.version)
        if key in self._by_key:
            raise DuplicatePromptVersionError(
                f"Prompt {template.prompt_id!r} version {template.version!r} "
                "is already registered."
            )
        self._by_key[key] = template

    def get(self, prompt_id: str, version: str | None = None) -> PromptTemplate:
        """Return the requested (or numerically latest) version of a prompt."""
        versions = [v for pid, v in self._by_key if pid == prompt_id]
        if not versions:
            raise PromptNotFoundError(
                f"No prompt registered under id {prompt_id!r}; known ids: "
                f"{sorted({pid for pid, _ in self._by_key}) or 'none'}."
            )
        if version is None:
            version = max(versions, key=_version_sort_key)
        template = self._by_key.get((prompt_id, version))
        if template is None:
            raise PromptNotFoundError(
                f"Prompt {prompt_id!r} has no version {version!r}; known: {versions}."
            )
        return template

    def render(
        self, prompt_id: str, variables: dict[str, str], *, version: str | None = None
    ) -> str:
        return self.get(prompt_id, version).render(variables)

    def prompt_ids(self) -> tuple[str, ...]:
        return tuple(sorted({pid for pid, _ in self._by_key}))

    def versions(self, prompt_id: str) -> tuple[str, ...]:
        return tuple(
            sorted((v for pid, v in self._by_key if pid == prompt_id), key=_version_sort_key)
        )

    def __len__(self) -> int:
        return len(self._by_key)

    @classmethod
    def from_directory(cls, directory: str | Path, *, pattern: str = "*.toml") -> PromptRegistry:
        """Load every ``*.toml`` prompt file in *directory* into a new registry."""
        directory = Path(directory)
        if not directory.is_dir():
            raise PromptRegistryError(
                f"Prompt directory does not exist: {directory}"
            )
        registry = cls()
        for path in sorted(directory.glob(pattern)):
            for template in load_prompts_from_file(path):
                registry.register(template)
        return registry
