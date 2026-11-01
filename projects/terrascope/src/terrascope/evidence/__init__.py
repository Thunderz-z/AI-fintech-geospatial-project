"""TerraScope evidence: packaging analytics claims into RELIA evidence contracts.

Status: implemented for the water-extent v0 claim (M0 step 6 start). Every
numeric TerraScope claim must ship in one of these envelopes, or abstain.
"""

from __future__ import annotations

from terrascope.evidence.water import water_extent_contract

__all__ = ["water_extent_contract"]
