# UCOA Lookup App

Reference explorer for the New Mexico Uniform Chart of Accounts (UCOA), School Budget Bureau.

## Data flow

    COA Configuration Report (OBMS, weekly) ─┐
                                             ├─►  build_ucoa.py  ─►  data/ucoa_<dim>.csv  ─►  ucoa_reference.py (app)
    PSAB Supplement 3 PDF (rare)  ─► psab_extract.py ─► psab/*.csv ─┘

- **COA report** = source of truth for which codes exist and their system flags.
- **PSAB** = source of truth for descriptions (rebuilt only when PSAB updates, ~every few years).
- **data/ucoa_*.csv** = generated source of truth the app reads. Never hand-edit. Commit after each build.

## First-time setup (new or restored machine)

Run from the project folder in the VS Code terminal.

    # 1. Sync with GitHub
    git status                       # should be clean
    git pull                         # bring in anything newer from GitHub

    # 2. Rebuild the virtual environment (venvs don't survive a restore/copy)
    rm -rf .venv
    python3 -m venv .venv
    source .venv/bin/activate        # prompt should now start with (.venv)

    # 3. Install libraries
    pip install -r requirements.txt

    # 4. Sanity check
    python check_setup.py

If VS Code asks, pick the `.venv` interpreter (Cmd+Shift+P → "Python: Select Interpreter").

## Weekly routine

1. `source .venv/bin/activate` (skip if the prompt already shows `(.venv)`)
2. `git pull`
3. Pull a fresh COA Configuration Report from OBMS. Save it over `COA Configuration Report.csv` in this folder (keep the OBMS name, spaces and all).
4. `python build_ucoa.py "COA Configuration Report.csv"` — quotes required because of the spaces.
5. Review `data/_build_audit.md` (or `git diff --stat data/`) to see what changed in OBMS.
6. `git add data "COA Configuration Report.csv" && git commit -m "UCOA refresh YYYY-MM-DD"`
7. `git push`
8. App picks it up on next load (or hit **Refresh data**).

## When PSAB updates (rare)

1. Export the PSAB Supplement 3 PDF to text → `psab.txt`.
2. `python psab_extract.py psab.txt --out ./psab --coa-dir <parsed COA dir>`
3. Commit `psab/`, then run the weekly build so descriptions flow into `data/`.

## Run the app

    streamlit run ucoa_reference.py