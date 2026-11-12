"""
pages/1_Lines_on_my_fund.py — "Which chart lines are open on this fund?"

Phase 1 of the Chart Line Guide (chart_line_guide_spec.md §3.2, step 1).

How this page plugs in
----------------------
Streamlit treats any .py file inside a folder named `pages/` (next to the main
script) as an extra page and adds it to the sidebar navigation automatically.
Nothing in ucoa_reference.py has to change. The number prefix (1_) sets the
order; underscores become spaces in the menu.

Each page is its own script, run top to bottom on every interaction, so this
file loads its own data and sets its own page config.

Data it reads (all built by the two build scripts — never hand-edited)
---------------------------------------------------------------------
    data/chart_lines.parquet     every open line, codes only   (build_chart_lines.py)
    data/fund_line_summary.csv   one row per fund               (build_chart_lines.py)
    data/ucoa_<dim>.csv          names + PSAB descriptions      (build_ucoa.py)
"""

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Lines on my fund · UCOA", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 3rem !important; max-width: 1180px; }
[data-testid="stExpander"] { border: 0.5px solid #ececec; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# __file__ is this file; .parent is pages/; .parent.parent is the project folder.
DATA_DIR = Path(__file__).parent.parent / "data"
DIMS = {"fund": "ucoa_fund.csv", "function": "ucoa_function.csv", "object": "ucoa_object.csv",
        "program": "ucoa_program.csv", "job_class": "ucoa_job_class.csv"}


# ─── Loading ──────────────────────────────────────────────────────────
# @st.cache_data keeps the result in memory, so the files are read once and
# every later click reuses them. ttl=3600 means "re-read after an hour".

@st.cache_data(ttl=3600, show_spinner="Loading chart lines…")
def load_lines() -> tuple[pd.DataFrame, str]:
    path = DATA_DIR / "chart_lines.parquet"
    df = pd.read_parquet(path)
    built = datetime.fromtimestamp(path.stat().st_mtime).strftime("%b %d %Y")
    return df, built


@st.cache_data(ttl=3600, show_spinner=False)
def load_lookups() -> dict[str, pd.DataFrame]:
    """One small table per dimension, indexed by code, for names and PSAB text."""
    out = {}
    for dim, fname in DIMS.items():
        d = pd.read_csv(DATA_DIR / fname, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        out[dim] = d.drop_duplicates("Code").set_index("Code")
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def load_summary() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "fund_line_summary.csv", dtype={"fund": str}).set_index("fund")


try:
    lines, built = load_lines()
    look = load_lookups()
    summary = load_summary()
except FileNotFoundError as e:
    st.error(f"Chart line data not found ({e.filename}). Run build_chart_lines.py first.")
    st.stop()


def name_of(dim: str, code: str) -> str:
    t = look[dim]
    return t.at[code, "Name"] if code in t.index else ""


def psab_of(dim: str, code: str) -> str:
    t = look[dim]
    return t.at[code, "PSABDescription"] if code in t.index else ""


# ─── Header ───────────────────────────────────────────────────────────
st.title("Lines open on a fund")
st.caption(
    f"Chart lines currently open in OBMS, as of the {built} export. "
    "PSAB Supplement 3 is the authoritative guidance on what each code means."
)

# ─── Pick a fund ──────────────────────────────────────────────────────
fund_codes = sorted(summary.index)
fund = st.selectbox(
    "Fund",
    fund_codes,
    index=None,
    placeholder="Type a fund number or name…",
    # format_func changes only what is displayed; the value stays the code.
    format_func=lambda c: f"{c} — {summary.at[c, 'fund_name']}",
)
if fund is None:
    st.info("Choose a fund to see every function / object / program / job class line open on it.")
    st.stop()

info = summary.loc[fund]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Function / object pairs", f"{info.function_object_pairs:,}")
c2.metric("Expenditure lines", f"{info.expenditure_lines:,}")
c3.metric("Revenue lines", f"{info.revenue_lines:,}")
c4.metric("Width", info.width.title())

fund_psab = psab_of("fund", fund)
if fund_psab:
    with st.expander("PSAB description of this fund"):
        st.write(fund_psab)

# ─── This fund's lines ────────────────────────────────────────────────
# Boolean filter: (lines.fund == fund) is a True/False column; df[mask] keeps the Trues.
# .astype(str) converts the compact "category" columns back to plain text.
fl = lines[lines.fund == fund].astype(str)

# The export has one row per job class. For reading, collapse those into one
# row per function/object/program and list the job classes side by side.
grouped = (
    fl.groupby(["account_type", "function", "object", "program"], sort=True)["job_class"]
      .agg(lambda s: ", ".join(j for j in sorted(s) if j != "0000"))
      .reset_index()
      .rename(columns={"job_class": "job_classes"})
)
grouped.insert(2, "function_name", grouped.function.map(lambda c: name_of("function", c)))
grouped.insert(4, "object_name", grouped.object.map(lambda c: name_of("object", c)))

# ─── Filters ──────────────────────────────────────────────────────────
f1, f2, f3 = st.columns([1, 2, 2])
kind = f1.segmented_control("Type", ["Expenditure", "Revenue"], default="Expenditure")
funcs = sorted(grouped.function.unique())
sel_funcs = f2.multiselect("Function", funcs, format_func=lambda c: f"{c} — {name_of('function', c)}",
                           placeholder="All functions")
q = f3.text_input("Search", placeholder="Code or word, e.g. 53330 or training")

view = grouped
if kind:
    view = view[view.account_type == kind]
if sel_funcs:
    view = view[view.function.isin(sel_funcs)]
if q.strip():
    # Glue each row into one lowercase string, then keep rows containing every search word.
    # The object's PSAB description is included, so "training" finds 53330
    # (Professional Development) even though the word isn't in its name.
    hay = (view.astype(str).agg(" ".join, axis=1) + " "
           + view.object.map(lambda c: psab_of("object", c))).str.lower()
    for word in q.lower().split():
        hay_mask = hay.str.contains(word, regex=False)
        view, hay = view[hay_mask], hay[hay_mask]

view = view.reset_index(drop=True)

if view.empty:
    st.warning(
        "No open lines on this fund match. If you need one, check PSAB Supplement 3 for the "
        "right code, then request it with the COA Maintenance Form."
    )
    st.stop()

st.caption(f"{len(view):,} line group(s). Click a row for the PSAB descriptions.")

# on_select="rerun" makes a row click re-run the script; the clicked row
# number comes back in event.selection.rows.
event = st.dataframe(
    view.drop(columns="account_type"),
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "function": st.column_config.TextColumn("Function", width="small"),
        "function_name": "Function name",
        "object": st.column_config.TextColumn("Object", width="small"),
        "object_name": "Object name",
        "program": st.column_config.TextColumn("Program", width="small"),
        "job_classes": "Job classes open",
    },
)

# ─── Detail for the clicked row ───────────────────────────────────────
if event.selection.rows:
    r = view.iloc[event.selection.rows[0]]
    st.subheader(f"{fund} · {r.function} · {r.object} · {r.program}")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"**Function {r.function} — {r.function_name}**")
        st.write(psab_of("function", r.function) or "_No PSAB description on file._")
    with d2:
        st.markdown(f"**Object {r.object} — {r.object_name}**")
        st.write(psab_of("object", r.object) or "_No PSAB description on file._")
    st.markdown(f"**Program {r.program} — {name_of('program', r.program)}**")
    if r.job_classes:
        st.markdown("**Job classes open on this line**")
        st.dataframe(
            pd.DataFrame({"Job class": jc, "Name": name_of("job_class", jc)} for jc in r.job_classes.split(", ")),
            hide_index=True, width="content",
        )

# ─── Download ─────────────────────────────────────────────────────────
# Full detail (one row per job class), limited to the filtered groups above.
keys = view[["account_type", "function", "object", "program"]]
detail = fl.merge(keys, on=list(keys.columns))
for dim in ("function", "object", "program", "job_class"):
    detail[f"{dim}_name"] = detail[dim].map(lambda c, d=dim: name_of(d, c))
st.download_button(
    f"Download these lines ({len(detail):,} rows, CSV)",
    detail.to_csv(index=False).encode("utf-8-sig"),   # utf-8-sig so Excel opens it cleanly
    file_name=f"chart_lines_{fund}.csv",
    mime="text/csv",
)
