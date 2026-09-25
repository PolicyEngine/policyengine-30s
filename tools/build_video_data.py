"""Assemble data/video.json: every string and number the video displays.

Reads the PolicyEngine outputs in data/ (statute.json, household.json,
national.json, households_sample.json, districts.json, district_layout.json)
plus the parameter file snapshot data/base.yaml. Anything missing is filled
with MOCK_ values and the file is flagged "mock": true, which makes the page
paint a MOCK DATA banner on every frame.

usage: uv run --with pyyaml tools/build_video_data.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load(name):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else None


def code_block():
    lines = (DATA / "base.yaml").read_text().splitlines()
    meta = yaml.safe_load((DATA / "base.yaml").read_text())
    first, last = 7, 26  # "amount:" through the § 24(h)(2) reference href
    block = lines[first - 1 : last]
    value_line = next(i for i, l in enumerate(lines, 1) if "2025-01-01: 2_200" in l)
    arpa_line = next(i for i, l in enumerate(lines, 1) if "arpa.yaml" in l)
    ref_line = next(i for i, l in enumerate(lines, 1) if "§ 24(h)(2)" in l)
    assert first <= value_line <= last and first <= arpa_line <= last and first <= ref_line <= last
    label = meta["metadata"]["label"]
    commit = (DATA / "base.yaml.commit").read_text().split()[0]
    return {
        "file": "policyengine_us/parameters/gov/irs/credits/ctc/amount/base.yaml",
        "dedent": min(len(l) - len(l.lstrip()) for l in block if l.strip()),
        "first": first,
        "lines": block,
        "valueLine": value_line,
        "arpaLine": arpa_line,
        "refLine": ref_line,
        "label": label,
        "commit": commit,
    }


def provenance(year):
    n = load("national.json")
    if not n:
        return ["MOCK provenance"]
    v = n["meta"]["versions"]
    ds = n["meta"]["dataset"]["default_dataset"]
    nv = load("nation_video.json") or {}
    dr = nv.get("draws") or {}
    return [
        f"policyengine.py {v['policyengine']} · policyengine-us {v['policyengine-us']} · dataset {ds}",
        f"Tax year {year} · static, no behavioral responses · poverty: Supplemental Poverty Measure",
        f"Map: {dr.get('n', 12000):,} weighted draws of {dr.get('unique') or 0:,} distinct households",
    ]


def cd_geometry():
    """Census cb_2024 cd119 district shapes (via policyengine-app-v2), rounded for size."""
    g = load("district_geography.json")
    if not g:
        return []
    out = []
    for d in g["districts"]:
        polys = [[[[round(x, 3), round(y, 3)] for x, y in ring] for ring in poly] for poly in d["polygons"]]
        out.append({"geoid": d["geoid"], "polys": polys})
    return out


def main():
    mock_parts = []
    code = code_block()
    # the reform card and chip come from the dict PolicyEngine received and the
    # baseline value the model read, never from constants typed here
    # no fallback: a missing or stale household.json must stop the build, not ship defaults
    hmeta = load("household.json")["meta"]
    rdict = hmeta["reform_dict_passed"]
    ((rpath, periods),) = rdict.items()
    ((rperiod, rvalue),) = periods.items()
    assert rvalue == int(rvalue), f"reform value {rvalue} would be rounded on screen"
    video = {
        "mock": False,
        "reform": {
            "label": code["label"],
            "path": rpath,
            "from": int(hmeta["reform"]["baseline_value_2026"]),
            "to": int(rvalue),
            "year": int(rperiod[:4]),
            "dict": rdict,
        },
        "cdGeo": cd_geometry(),
        "code": code,
        "signoff": 'Free and open source · <b>policyengine.org</b>',
        "provenance": provenance(int(rperiod[:4])),
    }

    st = load("statute.json")
    if st:
        amount = "$2,200"
        assert amount in st["h2_text"], "statute (h)(2) text lacks $2,200"
        video["statute"] = {
            "wall": st["wall_text"],
            "wall_h2_offset": st.get("wall_h2_offset"),
            "h2": st["h2_text"],
            "amount": amount,
            "cite": "26 U.S.C. § 24(h)(2)",
            "source": st["h2_source_url"],
        }
        fq = st["federalist_quote"]
        frag = "if the laws be so voluminous that they cannot be read"
        assert frag in fq, "Federalist fragment not found verbatim"
        video["quote"] = {
            "text": f"…{frag}…",
            "attr": "Federalist No. 62 · 1788",
            "source": st["federalist_url"],
            "date_source": "https://founders.archives.gov/documents/Madison/01-10-02-0309",
        }
    else:
        mock_parts.append("statute")
        video["statute"] = {"wall": "MOCK STATUTE TEXT " * 900, "h2": "MOCK $2,200", "amount": "$2,200", "cite": "26 U.S.C. § 24(h)(2)"}
        video["quote"] = {"text": "…the laws be so voluminous that they cannot be read…", "attr": "Federalist No. 62 · 1788"}

    hh = load("household_video.json")  # written by tools/adapt_outputs.py once real outputs land
    if hh:
        video["household"] = hh
    else:
        mock_parts.append("household")
        video["household"] = {
            "who": "<b>MOCK</b> household",
            "rows": [
                {"label": "Earnings", "base": 60000, "reform": 60000, "kind": "start"},
                {"label": "Taxes", "base": -9000, "reform": -9000, "kind": "minus"},
                {"label": "Child Tax Credit", "base": 4400, "reform": 6000, "kind": "plus"},
                {"label": "Net income", "base": 55400, "reform": 57000, "kind": "total"},
            ],
            "gain": 1600,
            "caption": ["MOCK family gains ", "$0"],
        }

    nat = load("nation_video.json")
    if nat:
        video["nation"] = nat
    else:
        mock_parts.append("nation")
        video["nation"] = {
            "caption": ["MOCK ", "caption"],
            "stats": [
                {"kind": "billion", "value": 0, "what": "MOCK federal cost"},
                {"kind": "pct", "value": 0, "what": "MOCK share gaining"},
            ],
            "dotNote": "MOCK dots",
            "deciles": {"avg": [0] * 10, "caption": ["MOCK ", "deciles"]},
            "dotMax": 3200,
        }

    samp = load("sample_video.json")
    if samp:
        video["sample"] = samp
    else:
        mock_parts.append("sample")
        import random

        rnd = random.Random(99)
        fips = [6, 48, 12, 36, 42, 17, 39, 13, 37, 26, 34, 51, 53, 4, 47, 18, 25, 29, 24, 55]
        video["sample"] = [[rnd.choice(fips), rnd.choice([0, 0, 800, 1600]), None, rnd.randint(1, 10)] for _ in range(12000)]

    video["districts"] = None  # see adapt_outputs.py: district estimates too noisy to show
    video["deciles"] = video["nation"].get("deciles")

    if mock_parts:
        video["mock"] = True
        video["mock_parts"] = mock_parts
    (DATA / "video.json").write_text(json.dumps(video, ensure_ascii=False))
    print(f"wrote data/video.json  mock={video['mock']}  parts={mock_parts}")


if __name__ == "__main__":
    sys.exit(main())
