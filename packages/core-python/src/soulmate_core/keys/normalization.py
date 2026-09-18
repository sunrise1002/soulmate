"""Deterministic target key normalization shared by extraction and aliasing."""

import re

KEY_NORMALIZER_VERSION = "key-normalizer-v1"

_FILLER_TOKENS = frozenset({"mode", "preference", "setting", "level"})
_SEPARATORS = re.compile(r"[\s\-/]+")
_REPEATED_UNDERSCORES = re.compile(r"_+")


def _segment(value: str) -> str:
    joined = _SEPARATORS.sub("_", value.strip())
    return _REPEATED_UNDERSCORES.sub("_", joined).strip("_")


def _without_filler(segment: str) -> str:
    tokens = [token for token in segment.split("_") if token not in _FILLER_TOKENS]
    return "_".join(tokens) if tokens else segment


def normalize_key(key: str) -> str:
    """Return the ``key-normalizer-v1`` form of a free-form dotted target key.

    Casefolds, trims, turns spaces, hyphens, and slashes into single underscores,
    drops empty segments, and removes the filler tokens ``mode``, ``preference``,
    ``setting``, and ``level`` from the final segment, so ``ui.theme.dark_mode``
    and ``UI / Theme - Dark`` both become ``ui.theme.dark``. A final segment made
    only of filler tokens is kept, because dropping it would merge distinct keys.
    """
    segments = [
        segment for segment in (_segment(part) for part in key.casefold().split(".")) if segment
    ]
    if not segments:
        raise ValueError("Target key must not be empty after normalization.")
    segments[-1] = _without_filler(segments[-1])
    return ".".join(segments)
