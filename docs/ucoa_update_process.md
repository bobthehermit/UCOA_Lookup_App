---
title: "UCOA Update Process"
status: Working draft
---

# UCOA Update Process

How the School Budget Bureau (SBB) handles requests to add, deactivate or change UCOA funds and chart lines in OBMS: who decides what, the steps, and what happens when we disagree.

This file lives in the app's repository so every change to the process has a commit behind it. Related files:

| What | Where |
|---|---|
| Coding rules (the single source — do not copy them into this document) | `config/rules.yaml` → *Coding rules* page |
| Who signs, by fund | `config/workflow.csv` (from the Workflow tab of the COA Maintenance Form) |
| Lines open today | `data/chart_lines.parquet` → *Lines on a fund* page |
| Where existing lines are looser than the rules | `data/_rules_audit.md` |
| Official code definitions | PSAB Supplement 3 (April 2026) |

---

## 1. Who decides what

**The program manager decides what is allowable. SBB decides how it is coded.** Keep those two questions separate.

| Party | Role | Decides |
|---|---|---|
| School Business Official (SBO) | Submits the COA Maintenance Form; explains the expense; gives a justification if SBB recommends a different line | What they need to record |
| PED Program Manager (PM) | Confirms the activity is allowable under the grant or statute and describes it in plain terms; signs the PM section | Allowability |
| School Budget Bureau | Owns the UCOA and PSAB Supplement 3; reviews whether requested lines fit what the PM describes; final signature; OBMS administrator builds the change | Correct UCOA lines; final approval |
| Fiscal Grants Management | New flow-through funds (24xxx, 27xxx) and OBMS fiscal role setup | New-fund setup |

Program managers are not asked to pick codes.

## 2. Who signs

The Workflow tab of the COA Maintenance Form is the authority. If this section and the tab disagree, the tab wins and this section gets fixed.

**Line changes on an existing fund**

| Funds | Program-side signer | Final |
|---|---|---|
| 13000 Transportation | Transportation | School Budget |
| 14000 Instructional Materials | Instructional Materials | School Budget |
| 21000 Food Service, 21100 Universal Free Lunch | Student Success | School Budget |
| 24xxx Federal Flow-Through, 27xxx State Flow-Through | PED Program Manager | School Budget |
| 31200, 31400, 31700, 31701, 31703 (capital outlay) | Capital Outlay | School Budget |
| 25111 and 27109 (named exceptions) | PED Program Manager | School Budget |
| Everything else (11000, 12000, 15100, 15200, 22000, 23000, 25xxx, 26xxx, 28xxx, 29xxx, other 31xxx, 32100, 41xxx–43000, 60000) | None | School Budget |

**New funds**

| Funds | Signers |
|---|---|
| 24xxx, 27xxx | PED Program Manager → PED Senior Manager of Fiscal Grants → School Budget |
| All others | School Budget |

The *Check new lines* page shows the signers for any fund.

## 3. Request types

1. **Line changes on an existing fund** (add or deactivate lines). The most common.
2. **New fund.** Needs the law, award or agreement; CFDA number and award dates for federal funds; and either a starting template or a specific line list.
3. **Fund name change or deactivation.**

## 4. Our defaults

- **Start narrow, widen on request.** A new fund gets the lines its purpose needs, not a clone of a wide fund. Every line on a fund is open to every entity that uses the fund.
- **Existing lines are grandfathered.** We do not remove combinations that already exist, and we do not narrow funds that were built wide. Whether a budget or reimbursement on those lines is appropriate is the program manager's review. The rules audit tells us where the chart is already looser than the rules so we do not widen it further.
- **Rules live in one place.** A coding decision that should apply next time is added to `config/rules.yaml` — `proposed` first if it needs confirming, `settled` once it is. Nearly every rule should trace to a PSAB Supplement 3 passage; cite it in `basis`.
- **Every "no" comes with a citation and an alternative.**

## 5. Steps: line changes

1. **Before the form.** The SBO checks *Lines on a fund* (the line may already be open) and runs the lines through *Check new lines*.
2. **Intake.** The SBO submits the form to their assigned budget analyst, who forwards it to SBB's UCOA reviewers. Completeness check: requestor, fund, full lines (fund / function / object / program / job class), written justification, award attached for grant funds. Incomplete → back to the SBO with what is missing.
3. **Route** by fund (section 2). No program-side signer → step 5.
4. **Allowability.** The PM confirms what is allowable and describes the activity plainly: what is being bought or paid for, and for whom.
5. **Code review.** SBB runs the lines through *Check new lines* and reviews:
   - rule findings (errors and warnings) and the PSAB text
   - whether the lines fit what the PM described
   - consistency with lines already on the fund
   - the federal reporting checks in section 7
6. **Decision**, each with a reason:
   - approve as requested
   - approve with a recommended alternate line (cite the PSAB passage)
   - decline (cite the PSAB passage and say what would work)
7. **SBO response**, if we recommended an alternate or declined — section 6.
8. **Sign-off.** Program-side signature where required; Manager, Budget and Finance.
9. **Build and close.** The OBMS administrator makes the change. Notify the SBO, PM and analyst. Log the decision and its reason in the request log. Pull that fund's Chart Line Listing and rebuild so the app shows the new line.

## 6. When the SBO disagrees

- SBB is final on coding; the PM is final on allowability.
- A good justification should be able to change our answer.
- Do not block the SBO's budget work while we discuss it.

1. Our response names the line, the reason, the PSAB passage and the recommended alternative.
2. The SBO may respond (suggested: within 10 business days) with what the expense actually is, why the recommended line does not capture it, and any reporting need behind it (audit finding, federal report, board reporting).
3. Second look by the SBB reviewers. Outcomes: accept and approve the requested line; keep the recommendation and explain why; or approve the recommended line now as an interim so the SBO can keep moving.
4. If it turns out to be an allowability question, it goes back to the PM.
5. Still unresolved → a short call with the SBO, PM and SBB.
6. **Tiebreaker.** Any one of the SBB managers (Senior Manager; Manager, Budget and Finance; peer manager) can break a tie. A contested call goes to all three.
7. Record the decision and reason. If the disagreement exposed an unclear spot in PSAB Supplement 3, note it for the next manual revision, and add or adjust a rule in `config/rules.yaml`.

## 7. Before adding a line: federal reporting checks

Every new combination flows into F-33, NPEFS and SLFS through the crosswalk.

- [ ] **Function category.** 1000 counts as instruction; 2100–2900 are support-services subcategories; 3300 is reported outside K-12 current expenditures.
- [ ] **Object category.** Salaries (51xxx), benefits (52xxx), purchased services, supplies and property each map separately.
- [ ] **Intergovernmental payments.** 55912, 55913 and 55914 only when the counterparty is a district, charter, REC or government agency.
- [ ] **Per-pupil and school-level effects.** Function 1000 raises instructional figures; 3300 is left out of school-level figures.
- [ ] **Revenue side (new funds).** The revenue objects on the fund decide whether the money reports as state or federal.
- [ ] **Crosswalk mapping.** Is the function/object pair mapped? *Check new lines* flags pairs that are not open on any fund statewide — those need a mapping when approved.
- [ ] **Narrowest combination.** Does an existing line already do the job?

## 8. Keeping the data current

| Report (OBMS → Reports → Administrative Reports) | When | Then run |
|---|---|---|
| COA Configuration Report | Existing routine | `python build_ucoa.py "COA Configuration Report.csv"` |
| Chart Line Listing Report, all funds, CSV | Monthly, or after a batch of approved changes | `python build_chart_lines.py "Chart Line Listing Report.csv"` then `python audit_rules.py` |

Review `data/_chart_lines_audit.md` after each build: lines added or removed that do not match a logged request are worth a look. Commit `data/` after every build.

## 9. Open questions

- Turnaround targets for each step.
- Submission path: the form says "submit to your assigned Budget Analyst." Keep, or send straight to the UCOA reviewers?
- Deactivations: confirm no remaining budget or actuals on a line first.
- Timing: mid-year additions vs. effective at the start of the fiscal year.
- Workflow tab cleanup: 31400 has a blank fiscal signer for line updates; 21000 / 21100 list "Student Success" — confirm the office name.
- When a request starts with the PM instead of an SBO, is it the same path minus step 4?
- Program rules R040–R045 (which functions each program may be used with) are `proposed` — confirm against PSAB and settle.
- Who backs up UCOA review.

## Changelog

- **2026-11-12** — Moved into the app repository. Signers now follow the form's Workflow tab. Coding rules moved to `config/rules.yaml`. Added: narrow-by-default, grandfathering of existing lines, tiebreaker, the app pages in the steps, data refresh cadence.
- **2026-10-29** — First draft.
