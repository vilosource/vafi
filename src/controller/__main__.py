"""vafi controller entry point.

Usage: python -m controller
"""

from controller.config import AgentConfig


def main():
    config = AgentConfig.from_env()
    print(config.display())


if __name__ == "__main__":
    main()
