"""Tests for pi_protocol.py — shared Pi RPC handshake."""

import json
import asyncio
from unittest.mock import AsyncMock

import pytest

from bridge.pi_protocol import pi_handshake
from bridge.pi_events import parse_pi_event


class TestPiHandshake:
    def test_extracts_session_id(self):
        """Handshake sends get_state and extracts sessionId from response."""
        write_fn = AsyncMock()
        response = json.dumps({
            "type": "response",
            "command": "get_state",
            "success": True,
            "data": {"sessionId": "test-session-123"},
        })

        async def read_fn():
            return response

        result = asyncio.get_event_loop().run_until_complete(
            pi_handshake(write_fn, read_fn)
        )

        assert result == "test-session-123"
        write_fn.assert_called_once()
        # Verify it sent get_state command
        sent_data = write_fn.call_args[0][0]
        parsed = json.loads(sent_data.decode("utf-8"))
        assert parsed["type"] == "get_state"

    def test_skips_init_events(self):
        """Handshake skips non-get_state events before the response."""
        write_fn = AsyncMock()
        events = [
            json.dumps({"type": "extension_ui_request", "data": {}}),
            json.dumps({"type": "session", "id": "pre-session"}),
            json.dumps({
                "type": "response",
                "command": "get_state",
                "success": True,
                "data": {"sessionId": "real-session"},
            }),
        ]
        call_count = 0

        async def read_fn():
            nonlocal call_count
            if call_count < len(events):
                event = events[call_count]
                call_count += 1
                return event
            return None

        result = asyncio.get_event_loop().run_until_complete(
            pi_handshake(write_fn, read_fn)
        )

        assert result == "real-session"
        assert call_count == 3

    def test_returns_none_on_eof(self):
        """Handshake returns None if Pi exits before responding."""
        write_fn = AsyncMock()

        async def read_fn():
            return None

        result = asyncio.get_event_loop().run_until_complete(
            pi_handshake(write_fn, read_fn)
        )

        assert result is None

    def test_returns_none_on_missing_session_id(self):
        """Handshake returns None if get_state response lacks sessionId."""
        write_fn = AsyncMock()
        response = json.dumps({
            "type": "response",
            "command": "get_state",
            "success": True,
            "data": {},
        })

        async def read_fn():
            return response

        result = asyncio.get_event_loop().run_until_complete(
            pi_handshake(write_fn, read_fn)
        )

        assert result is None
