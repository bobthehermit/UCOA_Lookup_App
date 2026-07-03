#!/usr/bin/env python3
"""
psab_extract.py — extract per-code descriptions from PSAB Supplement 3 (the UCOA manual PDF)
NM PED School Budget Bureau

WHY
---
PSAB Supplement 3 is the authoritative source for chart-element descriptions. It's a
narrative manual: one chapter per dimension (Fund, Functions, Objects, Programs, Job
Classifications), and inside each chapter every code appears as a heading followed by a
description paragraph. This turns that prose into a clean `code -> {name, description}`
table per dimension so it can feed the Google Sheet's PSABDescription column.

PSAB changes rarely (April 2026, before that ~5 years), so this is a run-occasionally tool.
Pair it with coa_reconcile.py: COA owns structure + fallback text, PSAB owns descriptions.

INPUT
-----
A text extraction of the PSAB Supplement 3 PDF. Get it however you like; e.g. on your Mac:
    python -c "import pdfplumber,sys; print('\n\n'.join(p.extract_text() or '' for p in pdfplumber.open(sys.argv[1]).pages))" Supplement-3-April-2026.pdf > psab.txt
(This script was validated against the Drive text export of the April 2026 edition.)

USAGE
-----
    python psab_extract.py psab.txt --out ./psab_out
    python psab_extract.py psab.txt --out ./psab_out --coa-dir ./parsed   # + coverage vs COA codes
"""

from __future__ import annotations
import argparse, re
from pathlib import Path
import pandas as pd

# Chapter headers as they appear in the manual body (we search AFTER the table of contents).
CHAPTERS = [
    ("Fund",      "IV. FUND TYPE",           "V. FUNCTIONS"),
    ("Function",  "V. FUNCTIONS",            "VI. OBJECTS"),
    ("Object",    "VI. OBJECTS",             "VII. PROGRAMS"),
    ("Program",   "VII. PROGRAMS",           "VIII. LOCATIONS"),
    ("Job Class", "IX. JOB CLASSIFICATIONS", None),  # runs to end of document
]

# A code heading: 4-5 digits at the start of a line, optional NCES asterisk, then the name/text.
ANCHOR = re.compile(r'(?m)^[ \t]*(\d{4,5})\*?[ \t]+([A-Za-z(].*)$')

def _clean(txt: str) -> str:
    txt = re.sub(r'\s+', ' ', txt).strip()
    txt = re.sub(r'\s+([.,;:])', r'\1', txt)     # tidy spaced punctuation
    return txt

def _load(path: str | Path) -> str:
    t = Path(path).read_text(encoding="utf-8", errors="ignore")
    t = re.sub(r'\\+n', '\n', t)                              # escaped \n markers -> real newlines
    t = t.replace('\\', '')                                   # then drop markdown escapes (\* \. \#)
    t = re.sub(r'Updated April 2026 Page \d+ of 66', '\n', t) # drop page footers mid-paragraph
    # Some headings run inline after the previous sentence (esp. Programs). A 4-5 digit code
    # that follows a period and precedes a Capitalized word (not a '(' cross-reference) is a
    # heading — force a line break before it so the anchor catches it.
    t = re.sub(r'(?<=\.)[ \t]+(\d{4,5}\*?)[ \t]+([A-Z])', r'\n\1 \2', t)
    return t

def _chapter_bounds(t: str) -> dict[str, tuple[int, int]]:
    body = t.find('UCOA Updates')                            # everything before this is TOC
    body = body if body > 0 else 0
    bounds = {}
    for dim, start_h, end_h in CHAPTERS:
        s = t.find(start_h, body)
        e = t.find(end_h, s) if end_h else len(t)
        if s < 0:
            raise ValueError(f"chapter header not found: {start_h}")
        bounds[dim] = (s, e if e > 0 else len(t))
    return bounds

def _split_name_desc(first_line: str, following: str) -> tuple[str, str]:
    """Two PSAB heading styles:
       inline  -> 'Bank Accounts. All funds on deposit ...'   (name + desc share a line)
       caps    -> 'INSTRUCTION' \n\n 'Instruction includes ...' (name alone, desc follows)
    """
    if '. ' in first_line:                       # inline style
        name, _, rest = first_line.partition('. ')
        desc = (rest + ' ' + following).strip()
    else:                                         # caps / name-only style
        name = first_line.strip().rstrip('.')
        desc = following.strip()
    return _clean(name), _clean(desc)

def extract(path: str | Path) -> dict[str, pd.DataFrame]:
    t = _load(path)
    bounds = _chapter_bounds(t)
    out: dict[str, pd.DataFrame] = {}

    for dim, (s, e) in bounds.items():
        chapter = t[s:e]
        anchors = list(ANCHOR.finditer(chapter))
        rows = []
        for i, m in enumerate(anchors):
            code = m.group(1)
            first_line = m.group(2)
            nxt = anchors[i + 1].start() if i + 1 < len(anchors) else len(chapter)
            following = chapter[m.end():nxt]
            name, desc = _split_name_desc(first_line, following)
            rows.append((code, name, desc, len(desc)))

        df = pd.DataFrame(rows, columns=["Code", "Name", "PSABDescription", "_len"])
        # Dedup echoes (TOC / NCES summary lists / repeats): keep the richest definition.
        df = (df.sort_values("_len", ascending=False)
                .drop_duplicates("Code", keep="first")
                .drop(columns="_len")
                .sort_values("Code", key=lambda s: s.str.zfill(6))
                .reset_index(drop=True))
        out[dim] = df
    return out

# ── Fund parent-category descriptions ────────────────────────────────
# PSAB describes the 9 fund TYPES (10000, 20000, …) and names the sub-fund groups
# (24000, 27000, …). Granular grant funds (24101, 27107 …) have no PSAB description of
# their own, so we attach their parent category as context.
def fund_parent_map(psab_fund: pd.DataFrame, coa_fund: pd.DataFrame) -> pd.DataFrame:
    """For every COA fund code, walk COA's ParentFundCode chain up to the nearest ancestor
    that PSAB actually describes, and attach that description as parent-category context.

    This is what gives the 856 granular 24xxx/27xxx grant funds a meaningful description
    even though PSAB names only their parent category.
    """
    psab_desc = dict(zip(psab_fund["Code"], psab_fund["PSABDescription"]))
    psab_name = dict(zip(psab_fund["Code"], psab_fund["Name"]))
    parent_of = dict(zip(coa_fund["Code"], coa_fund.get("ParentFundCode", pd.Series(dtype=str))))
    name_of   = dict(zip(coa_fund["Code"], coa_fund["Name"]))

    def nearest_described(code: str) -> str:
        seen, cur = set(), code
        while cur and cur not in seen:
            seen.add(cur)
            if psab_desc.get(cur, "").strip():
                return cur
            cur = str(parent_of.get(cur, "")).strip()
        # fall back to the fund-type root (first digit) if it has a PSAB description
        root = code[0] + "0000"
        return root if psab_desc.get(root, "").strip() else ""

    recs = []
    for code in coa_fund["Code"]:
        anc = nearest_described(code)
        recs.append((
            code,
            name_of.get(code, ""),
            anc,
            psab_name.get(anc, ""),
            psab_desc.get(anc, ""),
        ))
    return pd.DataFrame(recs, columns=["Code", "Name", "ParentCategoryCode",
                                       "ParentCategoryName", "ParentCategoryDescription"])

# ── coverage vs the COA code set ─────────────────────────────────────
def coverage(psab: dict[str, pd.DataFrame], coa_dir: str | Path) -> pd.DataFrame:
    rows = []
    for dim, df in psab.items():
        coa_path = Path(coa_dir) / f"parsed_{dim.replace(' ','_')}.csv"
        if not coa_path.exists():
            rows.append((dim, len(df), None, None, None)); continue
        coa = pd.read_csv(coa_path, dtype=str, keep_default_na=False)
        coa_codes = set(coa["Code"].str.strip())
        psab_has = df[df["PSABDescription"].str.len() > 0]
        matched = coa_codes & set(psab_has["Code"])
        rows.append((dim, len(coa_codes), len(matched),
                     len(coa_codes) - len(matched),
                     round(100*len(matched)/max(1,len(coa_codes)), 1)))
    return pd.DataFrame(rows, columns=["Dimension","COA codes","PSAB-described",
                                       "Fallback to COA","Coverage %"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("psab_txt")
    ap.add_argument("--out", default="./psab_out")
    ap.add_argument("--coa-dir", default=None, help="dir of parsed_<Dim>.csv from coa_reconcile --parse-only")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    psab = extract(args.psab_txt)

    for dim, df in psab.items():
        df.to_csv(out / f"psab_{dim.replace(' ','_').lower()}.csv", index=False, encoding="utf-8-sig")
        described = (df["PSABDescription"].str.len() > 0).sum()
        print(f"{dim:10s}: {len(df):4d} codes parsed, {described:4d} with descriptions")

    if args.coa_dir:
        # Fund parent-category context (needs COA's ParentFundCode chain)
        coa_fund = pd.read_csv(Path(args.coa_dir) / "parsed_Fund.csv", dtype=str, keep_default_na=False)
        fpm = fund_parent_map(psab["Fund"], coa_fund)
        fpm.to_csv(out / "psab_fund_parent_categories.csv", index=False, encoding="utf-8-sig")

        cov = coverage(psab, args.coa_dir)
        print("\nCoverage vs COA code set:")
        print(cov.to_string(index=False))
        cov.to_csv(out / "coverage_report.csv", index=False, encoding="utf-8-sig")

    print(f"\nWrote outputs to {out.resolve()}")

if __name__ == "__main__":
    main()
