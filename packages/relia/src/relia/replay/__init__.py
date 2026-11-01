"""Record/replay cassettes for deterministic provider interactions.

Schema lives in ``relia.replay.base`` (protected interface); the recorder and
replayer implementations live in ``relia.replay.cassette``.
"""

from relia.replay.base import Cassette, RecordedInteraction, ReplayMismatchError
from relia.replay.cassette import (
    RecordingProvider,
    ReplayProvider,
    load_cassette,
    save_cassette,
)

__all__ = [
    "Cassette",
    "RecordedInteraction",
    "RecordingProvider",
    "ReplayMismatchError",
    "ReplayProvider",
    "load_cassette",
    "save_cassette",
]
