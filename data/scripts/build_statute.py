"""Build statute.json: 26 U.S.C. 24 text (OLRC, cross-checked vs LII) + Federalist No. 62 quote.

Stdlib only. Run with:  uv run --no-project python scripts/build_statute.py
Every string written to statute.json is sliced verbatim from the fetched HTML
(after HTML-entity decoding); nothing is typed in by hand.
"""

import datetime as dt
import difflib
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

T0 = time.time()
DATA = Path(__file__).resolve().parents[1]
RAW = DATA / "raw"
RAW.mkdir(parents=True, exist_ok=True)

OLRC_URL = (
    "https://uscode.house.gov/view.xhtml?"
    "req=granuleid:USC-prelim-title26-section24&num=0&edition=prelim"
)
LII_URL = "https://www.law.cornell.edu/uscode/text/26/24"
FED_URL = "https://avalon.law.yale.edu/18th_century/fed62.asp"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) policyengine-30s-data/1.0"


def fetch(url: str, dest: Path) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with urllib.request.urlopen(req, timeout=60) as r:
        status = r.status
        body = r.read()
    dest.write_bytes(body)
    return {
        "url": url,
        "local_path": str(dest),
        "http_status": status,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "fetched_utc": ts,
        "fetched_local": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


sources = {
    "olrc": fetch(OLRC_URL, RAW / "usc_house_s24.html"),
    "lii": fetch(LII_URL, RAW / "lii_s24.html"),
    "federalist": fetch(FED_URL, RAW / "fed62.html"),
}

# ---------------------------------------------------------------- OLRC (official)
olrc_raw = (RAW / "usc_house_s24.html").read_text(encoding="utf-8")
m = re.search(r"<!-- documentid:(\S+)\s+usckey:(\S+)\s+currentthrough:(\S+)", olrc_raw)
olrc_currentthrough = m.group(3) if m else None
s0 = olrc_raw.index("<!-- field-start:statute -->")
s1 = olrc_raw.index("<!-- field-end:statute -->")


class OlrcBlocks(HTMLParser):
    """Collect each <h4> heading and <p> body in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.cur = [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("h4", "p"):
            self.cur = [tag, dict(attrs).get("class", ""), ""]

    def handle_endtag(self, tag):
        if tag in ("h4", "p") and self.cur is not None:
            self.blocks.append(tuple(self.cur))
            self.cur = None

    def handle_data(self, d):
        if self.cur is not None:
            self.cur[2] += d


ob = OlrcBlocks()
ob.feed(olrc_raw[s0:s1])
blocks = [(tag, cls, re.sub(r"\s+", " ", t.replace("\xa0", " ")).strip()) for tag, cls, t in ob.blocks]
assert blocks[0] == ("h4", "subsection-head", "(a) Allowance of credit"), blocks[0]

# Locate (h)(2): the "(2) Credit amount" paragraph head that follows the "(h) ..." subsection head.
h_idx = next(i for i, b in enumerate(blocks) if b[1] == "subsection-head" and b[2].startswith("(h) "))
h2_head_idx = next(
    i for i in range(h_idx + 1, len(blocks))
    if blocks[i][1] == "paragraph-head" and blocks[i][2].startswith("(2) ")
)
h2_body_idx = h2_head_idx + 1
assert blocks[h2_body_idx][0] == "p"
assert blocks[h2_body_idx + 1][2].startswith("(3) "), "h2 should be a single body paragraph"
h2_heading = blocks[h2_head_idx][2]
h2_text = blocks[h2_body_idx][2]
h_heading = blocks[h_idx][2]

# Wall text: every heading/body block of the section, (a) through the end, one per line.
wall_lines = [b[2] for b in blocks]
wall_text = "\n".join(wall_lines)
line_starts, pos = [], 0
for ln in wall_lines:
    line_starts.append(pos)
    pos += len(ln) + 1
wall_h2_offset = line_starts[h2_body_idx]
assert wall_text[wall_h2_offset : wall_h2_offset + len(h2_text)] == h2_text
wall_h2_heading_offset = line_starts[h2_head_idx]
wall_h_offset = line_starts[h_idx]
wall_words = len(wall_text.split())
subsection_offsets = {
    b[2].split(" ", 1)[0]: {"heading": b[2], "offset": line_starts[i]}
    for i, b in enumerate(blocks)
    if b[1] == "subsection-head"
}

# ---------------------------------------------------------------- LII (cross-check)
lii_raw = (RAW / "lii_s24.html").read_text(encoding="utf-8")
l0 = lii_raw.index('<div class="tab-pane active" id="tab_default_1">')
l1 = lii_raw.index('<div class="tab-pane" id="tab_default_2">')


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, d):
        self.parts.append(d)

    def handle_starttag(self, tag, attrs):
        if tag in ("div", "p", "br"):
            self.parts.append("\n")
        elif tag == "span":
            self.parts.append(" ")


to = TextOnly()
to.feed(lii_raw[l0:l1])
lii_statute_text = re.sub(r"[ \t\xa0]+", " ", "".join(to.parts))
# LII places the source credit "(Added Pub. L. ...)" inside the same tab; OLRC keeps it outside the
# statute field. Drop it so both sides cover statutory text only.
_sc = lii_statute_text.find("(Added Pub. L.")
assert _sc > 0
lii_statute_text = lii_statute_text[:_sc]

lii_h2 = re.search(
    r'<a name="h_2"></a><span class="num bold" value="2">([^<]*)</span><span class="heading bold">\s*([^<]*)</span>\s*<div class="content">\s*<p>(.*?)</p>',
    lii_raw,
    re.S,
)
lii_h2_heading = lii_h2.group(1).strip() + " " + lii_h2.group(2).strip()
lii_h2_text = re.sub(r"<[^>]+>", "", lii_h2.group(3)).strip()


def norm(s: str) -> str:
    """Map typographic punctuation to ASCII and drop whitespace, for wording comparison only."""
    tbl = {"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-"}
    for k, v in tbl.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", "", s)


h2_exact_bytes_match = h2_text == lii_h2_text
h2_crosscheck_match = norm(h2_text) == norm(lii_h2_text) and norm(h2_heading) == norm(lii_h2_heading)

# Whole-section wording cross-check (tokens after punctuation normalization).
def toks(s):
    tbl = {"“": '"', "”": '"', "‘": "'", "’": "'", "—": " - ", "–": "-"}
    for k, v in tbl.items():
        s = s.replace(k, v)
    s = s.replace("-", " - ")
    return s.split()

ot, lt = toks(wall_text), toks(lii_statute_text)
sm = difflib.SequenceMatcher(a=ot, b=lt, autojunk=False)
wall_diffs = [
    {"op": op, "olrc": " ".join(ot[i1:i2]), "lii": " ".join(lt[j1:j2])}
    for op, i1, i2, j1, j2 in sm.get_opcodes()
    if op != "equal"
]
wall_crosscheck_match = not wall_diffs

# ---------------------------------------------------------------- Federalist No. 62
fed_raw = (RAW / "fed62.html").read_text(encoding="latin-1")
fed_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fed_raw))
START = "It will be of little avail to the people"
fi = fed_text.index(START)
fj = fed_text.index(".", fi) + 1  # sentence contains no internal periods
federalist_quote = fed_text[fi:fj]
assert fed_text.count(START) == 1
fed_page_heading = "The Federalist Papers : No. 62" if "The Federalist Papers : No. 62" in fed_text else None
fed_attribution = re.search(r"For the Independent Journal\.\s*([A-Z ]+?)\s+To the People", fed_text)

# ---------------------------------------------------------------- write
uv_v = subprocess.run(["uv", "--version"], capture_output=True, text=True).stdout.strip()
out = {
    "h2_text": h2_text,
    "h2_heading": h2_heading,
    "h_heading": h_heading,
    "h2_citation": "26 U.S.C. 24(h)(2)",
    "h2_source_url": OLRC_URL,
    "h2_source_currentthrough": olrc_currentthrough,
    "h2_crosscheck_url": LII_URL,
    "h2_crosscheck_text": lii_h2_text,
    "h2_crosscheck_match": h2_crosscheck_match,
    "h2_crosscheck_exact_bytes_match": h2_exact_bytes_match,
    "h2_crosscheck_method": (
        "Identical wording and heading after mapping LII's curly quotes (“ ”) to the "
        "straight ASCII quotes OLRC renders; the two strings differ only in quote glyphs."
        if h2_crosscheck_match and not h2_exact_bytes_match
        else ("byte-identical" if h2_exact_bytes_match else "MISMATCH - see h2_crosscheck_text")
    ),
    "wall_text": wall_text,
    "wall_source_url": OLRC_URL,
    "wall_scope": "Entire statutory text of 26 U.S.C. 24, subsections (a) through (k), in order; "
    "no source credits, notes, or editorial material. One heading or body paragraph per line.",
    "wall_words": wall_words,
    "wall_chars": len(wall_text),
    "wall_h2_offset": wall_h2_offset,
    "wall_h2_span": [wall_h2_offset, wall_h2_offset + len(h2_text)],
    "wall_h2_heading_offset": wall_h2_heading_offset,
    "wall_h_subsection_offset": wall_h_offset,
    "wall_offset_units": "Python str indices (Unicode code points); text is BMP-only so these equal JS UTF-16 indices",
    "wall_subsection_offsets": subsection_offsets,
    "wall_crosscheck_url": LII_URL,
    "wall_crosscheck_match": wall_crosscheck_match,
    "wall_crosscheck_diffs": wall_diffs,
    "federalist_quote": federalist_quote,
    "federalist_url": FED_URL,
    "federalist_page_heading": fed_page_heading,
    "federalist_page_attribution": fed_attribution.group(1).strip() if fed_attribution else None,
    "federalist_page_venue": "For the Independent Journal." if "For the Independent Journal." in fed_text else None,
    "retrieved": "2026-09-24",
    "meta": {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "script": str(Path(__file__).resolve()),
        "python": sys.version.split()[0],
        "python_impl": platform.python_implementation(),
        "packages": "Python standard library only (urllib, html.parser, re, difflib, hashlib); no third-party packages",
        "uv": uv_v,
        "datasets": "none (no microdata/.h5 used; text-only task)",
        "sources": sources,
        "olrc_documentid_currentthrough": olrc_currentthrough,
        "olrc_note": "uscode.house.gov prelim edition. The page carries the HTML comment "
        "'currentthrough:" + str(olrc_currentthrough) + "' (no visible currency banner was found in the page). "
        "In this HTML view OLRC writes quotation marks as ASCII \" and uses ASCII '-' where LII shows an em-dash "
        "(e.g. (i)(2) 'equal to-' vs LII 'equal to—'); wall_text and h2_text keep OLRC's characters verbatim.",
        "pub_l_119_21_check": {
            "olrc_amendment_note_present": "Pub. L. 119&ndash;21,</pLaw> &sect;70104(a)(2), substituted \"$2,200\" for \"$2,000\"" in olrc_raw,
            # LII puts a narrow no-break space (U+202F) after the section sign, so match whitespace loosely.
            "lii_amendment_note_present": bool(re.search(
                r"Subsec\. \(h\)\(2\)\. <a [^>]*>Pub\. L\. 119–21,\s*§\s*70104\(a\)\(2\)</a>, "
                r"substituted “\$2,200” for “\$2,000”", lii_raw)),
        },
        "wall_clock_seconds": None,
    },
}
out["meta"]["wall_clock_seconds"] = round(time.time() - T0, 2)
(DATA / "statute.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({k: out[k] for k in ("h2_text", "h2_crosscheck_text", "h2_crosscheck_match",
                                      "wall_words", "wall_h2_offset", "wall_crosscheck_match",
                                      "federalist_quote", "federalist_page_attribution")}, indent=1, ensure_ascii=False))
print("diffs:", len(wall_diffs))
for d in wall_diffs[:40]:
    print(d)
print("currentthrough:", olrc_currentthrough, "runtime:", out["meta"]["wall_clock_seconds"])
