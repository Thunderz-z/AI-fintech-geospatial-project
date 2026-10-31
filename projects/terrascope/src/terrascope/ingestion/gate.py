"""Explicit approval gate for network data retrieval.

Every network-facing step in the TerraScope ingestion pipeline (STAC search,
windowed COG reads from remote object storage) must pass through a
:class:`DownloadGate`. Local reads (cached windows on the data root, test
fixtures) are always allowed; remote reads raise
:class:`DownloadNotApprovedError` unless the gate was explicitly constructed
with ``allow_remote=True`` — which the CLI (``terrascope.ingestion.__main__``)
only does when the ``--approve`` flag is passed.

Rationale: ``AGENTS.md`` forbids dataset downloads without explicit approval,
and the M0 hard stop defers the first satellite retrieval until the portfolio
owner approves it. The gate is a code-level enforcement of that rule, not a
convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

__all__ = [
    "UNAPPROVED",
    "DownloadGate",
    "DownloadNotApprovedError",
    "is_remote_uri",
]

#: URI schemes treated as network retrieval (never silently attempted).
REMOTE_SCHEMES = frozenset({"http", "https", "s3", "gs", "abfs", "abfss", "ftp", "az"})


class DownloadNotApprovedError(RuntimeError):
    """Raised when a remote retrieval is attempted without explicit approval."""


def is_remote_uri(uri: str) -> bool:
    """Return True when *uri* targets a network resource rather than a local file."""
    return urlparse(uri).scheme.lower() in REMOTE_SCHEMES


@dataclass(frozen=True)
class DownloadGate:
    """Single decision point for remote reads.

    Construct with ``allow_remote=True`` *only* after explicit human approval
    (the CLI does this for ``--approve``). Tests and offline stages use the
    default, which permits local files and raises for anything remote.
    """

    allow_remote: bool = False

    @classmethod
    def approved(cls) -> DownloadGate:
        """The explicitly approved gate, used only behind the CLI ``--approve`` flag."""
        return cls(allow_remote=True)

    def require(self, uri: str, purpose: str) -> None:
        """Allow local *uri*; raise for remote *uri* unless approved.

        Args:
            uri: The resource to be opened (file path or remote URI).
            purpose: Human-readable description of the access, used in the
                error message so the operator knows exactly what was blocked.

        Raises:
            DownloadNotApprovedError: If *uri* is remote and the gate is not
                approved.
        """
        if is_remote_uri(uri) and not self.allow_remote:
            raise DownloadNotApprovedError(
                f"Remote access blocked by the download-approval gate ({purpose}): {uri}\n"
                "Satellite retrieval requires explicit approval. Run the ingestion CLI "
                "with --approve to perform an approved retrieval, or report to the "
                "portfolio owner per AGENTS.md."
            )


#: Shared unapproved gate: the default for offline stages and tests.
UNAPPROVED: DownloadGate = DownloadGate()
