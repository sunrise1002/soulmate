"""Test the versioned, deterministic target key normalizer."""

import pytest
from soulmate_core.keys import KEY_NORMALIZER_VERSION, normalize_key


def test_normalizer_version_is_pinned() -> None:
    assert KEY_NORMALIZER_VERSION == "key-normalizer-v1"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("ui.theme.dark", "ui.theme.dark"),
        ("ui.theme.dark_mode", "ui.theme.dark"),
        ("UI.Theme.Dark_Mode", "ui.theme.dark"),
        ("  UI.Theme. Dark Mode  ", "ui.theme.dark"),
        ("ui.theme.dark-mode", "ui.theme.dark"),
        ("UI / Theme - Dark Mode", "ui_theme_dark"),
        ("ui..theme...dark_mode", "ui.theme.dark"),
        (".ui.theme.dark_mode.", "ui.theme.dark"),
        ("ui.theme.dark___mode", "ui.theme.dark"),
        ("ui.theme.dark_mode_setting", "ui.theme.dark"),
        ("work.remote", "work.remote"),
        ("giao diện.Tối", "giao_diện.tối"),
    ],
)
def test_equivalent_spellings_normalize_to_one_key(key: str, expected: str) -> None:
    assert normalize_key(key) == expected


def test_normalization_is_idempotent() -> None:
    once = normalize_key("  UI.Theme. Dark Mode  ")

    assert normalize_key(once) == once


def test_filler_tokens_outside_the_final_segment_are_kept() -> None:
    assert normalize_key("mode.setting.dark") == "mode.setting.dark"


def test_final_segment_made_only_of_filler_is_kept() -> None:
    assert normalize_key("notification.sound.level") == "notification.sound.level"
    assert normalize_key("mode") == "mode"


def test_distinct_concepts_do_not_collapse_into_one_key() -> None:
    assert normalize_key("ui.theme.dark") != normalize_key("ui.theme.light")
    assert normalize_key("work.remote") != normalize_key("work.remote_office")


@pytest.mark.parametrize("key", ["", "   ", ".", "...", "___", " - / ", "\t\n"])
def test_keys_without_any_content_are_rejected(key: str) -> None:
    with pytest.raises(ValueError, match="must not be empty after normalization"):
        normalize_key(key)
