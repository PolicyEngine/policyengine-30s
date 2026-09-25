"""Fetch and check the UK video's primary sources: statute, quotation and parameter file.

Writes (every on-screen string is sliced from a fetched source, never typed here):
  data/uk/statute.json      Income Tax Act 2007 Part 3, Chapters 1-3 (the wall) and s. 35(1) (the
                            paragraph the camera dives to), from legislation.gov.uk, with each wall
                            line cross-checked against the site's HTML view of the same Part
  data/uk/quote.json        Edward VI, 1551, from Nichols (ed.), Literary Remains of King Edward the
                            Sixth, vol. 2 (1857), p. 486, checked in the OCR of two separate scans
  data/uk/amount.yaml       policyengine-uk's personal allowance parameter file, verbatim, at the
  data/uk/amount.yaml.commit  commit recorded next to it (fetched with `gh api`)
  data/uk/raw/sources/      the fetched files themselves, with fetch_log.json (sha256 also in the JSON files)

usage (repo root):  uv run --no-project --with lxml==6.1.3 python tools/uk/fetch_sources.py [--refresh-code]
  --refresh-code re-resolves policyengine-uk main; otherwise the commit in data/uk/amount.yaml.commit is kept.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html as htmllib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "data" / "uk"
RAW = OUT / "raw" / "sources"  # own folder: data/uk/raw/ also holds the geography build's files and log
sys.path.insert(0, str(HERE))

import clml  # noqa: E402

UA = "PolicyEngine-30s-UK-video/0.1 (+https://policyengine.org; low volume, text research)"
LGU = "https://www.legislation.gov.uk"
PART3_XML = f"{LGU}/ukpga/2007/3/part/3/data.xml"
PART3_HTML = f"{LGU}/ukpga/2007/3/part/3"
S35_XML = f"{LGU}/ukpga/2007/3/section/35/data.xml"
S35_HTML = f"{LGU}/ukpga/2007/3/section/35"
FA21_S5_XML = f"{LGU}/ukpga/2021/26/section/5/data.xml"
UC_REG22_XML = f"{LGU}/uksi/2013/376/regulation/22/data.xml"
UC_REG55_XML = f"{LGU}/uksi/2013/376/regulation/55/data.xml"
IA_ID = "literaryremainso0002john"
IA_TXT = f"https://archive.org/download/{IA_ID}/{IA_ID}_djvu.txt"
CU_ID = "cu31924091758312"
CU_TXT = f"https://archive.org/download/{CU_ID}/{CU_ID}_djvu.txt"
IA_PAGE = f"https://archive.org/download/{IA_ID}/page/n291.jpg"
REPO = "PolicyEngine/policyengine-uk"
PARAM_FILE = "policyengine_uk/parameters/gov/hmrc/income_tax/allowances/personal_allowance/amount.yaml"

NEEDLE = "£12,570"
WALL_FIRST = "Part 3 Personal reliefs"
WALL_STOP = re.compile(r"^CHAPTER 3A\b", re.I)  # the wall ends where Chapter 3A begins
WALL_LABEL = "Income Tax Act 2007, Part 3, Chapters 1–3"
QUOTE_FRAGMENT = "made more plaine and short, to th’intent that men might the better understaund them"


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def fetch(url: str, name: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t = now()
    with urllib.request.urlopen(req, timeout=120) as r:
        body, status, final = r.read(), r.status, r.geturl()
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / name).write_bytes(body)
    return {"url": url, "final_url": final, "http_status": status, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "local_path": f"data/uk/raw/sources/{name}", "fetched_utc": t}


def gh(*args) -> str:
    return subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True).stdout


# ------------------------------------------------------------------ statute
def html_text(raw: str) -> str:
    """The legislation.gov.uk HTML view as one normalised text stream, change markers removed."""
    raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    raw = re.sub(r'(?s)<a class="LegCommentaryLink"[^>]*>.*?</a>', " ", raw)      # F-note links "F38"
    raw = re.sub(r'<span class="LegChangeDelimiter">[\[\]]</span>', " ", raw)     # change marks [ ]
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", raw))
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(?<=\s)U\.K\.(?=\s)", " ", t)  # extent labels after headings
    return clml.norm(t)


def statute(sources: dict) -> dict:
    root = clml.load(RAW / "ita_2007_part_3.xml")
    clml.KEEP_RETAINED_REPEALS = True  # legislation.gov.uk shows s. 37's saved text; so does the wall
    lines = clml.render_scope(root)
    texts = [ln.text for ln in lines]
    assert texts[0] == WALL_FIRST, texts[0]
    stop = next(i for i, t in enumerate(texts) if WALL_STOP.match(t))
    wall_lines = texts[:stop]
    wall = "\n".join(wall_lines)
    # the paragraph with the number, from the section's own XML (a second fetch)
    s35 = clml.render_scope(clml.load(RAW / "ita_2007_s35.xml"))
    paras = [ln.text for ln in s35 if NEEDLE in ln.text]
    assert len(paras) == 1, paras
    h2 = paras[0]
    assert h2.startswith("(1) "), h2
    assert wall.count(h2) == 1 and wall.count(NEEDLE) == 1, "s. 35(1) must appear once in the wall"
    off = wall.index(h2)
    assert wall[off:off + len(h2)] == h2
    # every wall line appears verbatim in the HTML view of Part 3
    stream = html_text((RAW / "ita_2007_part_3.html").read_text(encoding="utf-8"))
    misses = [t for t in wall_lines if t not in stream]
    casefold_only = [t for t in misses if t.casefold() in stream.casefold()]
    hard = [t for t in misses if t not in casefold_only]
    assert not hard, f"wall lines not found in the HTML view: {hard[:5]}"
    assert h2 in html_text((RAW / "ita_2007_s35.html").read_text(encoding="utf-8"))
    # metadata: version date and outstanding effects, from the XML and the HTML banner
    meta = {}
    for tag, key in (("dct:valid", "valid_from"), ("dc:modified", "modified")):
        m = re.search(rf"<{tag}>([^<]+)</{tag}>", (RAW / "ita_2007_s35.xml").read_text(encoding="utf-8"))
        meta[key] = m.group(1) if m else None
    s35_html = (RAW / "ita_2007_s35.html").read_text(encoding="utf-8")
    m = re.search(r"There are currently no known outstanding effects[^<.]*\.", htmllib.unescape(s35_html))
    meta["outstanding_effects_banner"] = m.group(0) if m else None
    assert meta["outstanding_effects_banner"], "s. 35 page no longer says there are no outstanding effects"
    # 2026-27: Finance Act 2021 s. 5(2) (as extended) specifies the s. 35(1) amount for that year
    fa = [ln.text for ln in clml.render_scope(clml.load(RAW / "fa_2021_s5.xml")) if "section 35(1)" in ln.text and NEEDLE in ln.text]
    assert len(fa) == 1 and "2026-27" in fa[0] and NEEDLE in fa[0], fa
    # the basic rate limit for 2026-27 (s. 10(5) ITA 2007, set by FA 2021 s. 5(1)): with the allowance it fixes
    # where the higher rate starts, which the family curve's "to £50,270" rests on
    brl = [ln.text for ln in clml.render_scope(clml.load(RAW / "fa_2021_s5.xml")) if "section 10(5)" in ln.text]
    assert len(brl) == 1 and "2026-27" in brl[0], brl
    brl_amount = int(re.search(r"“£([\d,]+)”", brl[0]).group(1).replace(",", ""))
    dotpad = [t for t in wall.split() if re.fullmatch(r"\.+", t)]
    return {
        "wall_text": wall,
        "wall_label": WALL_LABEL,
        "wall_scope": ("Income Tax Act 2007 (c. 3), Part 3 from its heading through the end of Chapter 3 (ss. 33-55), "
                       "the revised text as published on legislation.gov.uk, one paragraph per line; annotations and "
                       "change marks excluded; wording repealed but still displayed for savings (s. 37) included; "
                       "\". . . .\" dot padding kept as published"),
        "wall_words_whitespace_tokens": len(wall.split()),
        "wall_words_excluding_dot_padding": len(wall.split()) - len(dotpad),
        "wall_dot_padding_tokens": len(dotpad),
        "wall_chars": len(wall),
        "wall_lines": len(wall_lines),
        "wall_h2_offset": off,
        "h2_text": h2,
        "h2_citation": "Income Tax Act 2007, s. 35(1)",
        "amount": NEEDLE,
        "cite": "Income Tax Act 2007, s. 35",
        "h2_source_url": S35_HTML,
        "wall_source_url": PART3_HTML,
        "html_crosscheck": {
            "method": ("each wall line is a substring of the HTML view's text after removing tags, [ F.. ] change marks "
                       "and U.K. extent labels, closing up the spaces tag-stripping leaves inside “ ” around defined "
                       "terms, and applying the same whitespace/punctuation normalisation as the XML rendering"),
            "lines_checked": len(wall_lines),
            "lines_found_exactly": len(wall_lines) - len(misses),
            "lines_found_only_case_insensitively": casefold_only,
        },
        "s35_metadata": meta,
        "figure_for_2026_27": {"text": fa[0], "source": FA21_S5_XML.replace("/data.xml", ""),
                               "note": "Finance Act 2021 s. 5(2), as amended, specifies the s. 35(1) amount for 2026-27"},
        "basic_rate_limit_2026_27": {"amount": brl_amount, "text": brl[0], "source": FA21_S5_XML.replace("/data.xml", "")},
        "licence": "Contains public sector information licensed under the Open Government Licence v3.0 (legislation.gov.uk).",
        "sources": {k: sources[k] for k in ("part3_xml", "part3_html", "s35_xml", "s35_html", "fa21_s5_xml")},
    }


# ------------------------------------------------------------------ the law behind the curve's note
def uc_law(sources: dict) -> dict:
    """UC Regs 2013 reg. 22 (the 55% taper) and reg. 55(5) (earnings counted net of income tax), as in force."""
    r22 = [ln.text for ln in clml.render_scope(clml.load(RAW / "uc_regs_2013_reg22.xml"))
           if "55% of the amount by which that earned income exceeds the work allowance" in ln.text]
    assert r22, "reg. 22 no longer sets a 55% taper"
    r55 = [ln.text for ln in clml.render_scope(clml.load(RAW / "uc_regs_2013_reg55.xml"))]
    i = next(k for k, t in enumerate(r55) if t.startswith("(5)"))
    tax = [t for t in r55[i:i + 6] if "income tax" in t]
    assert tax, "reg. 55(5) no longer deducts income tax"
    return {
        "taper": {"text": r22, "source": UC_REG22_XML.replace("/data.xml", "")},
        "earnings_net_of_income_tax": {"text": [r55[i]] + tax, "source": UC_REG55_XML.replace("/data.xml", "")},
        "note": "checked against the note \"Universal Credit counts pay after tax, so it takes back 55p of each £1 of the tax cut.\"; the builder checks the note against the model at every point",
        "sources": {k: sources[k] for k in ("uc_reg22_xml", "uc_reg55_xml")},
    }


# ------------------------------------------------------------------ quote
def quote(sources: dict) -> dict:
    squash = lambda s: re.sub(r"\s+", " ", s)
    hits = {}
    for key in ("ia_ocr", "cu_ocr"):
        t = squash((ROOT / sources[key]["local_path"]).read_text(encoding="utf-8"))
        # the Cornell OCR prints the apostrophe straight; the page (and the IA OCR) has ’
        hits[key] = QUOTE_FRAGMENT in t or QUOTE_FRAGMENT.replace("’", "'") in t
    assert all(hits.values()), hits
    t = squash((ROOT / sources["ia_ocr"]["local_path"]).read_text(encoding="utf-8"))
    i = t.index(QUOTE_FRAGMENT)
    sentence_start = t.rindex("Nevertheles I wold wishe", 0, i)
    sentence = t[sentence_start: t.index("commonweale.", i) + len("commonweale.")]
    words = QUOTE_FRAGMENT.split()
    assert 10 <= len(words) <= 15, len(words)
    return {
        "text": f"…{QUOTE_FRAGMENT}…",
        "attr": "Edward VI · 1551",
        "fragment": QUOTE_FRAGMENT,
        "fragment_words": len(words),
        "sentence": sentence,
        "source": ("J. G. Nichols (ed.), Literary Remains of King Edward the Sixth, vol. 2 (London: Roxburghe Club, "
                   "1857), p. 486, 'Discourse on the Reformation of Abuses, 1551', section 2, 'Devising of good lawes'"),
        "source_url": f"https://archive.org/details/{IA_ID}/page/486/mode/1up",
        "date_basis": "the page's running head reads \"[A.D. 1551.\" (page image data/uk/raw/sources/edward_vi_p486.jpg, read this session)",
        "spelling": "original 1551 spelling as printed by Nichols; the apostrophe in th’intent is the page's typographic apostrophe",
        "checks": {"found_in_ocr": hits,
                   "page_image_read": "wording, spelling and punctuation of the fragment match the printed page (checked by eye, 2026-09-25)"},
        "copyright": "public domain (1551 text, 1857 edition)",
        "sources": {k: sources[k] for k in ("ia_ocr", "cu_ocr", "ia_page")},
    }


# ------------------------------------------------------------------ parameter file
def code(refresh: bool) -> dict:
    pin = OUT / "amount.yaml.commit"
    if refresh or not pin.exists():
        head = json.loads(gh(f"repos/{REPO}/commits/main"))
        sha, date = head["sha"], head["commit"]["committer"]["date"]
    else:
        sha = pin.read_text().split()[0]
        date = json.loads(gh(f"repos/{REPO}/commits/{sha}"))["commit"]["committer"]["date"]
    blob = json.loads(gh(f"repos/{REPO}/contents/{PARAM_FILE}?ref={sha}"))
    body = base64.b64decode(blob["content"])
    (OUT / "amount.yaml").write_bytes(body)
    last = json.loads(gh(f"repos/{REPO}/commits?path={PARAM_FILE}&sha={sha}&per_page=1"))[0]
    pin.write_text(f"{sha} {date} policyengine-uk main at fetch; file last changed in {last['sha'][:12]} ({last['commit']['committer']['date']})\n")
    return {"repo": REPO, "path": PARAM_FILE, "commit": sha, "commit_date": date, "blob_sha": blob["sha"],
            "sha256": hashlib.sha256(body).hexdigest(), "file_last_changed_in": last["sha"], "fetched_utc": now(),
            "url": f"https://github.com/{REPO}/blob/{sha}/{PARAM_FILE}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-code", action="store_true")
    ap.add_argument("--no-fetch", action="store_true", help="rebuild from data/uk/raw/sources and its fetch log")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    log = RAW / "fetch_log.json"
    if args.no_fetch:
        src = json.loads(log.read_text())
        for s in src.values():  # the files on disk are the ones that were fetched
            assert hashlib.sha256((ROOT / s["local_path"]).read_bytes()).hexdigest() == s["sha256"], s
    else:
        src = {
            "part3_xml": fetch(PART3_XML, "ita_2007_part_3.xml"),
            "part3_html": fetch(PART3_HTML, "ita_2007_part_3.html"),
            "s35_xml": fetch(S35_XML, "ita_2007_s35.xml"),
            "s35_html": fetch(S35_HTML, "ita_2007_s35.html"),
            "fa21_s5_xml": fetch(FA21_S5_XML, "fa_2021_s5.xml"),
            "uc_reg22_xml": fetch(UC_REG22_XML, "uc_regs_2013_reg22.xml"),
            "uc_reg55_xml": fetch(UC_REG55_XML, "uc_regs_2013_reg55.xml"),
            "ia_ocr": fetch(IA_TXT, f"{IA_ID}_djvu.txt"),
            "cu_ocr": fetch(CU_TXT, f"{CU_ID}_djvu.txt"),
            "ia_page": fetch(IA_PAGE, "edward_vi_p486.jpg"),
        }
        log.write_text(json.dumps(src, indent=1))
    st = statute(src)
    st["uc_law"] = uc_law(src)
    (OUT / "statute.json").write_text(json.dumps(st, indent=1, ensure_ascii=False))
    q = quote(src)
    (OUT / "quote.json").write_text(json.dumps(q, indent=1, ensure_ascii=False))
    c = code(args.refresh_code)
    (OUT / "code_source.json").write_text(json.dumps(c, indent=1))
    print(json.dumps({k: v for k, v in st.items() if k not in ("wall_text", "sources")}, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in q.items() if k != "sources"}, indent=1, ensure_ascii=False))
    print(json.dumps(c, indent=1))


if __name__ == "__main__":
    main()
