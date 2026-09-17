"""Target key normalization and canonical key aliasing."""

from soulmate_core.keys.aliases import KeyAliasMap, ResolvedKey
from soulmate_core.keys.normalization import KEY_NORMALIZER_VERSION, normalize_key

__all__ = [
    "KEY_NORMALIZER_VERSION",
    "KeyAliasMap",
    "ResolvedKey",
    "normalize_key",
]
