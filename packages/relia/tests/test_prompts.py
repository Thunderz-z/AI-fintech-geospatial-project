"""Tests for the versioned prompt registry."""

from __future__ import annotations

import pytest

from relia.prompts import (
    DuplicatePromptVersionError,
    PromptNotFoundError,
    PromptRegistry,
    PromptRegistryError,
    PromptRenderError,
    PromptTemplate,
    load_prompts_from_file,
)

PROMPT_TOML = """
[[prompts]]
prompt_id = "water-summary"
version = "1.0.0"
description = "first"
template = \"\"\"
Summarize water dynamics for $input in ${region}.
JSON example: {"key": "value"} stays literal.
\"\"\"

[[prompts]]
prompt_id = "water-summary"
version = "1.10.0"
template = "v10 for $input"
"""

PROMPT_TOML_V19 = """
[[prompts]]
prompt_id = "water-summary"
version = "1.9.0"
template = "v9 for $input"
"""


def write(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_register_get_and_numeric_latest_version(tmp_path) -> None:
    write(tmp_path, "a.toml", PROMPT_TOML)
    write(tmp_path, "b.toml", PROMPT_TOML_V19)
    registry = PromptRegistry.from_directory(tmp_path)

    assert len(registry) == 3
    assert registry.prompt_ids() == ("water-summary",)
    assert registry.versions("water-summary") == ("1.0.0", "1.9.0", "1.10.0")

    latest = registry.get("water-summary")
    assert latest.version == "1.10.0"  # numeric ordering, not lexicographic
    assert registry.get("water-summary", "1.0.0").description == "first"


def test_duplicate_version_rejected(tmp_path) -> None:
    registry = PromptRegistry()
    template = PromptTemplate(prompt_id="p", version="1", template="x $a")
    registry.register(template)

    with pytest.raises(DuplicatePromptVersionError):
        registry.register(
            PromptTemplate(prompt_id="p", version="1", template="other $a")
        )


def test_get_missing_id_and_version_raise() -> None:
    registry = PromptRegistry()
    with pytest.raises(PromptNotFoundError, match="No prompt registered"):
        registry.get("nope")
    registry.register(PromptTemplate(prompt_id="p", version="1", template="x"))
    with pytest.raises(PromptNotFoundError, match="no version"):
        registry.get("p", "2")


def test_render_substitutes_and_keeps_json_braces_literal() -> None:
    template = PromptTemplate(
        prompt_id="p",
        version="1.0.0",
        template='Summarize $input for ${region}. JSON: {"k": "v"} stays.',
    )

    rendered = template.render({"input": "winter composite", "region": "IN2481"})

    assert rendered == (
        'Summarize winter composite for IN2481. JSON: {"k": "v"} stays.'
    )


def test_render_missing_variable_raises() -> None:
    template = PromptTemplate(
        prompt_id="p", version="1", template="needs $input and $region"
    )

    with pytest.raises(PromptRenderError, match="'region'"):
        template.render({"input": "x"})


def test_variables_are_detected_in_order() -> None:
    template = PromptTemplate(
        prompt_id="p", version="1", template="$b then $a then $b"
    )
    assert template.variables == ("b", "a")


def test_qualified_version_label() -> None:
    template = PromptTemplate(prompt_id="summarize", version="2.1.0", template="x")
    assert template.qualified_version == "summarize@2.1.0"


def test_load_file_malformed_toml_raises(tmp_path) -> None:
    path = write(tmp_path, "bad.toml", "[[prompts]\nbroken = ")

    with pytest.raises(PromptRegistryError, match="Cannot read prompt file"):
        load_prompts_from_file(path)


def test_load_file_without_prompts_array_raises(tmp_path) -> None:
    path = write(tmp_path, "empty.toml", "something = 'else'\n")

    with pytest.raises(PromptRegistryError, match=r"\[\[prompts\]\]"):
        load_prompts_from_file(path)


def test_load_file_invalid_entry_raises_with_location(tmp_path) -> None:
    path = write(tmp_path, "bad-entry.toml", '[[prompts]]\nversion = "1"\n')

    with pytest.raises(PromptRegistryError, match="entry 0"):
        load_prompts_from_file(path)


def test_from_directory_missing_dir_raises(tmp_path) -> None:
    with pytest.raises(PromptRegistryError, match="does not exist"):
        PromptRegistry.from_directory(tmp_path / "nope")
