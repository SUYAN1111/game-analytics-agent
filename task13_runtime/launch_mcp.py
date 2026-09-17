"""Trusted launcher: remove credentials BEFORE importing/starting the MCP host."""
import os
import sys
from task13_runtime.common import clean_environment


def main():
    safe = clean_environment()
    os.environ.clear(); os.environ.update(safe)
    from task13_runtime.mcp_entry import main as serve
    serve()


if __name__ == "__main__":
    main()
