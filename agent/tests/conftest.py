"""Ensure the SmartDocs-Agent project root is importable as the package root.

Lets ``from agent.tools import ...`` and ``from services import ...`` resolve
regardless of where pytest is invoked from.
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]  # …/SmartDocs-Agent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
