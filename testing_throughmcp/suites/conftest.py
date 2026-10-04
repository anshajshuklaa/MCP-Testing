"""Shared fixture for every test suite that runs against FinClusive.

The seeded bug under evaluation comes from the FINCLUSIVE_BUG environment
variable, which the runner sets; normal runs leave it empty.
"""

import os

import pytest

from finclusive.testkit import FinClusive


@pytest.fixture
def fc() -> FinClusive:
    """A fresh FinClusive app and client. Today is 2026-01-01 until a test changes it."""
    return FinClusive(bug=os.environ.get("FINCLUSIVE_BUG") or None)
