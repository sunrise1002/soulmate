"""Validate Phase 1 domain invariants without infrastructure."""

from datetime import datetime

import pytest
from soulmate_core.domain import Profile


def test_domain_records_reject_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Profile("profile_test", None, datetime(2026, 1, 1))
