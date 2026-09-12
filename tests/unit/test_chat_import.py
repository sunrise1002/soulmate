"""Verify provider-neutral chat history normalization."""

import json
from datetime import UTC, datetime

import pytest
from soulmate_core.domain import MessageRole
from soulmate_core.importing import ImportFormat, parse_chat_import

NOW = datetime(2026, 9, 12, tzinfo=UTC)


def test_generic_json_and_text_imports_preserve_roles_and_content() -> None:
    generic = parse_chat_import(
        json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "I prefer quiet work.",
                        "created_at": "2026-01-01T08:00:00Z",
                    },
                    {"role": "assistant", "content": "Understood."},
                ]
            }
        ),
        ImportFormat.JSON,
        imported_at=NOW,
    )
    text = parse_chat_import(
        "User: I prefer tea.\nAssistant: Noted.\nMore detail.",
        ImportFormat.TEXT,
        imported_at=NOW,
    )

    assert generic.message_count == 2
    assert generic.conversations[0].messages[0].role is MessageRole.USER
    assert generic.conversations[0].messages[0].created_at == datetime(2026, 1, 1, 8, tzinfo=UTC)
    assert text.conversations[0].messages[1].content == "Noted.\nMore detail."


def test_auto_detection_supports_chatgpt_and_claude_exports() -> None:
    chatgpt = parse_chat_import(
        json.dumps(
            [
                {
                    "mapping": {
                        "a": {
                            "message": {
                                "author": {"role": "user"},
                                "content": {"parts": ["A synthetic choice"]},
                                "create_time": 1_700_000_000,
                            }
                        },
                        "b": {
                            "message": {
                                "author": {"role": "assistant"},
                                "content": {"parts": ["A synthetic answer"]},
                                "create_time": 1_700_000_001,
                            }
                        },
                    }
                }
            ]
        ),
        imported_at=NOW,
    )
    claude = parse_chat_import(
        json.dumps(
            [
                {
                    "chat_messages": [
                        {"sender": "human", "text": "Synthetic input"},
                        {"sender": "assistant", "text": "Synthetic output"},
                    ]
                }
            ]
        ),
        imported_at=NOW,
    )

    assert chatgpt.detected_format is ImportFormat.CHATGPT
    assert chatgpt.message_count == 2
    assert claude.detected_format is ImportFormat.CLAUDE
    assert claude.message_count == 2


def test_import_rejects_empty_or_unsupported_messages() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        parse_chat_import("  ", imported_at=NOW)
    with pytest.raises(ValueError, match="supported"):
        parse_chat_import('[{"role":"system","content":"hidden"}]', imported_at=NOW)
