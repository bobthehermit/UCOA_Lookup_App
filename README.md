# UCOA Lookup App

Reference explorer for the New Mexico Uniform Chart of Accounts (UCOA), School Budget Bureau.

## Data flow

    COA Configuration Report (OBMS, weekly) ─┐
                                             ├─►  build_ucoa.py  ─►  data/ucoa_<dim>.csv  ─►  ucoa_reference.py (app)
    PSAB Supplement 3 PDF (rare)  ─► psab_extract.py ─► psab/*.csv ─┘

- **COA report** = source of truth for which codes exist and their system flags.
- **PSAB** = source of truth for descriptions (rebuilt only when PSAB updates, ~every few years).
- **data/ucoa_*.csv** = generated source of truth the app reads. Never hand-edit. Commit after each build.

## Weekly routine

1. Pull a fresh COA Configuration Report from OBMS.
2. `python build_ucoa.py COA_Configuration_Report.csv`
3. Review `data/_build_audit.md` (or `git diff data/`) to see what changed in OBMS.
4. `git add data && git commit -m "UCOA refresh <date>"` — version control is the audit log.
5. App picks it up on next load (or hit **Refresh data**).

## When PSAB updates (rare)

1. Export the PSAB Supplement 3 PDF to text → `psab.txt`.
2. `python psab_extract.py psab.txt --out ./psab --coa-dir <parsed COA dir>`
3. Commit `psab/`, then run the weekly build so descriptions flow into `data/`.

## Run the app

    streamlit run ucoa_reference.py
