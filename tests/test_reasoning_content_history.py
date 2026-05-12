"""Regression coverage for provider-required reasoning_content history.

Some OpenAI-compatible thinking-mode providers require the assistant
`reasoning_content` returned on one turn to be passed back on later turns.
WebUI's API-history sanitizer must preserve that provider-owned field while
still stripping display-only `reasoning`.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from api.streaming import (
    _promote_provider_reasoning_content,
    _is_provider_error_message,
    _is_xiaomi_mimo_route,
    _restore_reasoning_metadata,
    _sanitize_messages_for_api,
)


def test_sanitize_preserves_reasoning_content_but_strips_display_reasoning():
    messages = [
        {"role": "user", "content": "think"},
        {
            "role": "assistant",
            "content": "answer",
            "reasoning": "UI-only thinking card text",
            "reasoning_content": "provider-required chain state",
            "_ts": 12345,
        },
    ]

    sanitized = _sanitize_messages_for_api(messages)

    assistant = sanitized[1]
    assert assistant["reasoning_content"] == "provider-required chain state"
    assert "reasoning" not in assistant
    assert "_ts" not in assistant


def test_promote_provider_reasoning_content_from_nested_message_metadata():
    messages = [
        {"role": "user", "content": "think"},
        {
            "role": "assistant",
            "content": "answer",
            "reasoning": "display trace",
            "additional_kwargs": {
                "reasoning_content": "provider-required opaque state",
            },
        },
    ]

    _promote_provider_reasoning_content(messages)
    sanitized = _sanitize_messages_for_api(messages)

    assert messages[1]["reasoning_content"] == "provider-required opaque state"
    assert sanitized[1]["reasoning_content"] == "provider-required opaque state"
    assert "additional_kwargs" not in sanitized[1]
    assert "reasoning" not in sanitized[1]


def test_display_reasoning_is_not_synthesized_as_reasoning_content():
    messages = [
        {"role": "user", "content": "think"},
        {
            "role": "assistant",
            "content": "answer",
            "reasoning": "UI-only thinking card text",
        },
    ]

    _promote_provider_reasoning_content(messages)
    sanitized = _sanitize_messages_for_api(messages)

    assert "reasoning_content" not in messages[1]
    assert "reasoning_content" not in sanitized[1]
    assert "reasoning" not in sanitized[1]


def test_sanitize_skips_client_side_provider_error_cards():
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "**Error:** Error code: 400 - Param Incorrect",
            "provider_details": "raw provider payload",
        },
    ]

    assert _is_provider_error_message(messages[1])
    assert _sanitize_messages_for_api(messages) == [{"role": "user", "content": "hi"}]


def test_restore_reasoning_metadata_carries_reasoning_content_forward():
    previous_messages = [
        {"role": "user", "content": "think"},
        {
            "role": "assistant",
            "content": "answer",
            "reasoning": "display trace",
            "reasoning_content": "provider-required chain state",
            "timestamp": 1713500060,
        },
    ]
    updated_messages = [
        {"role": "user", "content": "think"},
        {"role": "assistant", "content": "answer"},
    ]

    restored = _restore_reasoning_metadata(previous_messages, updated_messages)

    assert restored[1]["reasoning"] == "display trace"
    assert restored[1]["reasoning_content"] == "provider-required chain state"
    assert restored[1]["timestamp"] == 1713500060


def test_xiaomi_mimo_route_detection():
    assert _is_xiaomi_mimo_route("xiaomi", "mimo-v2.5-pro", "https://api.xiaomimimo.com/v1")
    assert _is_xiaomi_mimo_route("", "mimo-v2.5-pro", "")
    assert _is_xiaomi_mimo_route("", "", "https://api.xiaomimimo.com/v1")
    assert not _is_xiaomi_mimo_route("openai", "gpt-4o", "https://api.openai.com/v1")


def test_xiaomi_mimo_default_reasoning_is_disabled_static():
    source = (REPO_ROOT / "api" / "streaming.py").read_text(encoding="utf-8")

    assert "_is_xiaomi_mimo_route(resolved_provider, resolved_model, resolved_base_url)" in source
    assert "_reasoning_config = {'enabled': False}" in source
    assert "def _apply_agent_reasoning_config(agent, reasoning_config)" in source
    assert "setattr(agent, 'reasoning_config', reasoning_config)" in source
    assert "_apply_agent_reasoning_config(agent, _reasoning_config)" in source
    assert "_is_provider_error_message(msg)" in source
