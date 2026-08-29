"""Load gather_activity.py (a script, not a package) as an importable module."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gather_activity.py"


def _load():
    spec = importlib.util.spec_from_file_location("gather_activity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gather_activity"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def ga():
    return _load()


@pytest.fixture
def completed():
    """Build a subprocess.CompletedProcess stand-in."""
    def _make(stdout="", returncode=0, stderr=""):
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr
        )
    return _make
