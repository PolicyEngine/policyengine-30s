"""Build data/uk/geography.json: the 650 Westminster constituencies (July 2024)
for the UK dot map, each with its English region (or nation) and nation.

Everything comes from public ONS Open Geography Portal services under the Open
Government Licence v3.0. No survey microdata is read.

  boundaries  Westminster Parliamentary Constituencies (July 2024) Boundaries UK BUC
              (ultra generalised 500 m, clipped to the coastline), fetched as
              GeoJSON in WGS84 lon/lat; also fetched in its native British
              National Grid to check the server's datum transformation
  names       Westminster Parliamentary Constituencies (July 2024) Names and Codes in the UK (V2)
  region      Ward to Westminster Parliamentary Constituency to LAD to CTYUA (July 2024)
              Lookup in the UK  (constituency -> local authority districts), then
              Local Authority District to Region (December 2024) Lookup in EN
  nation      the same ward lookup, then
              Local Authority District to Country (December 2024) Lookup in the UK
  licence     ONS "Licences" page (the attribution lines) and the ONS reference map
              of these constituencies (the year ONS puts on its own OS credit)

Cross-checks (not used to build anything): PolicyEngine's own constituency
list (policyengine-uk-data constituencies_2024.csv) and the Region enum in
policyengine-uk, which give each constituency a `pe_region` key.

Simplification: rings under 0.5 km2 (geodesic area) are dropped, except that
each constituency keeps its largest polygon; vertices are snapped to the
0.001-degree grid (3 decimals) with GEOS snap-rounding so every shape stays
valid; rings are rewound to d3-geo's winding (exterior clockwise).

Every download is saved under data/uk/raw/ with its URL, retrieval time and
sha256 in data/uk/raw/fetch_log.json; a rebuild reuses those files (and checks
their hashes) unless --refresh is passed, so rebuilding is a no-op.

usage:
  uv run --with pyproj --with shapely --with pypdf tools/uk/build_uk_geography.py [--refresh]
then check it the way the page will draw it:
  bun tools/uk/check_uk_geography.mjs
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import html
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pyproj
import shapely
from pyproj import Geod, Transformer
from pypdf import PdfReader
from shapely.geometry import MultiPolygon, Polygon

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "uk"
RAW = OUT_DIR / "raw"
OUT = OUT_DIR / "geography.json"
LOG = RAW / "fetch_log.json"

ARC = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
ITEM = "https://www.arcgis.com/sharing/rest/content/items/{}?f=json"
BUC_LAYER = f"{ARC}/Westminster_Parliamentary_Constituencies_July_2024_Boundaries_UK_BUC/FeatureServer/0"
# the exact query URL recorded when the source was first researched (2026-09-25)
BUC_QUERY = BUC_LAYER + "/query?where=1%3D1&outFields=*&outSR=4326&f=geojson"
BUC_BNG_QUERY = BUC_LAYER + "/query?where=1%3D1&outFields=PCON24CD&outSR=27700&f=json"
NAMES_LAYER = f"{ARC}/PCON_2024_UK_NC_v2/FeatureServer/0"
WARD_LAYER = f"{ARC}/WD24_PCON24_LAD24_UTLA24_UK_LU/FeatureServer/0"
RGN_LAYER = f"{ARC}/LAD24_RGN24_EN_LU/FeatureServer/0"
CTRY_LAYER = f"{ARC}/LAD24_CTRY24_UK_LU/FeatureServer/0"
ITEMS = {
    "boundaries": "ef63f363ac824b79ae9670744fcc4307",
    "names": "9a876e4777bc47e392e670a7b8bc3f5c",
    "ward_lookup": "62eb9df29a2f4521b5076a419ff9a47e",
    "lad_region": "3959874c514b470e9dd160acdc00c97a",
    "lad_country": "c7a307e84dae47f18a1bd756d18918af",
    "reference_map": "04571198b44440b9a42aaa2db43039aa",
}
LICENCES_PAGE = "https://www.ons.gov.uk/methodology/geography/licences"
REFERENCE_MAP_PDF = f"https://www.arcgis.com/sharing/rest/content/items/{ITEMS['reference_map']}/data"
ORDER_XML = "https://www.legislation.gov.uk/uksi/2023/1230/made/data.xml"
PE_UK_COMMIT = "412b25aa0a13be8809c61b19fba63f46e4518f65"
PE_REGION_ENUM = f"https://raw.githubusercontent.com/PolicyEngine/policyengine-uk/{PE_UK_COMMIT}/policyengine_uk/variables/household/demographic/geography.py"
PE_UK_DATA_COMMIT = "b45c373c6459762930d43a11bed5eaaec4131e14"
PE_CONSTITUENCIES = f"https://raw.githubusercontent.com/PolicyEngine/policyengine-uk-data/{PE_UK_DATA_COMMIT}/policyengine_uk_data/storage/constituencies_2024.csv"

ROUND = 3
# policyengine-uk-data's constituencies_2024.csv labels the East of England region "Eastern"
PE_CSV_REGION_ALIAS = {"Eastern": "East of England"}
MIN_RING_KM2 = 0.5
# generous box around the UK's extreme points (Out Stack 60.86N, Isles of Scilly
# 49.86N, St Kilda 8.6W, Lowestoft Ness 1.76E); only a sanity bound
UK_BBOX = (-8.8, 49.8, 1.8, 60.9)
NATIONS = ("England", "Wales", "Scotland", "Northern Ireland")
# ONS GSS entity codes for Westminster constituencies, used only as a cross-check
# on the nation that the published lookups give
PCON_PREFIX = {"E14": "England", "W07": "Wales", "S14": "Scotland", "N05": "Northern Ireland"}
ATTRIBUTION_YEAR = 2024

GEOD = Geod(ellps="WGS84")


# ------------------------------------------------------------------ fetching
def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Fetcher:
    def __init__(self, refresh: bool):
        self.refresh = refresh
        self.log = json.loads(LOG.read_text()) if LOG.exists() and not refresh else {}
        self.used: list[str] = []

    def get(self, name: str, url: str) -> bytes:
        path = RAW / name
        self.used.append(name)
        entry = self.log.get(name)
        if entry and path.exists() and entry["url"] == url:
            b = path.read_bytes()
            assert sha256(b) == entry["sha256"], f"{path} changed since it was fetched; rerun with --refresh"
            return b
        req = urllib.request.Request(url, headers={"User-Agent": "policyengine-30s-uk geography build (python urllib)"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    b = r.read()
                    status = r.status
                break
            except Exception as e:  # network hiccup: retry with backoff
                if attempt == 3:
                    raise
                print(f"  retry {name}: {e}", file=sys.stderr)
                time.sleep(2 ** attempt)
        path.write_bytes(b)
        self.log[name] = {
            "url": url,
            "retrieved_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "http_status": status,
            "bytes": len(b),
            "sha256": sha256(b),
        }
        print(f"  fetched {name} ({len(b):,} bytes)")
        LOG.write_text(json.dumps(self.log, indent=1, sort_keys=True) + "\n")  # so a failed run can resume
        return b

    def json(self, name: str, url: str):
        d = json.loads(self.get(name, url))
        assert "error" not in d, (name, d.get("error"))
        return d

    def table(self, stem: str, layer: str, fields: str = "*", page: int = 1000) -> list[dict]:
        """All rows of an ArcGIS table, paged by ObjectId; each page saved as its own raw file."""
        count = self.json(f"{stem}_count.json", f"{layer}/query?where=1%3D1&returnCountOnly=true&f=json")["count"]
        rows = []
        for i, off in enumerate(range(0, count, page)):
            q = urllib.parse.urlencode({
                "where": "1=1", "outFields": fields, "returnGeometry": "false", "orderByFields": "ObjectId",
                "resultOffset": off, "resultRecordCount": page, "f": "json",
            })
            d = self.json(f"{stem}_p{i:02d}.json", f"{layer}/query?{q}")
            rows += [f["attributes"] for f in d["features"]]
        assert len(rows) == count, (stem, len(rows), count)
        assert len({r["ObjectId"] for r in rows}) == count, f"{stem}: duplicate rows across pages"
        return rows

    def entry(self, name: str) -> dict:
        e = dict(self.log[name])
        e["raw_file"] = f"data/uk/raw/{name}"
        return e

    def save(self):
        keep = {k: self.log[k] for k in sorted(set(self.used))}
        LOG.write_text(json.dumps(keep, indent=1) + "\n")


def ms_utc(ms) -> str | None:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat(timespec="seconds") if ms else None


def item_summary(meta: dict) -> dict:
    lic = re.sub(r"<[^>]+>", "", html.unescape(meta.get("licenseInfo") or "")).strip()
    return {
        "arcgis_item": meta["id"],
        "title": meta["title"],
        "owner": meta["owner"],
        "item_page": f"https://www.arcgis.com/home/item.html?id={meta['id']}",
        "service_url": meta.get("url"),
        "item_created_utc": ms_utc(meta.get("created")),
        "item_modified_utc": ms_utc(meta.get("modified")),
        "license_info": lic,
    }


# ------------------------------------------------------------------ geometry
def ring_area_m2(ring) -> float:
    lons, lats = zip(*ring)
    area, _ = GEOD.polygon_area_perimeter(lons, lats)
    return abs(area)


def planar_signed_area(ring) -> float:
    return sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)) / 2


def wind(ring, clockwise: bool):
    """d3-geo's spherical convention: exterior rings clockwise, holes anticlockwise (lon/lat, y up)."""
    cw = planar_signed_area(ring) < 0
    return ring if cw == clockwise else ring[::-1]


def polygons_of(geom) -> list:
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    assert geom["type"] == "MultiPolygon", geom["type"]
    return geom["coordinates"]


def drop_small(polys, stats: collections.Counter, stage: str) -> list:
    """Drop polygons and holes under MIN_RING_KM2, always keeping the largest polygon."""
    small = MIN_RING_KM2 * 1e6
    ext_area = [ring_area_m2(p[0]) for p in polys]
    largest = max(range(len(polys)), key=lambda i: ext_area[i])
    out = []
    for i, poly in enumerate(polys):
        if ext_area[i] < small and i != largest:
            stats[f"{stage}_polygons_dropped"] += 1
            stats[f"{stage}_area_dropped_m2"] += round(ext_area[i])
            continue
        holes = [h for h in poly[1:] if ring_area_m2(h) >= small]
        stats[f"{stage}_holes_dropped"] += len(poly) - 1 - len(holes)
        out.append([poly[0], *holes])
    return out


def simplify(geom, stats: collections.Counter):
    """Drop small rings, snap to a 10^-ROUND degree grid, drop small rings again, rewind for d3."""
    polys = polygons_of(geom)
    stats["polygons_in"] += len(polys)
    stats["rings_in"] += sum(len(p) for p in polys)
    stats["vertices_in"] += sum(len(r) for p in polys for r in p)
    kept = drop_small(polys, stats, "before_snap")
    # GEOS snap-rounding: every vertex lands on the 0.001-degree grid (the same as
    # rounding to 3 decimals) and the result is repaired to stay valid, so a narrow
    # neck that rounds to a point splits into separate polygons instead of crossing itself
    snapped = shapely.set_precision(MultiPolygon([Polygon(p[0], p[1:]) for p in kept]), 10 ** -ROUND)
    parts = [snapped] if snapped.geom_type == "Polygon" else list(snapped.geoms)
    assert parts and all(g.geom_type == "Polygon" and not g.is_empty for g in parts), snapped.geom_type
    snapped_polys = [
        [[[round(x, ROUND), round(y, ROUND)] for x, y in r.coords] for r in (g.exterior, *g.interiors)] for g in parts
    ]
    stats["polygons_split_by_snapping"] += max(0, len(snapped_polys) - len(kept))
    out = []
    for poly in drop_small(snapped_polys, stats, "after_snap"):
        out.append([wind(poly[0], clockwise=True), *[wind(h, clockwise=False) for h in poly[1:]]])
    stats["polygons_out"] += len(out)
    stats["rings_out"] += sum(len(p) for p in out)
    stats["holes_out"] += sum(len(p) - 1 for p in out)
    stats["vertices_out"] += sum(len(r) for p in out for r in p)
    return out


def geodesic_area_km2(polys) -> float:
    return sum(ring_area_m2(p[0]) - sum(ring_area_m2(h) for h in p[1:]) for p in polys) / 1e6


def shapely_multi(polys) -> MultiPolygon:
    return MultiPolygon([Polygon(p[0], p[1:]) for p in polys])


def shape_of(geom) -> MultiPolygon:
    return shapely_multi(polygons_of(geom))


def overlaps(shapes: dict) -> dict:
    """Pairwise overlap between constituencies (geodesic km2 of each intersection)."""
    codes = list(shapes)
    tree = shapely.STRtree([shapes[c] for c in codes])
    pairs = []
    for i, j in zip(*tree.query([shapes[c] for c in codes], predicate="intersects")):
        if i < j:
            inter = shapes[codes[i]].intersection(shapes[codes[j]])
            if inter.area > 0:
                km2 = abs(GEOD.geometry_area_perimeter(inter)[0]) / 1e6
                pairs.append((km2, codes[i], codes[j]))
    pairs.sort(reverse=True)
    return {
        "pairs_with_positive_overlap": len(pairs),
        "total_km2": round(sum(p[0] for p in pairs), 4),
        "largest": [{"km2": round(k, 4), "codes": [a, b]} for k, a, b in pairs[:3]],
    }


# ------------------------------------------------------------------ build
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download every source instead of reusing data/uk/raw")
    ap.add_argument("--out", type=Path, default=OUT, help="where to write (the round-trip test writes elsewhere)")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    f = Fetcher(args.refresh)

    # --- metadata for every ONS source
    items = {k: f.json(f"arcgis_item_{v}.json", ITEM.format(v)) for k, v in ITEMS.items()}
    layers = {
        "boundaries": f.json("pcon24_buc_layer.json", BUC_LAYER + "?f=json"),
        "names": f.json("pcon24_names_v2_layer.json", NAMES_LAYER + "?f=json"),
        "ward_lookup": f.json("wd24_pcon24_lad24_layer.json", WARD_LAYER + "?f=json"),
        "lad_region": f.json("lad24_rgn24_layer.json", RGN_LAYER + "?f=json"),
        "lad_country": f.json("lad24_ctry24_layer.json", CTRY_LAYER + "?f=json"),
    }

    # --- boundaries
    buc_bytes = f.get("pcon24_buc_wgs84.geojson", BUC_QUERY)
    buc = json.loads(buc_bytes)
    assert not buc.get("exceededTransferLimit"), "ArcGIS truncated the boundary query"
    feats = buc["features"]
    count = f.json("pcon24_buc_count.json", BUC_LAYER + "/query?where=1%3D1&returnCountOnly=true&f=json")["count"]
    assert len(feats) == count == 650, (len(feats), count)
    bng = f.json("pcon24_buc_bng.json", BUC_BNG_QUERY)
    assert bng["spatialReference"]["wkid"] == 27700 and len(bng["features"]) == 650

    # --- lookups
    names_rows = f.table("pcon24_names_v2", NAMES_LAYER)
    ward_rows = f.table("wd24_pcon24_lad24", WARD_LAYER)
    rgn_rows = f.table("lad24_rgn24", RGN_LAYER)
    ctry_rows = f.table("lad24_ctry24", CTRY_LAYER)

    # --- licence text, verbatim from ONS
    lic_html = f.get("ons_geography_licences.html", LICENCES_PAGE).decode("utf-8")
    lic_text = re.sub(r"[ \t\r\f\v]+", " ", html.unescape(re.sub(r"<[^>]+>", "\n", lic_html)))
    lic_lines = [l.strip() for l in lic_text.split("\n") if l.strip()]
    i = lic_lines.index("Digital boundaries and reference maps:")
    boundary_block = lic_lines[i : i + 4]
    ons_line, os_line_template = boundary_block[2], boundary_block[3]
    assert boundary_block[1].startswith("Digital boundary products and reference maps are supplied under the Open Government Licence."), boundary_block
    assert ons_line == "Source: Office for National Statistics licensed under the Open Government Licence v.3.0", ons_line
    assert os_line_template == "Contains OS data © Crown copyright and database right [year]", os_line_template
    lic_updated = lic_lines[lic_lines.index("Last updated:") + 1]
    ogl_links = sorted(set(re.findall(r'href="(https?://[^"]*open-government-licence[^"]*)"', lic_html)))
    ni_clause = next((l for l in lic_lines if "not including logos or Northern Ireland data" in l), None)

    # the year ONS itself puts on the OS credit for this geography (its reference map)
    pdf = f.get("ons_pcon24_ew_reference_map.pdf", REFERENCE_MAP_PDF)
    map_text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    map_credit = next(l.strip() for l in map_text.splitlines() if "Crown copyright" in l)
    assert map_credit == f"Contains OS data © Crown copyright {ATTRIBUTION_YEAR}", map_credit

    # --- PolicyEngine cross-check sources
    pe_enum_src = f.get("policyengine_uk_geography.py", PE_REGION_ENUM).decode()
    enum_body = pe_enum_src.split("class Region(Enum):", 1)[1]
    pe_enum = dict(re.findall(r"^\s+([A-Z_]+) = \"([^\"]+)\"", enum_body, re.M))
    pe_by_label = {v.casefold(): k for k, v in pe_enum.items()}
    pe_csv = list(csv.DictReader(io.StringIO(f.get("pe_uk_data_constituencies_2024.csv", PE_CONSTITUENCIES).decode())))
    pe_con = {r["code"]: r for r in pe_csv}

    # ------------------------------------------------ join region and nation
    codes = [x["properties"]["PCON24CD"] for x in feats]
    assert len(set(codes)) == 650, "duplicate constituency codes"
    names = {r["PCON24CD"]: r["PCON24NM"] for r in names_rows}
    assert set(names) == set(codes), sorted(set(names) ^ set(codes))
    # names come from the V2 names-and-codes file; the boundary file's own names are
    # compared, not used (it writes "Glyndwr" where V2, the ward lookup and the Order write "Glyndŵr")
    buc_names = {x["properties"]["PCON24CD"]: x["properties"]["PCON24NM"] for x in feats}
    buc_name_diffs = [{"code": c, "names_v2": names[c], "boundary_file": buc_names[c]} for c in codes if names[c] != buc_names[c]]
    assert len(buc_name_diffs) <= 5, buc_name_diffs

    # and against the statute that created the constituencies (English-language names;
    # Welsh seats also carry a Welsh name in brackets, then the designation)
    order_xml = f.get("uksi_2023_1230_made.xml", ORDER_XML).decode("utf-8")
    order_names = {}
    for tr in re.finditer(r"<tr>\s*<td[^>]*>(.*?)</td>", order_xml, re.S):
        texts = [html.unescape(t).strip() for t in re.findall(r"<Text>([^<]*)</Text>", tr.group(1))]
        if texts and re.fullmatch(r"\((borough|county|burgh) constituency\)", texts[-1]):
            order_names[texts[0]] = texts[-1][1:-1]
    assert len(order_names) == 650, len(order_names)
    order_only = sorted(set(order_names) - set(names.values()))
    ons_only = sorted(set(names.values()) - set(order_names))
    unpunct = lambda s: re.sub(r"[.'’]", "", s)
    order_pairs = [{"ons": a, "order": next(b for b in order_only if unpunct(b) == unpunct(a))} for a in ons_only]
    assert len(order_only) == len(ons_only) <= 5 and len({p["order"] for p in order_pairs}) == len(order_only), (order_only, ons_only)

    lads_of = collections.defaultdict(set)
    ward_names = collections.defaultdict(set)
    for r in ward_rows:
        lads_of[r["PCON24CD"]].add(r["LAD24CD"])
        ward_names[r["PCON24CD"]].add(r["PCON24NM"])
    assert set(lads_of) == set(codes), sorted(set(lads_of) ^ set(codes))
    ward_name_diffs = [{"code": c, "names_v2": names[c], "ward_lookup": sorted(ward_names[c])} for c in codes if ward_names[c] != {names[c]}]
    assert all({n.casefold() for n in ward_names[c]} == {names[c].casefold()} for c in codes), ward_name_diffs
    region_of_lad = {r["LAD24CD"]: (r["RGN24CD"], r["RGN24NM"]) for r in rgn_rows}
    country_of_lad = {r["LAD24CD"]: (r["CTRY24CD"], r["CTRY24NM"]) for r in ctry_rows}
    all_lads = set().union(*lads_of.values())
    assert all_lads <= set(country_of_lad), sorted(all_lads - set(country_of_lad))

    joined = {}
    multi_lad = 0
    for c in codes:
        lads = lads_of[c]
        multi_lad += len(lads) > 1
        ctry = {country_of_lad[l] for l in lads}
        assert len(ctry) == 1, (c, ctry)
        (ctry_cd, nation), = ctry
        assert nation in NATIONS, nation
        assert PCON_PREFIX[c[:3]] == nation, (c, nation)
        if nation == "England":
            rg = {region_of_lad[l] for l in lads}
            assert len(rg) == 1, (c, rg)  # every English seat's districts lie in one region
            (rgn_cd, region), = rg
        else:
            rgn_cd, region = ctry_cd, nation
        joined[c] = {"region": region, "region_code": rgn_cd, "nation": nation, "nation_code": ctry_cd,
                     "pe_region": pe_by_label[region.casefold()], "lads": sorted(lads)}

    # PolicyEngine's own list agrees?
    pe_check = {
        "codes_in_both": len(set(pe_con) & set(codes)),
        "pe_rows": len(pe_con),
        "name_equal": sum(pe_con[c]["name"] == names[c] for c in codes if c in pe_con),
        "country_equal": sum(pe_con[c]["country"] == joined[c]["nation"] for c in codes if c in pe_con),
        "region_equal_casefold": sum(pe_con[c]["region"].casefold() == joined[c]["region"].casefold() for c in codes if c in pe_con),
        "region_equal_after_label_alias": sum(
            PE_CSV_REGION_ALIAS.get(pe_con[c]["region"], pe_con[c]["region"]).casefold() == joined[c]["region"].casefold()
            for c in codes if c in pe_con
        ),
        "label_alias": PE_CSV_REGION_ALIAS,
    }
    assert pe_check["codes_in_both"] == 650 and pe_check["country_equal"] == 650, pe_check
    assert pe_check["region_equal_after_label_alias"] == 650, pe_check
    pe_check["name_differences"] = [
        {"code": c, "ons": names[c], "policyengine": pe_con[c]["name"]} for c in codes if c in pe_con and pe_con[c]["name"] != names[c]
    ]
    pe_check["region_label_differences"] = [
        {"ons": a, "policyengine": b, "constituencies": n}
        for (a, b), n in sorted(collections.Counter(
            (joined[c]["region"], pe_con[c]["region"]) for c in codes
            if c in pe_con and pe_con[c]["region"].casefold() != joined[c]["region"].casefold()
        ).items())
    ]

    # ------------------------------------------------ datum check
    # does the server's WGS84 output match a local EPSG:27700 -> 4326 transform?
    tr = Transformer.from_crs(27700, 4326, always_xy=True)
    by_code = {x["properties"]["PCON24CD"]: x for x in feats}
    offsets = collections.defaultdict(list)
    over10 = collections.Counter()
    for bf in bng["features"]:
        c = bf["attributes"]["PCON24CD"]
        server = [p for poly in polygons_of(by_code[c]["geometry"]) for r in poly for p in r]
        local = [p for r in bf["geometry"]["rings"] for p in r]
        assert len(server) == len(local), c
        for (x, y) in local:
            lon, lat = tr.transform(x, y)
            best = min(server, key=lambda p: (p[0] - lon) ** 2 + (p[1] - lat) ** 2)
            dist = GEOD.inv(lon, lat, best[0], best[1])[2]
            offsets[joined[c]["nation"]].append(dist)
            over10[c] += dist > 10

    def q(v, p):
        v = sorted(v)
        return round(v[min(len(v) - 1, int(p * len(v)))], 1)

    datum = {
        "method": "For every vertex, transform the native British National Grid (EPSG:27700) coordinate with pyproj and measure the geodesic distance to the nearest vertex of the same constituency in the server's WGS84 GeoJSON.",
        "pyproj": pyproj.__version__,
        "proj": pyproj.proj_version_str,
        "metres_by_nation": {n: {"n": len(v), "median": q(v, 0.5), "p99": q(v, 0.99), "max": q(v, 1.0)} for n, v in sorted(offsets.items())},
        "vertices_over_10m_by_constituency": {c: n for c, n in sorted(over10.items()) if n},
        "reading": "Distances between the two transforms, not errors against ground truth; which side is closer for Northern Ireland was not investigated. One step of the 3-decimal rounding is about 111 m north-south.",
    }

    # ------------------------------------------------ simplify
    stats = collections.Counter()
    constituencies = []
    area_change = []
    by_nation_area = collections.defaultdict(lambda: [0.0, 0.0])
    for x in sorted(feats, key=lambda x: x["properties"]["PCON24CD"]):
        p = x["properties"]
        c = p["PCON24CD"]
        src_polys = polygons_of(x["geometry"])
        polys = simplify(x["geometry"], stats)
        assert polys and all(len(r) >= 4 for poly in polys for r in poly), c
        a_src = geodesic_area_km2(src_polys)
        a_out = geodesic_area_km2(polys)
        by_nation_area[joined[c]["nation"]][0] += a_src
        by_nation_area[joined[c]["nation"]][1] += a_out
        area_change.append((abs(a_out - a_src) / a_src, c))
        g = shapely_multi(polys)
        assert g.is_valid, (c, shapely.is_valid_reason(g))
        constituencies.append({
            "code": c,
            "name": names[c],
            "region": joined[c]["region"],
            "nation": joined[c]["nation"],
            "region_code": joined[c]["region_code"],
            "pe_region": joined[c]["pe_region"],
            "polys": polys,
        })

    # ------------------------------------------------ validate
    assert len(constituencies) == 650
    assert len({d["code"] for d in constituencies}) == 650
    nation_counts = collections.Counter(d["nation"] for d in constituencies)
    region_counts = collections.Counter(d["region"] for d in constituencies)
    x0, y0, x1, y1 = UK_BBOX
    lo = [min(pt[0] for d in constituencies for poly in d["polys"] for r in poly for pt in r),
          min(pt[1] for d in constituencies for poly in d["polys"] for r in poly for pt in r)]
    hi = [max(pt[0] for d in constituencies for poly in d["polys"] for r in poly for pt in r),
          max(pt[1] for d in constituencies for poly in d["polys"] for r in poly for pt in r)]
    for d in constituencies:
        assert d["polys"], d["code"]
        for poly in d["polys"]:
            assert poly and len(poly[0]) >= 4, d["code"]
            assert planar_signed_area(poly[0]) < 0, (d["code"], "exterior not clockwise")
            assert all(planar_signed_area(h) > 0 for h in poly[1:]), (d["code"], "hole not anticlockwise")
            for r in poly:
                for lon, lat in r:
                    assert x0 <= lon <= x1 and y0 <= lat <= y1, (d["code"], lon, lat)
    worst = max(area_change)
    assert worst[0] < 0.05, f"rounding changed {worst[1]} by {worst[0]:.1%}"
    # neighbours are snapped one at a time, so their shared borders can cross slightly;
    # measure the overlap (where a dot could sit in two constituencies), before and after
    overlap = {"source": overlaps({x["properties"]["PCON24CD"]: shape_of(x["geometry"]) for x in feats}),
               "output": overlaps({d["code"]: shapely_multi(d["polys"]) for d in constituencies})}
    assert overlap["output"]["total_km2"] < 1.0, overlap

    # ------------------------------------------------ write
    retrieved = sorted({f.log[n]["retrieved_utc"][:10] for n in f.used})
    layer_edit = lambda k: ms_utc(layers[k].get("editingInfo", {}).get("dataLastEditDate"))
    sources = {
        "boundaries": {
            **item_summary(items["boundaries"]),
            "layer_name": layers["boundaries"]["name"],
            "layer_data_last_edit_utc": layer_edit("boundaries"),
            "stored_crs": f"EPSG:{layers['boundaries']['extent']['spatialReference']['latestWkid']} (British National Grid)",
            "description": "digital vector boundaries as at 4 July 2024; BUC = ultra generalised (500 m), clipped to the coastline (Mean High Water Mark)",
            "download": f.entry("pcon24_buc_wgs84.geojson"),
            "download_native_bng_for_datum_check": f.entry("pcon24_buc_bng.json"),
            "fields_used": {"PCON24CD": "code", "geometry": "polys"},
        },
        "names": {
            **item_summary(items["names"]),
            "layer_data_last_edit_utc": layer_edit("names"),
            "why": "V2 amended the codes of five Scottish constituencies. The boundary file's 650 codes equal V2's; its names equal V2's except as listed, and `name` uses V2 (which the ward lookup and the 2023 Order agree with on those).",
            "boundary_file_name_differences": buc_name_diffs,
            "ward_lookup_name_differences_case_only": ward_name_diffs,
            "pages": [f.entry(n) for n in f.used if n.startswith("pcon24_names_v2_p")],
        },
        "ward_lookup": {
            **item_summary(items["ward_lookup"]),
            "layer_data_last_edit_utc": layer_edit("ward_lookup"),
            "rows": len(ward_rows),
            "use": "PCON24CD -> set of LAD24CD",
            "pages": [f.entry(n) for n in f.used if n.startswith("wd24_pcon24_lad24_p")],
        },
        "lad_region": {
            **item_summary(items["lad_region"]),
            "layer_data_last_edit_utc": layer_edit("lad_region"),
            "rows": len(rgn_rows),
            "use": "LAD24CD -> RGN24CD, RGN24NM (England only)",
            "pages": [f.entry(n) for n in f.used if n.startswith("lad24_rgn24_p")],
        },
        "lad_country": {
            **item_summary(items["lad_country"]),
            "layer_data_last_edit_utc": layer_edit("lad_country"),
            "rows": len(ctry_rows),
            "use": "LAD24CD -> CTRY24CD, CTRY24NM",
            "pages": [f.entry(n) for n in f.used if n.startswith("lad24_ctry24_p")],
        },
        "licences_page": {**f.entry("ons_geography_licences.html"), "page_last_updated": lic_updated},
        "name_check_statute": {
            "title": "The Parliamentary Constituencies Order 2023 (S.I. 2023/1230), as made",
            **f.entry("uksi_2023_1230_made.xml"),
            "names_in_order": len(order_names),
            "identical_to_ons_names": len(set(order_names) & set(names.values())),
            "differ_only_in_punctuation": order_pairs,
        },
        "reference_map": {**item_summary(items["reference_map"]), "download": f.entry("ons_pcon24_ew_reference_map.pdf")},
        "policyengine_crosscheck": {
            "policyengine_uk_region_enum": {**f.entry("policyengine_uk_geography.py"), "commit": PE_UK_COMMIT},
            "policyengine_uk_data_constituencies_2024": {**f.entry("pe_uk_data_constituencies_2024.csv"), "commit": PE_UK_DATA_COMMIT},
        },
    }
    meta = {
        "title": "Westminster parliamentary constituencies (July 2024), UK, for the dot map",
        "script": "tools/uk/build_uk_geography.py",
        "command": "uv run --with pyproj --with shapely --with pypdf tools/uk/build_uk_geography.py",
        "packages": {"pyproj": pyproj.__version__, "shapely": shapely.__version__},
        "retrieved_dates_utc": retrieved,
        "sources": sources,
        "licence": {
            "name": "Open Government Licence v3.0",
            "urls_on_ons_page": ogl_links,
            "ons_statement": boundary_block[1],
            "note_on_scope": "The ONS page lists these two statements for 'Digital boundaries and reference maps'. Its postcode-products section adds 'not including logos or Northern Ireland data'; that clause sits under postcode products, and the boundary item descriptions say only 'Contains both Ordnance Survey and ONS Intellectual Property Rights'. Whether any separate term covers the 18 Northern Ireland constituency boundaries was not established beyond these pages.",
            "ni_clause_verbatim": ni_clause,
        },
        "attribution": [ons_line, os_line_template.replace("[year]", str(ATTRIBUTION_YEAR))],
        "attribution_notes": {
            "template_verbatim": [ons_line, os_line_template],
            "year": f"{ATTRIBUTION_YEAR}: the boundaries are as at 4 July 2024, and ONS's own reference map of these constituencies (item {ITEMS['reference_map']}) carries '{map_credit or 'Contains OS data © Crown copyright 2024'}'.",
            "lookups": "The region and nation lookups are ONS lookup products, whose required statement is the first line alone.",
        },
        "coordinate_system": "WGS84 longitude/latitude (EPSG:4326), as served by the ONS feature service (outSR=4326)",
        "winding": "Exterior rings clockwise and holes anticlockwise in lon/lat (y up): d3-geo's spherical convention, the same as data/district_geography.json. The ONS GeoJSON follows RFC 7946 (exterior anticlockwise), which d3-geo would read as the whole globe minus the constituency, so every ring is rewound.",
        "simplification": {
            "round_decimals": ROUND,
            "min_ring_area_km2": MIN_RING_KM2,
            "rule": "1) Drop any polygon whose exterior ring, or any hole, has a geodesic area (WGS84 ellipsoid, pyproj.Geod) under 0.5 km2, but always keep each constituency's largest polygon. 2) Snap every vertex to the 0.001-degree grid, i.e. round to 3 decimals (about 111 m north-south, 54-72 m east-west across the UK), with GEOS snap-rounding (shapely.set_precision), which keeps the shape valid: a neck narrower than the grid splits into separate polygons instead of crossing itself. 3) Apply rule 1 again to the snapped parts. 4) Rewind rings for d3-geo.",
            "counts": dict(sorted(stats.items())),
            "area_km2_by_nation": {n: {"source": round(a, 1), "kept": round(b, 1), "kept_share": round(b / a, 5)} for n, (a, b) in by_nation_area.items()},
            "max_area_change_one_constituency": {"code": worst[1], "relative": round(worst[0], 5)},
            "validity": "Every constituency is a valid OGC MultiPolygon in planar lon/lat after snapping (shapely is_valid), asserted at build time.",
            "overlap_between_constituencies": overlap,
        },
        "datum_check": datum,
        "validation": {
            "constituencies": len(constituencies),
            "unique_codes": len({d["code"] for d in constituencies}),
            "by_nation": dict(sorted(nation_counts.items())),
            "by_region": dict(sorted(region_counts.items())),
            "bbox_lonlat": [lo, hi],
            "bbox_limit": list(UK_BBOX),
            "constituencies_spanning_several_lads": multi_lad,
            "every_constituency_in_one_region_and_nation": True,
            "gss_prefix_agrees_with_lookup_nation": True,
            "policyengine_constituencies_2024_csv": pe_check,
        },
        "fields": {
            "code": "PCON24CD (ONS GSS code)",
            "name": "PCON24NM from the Names and Codes (V2) file",
            "region": "RGN24NM for England; the nation name for Wales, Scotland and Northern Ireland",
            "nation": "CTRY24NM",
            "region_code": "RGN24CD for England; CTRY24CD otherwise",
            "pe_region": "policyengine-uk Region enum key whose label equals `region` (case-insensitive: ONS writes 'Yorkshire and The Humber', policyengine-uk 'Yorkshire and the Humber')",
            "polys": "MultiPolygon coordinates [[[[lon, lat], ...] ring] polygon]",
        },
    }
    out = {"meta": meta, "constituencies": constituencies}
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    args.out.write_text(text + "\n")
    f.save()
    size = len(text.encode())
    assert size < 1_500_000, f"geography.json is {size:,} bytes"
    print(f"wrote {OUT.relative_to(ROOT)}  {size:,} bytes  {len(constituencies)} constituencies  {dict(nation_counts)}")
    print(f"  vertices {stats['vertices_in']:,} -> {stats['vertices_out']:,}; polygons {stats['polygons_in']} -> {stats['polygons_out']}; worst area change {worst[0]:.2%} ({worst[1]})")
    print(f"  datum check (m): {json.dumps(datum['metres_by_nation'])}")
    print(f"  overlap between constituencies: {json.dumps(overlap)}")
    print(f"  PolicyEngine list: {json.dumps({k: v for k, v in pe_check.items() if not isinstance(v, list)})}")


if __name__ == "__main__":
    sys.exit(main())
