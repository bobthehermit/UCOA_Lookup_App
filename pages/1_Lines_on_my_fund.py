"""
pages/1_Lines_on_my_fund.py — open chart lines, read two ways.

    By fund   pick a fund  -> every function / object / program / job class line open on it
    By code   pick a code  -> every fund that code is open on, and what it is paired with

Both views read the same table (data/chart_lines.parquet, one row per open line). "By fund"
filters the rows to one fund; "By code" filters them to one code and then counts funds.

How this page plugs in
----------------------
Streamlit treats any .py file inside a folder named `pages/` (next to the main script) as an
extra page. Each page is its own script, run top to bottom on every interaction.

Links into this page
--------------------
Other pages can open this one already pointed at something, using the address bar:
    ...?view=code&dim=object&code=58215      (the Code lookup cards do this)
    ...?view=fund&fund=27579
st.query_params reads those values. They only set the starting choice; after that the
widgets are in charge.

Data it reads (all built by the two build scripts — never hand-edited)
---------------------------------------------------------------------
    data/chart_lines.parquet     every open line, codes only   (build_chart_lines.py)
    data/fund_line_summary.csv   one row per fund               (build_chart_lines.py)
    data/ucoa_<dim>.csv          names + PSAB descriptions      (build_ucoa.py)
"""

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))          # lets this page import modules from the project folder

import pandas as pd
import streamlit as st

from ui_common import setup_page

# setup_page does the things every page shares: tab title, brand CSS, logo,
# the page menu and the heading. See ui_common.py.
setup_page("Open chart lines")

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
st.caption(
    f"Chart lines currently open in OBMS, as of the {built} export. "
    "PSAB Supplement 3 is the authoritative guidance on what each code means."
)

# ─── Which way to read the data ───────────────────────────────────────
# A link from another page may arrive with ?view=...&dim=...&code=... in the address.
# Copy those into st.session_state ONCE (keyed by the link itself), so they set the
# starting choice without fighting the user's later clicks.
qp = st.query_params
link_id = "|".join(f"{k}={qp.get(k, '')}" for k in ("view", "dim", "code", "fund"))
if qp and st.session_state.get("_link_seen") != link_id:
    st.session_state["_link_seen"] = link_id
    if qp.get("view") in ("code", "fund"):
        st.session_state["view_mode"] = "By code" if qp.get("view") == "code" else "By fund"
    if qp.get("dim") in ("function", "object", "program", "job_class"):
        st.session_state["code_dim"] = qp.get("dim")
        if qp.get("code"):
            st.session_state[f"code_pick_{qp.get('dim')}"] = qp.get("code")
    if qp.get("fund"):
        st.session_state["fund_pick"] = qp.get("fund")

# A widget with a key keeps its value in st.session_state under that key. setdefault gives
# it a starting value only if a link (above) or an earlier click has not already set one.
st.session_state.setdefault("view_mode", "By fund")
st.session_state.setdefault("code_dim", "object")
mode = st.segmented_control("View", ["By fund", "By code"], key="view_mode",
                            label_visibility="collapsed") or "By fund"

TOTAL_FUNDS = lines["fund"].nunique()
DIM_LABEL = {"function": "Function", "object": "Object", "program": "Program", "job_class": "Job class"}


def family_of(fund_code: str) -> str:
    """Fund family = the fund's first two digits: 27579 -> 27000."""
    return fund_code[:2] + "000"


def family_label(fam: str) -> str:
    name = name_of("fund", fam)
    return f"{fam[:2]}xxx — {name}" if name else f"{fam[:2]}xxx"


# ═════════════════════════════════════════════════════════════════════
# BY CODE — where is this code open?
# ═════════════════════════════════════════════════════════════════════
if mode == "By code":
    st.caption("Pick a code to see every fund it is open on. This is where a code *can* be "
               "budgeted today — not where it has been.")

    d1, d2 = st.columns([1, 3])
    dim = d1.selectbox("Dimension", list(DIM_LABEL), format_func=DIM_LABEL.get, key="code_dim")

    # How many funds each code of this dimension is open on. groupby + nunique = "for each
    # code, count the distinct funds". observed=True skips category values with no rows.
    @st.cache_data(ttl=3600, show_spinner=False)
    def fund_counts(d: str) -> pd.Series:
        return lines.groupby(d, observed=True)["fund"].nunique()

    counts = fund_counts(dim)
    table = look[dim]
    in_obms = [c for c in table.index if table.at[c, "Availability"] != "Books only"] \
        if "Availability" in table.columns else list(table.index)
    code_options = sorted(set(in_obms) | set(counts.index.astype(str)))
    pick_key = f"code_pick_{dim}"
    if st.session_state.get(pick_key) not in code_options:
        st.session_state.pop(pick_key, None)          # a code from a stale link: ignore it
    code = d2.selectbox(
        "Code", code_options, index=None, key=pick_key,
        placeholder="Type a code or name…",
        format_func=lambda c: f"{c} — {name_of(dim, c)}  ·  {int(counts.get(c, 0))} funds",
    )
    if code is None:
        st.info("Choose a code to see which funds it is open on.")
        st.stop()

    cl = lines[lines[dim] == code].astype(str)        # every open line that uses this code
    open_funds = sorted(cl["fund"].unique())
    st.subheader(f"{DIM_LABEL[dim]} {code} — {name_of(dim, code)}")

    if not open_funds:
        st.warning(f"{DIM_LABEL[dim]} {code} is not open on any fund. It exists in the chart of "
                   "accounts, but no chart line uses it.")
        desc = psab_of(dim, code)
        if desc:
            with st.expander("PSAB description"):
                st.write(desc)
        st.stop()

    others = [d for d in DIM_LABEL if d != dim]
    main_other = "function" if dim != "function" else "object"
    top = cl.groupby(main_other)["fund"].nunique().sort_values(ascending=False)
    m1, m2, m3 = st.columns(3)
    m1.metric("Open on", f"{len(open_funds)} of {TOTAL_FUNDS} funds")
    m2.metric("Chart lines", f"{len(cl):,}")
    m3.metric(f"Most common {DIM_LABEL[main_other].lower()}",
              f"{top.index[0]} · {int(top.iloc[0])} funds",
              help=name_of(main_other, top.index[0]))

    desc = psab_of(dim, code)
    if desc:
        with st.expander("PSAB description"):
            st.write(desc)

    # ── By fund family ────────────────────────────────────────────────
    all_fams = pd.Series(sorted(summary.index)).map(family_of).value_counts()
    open_fams = pd.Series(open_funds).map(family_of).value_counts()
    fam_table = pd.DataFrame({"Open on": open_fams, "Funds in family": all_fams}).dropna()
    fam_table["Open on"] = fam_table["Open on"].astype(int)
    fam_table["Share"] = fam_table["Open on"] / fam_table["Funds in family"]
    fam_table.insert(0, "Fund family", [family_label(f) for f in fam_table.index])

    left, right = st.columns(2)
    with left:
        st.markdown("#### By fund family")
        st.dataframe(
            fam_table.sort_index(), hide_index=True, width="stretch",
            column_config={"Share": st.column_config.ProgressColumn(
                "Share of family", format="percent", min_value=0, max_value=1)},
        )
    with right:
        st.markdown("#### What it is paired with")
        tabs = st.tabs([DIM_LABEL[d] for d in others])
        for tab, d in zip(tabs, others):
            pair = cl.groupby(d)["fund"].nunique().sort_values(ascending=False).reset_index()
            pair.columns = ["Code", "Funds"]
            pair.insert(1, "Name", pair["Code"].map(lambda c, d=d: name_of(d, c)))
            tab.dataframe(pair, hide_index=True, width="stretch", height=248)

    # ── The funds ─────────────────────────────────────────────────────
    st.markdown("#### Funds")
    g1, g2, g3 = st.columns([1.4, 2, 2])
    show = g1.segmented_control("Show", ["Open on", "Not open on"], default="Open on",
                                key="code_show") or "Open on"
    fam_choices = sorted(all_fams.index)
    sel_fams = g2.multiselect("Fund family", fam_choices, format_func=family_label,
                              placeholder="All families", key="code_fams")
    fq = g3.text_input("Search funds", placeholder="Fund number or word", key="code_fund_q")

    if show == "Open on":
        # One row per fund: the other three dimensions it is paired with on that fund.
        fund_table = cl.groupby("fund").agg(
            **{d: (d, lambda s: ", ".join(sorted(set(s) - {"0000"}) or ["0000"])) for d in others},
            lines=("fund", "size"),
        ).reset_index()
    else:
        fund_table = pd.DataFrame({"fund": [f for f in sorted(summary.index) if f not in set(open_funds)]})
    fund_table.insert(1, "fund_name", fund_table["fund"].map(lambda c: summary.at[c, "fund_name"]))
    fund_table["width"] = fund_table["fund"].map(lambda c: summary.at[c, "width"].title())

    if sel_fams:
        fund_table = fund_table[fund_table["fund"].map(family_of).isin(sel_fams)]
    if fq.strip():
        hay = fund_table.astype(str).agg(" ".join, axis=1).str.lower()
        for word in fq.lower().split():
            keep = hay.str.contains(word, regex=False)
            fund_table, hay = fund_table[keep], hay[keep]
    fund_table = fund_table.reset_index(drop=True)

    verb = "open on" if show == "Open on" else "not open on"
    st.caption(f"{DIM_LABEL[dim]} {code} is {verb} {len(fund_table):,} fund(s) in this list."
               + (" Click a row to see its lines on that fund." if show == "Open on" else ""))
    labels = {"fund": st.column_config.TextColumn("Fund", width="small"), "fund_name": "Fund name",
              "function": st.column_config.TextColumn("Functions", width="medium"),
              "object": st.column_config.TextColumn("Objects", width="medium"), "program": "Programs",
              "job_class": "Job classes", "lines": st.column_config.NumberColumn("Lines", width="small"),
              "width": st.column_config.TextColumn("Fund width", width="small")}
    if show == "Open on":
        ev = st.dataframe(fund_table, hide_index=True, width="stretch", column_config=labels,
                          on_select="rerun", selection_mode="single-row", key="code_fund_table")
        if ev.selection.rows and len(fund_table):
            f = fund_table.iloc[ev.selection.rows[0]]["fund"]
            st.markdown(f"**{f} — {summary.at[f, 'fund_name']}** · lines using {DIM_LABEL[dim].lower()} {code}")
            det = cl[cl["fund"] == f][["function", "object", "program", "job_class"]].sort_values(
                ["function", "object", "program", "job_class"])
            for d in ("function", "object"):
                det.insert(det.columns.get_loc(d) + 1, f"{d}_name", det[d].map(lambda c, d=d: name_of(d, c)))
            st.dataframe(det, hide_index=True, width="stretch")
            st.page_link("pages/1_Lines_on_my_fund.py", label=f"See every line open on {f}",
                         icon=":material/list_alt:", query_params={"view": "fund", "fund": f})
    else:
        st.dataframe(fund_table, hide_index=True, width="stretch", column_config=labels)

    full = cl[["fund", "function", "object", "program", "job_class"]].copy()
    full.insert(1, "fund_name", full["fund"].map(lambda c: summary.at[c, "fund_name"]))
    st.download_button(
        f"Download every line using {code} ({len(full):,} rows, CSV)",
        full.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"chart_lines_{dim}_{code}.csv", mime="text/csv",
    )
    st.stop()

# ═════════════════════════════════════════════════════════════════════
# BY FUND — what is open on this fund?
# ═════════════════════════════════════════════════════════════════════
# ─── Pick a fund ──────────────────────────────────────────────────────
fund_codes = sorted(summary.index)
if st.session_state.get("fund_pick") not in fund_codes:
    st.session_state.pop("fund_pick", None)           # a fund from a stale link: ignore it
fund = st.selectbox(
    "Fund",
    fund_codes,
    index=None,
    key="fund_pick",
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
