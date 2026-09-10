# Case Finder — as-built specification

**Version 2.1.0 · 3 September 2026**

The normative specification is
[`CASE_FINDER_SPECS_NICEGUI_LEAN_v2.1.md`](CASE_FINDER_SPECS_NICEGUI_LEAN_v2.1.md),
which is unchanged from the version the build was commissioned against in every
respect that bears on a requirement. The one edit is redaction: §1.6 quoted the
v1 working copy by absolute path, and the leading `/Users/<name>` was replaced
with `~` when this repository was made public. This
document is the other half of that pair: what was actually built, where each
requirement lives in the source, how it was verified, and — in the register at
the end — every place the implementation departs from the specification, with
the reason.

Read the register. A spec with no deviations after an implementation is a spec
nobody checked.

---

## 1. Verification status

| | |
|---|---|
| Automated tests | **636 passing**, ~2.6 s, no network access required |
| Warehouse tests | **31 passing** against live BigQuery on `som-nero-phi-naras-ric`, ~60 s, ~2¢ (opt-in: `pytest -m warehouse`) |
| Lint | `ruff check .` clean |
| Live warehouse | All 7 routes return HTTP 200 against `som-rit-phi-starr-dev` with no tracebacks. Not re-run route-by-route since the project moved to `som-nero-phi-naras-ric`; the warehouse suite passes there and every query the routes issue is covered by it — see D32. |
| Native window | `python -m casefinder.main` opens a pywebview window on `127.0.0.1` with an OS-assigned port |
| macOS installer | `./install-mac.sh` completes on a clean path, exit 0, self-check reports BigQuery reachable |
| Wheel | Built, then installed into a throwaway tool directory and exercised there: `--version` and `--check` correct, all 7 checks `ok`, presets resolved from `site-packages`, and the console script reports `init_main_from_name: casefinder.main` — see D33 |
| Ask | End-to-end against Vertex on both eras; generated SQL passed the read-only guard and dry-ran under cap |

Tests requiring credentials are marked `warehouse` and excluded by default. The
fixtures fail loudly if a test reaches for BigQuery or Vertex without asking, so
a test that forgets its fakes fails rather than silently running on live data.

The split matters. `tests/test_warehouse.py` covers the §13.1 items a fake
cannot speak to — that the triage join does not fan out *on this data*, that `%`
is escaped against BigQuery's own `LIKE`, that the archive era's tables really
are shaped the way the era flags claim, that the corpus is still the size the
documentation quotes. Everything else runs against fakes, which is right: a fake
makes the contract explicit and the whole suite finishes in a second.

---

## 2. Module map

9,297 lines across 34 modules.

| Module | Lines | Responsibility |
|---|---:|---|
| `queries.py` | 786 | Pure `(sql, params)` builders. No I/O, no globals, no client. |
| `models.py` | 710 | Typed rows; the single place that decides how a missing value is displayed. |
| `ui/reconnect.py` | 566 | What the window says, and offers, when the program behind it stops answering (D20, D21). |
| `ui/case_detail.py` | 750 | §6.4 — header, metadata, comments, messages, timeline, files, related. |
| `ui/lists.py` | 444 | §6.2 — the triage list, its filters, its paging and its CSV. |
| `bq.py` | 469 | One client, byte caps, cost estimates, and the two-stage read-only guard. |
| `ui/search.py` | 434 | §6.3 — idle state, results, snippets, paging, case-number shortcut. |
| `data.py` | 350 | The UI↔query seam: builder + cache + model, one function per page need. |
| `views.py` | 297 | Saved views, and the allowlist of what may be persisted. |
| `ask.py` | 248 | §6.5 — question in, SQL out; nothing else in the prompt. |
| `ui/theme.py` | 346 | §3.3 — the visual language, and the two ways a stylesheet reaches a page. |
| `cache.py` | 302 | TTL cache with no disk backend, deliberately. Bounded, reaped, single-flight. |
| `intake.py` | 449 | Reads the serialised intake form out of a case body (D15). Pure. |
| `ui/components/table.py` | 223 | The list table; clickable rows, no Open button, container-query columns (D16). |
| `config.py` | 252 | Every environment variable and its default. |
| `ui/ask_page.py` | 215 | §6.5 UI — generate, review, then run. |
| `ui/components/filters.py` | 295 | The compact filter row and its disclosure. |
| `ui/sql_page.py` | 192 | §6.6 — free-form SQL with a priced dry run. |
| `window.py` | 194 | What the native window can still do once the server behind it has gone (D21). |
| `selfcheck.py` | 194 | `casefinder --check` — seven prerequisites, one line each, on any machine the app is installed on (D34). |
| `main.py` | 245 | Routes, the loopback-only native window, its selectable body (D19) and its bridge (D21). |
| `ui/settings.py` | 185 | §6.7 — era, connection, Ask availability, about. |
| `ui/shell.py` | 156 | §3.1 — the navigation rail, the content region, and the connection gate. |
| `ui/list_columns.py` | 140 | What a list row shows, and the order columns give way in (D16). |
| `ui/components/loading.py` | 104 | Says a slow thing is happening, and gets the work off the event loop. |
| `ui/components/intake_form.py` | 176 | Draws what `intake.py` parsed — as labels, never as HTML. |
| `ui/state.py` | 100 | §4.5 — what the reader has asked for, held between renders. |
| `ui/components/pager.py` | 88 | The range line and its two arrows; one pager for every paged screen. |
| `ui/saved_views.py` | 76 | §6.2 — the Saved Views screen, reachable from the selector not the rail. |
| `ui/components/metadata.py` | 101 | The flat metadata strip that replaced five metric cards. |
| `ui/components/actions.py` | 66 | The action vocabulary; `primary()` is the only filled button in the app. |
| `ui/components/empty_state.py` | 56 | Every "nothing here" screen, including the failure ones. |
| `ui/components/freshness.py` | 38 | The stale-snapshot banner. |
| `ui/errors.py` | 36 | §12 — one plain sentence, with the raw text one disclosure away. |

### The layering rule

`ui/` may call `data`. Nothing else. No UI module imports `bq` or `queries`, and
no query builder knows a page exists. This is what makes the query invariants in
§7.1 testable in isolation and the pages testable without a warehouse.

---

## 3. Requirement traceability

### Queries — §7.3

All eleven specified builders exist, plus one the spec's own §5.6 requires but
its inventory table omits.

| Builder | v1 status | Built |
|---|---|---|
| `search` | ported | ✓ |
| `browse` | promoted from private `_browse` | ✓ |
| `corpus_size` | ported | ✓ |
| `facets` | ported | ✓ |
| `case_header` | ported | ✓ |
| `comments_stream` | **new** — split from v1's `case_transcript` per SR-6 | ✓ |
| `case_messages` | **new** — the other half of that split | ✓ |
| `case_timeline` | ported | ✓ |
| `case_attachments` | ported | ✓ |
| `triage_list` | **new** — no v1 equivalent (SR-2, SR-3) | ✓ |
| `related_cases` | **new** — no v1 equivalent (FR-CASE-10) | ✓ |
| `warehouse_freshness` | **new** — required by §5.6, absent from the §7.3 table | ✓ |

Invariants Q-INV-1..5 are enforced by `tests/test_queries.py`, which walks every
builder in both eras and asserts each one is parameterised, capped, pure, and
deterministic. The sweep is driven by two lists at the top of that file, which
makes those lists load-bearing — so a further test enumerates `queries.py` by
reflection and fails if a public builder is missing from them. A new builder
added without invariant coverage cannot pass silently.

### Functional requirements

| Area | Spec | Where | Tests |
|---|---|---|---|
| Startup, access probe, no setup dashboard | FR-START-1..3 (landing page is D17) | `main.py`, `ui/shell.py` | `test_ui_actions.py`, `test_visual.py` |
| Lists, columns, sorting, filters, presets, saved views, paging, CSV | FR-LIST-1..12 (paging is D11) | `ui/lists.py`, `views.py`, `ui/components/pager.py` | `test_triage.py`, `test_ui_actions.py`, `test_pagination.py` |
| Filtering a queue by who owns it | D22 | `queries.py`, `ui/lists.py`, `ui/components/filters.py`, `ui/case_detail.py` | `test_triage.py`, `test_ui_actions.py`, `test_pagination.py` |
| Search: idle, execute, shortcut, parsing, scope, results, limits, paging, empty | FR-SEARCH-1..12 | `ui/search.py`, `queries.search`, `ui/components/pager.py` | `test_search_semantics.py`, `test_pagination.py` |
| Case: comments-first, header, metadata, copy summary, tabs, related, unknown | FR-CASE-1..11 | `ui/case_detail.py` | `test_ui_actions.py`, `test_visual.py` |
| Case body rendering, and the wait before one appears | FR-CASE-4, FR-CASE-5 (D15) | `intake.py`, `ui/components/intake_form.py`, `ui/components/loading.py` | `test_intake.py`, `test_reading.py` |
| The wait before any screen appears | D18 | `ui/components/loading.py`, and every page that queries | `test_reading.py` |
| Selecting and copying any text on any screen | D19 | `main.py`, `ui/shell.py`, and every region whose click navigates | `test_reading.py` |
| Losing the window's own connection to the app | D20 | `ui/reconnect.py`, `main.py` | `test_reconnect.py` |
| Getting out of a window whose app has gone | D21 | `window.py`, `ui/reconnect.py`, `main.py` | `test_window.py`, `test_reconnect.py` |
| Ask: layout, Enter, no case data, review, guards, availability | FR-ASK-1..7 | `ask.py`, `ui/ask_page.py` | `test_ask.py` |
| SQL: layout, read-only, errors | FR-SQL-1..4 | `ui/sql_page.py`, `bq.assert_read_only` + `bq.plan` | `test_read_only.py`, `test_bq.py` |
| Settings | §6.7 | `ui/settings.py` | `test_visual.py` |

### Lean UI — Appendix B

| Rule | Implementation | Test |
|---|---|---|
| One dominant task per page | flat page composition | UX-T1 |
| ≤1 primary filled action | asserted per screen state | UX-T1 |
| No Search button | Enter handler | UX-T2 |
| No Open button per result | clickable result | UX-T3 |
| No Open button per row | clickable row | UX-T3 |
| Comments-first | default detail tab | UX-T4 |
| No list admin toolbar | overflow menu | UX-T5 |
| Progressive disclosure | filter disclosure, overflow | UX-T6 |
| Flat surfaces, no nested cards | dividers and table rows | UX-T7 |
| Native desktop | `ui.run(native=True)` | launch verified manually |
| Loopback only | `host="127.0.0.1"`, free port, no on-air | `test_bq.py` network-exposure tests |
| No PHI persistence | memory-only cache, view allowlist | `test_triage.py` persistence tests |

UX-T1 is the load-bearing one. It renders each screen and counts primary filled
buttons, so the interface cannot re-accumulate a toolbar over the next year of
maintenance without a test going red.

### Failure matrix — §12

Every row is a test in `test_visual.py` or `test_ui_actions.py`: missing
credentials, authenticated-but-ungranted, Vertex unavailable, no model, over the
byte cap, mutation SQL, archive without history, archive without attachments,
unknown case, sub-2-character search, zero results, empty facet, stale snapshot,
and the generic BigQuery error. The native-window row is a documented fallback
(`CASEFINDER_NATIVE=0`) rather than a test, since it cannot be provoked in
process.

### Security — §9

| Control | Implementation |
|---|---|
| ADC only, no key (§9.1) | `bq.get_client()` uses default credentials; no key path exists in the source |
| IAM is the gate (§9.2) | the app adds no authorisation logic of its own |
| No PHI at rest (§9.3) | `cache.py` has no disk backend; CSV is metadata-only; nothing to Gemini but the question and a static schema |
| Saved-view rule (§9.3) | `views.py` serialises from an explicit field allowlist and rejects unknown keys |
| Read-only (§9.4) | every submitted query passes `assert_read_only`, and every query the app did not write is then refused unless BigQuery's own dry-run `statement_type` is `SELECT` — including generated SQL. See D23. |
| Escape-then-highlight (§9.5) | snippets are HTML-escaped, then marked; tested with markup in the search term |
| Loopback only (§9.6) | `127.0.0.1` on a free port; no `0.0.0.0`, no on-air, no tunnel in launch code |
| Bounded spend (§8, §12) | 4 GiB scanned and 120 s of runtime per job, both enforced by BigQuery rather than by the app |

One control is not in §9 because the specification did not anticipate the
repository being public: no live corpus data may be committed. It is enforced by
`tests/corpus_guard.py`, which fails the suite on an email address outside the
documentation domains or an absolute home directory, and which also runs as a
pre-commit hook (`git config core.hooksPath .githooks`). Names are the part no
pattern can settle, so invented people are kept in `tests/synthetic.py` and
taken from there rather than made up at each call site. The rule this encodes is
that diagnosing a rendering bug means looking at a real row, and the natural
next step — pasting that row into the comment explaining the fix — is the leak.
Carry over the shape, never the string.

---

## 4. Deviations register

Thirty-five departures from the specification. Each names what the spec says,
what was built, and why.

### D1 — `casefinder/data.py` is not in the specified module layout

**Spec:** §4.3 and Appendix A list `main`, `config`, `models`, `bq`, `queries`,
`ask`, `cache`, `views` and `ui/`. There is no `data.py`.

**Built:** a `data.py` module sitting between `ui/` and everything below it. Each
function takes an era and page-level arguments, builds the query, runs it under
the cache, and returns typed models.

**Why:** the layering rule in §4.2 says the UI must not build SQL, but the spec
does not say what the UI *should* call. Without a named seam, every page would
import `queries`, `bq`, `cache`, and `models`, wire the four together itself, and
own its own cache-key convention — which is exactly how "no ad-hoc SQL in the UI"
erodes one page at a time. Making the seam a module makes the rule mechanically
checkable: `ui/` imports `data` and nothing under it. It also gives the cache one
place to live and prefetching (D9, below) somewhere to exist.

**Effect on requirements:** none. This is an added interior boundary, not a
changed behaviour.

### D2 — the `ask` extra is `google-genai`, not `google-cloud-aiplatform`

**Spec:** §4.4 lists `google-cloud-aiplatform` as the optional dependency for
natural-language mode, matching v1's use of `vertexai.generative_models`.

**Built:** `google-genai>=1.0`, the Google Gen AI SDK, pointed at Vertex.

**Why:** `vertexai.generative_models` emits a deprecation warning naming a
removal date of 24 June 2026 — already past. It still imports today; planning
around it importing next year is not a plan. It also pulls the entire
`google-cloud-aiplatform` stack — Cloud Storage, Resource Manager, IAM — into an
install whose only job is sending one prompt. Known limitation 9 in the spec is
that Gemini availability shifts over time; the answer to that is to sit on the
SDK Google is still maintaining.

**Effect on requirements:** none visible. Same model, same Vertex project and
location, same prompt, same `VertexUnavailable` behaviour. FR-ASK-4 (the model
sees no case data) is if anything better tested than before —
`test_ask.py` reconstructs the outgoing prompt from its two declared parts and
asserts equality, so a third component cannot be added without failing.

### D3 — the "Data Broker Triage" preset is provisional

**Spec:** Appendix C traces "Data Broker / Open Cases lists" to FR-LIST-1 and
FR-LIST-8. FR-LIST-8 names Data Broker Triage as a shipped preset.

**Built:** a preset named "Data Broker Triage" filtering `status = 'Data Queue'`,
described in the app and in `views.json` as provisional and pending confirmation.
It currently matches 3 open cases.

**Why:** "Data Broker" does not appear in the warehouse. Not as a status value,
not as an owner, not as a queue name, not in any facet of `dim_case` or the raw
Case table. It is an operational term whose data meaning was never captured.
`Data Queue` is the nearest status that exists, and it may well be wrong.

Shipping a preset that silently filters on a guess is worse than shipping one
labelled as a guess, and shipping nothing loses the requirement. SR-13 already
routes this class of question to a stakeholder conversation; this is one of them.

**To resolve:** confirm the operational definition, then edit `views.json`. No
release, no rebuild — the file is read on every page load.

### D4 — no pandas

**Spec:** §4.4 lists pandas as optional.

**Built:** not a dependency. Rows are plain dicts from the BigQuery client,
converted to typed models in `models.py`.

**Why:** it was optional, and nothing needed it. The only candidate use was CSV
export, which `csv.DictWriter` handles in about ten lines for a metadata-only
file. Adding ~50 MB of NumPy and pandas to a desktop install to avoid those ten
lines is the wrong trade, and Q-INV-4 already requires plain-dict rows out of the
query layer.

### D5 — §13.4 visual tests are render assertions, not screenshot diffs

**Spec:** §13.4 defines a visual regression set of screens to be checked.

**Built:** `tests/test_visual.py`, 26 tests, rendering each specified screen into
an isolated NiceGUI client and asserting on the element tree: the screen renders
content rather than an error, it has exactly one `cf-h1`, the shell is intact,
selecting a tab actually triggers that tab's loader, snippets are the only raw
HTML on a results page, and each empty and failed state says the right thing.
Playwright is declared in the `dev` extra but no image baselines are committed.

**Why:** pixel baselines for a desktop app have to be captured per platform, and
they drift on a font update, an OS point release, or a display scale change. A
baseline that only one maintainer can regenerate becomes a test everybody skips
within a month, and a skipped test is worse than no test because it looks like
coverage. Structural assertions catch the regressions that matter here — a screen
that fails to render, a tab whose loader never fires, an error region where
content belongs — and they run in a second with no browser.

**What this does not catch:** actual layout and styling regressions. Capturing
release screenshots on both platforms stays a manual release step.

### D6 — read-only guard steps 4 and 5 are swapped

**Spec:** §9.4 orders the checks: strip comments, reject empty, reject
multi-statement, **require `SELECT` or `WITH`**, **reject mutation keywords**.

**Built:** the last two are inverted — keyword check before shape check. The
whole scan later became a pre-filter in front of BigQuery's own verdict; see
D23.

**Why:** §12 requires that mutation SQL be rejected *naming the offending
keyword*. In the specified order, `DELETE FROM dim_case` fails the shape check
first and is told "only SELECT queries are allowed" — true, and the less useful
of the two things we know about it. Inverted, it is told `'DELETE' is not
allowed`, which is what §12 asks for.

**Why this is safe:** both rules are pure predicates over the same normalised
string, so the refused set is identical in either order — only the message
differs. `tests/test_read_only.py` proves it rather than asserting it: it
re-implements the specified order alongside the built one and asserts both refuse
exactly the same queries across the whole allowed/refused corpus. If a future
change to either rule breaks that equivalence, the test fails.

### D7 — `pywebview` is pinned `>=5.4,<6`

**Spec:** §4.4 asks for "NiceGUI + a pinned compatible pywebview release" without
naming a range.

**Built:** `pywebview>=5.4,<6` in `pyproject.toml`, plus `uv.lock`, plus
`uv sync --frozen` in both installers and both launchers.

**Why:** NiceGUI 2.x declares `pywebview>=5.0.1,<6.0.0` for its native extra, and
an unbounded requirement here resolves to 6.x — outside the range the code
driving it was written against. Native desktop is the product; whether the window
opens is not a decision to leave to a resolver on someone else's laptop.
`--frozen` extends the same guarantee to install time, so a machine set up in six
months gets the environment that was tested rather than a fresh resolution.

### D8 — a wall-clock ceiling was added alongside the byte cap

**Spec:** §12 says a query over the 4 GiB cap is refused before execution.
Nothing anywhere bounds how long a query may run.

**Built:** every job also carries `job_timeout_ms`, defaulting to 120 seconds
and configurable via `CASEFINDER_QUERY_TIMEOUT`. An expiry is translated into a
message that says which guardrail stopped the query and why the other one did
not.

**Why:** the two bounds are not the same guarantee, and assuming the byte cap
covers both is a mistake this build made and then observed. Writing the
warehouse test for the cost guard produced:

```sql
SELECT t.*, c.* FROM fct_conversation_turn t CROSS JOIN dim_case c
```

which scans 275 MB — comfortably under the cap, dry-run priced at a fraction of
a cent — and then materialises roughly eleven billion rows. Preflight passed it,
the job started, and it had to be cancelled by hand. In the desktop app that is
a window that never comes back, on a query the user was told was cheap.

`job_timeout_ms` rather than a client-side timeout, because a client-side one
returns control to the UI while leaving the job running and billing. This one is
enforced by BigQuery, so the job is genuinely cancelled.

**Effect on requirements:** additive. No query the app itself writes comes close
to 120 seconds; the ceiling only ever fires on free-form or generated SQL, which
is where the spec already expects guardrails to be visible.

### D9 — seven environment variables beyond the §10 table

**Spec:** §10 tabulates the configuration surface.

**Built:** seven additions.

| Variable | Default | Why |
|---|---|---|
| `CASEFINDER_QUERY_TIMEOUT` | 120 s | The wall-clock ceiling described in D8. |
| `CASEFINDER_FACET_CACHE_TTL` | 3600 | Filter values change on the warehouse's load cadence, not on the 15-minute result cadence. Re-querying them every 15 minutes buys nothing and costs a visible pause on the filter row. |
| `CASEFINDER_PERSONAL_VIEWS_PATH` | per-OS app data dir | §11.5 requires the personal saved-view file to be documented and separable for uninstall. Overriding its location is what makes that testable without writing to a real user profile. |
| `CASEFINDER_ASK` | false | Whether the natural-language mode is offered at all — see D14. |
| `CASEFINDER_CACHE_MAX_ENTRIES` | 150 | The ceiling on the result cache — see D24. Entries rather than bytes, because sizing a Python object graph is expensive and inaccurate. |
| `CASEFINDER_FACET_CACHE_MAX_ENTRIES` | 32 | The same ceiling for the facet cache, which holds one entry per era and scope. |
| `CASEFINDER_CACHE_REAP_SECONDS` | 60 | How long a value that may no longer be served stays in memory — see D24. `0` disables the sweep. |

Every one has a working default; none needs to be set.

### D10 — pages warm independent queries concurrently

**Spec:** §8 sets latency targets and NFR-PERF-3 requires that the migration not
increase scan volume. It does not describe how pages issue queries.

**Built:** `data.prefetch()`, which runs several independent cached loads on a
small thread pool before the page draws them.

**Why:** a BigQuery round trip on this warehouse costs roughly 1.3–2 s, and
almost none of that is scanning — it is job creation and polling. Lists needs
three independent results before it can draw anything, so asking one at a time
made opening the app a ~7 s wait for ~2 s of work. Issuing them together took the
Lists page from 7.1 s to 4.7 s and case detail from 4.7 s to 2.7 s.

**Effect on NFR-PERF-3:** none. Every load still runs exactly once and every one
is a cached function, so the sequential calls that follow are cache hits. Bytes
billed are identical; this buys latency and nothing else. `test_bq.py` asserts
both halves — that each load runs exactly once, and that they genuinely overlap
(three 0.2 s loads must complete in under 0.45 s), because a version that quietly
ran them in sequence would pass every other test in the file while doing nothing.

`get_client()` acquired a double-checked lock for the same reason: the first
request of the app's life can now arrive on two threads at once.

### D11 — Lists is paged, which §6.2 does not ask for

**Spec:** FR-SEARCH-11 requires pagination on Search. Nothing in §6.2 mentions
paging a list, a row cap, or a `Rows per page` control; FR-LIST-1 sketches a
list and a count and stops there.

**Built:** `triage_list` takes an offset, Lists draws 50 rows at a time, and the
pager is repeated under the table as well as above it.

**Why:** Open Cases returns 334 rows and the archive era returns more. Without
paging the page rendered every row it retrieved, up to the 500-row cap, and the
rows beyond the cap were unreachable by any means the interface offered — there
was no next page, and no sort that would bring row 501 into the first 500 except
by luck. The count line said `334 cases` while the table held a silent prefix of
them. A capped list with no pager is a list that lies about what it contains.

It also made the page enormous: 334 rows of nine columns is ~993 KB of DOM on
open. Fifty rows is 204 KB.

**Effect on requirements:** none removed. FR-LIST-1's count is now a range —
`1–50 of 334 cases` — which says strictly more than `334` did. FR-LIST-5's
sorting still re-queries server-side, and paging resets to the first page
whenever the sort, a filter or the era changes, because an offset is a position
in one particular result.

**Cost:** unchanged per page, and that is worth being explicit about. `LIMIT`
and `OFFSET` bound what BigQuery returns, not what it scans, so page 7 bills the
same bytes as page 1 and the same bytes the unpaged list billed. This buys
reachability and payload size, not money. A live dry-run test in
`test_warehouse.py` asserts it rather than assuming it.

### D12 — every search sort carries a case-number tiebreak

**Spec:** FR-SEARCH-10 names four sorts — mentions, newest, oldest, longest
thread — and says nothing about ties.

**Built:** every one of them orders by `c.case_number DESC` as a final key.

**Why:** none of the four sort keys is unique. Hundreds of cases share a mention
count; a day's cases share a date. Without a total order BigQuery may return
tied rows in a different order on each request, and paging over an unstable sort
is not a partition: the same case can appear on two consecutive pages while
another appears on neither, silently. This is not a preference about tie
ordering — any deterministic tiebreak would do. It is what makes the pages of a
result add up to the result. `test_warehouse.py` fetches three consecutive pages
against live data and asserts their union equals a single fetch of the same
span, in the same order.

### D13 — Search pages past row 500; the 500 caps one fetch

**Spec:** FR-SEARCH-11 — "Use pagination … Cap server-side result retrieval at
500."

**Built:** `MAX_RETRIEVAL = 500` caps a single request. Offsets are not capped,
so a reader can page to result 501 and beyond, one page at a time.

**Why:** the two halves of that sentence pull against each other — pagination
whose offsets stop at 500 is pagination that hides the tail of any result larger
than 500, which is the problem pagination exists to solve. Read as "no single
response may be unbounded", both halves hold: the largest page offered is 100,
no request can turn into a 41,533-row response, and reaching result 501 takes a
deliberate act per page rather than one accidental query.

**Effect on requirements:** FR-SEARCH-9's truncation state is gone, because
there is no longer truncation to state. Where the page used to read
`334 results · showing first 100` it now reads `1–100 of 334 results`.

---

### D14 — the natural-language mode is off by default and hidden when off

**Spec:** §6.5 and FR-ASK-1..8 specify Ask as one of the four primary
destinations, always present, degrading to an explanatory message when Vertex
is unreachable.

**Built:** `config.ASK_ENABLED` (`CASEFINDER_ASK`, default off). With it off
there is no Ask destination in the rail, `/ask` redirects to Lists, and the
About panel does not name Vertex or a model. With it on, everything is exactly
as specified.

**Why:** the spec assumed the only question was whether Vertex was *reachable*.
The real question a site asks first is whether it wants questions about a PHI
corpus going to a model at all, and that is a decision to make deliberately
rather than to discover already made. §6.5's degraded state answers "why isn't
this working"; it has no way to say "this was not switched on", and a permanent
`Vertex AI · unavailable` in Settings reads as a broken dependency rather than
as an unthrown switch.

Hiding rather than disabling is the point. A greyed-out Ask still invites the
question, and the honest answer would have to describe a capability the site
has chosen not to offer.

**Effect on requirements:** FR-ASK-1..8 are unchanged and still tested — the
suite exercises the page in both states. Nav rule 1's "exactly four" becomes "at
most four"; the rail is filtered once at import, so it never changes shape
mid-session. The gate is on the surface, not the safety: `ask.py` still sends
only the question and a static schema, never case data, because a flag someone
can flip must not be what stands between a corpus and a third party.

---

### D15 — a case body that is the serialised intake form is restructured, not shown verbatim

**Spec:** FR-CASE-4 and FR-CASE-5 treat a body as one opaque thing: the
description "appears above the comment stream", each entry has "author,
role/source, timestamp, body". §9.5 adds that case text is rendered as text.

**Built:** `intake.py` recognises one specific shape — several JSON objects
joined by a `~#~#~` separator, which is how the web intake form serialises
itself into a case — and turns it into a labelled field grid, the request as
its own block with the requester's line breaks intact, and a collapsed
`Original record` holding the payload byte for byte. Every other body reaches
the screen exactly as before. `parse` returns `None` the moment the text is not
that shape, and one unparseable segment condemns the whole body rather than
half of it.

**Why:** the spec assumed bodies are prose, and most are. The ones that are not
are a single seven-hundred-character line of `{"Field__c":"value",…}` with the
actual request buried in the middle, and the field that holds it stores real
newlines JSON-escaped, so the paragraph breaks the requester typed were on
screen as the literal characters `\n`. Everything was present and none of it
was legible. Restructuring is not a cosmetic preference here — it is the
difference between a support person reading a request and a support person
decoding one.

**Effect on requirements:** §9.5 is unweakened and load-bearing on this path.
Every value goes through `ui.label`, which escapes; nothing on a case page is
rendered as HTML or markdown, and `test_reading.py` asserts that with a payload
carrying a `<script>` tag. FR-CASE-4's "must not dominate" is unchanged — the
description keeps its collapse-when-long behaviour and now takes the same
reading as a comment, so a case whose description is the form is not the one
place left showing JSON. The formatted view is an addition and never a
replacement: the original is one click away on every body it touches, because a
restructured view is an interpretation and someone acting on a case has to be
able to check it against what the record literally says.

---

### D16 — three list columns give way at narrow widths, not one; the description is not among them

**Spec:** FR-LIST-4 lists nine columns in order, marks the description
"truncated if width allows", and grants exactly one — Funded — the note "may be
hidden at narrow widths".

**Built:** Funded gives way first, then Department, then PI, at table widths of
1060, 956 and 828 pixels. The description gives way at no width at all.

**Why:** the two halves of FR-LIST-4 turned out to be in conflict, and the
conflict is arithmetic rather than editorial. The table sets
`table-layout:fixed`, because without it one case whose description is a pasted
email thread sets the width of every column in the list. Fixed layout makes the
declared widths authoritative and hands the leftover to the single column that
declares none — the description. So "truncated if width allows" is decided by
subtraction, and when the subtraction reaches zero the outcome is not a narrower
column. It is a column zero pixels wide: still in the table, still in the DOM,
still carrying a header, with its content gone and no ellipsis and nothing
whatever to say so. At a 1024-pixel window — `MIN_WINDOW_SIZE`, the smallest the
app allows — that is exactly what happened.

Given the choice between a description that silently vanishes and two columns
that visibly leave, the columns leave. Department goes first because it is the
widest of the identifiers and the most inferable — a case with a PI usually
implies its department, and neither PI nor IRB can be recovered from it. Both
remain in the CSV export and on the case page, so nothing is unreachable; they
are absent from one view at one size.

The description had previously been the *first* column to drop, which is how
this was found: at 1280 pixels it was not dropping but was being handed 64
pixels, and the only column that says what a case is about was wrapping to one
syllable per line.

**Effect on requirements:** FR-LIST-4's order, contents, and the description's
"truncated" behaviour all hold, at every width from `MIN_WINDOW_SIZE` upward,
with a measured floor of 138 pixels. The thresholds are not preferences and are
not hand-tuned: `table.py` derives them from the declared widths, and
`test_reading.py` re-derives them from `lists.COLUMNS` in each regime and fails
if any of them would put the description below that floor. A future change to
any column's width therefore cannot re-open this quietly.

They are container queries rather than media queries, which is the other half of
the fix. A `@media (max-width: 1180px)` rule measures the viewport, and the
table is 240 pixels narrower than the viewport — so the rule that was supposed to
drop Funded never fired at any window size a person would use.

### D17 — the app opens on Search; Lists is the second destination

**Spec:** navigation rule 4 says "No Dashboard/Home page. The first screen is
**Lists → Open Cases**", and FR-LIST-1 makes Open Cases the default route.
Navigation rule 1 lists the destinations as "Lists, Search, Ask, SQL", in that
order.

**Built:** `/` is Search. Lists keeps everything else it had, at `/lists`, and
is second in the rail.

**Why:** requested after use. The rule this is really about is the one that
says there is no dashboard, and Search does not reintroduce one — the idle
screen is a heading and a text box, which is the sparsest screen in the
application and by some distance the fastest to draw. What changed is which
question the app assumes you arrived with. Lists answers "what is on my plate";
Search answers "where is that one case", and the second is the more common
arrival, including for someone who already has a case number in hand and wants
FR-SEARCH-3's shortcut.

It also happens to be the better landing page for a cold start, which was not
the reason but is worth recording: Open Cases needs three warehouse round trips
before it can draw a row, and the idle search screen needs none before it can
draw the box and take focus.

**Effect on requirements:** FR-LIST-1's default view is unchanged — Open Cases
is still what `/lists` renders and still what a saved view returns to. Nav rule
4's prohibition holds. Nav rules 1, 2, 3, 5 and 6 hold; only the order within
rule 1 differs, and `test_ui_actions.py` asserts the new one, that the
destination targeting `/` is Search, and that every target in the rail is a
registered route.

### D18 — every screen that queries before it draws says so first

**Spec:** §12 covers errors and inline validation. It says nothing about the
interval between asking for a screen and getting one, which on this warehouse
is one to five seconds for almost every screen in the app.

**Built:** the placeholder built for the case page (D15) is now in front of the
access probe, the list, the search result, the search page's filter values, and
the snapshot date on Settings. Each names what it is waiting for — "Connecting
to BigQuery…", "Loading open cases (weekly review)…", "Searching…".

**Why:** a desktop window that goes blank does not look busy, it looks broken,
and the second click that produces is a second 240 MB scan. The version of this
that only covered the case page left the two worst waits uncovered. The first
was the access probe in `shell.gated`, which every route goes through: it is a
BigQuery job, and on the first page of a session it is also where the client is
constructed and the credentials discovered, so the window was empty for several
seconds with not even the rail drawn. The second was `search.results`, where
the placeholder had to go *inside* the refreshable rather than around it —
sorting, filtering and paging all come back through `refresh()`, and each is
another query, so deferring only the first search would have covered the one
wait a reader expects and none of the four they do not.

**Effect on requirements:** none are relaxed. The load moves to a worker thread
and the draw stays on the event loop, so `load` callables must not touch the
UI; `while_loading` falls back to running inline when there is no event loop to
defer onto, which is what makes these pages testable synchronously. Two round
trips that used to happen during a draw — the corpus size behind FR-SEARCH-8's
boilerplate warning, and the freshness line on Settings — moved into the load
for the same reason.

### D19 — the window is selectable, and a row click stands down for a selection

**Spec:** FR-CASE-9 gives the case page a **Copy summary** action and says
nothing about selecting text, because selecting text is not a feature — it is
what a window does.

**Built:** the native window is created with `text_select=True`, the four inline
`user-select:text` overrides on the intake form are gone, and the click handlers
of the regions that navigate — list rows, search results, related cases, saved
views — decline to fire while something is selected.

**Why:** reported after use, as "I just need one name, or one sentence". None of
it was selectable, and nothing in this repository was the cause: pywebview
defaults `text_select` to False, which appends
`body { user-select: none; cursor: default }` to the document *after* the page's
own head. It cannot be seen in a browser, cannot be overridden by a stylesheet
without `!important`, and is invisible to every test here, so the search for it
starts on the case page and has to end at the window constructor. Copy summary
was the only way text left the application, and it copies a whole case.

Two things only turned up by measuring inside the real window. A rail chip
declaring `user-select: none` computed to `text`: WebKit reads the prefixed
longhand, so that rule had never once had an effect and nobody could tell,
because pywebview was switching selection off document-wide anyway. And making
the page selectable made every row-sized click target ambiguous — press in the
middle of a description, release at the end of it, and the browser reports a
click on the row, so highlighting a name would open the case and lose the
highlight. The guard is a `js_handler` that declines to emit, which keeps the
decision in the browser and the row on one handler rather than two.

**Effect on requirements:** UX-T3 is unaffected — the row is still the whole
click target and there is still no Open button. §9 is unaffected: selecting text
is a read, the corpus is already on the screen, and nothing new leaves the
process. Copy summary stays exactly as specified; it is now the shortcut rather
than the only door.

### D20 — the window says which connection it lost, and what to do about it

**Spec:** FR-START-2 covers one connection, Case Finder to BigQuery, and
`shell.connection_screen` implements it. The spec says nothing about the other
one — the window to the local server that draws it — because in a lean desktop
app that connection is a loopback socket in a single process and was not
expected to be a user-visible thing.

**Built:** `ui/reconnect.py`, a notice installed into the shared page head at
startup. It replaces NiceGUI's `#popup`, names the connection that was actually
lost, counts the seconds and the retry attempts while socket.io works, and —
when the server stops answering a plain HTTP request — stops saying
"reconnecting" and says to close the window and start again.

**Why:** reported as "the app lost connection with bigquery… I do not see any
progress on reconnecting… and the entry app is unresponsive". BigQuery was not
involved. What was on the screen was NiceGUI's own notice: two fixed strings in
the bottom-left corner, `pointer-events: none`, no elapsed time, no attempt
count, no advice, nothing to press. Every part of that report follows from it.
The reader could not tell which connection had gone, could not tell whether
anything was being attempted, and was not told that the only thing that would
help was closing the window.

Checking whether the reconnect works turned up the distinction the notice has to
make. socket.io retries indefinitely, so "wait" is honest — while the server is
there. If it is not, nothing can succeed: NiceGUI deletes a disconnected client
after `reconnect_timeout`, the window is a `daemon=True` child that outlives a
server killed rather than closed, and `main._free_port` puts the next launch on
a different port. One HTTP request to a static file separates the two cases, and
the notice reads it: refused, or accepted and then silent past a deadline, means
the program is not coming back to this window. The deadline is not decoration —
a wedged event loop accepts the connection and never answers, which without it
reads as a healthy server for as long as the wedge lasts.

Verified in the shipping engine rather than only in Chromium: both readings, the
attempt counter, the dismissed-to-a-pill state and the pass-through scrim were
driven inside WKWebView over pywebview's `evaluate_js`, which keeps working
after the socket is down because it does not use it.

**Effect on requirements:** none are changed. §9.5 is unaffected — the notice's
markup is a fixed string with no interpolation, so no corpus value can reach
HTML through it, and the probe asks for a static file rather than a page route
precisely so an outage does not re-run the access check once a second. It is
also the one screen deliberately not modal: the scrim passes the pointer
through, so the case behind a dead window can still be selected and copied (D19)
before it is closed.

### D21 — the dead window can restart the app, and waits for it before closing

**Spec:** nothing in the spec covers it. The window is treated throughout as a
view of the program, and the case where the view outlives the program does not
appear.

**Built:** `casefinder/window.py`, a small object handed to pywebview as
`js_api` from `main._window_args`, and two buttons in D20's notice —
**Restart Case Finder** and **Close window** — that appear only once that
bridge has answered.

**Why:** reported as "the app is not responding… you can provide options to the
user… one option could be, to restart the app", with a photograph of D20's own
notice. The investigation is worth recording, because most of what it ruled out
is what a report like that usually means:

| | |
|---|---|
| Close the window | the server notices and exits. Clean. |
| Close the terminal that launched it | SIGHUP reaches the whole process group; both processes go. Clean. |
| **Kill the server, or let it die of anything** | **the window is re-parented to PID 1 and stays on screen, drawn and dead** |
| Click the window's own close button afterwards | the process does exit. |

No crash reports, and no evidence the server dies on its own. The window in the
photograph post-dated the D20 commit by eleven minutes and was a leftover from
this project's own native test runs, which kill servers directly — six of them
had accumulated, invisible to `pkill` because a spawned child's argv is
`python -c from multiprocessing.spawn import spawn_main`. So there was no crash
to fix. The defect is the third row: when the server does go, for any reason,
the window survives it and the best D20 could do was describe the exit.

It does not have to. The window process is alive; only its parent is gone. The
`js_api` bridge runs page → window process and never touches the websocket, so
it works in exactly the situation where nothing else does — a page whose server
had been killed went on calling into it once a second, started a replacement
that outlived the window launching it, and shut itself down on request.

Two details are the whole quality of it. The replacement is signalled by a file
in a 0700 directory whose path is passed in the environment, and the signal is
sent from `on_connect`, not `on_startup`: startup is uvicorn binding a socket at
0.55 s, and the window is not on screen until 1.9 s. Closing on the earlier
signal would blank the screen for over a second immediately after someone
pressed Restart, which looks exactly like the app dying again. Measured on the
handover, the new window appears at 4.5 s and the old one goes at 5.1 s — the
two overlap, and there is never an empty screen. And `close` is `os._exit`
rather than `webview.Window.destroy()`, because destroy takes the window off the
screen and leaves the process running with nothing to show, which is how
invisible copies accumulate in the first place.

**Effect on requirements:** none are changed. §9.3 still holds — the window
process writes one empty file to a temporary directory and removes it again, and
nothing from the corpus passes through this path. §9.6 is unaffected: the bridge
is process-local, exposes exactly three verbs that take no arguments, and opens
no port. A browser has no second process, gets no buttons, and still gets the
sentence telling it what to do by hand.

### D22 — a sixth filter, and it is Owner

**Spec:** FR-LIST-6 says "Exactly five primary filters" and lists them — Open
only, Status, Department, PI, IRB — then allows funding status as "#6 only if
[the stakeholder] confirms it as minimum scope". Owner is not on the list, and
the allowance was written for a different candidate.

**Built:** `owners` as a filter dimension end to end — a `TriageFilters` field,
a bound array clause, an entry in the facet query, a control in the row and in
its disclosure, a key in the saved-view allowlist — plus
`lists.focus_on_owner`, a **Cases owned by …** item in the case page's overflow
that opens the list as that person's open queue.

**Why:** asked for directly, from a case page, next to the OWNER cell. But it is
worth saying why the answer was a filter and not a search. Owner was already a
column in FR-LIST-4's list and a sort key in FR-LIST-5. It was the only
dimension the app would show you a value for and then refuse to act on: you
could sort a queue by owner and read whose it was, and there was no way to ask
for one person's. That is a gap in the five rather than a sixth idea, which is
the argument for making the exception here and not generally.

Three things it touched that the other five did not:

- Owner is not a field on the case. `dim_case` carries an `owner_id` into the
  Salesforce `User` table, so the filter expression is only valid where that
  join is in scope, and the facet query had to grow the join to offer the list.
- The row stopped fitting. Measured in the real shell rather than estimated:
  six controls occupy 958px plus five 10px gaps, and a page is given the
  viewport less 240 for the rail and its own padding — so the row needs a
  1248px window, and at 1220 it silently wrapped onto a second line. A wrapped
  row is worse than the disclosure FR-LIST-7 provides for exactly this, so
  `NARROW_PX` moved from 1180 to 1260 with the control that caused it.
- The jump goes through `ListState.apply` rather than writing the filters
  directly, because `lists.render` re-applies the default view whenever the
  column list is empty — which it is until Lists has been visited once in a session. Setting
  the filters by hand would have worked on every visit but the first.

**Effect on requirements:** FR-LIST-6's count is now six; nothing else in it
changes, and funding is still a dimension without a control, still pending the
confirmation SR-13 routes elsewhere. §9.3 is the one that deserved an argument
rather than a nod, because a saved view now writes a person's name to a file in
the user's home directory. It is the same name `pis` already writes and the same
one the metadata-only CSV already exports: a Salesforce User, a member of the
support team, picked from a facet, not a research subject and not text anyone
typed into a case. It is called out in `views._PERSISTABLE` rather than waved
through, and if that judgement is ever revisited, dropping `"owners"` from
`_PERSISTABLE_FILTERS` makes existing files stop honouring it on load — which is
the withdrawal path §9.3 asks for, and which has a test.

### D23 — the read-only guard asks BigQuery rather than only the text

**Spec:** §9.4 defines the guard as a scan of the query text: strip comments,
reject empty, reject multi-statement, reject mutation keywords, require a
`SELECT` or `WITH` prefix.

**Built:** that scan, plus a second check that decides. `run(preflight=True)`
already pays for a dry run to price the query; a dry-run job also reports
`statement_type`, which is BigQuery's own reading of what was submitted.
Anything that is not `SELECT` is refused, and `bq.plan` is the single entry
point that does both so neither check can be acquired without the other. The
text scan stayed, as a pre-filter: it refuses a pasted `DELETE FROM dim_case`
without a round trip to a warehouse holding a writable credential, and it names
the keyword, which a parser verdict cannot.

**Why:** scanning text for keywords cannot tell a statement from a string that
contains its name. The guard refused
`WHERE STRPOS(LOWER(body_clean), 'update') > 0` — a search for the word
"update", which on a corpus of support cases is an ordinary thing to want — and
`status = 'Call scheduled'`, and any literal holding a semicolon. It was worse
on the Ask page, whose prompt tells the model to write exactly that shape: the
application generated valid SQL and then rejected its own output as a mutation,
which reads to a user as the model being broken.

Blanking literals before the scan fixes the false positives, and `_scrub` does
that in the same left-to-right pass that removes comments, because neither
ordering works alone — comments can contain quotes and strings can contain
`--`. It also learned `#`, which GoogleSQL accepts and the old scan did not, so
`SELECT 1 # update later` was refused too.

The parser check is what stops the next such gap from mattering, and it closes
one the regex never covered: a multi-statement script reaches BigQuery as a
single job whose statement type is `SCRIPT`.

**Effect on requirements:** §9.4's step order is unchanged and still tested;
what changes is that it is no longer the last word. A client that reports no
statement type falls back to it, so an unavailable verdict is not a failing one.

### D24 — the cache deletes what it expires, and is bounded

**Spec:** §9.3 requires results to live in process memory only, with no disk
backend.

**Built:** that, and three properties it did not have. Expired entries are
removed — by a reaper on a timer as well as on the next read of the key — rather
than checked on read and otherwise left in the dictionary. Entries are capped
and evicted least-recently-used first. A load already in flight for a key is
shared rather than started again.

**Why:** "no disk backend" was true and not sufficient. The retention policy
this application states is the process lifetime, and expiry was only shadowing:
a case body whose fifteen minutes had passed hours ago was still resident, and
so was still reachable in a swap file or a crash dump. "Will not be served" and
"has been deleted" are different promises, and the second is the one §9.3 is
making. The reaper is a daemon thread started from `main` rather than a NiceGUI
timer, because the case it exists for is an idle window.

The cap is a separate concern with the same owner: a desktop window is open all
day, every case opened adds entries, and nothing removed them. It counts
entries rather than bytes — sizing a Python object graph is expensive and
inaccurate, and a predictable ceiling is worth more here than a precise one.

Single-flight was the cheapest of the three. The loader still runs outside the
lock, so a slow query does not serialise the app; what the lock now holds is the
*claim* on the key, so two clicks on the same case cost one 237 MB scan.

### D25 — a cached page says so instead of replaying what it cost

**Spec:** §5.4 asks for query cost to be shown when it is worth saying.

**Built:** `Page` carries `served_from_memory`, set on the way out of the cache
for the reader that got a hit. `is_trivial_cost` counts it as nothing worth
saying, so the cost line disappears on a cached page rather than misreporting —
the same treatment a BigQuery cache hit already got. `cost_note` answers
"already loaded this session — free" for any caller that asks anyway, because a
property that reports cost must not lie about it.

**Why:** the Page is stored whole, including `bytes_processed`, so every
revisit inside the TTL window reported *scanned 245 MB* at a reader who had just
been handed a value out of a dictionary. That overstates the spend, and it makes
a working cache look like it is not there — which is precisely the evidence
anyone would use to decide whether the caching is worth keeping.

`bytes_processed` still describes the query that produced the rows. The new
field describes this request. Once a Page is cached the two are not the same
thing, and the fix was to stop conflating them.

### D26 — cache keys are read off the filter dataclass

**Spec:** §7.2 requires each distinct question to have its own cache entry.

**Built:** `data._filters_key`, which walks the dataclass with
`dataclasses.astuple`, replacing the hand-written field lists in `triage` and
`search`.

**Why:** `triage` spelled out all seven `TriageFilters` fields under a comment
explaining that a dimension missing from the list is not a stale entry but the
wrong list under the right title — two owners sharing one key, and the second
served the first one's rows. That is a correctness bug in an operational tool,
and the mitigation was a test standing guard over a mistake the code invited.
Deriving the key removes the opportunity: a field added to the dataclass is part
of the key the moment it exists. The test now walks both filter classes and
asserts the property rather than the field list.

### D27 — the shell was four modules wearing one name

**Spec:** §3.1 gives the shell the rail, the content region and the error
surfaces.

**Built:** `ui/theme.py` (the visual language and the two stylesheet
installers), `ui/state.py` (§4.5 session state, and `ListState.apply`),
`ui/errors.py` (§12), `ui/components/actions.py` (the button vocabulary), and
`ui/shell.py` reduced to the rail, the layout and the connection gate.
`ui/lists.py` likewise gave up its column catalogue to `ui/list_columns.py` and
the Saved Views screen to `ui/saved_views.py`.

**Why:** every other module in the project does one thing, which is what made
these two conspicuous. The practical cost was in the imports: a component that
wanted a colour, or a page that wanted a button, imported the navigation rail to
get it, and `ui/lists.py` held two unrelated screens sharing nothing but an
import list. `ListState.apply` moved with the state it writes — two screens open
a saved view, and the second should not import the first to do it.

**Effect on requirements:** none. The rules these modules enforce are unchanged
and their tests are the same assertions against the same rendered trees; UX-T1
still counts `cf-primary`, and the rail still refuses to grow a fifth
destination.

---

### D28 — a preview is one line of prose, not a slice of the record

**Spec:** FR-LIST-4 puts a description in the list, "truncated if width allows".
§6.3 puts a matched snippet under each search result.

**Built:** both go through `models.flatten` and `models.strip_leading_label`
before they are shown. Full bodies do not.

**Why:** two things were reaching the screen that say nothing about any case.

The intake form serialises itself into a case body as JSON, so every newline
the requester typed is stored as the two characters `\` and `n`. `intake.py`
decodes them when it recognises the payload, which is why a case page reads
correctly — but a search snippet is cut out of the middle of that same body
with `SUBSTR` and never reaches the parser. Every snippet from a form-submitted
case arrived with `...quality of care outcomes\n\nQuestion: Would like to
request an update...` on screen, escapes and all, in prose that is otherwise
perfectly readable. Found by looking at the running application; nothing in the
suite drew a snippet from a real body.

And `Summary:` opens very nearly every description in the corpus, so the first
nine characters of the Description column were identical on every row — in the
one column FR-LIST-4 refuses to let drop at narrow widths, which makes them the
most expensive nine characters on the screen. The strip is an allowlist of the
form's own field names rather than a general `Word:` rule, because a
description opening `Question:` or `Availability:` is answering something and
the label is the only thing that says what. Like `strip_attribution`, it never
strips to nothing.

**Effect on requirements:** none, and the line is deliberate. A preview is one
flowing line and may be tidied; the body on the case page is left exactly as
the record has it, so a body that really does contain a backslash and an `n` —
pasted code, a Windows path — is still telling the truth where someone might
act on it.

---

### D29 — the Funded column shortens a closed picklist to fit

**Spec:** FR-LIST-4 lists funding status as a column, and the one column that
may disappear at narrow widths.

**Built:** `list_columns._SHORT`, three entries, on top of the existing
`Funded - ` prefix strip.

**Why:** measured before it was changed. `Funding_Status__c` holds eight values
across the current era — 888 Unfunded, 367 not recorded, 332 Grant, 66
Departmental/Gift, 25 Seeking Funding, 23 Funding Status Unknown, 16 Industry
and 4 Federal, summing to all 1,721 cases. It is a closed picklist, not the
free-text field it looked like from the screen, and that is what makes an
exhaustive map honest where a bucket would not be.

Re-counted on `som-nero-phi-naras-ric` (D32). The shape of the argument is
unchanged and no new value appeared, but the census lost an entry: the single
free-text answer this corpus does not contain. The fall-through that rendered
it is still there and now has a test of its own, because the field is a
picklist by intent rather than by constraint.

Three of the eight did not fit 104px, and for two of them truncation produced
something worse than a blank cell rather than merely shorter. `Departmental/
Gift` became `Department…`, which reads as a department name two columns away
from the Department column. `Funding Status Unknown` became `Funding Sta…`, an
ellipsised copy of the column header, on the one value whose entire meaning is
that nothing is known — the reader cannot tell it from a rendering fault. No
width solves the second one; 22 characters was never going to fit a column the
spec allows to be dropped entirely.

**Effect on requirements:** none, and the boundary is deliberate. The map is
display only: `_export_csv` reads the row rather than the cell, so the metadata
CSV still carries `Funded - Departmental/Gift`; the cell's `title` carries the
full value on hover; and `TriageFilters.funding` still matches the stored
strings. Funding remains the dimension without a control (FR-LIST-6, pending
SR-13) — when it gains one, the control has to offer the raw values, because a
label that does not match the value it filters on is a lie about the list, and
a test says so.

The single free-text case is left exactly as stored. Constraining the intake
form so a ninth value cannot be typed is a data-team change, not an app one.

---

### D30 — the filter chips are styled against Quasar, not on top of it

**Spec:** §3.3 sets the visual language; FR-LIST-7 asks for one compact filter
row.

**Built:** the chip stylesheet rewritten — every selector three classes deep,
the border and focus ring moved onto Quasar's own pseudo-elements, the floating
label dropped for an accent state, the menu capped, and the tooltip moved above
the control.

**Why:** the row had five defects and only one of them was visible as a defect.
They were found by photographing the rendered controls rather than by reading
the file, which is the only way three of them could have been found at all.

*The declared size was not the rendered size.* `.cf-select .q-field__control`
is two classes, and so is Quasar's `.q-field--dense .q-field__control`; its
stylesheet is served second, so every tie went to Quasar. The chip declared
30px and rendered at 40px — while `.q-field__marginal`, which Quasar does not
set for dense fields, kept the 30px it asked for, leaving the clear and
dropdown icons five pixels above the centre of the control. Nothing errored and
nothing looked wrong in isolation; the numbers in the file simply were not the
numbers on the screen.

*And sizing the control was not enough.* With the chip finally 30px, the text
still sat low in it. `.q-field--dense .q-field__native` carries its own
`min-height:40px`, which the rule styling the chip's text never touched — so
the text box hung ten pixels out of the bottom of the control, and its own
`align-items:center` centred the label in that box rather than in the pill.
Every label in the row rendered five pixels below centre. The same class of
mistake as the one above and a separate instance of it, which is why the test
pins the text box and the control separately.

*The palette was not being used.* Quasar paints an outlined field's border on
`:before` and its focus ring on `:after`, so the `border` set on the control
itself sat underneath both and was never seen. The row was outlined in
`rgba(0,0,0,.24)` and focused in Quasar's blue — neither of which appears
anywhere else in this application.

*An empty chip and a filled one were different widgets.* With a value chosen,
Quasar lifts the label into the border and stacks the value beneath it. There
is nowhere for a label to go in a 30px pill with a 999px radius, so it landed
on the curve. The label is gone; a chip now reads the dimension when nothing is
chosen and the choice when something is, one line either way, and carries the
accent treatment the rail already uses for "you are here". The dimension
survives in `aria-label`, which is also what the tests look chips up by.

*The menu was not the size of anything.* Left to itself it is as wide as its
widest option, and one PI in this corpus is an entire study title — so a 170px
chip opened a 438px menu that escaped the content area. Capped at 340px and
wrapped rather than ellipsised, because the reader is choosing between these
and has to be able to tell them apart.

*The tooltip covered the menu it belonged to.* A tooltip under a control that
opens its menu directly underneath lands on the menu's first option, and did:
`Filter by pi` sat on top of the first PI in the list. It anchors above now,
with a delay so it does not fire on the way to a click. The text also stopped
lowercasing the label — the two labels that are acronyms, `PI` and `IRB /
protocol`, are exactly the two a mechanical rule gets wrong.

**Effect on requirements:** none. FR-LIST-7's row and disclosure are unchanged,
and UX-INV-5's quiet status is better served: an active filter is now legible
without reading its text. `test_visual.py` pins the specificity rule, the
text-box height, the palette, the focus state, the menu cap and the tooltip
anchor, and each of those assertions was checked by reintroducing the defect it
describes.

---

### D31 — the case page is rebuilt around what a reader came for

**Spec:** section 6.4 and FR-CASE-1..11 describe the case page as a header, a
metadata grid, four tabs and a related-cases list, in that order.

**Built:** the same content, reorganised around the question a support person
arrives with rather than around where the data came from.

**Why:** the old order was the order the data arrives — case fields, comments,
messages, timeline, files, related — and every complaint about the page came
out of that one decision.

*The same payload rendered three times.* The web form arrives inside the case
body, so Comments parsed it into a grid, the duplicate turn beside it parsed it
again, and Timeline printed the raw JSON as the most prominent thing on the
tab. `intake_form.body` is now the one reader every body goes through, the
duplicate turn is dropped by `models.without_repeats`, and the turn that *is*
the request is dropped by `_without_the_request` because the request is pinned
above the thread instead.

*And it was not always in the description.* The first version of this looked
for the form there, which is where it sits on some cases and not on others —
on a good many the description is pasted email and the form arrives as the
first turn. Those cases kept the request exactly where it had always been:
entry one of a hundred and fifteen. `_submission` now takes the first thing
that parses, description first, wherever the integration filed it.

*Seven more of its fields described the person, not the request.* A name split
across two fields, an address, a telephone number, a rank, a department. They
are in the rail now, under `Requester`, and `intake.mark_requester` stops the
grid drawing them — the same fold, for the same reason, applied to the fields
the case does not itself show.

*And the request arrived as one paragraph.* Summary, Description and Question
are three answers to three prompts and the integration concatenates them, with
the requester's contact details appended after. `intake.sections` splits them
back apart and drops the contact block, which the form has already collected in
its own fields. Run together, the question is the part that disappears — and
the question is what a support person is answering.

*Nine of its fields were already on the page.* Subject was the title, PI name
the PI, funding status the funding, origin "came in via". Five more were
duplicated inside the form — an address as `Email` and `ContactEmail`, a SUNet
id on both objects, a department under three names, two byte-identical queue
blobs. `intake.reconcile` folds those away with a count and keeps the payload
whole behind `Original record`. Twenty-eight fields become about ten.

*And one of them was not a duplicate at all.* The form says the IRB protocol is
`TBD`; the case says `41288`, approved. The requester filled the form before
the protocol existed. Shown flat and hundreds of pixels apart, that read as the
page repeating itself; it is now the one thing on the form that is marked.

*A hundred and fifteen entries with no way through them.* Oldest-first and flat
optimises for reading a case from the beginning, which is the rarest thing
anyone does with an active one. The opening and the latest are drawn, the
middle folds behind its own count and date span, and each change of month is
marked — which on a case running April to September is the difference between
a scroll position and a date.

*Related cases below all of it.* Twenty-three of them after the thread, ranked
by recency with the reason printed at the end of the row. They are in the rail
now, grouped by relationship strength, strongest group open.

**Effect on requirements:** three changes, all deliberate.

FR-CASE-5 and FR-CASE-7 become one surface. Comments and Messages were the same
rows at two densities — same table, same order, differing by a subject and a
character count — and the second tab paid for its own ~256 MB scan of the body
column to fetch them. `comments_stream` now carries both, `case_messages` is
gone, and the density is a control inside the conversation. A reader who
switches to the index reading pays nothing.

FR-CASE-10 ranks by strength rather than recency, and moves to the rail.

FR-CASE-3's em dashes are gone from the rail. That rule is right for the grid
it was written for — four attributes across a reading column, in fixed
positions, where a blank cell and a missing row look different. A rail is one
column with no fixed positions, so an unrecorded Type costs a whole line of a
panel that also has to hold the related cases, and Type and Reason are
unrecorded on most cases in this corpus. Nothing is hidden: the values are
still on the case, and there were none.

FR-CASE-2's metric strip is gone. Status, owner and age moved to an identity
bar that stays put at every scroll position, which is where they are actually
needed on a long thread; the rest is in the rail. UX-INV-6 still holds — the
rail is one column of label/value pairs, and `test_ui_actions` still asserts
that nothing on the page is a card.

UX-INV-4 holds too, on the thread column rather than on the page: the page is
now two things, prose that has to stay narrow and a rail that is chrome. Below
1180px the rail folds above the thread, the same move the filter row makes at
its own breakpoint, because a 1024px window less a 280px rail is not a reading
measure.

### D32 — the default project is `som-nero-phi-naras-ric`

**Spec:** §9.1 and §11 name `som-rit-phi-starr-dev` as the default data project,
overridable with `CASEFINDER_PROJECT`.

**Built:** the same override, with `som-nero-phi-naras-ric` as the default.

**Why:** the corpus moved. The mechanism the spec describes is untouched — one
environment variable, one line in `config.py`, and `Era.table()` remains the
only place a table reference is assembled — so this is a change of value rather
than of design.

**Effect on requirements:** none. Verified against the new project rather than
assumed — `pytest -m warehouse`, 31 passed in 59.9 s.

The dataset layout is identical: `salesforce_current`, `salesforce_marts`, and
the `salesforce_raw.Case` / `salesforce_raw.User` join all resolve under the new
project with no code change beyond the id, and the join is still 1:1 and
complete at 1,721 of 1,721.

The corpus is the same corpus, seven cases further on. Both eras gained exactly
seven — 1,714 → 1,721 and 41,526 → 41,533 — which is a fresher batch load and
not a different archive. Three measured figures were re-counted and are carried
into the places that quote them:

| Figure | Was | Now |
|---|---:|---:|
| Current era cases | 1,714 | 1,721 |
| Archive era cases | 41,526 | 41,533 |
| Conversation turns, archive | 280,001 | 280,505 |
| Cases with no department, archive | 33,821 | 33,821 |

The department figure did not move: all seven new cases have one. Its
denominator did, so `queries.py`, `models.py` and `test_queries.py` now read
"33,821 of 41,533".

The one thing that changed shape rather than size is the funding census — see
D29. The warehouse suite's own bounds are deliberately loose (`1_500 <= current
<= 3_000`) so that a batch load does not fail the build; they were left loose,
and only the "documented as" text in the failure message was updated.

---

### D33 — a wheel is offered alongside the source folder

**Spec:** §11.1 fixes distribution at "source folder + setup script, not a signed
binary", and §11.5 defines uninstall as deleting that folder.

**Built:** both. The installer scripts are unchanged in kind, and `uv build`
additionally produces `casefinder-<version>-py3-none-any.whl` with a `casefinder`
console script. `uv tool uninstall casefinder` removes that copy.

**Why:** the spec's reasons for refusing a binary — no admin rights, no Apple
Developer certificate, no Authenticode, a reproducible `uv.lock` — are reasons
against *signed native binaries*, and a pure-Python wheel gives up none of them.
What it removes is the part of the source-folder model that was never a design
decision: handing a support analyst a folder of source, a `.gitignore` and a test
suite in order to install an application, and asking them not to move it,
because `run-mac.sh` resolves everything relative to where it sits.

**Effect on requirements:** none removed. §11.2 and §11.3 remain exactly as
specified for the checkout path.

The mechanism has one sharp edge, and it is the reason this entry is long.
NiceGUI's native mode opens the window in a *second process*
(`multiprocessing.Process` in `native_mode.activate`), and the window's
arguments — `text_select`, `min_size`, and the `js_api` object that puts the
**Restart Case Finder** button on the dead-window notice — are not pickled and
sent. They are read out of `app.native.window_args` by the child, after the child
has re-imported `__main__` for itself.

How the child re-imports `__main__` depends on `sys.modules["__main__"].__spec__`.
Run as `python -m casefinder.main` there is a spec, `spawn` records
`init_main_from_name`, and the child imports the module — reaching `main()` under
the `__mp_main__` half of the entry guard, which is why that guard names both
spellings. **A console script has no spec.** `spawn` records
`init_main_from_path` pointing at the shim in `~/.local/bin`, the child runs the
shim under the name `__mp_main__`, the shim's own `__main__` guard is false,
nothing sets the window arguments, and the window opens with an empty
dictionary.

Nothing raises. The app starts and draws, and is simply missing text selection,
its minimum size, and its only way out of a dead window — the failure mode this
project has already spent a commit on.

So `main.cli`, the console-script entry point, assigns
`importlib.util.find_spec("casefinder.main")` onto `__main__` before launching.
`main()` itself deliberately does not: it is called directly by `test_window` and
`test_reconnect` under pytest's own `__main__`, and pinning there would rewrite
it mid-suite. `test_packaging.py` asserts the switch against the real
`multiprocessing.spawn.get_preparation_data` rather than describing it, and
separately asserts that `cli` calls the helper — a test of the helper alone would
pass with the call site deleted, which is the only way this can regress.

Verified on the built artifact, not inferred: installed from the wheel into a
throwaway tool directory, the console script reports `init_main_from_name:
casefinder.main`.

---

### D34 — the self-check is a command in the app, not a step in the installer

**Spec:** §11.2.5 asks `install-mac.sh` for "a minimal native-window self-check
if practical"; §11.3 requires the Windows installer to check the webview runtime
and surface a remediation message.

**Built:** `casefinder --check`, seven checks — python, app, webview, presets,
gcloud, credentials, BigQuery — printing one line each with indented remedies,
exiting non-zero if any failed. Both installers now call it instead of carrying
their own copy.

**Why:** the checks were two heredocs, one per installer, and the installers are
not part of the wheel. Everything they knew would have left with them — above all
the WebView2 Evergreen Runtime URL, which existed nowhere else in the product and
is the single most likely thing a Windows user needs. A check that only runs at
install time is also the wrong shape: the machine it describes changes afterwards,
and "it worked last week" is when someone actually needs it.

It deliberately does not open a window, which would be a better check and a worse
tool — it could not run over SSH, or in the terminal a user has just been asked to
paste from, and it would leave a window someone has to close. Importing the
platform backend is what the installers already did, and it distinguishes "the
runtime is missing" from "the window opened grey". Known limitation 7 says so.

**Effect on requirements:** §11.2.5 and §11.3 are satisfied more completely than
specified, on more machines than the installers reach.

Every path it prints goes through `config.tilde`, which collapses the home
directory to `~`. The output is designed to be pasted into a support request, and
an absolute path names the person whose machine it is. Settings does the same, for
the same reason.

---

### D35 — the shared presets live inside the package

**Spec:** §7.4 and §16 describe a "distributed `views.json`" / "app `views.json`",
which in a source folder means the file beside the application.

**Built:** `casefinder/views.json`, force-included in the wheel.
`CASEFINDER_VIEWS_PATH` overrides it exactly as specified.

**Why:** "beside the app" has no referent once the app is a wheel — the package's
parent is `site-packages`. The distinction is invisible in a checkout, where the
repository root and the package's parent are the same directory, which is what
makes it worth an entry: resolving one level too high is correct everywhere it is
tested and wrong everywhere it is installed.

The failure is silent. `views.shared_views` treats an unreadable file as "no
shared views" and returns `builtin_views()` without saying so, so a wheel built
without the file starts up perfectly and is missing presets nobody thinks to look
for. Three things now catch it: the `presets` line of `--check`, a test asserting
that `Unassigned queues` — the one preset in the file and not in the code — is
actually loaded, and `release.sh` refusing to publish a wheel the file is not in.

**Effect on requirements:** none. Overriding the presets is now
`CASEFINDER_VIEWS_PATH` rather than editing the shipped file, which is the better
instruction for an installed copy in any case, since `uv tool install --force`
overwrites it.

A related hole opened with packaging, and is closed by
`test_every_file_in_the_package_is_tracked_by_git`. Hatchling chooses what to
package by asking git what is *ignored*; `tests/corpus_guard.py` scans what git is
*tracking*. An untracked scratch file under `casefinder/` sits between those two
questions — it ships in the wheel, and neither the guard nor the pre-commit hook
can see it. Under the source-folder model nothing was ever shipped, so this is an
exposure the wheel creates, and it is a PHI control rather than hygiene. The test
caught a real untracked file on its first run.

---

## 5. Known limitations

Carried from §14, with current status.

1. **Case-open scan volume** — ~240 MB, because `fct_conversation_turn` is not
   clustered on `case_id`. Warehouse-side fix; highest-value optimisation
   available. Unchanged.
2. **Search is substring matching** — not stemming, not BM25. Relevance is
   primarily mention count. Unchanged.
3. **Snapshot staleness** — a list can show a case as open after it was closed in
   live Salesforce. Mitigated by the freshness banner, not solved.
4. **Sparse extended metadata** — PI, IRB, department, and funding are missing on
   a substantial fraction of cases. `models.py` renders absence explicitly rather
   than as an empty cell.
5. **Generated SQL can be confidently wrong** — valid, cheap, and answering a
   different question than the one asked. Mitigated by mandatory review before
   execution.
6. **Attachments are pointers** — Box remains the operational file source, per
   SR-11.
7. **Native-mode webview surface** — depends on WebKit (macOS) and Edge WebView2
   (Windows). Both installers check for it at install time and both platforms
   have a documented browser fallback, but this needs re-validating each release.
8. **Local-app threat model** — no defence against a compromised laptop or an
   authorised user taking a screenshot. Out of scope by design; the same exposure
   exists with direct BigQuery access today.
9. **Gemini model availability shifts** — mitigated by probing candidates with a
   real two-token request rather than trusting construction to succeed, caching
   the outcome, and honouring `CASEFINDER_VERTEX_MODEL` as an override.
10. **A cost estimate is not a runtime estimate** — the figure shown before a
    free-form or generated query runs is bytes scanned, which is what BigQuery
    bills for and all it can predict. A query can be honestly priced at a
    fraction of a cent and still take an hour. Bounded by the 120-second job
    ceiling (D8), but the estimate on screen remains a cost estimate and should
    not be read as a speed one.

---

## 6. Provenance

The v1 Streamlit implementation is the normative reference for the data contract
(§5), query semantics (§7), and security posture (§9). Its four portable modules
— `__init__.py`, `config.py`, `bq.py`, `queries.py`, `ask.py` — were vendored
into this repository as an unmodified snapshot and committed first, so `git log`
separates original v1 behaviour from v2.1 changes. `app.py` and `launch.py` were
deliberately not vendored; they are replaced by `ui/` and `main.py`.

The working copy they came from:

```text
~/Documents/Astra/Workspaces/salesforce-cases/.astra/tasks/4DD4B29F/casefinder
```

That is a machine-local Astra task directory — provenance, not a dependency.
Nothing in this repository reads from it.
