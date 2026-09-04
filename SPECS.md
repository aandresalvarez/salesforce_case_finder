# Case Finder — as-built specification

**Version 2.1.0 · 3 September 2026**

The normative specification is
[`CASE_FINDER_SPECS_NICEGUI_LEAN_v2.1.md`](CASE_FINDER_SPECS_NICEGUI_LEAN_v2.1.md),
which is unchanged from the version the build was commissioned against. This
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
| Automated tests | **310 passing**, ~1.1 s, no network access required |
| Warehouse tests | **26 passing** against live BigQuery, ~30 s, ~2¢ (opt-in: `pytest -m warehouse`) |
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

5,212 lines across 21 modules.

| Module | Lines | Responsibility |
|---|---:|---|
| `queries.py` | 733 | Pure `(sql, params)` builders. No I/O, no globals, no client. |
| `models.py` | 498 | Typed rows; the single place that decides how a missing value is displayed. |
| `ui/case_detail.py` | 442 | §6.4 — header, metadata, comments, messages, timeline, files, related. |
| `ui/lists.py` | 423 | §6.2 — triage lists, filters, saved views, CSV. |
| `ui/shell.py` | 341 | §3.1 — rail, content region, era indicator, error surfaces. |
| `ui/search.py` | 320 | §6.3 — idle state, results, snippets, case-number shortcut. |
| `data.py` | 310 | The UI↔query seam: builder + cache + model, one function per page need. |
| `views.py` | 287 | Saved views, and the allowlist of what may be persisted. |
| `ask.py` | 231 | §6.5 — question in, SQL out; nothing else in the prompt. |
| `bq.py` | 226 | One client, byte caps, cost estimates, the read-only guard. |
| `ui/ask_page.py` | 214 | §6.5 UI — generate, review, then run. |
| `ui/sql_page.py` | 190 | §6.6 — free-form SQL with a priced dry run. |
| `config.py` | 177 | Every environment variable and its default. |
| `ui/components/filters.py` | 172 | The compact filter row and its disclosure. |
| `ui/settings.py` | 156 | §6.7 — era, connection, Ask availability, about. |
| `ui/components/table.py` | 129 | The list table; clickable rows, no Open button. |
| `cache.py` | 110 | TTL cache with no disk backend, deliberately. |
| `main.py` | 96 | Routes, and the loopback-only native window. |
| `ui/components/metadata.py` | 62 | The flat metadata strip that replaced five metric cards. |
| `ui/components/empty_state.py` | 56 | Every "nothing here" screen, including the failure ones. |
| `ui/components/freshness.py` | 30 | The stale-snapshot banner. |

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
| Startup, access probe, no setup dashboard | FR-START-1..3 | `main.py`, `ui/shell.py` | `test_ui_actions.py`, `test_visual.py` |
| Lists, columns, sorting, filters, presets, saved views, CSV | FR-LIST-1..12 | `ui/lists.py`, `views.py` | `test_triage.py`, `test_ui_actions.py` |
| Search: idle, execute, shortcut, parsing, scope, results, limits, empty | FR-SEARCH-1..12 | `ui/search.py`, `queries.search` | `test_search_semantics.py` |
| Case: comments-first, header, metadata, copy summary, tabs, related, unknown | FR-CASE-1..11 | `ui/case_detail.py` | `test_ui_actions.py`, `test_visual.py` |
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

---

## 4. Deviations register

Ten departures from the specification. Each names what the spec says, what was
built, and why.

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

### D9 — three environment variables beyond the §10 table

**Spec:** §10 tabulates the configuration surface.

**Built:** three additions.

| Variable | Default | Why |
|---|---|---|
| `CASEFINDER_QUERY_TIMEOUT` | 120 s | The wall-clock ceiling described in D8. |
| `CASEFINDER_FACET_CACHE_TTL` | 3600 | Filter values change on the warehouse's load cadence, not on the 15-minute result cadence. Re-querying them every 15 minutes buys nothing and costs a visible pause on the filter row. |
| `CASEFINDER_PERSONAL_VIEWS_PATH` | per-OS app data dir | §11.5 requires the personal saved-view file to be documented and separable for uninstall. Overriding its location is what makes that testable without writing to a real user profile. |

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
/Users/alvaro1/Documents/Astra/Workspaces/salesforce-cases/.astra/tasks/4DD4B29F/casefinder
```

That is a machine-local Astra task directory — provenance, not a dependency.
Nothing in this repository reads from it.
