#!/usr/bin/env python3
"""
psab_extract.py — turn PSAB Supplement 3 (the UCOA manual PDF) into one table per dimension.
NM PED School Budget Bureau

    python psab_extract.py Supplement-3-April-2026.pdf --out ./psab

WHAT IT WRITES (in --out)
-------------------------
    psab_fund.csv, psab_function.csv, psab_object.csv, psab_program.csv, psab_job_class.csv
        Code             the code, as text
        Name             the heading name
        PSABDescription  the description as one plain line of text (search, rules, diffs)
        PSABHtml         the same description with the manual's formatting: paragraphs,
                         numbered and roman-numeral lists, bold, italics, footnotes
        Page             page of the PDF where the definition starts
        NCES             "Yes" if the manual marks the code as required for NCES reporting
                         (asterisk on the heading, or listed under NCES REQUIRED REPORTING CODES)
        Optional         "Yes" for the optional, more detailed codes that roll up to a parent
        ParentCode       the code this one is listed under (optional sub-functions, sub-funds)
        Section          the manual section it sits in ("Balance Sheet Objects: Assets", ...)
    _psab_coverage.md
        Proof that every line of the manual was accounted for. Read it after every run.

HOW IT WORKS (version 2, 2026-11-14)
------------------------------------
Version 1 flattened the PDF to plain text and guessed where each code started and stopped.
That is how Program 9000 picked up a table and Function 5000 picked up the next section.

Version 2 never flattens. It reads the PDF line by line and keeps, for every line:
    the page, the left edge (indent), the font size, and which characters are bold or italic.
Those properties are how a person tells a heading from body text, so the script uses them too:

    1. read_lines()   PDF  -> lines with page / indent / size / bold / italic
    2. classify()     walk the lines once, top to bottom, and give EVERY line exactly one role:
                        footer, chapter title, section title, intro text, index entry,
                        group header, heading (starts a code), description (belongs to a code),
                        footnote
                      A section title ("OVERVIEW", "NCES REQUIRED REPORTING CODES") closes the
                      code before it, so text can no longer leak across sections.
    3. render()       each code's description lines -> HTML (lists, bold) and plain text
    4. coverage       count the roles; list anything suspicious; compare with the last run

The heading rules, in plain words
---------------------------------
A line starts a code when it begins with a number of the right length for the chapter
(5 digits for funds and objects, 4 for the rest) AND that number is styled as a heading:
bold, italic, or 12-point. A number in ordinary body text ("use 53330 for ...") is not.

    index entry   a bold code + name, indented, with no sentence after it. These are the
                  stacked lists (chapter overviews, NCES lists, sub-funds). Never a definition.
    group header  an italic code + name inside OPTIONAL NCES FUNCTION CODES. It names the
                  parent that the optional codes below it roll up to.
    heading       everything else that passes the test above. The NAME is the bold part
                  (or the whole line for an all-capitals heading); the rest is description.
"""

from __future__ import annotations

import argparse
import html
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

# ─── What the manual looks like ───────────────────────────────────────
# Chapter titles are 14-point bold and start with a roman numeral.
CHAPTERS = {"IV.": "Fund", "V.": "Function", "VI.": "Object", "VII.": "Program",
            "VIII.": None, "IX.": "Job Class"}          # None = chapter with no codes (Locations)
CODE_LEN = {"Fund": 5, "Function": 4, "Object": 5, "Program": 4, "Job Class": 4}

FOOTER = re.compile(r"^Updated \w+ \d{4} Page \d+ of \d+$")
CODE_AT_START = re.compile(r"^(\d{4,5})(\*?)\s+(\S.*)$")
INDEX_INDENT = (62, 80)          # left edge (points) of the stacked index lists
ABBREVIATIONS = {"ed", "cap", "assoc", "supt", "bus", "mgr", "no", "dept", "e.g", "i.e",
                 "etc", "st", "fin", "vs", "u.s", "inc", "approx"}
USAGE_PAREN = re.compile(r"\s*(\((?:used|only)\b.*)$", re.IGNORECASE)

# List markers at the start of a description line.
NUM_ITEM = re.compile(r"^(\d{1,2})\.\s+(?=\S)")
ROMAN_ITEM = re.compile(r"^((?:x{0,2})(?:ix|iv|v?i{0,3}))\.\s+(?=\S)")
BULLET_ITEM = re.compile(r"^[•·▪■]\s+(?=\S)")


@dataclass
class Line:
    page: int
    x0: float                    # left edge
    x1: float                    # right edge
    top: float
    bottom: float
    size: float                  # font size of most characters
    text: str                    # plain text, superscript footnote marks removed
    spans: list                  # [(text, bold, italic)] — the same text, cut where style changes
    all_bold: bool
    all_italic: bool
    starts_bold: bool
    ends_bold: bool
    marks: str = ""              # footnote numbers found as superscripts on this line
    role: str = ""               # filled in by classify()
    code: str = ""               # the code this line belongs to (heading / desc / footnote)
    dim: str = ""


@dataclass
class Entry:
    dim: str
    code: str
    name: str
    page: int
    section: str
    nces: bool = False
    optional: bool = False
    parent: str = ""
    lines: list = field(default_factory=list)       # description Line objects, in order
    footnotes: list = field(default_factory=list)   # footnote Line objects
    first: list = field(default_factory=list)       # spans left on the heading line after the name
    index_only: bool = False                        # seen only in a list, never defined


# ─── 1. Read the PDF ──────────────────────────────────────────────────

def read_lines(path: str | Path) -> list[Line]:
    """Every text line in the PDF, with its position and styling."""
    import pdfplumber

    out: list[Line] = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            for raw in page.extract_text_lines(return_chars=True):
                chars = [c for c in raw["chars"] if c["text"].strip()]
                if not chars:
                    continue
                # A character's style, read from the PDF itself:
                #   bold    the font name contains "Bold"
                #   italic  the text matrix is slanted (this PDF fakes italics by skewing)
                #   super   much smaller than body text (footnote marks)
                # matrix[3] is the true font height; matrix[2] is the slant.
                styles = [("Bold" in c["fontname"], abs(c["matrix"][2]) > 0.5, c["matrix"][3] < 7.5)
                          for c in chars]
                # pdfplumber already rebuilt the spacing in raw["text"]. Walk that text and hand
                # each visible character its style, in order.
                spans: list[list] = []
                it = iter(zip(chars, styles))
                current = (False, False, False)
                ok = True
                seen_normal = False                      # small text at the START of a line is not
                marks = ""                               # a footnote mark (it is a list number)
                for ch in raw["text"]:
                    if ch.isspace():
                        if spans:
                            spans[-1][0] += ch           # a space keeps the style before it
                        continue
                    try:
                        c, current = next(it)
                    except StopIteration:
                        ok = False
                        break
                    if current[2] and seen_normal and ch.isdigit():
                        marks += ch                      # superscript footnote mark: remember, drop
                        continue
                    seen_normal = seen_normal or not current[2]
                    key = current[:2]
                    if spans and spans[-1][1] == key:
                        spans[-1][0] += ch
                    else:
                        spans.append([ch, key])
                if not ok or not spans:                  # fallback: no styling for this line
                    spans = [[raw["text"], (False, False)]]
                text = re.sub(r"\s+", " ", "".join(s for s, _ in spans)).strip()
                if not text:
                    continue
                body = [s for s in styles if not s[2]] or styles
                out.append(Line(
                    page=page_no, x0=round(chars[0]["x0"], 1), x1=round(chars[-1]["x1"], 1),
                    top=round(raw["top"], 1), bottom=round(raw["bottom"], 1),
                    size=round(statistics.median(c["matrix"][3] for c in chars), 1),
                    text=text, spans=[(s, k[0], k[1]) for s, k in spans],
                    all_bold=all(s[0] for s in body), all_italic=all(s[1] for s in body),
                    starts_bold=body[0][0], ends_bold=body[-1][0], marks=marks,
                ))
    return out


# ─── 2. Give every line a role ────────────────────────────────────────

def _sentence_end(text: str) -> int:
    """Index of the first period that ends a sentence (not an abbreviation), or -1."""
    for m in re.finditer(r"\.(?=\s|$)", text):
        before = re.search(r"([A-Za-z.]+)$", text[:m.start()])
        word = before.group(1).lower() if before else ""
        if word in ABBREVIATIONS:
            continue
        if text[:m.start()].count("(") > text[:m.start()].count(")"):
            continue                                     # still inside a parenthesis
        return m.start()
    return -1


def _drop_chars(spans, n: int):
    """The styled spans with their first n characters removed."""
    out = []
    for s, b, i in spans:
        if n >= len(s):
            n -= len(s)
            continue
        out.append((s[n:], b, i))
        n = 0
    return out


def _drop_lead(spans):
    """Remove the period, colon or dash (and spaces) that separate a heading's name from its
    text: "Name. Text", "Name: Text", "Name – Text"."""
    text = "".join(s for s, _, _ in spans)
    return _drop_chars(spans, len(text) - len(text.lstrip(" .:–—-")))


def _is_title(line: Line) -> bool:
    """A section title: 12-point bold or all-italic capitals, with no code in front."""
    if CODE_AT_START.match(line.text):
        return False
    letters = [c for c in line.text if c.isalpha()]
    if len(letters) < 4 or not all(c.isupper() for c in letters):
        return False
    return (line.size >= 11.5 and line.all_bold) or line.all_italic


def classify(lines: list[Line]) -> tuple[dict[tuple[str, str], Entry], list[dict]]:
    """
    One pass over the document. Sets line.role / line.code on every line and returns
    the entries (codes) found, plus the list of non-code blocks for the coverage report.
    """
    entries: dict[tuple[str, str], Entry] = {}
    order: list[Entry] = []
    blocks: list[dict] = []                   # intro / section text, for the coverage report

    dim: str | None = None                    # current chapter's dimension
    in_body = False                           # False until the first real chapter title
    major = minor = ""                        # current section titles
    mode = "defs"                             # defs | intro | nces | optional
    current: Entry | None = None              # the code whose description is open
    group_parent = ""                         # optional section: code of the italic group header
    name_open = False                         # heading name continues on the next line
    prev: Line | None = None
    footnote_lines: list[tuple[Line, Entry | None]] = []
    mark_owner: dict[tuple[int, str], Entry] = {}     # (page, footnote number) -> code with the mark

    def note_block(line: Line, kind: str):
        if blocks and blocks[-1]["kind"] == kind and blocks[-1]["dim"] == (dim or "") \
                and blocks[-1]["section"] == (minor or major):
            blocks[-1]["n"] += 1
            blocks[-1]["end"] = line.page
        else:
            blocks.append({"kind": kind, "dim": dim or "", "section": minor or major,
                           "page": line.page, "end": line.page, "n": 1, "first": line.text[:90]})

    for line in lines:
        line.dim = dim or ""

        if FOOTER.match(line.text):
            line.role = "footer"
            continue

        # Chapter title: 14-point bold, starts with a roman numeral.
        if line.size >= 13.5 and line.all_bold:
            first = line.text.split()[0]
            if first in CHAPTERS or re.fullmatch(r"[IVX]+\.", first):
                in_body = True
                dim = CHAPTERS.get(first)
                line.role, line.dim = "chapter", dim or ""
                major = minor = ""
                mode, current, group_parent, name_open = "defs", None, "", False
                prev = line
                continue
        if not in_body or dim is None:
            line.role = "front matter" if not in_body else "other chapter"
            continue

        # Footnotes are 8-point. They belong to the code being described on that page.
        if line.size <= 8.4:
            line.role = "footnote"
            line.code = current.code if current is not None else ""
            footnote_lines.append((line, current))
            continue

        # Section titles close whatever code was open.
        if _is_title(line):
            line.role = "section"
            title = line.text.strip()
            up = title.upper()
            # "OVERVIEW" is not a section of codes, so it never becomes a section label.
            if line.size >= 11.5:
                major, minor = ("" if up == "OVERVIEW" else title), ""
            elif up != "OVERVIEW":
                minor = title
            if "NCES REQUIRED" in up:
                mode = "nces"
            elif "OPTIONAL" in up:
                mode = "optional"
            elif up == "OVERVIEW":
                mode = "intro"
            else:
                mode = "defs"
            current, group_parent, name_open = None, "", False
            prev = line
            continue

        m = CODE_AT_START.match(line.text)
        styled = line.starts_bold or line.all_italic or line.size >= 11.5
        right_len = bool(m) and len(m.group(1)) == CODE_LEN[dim]
        # A bold number that simply continues a bold sentence from the line above is not a
        # heading ("...Use / 53330 for any expenditures..."): headings start with a capital.
        looks_like_name = bool(m) and bool(re.match(r"[A-Z(“\"]", m.group(3)))
        continues_bold = (prev is not None and prev.role in ("desc", "heading") and prev.ends_bold
                          and line.all_bold and not _sentence_end(prev.text) == len(prev.text) - 1
                          and not prev.text.rstrip().endswith((".", ":", ")")))

        if m and styled and right_len and looks_like_name and not continues_bold:
            code, star, rest = m.group(1), m.group(2), m.group(3)
            key = (dim, code)
            no_sentence = _sentence_end(rest) < 0 and not rest.rstrip().endswith(".")
            indented = INDEX_INDENT[0] <= line.x0 <= INDEX_INDENT[1]

            # ── index entry: a stacked list item, never a definition ──
            if mode == "nces" or (indented and no_sentence and (line.all_bold or mode == "intro")):
                line.role, line.code = "index", code
                e = entries.get(key)
                if e is None:
                    e = Entry(dim, code, rest.strip(), line.page, minor or major, index_only=True)
                    entries[key] = e
                    order.append(e)
                if mode == "nces":
                    e.nces = True
                elif current is not None and e.index_only and not e.parent and e is not current:
                    e.parent = current.code          # e.g. sub-fund listed under its fund type
                if current is not None and mode != "nces":
                    current.lines.append(line)       # the list is part of that definition's text
                name_open = False
                prev = line
                continue

            # ── group header in the optional section ──
            if mode == "optional" and line.all_italic:
                line.role, line.code = "group", code
                group_parent = code
                current, name_open = None, False
                prev = line
                continue

            # ── a real heading: open this code ──
            caps_style = line.size >= 11.5 or line.all_italic
            if caps_style:
                name, first_spans, name_open = rest, [], False
            else:
                # The name is the leading bold run. Find where bold stops on this line.
                bold_text, after = "", []
                seen_plain = False
                for s, b, i in line.spans:
                    if b and not seen_plain:
                        bold_text += s
                    else:
                        seen_plain = True
                        after.append((s, b, i))
                bold_rest = CODE_AT_START.match(re.sub(r"\s+", " ", bold_text).strip())
                bold_rest = bold_rest.group(3) if bold_rest else rest
                if after:                                   # bold name, then normal text
                    name, first_spans, name_open = bold_rest, after, False
                    tail = "".join(t for t, _, _ in after)
                    # "Printing, Publishing" + ", and Duplicating Services. Activities ...":
                    # the bold stopped early. If the plain text picks up mid-phrase (comma,
                    # dash, lowercase word), the name runs on to the end of that sentence.
                    if re.match(r"\s*(?:[,/&–-]|[a-z])", tail):
                        cut = _sentence_end(tail)
                        if cut >= 0:
                            name = (bold_rest.rstrip() + ("" if tail[:1] in ",/" else " ")
                                    + tail[:cut].strip()).replace(" ,", ",")
                            first_spans = _drop_chars(after, cut + 1)
                    first_spans = _drop_lead(first_spans)
                else:                                       # the whole line is bold
                    cut = _sentence_end(bold_rest)
                    if 0 <= cut < len(bold_rest.rstrip()) - 1:   # "Name. Bold description..."
                        name = bold_rest[:cut]
                        first_spans = [(bold_rest[cut + 1:], True, False)]
                        name_open = False
                    else:
                        name, first_spans = bold_rest, []
                        # No period yet: the name may wrap onto the next line (1115).
                        name_open = cut < 0
            pm = USAGE_PAREN.search(name)                    # "(Used only in Function 2900)"
            if pm and not caps_style:
                first_spans = [(pm.group(1) + " ", False, False)] + first_spans
                name = name[:pm.start()]
            name = name.strip().rstrip(".:").strip()

            old = entries.get(key)
            e = Entry(dim, code, name, line.page, minor or major)
            e.nces = bool(star) or (old.nces if old else False)
            if mode == "optional":
                e.optional, e.parent = True, group_parent
            elif old is not None and old.parent:
                e.parent = old.parent
            e.first = first_spans
            if old is not None and not old.index_only:
                e.duplicate_of = old                         # keep for the coverage report
            entries[key] = e
            if old is not None and old in order:
                order[order.index(old)] = e
            else:
                order.append(e)
            current = e
            line.role, line.code = "heading", code
            for mk in line.marks:
                mark_owner[(line.page, mk)] = e
            prev = line
            continue

        # ── not a heading ──
        if current is not None and name_open and line.starts_bold:
            # The heading's name wrapped onto this line: bold part joins the name.
            bold_text, after, seen_plain = "", [], False
            for s, b, i in line.spans:
                if b and not seen_plain:
                    bold_text += s
                else:
                    seen_plain = True
                    after.append((s, b, i))
            current.name = (current.name + " " + bold_text.strip()).strip().rstrip(".:").strip()
            current.first = _drop_lead(after)
            name_open = not after and _sentence_end(bold_text) < 0
            line.role, line.code = "heading", current.code
            prev = line
            continue
        name_open = False

        if current is not None and mode != "nces":
            line.role, line.code = "desc", current.code
            current.lines.append(line)
            for mk in line.marks:
                mark_owner[(line.page, mk)] = current
        else:
            line.role = "intro"
            note_block(line, "intro")
        prev = line

    # Footnotes: a footnote belongs to the code whose text carries its number as a
    # superscript on the same page. If no mark is found, to the code open at that point.
    owner: Entry | None = None
    for line, open_entry in footnote_lines:
        m = re.match(r"^(\d)\s", line.text)
        if m:
            owner = mark_owner.get((line.page, m.group(1)), open_entry)
        elif owner is None:
            owner = open_entry
        if owner is not None:
            owner.footnotes.append(line)
            line.code = owner.code

    return entries, blocks


# ─── 3. Render a description ──────────────────────────────────────────

def _spans_html(spans) -> str:
    out = []
    for s, b, i in spans:
        t = html.escape(s)
        if not t.strip():
            out.append(t)
            continue
        if i:
            t = f"<em>{t}</em>"
        if b:
            t = f"<strong>{t}</strong>"
        out.append(t)
    return "".join(out)


def _tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    # stray space inside a hyphenated word ("roll- up"), but keep "research- or evidence-based"
    text = re.sub(r"(?<=[A-Za-z])- (?!(?:or|and|to)\b)(?=[a-z])", "-", text)
    text = re.sub(r"\b(Co|Non|Sub|Pre)- (?=[A-Z])", r"\1-", text)
    return text


def _join_html(parts: list[str]) -> str:
    """Join line fragments with a space, rejoining words hyphenated across a line break."""
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not out:
            out = p
        elif re.search(r"[A-Za-z]-$", re.sub(r"<[^>]+>", "", out)) and re.match(r"(?:<[^>]+>)*[a-z]", p):
            out += p
        else:
            out += " " + p
    out = re.sub(r"</strong>(\s*)<strong>", r"\1", out)          # merge neighbouring bold runs
    out = re.sub(r"</em>(\s*)<em>", r"\1", out)
    out = re.sub(r"(?<=[A-Za-z])- (?!(?:or|and|to)\b)(?=[a-z])", "-", out)
    out = re.sub(r"\b(Co|Non|Sub|Pre)- (?=[A-Z])", r"\1-", out)
    return re.sub(r"\s+([.,;:])", r"\1", out)


def render(e: Entry) -> tuple[str, str]:
    """
    Build (plain text, HTML) for one code.

    The description is cut into blocks: paragraphs and list items. A line starts a new block
    when it begins with a list marker (1.  ii.  •), when it is an index entry (a listed code),
    or when the line before it ended early (a short last line of a paragraph) and this one
    does not continue an open list item.
    """
    blocks: list[dict] = []          # {kind: p|num|roman|bullet|code, marker, parts:[html], text:[str]}

    def start(kind, marker="", html_part="", text_part=""):
        blocks.append({"kind": kind, "marker": marker, "parts": [html_part], "text": [text_part]})

    if e.first and "".join(s for s, _, _ in e.first).strip():
        start("p", "", _spans_html(e.first), "".join(s for s, _, _ in e.first))

    right = max((l.x1 for l in e.lines), default=0)
    prev: Line | None = None
    item_indent = None               # left edge of the text of the open list item
    for line in e.lines:
        text = line.text
        spans = list(line.spans)

        def strip_marker(n: int):
            """Remove the first n characters (the list marker) from the styled spans."""
            nonlocal spans
            left, out = n, []
            for s, b, i in spans:
                if left >= len(s):
                    left -= len(s)
                    continue
                out.append((s[left:], b, i))
                left = 0
            spans = out

        if line.role == "index":
            m = CODE_AT_START.match(text)
            start("code", m.group(1), html.escape(m.group(3)), f"{m.group(1)} {m.group(3)}")
            item_indent = None
        elif (m := NUM_ITEM.match(text)):
            strip_marker(m.end())
            start("num", m.group(1), _spans_html(spans), text)
            item_indent = line.x0 + 10
        elif (m := ROMAN_ITEM.match(text)) and m.group(1):
            strip_marker(m.end())
            start("roman", m.group(1), _spans_html(spans), text)
            item_indent = line.x0 + 10
        elif (m := BULLET_ITEM.match(text)):
            strip_marker(m.end())
            start("bullet", "", _spans_html(spans), text)
            item_indent = line.x0 + 10
        else:
            new_para = False
            if not blocks:
                new_para = True
            elif blocks[-1]["kind"] == "code":
                new_para = True
            elif blocks[-1]["kind"] in ("num", "roman", "bullet"):
                # Still inside the item if this line is indented at least as far as its text.
                if item_indent is not None and line.x0 < item_indent - 14:
                    new_para = True
            elif prev is not None and prev.role == "desc":
                short_last = prev.x1 < right - 45 and prev.page == line.page
                ended = prev.text.rstrip().endswith((".", ":", ")", "”"))
                gap = line.page == prev.page and (line.top - prev.bottom) > 5.5
                if (short_last and ended) or gap:
                    new_para = True
            if new_para:
                start("p", "", _spans_html(spans), text)
                item_indent = None
            else:
                blocks[-1]["parts"].append(_spans_html(spans))
                blocks[-1]["text"].append(text)
        prev = line

    # ── HTML: open and close lists as the block kinds change ──
    out, stack = [], []              # stack of open list kinds, outermost first

    def close_to(depth: int):
        while len(stack) > depth:
            out.append("</li></ol>" if stack[-1] != "bullet" and stack[-1] != "code" else "</li></ul>")
            stack.pop()

    for b in blocks:
        body = _join_html(b["parts"])
        kind = b["kind"]
        if kind == "p":
            close_to(0)
            out.append(f"<p>{body}</p>")
            continue
        level = 2 if (kind == "roman" and "num" in stack) else 1
        if kind in ("bullet",) and stack and stack[0] in ("num",):
            level = 2
        if len(stack) >= level and stack[level - 1] != kind:
            close_to(level - 1)
        close_to(level)
        if len(stack) == level:
            out.append("</li>")
        else:
            if kind == "num":
                out.append("<ol>")
            elif kind == "roman":
                out.append('<ol type="i" class="psab-roman">')
            else:
                out.append('<ul class="psab-codes">' if kind == "code" else "<ul>")
            stack.append(kind)
        if kind == "num":
            out.append(f'<li value="{int(b["marker"])}">{body}')
        elif kind == "code":
            out.append(f"<li><strong>{b['marker']}</strong> {body}")
        else:
            out.append(f"<li>{body}")
    close_to(0)

    for num, fn in _footnotes(e):
        out.append(f'<p class="psab-footnote"><sup>{num}</sup> {html.escape(fn)}</p>')

    plain = _tidy(" ".join(" ".join(b["text"]) for b in blocks))
    plain = re.sub(r"(?<=[A-Za-z])-\s(?=[a-z])(?!(?:or|and|to)\b)", "-", plain)
    return plain, "".join(out)


def _footnotes(e: Entry) -> list[tuple[str, str]]:
    """Footnote lines joined back into whole footnotes (a new one starts with its number)."""
    notes: list[list[str]] = []          # [number, text]
    for l in e.footnotes:
        m = re.match(r"^(\d+)\s+(.*)$", l.text)
        if m or not notes:
            notes.append([m.group(1), m.group(2)] if m else ["*", l.text])
        else:
            notes[-1][1] += " " + l.text
    return [(num, _tidy(text)) for num, text in notes]


# ─── 4. Tables, coverage report, comparison ───────────────────────────

COLUMNS = ["Code", "Name", "PSABDescription", "PSABHtml", "Page", "NCES", "Optional",
           "ParentCode", "Section"]


def extract(path: str | Path):
    lines = read_lines(path)
    entries, blocks = classify(lines)
    tables: dict[str, pd.DataFrame] = {}
    for dim in CODE_LEN:
        rows = []
        for (d, code), e in entries.items():
            if d != dim:
                continue
            plain, rich = ("", "") if e.index_only else render(e)
            rows.append({
                "Code": code, "Name": _tidy(e.name), "PSABDescription": plain, "PSABHtml": rich,
                "Page": e.page, "NCES": "Yes" if e.nces else "No",
                "Optional": "Yes" if e.optional else "No", "ParentCode": e.parent,
                "Section": e.section.title().replace("Nces", "NCES") if e.section else "",
            })
        df = pd.DataFrame(rows, columns=COLUMNS)
        tables[dim] = df.sort_values("Code", key=lambda s: s.str.zfill(6)).reset_index(drop=True)
    return tables, lines, entries, blocks


def coverage_report(lines, entries, blocks, tables, source: Path) -> tuple[str, list[str]]:
    """Markdown proof that every line has a role, plus a list of things worth a look."""
    flags: list[str] = []
    roles = Counter((l.dim or "—", l.role) for l in lines)
    no_role = [l for l in lines if not l.role]

    md = [f"# PSAB extraction coverage — {datetime.now():%Y-%m-%d %H:%M}", "",
          f"Source: `{source.name}` · {len(lines):,} text lines · "
          f"**{len(no_role)} lines without a role** (must be 0)", "",
          "## Where every line went", "",
          "| Chapter | heading | description | index entry | group header | section title | "
          "intro text | footnote |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for dim in CODE_LEN:
        md.append(f"| {dim} | " + " | ".join(str(roles.get((dim, r), 0)) for r in
                  ("heading", "desc", "index", "group", "section", "intro", "footnote")) + " |")
    md += ["", f"Not in a code chapter: {roles.get(('—', 'front matter'), 0)} front-matter lines, "
           f"{roles.get(('—', 'other chapter'), 0)} lines in chapters without codes (Introduction, Structure, Locations), "
           f"{sum(v for (d, r), v in roles.items() if r == 'footer')} page footers, "
           f"{sum(v for (d, r), v in roles.items() if r == 'chapter')} chapter titles.", "",
           "## Codes found", "", "| Chapter | Codes | With a description | NCES | Optional |",
           "|---|---:|---:|---:|---:|"]
    for dim, df in tables.items():
        md.append(f"| {dim} | {len(df)} | {(df.PSABDescription.str.len() > 0).sum()} | "
                  f"{(df.NCES == 'Yes').sum()} | {(df.Optional == 'Yes').sum()} |")

    md += ["", "## Text that belongs to no code", "",
           "Chapter overviews and section introductions. Skim the first words: nothing here "
           "should read like the description of a code.", "",
           "| Chapter | Section | Pages | Lines | Starts with |", "|---|---|---|---:|---|"]
    for b in blocks:
        pages = str(b["page"]) if b["page"] == b["end"] else f"{b['page']}–{b['end']}"
        md.append(f"| {b['dim']} | {b['section'].title()} | {pages} | {b['n']} | {b['first']} |")

    # ── things worth a look ──
    for l in lines:
        if l.role == "desc" and re.match(r"^\d{4,5}\*?\s+[A-Z]", l.text) \
                and len(re.match(r"^(\d+)", l.text).group(1)) == CODE_LEN.get(l.dim, 0):
            flags.append(f"{l.dim} {l.code}: a description line starts like a heading "
                         f"(p{l.page}): '{l.text[:70]}'")
    for (dim, code), e in entries.items():
        if getattr(e, "duplicate_of", None) is not None:
            flags.append(f"{dim} {code}: defined twice (p{e.duplicate_of.page} and p{e.page}); "
                         f"kept the later one")
        if len(e.name) > 120:
            flags.append(f"{dim} {code}: very long name — '{e.name[:80]}…'")
        if not e.name:
            flags.append(f"{dim} {code}: empty name")
    md += ["", "## Worth a look", ""] + ([f"- {f}" for f in flags] or ["Nothing flagged."])
    if no_role:
        md += ["", "## Lines without a role", ""] + [f"- p{l.page}: {l.text[:90]}" for l in no_role]
    return "\n".join(md) + "\n", flags


def _norm(s: str) -> str:
    """Compare text ignoring spacing only (so "roll- up" equals "roll-up"). Punctuation counts:
    a stray dash at the start of a description must show up as a change."""
    return re.sub(r"\s+", "", s)


def compare_to_existing(dim: str, new: pd.DataFrame, path: Path) -> list[str]:
    """How the plain descriptions differ from the CSV already at `path` (spacing ignored)."""
    if not path.exists():
        return [f"{dim}: new file"]
    old = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    o = dict(zip(old["Code"], old["PSABDescription"]))
    n = dict(zip(new["Code"], new["PSABDescription"]))
    out = []
    for code in sorted(set(o) | set(n), key=lambda c: c.zfill(6)):
        if code not in n:
            out.append(f"{dim:9s} {code}  REMOVED  (was '{o[code][:50]}')")
        elif code not in o:
            out.append(f"{dim:9s} {code}  ADDED    '{n[code][:60]}'")
        elif _norm(o[code]) != _norm(n[code]):
            a, b = o[code], n[code]
            k = 0
            while k < min(len(a), len(b)) and a[k] == b[k]:
                k += 1
            s = max(0, k - 25)
            lead = "…" if s else ""
            out.append(f"{dim:9s} {code}  was '{lead}{a[s:k + 45]}'  ({len(a)} chars)")
            out.append(f"{'':9s} {'':5s}  now '{lead}{b[s:k + 45]}'  ({len(b)} chars)")
    return out


def main():
    ap = argparse.ArgumentParser(description="Extract UCOA code descriptions from PSAB Supplement 3 (PDF).")
    ap.add_argument("psab_pdf", help="PSAB Supplement 3 as a .pdf")
    ap.add_argument("--out", default="./psab", help="output folder (default ./psab)")
    args = ap.parse_args()

    src = Path(args.psab_pdf)
    if src.suffix.lower() != ".pdf":
        raise SystemExit("Version 2 reads the PDF directly (it needs fonts and positions). "
                         "Pass the .pdf, not a text export.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tables, lines, entries, blocks = extract(src)

    changes = []
    for dim, df in tables.items():
        changes += compare_to_existing(dim, df, out / f"psab_{dim.replace(' ', '_').lower()}.csv")
    for dim, df in tables.items():
        df.to_csv(out / f"psab_{dim.replace(' ', '_').lower()}.csv", index=False, encoding="utf-8-sig")
        print(f"{dim:10s}: {len(df):4d} codes, {(df.PSABDescription.str.len() > 0).sum():4d} described, "
              f"{(df.NCES == 'Yes').sum():3d} NCES, {(df.Optional == 'Yes').sum():3d} optional")

    report, flags = coverage_report(lines, entries, blocks, tables, src)
    (out / "_psab_coverage.md").write_text(report, encoding="utf-8")
    unassigned = sum(1 for l in lines if not l.role)
    print(f"\nCoverage: {len(lines):,} lines read, {unassigned} without a role "
          f"({'OK' if unassigned == 0 else 'CHECK'}). {len(flags)} item(s) flagged — see "
          f"{out / '_psab_coverage.md'}")

    if changes:
        print(f"\nCHANGES vs the files that were in {out} (spacing ignored):")
        for c in changes:
            print("  " + c)
    else:
        print(f"\nNo description changes vs the files that were in {out}.")
    print(f"\nWrote outputs to {out.resolve()}")


if __name__ == "__main__":
    main()
