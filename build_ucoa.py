#!/usr/bin/env python3
"""
build_ucoa.py — build the UCOA source of truth that feeds the Streamlit app.
NM PED School Budget Bureau

WHAT THIS IS
------------
The weekly job. You pull a fresh COA Configuration Report from OBMS, run this once, and it
writes the five per-dimension source-of-truth CSVs the app reads. It joins in the PSAB
description layer (produced rarely by psab_extract.py) and flags deprecated codes.

    COA report (weekly)  ─┐
                          ├─►  build_ucoa.py  ─►  data/ucoa_<dim>.csv  ─►  ucoa_reference.py (app)
    psab/*.csv (rare)    ─┘

Commit data/ after each run: `git diff` then shows exactly what changed in OBMS that week —
codes added, repurposed, flags flipped. Version control becomes the audit log.

    python build_ucoa.py COA_Configuration_Report.csv
    python build_ucoa.py COA_Configuration_Report.csv --psab ./psab --data ./data

Layers:
  COA  = source of truth for which codes exist IN OBMS + their system flags (authoritative).
  PSAB = source of truth for descriptions (psab/ CSVs, updated every few years).
  The built CSV is a generated artifact — never hand-edited.

2026-11-14: the build now keeps EVERY code in the manual, not only the ones OBMS has.
  Availability = "OBMS"        the code is in the COA Configuration Report
  Availability = "Books only"  the code is in PSAB Supplement 3 but not in OBMS: the optional
                               sub-functions (2220 rolls up to 2200), the balance sheet objects
                               OBMS does not carry, and a few fund types. Districts can use
                               these in their own books; OBMS only ever sees the parent.
  It also carries the formatted description and the PSAB page, NCES and section columns
  that psab_extract.py (version 2) writes.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import pandas as pd

# ─────────────────────────────────────────────────────────────────────
# COA report structure (stacked SSRS export; columns reused per section).
# Decoded from the separator rows of the report.
# ─────────────────────────────────────────────────────────────────────
SECTION_ORDER = ["Fund", "Function", "Object", "Program", "Job Class"]
SEP_MARKERS = {"Code1", "Code2", "Code3", "Textbox95"}
FUND_JUNK = {"Textbox14"}

SECTION_COLMAP: dict[str, dict[str, str] | None] = {
    "Fund": None,
    "Function": {
        "Code": "Code", "Name": "Name", "Description": "Description", "ChartType": "ChartType",
        "FundType": "ChartAccountType", "ParentFundCode": "ParentFunctionCode",
        "IsGrant": "SummaryLine", "GrantName": "IsBudgetable", "SummaryLine": "ActualsPostable",
        "IsBudgetable": "SupportsPrograms", "ActualsPostable": "NCESReportingRequired",
        "IsReimbursable": "NotInUse",
    },
    "Object": {
        "Code": "Code", "Name": "Name", "Description": "Description", "ChartType": "ChartType",
        "FundType": "ChartAccountType", "ParentFundCode": "ParentObjectCode",
        "IsGrant": "SummaryLine", "GrantName": "IsBudgetable", "SummaryLine": "ActualsPostable",
        "IsBudgetable": "RequiresJobClass", "ActualsPostable": "AcceptsFTE",
        "IsReimbursable": "UsesDependentCharterTransfer", "RequiresApprovals": "NCESReportingRequired",
        "SupportsAssessedValuations": "AllowsNegative", "RevObjectCurrYear": "NotInUse",
    },
    "Program": {
        "Code": "Code", "Name": "Name", "Description": "Description", "ChartType": "ChartType",
        "FundType": "ParentProgramCode", "ParentFundCode": "ParentType", "ParentType": "SummaryLine",
        "IsGrant": "IsBudgetable", "GrantName": "ActualsPostable", "SummaryLine": "NotInUse",
    },
    "Job Class": {
        "Code": "Code", "Name": "Name", "Description": "Description", "ChartType": "ChartType",
        "FundType": "ParentJobClassCode", "ParentFundCode": "ParentType", "ParentType": "IsLicensed",
        "IsGrant": "JobClassCategory", "GrantName": "StaffTitlesReportTitle", "SummaryLine": "SummaryLine",
        "IsBudgetable": "IsBudgetable", "ActualsPostable": "ActualsPostable", "IsReimbursable": "SupportsFTE",
    },
}

TRUE_SET = {"yes", "true", "1", "y"}

def parse_report(path: str | Path) -> dict[str, pd.DataFrame]:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    raw.columns = [c.strip() for c in raw.columns]
    seps = [i for i, code in enumerate(raw["Code"]) if str(code).strip() in SEP_MARKERS]
    if len(seps) != len(SECTION_ORDER) - 1:
        raise ValueError(f"Expected {len(SECTION_ORDER)-1} section separators, found {len(seps)}. "
                         "Report layout may have changed — inspect the 'Code' column markers.")
    edges = [0] + [s + 1 for s in seps] + [len(raw)]
    stops = seps + [len(raw)]
    out: dict[str, pd.DataFrame] = {}
    for k, dim in enumerate(SECTION_ORDER):
        block = raw.iloc[edges[k]:stops[k]].copy()
        cmap = SECTION_COLMAP[dim]
        if cmap is None:
            df = block[[c for c in raw.columns if c not in FUND_JUNK]].copy()
        else:
            df = block[[c for c in raw.columns if c in cmap]].rename(columns=cmap)
        for c in df.columns:
            df[c] = df[c].astype(str).str.strip()
        out[dim] = df[df["Code"] != ""].reset_index(drop=True)
    return out

# ─────────────────────────────────────────────────────────────────────
# PSAB description layer (produced by psab_extract.py)
# ─────────────────────────────────────────────────────────────────────
PSAB_FILE = {d: f"psab_{d.replace(' ', '_').lower()}.csv" for d in SECTION_ORDER}

# Columns psab_extract.py writes -> the names they get in data/ucoa_<dim>.csv.
PSAB_COLS = {"Name": "PSABName", "PSABDescription": "PSABDescription", "PSABHtml": "PSABHtml",
             "Page": "PSABPage", "NCES": "PSABNCES", "Optional": "Optional",
             "ParentCode": "PSABParent", "Section": "PSABSection"}

def load_psab(psab_dir: str | Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    pdir = Path(psab_dir)
    layer: dict[str, pd.DataFrame] = {}
    for dim in SECTION_ORDER:
        p = pdir / PSAB_FILE[dim]
        if p.exists():
            df = pd.read_csv(p, dtype=str, keep_default_na=False)
            for src in PSAB_COLS:                      # older psab files lack the new columns
                if src not in df.columns:
                    df[src] = ""
            layer[dim] = df[["Code", *PSAB_COLS]].rename(columns=PSAB_COLS)
        else:
            print(f"  ! PSAB file missing for {dim}: {p} (descriptions will be blank)", file=sys.stderr)
            layer[dim] = pd.DataFrame(columns=["Code", *PSAB_COLS.values()])
    ppc = pdir / "psab_fund_parent_categories.csv"
    parents = pd.read_csv(ppc, dtype=str, keep_default_na=False) if ppc.exists() else pd.DataFrame()
    return layer, parents

# ─────────────────────────────────────────────────────────────────────
# Build the source of truth
# ─────────────────────────────────────────────────────────────────────
def _status(row) -> str:
    return "Historical" if str(row.get("NotInUse", "")).lower() in TRUE_SET else "Active"

_SMALL_WORDS = {"and", "or", "of", "the", "for", "to", "in", "on", "from", "by", "a", "an"}

def _nice_name(name: str) -> str:
    """PSAB prints some headings in capitals ("CASH ASSETS"). OBMS-style: "Cash Assets"."""
    if not name.isupper():
        return name
    words = name.lower().split()
    out = [w if (i and w in _SMALL_WORDS) else w[:1].upper() + w[1:] for i, w in enumerate(words)]
    return " ".join(out)

# The OBMS "type" column per dimension, so codes that exist only in PSAB still show up
# under the app's Type filter.
TYPE_COL = {"Fund": "FundType", "Function": "ChartAccountType", "Object": "ChartAccountType"}

def _books_only_type(dim: str, row) -> str:
    if dim == "Object":
        return "Balance Sheet" if str(row["PSABSection"]).startswith("Balance Sheet") else "Books only"
    if dim == "Function":
        return "Expenditure"
    return "Not in OBMS"

def _order_columns(df: pd.DataFrame, dim: str) -> pd.DataFrame:
    lead = ["Code", "Name", "Status", "Availability", "PSABDescription", "PSABHtml", "PSABPage",
            "PSABNCES", "PSABSection", "Optional", "PSABParent"]
    if dim == "Fund":
        lead += ["ParentCategoryName", "ParentCategoryDescription"]
    drop = {"Description", "PSABName"}                 # COA's empty Description; PSAB's own name
    rest = [c for c in df.columns if c not in lead and c not in drop]
    return df[[c for c in lead if c in df.columns] + rest]

def build(report: dict[str, pd.DataFrame], psab: dict[str, pd.DataFrame],
          parents: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for dim in SECTION_ORDER:
        # how="outer" keeps codes from BOTH sides. indicator=True adds a "_merge" column
        # saying where each row came from: "both", "left_only" (OBMS) or "right_only" (PSAB).
        df = report[dim].merge(psab[dim], on="Code", how="outer", indicator=True)
        df = df.fillna("")
        books = df["_merge"] == "right_only"
        df["Availability"] = "OBMS"
        df.loc[books, "Availability"] = "Books only"
        df.loc[books, "Name"] = df.loc[books, "PSABName"].map(_nice_name)
        if dim in TYPE_COL and TYPE_COL[dim] in df.columns:
            df.loc[books, TYPE_COL[dim]] = df[books].apply(lambda r: _books_only_type(dim, r), axis=1)
        df = df.drop(columns="_merge")
        df["Status"] = df.apply(_status, axis=1)
        if dim == "Fund" and not parents.empty:
            df = df.merge(parents[["Code", "ParentCategoryName", "ParentCategoryDescription"]],
                          on="Code", how="left")
            for c in ("ParentCategoryName", "ParentCategoryDescription"):
                df[c] = df[c].fillna("")
        df = df.sort_values("Code", key=lambda s: s.str.zfill(6), kind="stable").reset_index(drop=True)
        out[dim] = _order_columns(df, dim).fillna("")
    return out

# ─────────────────────────────────────────────────────────────────────
# Audit: diff the new build against the currently committed CSVs
# ─────────────────────────────────────────────────────────────────────
def _norm(v) -> str:
    s = str(v).strip(); low = s.lower()
    return "yes" if low in TRUE_SET else "no" if low in {"no", "false", "0", "n"} else s

def audit(new: dict[str, pd.DataFrame], data_dir: Path) -> list[str]:
    lines = ["# UCOA build audit (vs currently committed data/)", ""]
    any_prior = False
    for dim in SECTION_ORDER:
        prev_path = data_dir / f"ucoa_{dim.replace(' ', '_').lower()}.csv"
        if not prev_path.exists():
            lines.append(f"## {dim}: no prior file — first build ({len(new[dim])} codes)"); lines.append("")
            continue
        any_prior = True
        prev = pd.read_csv(prev_path, dtype=str, keep_default_na=False)
        nw = new[dim]
        pc, nc = set(prev["Code"]), set(nw["Code"])
        added, removed = sorted(nc - pc), sorted(pc - nc)
        shared_cols = [c for c in nw.columns if c in prev.columns and c != "Code"]
        pi, ni = prev.set_index("Code"), nw.set_index("Code")
        changes = []
        for code in sorted(pc & nc):
            for c in shared_cols:
                if c == "PSABHtml":
                    continue                    # formatting only; PSABDescription shows the change
                if _norm(pi.at[code, c]) != _norm(ni.at[code, c]):
                    changes.append(f"    {code:>8} {c}: '{pi.at[code, c]}' -> '{ni.at[code, c]}'")
        lines.append(f"## {dim}")
        lines.append(f"- added: {len(added)}" + (f"  ({', '.join(added[:30])})" if added else ""))
        lines.append(f"- removed: {len(removed)}" + (f"  ({', '.join(removed[:30])})" if removed else ""))
        lines.append(f"- changed fields: {len(changes)}")
        lines.extend(changes[:80])
        if len(changes) > 80:
            lines.append(f"    … {len(changes) - 80} more")
        lines.append("")
    if not any_prior:
        lines.append("First build — nothing to diff against yet. Commit data/ to start the audit trail.")
    return lines

def main():
    ap = argparse.ArgumentParser(description="Build UCOA source-of-truth CSVs from a COA report + PSAB layer.")
    ap.add_argument("report_csv", help="COA Configuration Report csv from OBMS")
    ap.add_argument("--psab", default="./psab", help="Dir of psab_*.csv (from psab_extract.py)")
    ap.add_argument("--data", default="./data", help="Output dir for ucoa_*.csv (the app feed)")
    args = ap.parse_args()

    data_dir = Path(args.data)

    print(f"Parsing COA report: {args.report_csv}")
    report = parse_report(args.report_csv)
    print("Loading PSAB layer…")
    psab, parents = load_psab(args.psab)

    built = build(report, psab, parents)

    # Audit BEFORE overwriting, so we compare against the committed version.
    audit_lines = audit(built, data_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    for dim in SECTION_ORDER:
        df = built[dim]
        described = (df["PSABDescription"].str.len() > 0).sum()
        hist = (df["Status"] == "Historical").sum()
        df.to_csv(data_dir / f"ucoa_{dim.replace(' ', '_').lower()}.csv", index=False, encoding="utf-8-sig")
        books = (df["Availability"] == "Books only").sum()
        print(f"  {dim:10s}: {len(df):4d} codes | {len(df) - books:4d} in OBMS | {books:3d} books only | "
              f"{described:4d} described | {hist:3d} historical")

    (data_dir / "_build_audit.md").write_text("\n".join(audit_lines), encoding="utf-8")
    print("\n" + "\n".join(audit_lines))
    print(f"\nWrote source of truth to {data_dir.resolve()}  (commit it to log the change)")

if __name__ == "__main__":
    main()
