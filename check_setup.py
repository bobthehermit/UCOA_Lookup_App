#!/usr/bin/env python3
"""
check_setup.py — verify the UCOA_Lookup_App folder is wired correctly before launching.
Run from the project root:  python check_setup.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).parent
DIMS = ["fund", "function", "object", "program", "job_class"]

EXPECTED = {
    "scripts (project root)": [ROOT / f for f in
        ["ucoa_reference.py", "build_ucoa.py", "psab_extract.py"]],
    "data/ (app feed — five files)": [ROOT / "data" / f"ucoa_{d}.csv" for d in DIMS],
    "psab/ (description layer — six files)": [ROOT / "psab" / f for f in
        ["psab_fund.csv", "psab_function.csv", "psab_object.csv",
         "psab_program.csv", "psab_job_class.csv", "psab_fund_parent_categories.csv"]],
}

def main():
    ok = True
    print(f"Checking {ROOT.resolve()}\n")
    for group, paths in EXPECTED.items():
        print(f"{group}")
        for p in paths:
            mark = "✓" if p.exists() else "✗ MISSING"
            if not p.exists():
                ok = False
            print(f"   {mark}  {p.relative_to(ROOT)}")
        print()

    # Verify ucoa_reference.py is the new (local-CSV) version, not the old Google-Sheets one
    app = ROOT / "ucoa_reference.py"
    if app.exists():
        src = app.read_text(encoding="utf-8", errors="ignore")
        if "SHEET_ID" in src or "SHEET_URLS" in src:
            print("✗ ucoa_reference.py is the OLD Google-Sheets version — replace it with the\n"
                  "  new one that reads ./data (look for DATA_DIR near the top).\n")
            ok = False
        elif "DATA_DIR" in src:
            print("app version\n   ✓  ucoa_reference.py reads ./data (current version)\n")
        else:
            print("? ucoa_reference.py: couldn't confirm version — check it reads ./data\n")

    # Try loading the five data files
    try:
        import pandas as pd
        print("Loading data/ …")
        for d in DIMS:
            p = ROOT / "data" / f"ucoa_{d}.csv"
            if p.exists():
                df = pd.read_csv(p, dtype=str, keep_default_na=False)
                print(f"   ✓ ucoa_{d}.csv — {len(df)} rows")
        print()
    except ImportError:
        print("! pandas not installed in this environment — run: pip install pandas streamlit pillow\n")
        ok = False
    except Exception as e:
        print(f"✗ error loading data: {e}\n")
        ok = False

    if ok:
        print("All good. Launch with:  streamlit run ucoa_reference.py")
    else:
        print("Fix the ✗ items above, then re-run this check.")
        sys.exit(1)

if __name__ == "__main__":
    main()
