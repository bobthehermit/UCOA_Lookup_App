"""
audit_rules.py — run every rule in config/rules.yaml across ALL lines open in OBMS.

    python audit_rules.py

Reads   data/chart_lines.parquet  (from build_chart_lines.py)
Writes  data/_rules_audit.md

Existing lines are grandfathered: this report is for awareness ("where is the
chart looser than our rules?"), not a removal list. It is also a quick way to
test a new rule before settling it — add it as `proposed`, run this, and see
how much of the existing chart it would touch.

Guidance rules are skipped: they are advice, not something a line can break.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

import rules_engine as re_

ROOT = Path(__file__).parent
MAX_FUNDS_LISTED = 30


def main() -> None:
    lines = pd.read_parquet(ROOT / "data" / "chart_lines.parquet").astype(str)
    lines = lines[lines.account_type == "Expenditure"].reset_index(drop=True)
    rules = [r for r in re_.active_rules(re_.load_rules(ROOT / "config" / "rules.yaml"))
             if r["kind"] in ("forbid", "require")]
    n_funds = lines.fund.nunique()

    out = [
        f"# Rules audit — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Every `forbid` / `require` rule checked against the {len(lines):,} expenditure lines "
        f"open on {n_funds} funds. **Existing lines are grandfathered** — this shows where the "
        "chart is looser than the rules, so we don't widen it further.",
        "",
        "| Rule | Status | Existing lines | Funds | Title |",
        "|---|---|---:|---:|---|",
    ]
    details = []
    for r in rules:
        hit = lines[re_.violations(lines, r)]
        funds = sorted(hit.fund.unique())
        out.append(f"| {r['id']} | {r['status']} | {len(hit):,} | {len(funds)} | {r['title']} |")
        if hit.empty:
            continue
        # Which function.object(.program) combinations account for the hits?
        show_prog = "program" in r["when"]
        cols = ["function", "object"] + (["program"] if show_prog else [])
        combos = (hit.groupby(cols).fund.nunique().sort_values(ascending=False).head(15))
        details += [f"## {r['id']} — {r['title']}", "",
                    f"{len(hit):,} existing lines on {len(funds)} funds. Basis: {r.get('basis', '')}", "",
                    "| " + " | ".join(c.title() for c in cols) + " | Funds |",
                    "|" + "---|" * len(cols) + "---:|"]
        details += ["| " + " | ".join(k if isinstance(k, tuple) else (k,)) + f" | {v} |" for k, v in combos.items()]
        listed = ", ".join(funds[:MAX_FUNDS_LISTED]) + (f" … (+{len(funds) - MAX_FUNDS_LISTED} more)"
                                                        if len(funds) > MAX_FUNDS_LISTED else "")
        details += ["", f"Funds: {listed}", ""]

    path = ROOT / "data" / "_rules_audit.md"
    path.write_text("\n".join(out + [""] + details), encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
