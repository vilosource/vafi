"""Tests for heartbeat functionality in vafi controller.

These tests verify the heartbeat coroutine behavior during task execution,
including proper cancellation and error handling.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from src.controller.heartbeat import heartbeat_loop


class TestHeartbeatLoop:
    """Test the heartbeat_loop function behavior."""

    @pytest.fixture
    def mock_work_source(self):
        """Create a mock WorkSource for testing."""
        work_source = Mock()
        work_source.heartbeat = AsyncMock()
        return work_source

    @pytest.mark.asyncio
    async def test_heartbeat_loop_sends_periodic_heartbeats(self, mock_work_source):
        """Test that heartbeat loop sends heartbeats at the configured interval."""
        task_id = "test-task-123"
        interval = 0.1  # 100ms for fast test

        # Start heartbeat loop
        heartbeat_task = asyncio.create_task(
            heartbeat_loop(mock_work_source, task_id, interval)
        )

        try:
            # Let it run for ~250ms to get 2-3 heartbeats
            await asyncio.sleep(0.25)

            # Cancel the task
            heartbeat_task.cancel()

            # Wait for clean cancellation
            with pytest.raises(asyncio.CancelledError):
                await heartbeat_task

        except Exception:
            # Ensure task is cancelled even if test fails
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            raise

        # Verify heartbeats were sent (should be 2-3 calls in 250ms with 100ms interval)
        assert mock_work_source.heartbeat.call_count >= 2
        assert mock_work_source.heartbeat.call_count <= 4

        # Verify all calls were for the correct task
        for call in mock_work_source.heartbeat.call_args_list:
            assert call[0][0] == task_id

    @pytest.mark.asyncio
    async def test_heartbeat_loop_handles_heartbeat_errors(self, mock_work_source, caplog):
        """Test that heartbeat loop continues running even if individual heartbeats fail."""
        task_id = "test-task-456"
        interval = 0.1  # 100ms for fast test

        # Make heartbeat fail on some calls
        call_count = 0
        async def failing_heartbeat(task_id):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Simulated heartbeat failure")

        mock_work_source.heartbeat.side_effect = failing_heartbeat

        # Start heartbeat loop
        heartbeat_task = asyncio.create_task(
            heartbeat_loop(mock_work_source, task_id, interval)
        )

        try:
            # Let it run for ~350ms to get multiple heartbeats including the failure
            await asyncio.sleep(0.35)

            # Cancel the task
            heartbeat_task.cancel()

            # Wait for clean cancellation
            with pytest.raises(asyncio.CancelledError):
                await heartbeat_task

        except Exception:
            # Ensure task is cancelled even if test fails
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            raise

        # Verify heartbeats were attempted multiple times despite the failure
        assert mock_work_source.heartbeat.call_count >= 3

        # Verify error was logged but loop continued
        assert any("Heartbeat failed for task test-task-456" in record.message
                  for record in caplog.records if record.levelname == "WARNING")

    @pytest.mark.asyncio
    async def test_heartbeat_loop_cancellation_is_clean(self, mock_work_source, caplog):
        """Test that heartbeat loop cancellation is logged and handled properly."""
        task_id = "test-task-789"
        interval = 0.1  # 100ms for fast test

        # Enable INFO level logging to capture startup message
        with caplog.at_level(logging.INFO):
            # Start heartbeat loop
            heartbeat_task = asyncio.create_task(
                heartbeat_loop(mock_work_source, task_id, interval)
            )

            # Let it run briefly to ensure startup log is captured
            await asyncio.sleep(0.05)

            # Cancel the task
            heartbeat_task.cancel()

            # Wait for cancellation and verify it raises CancelledError
            with pytest.raises(asyncio.CancelledError):
                await heartbeat_task

        # Verify cancellation was logged
        assert any("Starting heartbeat loop for task test-task-789" in record.message
                  for record in caplog.records if record.levelname == "INFO")
        assert any("Heartbeat loop cancelled for task test-task-789" in record.message
                  for record in caplog.records if record.levelname == "INFO")

    @pytest.mark.asyncio
    async def test_heartbeat_loop_logs_start_and_heartbeats(self, mock_work_source, caplog):
        """Test that heartbeat loop logs startup and individual heartbeats."""
        task_id = "test-task-logging"
        interval = 0.1  # 100ms for fast test

        # Enable debug logging for this test
        with caplog.at_level(logging.DEBUG):
            # Start heartbeat loop
            heartbeat_task = asyncio.create_task(
                heartbeat_loop(mock_work_source, task_id, interval)
            )

            try:
                # Let it run for ~150ms to get 1-2 heartbeats
                await asyncio.sleep(0.15)

                # Cancel the task
                heartbeat_task.cancel()

                # Wait for clean cancellation
                with pytest.raises(asyncio.CancelledError):
                    await heartbeat_task

            except Exception:
                # Ensure task is cancelled even if test fails
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                raise

        # Verify startup log message
        startup_logs = [r for r in caplog.records
                       if "Starting heartbeat loop for task test-task-logging" in r.message]
        assert len(startup_logs) == 1
        assert "(interval=0.1s)" in startup_logs[0].message

        # Verify heartbeat debug messages (should have at least 1)
        heartbeat_logs = [r for r in caplog.records
                         if "Heartbeat sent for task test-task-logging" in r.message]
        assert len(heartbeat_logs) >= 1

    @pytest.mark.asyncio
    async def test_heartbeat_loop_with_zero_interval(self, mock_work_source):
        """Test that heartbeat loop with zero interval sends heartbeats continuously."""
        task_id = "test-task-zero-interval"
        interval = 0  # No delay between heartbeats

        # Start heartbeat loop
        heartbeat_task = asyncio.create_task(
            heartbeat_loop(mock_work_source, task_id, interval)
        )

        try:
            # Let it run for a short time
            await asyncio.sleep(0.01)  # 10ms

            # Cancel the task
            heartbeat_task.cancel()

            # Wait for clean cancellation
            with pytest.raises(asyncio.CancelledError):
                await heartbeat_task

        except Exception:
            # Ensure task is cancelled even if test fails
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            raise

        # With zero interval, should send many heartbeats very quickly
        # But we can't predict exact count due to asyncio scheduling
        assert mock_work_source.heartbeat.call_count > 0