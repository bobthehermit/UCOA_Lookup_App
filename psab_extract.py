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
table per dimension so it can feed the PSABDescription column.

PSAB changes rarely (April 2026, before that ~5 years), so this is a run-occasionally tool.

INPUT
-----
A PDF of PSAB Supplement 3, or a text extraction of it. Passing the PDF directly is easiest
(requires pdfplumber):
    python psab_extract.py Supplement-3-April-2026.pdf --out ./psab
A .txt works too (e.g. a Drive text export or a saved pdfplumber dump).

USAGE
-----
    python psab_extract.py Supplement-3-April-2026.pdf --out ./psab
    python psab_extract.py psab.txt --out ./psab --coa-dir ./parsed   # + coverage vs COA codes

After it runs, read the "REVIEW" lines it prints: those are codes whose heading line had no
clean name/description break, so the parser fell back to keeping all of the text in the
description. Spot-check them against the PDF.

2026-10-30: rewrote _split_name_desc. The old version treated any heading line without
". " as a name-only heading, which silently dropped text into the Name column whenever PSAB
ran the description straight on without a period (58219, 58220, 58221, 43211, 55820, 56109,
55912, and abbreviations like "Ed." / "Assoc." split names in the wrong place). The rule now
is: never let description text disappear — when in doubt, keep it in the description.
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
# The name must start with a capital letter. This rejects line-wrapped cross-references
# like "...established for the\n41100 series." or "Use\n53330 for educational consultants".
ANCHOR = re.compile(r'(?m)^[ \t]*(\d{4,5})\*?[ \t]+([A-Z].*)$')

# Codes in each chapter have a fixed width, so a 4-digit number in the Object chapter
# ("1978 Compilation", "Function 2900 (Other Support Services)") can't be a heading.
CODE_LEN = {"Fund": 5, "Function": 4, "Object": 5, "Program": 4, "Job Class": 4}

# Words that end in a period but are NOT the end of a heading name ("Ed. Technology",
# "Public School Cap. Outlay", "Assoc. Supt.-Fin./Bus. Mgr."). Compared lowercase,
# without the trailing period.
ABBREVIATIONS = {"ed", "cap", "assoc", "supt", "bus", "mgr", "no", "dept", "e.g", "i.e",
                 "etc", "st", "fin", "vs", "u.s", "inc", "approx"}

# Parentheticals that are usage rules, not part of the name: "(Used only in Function 2900)",
# "(only used in Fund 41000)", "(Only used with function 5000.)"
USAGE_PAREN = re.compile(r'\s*(\((?:used|only)\b.*)$', re.IGNORECASE)


def _clean(txt: str) -> str:
    txt = re.sub(r'\s+', ' ', txt).strip()
    txt = re.sub(r'\s+([.,;:])', r'\1', txt)     # tidy spaced punctuation
    return txt


def _pdf_to_text(path: Path) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n\n".join(p.extract_text() or "" for p in pdf.pages)


def _load(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        t = _pdf_to_text(path)
    else:
        t = path.read_text(encoding="utf-8", errors="ignore")
    t = re.sub(r'\\+n', '\n', t)                              # escaped \n markers -> real newlines
    t = re.sub(r'\\?u003c', '<', t)                           # JSON-escaped < and > (Drive exports)
    t = re.sub(r'\\?u003e', '>', t)
    t = t.replace('\\', '')                                   # then drop markdown escapes (\* \. \#)
    # drop page footers mid-paragraph (any edition: "Updated April 2026 Page 12 of 66")
    t = re.sub(r'Updated \w+ \d{4} Page \d+ of \d+', '\n', t)
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


def _sentence_end(line: str) -> int:
    """Index of the first period that ends the heading name, or -1.
    A period counts if it's followed by whitespace or end-of-line AND the word before it
    isn't a known abbreviation."""
    for m in re.finditer(r'\.(?=\s|$)', line):
        before = re.search(r'([A-Za-z.]+)$', line[:m.start()])
        word = before.group(1).lower() if before else ""
        if word in ABBREVIATIONS:
            continue
        return m.start()
    return -1


def _peel_name(name: str) -> tuple[str, str]:
    """Split description-like text off the end of a candidate name.
    Returns (name, tail) — tail goes to the front of the description."""
    m = USAGE_PAREN.search(name)                 # "Loss on Investments (Used only in ...)"
    if m:
        return name[:m.start()].rstrip(' :–-'), m.group(1)
    m = re.search(r':\s+', name)                 # "Miscellaneous Expense: Amounts paid ..."
    if m:
        return name[:m.start()], name[m.end():]
    if len(name) > 60:                           # "Other Transportation-Related Services – To be used ..."
        m = re.search(r'\s+[–-]\s+', name)       # (short names keep their dash: "Special Capital Outlay – Local")
        if m:
            return name[:m.start()], name[m.end():]
    return name, ""


def _split_name_desc(first_line: str, following: str) -> tuple[str, str, bool]:
    """PSAB heading styles seen in the April 2026 edition:
       inline   -> 'Bank Accounts. All funds on deposit ...'     (name + desc share a line)
       caps     -> 'INSTRUCTION' \\n 'Instruction includes ...'   (name alone, desc follows)
       run-on   -> 'Loss on Investments (Used only in Function 2900) May be used in Funds, 11000,'
                   \\n '31600, 31700 ...'                         (no period between name and desc)
    Returns (name, description, needs_review). needs_review flags the fallback path."""
    line = first_line.strip()
    following = following.strip()
    # A name that wraps mid-parenthesis ("... (OBMS shortcut" / "Assoc. Supt.-Fin./Bus. Mgr.). ...")
    # — pull following lines up until the parentheses balance.
    while line.count("(") > line.count(")") and following:
        nxt, _, following = following.partition("\n")
        line = f"{line} {nxt.strip()}"
        following = following.strip()

    cut = _sentence_end(line)
    if cut >= 0:                                  # inline style
        name, rest = line[:cut], line[cut + 1:]
    else:
        name, rest = line, ""

    name, tail = _peel_name(name)
    desc = " ".join(x for x in (tail, rest, following) if x.strip())

    if cut < 0 and not tail:
        # No period and nothing peeled. Either a true name-only heading, or a run-on line
        # whose description continues on the next line. The tell for a run-on: the line ends
        # with a comma (58220), or the next line starts lowercase (43211).
        run_on = line.endswith(",") or bool(re.match(r'[a-z]', following))
        if run_on:
            # Can't find where the name ends — keep EVERYTHING in the description.
            return _clean(line), _clean(line + " " + following), True

    review = cut < 0 and bool(tail)               # peeled without a period: worth a glance
    return _clean(name.rstrip('.')), _clean(desc), review


def extract(path: str | Path) -> tuple[dict[str, pd.DataFrame], list[str]]:
    t = _load(path)
    bounds = _chapter_bounds(t)
    out: dict[str, pd.DataFrame] = {}
    review: list[str] = []

    for dim, (s, e) in bounds.items():
        chapter = t[s:e]
        anchors = [m for m in ANCHOR.finditer(chapter) if len(m.group(1)) == CODE_LEN[dim]]
        rows = []
        for i, m in enumerate(anchors):
            code = m.group(1)
            first_line = m.group(2)
            nxt = anchors[i + 1].start() if i + 1 < len(anchors) else len(chapter)
            following = chapter[m.end():nxt]
            name, desc, flag = _split_name_desc(first_line, following)
            rows.append((code, name, desc, len(desc)))
            if flag:
                review.append(f"{dim:9s} {code}  name='{name[:50]}'  desc starts '{desc[:60]}'")

        df = pd.DataFrame(rows, columns=["Code", "Name", "PSABDescription", "_len"])
        # Dedup echoes (TOC / NCES summary lists / repeats): keep the richest definition.
        df = (df.sort_values("_len", ascending=False)
                .drop_duplicates("Code", keep="first")
                .drop(columns="_len")
                .sort_values("Code", key=lambda s: s.str.zfill(6))
                .reset_index(drop=True))
        out[dim] = df
    return out, sorted(set(review))


# ── Fund parent-category descriptions ────────────────────────────────
# PSAB describes the 9 fund TYPES (10000, 20000, …) and names the sub-fund groups
# (24000, 27000, …). Granular grant funds (24101, 27107 …) have no PSAB description of
# their own, so we attach their parent category as context.
def fund_parent_map(psab_fund: pd.DataFrame, coa_fund: pd.DataFrame) -> pd.DataFrame:
    """For every COA fund code, walk COA's ParentFundCode chain up to the nearest ancestor
    that PSAB actually describes, and attach that description as parent-category context."""
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
        root = code[0] + "0000"
        return root if psab_desc.get(root, "").strip() else ""

    recs = []
    for code in coa_fund["Code"]:
        anc = nearest_described(code)
        recs.append((code, name_of.get(code, ""), anc,
                     psab_name.get(anc, ""), psab_desc.get(anc, "")))
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
    ap.add_argument("psab_source", help="PSAB Supplement 3 as .pdf (needs pdfplumber) or .txt")
    ap.add_argument("--out", default="./psab_out")
    ap.add_argument("--coa-dir", default=None, help="dir of parsed_<Dim>.csv from coa_reconcile --parse-only")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    psab, review = extract(args.psab_source)

    for dim, df in psab.items():
        df.to_csv(out / f"psab_{dim.replace(' ','_').lower()}.csv", index=False, encoding="utf-8-sig")
        described = (df["PSABDescription"].str.len() > 0).sum()
        print(f"{dim:10s}: {len(df):4d} codes parsed, {described:4d} with descriptions")

    if review:
        print(f"\nREVIEW — {len(review)} heading(s) had no clean name/description break; "
              "all text kept in the description. Spot-check against the PDF:")
        for r in review:
            print("  " + r)

    if args.coa_dir:
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
