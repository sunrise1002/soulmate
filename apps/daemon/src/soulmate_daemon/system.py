"""Installation bootstrap and local service identity."""

from datetime import UTC, datetime
from uuid import uuid4

from soulmate_core.domain import Profile, ProfileRepository, SystemMetadataRepository

INSTALLATION_ID_KEY = "installation_id"
DEFAULT_PROFILE_ID = "profile_default"


def ensure_installation(metadata: SystemMetadataRepository, profiles: ProfileRepository) -> str:
    """Create stable local installation metadata and the single owner profile."""
    now = datetime.now(UTC)
    installation_id = metadata.get_or_create(
        INSTALLATION_ID_KEY, f"installation_{uuid4().hex}", now
    )
    if profiles.get(DEFAULT_PROFILE_ID) is None:
        profiles.add(Profile(DEFAULT_PROFILE_ID, None, now))
    return installation_id
