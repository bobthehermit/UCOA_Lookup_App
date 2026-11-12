"""
pages/3_Coding_rules.py — the SBB coding rules, readable by anyone.

Renders config/rules.yaml. Only the public fields are shown (title, basis,
alternative, example); the internal `note` field stays out of the app.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))          # lets this page import modules from the project folder

import streamlit as st

import rules_engine as re_
from ui_common import setup_page

setup_page("Coding rules")

st.caption(
    "Rules the School Budget Bureau applies when reviewing requests for new chart lines. "
    "They come from PSAB Supplement 3 and from past decisions. **PSAB Supplement 3 is the "
    "authoritative guidance.** Rules apply to new requests; lines already open in OBMS are not affected."
)


@st.cache_data(ttl=3600, show_spinner=False)
def load():
    return re_.active_rules(re_.load_rules(ROOT / "config" / "rules.yaml"))


rules = load()
q = st.text_input("Search rules", placeholder="Code or word, e.g. 53330, stipend, food").strip().lower()

SECTIONS = [
    ("Rules", "Requests that break these are not approved as submitted.",
     lambda r: r["kind"] != "guidance" and r["status"] == "settled"),
    ("Proposed rules", "Under review. Requests that break these get a closer look.",
     lambda r: r["kind"] != "guidance" and r["status"] == "proposed"),
    ("Guidance", "How to choose between codes that look similar.",
     lambda r: r["kind"] == "guidance"),
]

shown = 0
for heading, blurb, keep in SECTIONS:
    group = [r for r in rules if keep(r)]
    if q:
        group = [r for r in group
                 if q in " ".join(str(v) for k, v in r.items() if k != "note").lower()]
    if not group:
        continue
    st.subheader(heading)
    st.caption(blurb)
    for r in group:
        shown += 1
        with st.container(border=True):
            st.markdown(f"**{r['title']}**")
            if r.get("alternative"):
                st.markdown(f"Use instead: {r['alternative']}")
            if r.get("ask"):
                st.markdown(f"We will ask: {r['ask']}")
            if r.get("example"):
                st.markdown(f"Example: {r['example']}")
            st.caption(f"{r['id']} · Basis: {r.get('basis', '—')}")

if not shown:
    st.info("No rules match that search.")
