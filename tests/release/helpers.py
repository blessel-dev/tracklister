"""Load the build scripts in packaging/ for the tests.

SPDX-License-Identifier: GPL-3.0-or-later

packaging/ is deliberately NOT a Python package (no __init__.py): a package of that name on
sys.path would shadow the `packaging` library that the update check imports. So the scripts are
loaded from their files under unique module names.
"""
from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGING = REPO / "packaging"


@lru_cache(maxsize=None)
def load(name: str):
    mod_name = f"tracklister_packaging_{name}"
    spec = importlib.util.spec_from_file_location(mod_name, PACKAGING / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod
