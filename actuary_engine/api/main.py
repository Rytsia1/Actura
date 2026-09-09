"""
Compatibility shim redirecting actuary_engine.api.main to actuary_engine.main.
"""
from actuary_engine.main import *  # noqa: F401, F403
from actuary_engine.main import app  # Explicit re-export
