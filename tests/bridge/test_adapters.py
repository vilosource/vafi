"""Tests for bridge channel adapter interface."""

from typing import Protocol

from bridge.adapters.protocol import ChannelAdapter


class TestAdapterProtocol:
    def test_adapter_protocol_has_required_methods(self):
        assert hasattr(ChannelAdapter, "start")
        assert hasattr(ChannelAdapter, "stop")
        assert hasattr(ChannelAdapter, "send_response")
        assert hasattr(ChannelAdapter, "send_notification")

    def test_adapter_is_a_protocol(self):
        assert issubclass(ChannelAdapter, Protocol)
