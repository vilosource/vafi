"""vafi controller entry point.

Usage: python -m controller
"""

import asyncio
import logging

from controller.config import AgentConfig
from controller.controller import Controller
from controller.vtf_client import VtfClient
from controller.worksources.vtf import VtfWorkSource


def setup_logging():
    """Configure logging for the controller."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )


async def main():
    """Main entry point for the vafi controller."""
    setup_logging()
    logger = logging.getLogger(__name__)

    # Load configuration from environment
    config = AgentConfig.from_env()
    logger.info("Starting vafi controller")
    logger.info(f"\n{config.display()}")

    # Create VtfClient
    vtf_client = VtfClient(base_url=config.vtf_api_url)

    try:
        async with vtf_client:
            # Create VtfWorkSource
            work_source = VtfWorkSource(client=vtf_client, tags=config.agent_tags)

            # Create Controller
            controller = Controller(work_source=work_source, config=config)

            # Run the controller
            await controller.run()

    except Exception as e:
        logger.error(f"Failed to start controller: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
