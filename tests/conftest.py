import json
import sys
from pathlib import Path

import pytest
from hypothesis import settings

# these are invariants, not timing tests: no per-example deadline (a 23 MB score buffer per
# example can overrun Hypothesis's 200 ms default on a loaded machine and fail as flaky)
settings.register_profile("invariants", deadline=None)
settings.load_profile("invariants")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def load(name):
    return json.loads((ROOT / "data" / name).read_text())


@pytest.fixture(scope="session")
def video():
    return load("video.json")


@pytest.fixture(scope="session")
def sweep():
    return load("earnings_sweep.json")


@pytest.fixture(scope="session")
def national():
    return load("national.json")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: runs PolicyEngine itself (needs data/.venv); skipped in CI")
