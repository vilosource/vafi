"""Channel adapter protocol for bridge service."""

from typing import Protocol, runtime_checkable, Any


@runtime_checkable
class ChannelAdapter(Protocol):
    """Interface that all channel adapters implement."""

    async def start(self) -> None:
        """Start listening for channel events."""
        ...

    async def stop(self) -> None:
        """Stop listening, clean up connections."""
        ...

    async def send_response(self, channel_context: dict[str, Any], response: dict[str, Any]) -> None:
        """Send a response back to the originating channel."""
        ...

    async def send_notification(self, channel_context: dict[str, Any], message: str) -> None:
        """Send a notification to the channel."""
        ...
