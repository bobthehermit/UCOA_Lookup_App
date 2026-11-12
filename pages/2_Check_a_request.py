"""
pages/2_Check_a_request.py — test lines before (or while) requesting them.

Phase 2 of the Chart Line Guide. Type or paste the lines someone wants on a
fund; each line is checked against:

  1. OBMS settings      codes exist, are active, are postable         (rules_engine.builtin_checks)
  2. What's open        already on the fund? brand new statewide?     (data/chart_lines.parquet)
  3. SBB coding rules   config/rules.yaml                             (rules_engine.check_lines)

It also shows who signs for the fund, from the COA Maintenance Form's Workflow
tab (config/workflow.csv).

The page decides nothing — it prepares the review. The form is still the request.
"""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

import rules_engine as re_
from ui_common import setup_page

setup_page("Check new lines")
st.caption(
    "Enter the chart lines you plan to request and see how they line up with PSAB Supplement 3 "
    "and SBB's coding rules. This is a pre-check, not an approval: requests still go through the "
    "COA Maintenance Form, and **PSAB Supplement 3 is the authoritative guidance.**"
)

DATA = ROOT / "data"
DIMS = {"fund": "ucoa_fund.csv", "function": "ucoa_function.csv", "object": "ucoa_object.csv",
        "program": "ucoa_program.csv", "job_class": "ucoa_job_class.csv"}
ICON = {"error": "❌", "warning": "⚠️", "question": "❓", "info": "ℹ️", "ok": "✅"}
STATUS_TEXT = {"error": "❌ Needs a change", "warning": "⚠️ Needs review",
               "question": "❓ Needs an answer", "ok": "✅ No issues found",
               "open": "✅ Already open"}


@st.cache_data(ttl=3600, show_spinner="Loading chart lines…")
def load():
    look = {}
    for dim, fname in DIMS.items():
        d = pd.read_csv(DATA / fname, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        look[dim] = d.drop_duplicates("Code").set_index("Code")
    lines = pd.read_parquet(DATA / "chart_lines.parquet").astype(str)
    workflow = pd.read_csv(ROOT / "config" / "workflow.csv", dtype=str, keep_default_na=False).set_index("fund")
    return look, lines, workflow


look, all_lines, workflow = load()
# Not cached: rules.yaml is small, and reading it fresh means an edit shows up on the next rerun.
rules = re_.load_rules(ROOT / "config" / "rules.yaml")

# ─── Fund ─────────────────────────────────────────────────────────────
funds = look["fund"]
fund_codes = sorted(c for c in funds.index if funds.at[c, "Status"] != "Historical")
fund = st.selectbox(
    "Fund",
    fund_codes,
    index=None,
    placeholder="Type a fund number or name — or a new fund number not in OBMS yet",
    format_func=lambda c: f"{c} — {funds.at[c, 'Name']}" if c in funds.index else f"{c} — new fund",
    accept_new_options=True,       # lets the user type a fund that isn't in the list
)
if not fund:
    st.info("Choose the fund the lines are for.")
    st.stop()
fund = fund.strip()
if not (fund.isdigit() and len(fund) == 5):
    st.error("A fund number is five digits, e.g. 27579.")
    st.stop()

is_new_fund = fund not in funds.index
fund_lines = all_lines[all_lines.fund == fund]

route = re_.approval_route(fund, workflow, funds)
with st.container(border=True):
    if is_new_fund:
        st.markdown(f"**{fund} is not in OBMS yet** — this would be a new-fund request.")
    else:
        exp = fund_lines[fund_lines.account_type == "Expenditure"]
        n_pairs = len(exp[["function", "object"]].drop_duplicates())
        st.markdown(f"**{fund} — {funds.at[fund, 'Name']}** · {n_pairs:,} function/object pairs open today")
    if route:
        pm = route["new_fund_pm_signer"] if is_new_fund else route["update_pm_signer"]
        if route["pm_exception"]:
            pm = "PED Program Manager"
        fm = route["new_fund_fm_signer"] if is_new_fund else route["update_fm_signer"]
        final = route["new_fund_signer"] if is_new_fund else route["update_signer"]
        blank = {"", "N/A", "None"}
        steps = [f"Program manager: **{pm}**" if pm not in blank else "Program manager: not required",
                 f"Fiscal: **{fm}**" if fm not in blank else None,
                 f"Final: **{final or 'School Budget'}**"]
        st.caption("Who signs (" + route["description"] + " funds) — " + " → ".join(s for s in steps if s))
    else:
        st.caption("No approval route on file for this fund family — ask the School Budget Bureau.")

# ─── Lines to check ───────────────────────────────────────────────────
st.markdown("#### Lines to check")

# Widgets remember their contents by `key`. Putting a counter in the key means
# "Clear" only has to bump the counter: new key = brand-new, empty widgets.
if "clear_count" not in st.session_state:
    st.session_state.clear_count = 0
suffix = f"{fund}_{st.session_state.clear_count}"

head = st.columns([3, 1])
mode = head[0].segmented_control("How do you want to enter lines?", ["Paste", "Type"], default="Paste",
                                 label_visibility="collapsed")
if head[1].button("Clear", width="stretch"):
    st.session_state.clear_count += 1
    st.rerun()

if mode == "Type":
    st.caption("One row per line. Leave program and job class blank for 0000.")
    blank = pd.DataFrame({"function": [""] * 3, "object": [""] * 3, "program": [""] * 3, "job_class": [""] * 3})
    edited = st.data_editor(
        blank,
        num_rows="dynamic",            # users can add and delete rows
        hide_index=True,
        width="stretch",
        key=f"editor_{suffix}",
        column_config={
            "function": st.column_config.TextColumn("Function"),
            "object": st.column_config.TextColumn("Object"),
            "program": st.column_config.TextColumn("Program"),
            "job_class": st.column_config.TextColumn("Job class"),
        },
    )
    # Clean up what was typed: trim spaces, drop empty rows, restore leading
    # zeros ("0" → "0000") and fill blanks with 0000.
    req = edited.fillna("").astype(str).apply(lambda s: s.str.strip())
    req = req[(req.function != "") | (req.object != "")].copy()
    req["function"] = req.function.str.zfill(4)
    req["program"] = req.program.replace("", "0000").str.zfill(4)
    req["job_class"] = req.job_class.replace("", "0000").str.zfill(4)
    req.insert(0, "fund", fund)
else:
    pasted = st.text_area(
        "Paste lines",
        key=f"paste_{suffix}",
        height=180,
        label_visibility="collapsed",
        placeholder="One line per row, copied from Excel or typed. With or without the fund. For example:\n"
                    "2200.53330\n"
                    "2100  51300  0000  1211\n"
                    f"{fund}  1000  51100  1010  1610",
    )
    st.caption("Order: function, object, program, job class. Program and job class are optional. "
               "A leading fund number is fine.")
    req, unreadable = re_.parse_pasted_lines(pasted or "")
    if unreadable:
        st.warning(f"Could not read {len(unreadable)} row(s): " + "; ".join(f"`{u[:40]}`" for u in unreadable[:5]))
    other = req[(req.fund != "") & (req.fund != fund)]
    if len(other):
        st.warning(f"Skipped {len(other)} row(s) for a different fund ({', '.join(sorted(other.fund.unique()))}). "
                   f"You are checking fund {fund}.")
        req = req.drop(other.index)
    req = req.assign(fund=fund)

if req.empty:
    st.stop()
req = req[re_.LINE_FIELDS].drop_duplicates().reset_index(drop=True)

# ─── Run the checks ───────────────────────────────────────────────────
findings = pd.concat([
    re_.builtin_checks(req, look, all_lines),
    re_.check_lines(req, rules),
], ignore_index=True)


def name_of(dim, code):
    t = look[dim]
    return t.at[code, "Name"] if code in t.index else "?"


rows = []
for idx, r in req.iterrows():
    f = findings[findings.line == idx]
    status = re_.worst(f.severity)
    if status in ("ok", "question") and (f.rule_id == "B010").any():
        status = "open"
    rows.append({
        "Result": STATUS_TEXT[status],
        "Line": f"{r.function}.{r.object}.{r.program}.{r.job_class}",
        "Function": name_of("function", r.function),
        "Object": name_of("object", r.object),
        "Issues": int(f.severity.isin(["error", "warning"]).sum()),
        "Questions": int((f.severity == "question").sum()),
        "_status": status,
    })
summary = pd.DataFrame(rows)

st.markdown("#### Results")
counts = summary._status.value_counts()
m = st.columns(5)
m[0].metric("Needs a change", int(counts.get("error", 0)))
m[1].metric("Needs review", int(counts.get("warning", 0)))
m[2].metric("Needs an answer", int(counts.get("question", 0)))
m[3].metric("No issues found", int(counts.get("ok", 0)))
m[4].metric("Already open", int(counts.get("open", 0)))
st.dataframe(summary.drop(columns="_status"), hide_index=True, width="stretch")

# ─── Questions, grouped ───────────────────────────────────────────────
# Many lines usually raise the same question, so show each question once with
# the lines it covers. Lines already open on the fund are left out.
open_idx = set(summary.index[summary._status == "open"])
questions = findings[(findings.severity == "question") & ~findings.line.isin(open_idx)]
question_blocks = []          # also reused for the download below
if len(questions):
    st.markdown("#### Questions to answer in the justification")
    st.caption("The School Budget Bureau will ask these before it can review the lines. "
               "Answering them on the form saves a round of email.")
    for rid, g in questions.groupby("rule_id", sort=False):
        first = g.iloc[0]
        line_list = [f"{fund}.{summary.at[i, 'Line']}" for i in g.line]
        question_blocks.append((first, line_list))
        with st.container(border=True):
            st.markdown(f"❓ **{first.ask}**")
            st.markdown(f"Why we ask: {first.title}.")
            if first.alternative:
                st.markdown(f"If not: {first.alternative}")
            st.caption(f"{rid} · Basis: {first.basis} · Applies to {len(line_list)} line(s): "
                       + ", ".join(line_list[:12]) + (" …" if len(line_list) > 12 else ""))

st.markdown("#### Line by line")
for idx, r in req.iterrows():
    f = findings[findings.line == idx].copy()
    if f.empty:
        continue
    f["_o"] = f.severity.map(re_.SEVERITY_ORDER)
    f = f.sort_values("_o")
    status = summary.at[idx, "_status"]
    with st.expander(f"{summary.at[idx, 'Result']} · {fund}.{summary.at[idx, 'Line']} — "
                     f"{summary.at[idx, 'Function']} / {summary.at[idx, 'Object']}",
                     expanded=status in ("error", "warning")):
        for _, x in f.iterrows():
            st.markdown(f"{ICON[x.severity]} **{x.title}**")
            extra = [f"Question: {x.ask}"] if x.ask else []
            if x.alternative:
                extra.append(f"Use instead: {x.alternative}")
            if x.example:
                extra.append(f"Example: {x.example}")
            if extra:
                st.markdown("  \n".join(extra))
            st.caption(f"{x.rule_id} · Basis: {x.basis}")

st.caption("✅ means no rule was broken — not that the line is approved. Allowability under the "
           "grant is the program manager's call; coding is the School Budget Bureau's.")

# ─── Download the review ──────────────────────────────────────────────
md = [f"# Chart line pre-check — fund {fund}", "",
      f"- Date: {date.today():%B %d, %Y}",
      f"- Fund: {fund} — {'new fund' if is_new_fund else funds.at[fund, 'Name']}",
      f"- Lines checked: {len(req)}", "",
      "| Result | Line | Function | Object |", "|---|---|---|---|"]
md += [f"| {s.Result} | {fund}.{s.Line} | {s.Function} | {s.Object} |" for s in summary.itertuples()]
md.append("")
if question_blocks:
    md += ["## Questions to answer in the justification", ""]
    for first, line_list in question_blocks:
        md += [f"- ❓ **{first.ask}**", f"  - Why: {first.title} ({first.rule_id}; basis: {first.basis})",
               f"  - Lines: {', '.join(line_list)}"]
    md.append("")
for idx, r in req.iterrows():
    f = findings[findings.line == idx]
    if f.empty:
        continue
    md.append(f"## {fund}.{summary.at[idx, 'Line']}")
    for _, x in f.iterrows():
        md.append(f"- {ICON[x.severity]} **{x.title}** ({x.rule_id}; basis: {x.basis})"
                  + (f" — use instead: {x.alternative}" if x.alternative else ""))
    md.append("")
md += ["_Pre-check only. PSAB Supplement 3 is the authoritative guidance; requests go through the "
       "OBMS COA Maintenance Form._"]
st.download_button("Download this pre-check (.md)", "\n".join(md).encode("utf-8"),
                   file_name=f"chart_line_precheck_{fund}.md", mime="text/markdown")
