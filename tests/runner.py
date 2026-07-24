#!/usr/bin/env python3
"""Run all kcs tests with a single server instance."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.common import State, find_free_port
from tests import test_system, test_lifecycle, test_upload, test_mcp


def main():
    port = find_free_port()
    s = State(port)

    print(f"\n{'=' * 60}")
    print(f"kcs tests  port={port}")
    print(f"{'=' * 60}")

    if not s.start_server():
        print("FAILED to start server")
        sys.exit(1)

    try:
        test_system.run(s)
        test_lifecycle.run(s)
        test_upload.run(s)
        test_mcp.run(s)
    finally:
        s.stop_server()
        print("\nServer stopped.")

    ok = s.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
