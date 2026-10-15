"""Suite-wide guards (PRJ-06 step 12.6)."""

import pytest

from tools.bounded_run import check


def pytest_configure(config):
    # On the Dell a test run must be capped (the Gemma encoder in sovereign-server can take ~1.5 GB at any moment)
    # and stay out of the 03:30-05:30 backup window. Other hosts and CI are not checked.
    reason = check("pytest run")
    if reason:
        pytest.exit(reason, returncode=2)
