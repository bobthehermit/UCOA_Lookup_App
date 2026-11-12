"""
build_chart_lines.py — Phase 1 of the Chart Line Guide (see chart_line_guide_spec.md §4)

Turns the full OBMS "Chart Line Listing Report" CSV export (~280 MB, ~1.5M rows)
into small files the Streamlit app can load instantly:

    data/chart_lines.parquet      every open chart line, codes only (a few MB)
    data/fund_line_summary.csv    one row per fund: how many lines, how wide
    data/_chart_lines_audit.md    what changed since the last build

Usage (from the project folder, venv active):

    python build_chart_lines.py "Chart Line Listing Report.csv"

The raw CSV is NOT committed (too big for git); the three outputs are.

------------------------------------------------------------------------------
How it works, briefly
------------------------------------------------------------------------------
1. READ: pandas reads only the code columns, all as strings (dtype=str) so
   "0000" stays "0000" instead of becoming 0. encoding="utf-8-sig" strips the
   invisible byte-order mark OBMS puts at the start of the file (it would
   otherwise glue itself onto the first column name).

2. SHRINK: the names (FundName, ObjectName...) repeat on every row and already
   live in data/ucoa_<dim>.csv, so we drop them. Code columns are converted to
   pandas "category" type: each distinct code is stored once and rows hold a
   small integer pointer to it. That plus Parquet's columnar compression is
   why 280 MB becomes a few MB.

3. SUMMARIZE: group by fund and count lines and distinct function/object
   pairs — the "how wide is this fund" number from our brainstorm.

4. DIFF: if a previous chart_lines.parquet exists, compare old vs. new using a
   set of line keys ("27579|2100|51300|0000|1211"). Lines only in the new set
   were added; lines only in the old set were removed. Changes you can't match
   to a logged request are worth a look.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Columns as OBMS names them in the export header.
CODE_COLS = {
    "AccountType": "account_type",
    "FundCode": "fund",
    "FunctionCode": "function",
    "ObjectCode": "object",
    "ProgramCode": "program",
    "JobClassCode": "job_class",
}
KEY_COLS = ["fund", "function", "object", "program", "job_class"]

# Width bands for the fund summary (function/object pairs per fund).
# Tune freely — this is only a label to help spot wide-open funds.
WIDTH_BANDS = [(0, 50, "narrow"), (51, 150, "moderate"), (151, 449, "broad"), (450, 10_000, "wide open")]


def read_export(csv_path: Path) -> tuple[pd.DataFrame, str]:
    """Read the OBMS export, codes only. Returns (lines, chart_of_accounts_name)."""
    header = pd.read_csv(csv_path, nrows=1, dtype=str, encoding="utf-8-sig")
    missing = [c for c in [*CODE_COLS, "ChartOfAccountsName", "FundName"] if c not in header.columns]
    if missing:
        sys.exit(f"ERROR: export is missing expected columns: {missing}\n"
                 f"Found: {list(header.columns)}\n"
                 "Was it exported as 'CSV (comma delimited)' from the Chart Line Listing Report?")
    coa_name = header.loc[0, "ChartOfAccountsName"]

    print(f"Reading {csv_path.name} ...", flush=True)
    df = pd.read_csv(
        csv_path,
        usecols=list(CODE_COLS) + ["FundName"],
        dtype=str,
        encoding="utf-8-sig",
        keep_default_na=False,   # treat blanks as "" not NaN, so codes never turn into floats
    ).rename(columns=CODE_COLS)

    # Trim stray whitespace OBMS sometimes leaves on codes.
    for c in df.columns:
        df[c] = df[c].str.strip()

    df = df[df["fund"] != ""]            # drop trailing blank lines
    before = len(df)
    df = df.drop_duplicates()
    if len(df) != before:
        print(f"  note: dropped {before - len(df):,} exact duplicate rows")
    return df, coa_name


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """One row per fund: line counts and a width label."""
    exp = df[df["account_type"] == "Expenditure"]
    g = exp.groupby("fund", observed=True)
    summary = pd.DataFrame({
        "fund_name": df.groupby("fund", observed=True)["FundName"].first(),
        "expenditure_lines": g.size(),
        "function_object_pairs": g.apply(lambda x: len(x[["function", "object"]].drop_duplicates()),
                                         include_groups=False),
        "functions": g["function"].nunique(),
        "objects": g["object"].nunique(),
        "job_classes": g["job_class"].nunique(),
    })
    summary["revenue_lines"] = df[df["account_type"] == "Revenue"].groupby("fund", observed=True).size()
    summary = summary.fillna(0)
    int_cols = [c for c in summary.columns if c != "fund_name"]
    summary[int_cols] = summary[int_cols].astype(int)

    def band(n: int) -> str:
        for lo, hi, label in WIDTH_BANDS:
            if lo <= n <= hi:
                return label
        return "wide open"

    summary["width"] = summary["function_object_pairs"].map(band)
    return summary.reset_index().sort_values("fund")


def line_keys(df: pd.DataFrame) -> set[str]:
    """Each line as one string, so two builds can be compared with set math."""
    # Vectorized string concat (column + "|" + column ...) is much faster than a
    # row-by-row join on 1.5M rows.
    s = df[KEY_COLS[0]].astype(str)
    for c in KEY_COLS[1:]:
        s = s + "|" + df[c].astype(str)
    return set(s)


def write_audit(out_dir: Path, coa_name: str, new: pd.DataFrame, old: pd.DataFrame | None, summary: pd.DataFrame) -> None:
    lines = [
        f"# Chart line build audit — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Chart of accounts: **{coa_name}**",
        f"- Lines: **{len(new):,}** ({(new.account_type == 'Expenditure').sum():,} expenditure, "
        f"{(new.account_type == 'Revenue').sum():,} revenue)",
        f"- Funds: **{new.fund.nunique()}**",
        f"- Distinct function/object pairs statewide: **{len(new[['function', 'object']].drop_duplicates()):,}**",
        "- Funds by width: " + ", ".join(f"{k} {v}" for k, v in summary["width"].value_counts().items()),
        "",
    ]

    if old is None:
        lines += ["_No previous build found — this is the baseline._", ""]
    else:
        new_k, old_k = line_keys(new), line_keys(old)
        added, removed = new_k - old_k, old_k - new_k
        lines += [f"## Changes since last build", "",
                  f"- Added: **{len(added):,}** lines",
                  f"- Removed: **{len(removed):,}** lines", ""]
        for title, keys in (("Added", added), ("Removed", removed)):
            if not keys:
                continue
            by_fund = pd.Series([k.split("|")[0] for k in keys]).value_counts().sort_index()
            lines += [f"### {title} by fund", "", "| Fund | Lines |", "|---|---:|"]
            lines += [f"| {f} | {n:,} |" for f, n in by_fund.items()]
            lines += ["", f"<details><summary>{title} lines (first 200)</summary>", "",
                      "```", "fund|function|object|program|job_class"]
            lines += sorted(keys)[:200]
            lines += ["```", "</details>", ""]

    (out_dir / "_chart_lines_audit.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("csv", type=Path, help='OBMS export, e.g. "Chart Line Listing Report.csv"')
    ap.add_argument("--out", type=Path, default=Path("data"), help="output folder (default: data)")
    args = ap.parse_args()

    if not args.csv.exists():
        sys.exit(f"ERROR: {args.csv} not found")
    args.out.mkdir(parents=True, exist_ok=True)
    parquet_path = args.out / "chart_lines.parquet"

    df, coa_name = read_export(args.csv)
    old = pd.read_parquet(parquet_path) if parquet_path.exists() else None

    summary = summarize(df)
    summary.to_csv(args.out / "fund_line_summary.csv", index=False)

    # Codes only, as categories, sorted so similar rows sit together (compresses better).
    lines = df.drop(columns="FundName").sort_values(KEY_COLS).reset_index(drop=True)
    for c in lines.columns:
        lines[c] = lines[c].astype("category")
    lines.to_parquet(parquet_path, index=False, compression="zstd")

    write_audit(args.out, coa_name, lines, old, summary)

    size_mb = parquet_path.stat().st_size / 1_048_576
    print(f"Wrote {parquet_path} ({len(lines):,} lines, {size_mb:.1f} MB)")
    print(f"Wrote {args.out / 'fund_line_summary.csv'} ({len(summary)} funds)")
    print(f"Wrote {args.out / '_chart_lines_audit.md'} — review it before committing")


if __name__ == "__main__":
    main()
