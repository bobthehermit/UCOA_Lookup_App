# ucoa_reference.py — UCOA Reference Explorer
# NM PED School Budget Bureau
#
# Loads chart-of-accounts reference data from the NMPED UCOA Reference Tables
# Google Sheet (one tab per dimension: Fund, Function, Object, Program, Job Class).
# Design language matches PED Contacts Manager (Merge_ped_contacts_v2.py).

import pandas as pd
import streamlit as st
from datetime import datetime
from pathlib import Path
import base64
from io import BytesIO

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ─── Page config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="UCOA Reference Explorer",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Brand CSS ────────────────────────────────────────────────────────
# Palette mirrors Contacts Manager exactly:
#   Primary teal : #245d62   Dark teal : #1a474b
#   Gold          : #edc872  Coral     : #c64c43  (alerts only)
st.markdown("""
<style>
.block-container { padding-top: 1.1rem !important; max-width: 1180px; }

h1, h2, h3, h4 { color: #245d62; font-weight: 600; }

.ped-eyebrow {
    font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
    color: #7a8a86; font-weight: 600;
}
.ped-title {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1.6rem; color: #245d62; font-weight: 600;
    margin: .15rem 0 .6rem; line-height: 1.1;
}
.ped-rule { display: flex; height: 3px; margin-bottom: 1.3rem; }
.ped-rule .g { width: 46px; background: #edc872; }
.ped-rule .t { flex: 1; background: #245d62; }

.section-label {
    font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
    color: #245d62; font-weight: 600;
    padding-bottom: 6px; border-bottom: 1px solid #edc872;
    margin: 16px 0 10px;
}

.pill { font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; }
.pill-grant   { color: #854f0b; background: #faeeda; }
.pill-flow    { color: #1a474b; background: #e1efe9; }
.pill-gen     { color: #444441; background: #f1efe8; }
.pill-direct  { color: #72243e; background: #fbeaf0; }
.pill-retired { color: #5f5e5a; background: #e8e8e4; }
.pill-gap     { color: #993c1d; background: #faece7; }

.badge {
    font-size: 12px; color: #5f5e5a; background: #f1efe8;
    padding: 3px 9px; border-radius: 6px;
}
.badge-mono { font-family: monospace; }

.desc-box {
    background: #f7f6f2; border-left: 3px solid #edc872;
    padding: 10px 14px; border-radius: 0 6px 6px 0;
    font-size: 13px; color: #3a3a38; line-height: 1.55;
    margin-top: 4px;
}

a { color: #245d62; text-decoration: none; }
a:hover { color: #1a474b; text-decoration: underline; }

.stDownloadButton button {
    width: 100%; background: #245d62; color: #fff !important; border: none;
}
.stDownloadButton button:hover { background: #1a474b; }
.stDownloadButton button p,
.stDownloadButton button span { color: #fff !important; }

[data-testid="stSidebar"] .stMultiSelect [data-baseweb="tag"] {
    background: #245d62 !important;
}
[data-testid="stSidebar"] .stMultiSelect [data-baseweb="tag"] span { color: #fff !important; }
[data-testid="stSidebar"] .stMultiSelect [data-baseweb="tag"] svg  { fill: #fff !important; }

[data-testid="stExpander"] { border: 0.5px solid #ececec; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# ─── Logo ─────────────────────────────────────────────────────────────
LOGO_PATH = Path(__file__).parent / "300 DPI NM PED Logo JPEG.jpg"
LOGO_LINK = "https://web.ped.nm.gov/bureaus/school-budget-bureau/"

def _load_logo():
    if not LOGO_PATH.exists() or not HAS_PIL:
        return None
    try:
        buf = BytesIO()
        Image.open(LOGO_PATH).save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return (
            f'<a href="{LOGO_LINK}" target="_blank">'
            f'<img src="data:image/png;base64,{b64}" '
            f'style="max-height:90px;height:auto;max-width:100%"></a>'
        )
    except Exception:
        return None

logo = _load_logo()
if logo:
    st.sidebar.markdown(logo, unsafe_allow_html=True)
st.sidebar.caption("School Budget Bureau")

# ═════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════

SHEET_ID = "179P7Kc1RZjUdU7M0tlcyHIvyeGXLsSgdHA7D9Za1bts"

SHEET_URLS = {
    "Fund":      f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1867310814",
    "Function":  f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=292988496",
    "Object":    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=279448712",
    "Program":   f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=17961571",
    "Job Class": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1361122649",
}

# Fund tab — actual column names from the sheet
FUND_COLS = {
    "type_col":       "FundType",
    "parent_col":     "ParentFundCode",
    "grant_col":      "IsGrant",
    "grantname_col":  "GrantName",
    "budget_col":     "IsBudgetable",
    "actuals_col":    "ActualsPostable",
    "reimburse_col":  "IsReimbursable",
    "approvals_col":  "RequiresApprovals",
    "assessedval_col":"SupportsAssessedValuations",
    "revobj_col":     "RevObjectCurrYear",
    "revobj_py_col":  "RevObjectPriorYear",
    "chartxfer_col":  "UsesDependentCharterXfer",
    "zeroout_col":    "PEDZeroOut",
    "notinuse_col":   "NotInUse",
    "psab_col":       "PSABDescription",
    "obms_col":       "OBMSDescription",
}

DIM_CONFIG = {
    "Fund": {
        "title": "Fund codes",
        **FUND_COLS,
    },
    "Function": {
        "title":    "Function codes",
        "type_col": "FunctionType",
    },
    "Object": {
        "title":    "Object codes",
        "type_col": "ObjectType",
    },
    "Program": {
        "title":       "Program codes",
        "type_col":    "ProgramType",
        "protect_col": "IsProtected",
    },
    "Job Class": {
        "title":    "Job class codes",
        "type_col": "ClassType",
    },
}

PAGE_SIZE = 10

# ═════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════

def _clean(x) -> str:
    return "" if pd.isna(x) else str(x).strip()

def _is_gap(x) -> bool:
    return _clean(x) in {"????", "?", "TBD", ""}

def _bool_col(val) -> bool:
    return _clean(val).lower() in {"yes", "true", "1", "y"}

def _yn(val) -> str:
    """Display Yes/No with light colour hint."""
    v = _clean(val)
    if v.lower() in {"yes", "true", "1", "y"}:
        return "✓ Yes"
    if v.lower() in {"no", "false", "0", "n"}:
        return "No"
    return v or "—"

def _type_pill(t: str) -> str:
    t = _clean(t)
    tl = t.lower()
    if "flowthrough" in tl or "flow" in tl:
        return f'<span class="pill pill-flow">{t}</span>'
    if "direct" in tl:
        return f'<span class="pill pill-direct">{t}</span>'
    if "general" in tl:
        return f'<span class="pill pill-gen">{t}</span>'
    if "martinez" in tl or "protected" in tl:
        return f'<span class="pill pill-grant">Protected</span>'
    return f'<span class="pill pill-gen">{t}</span>' if t else ""

def _metric_card(label: str, value, alert: bool = False) -> str:
    if alert:
        border = "border:0.5px solid #ecc9c1;border-left:3px solid #c64c43;"
        lab_color, val_color = "#a8584c", "#c64c43"
    else:
        border = "border:0.5px solid #e3e3dd;"
        lab_color, val_color = "#8a8a82", "#245d62"
    return (
        f'<div style="{border}border-radius:8px;padding:13px 15px;">'
        f'<div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;'
        f'color:{lab_color};">{label}</div>'
        f'<div style="font-size:1.7rem;font-weight:600;color:{val_color};">{value}</div>'
        f'</div>'
    )

# ═════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_all_dims() -> tuple[dict[str, pd.DataFrame], str]:
    ts = datetime.now().strftime("%b %d %Y, %I:%M %p")
    data: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    for dim, url in SHEET_URLS.items():
        try:
            df = pd.read_csv(url, dtype=str).fillna("")
            df.columns = [c.strip() for c in df.columns]
            # Drop completely empty rows
            df = df[df.apply(lambda r: any(_clean(v) for v in r), axis=1)]
            data[dim] = df
        except Exception as e:
            errors.append(f"{dim}: {e}")
            data[dim] = pd.DataFrame()
    return data, ts, errors

# ═════════════════════════════════════════════════════════════════════
# DETAIL CARD
# ═════════════════════════════════════════════════════════════════════

def display_fund_detail(row: pd.Series, cfg: dict):
    """Full detail card for a Fund code row."""
    code      = _clean(row.get("Code", ""))
    name      = _clean(row.get("Name", ""))
    fund_type = _clean(row.get(cfg.get("type_col",""), ""))
    parent    = _clean(row.get(cfg.get("parent_col",""), ""))
    is_grant  = _bool_col(row.get(cfg.get("grant_col",""), ""))
    grant_name= _clean(row.get(cfg.get("grantname_col",""), ""))
    not_in_use= _bool_col(row.get(cfg.get("notinuse_col",""), ""))

    # Header
    retired_pill = ' <span class="pill pill-retired">Not in use</span>' if not_in_use else ""
    grant_pill   = ' <span class="pill pill-grant">Grant</span>' if is_grant else ""
    gap_pill     = ' <span class="pill pill-gap">⚠ Grant name missing</span>' if (is_grant and _is_gap(grant_name)) else ""

    st.markdown(
        f'<div style="font-size:1.2rem;font-weight:600;color:#222;">{name}</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0 4px;">'
        f'<span class="badge badge-mono">{code}</span>'
        f'{_type_pill(fund_type)}{grant_pill}{retired_pill}{gap_pill}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Core attributes ──────────────────────────────────────────────
    st.markdown('<div class="section-label">Fund attributes</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.write(f"**Fund type:** {fund_type or '—'}")
        st.write(f"**Parent fund:** {parent or '—'}")
        st.write(f"**Is grant:** {_yn(row.get(cfg.get('grant_col',''),''))}")
        st.write(f"**Grant name:** {grant_name if not _is_gap(grant_name) else '⚠ Missing'}")
    with c2:
        st.write(f"**Budgetable:** {_yn(row.get(cfg.get('budget_col',''),''))}")
        st.write(f"**Actuals postable:** {_yn(row.get(cfg.get('actuals_col',''),''))}")
        st.write(f"**Reimbursable:** {_yn(row.get(cfg.get('reimburse_col',''),''))}")
        st.write(f"**Requires approvals:** {_yn(row.get(cfg.get('approvals_col',''),''))}")
    with c3:
        st.write(f"**Supports assessed valuations:** {_yn(row.get(cfg.get('assessedval_col',''),''))}")
        st.write(f"**Uses dependent charter xfer:** {_yn(row.get(cfg.get('chartxfer_col',''),''))}")
        st.write(f"**PED zero-out:** {_yn(row.get(cfg.get('zeroout_col',''),''))}")
        st.write(f"**Not in use:** {_yn(row.get(cfg.get('notinuse_col',''),''))}")

    # Revenue objects
    rev_cy = _clean(row.get(cfg.get("revobj_col",""), ""))
    rev_py = _clean(row.get(cfg.get("revobj_py_col",""), ""))
    if rev_cy or rev_py:
        st.markdown('<div class="section-label">Revenue objects</div>', unsafe_allow_html=True)
        rc1, rc2 = st.columns(2)
        with rc1:
            st.write(f"**Current year:** {rev_cy or '—'}")
        with rc2:
            st.write(f"**Prior year:** {rev_py or '—'}")

    # PSAB description
    psab = _clean(row.get(cfg.get("psab_col",""), ""))
    if psab:
        st.markdown('<div class="section-label">PSAB description</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="desc-box">{psab}</div>', unsafe_allow_html=True)

    # OBMS description
    obms = _clean(row.get(cfg.get("obms_col",""), ""))
    if obms:
        st.markdown('<div class="section-label">OBMS notes</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="desc-box">{obms}</div>', unsafe_allow_html=True)


def display_generic_detail(row: pd.Series, dim: str, cfg: dict):
    """Detail card for Function, Object, Program, Job Class."""
    code     = _clean(row.get("Code", ""))
    name     = _clean(row.get("Name", ""))
    type_col = cfg.get("type_col", "")
    type_val = _clean(row.get(type_col, "")) if type_col else ""

    st.markdown(
        f'<div style="font-size:1.2rem;font-weight:600;color:#222;">{name}</div>'
        f'<div style="display:flex;gap:8px;align-items:center;margin:8px 0;">'
        f'<span class="badge badge-mono">{code}</span>'
        f'{_type_pill(type_val)}'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-label">Details</div>', unsafe_allow_html=True)

    # All columns except Code and Name
    fields = [
        (col, _clean(row[col]))
        for col in row.index
        if col not in {"Code", "Name"} and _clean(row[col])
    ]

    if not fields:
        st.write("No additional detail available.")
        return

    c1, c2 = st.columns(2)
    half = len(fields) // 2 + len(fields) % 2
    for i, (k, v) in enumerate(fields):
        col = c1 if i < half else c2
        with col:
            st.write(f"**{k}:** {v}")


# ═════════════════════════════════════════════════════════════════════
# MAIN APP
# ═════════════════════════════════════════════════════════════════════

# Masthead
st.markdown(
    '<div class="ped-eyebrow">New Mexico PED · School Budget Bureau</div>'
    '<div class="ped-title">UCOA Reference Explorer</div>'
    '<div class="ped-rule"><span class="g"></span><span class="t"></span></div>',
    unsafe_allow_html=True,
)

# ── Sidebar: data loading ─────────────────────────────────────────────
st.sidebar.header("Data")

if st.sidebar.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()

with st.spinner("Loading from Google Sheets…"):
    all_data, refresh_ts, load_errors = _fetch_all_dims()

st.sidebar.success(f"Loaded — {refresh_ts}")
if load_errors:
    for err in load_errors:
        st.sidebar.warning(err)

# ── Dimension selector ────────────────────────────────────────────────
st.sidebar.markdown("### Dimension")
dim_options = list(SHEET_URLS.keys())
dim_counts  = {d: len(all_data.get(d, [])) for d in dim_options}
dim_labels  = [f"{d}  ({dim_counts[d]})" for d in dim_options]
dim_idx = st.sidebar.radio(
    "Select dimension",
    range(len(dim_options)),
    format_func=lambda i: dim_labels[i],
    label_visibility="collapsed",
)
active_dim = dim_options[dim_idx]
df_active  = all_data.get(active_dim, pd.DataFrame())
cfg        = DIM_CONFIG.get(active_dim, {})
type_col   = cfg.get("type_col", "")

# ── Sidebar filters ───────────────────────────────────────────────────
st.sidebar.markdown("### Filters")

# Type multiselect (all dims)
sel_types = []
if type_col and type_col in df_active.columns:
    all_types = sorted(df_active[type_col].dropna().unique().tolist())
    if all_types:
        sel_types = st.sidebar.multiselect("Type", all_types, default=all_types)

# Fund-specific checkboxes
show_grants_only    = False
show_gaps_only      = False
show_budgetable_only= False
show_active_only    = False

if active_dim == "Fund":
    if cfg.get("grant_col","") in df_active.columns:
        show_grants_only = st.sidebar.checkbox("Grants only")
    if cfg.get("grantname_col","") in df_active.columns:
        show_gaps_only = st.sidebar.checkbox("Missing grant names (????)")
    if cfg.get("budget_col","") in df_active.columns:
        show_budgetable_only = st.sidebar.checkbox("Budgetable only")
    if cfg.get("notinuse_col","") in df_active.columns:
        show_active_only = st.sidebar.checkbox("Active only (exclude Not in Use)")

# Program-specific
show_protected_only = False
if active_dim == "Program" and cfg.get("protect_col","") in df_active.columns:
    show_protected_only = st.sidebar.checkbox("Martinez-Yazzie protected only")

if st.sidebar.button("Reset filters"):
    st.rerun()

# ── Search ────────────────────────────────────────────────────────────
search = st.text_input("Search", placeholder="Code, name, grant name, CFDA, description…")

# ── Apply filters ─────────────────────────────────────────────────────
view = df_active.copy()

if sel_types and type_col and type_col in view.columns:
    view = view[view[type_col].isin(sel_types)]

if show_grants_only and cfg.get("grant_col","") in view.columns:
    view = view[view[cfg["grant_col"]].str.lower().isin({"yes","true","1","y"})]

if show_gaps_only and cfg.get("grantname_col","") in view.columns:
    view = view[view[cfg["grantname_col"]].apply(_is_gap)]

if show_budgetable_only and cfg.get("budget_col","") in view.columns:
    view = view[view[cfg["budget_col"]].str.lower().isin({"yes","true","1","y"})]

if show_active_only and cfg.get("notinuse_col","") in view.columns:
    view = view[~view[cfg["notinuse_col"]].str.lower().isin({"yes","true","1","y"})]

if show_protected_only and cfg.get("protect_col","") in view.columns:
    view = view[view[cfg["protect_col"]].str.lower().isin({"yes","true","1","y"})]

if search:
    q = search.lower()
    mask = pd.Series(False, index=view.index)
    for c in view.select_dtypes(include="object").columns:
        mask |= view[c].astype(str).str.lower().str.contains(q, na=False)
    view = view[mask]

# ── Metrics row ───────────────────────────────────────────────────────
total_in_dim = len(df_active)
showing      = len(view)

grants_n = gaps_n = not_in_use_n = 0
if active_dim == "Fund":
    gc  = cfg.get("grant_col","")
    gnc = cfg.get("grantname_col","")
    niu = cfg.get("notinuse_col","")
    if gc  in df_active.columns:
        grants_n    = int(df_active[gc].str.lower().isin({"yes","true","1","y"}).sum())
    if gnc in df_active.columns:
        # gaps only among grant funds
        grant_mask = df_active[gc].str.lower().isin({"yes","true","1","y"}) if gc in df_active.columns else pd.Series(True, index=df_active.index)
        gaps_n = int(df_active[gnc][grant_mask].apply(_is_gap).sum())
    if niu in df_active.columns:
        not_in_use_n = int(df_active[niu].str.lower().isin({"yes","true","1","y"}).sum())

m1, m2, m3, m4 = st.columns(4)
m1.markdown(_metric_card("Total codes", total_in_dim), unsafe_allow_html=True)
m2.markdown(_metric_card("Showing", showing), unsafe_allow_html=True)

if active_dim == "Fund":
    m3.markdown(_metric_card("Grant funds", grants_n), unsafe_allow_html=True)
    m4.markdown(_metric_card("Missing grant names", gaps_n, alert=gaps_n > 0), unsafe_allow_html=True)
else:
    m3.markdown(_metric_card("Dimension", active_dim), unsafe_allow_html=True)
    m4.markdown(_metric_card("Filtered", showing), unsafe_allow_html=True)

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════
# PAGINATED CODE BROWSER
# ═════════════════════════════════════════════════════════════════════

dim_page_key = f"page_{active_dim}"
if dim_page_key not in st.session_state:
    st.session_state[dim_page_key] = 0

if len(view) == 0:
    st.info("No codes match your filters.")
else:
    total_pages = max(1, -(-len(view) // PAGE_SIZE))
    page  = min(st.session_state[dim_page_key], total_pages - 1)
    start = page * PAGE_SIZE
    end   = min(start + PAGE_SIZE, len(view))
    page_df = view.iloc[start:end]

    dim_title = cfg.get("title", f"{active_dim} codes")
    st.markdown(f"#### {dim_title.capitalize()} ({start+1}–{end} of {showing})")

    grantname_col = cfg.get("grantname_col", "")
    notinuse_col  = cfg.get("notinuse_col", "")

    for _, row in page_df.iterrows():
        code     = _clean(row.get("Code", ""))
        name     = _clean(row.get("Name", ""))
        type_val = _clean(row.get(type_col, "")) if type_col else ""

        is_grant  = _bool_col(row.get(cfg.get("grant_col",""), "")) if active_dim == "Fund" else False
        grant_name= _clean(row.get(grantname_col, "")) if grantname_col else ""
        not_in_use= _bool_col(row.get(notinuse_col, "")) if notinuse_col else False

        grant_tag   = " · Grant" if is_grant else ""
        gap_tag     = " ⚠" if (is_grant and _is_gap(grant_name)) else ""
        retired_tag = " · [not in use]" if not_in_use else ""
        label = f"**{code}** — {name} · {type_val}{grant_tag}{gap_tag}{retired_tag}"

        with st.expander(label, expanded=False):
            if active_dim == "Fund":
                display_fund_detail(row, cfg)
            else:
                display_generic_detail(row, active_dim, cfg)

    # Pagination
    pcol1, pcol2, pcol3, pcol4, pcol5 = st.columns([1, 1, 2, 1, 1])
    with pcol1:
        if st.button("First", disabled=(page == 0), key=f"pg_first_{active_dim}"):
            st.session_state[dim_page_key] = 0
            st.rerun()
    with pcol2:
        if st.button("‹ Prev", disabled=(page == 0), key=f"pg_prev_{active_dim}"):
            st.session_state[dim_page_key] = page - 1
            st.rerun()
    with pcol3:
        st.markdown(
            f"<div style='text-align:center;padding-top:6px;color:#8a8a82'>"
            f"Page {page+1} of {total_pages}</div>",
            unsafe_allow_html=True,
        )
    with pcol4:
        if st.button("Next ›", disabled=(page >= total_pages - 1), key=f"pg_next_{active_dim}"):
            st.session_state[dim_page_key] = page + 1
            st.rerun()
    with pcol5:
        if st.button("Last", disabled=(page >= total_pages - 1), key=f"pg_last_{active_dim}"):
            st.session_state[dim_page_key] = total_pages - 1
            st.rerun()

# ═════════════════════════════════════════════════════════════════════
# DATA TABLE & DOWNLOADS
# ═════════════════════════════════════════════════════════════════════

with st.expander("Data table", expanded=False):
    st.dataframe(view, width="stretch", height=400)

st.subheader("Downloads")
dl1, dl2 = st.columns(2)
with dl1:
    st.download_button(
        f"Filtered ({active_dim})",
        view.to_csv(index=False).encode("utf-8-sig"),
        f"ucoa_{active_dim.lower().replace(' ','_')}_filtered.csv",
        "text/csv",
    )
with dl2:
    combined = pd.concat(
        [df.assign(Dimension=dim) for dim, df in all_data.items() if not df.empty],
        ignore_index=True,
    )
    st.download_button(
        "All dimensions (combined CSV)",
        combined.to_csv(index=False).encode("utf-8-sig"),
        "ucoa_all_dimensions.csv",
        "text/csv",
    )

# Footer
st.markdown("---")
st.caption("New Mexico Public Education Department · School Budget Bureau")