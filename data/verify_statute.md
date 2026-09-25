# statute.json verification

- Verified: 2026-09-25 02:56 UTC (2026-09-24 local), fresh fetches via `curl` into a scratch dir. `statute.json` was not edited.
- I wrote new extractors for this check. I did not reuse `data/scripts/build_statute.py`.
- Verdict: **PASS.** All three checks hold. The notes at the end are non-blocking.

## Fresh fetches

| Source | URL | HTTP | Bytes | sha256 | Same as the page `build_statute.py` fetched (by sha256 in `statute.json`)? |
|---|---|---|---|---|---|
| OLRC | https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section24&num=0&edition=prelim | 200 | 259,831 | 82debe90…46f4 | Yes, once `jsessionid` and `javax.faces.ViewState` are masked (the only differing bytes) |
| LII | https://www.law.cornell.edu/uscode/text/26/24 | 200 | 143,959 | 9421356e…f5d2 | Byte-identical |
| Avalon | https://avalon.law.yale.edu/18th_century/fed62.asp | 200 | 19,768 | 0cc963a5…7685 | Byte-identical |

The fresh OLRC page still has the comment `currentthrough:20260918_119-111`. That matches `h2_source_currentthrough`.

## (1) h2_text against current 26 U.S.C. § 24(h)(2)

`h2_text` = `Subsection (a) shall be applied by substituting "$2,200" for "$1,000".`

- **OLRC: exact match.** I took the `<p>` after the `(2) Credit amount` `<h4>` inside `(h) Special rules for taxable years beginning after 2017`. Its text equals `h2_text` character for character. The raw HTML has the same ASCII `"` (0x22) characters, with no entities.
- **LII: same wording, different quote glyphs.** LII renders `Subsection (a) shall be applied by substituting “$2,200” for “$1,000”.` with U+201C and U+201D quotes.
  - This equals `h2_crosscheck_text` exactly.
  - It equals `h2_text` once curly quotes are mapped to ASCII. Nothing else differs.
  - The file already says this (`h2_crosscheck_exact_bytes_match: false`).
  - Because the two sites use different glyphs, no single string can match both byte for byte.
- **Headings match on both sites:** `(h) Special rules for taxable years beginning after 2017` and `(2) Credit amount`.
- **$2,200 is current law.** OLRC's amendment notes say: "Subsec. (h)(2). Pub. L. 119–21, §70104(a)(2), substituted "$2,200" for "$2,000"."
  - The source credit ends at Pub. L. 119–21, so no later law in this release point amends § 24.
- **Offsets are correct:**
  - `wall_text[6535:6605] == h2_text`, and it occurs only once.
  - `wall_h2_heading_offset` 6517 starts at `(2) Credit amount`.
  - `wall_h_subsection_offset` 6307 starts at the `(h)` heading.
  - Each of the 11 `wall_subsection_offsets` begins a line with its heading.
  - `wall_chars` is 16,249 and `wall_words` is 2,686. Both are correct.

## (2) wall_text: contiguous statutory text, no editorial insertions

- **OLRC: exact match.** I read the block between `<!-- field-start:statute -->` and `<!-- field-end:statute -->`.
  - It holds 145 `<h4>`/`<p>` units, in document order.
  - Apart from anchors, the only other markup is 2 `<br class="Q04">` tags.
  - After stripping tags and unescaping entities, the joined lines equal `wall_text` exactly: 145 lines, same characters.
  - So `wall_text` is all of § 24(a)–(k), in order and with nothing skipped. The source credit, notes and amendment history sit outside that block and are not in `wall_text`.
- **LII: identical word stream.** I extracted `div.section` up to `div.sourceCredit` and mapped glyphs (“ ” → `"`, ’ → `'`, — → `-`).
  - The resulting word stream equals `wall_text`'s: 2,686 words each, with zero differences.
  - Two lines break differently, (d)(1)(B) and (d)(1)(B)(ii). That comes from how my parser handles LII chapeau spans, not from the text.
- **No editorial insertions:**
  - `wall_text` has no `[`, `]`, "sic", "So in original" or footnote text.
  - Neither source has footnote or `<sup>` markup inside the statute block.
  - `wall_text` is pure ASCII.

## (3) federalist_quote against Avalon, Federalist No. 62

- **Exact match.** The quote appears once, character for character, in the raw Avalon HTML with no normalization.
  - It is a whole sentence. Before it: "…It poisons the blessing of liberty itself. " After it: " Law is defined to be a rule of action…"
  - The page's spellings "to-day" and "to-morrow" are kept.
  - The quote is pure ASCII.
- **Page metadata matches:**
  - `federalist_page_heading`: `<div class="document-title">The Federalist Papers : No. 62</div>`
  - `federalist_page_attribution`: `<H4>HAMILTON OR MADISON</H4>`
  - `federalist_page_venue`: "The Senate / For the Independent Journal."

## Non-blocking notes

1. **Quote glyphs in h2.**
   - `h2_text` matches OLRC's HTML exactly, with straight quotes.
   - LII has the same text with curly quotes.
   - The on-screen quote style can follow either source. Whichever one it follows is the source to cite for that glyph set.
2. **Dashes and apostrophes in wall_text.** It keeps OLRC's HTML characters.
   - 16 line-final ASCII `-` correspond to LII's em dashes (—).
   - 6 ASCII `'` correspond to LII's ’.
   - This is disclosed in `meta.olrc_note`.
3. **Stale cross-references.** (k)(2)(A)(i) and (k)(3)(C)(ii)(I) cite "subsection (i)(1)" for Puerto Rico and American Samoa rules. The current (i) is "Inflation adjustments."
   - Both OLRC and LII carry this text, so it is genuine statute text and not an extraction error.
   - Don't quote those lines on screen as though they make sense in the current code.
4. **Attribution.** Avalon credits No. 62 to "HAMILTON OR MADISON." A caption that names Madison alone would go beyond what this source says.
