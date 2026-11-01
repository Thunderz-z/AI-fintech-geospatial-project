"""Tests for cassette recording/replay — network-free by construction."""

from __future__ import annotations

import asyncio

import pytest

from relia.providers.base import (
    CompletionRequest,
    LLMProvider,
    Message,
)
from relia.providers.fake import ScriptedProvider, scripted_response
from relia.replay import (
    Cassette,
    RecordedInteraction,
    RecordingProvider,
    ReplayMismatchError,
    ReplayProvider,
    load_cassette,
    save_cassette,
)


def run(coro):
    return asyncio.run(coro)


def make_request(content: str = "hi", **overrides) -> CompletionRequest:
    defaults: dict = {
        "model": "m",
        "messages": [Message(role="user", content=content)],
    }
    defaults.update(overrides)
    return CompletionRequest(**defaults)


def record_simple_cassette() -> tuple[Cassette, RecordingProvider]:
    inner = ScriptedProvider.text("first answer", "second answer", name="scripted")
    recorder = RecordingProvider(inner, cassette_id="test-cassette")
    run(recorder.complete(make_request("q1")))
    run(recorder.complete(make_request("q2")))
    return recorder.cassette, recorder


def test_recording_provider_captures_interactions() -> None:
    inner = ScriptedProvider.text("answer", name="scripted")
    recorder = RecordingProvider(inner, cassette_id="c-1")

    response = run(recorder.complete(make_request("q")))

    assert response.text == "answer"
    assert recorder.name == "scripted"
    assert recorder.cassette.cassette_id == "c-1"
    assert recorder.cassette.provider == "scripted"
    assert len(recorder.cassette.interactions) == 1
    assert recorder.cassette.interactions[0].request["messages"][0]["content"] == "q"
    assert recorder.cassette.interactions[0].response["text"] == "answer"


def test_save_and_load_round_trip(tmp_path) -> None:
    cassette, _ = record_simple_cassette()

    path = save_cassette(cassette, tmp_path / "tapes" / "c.json")
    loaded = load_cassette(path)

    assert loaded == cassette  # includes the recorded_at timestamps


def test_recording_provider_save_helper(tmp_path) -> None:
    _, recorder = record_simple_cassette()

    path = recorder.save(tmp_path / "c.json")

    assert load_cassette(path).cassette_id == "test-cassette"


def test_replay_returns_recorded_responses_in_order() -> None:
    cassette, _ = record_simple_cassette()
    replayer = ReplayProvider(cassette)

    first = run(replayer.complete(make_request("q1")))
    second = run(replayer.complete(make_request("q2")))

    assert first.text == "first answer"
    assert second.text == "second answer"
    assert replayer.consumed == 2
    assert replayer.remaining == 0
    replayer.verify_complete()  # must not raise


def test_replay_is_network_free_via_file_round_trip(tmp_path) -> None:
    cassette, _ = record_simple_cassette()
    path = save_cassette(cassette, tmp_path / "c.json")
    replayer = ReplayProvider(load_cassette(path))

    response = run(replayer.complete(make_request("q1")))

    assert response.text == "first answer"
    assert response.provider == "scripted"
    assert response.usage.input_tokens == 1


def test_replay_request_divergence_raises() -> None:
    cassette, _ = record_simple_cassette()
    replayer = ReplayProvider(cassette)

    with pytest.raises(ReplayMismatchError, match="does not match the outgoing request"):
        run(replayer.complete(make_request("different question")))


def test_replay_request_divergence_reports_differing_keys() -> None:
    cassette, _ = record_simple_cassette()
    replayer = ReplayProvider(cassette)

    with pytest.raises(ReplayMismatchError, match=r"temperature.*recorded 0\.0"):
        run(replayer.complete(make_request("q1", temperature=0.7)))


def test_replay_exhaustion_raises() -> None:
    cassette, _ = record_simple_cassette()
    replayer = ReplayProvider(cassette)
    run(replayer.complete(make_request("q1")))
    run(replayer.complete(make_request("q2")))

    with pytest.raises(ReplayMismatchError, match="exhausted"):
        run(replayer.complete(make_request("q3")))


def test_verify_complete_detects_unreplayed_interactions() -> None:
    cassette, _ = record_simple_cassette()
    replayer = ReplayProvider(cassette)
    run(replayer.complete(make_request("q1")))

    with pytest.raises(ReplayMismatchError, match="never replayed"):
        replayer.verify_complete()


def test_corrupt_recorded_response_raises_mismatch() -> None:
    cassette = Cassette(
        cassette_id="broken",
        provider="scripted",
        model="m",
        interactions=[
            RecordedInteraction(request=make_request().model_dump(mode="json"),
                                response={"nope": True})
        ],
    )
    replayer = ReplayProvider(cassette)

    with pytest.raises(ReplayMismatchError, match="not a valid CompletionResponse"):
        run(replayer.complete(make_request()))


def test_structured_output_and_cost_survive_record_replay(tmp_path) -> None:
    inner = ScriptedProvider(
        scripted_response(
            '{"answer": "42"}',
            structured={"answer": "42"},
            input_tokens=11,
            output_tokens=7,
            cost_usd=0.00025,
        ),
        name="scripted",
    )
    recorder = RecordingProvider(inner, cassette_id="structured-c")
    request = make_request("q", response_schema={"type": "object"})
    run(recorder.complete(request))
    path = recorder.save(tmp_path / "structured.json")

    replayer = ReplayProvider(load_cassette(path))
    replayed = run(replayer.complete(request))

    assert replayed.structured == {"answer": "42"}
    assert replayed.cost_usd == pytest.approx(0.00025)
    assert replayed.usage.input_tokens == 11
    replayer.verify_complete()
    assert replayer.cassette_id == "structured-c"


def test_replay_mismatch_error_is_raised_not_swallowed_for_schema_changes() -> None:
    # A change in the requested response schema invalidates the tape.
    cassette, _ = record_simple_cassette()
    replayer = ReplayProvider(cassette)

    with pytest.raises(ReplayMismatchError):
        run(replayer.complete(make_request("q1", response_schema={"type": "object"})))


def test_recorder_and_replayer_satisfy_provider_protocol() -> None:
    recorder = RecordingProvider(ScriptedProvider.text("x"), cassette_id="c")
    assert isinstance(recorder, LLMProvider)
    empty = Cassette(cassette_id="c", provider="p", model="m")
    assert isinstance(ReplayProvider(empty), LLMProvider)
