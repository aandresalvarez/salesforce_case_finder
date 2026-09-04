# Case Finder v2.1 — Proposal and delivery note

**3 September 2026 · for the support team and RIT data stakeholders**

---

## The problem, restated

41,526 support cases and 280,001 conversation messages are in BigQuery. The
answer to "has anyone hit this before?" is usually in there. Getting it out
currently requires three things at once: SQL, the schema, and the knowledge that
the useful text lives in `fct_conversation_turn.body_clean` rather than in the
case subject.

Almost nobody on the support team has all three. So the archive is, in practice,
searchable by a handful of people — and the rest of the team re-solves problems
that were solved in 2023.

## What we propose, and have built

A small desktop application, installed on each person's own laptop, that answers
that question without SQL. It does five things:

1. **Lists** — the triage queues, with the columns the team actually triages on.
2. **Search** — one box, across case fields *and* the conversation bodies.
3. **Case** — a whole case on one page, comments first.
4. **Ask** — plain-English question in, reviewable SQL out.
5. **SQL** — for the people who already know what they want.

This is v2.1: the same data and security model as the delivered v1 Streamlit
tool, with the interface rebuilt as a native desktop app and the operational
triage features (lists, saved views, extended metadata, related cases) that v1
never had.

**Status: complete and verified against the live warehouse.** 472 automated
tests, plus 30 more that run against live BigQuery to check the things a test
double cannot; all seven screens exercised end to end; both installers run
through on a clean path.

---

## The three decisions worth arguing about

### 1. No server. Each laptop talks to BigQuery directly.

The alternative — one hosted instance everybody visits — is the normal shape for
this kind of tool, and we are not building it.

A hosted app needs an application identity, which means a service-account key
that reads PHI on behalf of whoever happens to be pointed at the URL. Access
control becomes something the app implements and we have to get right. Audit
logs say "the app read this case," not "this person read this case."

Running locally under each user's own Google credentials inverts all of that.
BigQuery IAM is the access gate and Case Finder grants nothing: if you cannot
query the dataset today, installing this changes nothing for you. Every query in
the audit log carries a human name. There is no key to distribute, rotate, or
leak, and no infrastructure to operate, patch, or pay for.

The cost is that installation happens 30 times instead of once. That is what the
setup scripts are for, and it is the trade we recommend making.

### 2. No copy of the data. Ever, anywhere, for any reason.

The corpus contains PHI, so the design treats every byte that lands on a disk as
a liability. Results live in a 15-minute in-memory cache with no disk backend —
quitting the app *is* the retention policy. Saved views persist filter
definitions and nothing else: field names, selected values, sort order, visible
columns. Never a row, a body, a snippet, or a description. The CSV export is
metadata only. The Ask feature sends Gemini your question and a static table
layout, and no case content of any kind.

Two things leave the process, both because you asked: **Copy summary** puts a
handoff on your clipboard, and **Export metadata CSV** writes the file you named.
Both are deliberate, visible actions.

### 3. Lean UI: show the work, not the controls.

The earlier concept had a dashboard landing page, a Search button, an Open button
on every row, an Apply Filters button, a persistent Save/Export/Columns toolbar,
five metric cards in the case header, and nested cards throughout.

All of it is gone. You land on a search box, not a dashboard — Open Cases is one
click away in the rail. Enter searches. Rows are clickable. Filters apply as you
set them. Administrative actions live in an overflow menu. The rule the whole UI
is built on is that a screen has at most one primary filled button, and controls
appear only when they are needed.

This is not minimalism for its own sake. It is a triage tool people open thirty
times a day; every control that is present but not needed is a thing to look past
each time. Seven automated acceptance tests (UX-T1 through UX-T7) enforce the
rules so the interface cannot quietly re-accumulate buttons over the next year.

---

## What it costs to run

Nothing to operate — no server, no license, no scheduled job.

Query spend, on BigQuery on-demand pricing at $6.25/TiB:

| Operation | Scanned | Cost |
|---|---:|---:|
| Open the app on Lists | ~5 MB | ~$0.00003 |
| Search, one term, whole conversation | ~245 MB | ~$0.0015 |
| Open a case | ~240 MB | ~$0.0015 |
| Repeat anything within 15 minutes | 0 | free |

A heavy user doing 100 searches and opening 100 cases in a day spends about
**thirty cents**. Every job carries two hard ceilings — 4 GiB scanned and two
minutes of runtime — both enforced by BigQuery rather than by the app. A mistake
is refused before it runs or cancelled while it does, rather than billed after.
Free-form and generated SQL are additionally dry-run and priced before
execution.

Measured latency: opening the app takes ~4.7 s cold and ~0.2 s afterwards; search
~1.5 s; opening a case ~2.7 s cold and instant on return. Cold times are BigQuery
round-trip latency rather than scanning, which is why the pages that need several
independent queries now issue them concurrently.

---

## How it gets to people

Source folder plus a setup script — not a signed binary. No admin rights, no
Apple Developer certificate, no Authenticode signing, no IT ticket.

```bash
./install-mac.sh     # or: powershell -File .\install-windows.ps1
```

The script installs `uv` into the user profile if it is missing, builds the
environment from a locked dependency set, checks for the Google Cloud CLI, offers
to sign the user in, and then runs a self-check that reports whether the desktop
window and BigQuery are *actually* reachable on this machine rather than assuming
they are. Uninstalling is deleting the folder.

Packaging a real `.app` and `.exe` later is possible and would remove the
terminal from the install story. It is not required, and it introduces code
signing, notarisation, and a release pipeline — worth doing when the tool has
proven itself, not before.

---

## Where the stakeholder asks landed

| Ask | Where it is |
|---|---|
| Read-only; no edits back to Salesforce | Enforced in code on every query, including generated SQL |
| Triage list: owner, status, PI, dept, IRB, description, last activity, funding | Default columns on Lists |
| Personal and shared filtered views | Saved views; shared presets in `views.json`, personal ones outside the repo |
| 4–5 priority filters to start | Status, owner, department, date, open-only — with the rest behind disclosure |
| Case detail with IRB, PI, department, comments | Case page; comments is the default tab |
| Don't make people open individual emails | Comments stream is the default; individual messages are a separate tab |
| Search by case number; find related cases | Typing `CASE-…` navigates directly; Related is a tab on every case |
| Default 2022+, older archive optional | Era switch in Settings, defaulting to 2022+ |
| Copyable text for ServiceNow handoff | **Copy summary** on every case |
| macOS and Windows | Both, from one source tree; installers for each |
| No attachment migration — use Box | Files tab lists pointers and says so |
| Column sorting and filtering | Both, on Lists |
| Warehouse freshness surfaced honestly | A banner appears when the snapshot is over a week old |

---

## Open questions

**1. What is a "Data Broker" case?** (SR-13)

This is the one requirement we could not close from the data. "Data Broker"
appears nowhere in the warehouse — not as a status, not as an owner, not as a
queue name. The shipped **Data Broker Triage** preset is a placeholder filtering
on `status = 'Data Queue'`, which currently matches 3 open cases, and it is
labelled provisional in the app. Someone who knows the operational meaning needs
to tell us what the real filter is; changing it is a one-line edit to
`views.json` and needs no release.

**2. Which of the legacy Salesforce filters actually matter?** (SR-4)

We shipped the five priority filters and built the disclosure mechanism for more.
Adding a filter is cheap; adding all of them would undo the lean UI. We would
rather add the three people ask for after a month of real use.

**3. Should opening a case get faster?**

It scans ~240 MB because the conversation table is not clustered on `case_id`.
Clustering it is a warehouse-side change, not an app change, and it is the single
highest-value optimisation available — it would cut both case-open and search
cost by roughly an order of magnitude. Worth doing if this tool sees real use.

---

## What this deliberately is not

It is not a Salesforce replacement, a BI dashboard, an admin console, or a
reporting tool for people outside the support team. It does not write anything,
anywhere. It does not attempt to be useful to someone without BigQuery access to
the dataset — for that person it correctly shows a screen saying so.

It also does not defend against a compromised laptop or against an authorised
user taking a screenshot. Those are real risks and they are the same risks that
exist today with `bq query`; this tool does not add to them, and does not pretend
to solve them.

---

## Recommendation

Roll it out to the support team as-is, get the Data Broker definition confirmed,
and revisit filters and packaging after a month of actual use. The technical
work is done; the remaining decisions are operational ones that need users, not
more engineering.

`README.md` is the user-facing documentation. `SPECS.md` is the specification
this was built against, plus a register of every place the build deviates from
it and why.
