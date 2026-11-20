#!/usr/bin/env python3
"""Standalone Hot Pepper Gourmet CLI."""
import sys

if sys.version_info < (3, 11, 5):
    raise SystemExit("Python >=3.11.5 required.")
try:
    from hotpepper_client.cli import main
except ModuleNotFoundError as error:
    raise SystemExit(f"Missing {error.name}; install this skill's scripts/requirements.txt.") from None

if __name__ == "__main__":
    raise SystemExit(main())
