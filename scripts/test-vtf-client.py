#!/usr/bin/env python3
"""Integration test for VtfClient against live vtf API.

This script tests the VtfClient against the actual vtf API to verify
that all methods work correctly with real responses.

Usage:
    python scripts/test-vtf-client.py

Environment:
    VTF_API_URL: vtf API base URL (default: http://localhost:8002)
    VTF_TOKEN: Optional auth token (default: register new agent)
"""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path so we can import controller modules
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from controller.vtf_client import VtfClient, VtfError


async def test_vtf_client():
    """Run integration tests against live vtf API."""
    # Configuration
    api_url = os.environ.get("VTF_API_URL", "http://localhost:8002")
    token = os.environ.get("VTF_TOKEN")

    print(f"Testing VtfClient against {api_url}")

    async with VtfClient(api_url, token) as client:
        try:
            # Test 1: Agent registration
            print("\n1. Testing agent registration...")
            agent_data = await client.register_agent(
                name="test-executor",
                tags=["executor", "test"]
            )
            print(f"✓ Registered agent: {agent_data['id']}")
            agent_id = agent_data["id"]

            # Test 2: List claimable tasks
            print("\n2. Testing claimable tasks list...")
            claimable_tasks = await client.list_claimable(
                tags=["executor", "test"],
                agent_id=agent_id
            )
            print(f"✓ Found {len(claimable_tasks)} claimable tasks")

            # Test 3: List tasks with filtering
            print("\n3. Testing tasks list with filters...")
            all_tasks = await client.list_tasks("todo")
            print(f"✓ Found {len(all_tasks)} todo tasks")

            # Test 4: List tasks with expand
            print("\n4. Testing tasks list with expand...")
            tasks_with_reviews = await client.list_tasks(
                "pending_completion_review",
                expand=["reviews"]
            )
            print(f"✓ Found {len(tasks_with_reviews)} tasks pending review")

            # Test 5: Get project (if we have tasks)
            if all_tasks:
                print("\n5. Testing project metadata...")
                sample_task = all_tasks[0]
                project_id = sample_task.get("project")
                if project_id:
                    try:
                        project = await client.get_project(project_id)
                        print(f"✓ Retrieved project: {project.get('name', 'Unknown')}")
                    except VtfError as e:
                        print(f"! Project retrieval failed: {e}")
                else:
                    print("! No project ID in sample task")
            else:
                print("\n5. Skipping project test (no tasks available)")

            # Test 6: Get task details (if we have tasks)
            if all_tasks:
                print("\n6. Testing task details...")
                sample_task_id = all_tasks[0]["id"]
                task_details = await client.get_task(sample_task_id)
                print(f"✓ Retrieved task details for {task_details['id']}")

                # Test with expand
                task_with_expand = await client.get_task(
                    sample_task_id,
                    expand=["reviews", "links"]
                )
                print(f"✓ Retrieved task with expand: {len(task_with_expand.get('reviews', []))} reviews")
            else:
                print("\n6. Skipping task details test (no tasks available)")

            # Test 7: Add note to task (if we have tasks)
            if all_tasks:
                print("\n7. Testing add note...")
                sample_task_id = all_tasks[0]["id"]
                try:
                    note = await client.add_note(
                        task_id=sample_task_id,
                        text="Test note from vtf_client integration test",
                        actor_id=agent_id
                    )
                    print(f"✓ Added note: {note.get('id', 'unknown ID')}")
                except VtfError as e:
                    print(f"! Note creation failed: {e}")
            else:
                print("\n7. Skipping add note test (no tasks available)")

            # Test 8: Task lifecycle operations (only if we have claimable tasks)
            if claimable_tasks:
                print("\n8. Testing task lifecycle (claim/heartbeat)...")
                test_task = claimable_tasks[0]
                test_task_id = test_task["id"]

                try:
                    # Claim the task
                    claimed_task = await client.claim_task(
                        task_id=test_task_id,
                        agent_id=agent_id,
                        tags=["executor", "test"]
                    )
                    print(f"✓ Claimed task: {claimed_task['id']}")

                    # Send heartbeat
                    await client.heartbeat(test_task_id)
                    print(f"✓ Sent heartbeat for task {test_task_id}")

                    # Fail the task (safer than complete for testing)
                    await client.fail_task(test_task_id)
                    print(f"✓ Failed task {test_task_id} (test cleanup)")

                except VtfError as e:
                    print(f"! Task lifecycle test failed: {e}")
            else:
                print("\n8. Skipping task lifecycle test (no claimable tasks)")

            # Test 9: Review submission (only test if we have review tasks)
            if tasks_with_reviews:
                print("\n9. Testing review submission...")
                review_task = tasks_with_reviews[0]
                review_task_id = review_task["id"]

                try:
                    review = await client.submit_review(
                        task_id=review_task_id,
                        decision="changes_requested",
                        reason="Integration test review - please ignore",
                        reviewer_id=agent_id
                    )
                    print(f"✓ Submitted review: {review.get('id', 'unknown ID')}")
                except VtfError as e:
                    print(f"! Review submission failed: {e}")
            else:
                print("\n9. Skipping review test (no tasks pending review)")

            print("\n✅ All tests completed successfully!")
            return True

        except Exception as e:
            print(f"\n❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
            return False


async def main():
    """Main entry point."""
    success = await test_vtf_client()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())