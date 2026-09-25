"""Extract the congressional-district hex layout PolicyEngine's app draws.

Source: PolicyEngine/policyengine-app-v2, app/public/data/geojson/
congressional_districts_hex.geojson, read with `git show <commit>:<path>` so the
local checkout's working tree is never used or modified. The app renders it
with react-simple-maps `geoEquirectangular`, fitted to the layer's bounding box
(app/src/components/visualization/choropleth/USDistrictChoroplethMap.tsx).

Also extracts the app's geographic boundaries (Census cartographic boundary
file, 119th Congress, 1:20m), which the app renders with `geoAlbersUsa`, so a
video can morph between the geographic map and the hex cartogram.

Join key: `geoid` = 4-character PolicyEngine congressional_district_geoid
(state FIPS x 100 + district number; at-large states and DC use 00). The source
files give DC as Census GEOID "1198"; it is mapped to "1100" to match
PolicyEngine's microdata and region registry. `district_id` (e.g. "AK-01",
"DC-01") is the PolicyEngine API/app code and is kept as a second key.

Usage: python extract_layout.py  (writes ../../district_layout.json and
../../district_geography.json relative to this script)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
import os
from pathlib import Path

APP_REPO = Path(os.environ.get("APP_REPO", Path.home() / "PolicyEngine" / "policyengine-app-v2"))
REF = "origin/main"
HEX_PATH = "app/public/data/geojson/congressional_districts_hex.geojson"
GEO_PATH = "app/public/data/geojson/congressional_districts.geojson"
README_PATH = "app/public/data/geojson/README.md"
RENDER_PATH = "app/src/components/visualization/choropleth/USDistrictChoroplethMap.tsx"
OUT_DIR = Path(__file__).resolve().parents[2]

# PolicyEngine at-large set, copied from
# policyengine/countries/us/data/districts.py (AT_LARGE_STATES).
AT_LARGE = {"AK", "DE", "DC", "ND", "SD", "VT", "WY"}
FIPS = {
    "AL": 1, "AK": 2, "AZ": 4, "AR": 5, "CA": 6, "CO": 8, "CT": 9, "DE": 10,
    "DC": 11, "FL": 12, "GA": 13, "HI": 15, "ID": 16, "IL": 17, "IN": 18,
    "IA": 19, "KS": 20, "KY": 21, "LA": 22, "ME": 23, "MD": 24, "MA": 25,
    "MI": 26, "MN": 27, "MS": 28, "MO": 29, "MT": 30, "NE": 31, "NV": 32,
    "NH": 33, "NJ": 34, "NM": 35, "NY": 36, "NC": 37, "ND": 38, "OH": 39,
    "OK": 40, "OR": 41, "PA": 42, "RI": 44, "SC": 45, "SD": 46, "TN": 47,
    "TX": 48, "UT": 49, "VT": 50, "VA": 51, "WA": 53, "WV": 54, "WI": 55,
    "WY": 56,
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(APP_REPO), *args], check=True, capture_output=True, text=True
    ).stdout


def git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(APP_REPO), *args], check=True, capture_output=True
    ).stdout


def pe_geoid(district_id: str) -> str:
    st, num = district_id.split("-")
    dnum = 0 if st in AT_LARGE else int(num)
    return f"{FIPS[st] * 100 + dnum:04d}"


def ring_area_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    """Signed shoelace area and centroid of one ring in the (lon, lat) plane."""
    a = cx = cy = 0.0
    n = len(ring)
    for i in range(n - 1 if ring[0] == ring[-1] else n):
        x0, y0 = ring[i][:2]
        x1, y1 = ring[(i + 1) % n][:2]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if a == 0:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return a, cx / (6 * a), cy / (6 * a)


def polygons_of(geom: dict) -> list:
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    raise ValueError(geom["type"])


def centroid(polys: list) -> tuple[float, float]:
    """Area-weighted centroid in the equirectangular (lon, lat) plane.

    Outer rings add area, holes subtract it (by signed area)."""
    A = X = Y = 0.0
    for poly in polys:
        for k, ring in enumerate(poly):
            a, cx, cy = ring_area_centroid(ring)
            a = abs(a) if k == 0 else -abs(a)
            A += a
            X += a * cx
            Y += a * cy
    return X / A, Y / A


def bbox(polys: list) -> list[float]:
    xs = [p[0] for poly in polys for ring in poly for p in ring]
    ys = [p[1] for poly in polys for ring in poly for p in ring]
    return [min(xs), min(ys), max(xs), max(ys)]


def main() -> None:
    t0 = time.time()
    git_version = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    commit = git("rev-parse", REF).strip()
    commit_info = git("log", "-1", "--format=%H|%ci|%s", commit).strip()
    remote = git("remote", "get-url", "origin").strip()

    def source_record(path: str) -> dict:
        raw = git_bytes("show", f"{commit}:{path}")
        last = git("log", "-1", "--format=%H|%ci|%s", commit, "--", path).strip()
        return {
            "repo": remote,
            "commit": commit,
            "commit_info": commit_info,
            "path": path,
            "git_blob": git("rev-parse", f"{commit}:{path}").strip(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "last_changed_by_commit": last,
            "github_url": f"https://github.com/PolicyEngine/policyengine-app-v2/blob/{commit}/{path}",
        }, raw

    hex_src, hex_raw = source_record(HEX_PATH)
    geo_src, geo_raw = source_record(GEO_PATH)
    readme_src, _ = source_record(README_PATH)
    render_src, _ = source_record(RENDER_PATH)

    hexgj = json.loads(hex_raw)
    rows = []
    all_polys = []
    for f in hexgj["features"]:
        p = f["properties"]
        did = p["DISTRICT_ID"]
        st = did.split("-")[0]
        polys = polygons_of(f["geometry"])
        all_polys.extend(polys)
        cx, cy = centroid(polys)
        g = pe_geoid(did)
        rows.append(
            {
                "geoid": g,
                "district_id": did,
                "state_code": st,
                "district_number": int(g) % 100,
                "source_geoid": p["GEOID"],
                "source_label": p["CDLABEL"],
                "centroid": {"x": cx, "y": cy},
                "bbox": bbox(polys),
                "geometry_type": f["geometry"]["type"],
                "polygons": polys,
            }
        )
    rows.sort(key=lambda r: r["geoid"])
    assert len(rows) == 436 and len({r["geoid"] for r in rows}) == 436
    assert len({r["district_id"] for r in rows}) == 436

    layout = {
        "meta": {
            "title": "PolicyEngine app congressional district hex cartogram layout",
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "script": str(Path(__file__).resolve()),
            "python": sys.version,
            "packages": {"note": "Python standard library only (json, hashlib, subprocess)", "git": git_version},
            "source": hex_src,
            "source_readme": readme_src,
            "renderer_in_app": {
                **render_src,
                "projection": "geoEquirectangular (react-simple-maps), center and scale fitted to the layer's lon/lat bounding box",
            },
            "upstream": {
                "via": "https://github.com/PolicyEngine/snap-district-map (files HexCDv31/HexCDv31.shp and convert_hex_to_geojson.py; that repo declares no license)",
                "original": "The Downballot (formerly Daily Kos Elections) House hexmap, version 3.1 (per the app README and the HexCDv31 shapefile name)",
                "original_publisher_page": "https://www.the-downballot.com/p/the-downballot-releases-our-latest",
                "license": "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
                "license_evidence": "The Downballot hexmap page says the map is 'freely available under a Creative Commons license' and links that phrase to https://creativecommons.org/licenses/by/4.0/ (fetched 2026-09-24).",
                "attribution_required": "Attribute the map to The Downballot, e.g. 'District hex layout: The Downballot (CC BY 4.0)'.",
                "map_creator": "Daniel Donner (per The Downballot hexmap page)",
                "version_note": "The Downballot page (datePublished 2026-07-28) presents a newer revision that 'reflects the new maps adopted by 10 states since the 2024 elections'; the app's file is the older v3.1 layout, and its README says district IDs match the 119th Congress.",
            },
            "coordinate_system": {
                "crs": hexgj.get("crs"),
                "units": "pseudo longitude/latitude degrees; the cartogram is not geographic, positions only resemble the US shape",
                "to_screen": "Plate carree like the app: x = lon, y = -lat, then scale uniformly to fit the bbox",
                "bbox_all": bbox(all_polys),
            },
            "shape_note": "Per the app README, districts are irregular tessellating 'blob' polygons from the Daily Kos/Downballot artistic layout, not uniform hexagons, so no axial q/r grid coordinates exist. Use 'polygons' for fills and 'centroid' for labels/dots.",
            "join_key": "geoid = PolicyEngine congressional_district_geoid as 4 characters (at-large states and DC = SS00). The source files use Census GEOID 1198 for DC; source_geoid keeps the original.",
            "fields": {
                "geoid": "Join key shared with districts.json",
                "district_id": "PolicyEngine API/app district code (DISTRICT_ID in the source)",
                "state_code": "USPS state abbreviation",
                "district_number": "District number used in geoid (0 for at-large and DC)",
                "source_geoid": "GEOID property in the source file (Census style)",
                "source_label": "CDLABEL property in the source file",
                "centroid": "Area-weighted centroid of the polygons in the (lon, lat) plane",
                "bbox": "[min_x, min_y, max_x, max_y] in the same plane",
                "polygons": "List of polygons; each polygon is a list of rings (first ring outer), each ring a list of [x, y] points copied unmodified from the source GeoJSON",
            },
            "n_districts": len(rows),
            "runtime_seconds": None,
        },
        "districts": rows,
    }

    geogj = json.loads(geo_raw)
    geo_rows = []
    for f in geogj["features"]:
        p = f["properties"]
        did = p["DISTRICT_ID"]
        st = did.split("-")[0]
        if st not in FIPS:  # drops PR-98
            continue
        polys = polygons_of(f["geometry"])
        g = pe_geoid(did)
        geo_rows.append(
            {
                "geoid": g,
                "district_id": did,
                "state_code": st,
                "district_number": int(g) % 100,
                "source_geoid": p["GEOID"],
                "name": p["NAMELSAD"],
                "polygons": polys,
            }
        )
    geo_rows.sort(key=lambda r: r["geoid"])
    assert len(geo_rows) == 436 and {r["geoid"] for r in geo_rows} == {
        r["geoid"] for r in rows
    }
    geography = {
        "meta": {
            "title": "PolicyEngine app congressional district boundaries (geographic)",
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "script": str(Path(__file__).resolve()),
            "python": sys.version,
            "packages": {"note": "Python standard library only (json, hashlib, subprocess)", "git": git_version},
            "runtime_seconds": None,
            "source": geo_src,
            "upstream": "US Census Bureau cartographic boundary file cb_2024_us_cd119_20m (119th Congress, 1:20,000,000), per the app README; Census cartographic boundary files are US government works.",
            "renderer_in_app": "geoAlbersUsa (react-simple-maps) in USDistrictChoroplethMap.tsx",
            "coordinate_system": "WGS84 longitude/latitude; project with an Albers USA projection (e.g. d3.geoAlbersUsa) to match the app",
            "excluded": "PR-98 (Puerto Rico resident commissioner), not among PolicyEngine's 436 districts",
            "join_key": "geoid as in district_layout.json and districts.json",
            "n_districts": len(geo_rows),
        },
        "districts": geo_rows,
    }

    layout["meta"]["runtime_seconds"] = time.time() - t0
    geography["meta"]["runtime_seconds"] = time.time() - t0
    (OUT_DIR / "district_layout.json").write_text(json.dumps(layout, separators=(",", ":")))
    (OUT_DIR / "district_geography.json").write_text(
        json.dumps(geography, separators=(",", ":"))
    )
    print(
        json.dumps(
            {
                "layout": str(OUT_DIR / "district_layout.json"),
                "geography": str(OUT_DIR / "district_geography.json"),
                "n_hex": len(rows),
                "n_geo": len(geo_rows),
                "bbox_all": layout["meta"]["coordinate_system"]["bbox_all"],
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
