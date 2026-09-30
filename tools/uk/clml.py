"""Minimal CLML (legislation.gov.uk Crown Legislation Markup Language) to plain text.

Renders the statutory text of a CLML document or fragment one paragraph per
line, the way legislation.gov.uk lays it out: section/regulation headings on
their own line, then "(1) ...", "(a) ...", "(i) ..." lines. Annotation
(Commentary) text, footnotes, metadata, prelims, the signature block and
explanatory notes are excluded; CommentaryRef markers are dropped.

Only the text content of the XML is used; nothing is paraphrased. Two
renderings are NOT verbatim character streams from the source and are
flagged by callers:
  * MathML formulas are linearised ("(ANI – L) / X %").
  * Table rows are joined with " | " between cells.

Carried over from the statute research scripts (2026-09-25)
(2026-09-25) with three changes, each found by checking every rendered line of
ITA 2007 Part 3 against the site's HTML view (tools/uk/fetch_sources.py):
  * runs of dots (". . . ." padding and "... ." omissions) keep their published
    spacing instead of being squeezed to "...." by the punctuation fix in norm();
  * no space inside the curly quotes around a defined term ("“the minimum amount”");
  * a section number's PuncAfter is kept ("43A." is printed with its full stop).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

LEG = "http://www.legislation.gov.uk/namespaces/legislation"
UKM = "http://www.legislation.gov.uk/namespaces/metadata"
XHTML = "http://www.w3.org/1999/xhtml"
MATHML = "http://www.w3.org/1998/Math/MathML"
NS = {"leg": LEG, "ukm": UKM, "xhtml": XHTML, "m": MATHML}

SKIP = {
    "Commentaries", "Commentary", "CommentaryRef", "FootnoteRef", "Footnotes",
    "Footnote", "Resources", "Metadata", "Contents", "ExplanatoryNotes",
    "EarlierOrders", "SignedSection", "PrimaryPrelims", "SecondaryPrelims",
    "Versions", "MarginNote", "MarginNotes",
}
PLEVELS = {f"P{i}": i for i in range(1, 8)}
PPARAS = {f"P{i}para" for i in range(1, 8)}
# Text marked <Repeal RetainText="true"> is repealed wording that legislation.gov.uk
# still displays (usually because a saving keeps it alive for some cases). It is
# dropped from the rendered text and logged here so callers can report it.
DROPPED_RETAINED_REPEALS: list[str] = []
KEEP_RETAINED_REPEALS = False  # set True to count/display them (space-separated)
INLINE_CHAR = {"NonBreakingSpace": " ", "EmSpace": " ", "EnSpace": " ", "DotPadding": " . . . ", "EmDash": "—", "EnDash": "–"}


def local(el) -> str:
    t = el.tag
    if not isinstance(t, str):
        return ""
    return t.split("}", 1)[1] if "}" in t else t


# runs of three or more dots (". . . ." padding, "... ." omissions), with the space before them
DOTS = re.compile(r" ?\.(?: ?\.){2,}")


def norm(s: str) -> str:
    s = s.replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # protect dot runs (they mark omitted text) before the punctuation fix below
    # would squeeze their spaces out; they are kept exactly as published
    pads = DOTS.findall(s)
    s = DOTS.sub("\x00", s)
    # CLML puts whitespace inside inline wrappers; legislation.gov.uk renders no
    # space before closing punctuation or after an opening bracket, and no space
    # inside the curly quotes around a defined term.
    s = re.sub(r" ([,;:.)\]])", r"\1", s)
    s = re.sub(r"([(\[]) ", r"\1", s)
    s = s.replace("“ ", "“").replace(" ”", "”")
    for pad in pads:
        s = s.replace("\x00", pad, 1)
    return s.strip()


def math_text(el) -> str:
    name = local(el)
    kids = [k for k in el if isinstance(k.tag, str)]
    if name == "annotation":
        return ""
    if name in ("mi", "mo", "mn", "mtext"):
        return (el.text or "").strip()
    if name == "mfrac" and len(kids) == 2:
        a, b = (math_text(k) for k in kids)
        a = f"({a})" if " " in a else a
        b = f"({b})" if " " in b else b
        return f"{a} / {b}"
    if name == "msub" and len(kids) == 2:
        return f"{math_text(kids[0])}_{math_text(kids[1])}"
    if name == "msup" and len(kids) == 2:
        return f"{math_text(kids[0])}^{math_text(kids[1])}"
    if name == "semantics" and kids:
        return math_text(kids[0])
    return " ".join(t for t in (math_text(k) for k in kids) if t)


def inline_text(el) -> str:
    """Text of an inline container (Text, Title, Pnumber, td ...)."""
    out: list[str] = []

    def walk(e):
        name = local(e)
        if name in SKIP:
            if e.tail:
                out.append(e.tail)
            return
        if name == "Character":
            out.append(INLINE_CHAR.get(e.get("Name", ""), ""))
            if e.tail:
                out.append(e.tail)
            return
        if name == "Repeal" and e.get("RetainText") == "true":
            txt = norm("".join(e.itertext()))
            DROPPED_RETAINED_REPEALS.append(txt)
            if KEEP_RETAINED_REPEALS:
                out.append(f" {txt} ")
            if e.tail:
                out.append(e.tail)
            return
        if name == "math":
            out.append(math_text(e))
            if e.tail:
                out.append(e.tail)
            return
        if e.text:
            out.append(e.text)
        for k in e:
            if isinstance(k.tag, str):
                walk(k)
            elif k.tail:
                out.append(k.tail)
        if e.tail and e is not el:
            out.append(e.tail)

    walk(el)
    return norm("".join(out))


@dataclass
class Line:
    text: str
    kind: str  # heading | para | table_row | formula
    provision: str | None = None  # CLML id of the innermost numbered unit
    repealed: bool = False


@dataclass
class Renderer:
    is_act: bool
    exclude_repealed: bool = False
    lines: list[Line] = field(default_factory=list)

    def emit(self, text, kind, prov, repealed, prefix):
        text = norm(text)
        if prefix:
            label = prefix[0]
            for p in prefix[1:]:
                label = f"{label}—{p}" if label.endswith(".") else f"{label} {p}"
            text = f"{label} {text}".strip() if text else label
            prefix.clear()
        if not text:
            return
        self.lines.append(Line(text, kind, prov, repealed))

    def render(self, el, prefix=None, prov=None, repealed=False):
        prefix = prefix if prefix is not None else []
        name = local(el)
        if not name or name in SKIP:
            return
        if el.get("Status") == "Repealed":
            repealed = True
            if self.exclude_repealed:
                return
        if name in ("Part", "Chapter", "Schedule", "Group"):
            num = el.find("leg:Number", NS)
            title = el.find("leg:Title", NS)
            if title is None:
                tb = el.find("leg:TitleBlock", NS)
                title = tb.find("leg:Title", NS) if tb is not None else None
            head = " ".join(x for x in (inline_text(num) if num is not None else "", inline_text(title) if title is not None else "") if x)
            self.emit(head, "heading", el.get("id"), repealed, [])
            for k in el:
                if local(k) not in ("Number", "Title", "TitleBlock", "Reference"):
                    self.render(k, [], el.get("id"), repealed)
            return
        if name in ("Pblock", "PsubBlock"):
            t = el.find("leg:Title", NS)
            if t is not None:
                self.emit(inline_text(t), "heading", prov, repealed, [])
            for k in el:
                if local(k) not in ("Title", "Number"):
                    self.render(k, [], prov, repealed)
            return
        if name == "P1group":
            t = el.find("leg:Title", NS)
            title = inline_text(t) if t is not None else ""
            if self.is_act:
                # Acts: "35 Personal allowance" heading; number moved off the P1.
                p1 = el.find("leg:P1", NS)
                pn = p1.find("leg:Pnumber", NS) if p1 is not None else None
                num = inline_text(pn) if pn is not None else ""
                if num and pn.get("PuncAfter"):  # e.g. "43A." where the published number carries a full stop
                    num += pn.get("PuncAfter")
                self.emit(f"{num} {title}".strip(), "heading", p1.get("id") if p1 is not None else prov, repealed, [])
            else:
                self.emit(title, "heading", prov, repealed, [])
            for k in el:
                if local(k) != "Title":
                    self.render(k, [], prov, repealed)
            return
        if name in PLEVELS:
            lvl = PLEVELS[name]
            pn = el.find("leg:Pnumber", NS)
            num = inline_text(pn) if pn is not None else ""
            pid = el.get("id") or prov
            if lvl == 1:
                if self.is_act and local(el.getparent()) == "P1group":
                    label = None  # number already in heading
                else:
                    label = f"{num}." if num else None
            else:
                label = f"({num})" if num else None
            new_prefix = list(prefix) + ([label] if label else [])
            for k in el:
                if local(k) != "Pnumber":
                    self.render(k, new_prefix, pid, repealed)
                    new_prefix = []
            if new_prefix:  # numbered unit with no text
                self.emit("", "para", pid, repealed, new_prefix)
            return
        if name in PPARAS or name in ("Para", "BlockText", "ListItem", "OrderedList", "UnorderedList",
                                     "Where", "Body", "Schedules", "ScheduleBody", "Appendix",
                                     "BlockAmendment", "Figure", "Tabular", "Primary", "Secondary",
                                     "Legislation", "Division", "P", "Group"):
            if name == "Tabular":
                self.render_table(el, prov, repealed, prefix)
                return
            pending = prefix
            for k in el:
                self.render(k, pending, prov, repealed)
                pending = []
            return
        if name == "Text":
            self.emit(inline_text(el), "para", prov, repealed, prefix)
            return
        if name == "Formula":
            m = el.find(".//m:math", NS)
            self.emit(math_text(m) if m is not None else inline_text(el), "formula", prov, repealed, prefix)
            for k in el:
                if local(k) in ("Where",):
                    self.render(k, [], prov, repealed)
            return
        if name in ("Title", "Number", "Pnumber", "Reference", "Image", "TitleBlock"):
            return
        # unknown container: recurse
        for k in el:
            self.render(k, prefix, prov, repealed)
            prefix = []

    def render_table(self, el, prov, repealed, prefix):
        for tr in el.iter(f"{{{XHTML}}}tr", "tr"):
            cells = [inline_text(c) for c in tr if local(c) in ("td", "th")]
            cells = [c for c in cells if c]
            if cells:
                self.emit(" | ".join(cells), "table_row", prov, repealed, prefix)
                prefix = []


def load(path):
    parser = etree.XMLParser(huge_tree=True, remove_comments=True)
    return etree.parse(path, parser).getroot()


def doc_is_act(root) -> bool:
    t = root.find(".//ukm:DocumentMainType", NS)
    return t is not None and "Act" in t.get("Value", "") and "Instrument" not in t.get("Value", "")


def render_scope(root, exclude_repealed=False) -> list[Line]:
    r = Renderer(is_act=doc_is_act(root), exclude_repealed=exclude_repealed)
    for tag in ("Body", "Schedules"):
        for el in root.iter(f"{{{LEG}}}{tag}"):
            r.render(el)
    return r.lines


def commentaries(root) -> dict[str, str]:
    out = {}
    for c in root.iter(f"{{{LEG}}}Commentary"):
        out[c.get("id")] = norm("".join(c.itertext()))
    return out


def unapplied_effects(root) -> list[dict]:
    out = []
    for e in root.iter(f"{{{UKM}}}UnappliedEffect"):
        out.append({k: e.get(k) for k in ("Type", "AffectedProvisions", "AffectingURI", "AffectingProvisions", "Notes", "RequiresApplied")}
                   | {"AffectingTitle": norm("".join(x.itertext())) if (x := e.find("ukm:AffectingTitle", NS)) is not None else None})
    return out


def change_refs_for(root, needle: str) -> list[dict]:
    """Every Substitution/Addition wrapper whose own text equals the needle, with its commentary."""
    comm = commentaries(root)
    hits = []
    for tag in ("Substitution", "Addition", "InlineAmendment"):
        for el in root.iter(f"{{{LEG}}}{tag}"):
            if norm("".join(el.itertext())) == needle:
                # innermost numbered ancestor
                anc = el
                pid = None
                while anc is not None:
                    if local(anc) in PLEVELS and anc.get("id"):
                        pid = anc.get("id")
                        break
                    anc = anc.getparent()
                hits.append({"wrapper": tag, "provision_id": pid, "commentary_ref": el.get("CommentaryRef"),
                             "commentary": comm.get(el.get("CommentaryRef"))})
    # de-duplicate nested identical wrappers, keep innermost (last) first
    seen, out = set(), []
    for h in hits:
        k = (h["provision_id"], h["commentary_ref"])
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out


def word_count(lines: list[Line], drop_repealed=True) -> int:
    n = 0
    for ln in lines:
        if drop_repealed and ln.repealed:
            continue
        toks = [t for t in ln.text.split() if not re.fullmatch(r"[.\s]+", t)]
        n += len(toks)
    return n
