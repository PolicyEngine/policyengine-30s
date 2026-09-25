"""Shared provenance helpers for the PolicyEngine 30s video numbers.

Every output JSON carries a ``meta`` block built here: exact package
versions, the policyengine.py release-bundle dataset selection, the sha256 of
the .h5 actually read, and wall-clock runtime.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent  # .../policyengine-30s/data
PE_DATA_DIR = DATA_DIR / "pe_data"  # policyengine.py data_folder

REFORM_PARAMETER = "gov.irs.credits.ctc.amount.base[0].amount"
REFORM_VALUE = 3_000
REFORM_START = "2026-01-01"
REFORM_STOP = "2026-12-31"
YEAR = 2026

PACKAGES = [
    "policyengine",
    "policyengine-us",
    "policyengine-core",
    "spm-calculator",
    "microdf-python",
    "numpy",
    "pandas",
    "h5py",
    "tables",
]


def package_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None
    out["python"] = sys.version.split()[0]
    out["platform"] = platform.platform()
    return out


def sha256_file(path: str | Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def bundle_us_dataset() -> dict:
    """The US dataset selection pinned by the installed policyengine.py bundle."""
    import policyengine

    manifest_path = (
        Path(policyengine.__file__).parent / "data" / "bundle" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    us = manifest["data_releases"]["us"]
    default = us["default_dataset"]
    spec = us["datasets"][default]
    return {
        "manifest_path": str(manifest_path),
        "bundle_version": manifest.get("bundle_version"),
        "bundle_id": us.get("bundle_id"),
        "build_id": us.get("build_id"),
        "default_dataset": default,
        "default_dataset_uri": us.get("default_dataset_uri"),
        "repo_id": spec["repo_id"],
        "repo_type": us["data_package"].get("repo_type"),
        "path": spec["path"],
        "revision": spec["revision"],
        "expected_sha256": spec["sha256"],
        "certification": us.get("certification"),
        "spm_measurement": manifest.get("measurements", {}).get("spm"),
    }


def reform_description() -> dict:
    return {
        "parameter": REFORM_PARAMETER,
        "yaml_path": "policyengine_us/parameters/gov/irs/credits/ctc/amount/base.yaml (bracket 0 amount)",
        "baseline_value_2026": 2_200,
        "reform_value": REFORM_VALUE,
        "period": f"{REFORM_START}.{REFORM_STOP}",
        "nothing_else_changes": True,
    }


class Timer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.laps: dict[str, float] = {}
        self._last = self.t0

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.laps[name] = round(now - self._last, 2)
        self._last = now

    def summary(self) -> dict:
        return {
            "started_at_utc": self.started_at,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "wall_clock_seconds": round(time.perf_counter() - self.t0, 2),
            "laps_seconds": self.laps,
        }


def write_json(path: str | Path, obj, compact: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(obj, separators=(",", ":"), allow_nan=False)
    else:
        text = json.dumps(obj, indent=2, allow_nan=False)
    path.write_text(text + "\n")
