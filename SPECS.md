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
| Automated tests | **463 passing**, ~1.7 s, no network access required |
| Warehouse tests | **30 passing** against live BigQuery, ~45 s, ~2¢ (opt-in: `pytest -m warehouse`) |
| Lint | `ruff check .` clean |
| Live warehouse | All 7 routes return HTTP 200 against `som-rit-phi-starr-dev` with no tracebacks |
| Native window | `python -m casefinder.main` opens a pywebview window on `127.0.0.1` with an OS-assigned port |
| macOS installer | `./install-mac.sh` completes on a clean path, exit 0, self-check reports BigQuery reachable |
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

6,492 lines across 25 modules.

| Module | Lines | Responsibility |
|---|---:|---|
| `queries.py` | 759 | Pure `(sql, params)` builders. No I/O, no globals, no client. |
| `models.py` | 588 | Typed rows; the single place that decides how a missing value is displayed. |
| `ui/lists.py` | 572 | §6.2 — triage lists, filters, saved views, paging, CSV. |
| `ui/case_detail.py` | 486 | §6.4 — header, metadata, comments, messages, timeline, files, related. |
| `ui/shell.py` | 480 | §3.1 — rail, content region, era indicator, error surfaces. |
| `ui/search.py` | 421 | §6.3 — idle state, results, snippets, paging, case-number shortcut. |
| `data.py` | 315 | The UI↔query seam: builder + cache + model, one function per page need. |
| `views.py` | 287 | Saved views, and the allowlist of what may be persisted. |
| `bq.py` | 261 | One client, byte caps, cost estimates, the read-only guard. |
| `ask.py` | 231 | §6.5 — question in, SQL out; nothing else in the prompt. |
| `intake.py` | 225 | Reads the serialised intake form out of a case body (D15). Pure. |
| `ui/components/table.py` | 217 | The list table; clickable rows, no Open button, container-query columns (D16). |
| `ui/ask_page.py` | 214 | §6.5 UI — generate, review, then run. |
| `config.py` | 202 | Every environment variable and its default. |
| `ui/components/filters.py` | 190 | The compact filter row and its disclosure. |
| `ui/sql_page.py` | 190 | §6.6 — free-form SQL with a priced dry run. |
| `ui/settings.py` | 168 | §6.7 — era, connection, Ask availability, about. |
| `cache.py` | 110 | TTL cache with no disk backend, deliberately. |
| `main.py` | 113 | Routes, and the loopback-only native window. |
| `ui/components/intake_form.py` | 99 | Draws what `intake.py` parsed — as labels, never as HTML. |
| `ui/components/loading.py` | 104 | Says a slow thing is happening, and gets the work off the event loop. |
| `ui/components/pager.py` | 88 | The range line and its two arrows; one pager for every paged screen. |
| `ui/components/metadata.py` | 69 | The flat metadata strip that replaced five metric cards. |
| `ui/components/empty_state.py` | 56 | Every "nothing here" screen, including the failure ones. |
| `ui/components/freshness.py` | 38 | The stale-snapshot banner. |

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
| Search: idle, execute, shortcut, parsing, scope, results, limits, paging, empty | FR-SEARCH-1..12 | `ui/search.py`, `queries.search`, `ui/components/pager.py` | `test_search_semantics.py`, `test_pagination.py` |
| Case: comments-first, header, metadata, copy summary, tabs, related, unknown | FR-CASE-1..11 | `ui/case_detail.py` | `test_ui_actions.py`, `test_visual.py` |
| Case body rendering, and the wait before one appears | FR-CASE-4, FR-CASE-5 (D15) | `intake.py`, `ui/components/intake_form.py`, `ui/components/loading.py` | `test_intake.py`, `test_reading.py` |
| The wait before any screen appears | D18 | `ui/components/loading.py`, and every page that queries | `test_reading.py` |
| Ask: layout, Enter, no case data, review, guards, availability | FR-ASK-1..7 | `ask.py`, `ui/ask_page.py` | `test_ask.py` |
| SQL: layout, read-only, errors | FR-SQL-1..4 | `ui/sql_page.py`, `bq.assert_read_only` | `test_read_only.py` |
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
| Read-only (§9.4) | every submitted query passes `assert_read_only`, including generated SQL |
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

Fourteen departures from the specification. Each names what the spec says, what
was built, and why.

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

**Built:** the last two are inverted — keyword check before shape check.

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

### D9 — four environment variables beyond the §10 table

**Spec:** §10 tabulates the configuration surface.

**Built:** four additions.

| Variable | Default | Why |
|---|---|---|
| `CASEFINDER_QUERY_TIMEOUT` | 120 s | The wall-clock ceiling described in D8. |
| `CASEFINDER_FACET_CACHE_TTL` | 3600 | Filter values change on the warehouse's load cadence, not on the 15-minute result cadence. Re-querying them every 15 minutes buys nothing and costs a visible pause on the filter row. |
| `CASEFINDER_PERSONAL_VIEWS_PATH` | per-OS app data dir | §11.5 requires the personal saved-view file to be documented and separable for uninstall. Overriding its location is what makes that testable without writing to a real user profile. |
| `CASEFINDER_ASK` | false | Whether the natural-language mode is offered at all — see D14. |

Both have working defaults; neither needs to be set.

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
no request can turn into a 41,526-row response, and reaching result 501 takes a
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
