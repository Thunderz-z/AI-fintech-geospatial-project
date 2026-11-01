"""RELIA command-line interface.

Implemented commands:

* ``check-data-root`` — data-root diagnostics.
* ``eval run`` — deterministic evaluation of a dataset against a scripted
  provider, a recorded cassette (network-free) or an OpenAI-compatible
  endpoint configured via ``RELIA_LLM_*``; writes :class:`EvalResult` JSON.
* ``eval compare`` — point-delta comparison of two eval-result files.

Regression bisection and LLM-as-judge evaluation are planned; see
``docs/architecture/relia.md`` and the roadmap.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from relia.config.paths import DataRootError, DataRootStatus, check_data_root, find_repo_root
from relia.evaluations import (
    ContainsCheck,
    DeterministicCheck,
    EvalCase,
    EvalDatasetError,
    EvalResult,
    EvalRunner,
    ExactMatch,
    RegexCheck,
    ValidJsonCheck,
    load_eval_dataset,
)
from relia.prompts import PromptRegistry, PromptRegistryError, PromptRenderError
from relia.providers import (
    CompletionRequest,
    Message,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    ScriptedProvider,
    scripted_response,
)
from relia.replay import ReplayProvider, load_cassette

_GIB = 1024**3

_EPSILON = 1e-12


class _CliEvalError(Exception):
    """Internal: an eval command could not be set up (printed as ERROR)."""


def _format_status(status: DataRootStatus) -> str:
    lines = [
        f"Data root:           {status.root}",
        f"Configured via:      {status.source}",
        f"Exists:              {status.exists}",
        f"Is a directory:      {status.is_dir}",
        f"Writable:            {status.writable}",
    ]
    if status.free_bytes is not None:
        lines.append(f"Free space:          {status.free_bytes / _GIB:.1f} GiB")
    lines.append(
        "Project directories: present="
        + (", ".join(status.present_projects) or "-")
        + " missing="
        + (", ".join(status.missing_projects) or "-")
    )
    lines.append(f"Healthy:             {status.healthy}")
    return "\n".join(lines)


# --- eval: shared helpers ---------------------------------------------------


def _default_out_dir() -> Path:
    """EvalResult outputs land under the repository's docs/evaluations."""
    repo_root = find_repo_root()
    return (repo_root or Path.cwd()) / "docs" / "evaluations"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "unnamed"


def _parse_check_spec(spec: str) -> DeterministicCheck:
    name, sep, arg = spec.partition(":")
    name = name.strip()
    if name == "exact_match" and not sep:
        return ExactMatch()
    if name == "valid_json" and not sep:
        return ValidJsonCheck()
    if name == "contains" and sep and arg:
        return ContainsCheck(arg)
    if name == "regex" and sep and arg:
        return RegexCheck(arg)
    raise ValueError(
        f"Unknown check spec {spec!r}; known specs: exact_match, valid_json, "
        "contains:TEXT, regex:PATTERN."
    )


def _build_answer_source(args: argparse.Namespace, dataset_cases: int):
    """Return (provider, resolved_model, close_coro_needed). Raises _CliEvalError."""
    if args.cassette:
        cassette = load_cassette(args.cassette)
        provider = ReplayProvider(cassette)
        recorded_model = (
            cassette.interactions[0].request.get("model") if cassette.interactions else None
        )
        model = args.model or recorded_model
        if not model:
            raise _CliEvalError(
                "Cannot determine the model for replay: cassette has no "
                "interactions and no --model was given."
            )
        return provider, model, None

    if args.answer_source == "scripted":
        if args.scripted_response is None:
            raise _CliEvalError(
                "--answer-source scripted requires --scripted-response TEXT."
            )
        provider = ScriptedProvider(
            *[scripted_response(args.scripted_response) for _ in range(dataset_cases)],
            name="scripted-cli",
        )
        return provider, args.model or "scripted-model", None

    if args.answer_source == "openai-compatible":
        try:
            config = ProviderConfig.from_env()
        except ProviderError as exc:
            raise _CliEvalError(str(exc)) from exc
        model = args.model or config.default_model
        if not model:
            raise _CliEvalError(
                "No model for the real provider: pass --model or set "
                "RELIA_LLM_DEFAULT_MODEL."
            )
        provider = OpenAICompatibleProvider(config)
        return provider, model, provider.aclose()

    raise _CliEvalError(
        "No answer source configured: pass --answer-source "
        "{scripted,openai-compatible} or --cassette PATH."
    )


async def _run_eval(
    args: argparse.Namespace, dataset, checks: list[DeterministicCheck]
) -> EvalResult:
    template = None
    if args.prompt_id:
        if not args.prompts_dir:
            raise _CliEvalError("--prompt-id requires --prompts-dir DIR.")
        try:
            registry = PromptRegistry.from_directory(args.prompts_dir)
            template = registry.get(args.prompt_id, args.prompt_version)
        except PromptRegistryError as exc:
            raise _CliEvalError(str(exc)) from exc
        # Fail fast on a render config bug before any provider call (a real
        # provider would otherwise burn tokens on every case).
        first = dataset.cases[0]
        try:
            template.render({"input": first.input, **first.context})
        except PromptRenderError as exc:
            raise _CliEvalError(str(exc)) from exc

    provider, model, close = _build_answer_source(args, len(dataset.cases))

    async def answer_fn(case: EvalCase) -> str:
        content = (
            template.render({"input": case.input, **case.context})
            if template is not None
            else case.input
        )
        request = CompletionRequest(
            model=model,
            messages=[Message(role="user", content=content)],
            timeout_seconds=args.timeout_seconds,
        )
        response = await provider.complete(request)
        return response.text

    config_version = args.config_version or (
        template.qualified_version if template is not None else "raw"
    )
    try:
        result = await EvalRunner(answer_fn).run(
            dataset, config_version, checks
        )
    finally:
        if close is not None:
            await close

    ledger = getattr(provider, "ledger", None)
    if ledger is not None and ledger.completions:
        usage_note = f"provider usage: {json.dumps(ledger.snapshot())}"
        result.notes = f"{result.notes} {usage_note}" if result.notes else usage_note
    return result


def _eval_run(args: argparse.Namespace) -> int:
    try:
        dataset = load_eval_dataset(args.dataset)
        checks = [_parse_check_spec(spec) for spec in (args.check or ["exact_match"])]
    except (EvalDatasetError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        result = asyncio.run(_run_eval(args, dataset, checks))
    except (ProviderError, _CliEvalError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output_path = out_dir / (
        f"{_safe_name(dataset.dataset_id)}__{_safe_name(result.config_version)}"
        f"__{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    print(f"Dataset: {dataset.dataset_id} v{dataset.version}")
    print(f"Config:  {result.config_version}")
    print(f"Cases:   {len(result.case_results)}")
    for metric in result.metrics:
        print(f"  {metric.name}: {metric.value:.4f}")
    if result.notes:
        print(f"Notes:   {result.notes}")
    print(f"Result:  {output_path}")

    if args.fail_under is not None:
        failed = [m for m in result.metrics if m.value < args.fail_under]
        if failed:
            listing = ", ".join(f"{m.name}={m.value:.4f}" for m in failed)
            print(
                f"ERROR: metrics below --fail-under {args.fail_under}: {listing}",
                file=sys.stderr,
            )
            return 1
    return 0


def _eval_compare(args: argparse.Namespace) -> int:
    try:
        baseline = EvalResult.model_validate_json(
            Path(args.baseline).read_text(encoding="utf-8")
        )
        candidate = EvalResult.model_validate_json(
            Path(args.candidate).read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        print(f"ERROR: cannot load eval result: {exc}", file=sys.stderr)
        return 2

    print(f"Baseline:  {baseline.dataset_id} {baseline.config_version}")
    print(f"Candidate: {candidate.dataset_id} {candidate.config_version}")
    baseline_metrics = {m.name: m for m in baseline.metrics}
    candidate_metrics = {m.name: m for m in candidate.metrics}

    regressions: list[str] = []
    for name in sorted(set(baseline_metrics) | set(candidate_metrics)):
        base = baseline_metrics.get(name)
        cand = candidate_metrics.get(name)
        if base is None:
            print(f"  {name}: only in candidate ({cand.value:.4f})")
            continue
        if cand is None:
            print(f"  {name}: only in baseline ({base.value:.4f})")
            continue
        delta = cand.value - base.value
        if abs(delta) <= _EPSILON:
            verdict = "unchanged"
        else:
            better = delta > 0 if base.higher_is_better else delta < 0
            verdict = "improved" if better else "regressed"
        if verdict == "regressed":
            regressions.append(name)
        print(
            f"  {name}: {base.value:.4f} -> {cand.value:.4f} "
            f"({delta:+.4f}) {verdict}"
        )
    print(
        "Note: point deltas only — statistical comparison with bootstrap CIs "
        "is planned, not implemented."
    )
    if args.fail_on_regression and regressions:
        print(
            f"ERROR: {len(regressions)} metric(s) regressed: {regressions}",
            file=sys.stderr,
        )
        return 1
    return 0


# --- entry point --------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="relia",
        description="RELIA reliability infrastructure CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "check-data-root",
        help="Validate PORTFOLIO_DATA_ROOT and the dataset directory layout",
    )

    eval_parser = subparsers.add_parser(
        "eval", help="Deterministic evaluation commands"
    )
    eval_sub = eval_parser.add_subparsers(dest="eval_command", required=True)

    run_parser = eval_sub.add_parser(
        "run",
        help="Run a dataset deterministically and write an EvalResult JSON",
    )
    run_parser.add_argument("--dataset", required=True, help="TOML eval dataset path")
    run_parser.add_argument(
        "--prompts-dir", help="Directory of TOML prompt files (with --prompt-id)"
    )
    run_parser.add_argument("--prompt-id", help="Render this prompt per case")
    run_parser.add_argument(
        "--prompt-version", help="Prompt version (default: latest registered)"
    )
    run_parser.add_argument(
        "--answer-source",
        choices=("scripted", "openai-compatible"),
        help="Where answers come from; --cassette is the network-free alternative",
    )
    run_parser.add_argument(
        "--scripted-response",
        help="Constant response text for --answer-source scripted",
    )
    run_parser.add_argument(
        "--cassette", help="Replay a recorded cassette JSON (network-free)"
    )
    run_parser.add_argument("--model", help="Model id for the completion request")
    run_parser.add_argument(
        "--timeout-seconds", type=float, default=60.0, help="Per-request timeout"
    )
    run_parser.add_argument(
        "--check",
        action="append",
        help=(
            "Deterministic check spec, repeatable "
            "(exact_match, valid_json, contains:TEXT, regex:PATTERN); "
            "default: exact_match"
        ),
    )
    run_parser.add_argument(
        "--config-version",
        help="Label under test (default: prompt_id@version or 'raw')",
    )
    run_parser.add_argument(
        "--out-dir", help=f"Output directory (default: {_default_out_dir()})"
    )
    run_parser.add_argument(
        "--fail-under",
        type=float,
        help="Exit 1 when any metric value is below this threshold",
    )

    compare_parser = eval_sub.add_parser(
        "compare", help="Compare two EvalResult JSON files (point deltas)"
    )
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit 1 when any shared metric regressed",
    )

    args = parser.parse_args(argv)

    if args.command == "check-data-root":
        try:
            status = check_data_root()
        except DataRootError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(_format_status(status))
        return 0 if status.healthy else 1

    if args.command == "eval":
        if args.eval_command == "run":
            return _eval_run(args)
        if args.eval_command == "compare":
            return _eval_compare(args)

    parser.error(f"Unknown command {args.command!r}")
    return 2  # pragma: no cover - parser.error exits


if __name__ == "__main__":
    raise SystemExit(main())
