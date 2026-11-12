"""
ui_common.py — look-and-feel shared by every page of the UCOA app.

Why this file exists
--------------------
Each Streamlit page is its own script. Without a shared module, every page
would need its own copy of the logo code, the brand CSS and the page menu, and
they would drift apart. Pages import from here instead:

    from ui_common import setup_page
    setup_page("Lines open on a fund")

The page menu
-------------
Streamlit's automatic menu names pages after their file names ("ucoa reference").
We turn that menu off (.streamlit/config.toml → showSidebarNavigation = false)
and draw our own with st.page_link, so the labels and order are ours.
To add a page: add one line to PAGES below.
"""

import base64
from io import BytesIO
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
LOGO_PATH = ROOT / "300 DPI NM PED Logo JPEG.jpg"
LOGO_LINK = "https://web.ped.nm.gov/bureaus/school-budget-bureau/"

# (file, menu label, icon, one-line description for the home-page cards)
PAGES = [
    ("ucoa_reference.py",            "Code lookup",       ":material/search:",
     "What a fund, function, object, program or job class code means."),
    ("pages/1_Lines_on_my_fund.py",  "Lines on a fund",   ":material/list_alt:",
     "Which chart lines are already open on a fund."),
    ("pages/2_Check_a_request.py",   "Check new lines",   ":material/fact_check:",
     "Test lines you plan to request against PSAB and SBB coding rules."),
    ("pages/3_Coding_rules.py",      "Coding rules",      ":material/gavel:",
     "The coding rules SBB applies when reviewing line requests."),
]

BRAND_CSS = """
<style>
.block-container { padding-top: 3rem !important; max-width: 1180px; }
h1, h2, h3, h4 { color: #245d62; font-weight: 600; }
.ped-eyebrow { font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
               color: #7a8a86; font-weight: 600; }
.ped-title { font-family: Georgia, "Times New Roman", serif; font-size: 1.6rem;
             color: #245d62; font-weight: 600; margin: .15rem 0 .6rem; line-height: 1.25; }
.ped-rule { display: flex; height: 3px; margin-bottom: 1.3rem; }
.ped-rule .g { width: 46px; background: #edc872; }
.ped-rule .t { flex: 1; background: #245d62; }
.desc-box { background: #f7f6f2; border-left: 3px solid #edc872; padding: 10px 14px;
            border-radius: 0 6px 6px 0; font-size: 13px; color: #3a3a38; line-height: 1.55; }
a { color: #245d62; text-decoration: none; }
a:hover { color: #1a474b; text-decoration: underline; }
.stDownloadButton button { background: #245d62; color: #fff !important; border: none; }
.stDownloadButton button:hover { background: #1a474b; }
.stDownloadButton button p, .stDownloadButton button span { color: #fff !important; }
[data-testid="stExpander"] { border: 0.5px solid #ececec; border-radius: 8px; }
</style>
"""


@st.cache_data(show_spinner=False)
def _logo_html() -> str:
    """The logo as an <img> tag with the picture embedded as text (base64)."""
    try:
        from PIL import Image
        buf = BytesIO()
        Image.open(LOGO_PATH).save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return (f'<a href="{LOGO_LINK}" target="_blank"><img src="data:image/png;base64,{b64}" '
                f'style="max-height:90px;height:auto;max-width:100%"></a>')
    except Exception:
        return ""


def sidebar_nav() -> None:
    """Draw the page menu in the sidebar. Pages whose file is missing are skipped."""
    st.sidebar.markdown("### Tools")
    for path, label, icon, _ in PAGES:
        if (ROOT / path).exists():
            st.sidebar.page_link(path, label=label, icon=icon)
    st.sidebar.divider()


def page_cards(skip: str = "") -> None:
    """A row of link cards (used on the home page to point at the other tools)."""
    items = [p for p in PAGES if p[0] != skip and (ROOT / p[0]).exists()]
    if not items:
        return
    for col, (path, label, icon, blurb) in zip(st.columns(len(items)), items):
        with col.container(border=True):
            st.page_link(path, label=f"**{label}**", icon=icon)
            st.caption(blurb)


def setup_page(title: str, tab_title: str | None = None) -> None:
    """Call first on every extra page: tab title, brand CSS, logo, menu, heading."""
    st.set_page_config(page_title=f"{tab_title or title} · UCOA", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(BRAND_CSS, unsafe_allow_html=True)
    logo = _logo_html()
    if logo:
        st.sidebar.markdown(logo, unsafe_allow_html=True)
    st.sidebar.caption("School Budget Bureau")
    sidebar_nav()
    st.markdown(
        '<div class="ped-eyebrow">New Mexico PED · School Budget Bureau</div>'
        f'<div class="ped-title">{title}</div>'
        '<div class="ped-rule"><span class="g"></span><span class="t"></span></div>',
        unsafe_allow_html=True,
    )
