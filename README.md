# Case Finder

A small desktop app for searching the historical Salesforce support-case archive
in BigQuery. It runs on your own laptop, signs in as you, and never copies case
data to disk.

**Version 2.1.1** · macOS and Windows · [full specification](SPECS.md)

Everything through **Uninstall** is for people who use the app. Everything after
it is for people who change it.

---

## What it does

The app opens on Search — a heading and a box, nothing else. Type a case
number and you land on the case; type anything else and you get results.

| | |
|---|---|
| **Search** | Full-text across case fields *and* the conversation bodies — the part that is actually hard to reach in SQL. Matches are shown in context. |
| **Lists** | Triage queues with owner, status, PI, department, IRB protocol, description, last activity, and funding. Filter by owner, status, department, PI or IRB; sort, save a view, export the metadata. From a case, the `…` menu opens its owner's queue. |
| **Case** | The request pinned at the top, the conversation beside the facts about it. A long thread shows its opening and its latest with the middle folded behind a count, and each month marked. The rail carries the case's PI, protocol and funding, and its related cases grouped by how strongly they are related — none of which scrolls away. Bodies submitted through the web intake form are read back as a form rather than as the JSON they are stored as, with the fields the case already shows folded away and the original always one click away. |
| **Ask** | A plain-English question becomes BigQuery SQL. You read the query before it runs. **Off by default** — set `CASEFINDER_ASK=1` to offer it. |
| **SQL** | For when you already know what you want. Read-only, with a cost estimate before you spend anything. |

Two slices of the archive are available, switchable in Settings:

- **2022 onward** (default) — 1,721 cases, with the audit trail and attachment records.
- **Everything ever** — all 41,533 cases, conversation and case fields only. The
  audit trail and attachment records were not retained for the older era.

---

## Install

You need a Google account that has been granted BigQuery access to the data
project. No admin rights, no service-account key, nothing to configure.

There are two ways in: install it to use it, or clone it to work on it.

### Use it

**Step 1 — install `uv`,** the tool that does the installing. Skip this if you
already have it.

On macOS, open Terminal:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows, open **PowerShell** — the older `cmd.exe` prompt will not run these:

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

Then **close that window and open a new one.** The installer edits your shell
profile, and a window that was already open does not see the change. Skipping
this is the one reason the next step says `uv: command not found`.

**Step 2 — install Case Finder.** One command, the same on both systems; there
is nothing to download first:

```bash
uv tool install "https://github.com/aandresalvarez/salesforce_case_finder/releases/download/v2.1.1/casefinder-2.1.1-py3-none-any.whl"
```

If someone handed you the `.whl` file directly instead, point at the file:

```bash
cd ~/Downloads && uv tool install "./casefinder-2.1.1-py3-none-any.whl"
```

**Step 3 — check the machine, then start it:**

```bash
casefinder --check
```

That prints a line per prerequisite — Python, the desktop window's drawing
engine, the shared presets, `gcloud`, your credentials, and BigQuery itself —
and tells you how to fix any that are not ready. It is also the right thing to
paste into a support request; it names no paths belonging to you. When it is
happy:

```bash
casefinder
```

Leave that terminal window open. Closing it closes the app with it.

**If `casefinder --check` says the command is not found,** the install worked but
your shell has not been told where it went. Run `uv tool update-shell`, then open
a new window.

To include the optional natural-language mode, ask for the `ask` extra. From a
URL that is the `name[extra] @ url` form; from a file it goes on the end. The
quotes are required either way, because a bare `[ask]` means something else to
the shell:

```bash
uv tool install --force "casefinder[ask] @ https://github.com/aandresalvarez/salesforce_case_finder/releases/download/v2.1.1/casefinder-2.1.1-py3-none-any.whl"
```

```bash
uv tool install --force "./casefinder-2.1.1-py3-none-any.whl[ask]"
```

That installs the mode without switching it on; see `CASEFINDER_ASK` below.

### Keep it up to date

Not `uv tool upgrade`. The install line above names one exact version and `uv`
remembers it, so `uv tool upgrade casefinder` answers `Nothing to upgrade` — and
will keep answering that no matter how many releases go by. Use the app's own
command:

```bash
casefinder --update
```

It asks GitHub which release is newest, installs it if it is newer than yours,
and tells you if it is not. An install made with `[ask]` keeps `[ask]`. Restart
the app afterwards to be running the new one.

You do not have to remember to check: `casefinder --check` says when a newer
release exists. If you would rather it did not reach out, set
`CASEFINDER_UPDATE_CHECK=0` — `--update` still works when you ask for it.

Every release is listed on the
[releases page](https://github.com/aandresalvarez/salesforce_case_finder/releases),
and each one carries the install line for that version.

### Work on it

Clone the repository, then run the setup script for your system:

```bash
./install-mac.sh     # then ./run-mac.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1   # then .\run-windows.bat
```

The installer puts `uv` in your user profile if it is missing, builds `./.venv`
from `uv.lock`, checks for the Google Cloud CLI, offers to sign you in, and
finishes with the same self-check. Run it again any time; it is idempotent.

### If the desktop window will not open

Native mode draws through the platform webview — WebKit on macOS, the Edge
WebView2 runtime on Windows — and that is the one part of the install that can
be missing on an otherwise healthy machine. `casefinder --check` says so by
name, and links the Windows runtime download. Until it is fixed, the app runs in
a browser tab instead:

```bash
CASEFINDER_NATIVE=0 casefinder             # macOS
```

```powershell
$env:CASEFINDER_NATIVE=0; casefinder       # Windows
```

From a source checkout, put the same variable in front of `./run-mac.sh` or
`run-windows.bat`. Every setting in [Configuration](#configuration) is set this
way; a variable set like that lasts for the one command, and setting it in your
shell profile makes it stick.

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
  or wedged, and nothing on the screen will do anything again. The notice offers
  two buttons: **Restart Case Finder**, which starts a fresh copy and keeps this
  window on screen until the new one is up, and **Close window**. Nothing is lost
  — the app saves nothing to your computer — and you can still select and copy
  anything on the page before pressing either.

  In a browser tab there is no second process to ask, so there are no buttons:
  close the tab and start Case Finder the way you normally do.

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
| **Nothing at rest** | Results live in a 15-minute in-memory cache with no disk backend. Entries are deleted when they expire rather than merely refused, and the cache is capped so a long day cannot grow the process without limit. Quitting the app is still the whole retention policy. |
| **Nothing on the network** | The local server binds to loopback on a random port. There is no on-air, tunnel, or share mode in the code. |
| **Nothing to Gemini** | Ask is off unless a site switches it on, and even then it sends your question and a static table layout. No case row, body, subject, or search result is ever part of a prompt. |
| **Nothing in an export** | The CSV is metadata only — case number, owner, status, PI, department, IRB, funding, last activity. Descriptions and message bodies are excluded on purpose. |
| **Nothing in a saved view** | Saved views persist filter definitions: field names, selected values, sort order, visible columns. Never rows, bodies, snippets, descriptions, or summaries. |
| **Nothing written, anywhere** | Every query is checked for read-only-ness before it is submitted, including the ones Gemini writes — first against the text, then against BigQuery's own reading of it, which is the one that decides. |

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
| `CASEFINDER_PROJECT` | `som-nero-phi-naras-ric` | Project holding the datasets |
| `CASEFINDER_BILLING_PROJECT` | same as above | Project billed for queries |
| `CASEFINDER_MAX_BYTES` | 4 GiB | Hard cap on bytes scanned per query |
| `CASEFINDER_QUERY_TIMEOUT` | 120 | Hard cap on how long a query may run, seconds |
| `CASEFINDER_USD_PER_TIB` | 6.25 | Rate used for the on-screen estimate |
| `CASEFINDER_CACHE_TTL` | 900 | Result cache, seconds |
| `CASEFINDER_FACET_CACHE_TTL` | 3600 | Filter-value cache, seconds |
| `CASEFINDER_CACHE_MAX_ENTRIES` | 150 | Result cache ceiling; least recently used goes first |
| `CASEFINDER_FACET_CACHE_MAX_ENTRIES` | 32 | Filter-value cache ceiling |
| `CASEFINDER_CACHE_REAP_SECONDS` | 60 | How often expired entries are deleted; `0` disables the sweep |
| `CASEFINDER_STALE_DAYS` | 7 | Age at which lists show a freshness banner |
| `CASEFINDER_ASK` | false | `1` offers the Ask destination; off, it is hidden entirely |
| `CASEFINDER_VERTEX_LOCATION` | `us-central1` | Vertex AI region for Ask |
| `CASEFINDER_VERTEX_MODEL` | unset | Pin one Gemini model instead of probing |
| `CASEFINDER_VIEWS_PATH` | the packaged `views.json` | Shared team presets; point it at your own file to override them |
| `CASEFINDER_PERSONAL_VIEWS_PATH` | per-OS app data | Your own saved views |
| `CASEFINDER_NATIVE` | true | `0` runs in a browser tab instead |
| `CASEFINDER_UPDATE_CHECK` | true | `0` stops `--check` asking GitHub whether a newer release exists |

---

## Team presets

The shared presets everyone sees ship inside the app, as `casefinder/views.json`.
The file holds filter definitions only, and Settings shows the exact path it was
read from.

Editing it in place works from a source checkout and is a bad idea in an
installed copy, where the next `uv tool install --force` overwrites it. Point
`CASEFINDER_VIEWS_PATH` at a file of your own instead:

```bash
CASEFINDER_VIEWS_PATH=~/team-views.json casefinder
```

To add a preset to either file: save a view in the app, use **Copy definition**
in its overflow menu, and paste the JSON object into the list. The file is read
on every page load, so no rebuild is needed — and if it is missing or
unreadable, the app quietly falls back to its built-in presets, which is what
the `presets` line of `casefinder --check` is there to tell you.

Your own saved views go somewhere else and are never shared:

- macOS — `~/Library/Application Support/CaseFinder/personal_views.json`
- Windows — `%APPDATA%\CaseFinder\personal_views.json`
- Linux — `~/.config/casefinder/personal_views.json`

---

## Uninstall

If you installed the `.whl`:

```bash
uv tool uninstall casefinder
```

If you have the source checkout, delete the folder.

Either way, delete the personal views file above if you made one — it holds
filter choices, not case data, but it is yours and nothing else will remove it.
Your Google credentials are `gcloud`'s and are left alone; `gcloud auth
application-default revoke` is the command if you want them gone too.

---

## Development

```bash
uv sync --extra ask --extra dev
uv run pytest              # 672 tests, no credentials needed, ~4 s
uv run ruff check .
uv run casefinder          # the same entry point an installed copy uses
git config core.hooksPath .githooks   # once, per clone — see below
```

The default test run touches no network. Fixtures fail loudly if a test reaches
for BigQuery or Vertex, so a test that forgets its fakes fails rather than
quietly passing on live data or hanging.

Tests that do hit the warehouse are opt-in. They need ADC and cost roughly two
cents a run. Run them before a release and after any change to `queries.py`:

```bash
uv run pytest -m warehouse   # 31 tests, ~55 s
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
| `test_packaging.py` | What is true of the wheel but not of a checkout: packaged presets, the console script, nothing untracked shipping |
| `test_update.py` | Finding the newest release and installing over this one, without touching the network |
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

### Releasing

Bump `VERSION` in `casefinder/config.py` — the only place it lives;
`pyproject.toml` reads it from there and `casefinder.__version__` re-exports it
— update the install URLs in this file and `PROPOSAL.md` to match, commit, push,
then:

```bash
./release.sh --publish
```

Without `--publish` it stops after building, which is the right thing when you
want to look at the wheel. With it, one command does all of:

1. refuses a dirty working tree;
2. `ruff` and the full suite;
3. builds the wheel and checks `views.json` is inside it;
4. checks the install URLs in the docs name the version being released;
5. writes `dist/requirements-lock.txt` — the exact versions this release was
   tested against, for a site that has to pin them;
6. tags, pushes the tag, and creates the GitHub release with both files
   attached;
7. downloads the published asset with no credentials and installs it into a
   throwaway directory, so the link in the README is known to work rather than
   assumed to.

Neither built file is committed. The wheel is a release asset because a binary
in git history is permanent: every clone fetches every version ever committed
and a force-push does not remove it, which is the same reasoning as the corpus
rule.

The dirty-tree refusal is the pre-commit hook seen from the other side. The
build packages the *working tree*, so an uncommitted file is one the corpus
guard has never scanned, and the wheel is the artifact that leaves the machine.

It will not move a tag that already exists, locally or on origin. A published
tag is one somebody may have installed from, and re-pointing it changes what a
URL means; the way to release again is a new version.

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
  selfcheck.py   `--check`: is this machine ready, and if not, what to do
  update.py      `--update`: which release is newest, and installing it
  ui/            one module per screen, plus:
    theme.py       the visual language — one stylesheet, two installers
    state.py       what the reader has asked for, held between renders
    shell.py       the navigation rail and the connection gate
    errors.py      how a page reports a failure
    components/    the reusable pieces, including the button vocabulary
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
   both operating systems each release. `casefinder --check` reports whether the
   backend imports, which is not the same as proving a window draws.
8. A local desktop app does not protect against a compromised laptop, or against
   an authorised user taking a screenshot.

`SPECS.md` records where the build deviates from the specification and why.
