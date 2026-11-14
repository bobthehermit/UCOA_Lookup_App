"""
rules_engine.py — reads config/rules.yaml and checks chart lines against it.

No Streamlit in here on purpose: the same functions serve the app pages and the
command-line audit (audit_rules.py), and can be tested on their own.

The core idea: masks
--------------------
A "mask" is a True/False column with one entry per chart line. Checking a rule
is just building masks and combining them:

    when-mask   lines the rule is about           (object == "53330")
    then-mask   lines that satisfy the rule       (function in 2200, 2300, ...)
    violation   when-mask AND NOT then-mask

Because pandas evaluates a mask for the whole table at once, the same code
checks a 3-line request or all 1.5 million existing lines.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

LINE_FIELDS = ["fund", "function", "object", "program", "job_class"]
KINDS = {"forbid", "require", "guidance", "breadth"}
STATUSES = {"settled", "proposed", "retired"}
FINDING_COLS = ["line", "rule_id", "severity", "kind", "title", "basis", "alternative", "example", "ask"]
SEVERITY_ORDER = {"error": 0, "warning": 1, "question": 2, "info": 3}


# ─── Loading ──────────────────────────────────────────────────────────

def load_rules(path: str | Path) -> list[dict]:
    """Read rules.yaml and stop with a clear message if a rule is malformed."""
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rules = doc.get("rules", [])
    seen = set()
    for r in rules:
        rid = r.get("id", "<no id>")
        if rid in seen:
            raise ValueError(f"rules.yaml: duplicate id {rid}")
        seen.add(rid)
        if r.get("kind") not in KINDS:
            raise ValueError(f"rules.yaml {rid}: kind must be one of {sorted(KINDS)}")
        if r.get("status") not in STATUSES:
            raise ValueError(f"rules.yaml {rid}: status must be one of {sorted(STATUSES)}")
        if not r.get("title") or not isinstance(r.get("when"), dict):
            raise ValueError(f"rules.yaml {rid}: needs a title and a when: block")
        if r["kind"] == "require" and not isinstance(r.get("then"), dict):
            raise ValueError(f"rules.yaml {rid}: kind 'require' needs a then: block")
        for block in ("when", "then"):
            for field, spec in (r.get(block) or {}).items():
                if field == "max_job_classes":
                    continue
                if field not in LINE_FIELDS:
                    raise ValueError(f"rules.yaml {rid}: unknown field '{field}' in {block}")
                for p in (spec if isinstance(spec, list) else [spec]):
                    if not isinstance(p, str):
                        raise ValueError(
                            f"rules.yaml {rid}: {block}.{field} has {p!r} — put codes in quotes "
                            f'(e.g. "0000"), otherwise YAML reads them as numbers')
    return rules


def active_rules(rules: list[dict]) -> list[dict]:
    return [r for r in rules if r["status"] != "retired"]


def severity(rule: dict) -> str:
    if rule["kind"] == "guidance":
        # Guidance with an `ask:` is a question the requester must answer before
        # SBB can judge the line; without one it is just background advice.
        return "question" if rule.get("ask") else "info"
    if rule["kind"] == "breadth":
        return "warning"          # a judgment call for the reviewer, never an automatic no
    return "error" if rule["status"] == "settled" else "warning"


# ─── Matching ─────────────────────────────────────────────────────────

def _one(series: pd.Series, pattern: str) -> pd.Series:
    """Mask for one positive pattern: exact code or 'prefix*'."""
    if pattern.endswith("*"):
        return series.str.startswith(pattern[:-1])
    return series == pattern


def field_mask(series: pd.Series, spec) -> pd.Series:
    """
    Mask for one field's condition.
      positives ("1000", "51*")   → the value must match ANY of them
      negatives ("!0000")         → the value must match NONE of them
    """
    patterns = spec if isinstance(spec, list) else [spec]
    pos = [p for p in patterns if not p.startswith("!")]
    neg = [p[1:] for p in patterns if p.startswith("!")]
    mask = pd.Series(True, index=series.index)
    if pos:
        any_pos = pd.Series(False, index=series.index)
        for p in pos:
            any_pos |= _one(series, p)
        mask &= any_pos
    for p in neg:
        mask &= ~_one(series, p)
    return mask


def cond_mask(df: pd.DataFrame, cond: dict) -> pd.Series:
    """All field conditions in a when:/then: block must hold (AND)."""
    mask = pd.Series(True, index=df.index)
    for field, spec in cond.items():
        if field in LINE_FIELDS:
            mask &= field_mask(df[field], spec)
    return mask


def violations(df: pd.DataFrame, rule: dict) -> pd.Series:
    """Mask of lines that break (or, for guidance, are covered by) one rule."""
    when = cond_mask(df, rule["when"])
    if rule["kind"] in ("forbid", "guidance"):
        return when
    if rule["kind"] == "require":
        return when & ~cond_mask(df, rule["then"])
    if rule["kind"] == "breadth":
        # Count distinct job classes per fund/function/object/program among matching lines.
        limit = int(rule.get("then", {}).get("max_job_classes", 2))
        sub = df[when & (df["job_class"] != "0000")]
        counts = sub.groupby(["fund", "function", "object", "program"])["job_class"].transform("nunique")
        mask = pd.Series(False, index=df.index)
        mask.loc[counts.index] = counts > limit
        return mask
    return pd.Series(False, index=df.index)


# ─── Checking a set of lines ──────────────────────────────────────────

def check_lines(df: pd.DataFrame, rules: list[dict]) -> pd.DataFrame:
    """
    Check every line in df (columns = LINE_FIELDS, all text) against every active rule.
    Returns one row per (line, rule) hit:
        line (df's index label), rule_id, severity, title, basis, alternative, example
    """
    df = df[LINE_FIELDS].astype(str)
    out = []
    for r in active_rules(rules):
        hit = violations(df, r)
        for idx in df.index[hit]:
            out.append({
                "line": idx, "rule_id": r["id"], "severity": severity(r), "kind": r["kind"],
                "title": r["title"], "basis": r.get("basis", ""),
                "alternative": r.get("alternative", ""), "example": r.get("example", ""),
                "ask": r.get("ask", ""),
            })
    return pd.DataFrame(out, columns=FINDING_COLS)


def builtin_checks(df: pd.DataFrame, look: dict[str, pd.DataFrame], open_lines: pd.DataFrame | None) -> pd.DataFrame:
    """
    Checks that come from OBMS settings rather than rules.yaml:
      - every code exists in OBMS (not a books-only code) and is active and postable
      - the line is already open on the fund (→ no request needed)
      - the function/object pair is brand new statewide (→ federal crosswalk check)

    look        {"function": table indexed by Code, "object": ..., ...} from data/ucoa_<dim>.csv
    open_lines  data/chart_lines.parquet as text, or None
    """
    df = df[LINE_FIELDS].astype(str)
    out = []

    def add(idx, rid, sev, title, alt=""):
        out.append({"line": idx, "rule_id": rid, "severity": sev, "kind": "builtin", "title": title,
                    "basis": "OBMS chart of accounts settings", "alternative": alt, "example": "", "ask": ""})

    labels = {"function": "Function", "object": "Object", "program": "Program", "job_class": "Job class"}
    for idx, row in df.iterrows():
        for dim, label in labels.items():
            code, t = row[dim], look[dim]
            if code not in t.index:
                add(idx, "B001", "error", f"{label} {code} is not a code in this year's chart of accounts")
                continue
            rec = t.loc[code]
            if rec.get("Availability", "OBMS") == "Books only":
                # In PSAB Supplement 3 but not in OBMS: optional sub-functions, most
                # balance sheet objects. They can never be opened as an OBMS chart line.
                parent = rec.get("PSABParent", "")
                add(idx, "B004", "error",
                    f"{label} {code} ({rec['Name']}) is a books-only code — OBMS does not carry it",
                    f"Use {parent}, which it rolls up to" if parent else "")
            elif rec.get("Status", "") == "Historical" or rec.get("NotInUse", "") == "Yes":
                add(idx, "B002", "error", f"{label} {code} ({rec['Name']}) is no longer in use")
            elif rec.get("ActualsPostable", "Yes") != "Yes":
                add(idx, "B003", "error",
                    f"{label} {code} ({rec['Name']}) is a roll-up, not a postable code",
                    "Choose one of the detailed codes underneath it")

    if open_lines is not None and len(df):
        keys = LINE_FIELDS
        already = df.reset_index().merge(open_lines[keys].drop_duplicates(), on=keys, how="inner")["index"]
        for idx in already:
            add(idx, "B010", "info", "This line is already open on the fund — no request needed")
        pairs = set(zip(open_lines["function"], open_lines["object"]))
        for idx, row in df.iterrows():
            if (row["function"], row["object"]) not in pairs and row["object"] in look["object"].index \
                    and row["function"] in look["function"].index:
                add(idx, "B011", "warning",
                    f"Function {row['function']} with object {row['object']} is not open on any fund statewide — "
                    "SBB must confirm the PSAB basis and map the new combination in the federal reporting crosswalk")

    return pd.DataFrame(out, columns=FINDING_COLS)


def worst(severities) -> str:
    """Overall status for a line from its findings: error > warning > question > ok."""
    s = set(severities)
    for level in ("error", "warning", "question"):
        if level in s:
            return level
    return "ok"


# ─── Approval route (from the COA Maintenance Form's Workflow tab) ────

def approval_route(fund: str, workflow: pd.DataFrame, fund_table: pd.DataFrame | None = None) -> dict | None:
    """
    Find the Workflow row for a fund. Tries, in order: the fund itself, each
    parent fund above it in OBMS, then the fund family (27579 → 27000).
    `workflow` is config/workflow.csv indexed by fund.
    """
    tried, code = [], fund
    for _ in range(6):
        tried.append(code)
        if code in workflow.index:
            break
        parent = ""
        if fund_table is not None and code in fund_table.index:
            parent = fund_table.at[code, "ParentFundCode"]
        if not parent or parent in tried:
            break
        code = parent
    if code not in workflow.index:
        code = fund[:2] + "000"
    if code not in workflow.index:
        return None
    row = workflow.loc[code].to_dict()
    row["matched_fund"] = code
    # Exceptions named on the Workflow tab: these funds need a PM signature on line updates.
    row["pm_exception"] = fund in {"25111", "27109"}
    return row


# ─── Reading pasted lines ─────────────────────────────────────────────

def parse_pasted_lines(text: str) -> tuple[pd.DataFrame, list[str]]:
    """
    Turn pasted text into chart lines. Accepts what people actually paste:

        2100.53330.0000.0000                      dotted
        27579  2100  53330  0000  1211            copied from Excel (tabs), fund first
        Expenditure,27579,2100,51300,0000,1211    a row from the "Lines on a fund" download
        2200 53330                                function and object only

    How: split each row into cells, skip leading words ("Expenditure"), then take
    the run of number cells. If the first number is 5 digits and the next is 4
    or fewer, the first one is a fund (functions are 4 digits, objects 5).
    Missing program / job class become 0000; short codes get their leading
    zeros back ("0" → "0000").

    Returns (lines, unreadable_rows). `lines` has a `fund` column that is ""
    when the row did not include one.
    """
    rows, bad = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "\t" in line:
            cells = line.split("\t")
        elif "," in line:
            cells = line.split(",")
        else:
            cells = line.replace(".", " ").replace("|", " ").replace("-", " ").split()
        cells = [c.strip().strip('"') for c in cells]
        while cells and not cells[0].isdigit():      # drop leading words
            cells.pop(0)
        nums = []
        for c in cells:                              # take numbers until the first non-number
            if not c.isdigit():
                break
            nums.append(c)
        fund = ""
        if len(nums) >= 3 and len(nums[0]) == 5 and len(nums[1]) <= 4:
            fund, nums = nums[0], nums[1:]
        if len(nums) < 2 or len(nums) > 4:
            if any(ch.isdigit() for ch in line):     # header rows (no digits) are skipped silently
                bad.append(raw.strip())
            continue
        nums += ["0000"] * (4 - len(nums))
        rows.append({"fund": fund, "function": nums[0].zfill(4), "object": nums[1],
                     "program": nums[2].zfill(4), "job_class": nums[3].zfill(4)})
    return pd.DataFrame(rows, columns=LINE_FIELDS), bad
