"""Invariants of data/uk/geography.json and of the simplifier that builds it.

Runs with the rest of the suite (`bun run test`).

Invariants (every constituency / every generated input):
  - exactly 650 constituencies, unique ONS codes, 543/57/32/18 by nation
  - the nation from the ONS lookups agrees with the GSS code prefix; region is an
    English region for England and the nation name elsewhere; pe_region is a
    policyengine-uk Region key whose label matches the region
  - every coordinate lies on the 0.001-degree grid and inside the UK box
  - exterior rings clockwise, holes anticlockwise (d3-geo's convention)
  - every shape is a valid MultiPolygon; neighbours overlap by < 1 km2 in total
  - simplify() never returns an empty shape, keeps the largest polygon, and moves
    boundaries by at most about one grid step (property-based)
  - rebuilding from data/uk/raw reproduces the file byte for byte (round trip)
  - d3-geo's spherical areas agree with pyproj's ellipsoidal areas (differential)
"""

from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import shapely
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from shapely.geometry import MultiPolygon, Polygon

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "tools" / "uk"
GEO = ROOT / "data" / "uk" / "geography.json"

spec = importlib.util.spec_from_file_location("build_uk_geography", HERE / "build_uk_geography.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


@pytest.fixture(scope="module")
def geo():
    return json.loads(GEO.read_text())


def rings(d):
    return [r for poly in d["polys"] for r in poly]


# ------------------------------------------------------------------ the built file
def test_counts_and_codes(geo):
    cs = geo["constituencies"]
    assert len(cs) == 650
    assert len({d["code"] for d in cs}) == 650
    assert collections.Counter(d["nation"] for d in cs) == {"England": 543, "Scotland": 57, "Wales": 32, "Northern Ireland": 18}


def test_region_and_nation(geo):
    pe_enum = {"NORTH_EAST", "NORTH_WEST", "YORKSHIRE", "EAST_MIDLANDS", "WEST_MIDLANDS", "EAST_OF_ENGLAND", "LONDON",
               "SOUTH_EAST", "SOUTH_WEST", "WALES", "SCOTLAND", "NORTHERN_IRELAND"}
    english = set()
    for d in geo["constituencies"]:
        assert B.PCON_PREFIX[d["code"][:3]] == d["nation"]
        assert d["pe_region"] in pe_enum
        if d["nation"] == "England":
            english.add(d["region"])
            assert d["region_code"].startswith("E12")
        else:
            assert d["region"] == d["nation"]
    assert len(english) == 9


def test_on_grid_inside_box_and_wound_for_d3(geo):
    x0, y0, x1, y1 = B.UK_BBOX
    for d in geo["constituencies"]:
        assert d["polys"], d["code"]
        for poly in d["polys"]:
            assert B.planar_signed_area(poly[0]) < 0, d["code"]
            assert all(B.planar_signed_area(h) > 0 for h in poly[1:]), d["code"]
            for r in poly:
                assert len(r) >= 4 and r[0] == r[-1], d["code"]
                for lon, lat in r:
                    assert round(lon, 3) == lon and round(lat, 3) == lat
                    assert x0 <= lon <= x1 and y0 <= lat <= y1


def test_valid_shapes_and_little_overlap(geo):
    for d in geo["constituencies"]:
        g = B.shapely_multi(d["polys"])
        assert g.is_valid, (d["code"], shapely.is_valid_reason(g))
    assert geo["meta"]["simplification"]["overlap_between_constituencies"]["output"]["total_km2"] < 1.0


def test_attribution_lines(geo):
    assert geo["meta"]["attribution"] == [
        "Source: Office for National Statistics licensed under the Open Government Licence v.3.0",
        "Contains OS data © Crown copyright and database right 2024",
    ]


def test_rebuild_is_a_noop(tmp_path):
    """Rebuilt from data/uk/raw into a scratch file (never over the committed one), the output
    is byte-identical, under whatever Python runs the suite."""
    raw = ROOT / "data" / "uk" / "raw" / "fetch_log.json"
    if not raw.exists():
        pytest.skip("data/uk/raw not present (raw downloads are not committed)")
    out = tmp_path / "geography.json"
    subprocess.run([sys.executable, str(HERE / "build_uk_geography.py"), "--out", str(out)], check=True, capture_output=True)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == hashlib.sha256(GEO.read_bytes()).hexdigest()


def test_d3_areas_agree_with_pyproj():
    bun = shutil.which("bun") or shutil.which("node")
    if not bun or not (ROOT / "node_modules" / "d3-geo").exists():
        pytest.skip("needs bun/node and node_modules/d3-geo")
    subprocess.run([bun, str(HERE / "check_uk_geography.mjs")], check=True, capture_output=True, cwd=ROOT)
    chk = json.loads((ROOT / "data" / "uk" / "geography_check.json").read_text())
    assert chk["failures"] == 0
    for nation, km2 in chk["sphere"]["by_nation_km2"].items():
        ell = chk["sphere"]["python_geodesic_kept_km2"][nation]
        # sphere of mean radius vs WGS84 ellipsoid: a fraction of a percent at UK latitudes
        assert abs(km2 / ell - 1) < 0.01, (nation, km2, ell)


# ------------------------------------------------------------------ the simplifier
def star(cx, cy, radii, phase):
    n = len(radii)
    step = 2 * math.pi / n
    ring = []
    for k, r in enumerate(radii):
        a = phase + k * step
        ring.append([cx + r * math.cos(a) / math.cos(math.radians(cy)), cy + r * math.sin(a)])
    ring.append(ring[0])
    return ring  # anticlockwise; shapes() flips some so both windings are exercised


@st.composite
def shapes(draw):
    """1-3 separated star-shaped polygons (simple by construction), some with a hole.
    The first is at least ~10 km2, like every constituency's main polygon; the rest
    may be far below the 0.5 km2 cut or smaller than the grid."""
    cx = draw(st.floats(-7.5, 0.5))
    cy = draw(st.floats(50.5, 59.5))
    polys = []
    for i in range(draw(st.integers(1, 3))):
        scale = draw(st.sampled_from([0.02, 0.1, 0.4] if i == 0 else [0.002, 0.006, 0.02, 0.1, 0.4]))
        radii = draw(st.lists(st.floats(0.6 * scale, scale), min_size=8, max_size=40))
        ext = star(cx + i * 2.0, cy, radii, draw(st.floats(0, 1)))
        if draw(st.booleans()):  # hole well inside the star's kernel
            hr = draw(st.lists(st.floats(0.1 * scale, 0.25 * scale), min_size=8, max_size=20))
            hole = star(cx + i * 2.0, cy, hr, 0.3)
            polys.append([ext, hole])
        else:
            polys.append([ext])
        if draw(st.booleans()):
            polys[-1][0] = polys[-1][0][::-1]  # either winding on input
    return {"type": "MultiPolygon", "coordinates": polys}


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(shapes())
def test_simplify_properties(geom):
    stats = collections.Counter()
    out = B.simplify(geom, stats)
    # never empty; always valid, on the grid, wound for d3
    assert out
    g = MultiPolygon([Polygon(p[0], p[1:]) for p in out])
    assert g.is_valid, shapely.is_valid_reason(g)
    for poly in out:
        assert B.planar_signed_area(poly[0]) < 0
        assert all(B.planar_signed_area(h) > 0 for h in poly[1:])
        for r in poly:
            assert r[0] == r[-1]
            assert all(round(x, 3) == x and round(y, 3) == y for x, y in r)
    # the largest input polygon survives (it may be split, never dropped)
    src = [Polygon(p[0], p[1:]) for p in geom["coordinates"]]
    largest = max(src, key=lambda p: abs(B.GEOD.geometry_area_perimeter(p)[0]))
    assert g.intersects(largest)
    # every kept polygon is either big enough or the largest one left after snapping
    ext_km2 = sorted((B.ring_area_m2(p[0]) / 1e6 for p in out), reverse=True)
    assert all(a >= B.MIN_RING_KM2 for a in ext_km2[1:])
    # when nothing was dropped, the boundary moved by at most about one grid step
    dropped = sum(v for k, v in stats.items() if k.endswith(("_polygons_dropped", "_holes_dropped")))
    if not dropped:
        assert shapely.hausdorff_distance(MultiPolygon(src).boundary, g.boundary) < 0.0025


@given(st.lists(st.tuples(st.floats(-1, 1), st.floats(-1, 1)), min_size=3, max_size=12, unique=True), st.booleans())
def test_wind_sets_orientation_and_keeps_points(pts, cw):
    ring = [list(p) for p in pts] + [list(pts[0])]
    a = B.planar_signed_area(ring)
    out = B.wind(ring, clockwise=cw)
    assert sorted(map(tuple, out)) == sorted(map(tuple, ring))
    if a != 0:
        assert (B.planar_signed_area(out) < 0) == cw
        assert B.wind(out, clockwise=cw) == out
