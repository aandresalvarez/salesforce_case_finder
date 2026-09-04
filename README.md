# Case Finder

A small desktop app for searching the historical Salesforce support-case archive
in BigQuery. It runs on your own laptop, signs in as you, and never copies case
data to disk.

**Version 2.1.0** · macOS and Windows · [full specification](SPECS.md)

---

## What it does

The app opens on Search — a heading and a box, nothing else. Type a case
number and you land on the case; type anything else and you get results.

| | |
|---|---|
| **Search** | Full-text across case fields *and* the conversation bodies — the part that is actually hard to reach in SQL. Matches are shown in context. |
| **Lists** | Triage queues with owner, status, PI, department, IRB protocol, description, last activity, and funding. Filter, sort, save a view, export the metadata. |
| **Case** | The whole case on one page: metadata, the comment stream, individual emails, an interleaved timeline, file pointers, and related cases. Bodies submitted through the web intake form are read back as a form rather than as the JSON they are stored as — with the original always one click away. |
| **Ask** | A plain-English question becomes BigQuery SQL. You read the query before it runs. **Off by default** — set `CASEFINDER_ASK=1` to offer it. |
| **SQL** | For when you already know what you want. Read-only, with a cost estimate before you spend anything. |

Two slices of the archive are available, switchable in Settings:

- **2022 onward** (default) — 1,714 cases, with the audit trail and attachment records.
- **Everything ever** — all 41,526 cases, conversation and case fields only. The
  audit trail and attachment records were not retained for the older era.

---

## Install

You need a Google account that has been granted BigQuery access to the data
project. No admin rights, no service-account key, nothing to configure.

### macOS

```bash
./install-mac.sh
./run-mac.sh
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
.\run-windows.bat
```

The installer puts `uv` in your user profile if it is missing, builds `./.venv`
from `uv.lock`, checks for the Google Cloud CLI, offers to sign you in, and
finishes with a self-check that tells you whether the desktop window and
BigQuery are both actually reachable. Run it again any time; it is idempotent.

### If the desktop window will not open

Native mode draws through the platform webview — WebKit on macOS, the Edge
WebView2 runtime on Windows — and that is the one part of the install that can
be missing on an otherwise healthy machine. The app runs in a browser tab
instead:

```bash
CASEFINDER_NATIVE=0 ./run-mac.sh          # macOS
set CASEFINDER_NATIVE=0 && run-windows.bat  # Windows
```

The server still binds to `127.0.0.1` on a random port either way. Nothing is
ever exposed to the network.

### If the window says it has lost the connection

That notice is about the window and the copy of Case Finder running on your own
computer, not about BigQuery — the connection to the warehouse has its own
screen and its own advice. It tells you which of the two things has happened:

- **Reconnecting.** The link dropped and the app is still there. It comes back
  on its own; the notice counts the seconds and the attempts so you can see it
  trying.
- **Case Finder has stopped responding.** The program behind the window is gone
  or wedged, and nothing on the screen will do anything again. Close the window
  and start Case Finder again. Nothing is lost — the app saves nothing to your
  computer — and you can still select and copy anything on the page first.

---

## Credentials

Case Finder has no login screen. It uses Application Default Credentials — the
same ones `gcloud` uses — so you are whoever is signed in on the machine, and
BigQuery IAM decides what you can read. The app grants nothing and can widen
nothing.

If the Connect screen appears:

```bash
gcloud auth application-default login
```

If that succeeds and the screen persists, you are authenticated but your account
has not been granted BigQuery access to the project. That is a request to the
data team, not something the app can fix.

---

## What it does with your data

The corpus contains PHI, and the design assumes it.

| | |
|---|---|
| **Nothing at rest** | Results live in a 15-minute in-memory cache with no disk backend. Quitting the app is the whole retention policy. |
| **Nothing on the network** | The local server binds to loopback on a random port. There is no on-air, tunnel, or share mode in the code. |
| **Nothing to Gemini** | Ask is off unless a site switches it on, and even then it sends your question and a static table layout. No case row, body, subject, or search result is ever part of a prompt. |
| **Nothing in an export** | The CSV is metadata only — case number, owner, status, PI, department, IRB, funding, last activity. Descriptions and message bodies are excluded on purpose. |
| **Nothing in a saved view** | Saved views persist filter definitions: field names, selected values, sort order, visible columns. Never rows, bodies, snippets, descriptions, or summaries. |
| **Nothing written, anywhere** | Every query is checked for read-only-ness before it is submitted, including the ones Gemini writes. |

Two things leave the process at your explicit request: **Copy summary** writes a
case handoff to your clipboard, and **Export metadata CSV** writes a file where
you tell it to. Both are deliberate actions with visible results. Text on the
screen can also be selected and copied, the way text in a window can; a row
click stands down while you are doing it, so highlighting a name does not open
the case out from under you.

---

## Cost

Every job carries a hard 4 GiB `maximum_bytes_billed` cap. Over it, BigQuery
refuses to start the query rather than running it and billing you — a mistake
costs nothing instead of an unknown amount. Free-form and generated SQL are
dry-run first and refused before execution if they would exceed the cap.

Every job also carries a two-minute time limit, which is a separate guarantee.
Bytes billed measures what a query *reads*; a join that multiplies rows can read
almost nothing and then run for hours. The time limit is enforced by BigQuery
rather than by the app, so the job is genuinely cancelled instead of merely
abandoned.

Measured against the live warehouse:

| Operation | Cold | Warm (cached) | Scanned |
|---|---:|---:|---:|
| Open Lists | ~4.7 s | ~0.2 s | ~5 MB |
| Search, one term, whole conversation | ~1.5 s | instant | ~245 MB |
| Open a case | ~2.7 s | instant | ~240 MB |

Cold numbers are dominated by BigQuery round-trip latency, not by scanning; the
pages that need several independent queries issue them concurrently. Repeating
anything inside the cache window costs nothing at all. The app only mentions
cost when a query scans more than ~50 MB — below that there is nothing worth
saying.

None of those waits is a blank window. Every screen that has to ask BigQuery
something before it can draw puts up a line saying what it is waiting for, and
does the asking off the event loop so that line actually reaches the screen.

---

## Configuration

Everything is an environment variable, and every one has a working default.

| Variable | Default | Purpose |
|---|---|---|
| `CASEFINDER_PROJECT` | `som-rit-phi-starr-dev` | Project holding the datasets |
| `CASEFINDER_BILLING_PROJECT` | same as above | Project billed for queries |
| `CASEFINDER_MAX_BYTES` | 4 GiB | Hard cap on bytes scanned per query |
| `CASEFINDER_QUERY_TIMEOUT` | 120 | Hard cap on how long a query may run, seconds |
| `CASEFINDER_USD_PER_TIB` | 6.25 | Rate used for the on-screen estimate |
| `CASEFINDER_CACHE_TTL` | 900 | Result cache, seconds |
| `CASEFINDER_FACET_CACHE_TTL` | 3600 | Filter-value cache, seconds |
| `CASEFINDER_STALE_DAYS` | 7 | Age at which lists show a freshness banner |
| `CASEFINDER_ASK` | false | `1` offers the Ask destination; off, it is hidden entirely |
| `CASEFINDER_VERTEX_LOCATION` | `us-central1` | Vertex AI region for Ask |
| `CASEFINDER_VERTEX_MODEL` | unset | Pin one Gemini model instead of probing |
| `CASEFINDER_VIEWS_PATH` | `./views.json` | Shared team presets |
| `CASEFINDER_PERSONAL_VIEWS_PATH` | per-OS app data | Your own saved views |
| `CASEFINDER_NATIVE` | true | `0` runs in a browser tab instead |

---

## Team presets

`views.json` next to the app holds the shared presets everyone sees. It contains
filter definitions only. To add one: save a view in the app, use **Copy
definition** in its overflow menu, and paste the JSON object into the list. The
file is read on every page load, so no rebuild is needed.

Your own saved views go somewhere else and are never shared:

- macOS — `~/Library/Application Support/CaseFinder/personal_views.json`
- Windows — `%APPDATA%\CaseFinder\personal_views.json`
- Linux — `~/.config/casefinder/personal_views.json`

---

## Uninstall

Delete this folder. Then delete the personal views file above if you made one —
it holds filter choices, not case data, but it is yours and nothing else will
remove it.

---

## Development

```bash
uv sync --extra ask --extra dev
uv run pytest              # 486 tests, no credentials needed, ~2 s
uv run ruff check .
uv run python -m casefinder.main
git config core.hooksPath .githooks   # once, per clone — see below
```

The default test run touches no network. Fixtures fail loudly if a test reaches
for BigQuery or Vertex, so a test that forgets its fakes fails rather than
quietly passing on live data or hanging.

Tests that do hit the warehouse are opt-in. They need ADC and cost roughly two
cents a run. Run them before a release and after any change to `queries.py`:

```bash
uv run pytest -m warehouse   # 30 tests, ~45 s
```

| File | Covers |
|---|---|
| `test_queries.py` | Query-builder invariants: parameterisation, caps, determinism, both eras |
| `test_search_semantics.py` | Term parsing, phrases, ranking, snippet extraction |
| `test_triage.py` | Filters, sorting, saved views, and what a view file may contain |
| `test_bq.py` | Cost and time guardrails, preflight, credentials, network exposure |
| `test_read_only.py` | The mutation guard, including keywords hidden in comments |
| `test_ask.py` | What is in a Gemini prompt, and what comes back |
| `test_ui_actions.py` | The lean-UI acceptance tests UX-T1 through UX-T7 |
| `test_pagination.py` | Paging on lists and search: offsets, tiebreaks, and when the offset resets |
| `test_visual.py` | Every screen renders, in its populated, empty, and failed states |
| `test_no_corpus_data.py` | No live case data is committed — this repo is public and the corpus is not |
| `test_warehouse.py` | Semantics only real data can prove — opt-in, marked `warehouse` |

UI tests render real NiceGUI pages into an isolated client and assert against
the element tree — no browser, no async, no screenshot baselines. See the
docstrings in `tests/conftest.py` and `tests/test_visual.py` for why.

### Never commit live case data

This repository is public. The corpus it queries is not: case bodies are pasted
email carrying requesters' names, personal and institutional addresses, study
titles, IRB numbers, and the names of the staff who worked the case.

The leak has a predictable shape. Diagnosing a rendering bug means looking at a
real row, and the natural next step is to paste that row into the comment
explaining the fix or the fixture reproducing it. Carry over the *shape*
instead — same length, same punctuation, same awkwardness — and take names from
`tests/synthetic.py` rather than inventing them at the call site.

`test_no_corpus_data.py` fails the build on an address outside the
documentation domains or an absolute home directory. The same check runs as a
pre-commit hook, which is worth installing because a rewritten history is not a
deleted one — old objects stay reachable by SHA on the remote until somebody
purges them:

```bash
git config core.hooksPath .githooks
```

Names are the part no regular expression can settle, which is exactly why the
roster exists: one place to look, and no reason to reach for a real one.

### Layout

```text
casefinder/
  config.py      projects, eras, caps, paths
  bq.py          one client, every query parameterised, every job capped
  queries.py     pure (sql, params) builders — no I/O, no globals
  data.py        the only seam the UI calls: builders + cache + models
  cache.py       TTL cache with no disk backend, on purpose
  models.py      typed rows and the formatting rules for missing values
  views.py       saved views; the allowlist of what may be persisted
  ask.py         question in, SQL out, no case data in the prompt
  intake.py      reads the serialised intake form out of a case body
  main.py        routes, and the loopback-only native window
  ui/            one module per screen, plus shared components/
```

`data.py` is the rule that keeps the rest honest: pages render data and dispatch
actions, and never build SQL.

---

## Known limitations

1. Opening a case scans more than a search does, because the conversation table
   is not clustered on `case_id`. This is the highest-value warehouse fix.
2. Search is substring matching, not stemming or BM25, and relevance is
   primarily mention count.
3. The warehouse is batch-loaded, so a list can show a case as open after it was
   closed in live Salesforce. Lists say so when the snapshot is over a week old.
4. PI, IRB, department, and funding are missing on a good number of cases.
5. Generated SQL can be valid and still answer the wrong question. Read it.
6. Attachments are pointers. Box remains the operational file source.
7. Native mode depends on the platform webview, which has to be re-validated on
   both operating systems each release.
8. A local desktop app does not protect against a compromised laptop, or against
   an authorised user taking a screenshot.

`SPECS.md` records where the build deviates from the specification and why.
