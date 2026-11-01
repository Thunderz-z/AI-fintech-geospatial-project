"""CLI tests for `relia eval run` / `relia eval compare` — network-free."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from relia.cli import main
from relia.providers import CompletionRequest, Message, ScriptedProvider
from relia.replay import RecordingProvider

DATASET_TOML = """
dataset_id = "cli-smoke"
version = "1.0.0"

[[cases]]
case_id = "c1"
input = "q1"
expected = "answer one"

[[cases]]
case_id = "c2"
input = "q2"
expected = "answer two"
"""

PROMPT_TOML = """
[[prompts]]
prompt_id = "smoke"
version = "1.2.0"
template = "Answer: $input"
"""


@pytest.fixture
def eval_files(tmp_path):
    dataset = tmp_path / "dataset.toml"
    dataset.write_text(DATASET_TOML, encoding="utf-8")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "smoke.toml").write_text(PROMPT_TOML, encoding="utf-8")
    out = tmp_path / "out"
    return dataset, prompts, out


def _result_path_from_output(captured_out: str):
    match = re.search(r"Result:\s+(.+)", captured_out)
    assert match, captured_out
    return match.group(1).strip()


def _run(args: list[str], capsys):
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_eval_run_scripted_provider_writes_result(eval_files, capsys) -> None:
    dataset, _, out = eval_files

    code, stdout, _ = _run(
        [
            "eval",
            "run",
            "--dataset",
            str(dataset),
            "--answer-source",
            "scripted",
            "--scripted-response",
            "answer one",
            "--out-dir",
            str(out),
        ],
        capsys,
    )

    assert code == 0
    assert "exact_match: 0.5000" in stdout  # only case 1 matches
    assert "case_success_rate: 1.0000" in stdout
    result = json.loads(Path(_result_path_from_output(stdout)).read_text(encoding="utf-8"))
    assert result["dataset_id"] == "cli-smoke"
    assert result["config_version"] == "raw"
    assert len(result["case_results"]) == 2
    assert result["case_results"][0]["answer"] == "answer one"


def test_eval_run_with_prompt_sets_config_version(eval_files, capsys) -> None:
    dataset, prompts, out = eval_files

    code, stdout, _ = _run(
        [
            "eval",
            "run",
            "--dataset",
            str(dataset),
            "--prompts-dir",
            str(prompts),
            "--prompt-id",
            "smoke",
            "--answer-source",
            "scripted",
            "--scripted-response",
            "answer one",
            "--out-dir",
            str(out),
        ],
        capsys,
    )

    assert code == 0
    assert "Config:  smoke@1.2.0" in stdout


def test_eval_run_fail_under_flags_low_metrics(eval_files, capsys) -> None:
    dataset, _, out = eval_files

    code, _, err = _run(
        [
            "eval",
            "run",
            "--dataset",
            str(dataset),
            "--answer-source",
            "scripted",
            "--scripted-response",
            "answer one",
            "--out-dir",
            str(out),
            "--fail-under",
            "0.9",
        ],
        capsys,
    )

    assert code == 1
    assert "below --fail-under" in err


def test_eval_run_unknown_check_spec_fails_fast(eval_files, capsys) -> None:
    dataset, _, out = eval_files

    code, _, err = _run(
        [
            "eval",
            "run",
            "--dataset",
            str(dataset),
            "--answer-source",
            "scripted",
            "--scripted-response",
            "x",
            "--check",
            "nonsense",
            "--out-dir",
            str(out),
        ],
        capsys,
    )

    assert code == 2
    assert "Unknown check spec" in err


def test_eval_run_requires_answer_source(eval_files, capsys) -> None:
    dataset, _, out = eval_files

    code, _, err = _run(
        ["eval", "run", "--dataset", str(dataset), "--out-dir", str(out)],
        capsys,
    )

    assert code == 1
    assert "No answer source" in err


def test_eval_run_scripted_requires_response_text(eval_files, capsys) -> None:
    dataset, _, out = eval_files

    code, _, err = _run(
        [
            "eval",
            "run",
            "--dataset",
            str(dataset),
            "--answer-source",
            "scripted",
            "--out-dir",
            str(out),
        ],
        capsys,
    )

    assert code == 1
    assert "--scripted-response" in err


def test_eval_run_openai_compatible_without_key_fails_cleanly(
    eval_files, capsys, tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no repo .env fallback
    monkeypatch.delenv("RELIA_LLM_API_KEY", raising=False)
    dataset, _, out = eval_files

    code, _, err = _run(
        [
            "eval",
            "run",
            "--dataset",
            str(dataset),
            "--answer-source",
            "openai-compatible",
            "--out-dir",
            str(out),
        ],
        capsys,
    )

    assert code == 1
    assert "RELIA_LLM_API_KEY" in err


def record_cli_cassette(path, *, requests: list[str], responses: list[str]) -> None:
    """Record requests with rendered-prompt content, responses = expected answers."""
    inner = ScriptedProvider.text(*responses)
    recorder = RecordingProvider(inner, cassette_id="cli-cassette")
    for content in requests:
        asyncio.run(
            recorder.complete(
                CompletionRequest(
                    model="m-test",
                    messages=[Message(role="user", content=content)],
                )
            )
        )
    recorder.save(path)


def test_eval_run_cassette_replay_is_network_free(eval_files, capsys, tmp_path) -> None:
    dataset, prompts, out = eval_files
    cassette = tmp_path / "cassette.json"
    record_cli_cassette(
        cassette,
        requests=["Answer: q1", "Answer: q2"],
        responses=["answer one", "answer two"],
    )

    code, stdout, _ = _run(
        [
            "eval",
            "run",
            "--dataset",
            str(dataset),
            "--cassette",
            str(cassette),
            "--prompts-dir",
            str(prompts),
            "--prompt-id",
            "smoke",
            "--out-dir",
            str(out),
        ],
        capsys,
    )

    assert code == 0
    assert "exact_match: 1.0000" in stdout
    result = json.loads(Path(_result_path_from_output(stdout)).read_text(encoding="utf-8"))
    assert result["config_version"] == "smoke@1.2.0"


def test_eval_run_cassette_divergence_becomes_visible_metric(
    eval_files, capsys, tmp_path
) -> None:
    # Requests without the prompt diverge from the recorded ones: every case
    # errors, case_success_rate drops to 0, and --fail-under gates the exit.
    dataset, _, out = eval_files
    cassette = tmp_path / "cassette.json"
    record_cli_cassette(
        cassette,
        requests=["Answer: q1", "Answer: q2"],
        responses=["answer one", "answer two"],
    )

    code, stdout, err = _run(
        [
            "eval",
            "run",
            "--dataset",
            str(dataset),
            "--cassette",
            str(cassette),
            "--out-dir",
            str(out),
            "--fail-under",
            "0.5",
        ],
        capsys,
    )

    assert "case_success_rate: 0.0000" in stdout
    assert code == 1
    assert "below --fail-under" in err


def _write_result_file(path, exact_match_value: float) -> None:
    result = {
        "dataset_id": "d",
        "dataset_version": "1",
        "config_version": "cfg",
        "metrics": [
            {"name": "exact_match", "value": exact_match_value},
            {"name": "case_success_rate", "value": 1.0},
        ],
    }
    path.write_text(json.dumps(result), encoding="utf-8")


def test_eval_compare_reports_deltas(tmp_path, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_result_file(baseline, 0.5)
    _write_result_file(candidate, 1.0)

    code, stdout, _ = _run(
        ["eval", "compare", str(baseline), str(candidate)], capsys
    )

    assert code == 0
    assert "exact_match: 0.5000 -> 1.0000 (+0.5000) improved" in stdout
    assert "point deltas only" in stdout


def test_eval_compare_fail_on_regression(tmp_path, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_result_file(baseline, 1.0)
    _write_result_file(candidate, 0.25)

    code, _, err = _run(
        [
            "eval",
            "compare",
            str(baseline),
            str(candidate),
            "--fail-on-regression",
        ],
        capsys,
    )

    assert code == 1
    assert "regressed" in err


def test_eval_compare_missing_file_fails_cleanly(tmp_path, capsys) -> None:
    code, _, err = _run(
        ["eval", "compare", str(tmp_path / "nope.json"), str(tmp_path / "nope2.json")],
        capsys,
    )

    assert code == 2
    assert "ERROR" in err
