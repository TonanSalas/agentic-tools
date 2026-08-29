"""Test fixtures for the `activity` package.

The package lives under `scripts/`, which isn't importable by default, so
that directory goes on sys.path once here. No importlib loading is needed
any more -- `activity` is a real package.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import activity  # noqa: E402


@pytest.fixture(scope="session")
def ga():
    """The package namespace.

    Kept so tests can reach every module through one handle (`ga.gh`,
    `ga.collect`, ...). Patch on the *owning* module -- e.g.
    `monkeypatch.setattr(ga.gh, "gh_api", fake)` -- so call sites in other
    modules, which reach through the module object, see the fake.
    """
    return activity


@pytest.fixture
def completed():
    """Build a subprocess.CompletedProcess stand-in."""
    def _make(stdout="", returncode=0, stderr=""):
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr
        )
    return _make
