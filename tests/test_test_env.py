"""The test suite's own environment (tests/conftest.py).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os


def test_the_suite_runs_numpy_with_one_openblas_thread():
    """tests/conftest.py caps OpenBLAS before anything imports numpy: otherwise every test process, and every
    fake engine (it inherits the environment), commits about 350 MB for idle OpenBLAS threads."""
    threads = os.environ.get("OPENBLAS_NUM_THREADS")     # only the value: a failure never prints the environment
    assert threads == "1"
