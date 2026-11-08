#!/usr/bin/env python3
"""Source-tree and standalone skill launcher."""
import sys

if sys.version_info < (3, 10):
    raise SystemExit('Python >=3.10 required; Python 3.12+ is recommended.')
try:
    from tablecheck_client.cli import main
except ModuleNotFoundError as error:
    raise SystemExit(f'Missing dependency {error.name}; install the skill requirements or this project.') from None

raise SystemExit(main())
