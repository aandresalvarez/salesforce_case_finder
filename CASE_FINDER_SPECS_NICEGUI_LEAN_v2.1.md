# Case Finder — System Specification

**Version 2.1.0 · 3 September 2026**  
**Target UI:** NiceGUI native desktop · Lean interaction model  
**Platforms:** Windows + macOS

Case Finder is a local desktop application that lets support staff search the historical Salesforce support-case archive held in BigQuery, run operational triage lists, read whole cases, and ask questions in plain English — with no shared server to operate, no credentials to distribute, and no PHI intentionally persisted to disk.

This revision keeps the data, query, security, cost, and stakeholder requirements from v2.0, but changes the target user experience from a Streamlit-style browser application to a **NiceGUI native desktop application with a deliberately lean UI**.

The central UI rule is:

> **Show the work, not the controls.** A user should see cases, comments, or results first. Controls appear only when they are needed.

---

## Document status

| Phase | Scope | Status |
|---|---|---|
| **v1** | Streamlit: full-text search, case reader, Ask, SQL, CSV export | **Delivered** — legacy baseline, 39/39 automated checks pass |
| **v2.1** | NiceGUI native UI, lean navigation, triage lists, extended metadata, comments-first detail, saved views, copy-to-clipboard | **Specified here; target implementation** |

The v1 source tree is the normative reference for every behavior this document describes as "retained from v1" — see [§1.6](#16-reference-implementation-v1-baseline) for its location and module-by-module disposition.

Stakeholder requirements remain those captured in September 2026 feedback. This document makes the UI behavior concrete enough to implement and test.

---

# 1. Purpose and scope

## 1.1 Problem

41,526 support cases and 280,001 conversation messages sit in BigQuery. The answer to “has anyone hit this before?” is often in the archive, but reaching it today requires knowing SQL, knowing the schema, and knowing that the useful text lives in `fct_conversation_turn.body_clean` rather than only in the case subject.

In practice, the archive is searchable by the few people who already know all three things.

## 1.2 Objective

Put two capabilities in front of every support-team member on their own laptop:

1. **Operational lists** for day-to-day triage.
2. **Historical search** across case metadata and conversation bodies.

The application must feel like a small desktop utility, not like a database tool or admin console.

## 1.3 Design constraints

| # | Constraint | Source / rationale |
|---|---|---|
| C1 | Zero shared application infrastructure — no hosted app server, container, or scheduled app job | Minimum-infrastructure requirement |
| C2 | Same source tree on Windows and macOS | Portability requirement |
| C3 | Launched as a local desktop application, not primarily visited as a URL | “A local app so they can install it” |
| C4 | Supports natural-language questions against the archive | Stakeholder request |
| C5 | No PHI intentionally persisted to local disk | Corpus contains PHI |
| C6 | No distributed service-account key | Individual auditability |
| C7 | Query cost is bounded and visible where useful | BigQuery on-demand billing |
| C8 | Read-only — no writes to Salesforce or the warehouse | SR-1 |
| C9 | Operational lists surface warehouse freshness honestly | Snapshot is batch-loaded |
| C10 | **Lean UI: one dominant task per screen and at most one primary visible action** | v2.1 design decision |
| C11 | **Progressive disclosure: advanced controls stay hidden until requested** | v2.1 design decision |
| C12 | **Keyboard/row interactions replace buttons when the intent is obvious** | v2.1 design decision |

## 1.4 Architectural consequence

C5 and C6 rule out a local warehouse copy and a hosted application identity. The target remains a thin local client that authenticates as the human sitting in front of it via Google Application Default Credentials (ADC) and reads BigQuery live.

**BigQuery IAM remains the access gate; Case Finder grants nothing.**

The v2.1 change is in presentation and runtime shell: the UI moves from Streamlit in the system browser to NiceGUI in a native desktop window. Data access, identity, cost controls, and read-only rules remain application-core concerns independent of the UI framework.

## 1.5 Stakeholder requirements

| ID | Requirement | Priority |
|---|---|---|
| SR-1 | Read-only case lookup from BigQuery; no editing/comments/updates in Salesforce | Must |
| SR-2 | Triage list with owner, status, PI, department, IRB/protocol, description, last activity, funded status | Must |
| SR-3 | Personal and shared filtered views for queues and weekly review | Must |
| SR-4 | 4–5 priority filters initially; legacy Salesforce filters later | Must |
| SR-5 | Case detail from list/search with IRB, PI, department, and Comments | Must |
| SR-6 | Users normally read the comment stream rather than opening individual emails | Must / UX default |
| SR-7 | Search by case number and find related historical cases | Must |
| SR-8 | Default data from 2022 onward; older archive optional | Must |
| SR-9 | Copyable text for ServiceNow handoff | Must |
| SR-10 | macOS + Windows local install | Must |
| SR-11 | No attachment migration; users use the relevant Box project folder | Must / policy |
| SR-12 | Column sorting and filtering on list views | Should |
| SR-13 | Minimum vs nice-to-have confirmed with Priya before final build prioritisation | Process |

**Operational caveat:** triage is only as current as the warehouse. A stale snapshot can show cases as open after they were closed in live Salesforce.

## 1.6 Reference implementation (v1 baseline)

The delivered v1 Streamlit application is the normative reference for the data contract (§5), query semantics (§7), and security posture (§9). Where this document and the v1 source disagree on UI, this document wins; where they disagree on query behavior, the v1 source is the baseline to be explained or deliberately changed.

**Location:**

```text
~/Documents/Astra/Workspaces/salesforce-cases/.astra/tasks/4DD4B29F/casefinder
```

| v1 file | Contents | v2.1 disposition |
|---|---|---|
| `__init__.py` | Package docstring, `__version__ = "1.0.0"` | Re-versioned |
| `config.py` | `PROJECT`, table constants, `MAX_BYTES_BILLED`, `USD_PER_TIB`, `CACHE_TTL_SECONDS`, Vertex model candidates, `Era` | **Port** → §10 |
| `bq.py` | `get_client`, `check_access`, `estimate_bytes`, `run`, `assert_read_only`, `QueryResult`, `AuthError` / `CostError` | **Port unchanged** → §9.1, §9.4 |
| `queries.py` | `parse_terms`, `search`, `_browse`, `corpus_size`, `facets`, `case_header`, `case_timeline`, `case_attachments`, `case_transcript` | **Port + extend** → §7.3 |
| `ask.py` | Vertex model resolution, `_system_prompt`, `to_sql`, `VertexUnavailable` | **Port unchanged** → §6.5 |
| `app.py` | Entire Streamlit UI in one module (~23 KB) | **Discard** → replaced by `ui/` (§4.3) |
| `launch.py` | Streamlit launcher | **Discard** → replaced by native entry point (§11.4) |

### Query-layer gap against §7.3

The v1 builders do not cover the full v2.1 inventory. Porting `queries.py` is necessary but not sufficient:

| §7.3 builder | v1 status |
|---|---|
| `search`, `corpus_size`, `facets`, `case_header`, `case_timeline`, `case_attachments` | Exists — port as-is |
| `browse` | Exists as private `_browse`; promote to public builder |
| `comments_stream`, `case_messages` | **New** — v1 has a single `case_transcript`; split per SR-6 / UC11 |
| `triage_list`, `related_cases` | **New** — no v1 equivalent (SR-2, SR-3, UC13) |

**Note on this path:** it is a machine-local working copy under an Astra task directory, not a durable artifact location — treat it as provenance, not as a dependency.

The four portable modules plus `__init__.py` have been vendored into this repository at `casefinder/` as an unmodified snapshot of that tree; the initial commit is the pristine v1 baseline, so `git log` distinguishes original v1 behavior from v2.1 changes. `app.py` and `launch.py` were deliberately not vendored, per the disposition table above. Implementers should work from `casefinder/`, not from the Astra path.

---

# 2. Users and primary use cases

## 2.1 User profile

Support staff and analysts who are comfortable using normal desktop applications. They are **not** assumed to know SQL, BigQuery schemas, Salesforce object structure, or the distinction between case fields and conversation turns.

The default UX must therefore be understandable without documentation.

## 2.2 Primary use cases

| ID | User intent | Product behavior |
|---|---|---|
| UC1 | “Has anyone asked about OMOP date shifting before?” | Full-text search over case fields + message bodies |
| UC2 | “What did we tell them?” | Comments-first case reading |
| UC3 | “What happened to this ticket?” | Unified chronological timeline |
| UC4 | “Show me CASE-056576” | Type case number and press Enter |
| UC5 | “How many cases were opened each month in 2025?” | Ask → generated SQL → explicit review/run |
| UC6 | “I need this case list in a spreadsheet” | Metadata-only CSV |
| UC7 | Power-user custom analysis | Read-only SQL workspace |
| UC8 | “Show me everything not closed” | Default Open Cases list |
| UC9 | “What’s in the Data Broker queue?” | Named list preset |
| UC10 | “Who is the PI and what’s the IRB?” | Extended metadata in case header |
| UC11 | “What have we said on this case?” | Flat Comments view, not email-by-email expanders |
| UC12 | “Copy this into ServiceNow” | Copy case summary |
| UC13 | “Find other cases for this PI / IRB / department” | Related cases |
| UC14 | “I need the attachment” | Show filename/pointer; direct user to Box |
| UC15 | “Use this filtered list again / share it” | Saved view / shared preset |

## 2.3 Explicit non-user

The application is not patient-facing or externally hosted. It has no app-level user accounts, no multi-tenancy, and no write-back workflow.

---

# 3. UX architecture — lean desktop design

## 3.1 Product shell

Case Finder uses a persistent desktop shell with a narrow navigation rail and one content surface.

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Case Finder                                                         │
├───────────────┬─────────────────────────────────────────────────────┤
│               │                                                     │
│  Case Finder  │                 CURRENT TASK                        │
│               │                                                     │
│  Lists        │        Search / table / case / result              │
│  Search       │                                                     │
│  Ask          │                                                     │
│  SQL          │                                                     │
│               │                                                     │
│               │                                                     │
│  Settings     │                                                     │
│               │                                                     │
└───────────────┴─────────────────────────────────────────────────────┘
```

### Navigation rules

1. Exactly four primary destinations: **Lists, Search, Ask, SQL**.
2. **Settings** is secondary and anchored at the bottom.
3. “About” is inside Settings, not a primary destination.
4. No Dashboard/Home page. The first screen is **Lists → Open Cases**.
5. The selected destination is indicated with a subtle background, not a large button.
6. Navigation items are text + small icon; no cards.

## 3.2 Global lean-design rules

These are implementation requirements, not aesthetic suggestions.

### UX-INV-1 — One primary action

A normal screen may show **at most one filled/primary button**.

Examples:
- First-run connection: `Retry` is the one primary action.
- Ask: `Run` is the one primary action after SQL is generated.
- SQL: `Run` is the primary action; `Check cost` is secondary text/outline.
- Search: **no Search button**; Enter executes.
- Lists: **no Open buttons**; row/case number click opens.

### UX-INV-2 — No button for navigation already represented by content

Do not render:
- `Open →` on every search card.
- `View case` in every list row.
- separate `Apply filters` buttons.
- a `Search` button next to a search box.
- persistent `Save`, `Copy`, `Export`, `More` buttons in the main toolbar.

Use row click, Enter, direct manipulation, or an overflow menu instead.

### UX-INV-3 — Progressive disclosure

The default view shows only the controls needed by most users.

Advanced or infrequent controls live behind one of:
- a compact filter chip row;
- a `Filters` disclosure;
- a `…` overflow menu;
- a secondary tab;
- Settings.

### UX-INV-4 — Content-first density

Screen real estate priority:

1. case/comment/result content;
2. primary metadata needed to interpret it;
3. filters/navigation;
4. explanations/help;
5. decorative UI.

### UX-INV-5 — Quiet status

Status such as query cost, cache hit, saved-view state, data freshness, and model name is rendered as muted inline text or a small banner only when actionable.

Do not create a permanent dashboard panel for telemetry.

### UX-INV-6 — No nested cards unless they encode a real object

Use whitespace and dividers before card-on-card layouts.

Cards are acceptable for:
- a search result;
- a connection error requiring action;
- an individual saved view if needed.

Metadata should generally not be surrounded by separate cards.

## 3.3 Visual language

- Light theme by default.
- Neutral background; white content surface.
- One restrained accent color for selection, links, focus, and primary actions.
- System/default sans-serif typography.
- Small border radius; no oversized rounded “pill dashboard” aesthetic.
- 1 px neutral dividers.
- Subtle shadows only for floating dialogs/menus.
- Compact tables.
- Status colors reserved for semantic meaning only.
- No gradients.
- No decorative illustrations except an empty/connection state icon.

### Suggested desktop dimensions

- Preferred initial window: **1280 × 800**.
- Minimum supported: **1024 × 700**.
- Navigation rail: approximately **132–152 px**.
- Main content maximum readable width for case detail: approximately **1000–1100 px**.

## 3.4 Interaction hierarchy

### Primary interactions

- click a case row;
- type and press Enter;
- change a filter;
- switch a detail tab;
- run reviewed SQL.

### Secondary interactions

Available via compact outline/text action or overflow:

- copy case summary;
- export metadata CSV;
- save current view;
- copy/share view definition;
- check query cost;
- choose visible columns;
- reveal advanced filters.

---

# 4. Target runtime architecture

## 4.1 Topology

```text
┌──────────────────── User laptop: Windows or macOS ───────────────────┐
│                                                                      │
│  NiceGUI native window                                               │
│  (pywebview shell)                                                   │
│          │                                                           │
│          ▼                                                           │
│  NiceGUI / local Python process                                      │
│          │                                                           │
│    ┌─────┴──────────────────────────────────────────────────────┐     │
│    │ ui/              pages, components, navigation             │     │
│    │ queries.py       pure SQL builders                         │     │
│    │ bq.py            BigQuery client, guards, cost caps        │     │
│    │ ask.py           NL → SQL, optional                        │     │
│    │ cache.py         process-memory TTL cache                  │     │
│    │ views.py         non-PHI saved-view definitions            │     │
│    │ config.py        projects, eras, limits                    │     │
│    └─────┬──────────────────────────────────────────────────────┘     │
│          │                                                           │
│  Application Default Credentials                                    │
│  ~/.config/gcloud or %APPDATA%\gcloud                               │
└──────────┼───────────────────────────────────────────────────────────┘
           │ TLS
           ▼
 Google Cloud — som-rit-phi-starr-dev
   ├── BigQuery: salesforce_current, salesforce_marts, salesforce_raw
   └── Vertex AI: Gemini (optional; receives no case data)
```

NiceGUI native mode still uses a local application server internally, but it is an implementation detail bound to loopback and presented to the user as a desktop window. There is **no shared/deployed Case Finder service**.

## 4.2 Framework boundary

The NiceGUI rewrite must not move SQL construction, authorization assumptions, or BigQuery access into page code.

### Layering rule

- `queries.py` builds SQL but performs no I/O.
- `bq.py` executes queries but builds no business SQL.
- `ui/` renders data and dispatches explicit application actions.
- `ask.py` generates candidate SQL but never executes it directly.
- `cache.py` stores query results in process memory only.

The UI framework is replaceable. The data/security semantics are not.

## 4.3 Proposed module layout

```text
casefinder/
  __init__.py
  config.py
  bq.py
  queries.py
  ask.py
  cache.py
  views.py
  models.py
  main.py
  ui/
    shell.py
    lists.py
    search.py
    case_detail.py
    ask_page.py
    sql_page.py
    settings.py
    components/
      table.py
      filters.py
      freshness.py
      empty_state.py
      metadata.py
```

## 4.4 Runtime dependencies

| Component | Target | Purpose |
|---|---|---|
| Python | ≥3.10 | Runtime supplied through `uv` |
| NiceGUI | pinned compatible release | UI + native window |
| pywebview | pinned compatible release | Native desktop shell |
| google-cloud-bigquery | ≥3.20 | Data access |
| google-cloud-aiplatform | optional `ask` extra | Gemini path |
| pandas | optional / SQL result convenience only | Dataframe conversions where useful |
| Playwright | optional `dev` extra | Visual/end-to-end tests |

Dependencies must be pinned in `uv.lock`; NiceGUI and pywebview compatibility must be tested on both target operating systems before release.

## 4.5 State model

| State | Location | Lifetime | Notes |
|---|---|---|---|
| Current destination | process/UI state | app session | Lists/Search/Ask/SQL |
| Selected case | process/UI route state | until navigation | Case number is canonical identifier |
| Search inputs | process/UI state | app session | No disk persistence |
| Query results | process-memory TTL cache | 15 min | PHI dies with process |
| Facets | process-memory TTL cache | 1 h | Low sensitivity |
| Access check | process-memory TTL cache | 15 min | Retry clears |
| Credentials | gcloud ADC store | until revoked | Managed by gcloud, not app |
| Personal saved-view definitions | local non-PHI config only | persistent | Filter/sort definitions only; never rows/bodies |
| Shared presets | distributed `views.json` | release/team managed | No case data |
| **Case/message data** | **process memory only** | **until process exits/cache expires** | **Never intentionally persisted** |

---

# 5. Data contract

## 5.1 Source project

Default project: `som-rit-phi-starr-dev`, overridable with `CASEFINDER_PROJECT`. Billing project defaults to the same and is separately overridable.

## 5.2 Two eras

| | Current | Archive |
|---|---|---|
| Label | 2022 onward (full detail) | Everything ever (conversation only) |
| Dataset | `salesforce_current` | `salesforce_marts` |
| Cases | 1,714 | 41,526 |
| Conversation turns | subset | 280,001 |
| `dim_case` | yes | yes |
| `fct_conversation_turn` | yes | yes |
| `case_history` | yes | no |
| `attachment_blob` | yes | no |

The era selector controls available content, not query cost. The current views read the same underlying data for body search; measured single-term search is approximately 244.5 MB vs 244.2 MB.

## 5.3 `dim_case`

One row per case, including:

`case_id`, `case_number`, `subject`, `description`, `status`, `origin`, `origin_class`, `type`, `reason`, `priority`, `is_closed`, `is_deleted`, ownership IDs, created/closed timestamps, `turn_count`, message counts, `last_turn_at`, and related summary fields.

## 5.4 `fct_conversation_turn`

One row per message/turn, including:

`case_id`, `turn_seq`, `turn_ts`, `source_object`, `source_id`, `direction`, `actor_role`, `actor_email`, `actor_name`, `actor_user_id`, `subject`, addressing fields, `body_clean`, `body_raw`, lengths, and deletion/orphan flags.

The application reads `body_clean`; `body_raw` is not used for normal display/search.

## 5.5 Extended case attributes

Triage metadata requires joining `salesforce_raw.Case` and `salesforce_raw.User`.

Measured current-era mappings:

| UI field | BigQuery source | Coverage / notes |
|---|---|---|
| Owner | `User.Name` via `owner_id` | ~100% |
| Status | `dim_case.status` | 100% |
| Department | `Project_Department__c` | 1,709/1,709 |
| PI | `PI_Name__c` | ~92% |
| IRB / protocol | `IRB_Protocol__c` | ~93% |
| Funding status | `Funding_Status__c` | ~79% |
| Description | `dim_case.description` | varies |
| Last activity | `last_turn_at`, fallback `last_modified_at` | sort key |

`Case.Comments` is empty in the measured corpus. The UX term **Comments** therefore means relevant `fct_conversation_turn` rows, especially `CaseComment` and copied email content.

## 5.6 Warehouse freshness

Measured 3 September 2026:

- newest `last_modified_at`: **2026-08-12 19:07 UTC**;
- snapshot age: **~22 days**;
- open cases in snapshot: **329**.

Every operational list must display `Data as of <timestamp>`.

If snapshot age > `CASEFINDER_STALE_DAYS` (default 7), show a single compact warning banner. Do not repeat freshness warnings on every row.

Target production freshness for trustworthy triage: **≤1 business day**.

---

# 6. Functional specification

## 6.1 Application start / first run

### FR-START-1 — Startup

Launch opens the NiceGUI native window directly. The user should not need to copy a localhost URL into a browser.

### FR-START-2 — Access probe

On startup, `bq.check_access()` reads one row from `dim_case`.

If access succeeds, route immediately to **Lists → Open Cases**.

If credentials or access are missing, render one centered connection state:

```text
              ☁
      Connect to Google Cloud

  Case Finder needs your existing
  Google Cloud credentials.

              [ Retry ]

  Setup instructions / help
```

Only `Retry` is primary. Detailed setup steps are available below or through a small help disclosure.

### FR-START-3 — No setup dashboard

Do not render configuration cards, corpus statistics, and authentication diagnostics simultaneously on first run. Show only what the user needs to continue.

---

## 6.2 Lists — default operational experience

### FR-LIST-1 — Landing page

After successful connection, the default route is **Open Cases**.

```text
Open Cases                                            119
Data as of Aug 12, 2026 · 22 days old

[Open only] [All statuses] [All departments] [All PIs] [IRB / protocol]

Case        Owner    Status   PI       Department   IRB       Last activity
CASE-...    ...      Open     ...      ...          ...       ...
```

### FR-LIST-2 — No list toolbar clutter

The default list does **not** show permanent buttons for:

- New view;
- Save;
- Export;
- Columns;
- Refresh;
- Open case;
- Apply filters.

Secondary operations are placed in a single `…` menu or appear contextually.

### FR-LIST-3 — Row navigation

Clicking the case number or row opens case detail. No separate Open button.

### FR-LIST-4 — Default columns

Default order:

1. Case number
2. Owner
3. Status
4. PI
5. Department
6. IRB/protocol
7. Description (truncated if width allows)
8. Last activity
9. Funded status (may be hidden at narrow widths)

### FR-LIST-5 — Sorting

Click a column header to toggle ascending/descending. The active sort gets a single small arrow indicator.

### FR-LIST-6 — Initial filters

Exactly five primary filters:

- Open only — default on for triage;
- Status;
- Department;
- PI;
- IRB/protocol.

Filter changes apply immediately after a short debounce; there is no Apply button.

Funding status is filter #6 only if Priya confirms it as minimum scope.

### FR-LIST-7 — Compact filters

On normal desktop widths, filters are one compact horizontal row. If width is insufficient, collapse them behind a single `Filters` disclosure showing an active-filter count.

### FR-LIST-8 — Named presets

At minimum:

- **Open Cases (weekly review)**
- **Data Broker Triage**

Preset selection can live under the Lists title or a compact view selector. Do not create a permanent left sub-navigation tree.

### FR-LIST-9 — Saved Views screen

A Saved Views screen is reachable from the Lists view selector or overflow menu, not from primary navigation.

It shows:

- Built-in/shared presets first;
- Personal saved views second;
- each view as one compact row;
- no card grid unless needed for touch layouts.

Personal view definitions store filters, sort, and column visibility only — never rows or message text.

### FR-LIST-10 — Save view

`Save current view` is an overflow action. Saving prompts only for a name. Do not open a full configuration modal unless necessary.

### FR-LIST-11 — Shared view

Shared team presets are file-backed (`views.json`). Personal definitions may be copied as a compact JSON/filter definition or promoted into the shared file by the project maintainer.

No server-side sharing system is introduced.

### FR-LIST-12 — CSV

Export is a secondary overflow action. Triage CSV includes metadata columns only and excludes message bodies/snippets.

---

## 6.3 Search

### FR-SEARCH-1 — Idle screen

Search is intentionally sparse:

```text
             Search historical support cases

      ┌─────────────────────────────────────┐
      │ Search cases or type CASE-...       │
      └─────────────────────────────────────┘

       Subject & description | Conversation

       Status     Type      2022 onward
```

No search tips card, recent-search dashboard, large illustration, or Search button.

### FR-SEARCH-2 — Execute

Pressing **Enter** executes the search.

Changing filters after a search updates results with debounce.

### FR-SEARCH-3 — Case-number shortcut

Input matching `^\s*CASE-\d+\s*$` navigates directly to the case detail on Enter. No intermediate “Open case” button is required.

### FR-SEARCH-4 — Term parsing

- all parsed terms use AND semantics;
- quoted phrases remain whole;
- lowercase once at parse time;
- terms shorter than 2 characters are dropped;
- maximum 6 terms;
- repeated terms collapse;
- `%` and `_` remain literal because matching uses `STRPOS`, not `LIKE`.

### FR-SEARCH-5 — Scope

Use a compact two-option segmented control:

- Subject & description
- Inside conversation

Both may be enabled. The control should visually read as one decision, not two large cards.

### FR-SEARCH-6 — Results

Result layout prioritises title and match context:

```text
CASE-056576                                      May 14, 2024
OMOP date shift by one day after ETL
Why this matched: subject and conversation contain similar terms…
…snippet with highlighted term…
```

The whole result is clickable.

Do not render an Open button per result.

### FR-SEARCH-7 — Result metadata

Show only high-value metadata by default:

- case number;
- date;
- subject;
- status if useful;
- one or two snippets / match explanation.

Turn counts, days-to-close, type, origin, and cost should not all occupy the first visual line.

### FR-SEARCH-8 — Boilerplate warning

If a term matches >50% of the corpus, show one compact warning above results explaining likely footer boilerplate. The warning can be dismissed for the current search.

### FR-SEARCH-9 — Result count

Show `N results` and truncation state quietly above the list.

Cost text is muted and visible only when non-trivial or explicitly requested.

### FR-SEARCH-10 — Sorting

Default: relevance / mention count. Alternate sorts live in a compact dropdown at the right of the result count:

- Most mentions
- Newest first
- Oldest first
- Longest thread

### FR-SEARCH-11 — Result limit

Do not show a large slider. Use pagination or compact `Rows per page` control (25/50/100) at the bottom. Cap server-side result retrieval at 500.

### FR-SEARCH-12 — Empty state

Explain the likely issue in one sentence and offer no more than 2–3 suggestions. No large error panel.

---

## 6.4 Case detail

### FR-CASE-1 — Default view is Comments

Case detail opens directly to **Comments**, because this matches support-team behavior.

Top-level tabs:

- Comments
- Messages
- Timeline
- Files

No separate Overview tab. Essential overview metadata sits above Comments.

### FR-CASE-2 — Header

```text
← Back
Why this shift hit by one day after ETL
CASE-056576

Open     Opened May 14     23 days     119 messages     7 files

Owner        PI            Department       IRB/protocol      Funding
...
```

Metrics render in one quiet strip or inline group, not five independent cards.

### FR-CASE-3 — Extended metadata

Always expose:

- Owner
- Type
- Reason
- Came in via
- PI
- Department
- IRB/protocol
- Funding status
- IRB status when populated

Missing values render `—`.

### FR-CASE-4 — Description

Description appears above the comment stream when present, collapsed if long. It must not dominate the page.

### FR-CASE-5 — Comments-first stream

Show a flat chronological reading stream using relevant `CaseComment` and email-derived turns.

Each entry has:

- author;
- role/source if needed;
- timestamp;
- body.

No expander per comment. Text is selectable.

Default ordering should match stakeholder preference; if newest-first is chosen for operational use, provide a subtle toggle in overflow rather than a persistent large control.

### FR-CASE-6 — Copy summary

`Copy summary` is a secondary action shown as a small outline/text control near the title or inside `…`.

Copy format:

```text
CASE-056576 | Status: Closed | PI: … | Dept: … | IRB: … | Funded: …
Opened: … | Last activity: …
Description: …
Recent comments:
  [timestamp author] …
```

### FR-CASE-7 — Messages tab

Messages is secondary. Show a compact list/table of individual messages.

Clicking a message expands it in-place or opens a side detail pane. Do not render all messages as large expanded cards.

### FR-CASE-8 — Timeline tab

Interleave conversation and case-history events chronologically using `UNION ALL`, never a fabricated join.

Use a simple vertical timeline with muted event-type indicators. One filter dropdown (`All events`) is allowed; additional controls stay hidden.

For archive era, explain that audit history was not retained and show conversation events only.

### FR-CASE-9 — Files tab

Show a simple table of filename, size, and pointer metadata.

Display one compact policy banner:

> Attachments are not migrated into Case Finder. Use the Box project folder for files and documents.

No upload, preview, delete, or migration controls.

### FR-CASE-10 — Related cases

Related cases are shown in a narrow secondary panel or section only when matches exist. Cap at 50 and sort by last activity.

Matching dimensions:

- same PI;
- same IRB/protocol;
- same department.

Do not show the panel when all three metadata values are missing.

### FR-CASE-11 — Unknown case

Show a calm empty state naming the selected era and one useful next action: search the other era.

---

## 6.5 Ask — natural language to SQL

### FR-ASK-1 — Purpose

Ask helps non-SQL users formulate aggregate questions. It is not a conversational chatbot over PHI.

### FR-ASK-2 — Lean layout

```text
Ask
Ask a question in plain English.

[ How many cases were opened each month in 2025?                 ]

SQL preview
---------------------------------------------------------------
SELECT ...
---------------------------------------------------------------
                                                [ Run ]

Results
...
```

No chat bubbles, transcript, suggestion carousel, or model dashboard.

### FR-ASK-3 — Generate on Enter

Press Enter to generate candidate SQL. Generation does not execute the query.

### FR-ASK-4 — Model sees no case data

Gemini receives only:

- user question;
- schema brief;
- SQL-generation rules.

No case rows, messages, snippets, or query results are sent to the model.

### FR-ASK-5 — SQL review

Generated SQL is visible before execution. The user explicitly chooses `Run`.

Model name is muted metadata, not a prominent badge.

### FR-ASK-6 — Guards

Generated SQL passes the same read-only and cost checks as SQL-tab input.

### FR-ASK-7 — Availability

Ask is shown only when a candidate Gemini model successfully responds to a real probe. If unavailable, the destination may remain visible but render one short explanation; all other features continue to work.

Candidate order remains configurable and must not depend on one permanently hard-coded model version.

---

## 6.6 SQL

### FR-SQL-1 — Audience

The SQL page is a power-user utility, not the center of the product.

### FR-SQL-2 — Layout

- editor occupies most of the upper content surface;
- `Run` is the one primary button;
- `Check cost` is secondary;
- result table follows directly below;
- cost estimate appears in a small side/inline panel only after requested or after run.

### FR-SQL-3 — Read-only

All submitted SQL must pass `assert_read_only()` before execution.

### FR-SQL-4 — Errors

BigQuery errors are surfaced verbatim in a compact error region below the editor.

---

## 6.7 Settings

Settings is read-mostly and intentionally boring.

Show:

- data project;
- billing project;
- default era;
- cache TTL;
- query cap;
- stale-data threshold;
- connection identity when it can be determined safely;
- version;
- privacy/read-only statements.

Do not turn Settings into an admin dashboard.

---

# 7. Query specification

## 7.1 Invariants

**Q-INV-1.** User values are always bound BigQuery parameters; never string-formatted into SQL.

**Q-INV-2.** Every executed job carries `maximum_bytes_billed`.

**Q-INV-3.** Query builders are pure functions returning `(sql, params)`.

**Q-INV-4.** Core query functions return plain Python dictionaries/records rather than depending on UI-specific dataframe dtypes.

**Q-INV-5.** UI events never construct ad-hoc SQL. They call named query builders.

## 7.2 Search structure

Search uses:

1. `matched_turns` — matching messages;
2. `turn_hits` — aggregate to one row per case;
3. `field_hits` — subject/description matches;
4. outer case join + filters;
5. `COUNT(*) OVER()` before `LIMIT` for true total matches.

Load-bearing choices retained from v1 (`queries.py::search` in the §1.6 reference tree):

- `STRPOS` over `LIKE` for literal matching and snippet offsets;
- `GREATEST(1, pos - 110)` for safe snippet start;
- subject + description concatenation;
- collapse turns before case join to prevent fan-out;
- disabled scopes represented without changing output shape;
- all user filters parameterized.

## 7.3 Complete query inventory

| Builder | Purpose | Reads |
|---|---|---|
| `search` | Main full-text search | turns + cases |
| `browse` | Filter-only case browse | `dim_case` |
| `corpus_size` | Match ratio | `dim_case` |
| `facets` | Filter values/date bounds | `dim_case` |
| `case_header` | Case metadata | `dim_case`, raw Case, User, attachments summary |
| `comments_stream` | Default case reading | turns + User |
| `case_messages` | Individual messages | turns + User |
| `case_timeline` | Conversation ∪ audit | turns + history + User |
| `case_attachments` | File pointer list | attachment table |
| `triage_list` | Open/queue listings | `dim_case`, raw Case, User |
| `related_cases` | Same PI/IRB/department | `dim_case`, raw Case |

---

# 8. Performance and cost

Measurements retained from 3 September 2026 baseline:

| Operation | Bytes scanned | Approx. cost | Latency |
|---|---:|---:|---:|
| Search, 1 term, conversation + fields | 244.5 MB | $0.0015 | ~2.1 s |
| Search, subject/description only | 30.8 MB | $0.0002 | <1 s |
| Browse, filters only | 4.8 MB | ~$0.00003 | <1 s |
| Facets | 1.6 MB | ~$0.00001 | <1 s |
| Triage list, 500 open cases | ~31.0 MB | ~$0.0002 | <1 s |
| Open case, legacy four-query path | ~590 MB | ~$0.0035 | ~3 s |
| Repeat inside 15-min app cache | 0 application query | free from app perspective | near instant |

### NFR-PERF-1

Search p95 target: <5 s.

### NFR-PERF-2

Normal list/filter interactions should feel immediate; use debounce and cache so changing a filter does not produce a query per keystroke.

### NFR-PERF-3

The NiceGUI migration must not increase BigQuery scan volume for equivalent operations.

### NFR-PERF-4

Opening a case remains the highest-value warehouse optimisation target because the turn table is not clustered on `case_id`.

---

# 9. Security and privacy

## 9.1 Authentication

ADC only. The application ships no service-account key and no application login screen.

## 9.2 Authorization

Delegated to BigQuery IAM. The app cannot widen access.

## 9.3 PHI handling

| Control | Implementation |
|---|---|
| No intentional PHI at rest | Case/message result caches are process-memory only |
| Local-only UI transport | Native/local server bound to loopback |
| No PHI to Gemini | Question + schema only |
| No PHI in standard CSV | Metadata only |
| No application telemetry | Disable/avoid analytics/telemetry |
| Read-only behavior | No mutation paths; untrusted SQL guard |

### Important saved-view rule

Saved views may persist **definitions only**: field names, selected status/department, sort order, column visibility, and similar configuration. They must never persist result rows, message bodies, snippets, descriptions, or generated summaries.

If a filter value is later classified as sensitive enough that local persistence is inappropriate, that field must be excluded from personal saved views or stored only in session memory.

## 9.4 Read-only SQL enforcement

For SQL written by users or generated by Gemini:

1. strip comments;
2. reject empty input;
3. reject multiple statements;
4. require `SELECT` or `WITH`;
5. reject mutation/DDL/control keywords including `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `REPLACE`, `EXPORT`, `LOAD`, `CALL`, `BEGIN`, `COMMIT`, `ROLLBACK`.

## 9.5 Injection and rendering

- user values are BigQuery parameters;
- search uses `STRPOS` rather than `LIKE`;
- case text is rendered as text, not trusted HTML;
- highlighting is applied only after escaping;
- generated SQL uses identical guards/cost preflight.

## 9.6 Network exposure

NiceGUI native mode must bind the local server to loopback only (`127.0.0.1` / localhost equivalent). No `0.0.0.0` configuration is allowed in production launch code.

The native window is the normal user surface. Opening the local page in a system browser is a support/development fallback, not the standard workflow.

---

# 10. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CASEFINDER_PROJECT` | `som-rit-phi-starr-dev` | Data project |
| `CASEFINDER_BILLING_PROJECT` | same | Billing project |
| `CASEFINDER_MAX_BYTES` | 4 GiB | Hard query cap |
| `CASEFINDER_USD_PER_TIB` | 6.25 | Display estimate |
| `CASEFINDER_CACHE_TTL` | 900 | Result-cache seconds |
| `CASEFINDER_STALE_DAYS` | 7 | Freshness warning threshold |
| `CASEFINDER_VERTEX_LOCATION` | `us-central1` | Vertex region |
| `CASEFINDER_VERTEX_MODEL` | unset | Optional pin |
| `CASEFINDER_VIEWS_PATH` | app `views.json` | Shared presets |
| `CASEFINDER_NATIVE` | true | Native desktop mode |

Native mode should use an automatically selected loopback port by default unless a fixed port is required for troubleshooting.

Search constants retained:

- boilerplate warning ratio: 0.50;
- snippet width: 280;
- snippet lead: 110;
- snippets per case: up to 3;
- term cap: 6;
- min term length: 2.

---

# 11. Installation and runtime

## 11.1 Distribution model

Default distribution remains **source folder + setup script**, not a signed binary.

This preserves:

- no admin rights;
- no Apple Developer certificate requirement;
- no Authenticode requirement;
- straightforward internal distribution;
- reproducible `uv.lock` environment.

A packaged `.app` / `.exe` may be evaluated later, but packaging is not required for v2.1 acceptance.

## 11.2 macOS

`install-mac.sh`:

1. install `uv` if absent;
2. `uv sync` including NiceGUI + compatible pywebview;
3. verify `gcloud`;
4. verify/offer ADC login;
5. perform a minimal native-window self-check if practical.

`run-mac.sh` executes the app entry point.

## 11.3 Windows

`install-windows.ps1` performs the equivalent steps.

The installer must check that the platform webview/runtime needed by pywebview is available and surface a clear remediation message if native mode cannot start.

`run-windows.bat` keeps errors visible on non-zero exit.

## 11.4 Application entry point

Target pattern:

```python
ui.run(
    native=True,
    reload=False,
    title='Case Finder',
    window_size=(1280, 800),
)
```

Production code must explicitly preserve loopback-only behavior and must not enable NiceGUI public-tunnel/on-air functionality.

## 11.5 Uninstall

Deleting the application folder removes the application runtime. Any optional personal saved-view file should be documented separately and contain no case rows or message content.

---

# 12. Failure and degradation matrix

| Condition | Lean UI behavior |
|---|---|
| No credentials | Centered Connect state + one `Retry` action + concise setup help |
| Authenticated but no BigQuery grant | One error region naming likely cause; raw BigQuery error available |
| Native window cannot initialize | Clear platform-specific message; support fallback command documented |
| Vertex unavailable | Ask shows short unavailable state; rest works |
| No model available | One concise message; details under disclosure |
| Query over 4 GiB cap | Refuse before execution; explain how to narrow |
| Mutation SQL | Reject and name offending keyword |
| Archive lacks history | Timeline explains limitation |
| Archive lacks attachments | Files explains limitation |
| Unknown case | Empty state + search-other-era action |
| Search term <2 chars | Inline validation; no query |
| Zero results | Short explanation + 2–3 suggestions |
| Empty facet | Do not render dead control |
| Snapshot stale | One compact freshness banner at top of list |
| Attachment pointer inaccessible | Explain separate access / Box policy |
| Any other BigQuery error | Compact error display, raw details available |

---

# 13. Test specification

The NiceGUI migration is accepted only if it preserves the v1 data/query semantics **and** passes new lean-UX checks.

## 13.1 Core/query tests

Retain coverage for:

- credentials/access;
- search parsing;
- facet values;
- corpus counts;
- body search/snippets;
- one row per case;
- AND semantics;
- literal `%` behavior;
- true match count before limit;
- status filters;
- cheap browse;
- case header;
- timeline semantics;
- ordered messages/authors;
- attachments;
- unknown case;
- archive behavior;
- read-only guard;
- cost cap;
- triage query one-row-per-case;
- enriched metadata joins;
- related cases.

## 13.2 NiceGUI component/page tests

Test application actions without requiring pixel-perfect screenshots where possible:

- startup success routes to Open Cases;
- startup failure shows Retry;
- Search executes on Enter;
- `CASE-...` executes direct navigation;
- search result row opens case without Open button;
- list row opens case;
- filters apply without Apply button;
- case opens on Comments tab;
- Messages/Timeline/Files tabs switch correctly;
- Copy summary contains case number and expected metadata;
- Ask requires review/run before execution;
- SQL mutation is rejected;
- stale snapshot banner appears when threshold exceeded.

## 13.3 Lean-UI acceptance tests

These are explicit v2.1 acceptance criteria.

### UX-T1 — Primary-button count

For each normal page state, assert no more than one primary filled action is visible.

### UX-T2 — Search has no Search button

Search must execute via Enter.

### UX-T3 — Result/list rows have no Open button

Navigation must be row/case-number click.

### UX-T4 — Default case tab is Comments

Individual messages must not be the default.

### UX-T5 — Default list has no permanent admin toolbar

No visible Save/Export/Columns/Refresh button group.

### UX-T6 — Advanced controls are progressive

Column visibility, export, save view, and advanced filters are not all visible simultaneously by default.

### UX-T7 — No nested card dashboard

Visual test should confirm the main content is primarily flat table/list/text surfaces.

## 13.4 Visual regression set

Minimum screenshots on both macOS and Windows or equivalent CI-supported environments:

1. Open Cases
2. Search idle
3. Search results
4. Case Comments
5. Case Messages
6. Case Timeline
7. Case Files
8. Ask with SQL preview
9. SQL with results/cost
10. Connection failure

Visual checks focus on hierarchy and overflow, not exact antialiasing.

---

# 14. Known limitations

1. Opening one case currently scans more data than a search because the body table is not clustered on `case_id`.
2. Era selection does not materially reduce body-search cost.
3. Search is substring-based, not stemming/BM25.
4. Relevance is primarily mention count.
5. No hosted collaboration or server-side saved searches.
6. PHI result cache is process-local only and disappears on exit.
7. Attachments are pointers; Box remains the operational file source.
8. Generated SQL can be semantically wrong even if valid; explicit review remains required.
9. Gemini availability changes over time.
10. Warehouse freshness currently limits triage usefulness.
11. PI/IRB/funding fields have missing values.
12. `Case.Comments` is empty; Comments UX depends on conversation turns.
13. Native desktop mode introduces a pywebview/platform-webview compatibility surface that did not exist in the browser-only Streamlit UI. This must be validated per release.
14. A local desktop UI does not protect against a compromised endpoint or screenshots by an authorized user.

---

# 15. Out of scope

- writing to Salesforce;
- live Salesforce synchronization inside the app;
- ServiceNow API integration;
- attachment migration/upload/preview workflow;
- PHI de-identification;
- mobile;
- offline warehouse copy;
- multi-user hosting;
- alerts/subscriptions;
- reporting dashboard/chart suite;
- full Salesforce list-view parity in v2.1;
- sending case data to Gemini for answer synthesis;
- building a general-purpose SQL IDE;
- building a general-purpose case-management system.

---

# 16. Extension points

Ordered by likely value:

1. **Cluster/materialize conversation data by `case_id`** to make opening a case cheap.
2. **Improve warehouse refresh SLA** to ≤1 business day for operational trust.
3. Materialize enriched case attributes into `dim_case`.
4. Materialize a search-optimised body table.
5. Add OR/NOT search operators if users need them.
6. Add more team presets through `views.json`.
7. Evaluate signed/package distribution after the workflow is validated.
8. Evaluate answer synthesis only after an explicit PHI/model-governance decision.

---

# 17. Implementation phases

## Phase 0 — Preserve the core

Starting point: the v1 tree at the path given in §1.6. Before UI migration:

- vendor `config.py`, `bq.py`, `queries.py`, and `ask.py` out of that tree into version control;
- freeze current query semantics with automated tests;
- keep `queries.py`, `bq.py`, and `ask.py` behavior stable;
- remove direct Streamlit dependencies from core modules;
- introduce process-memory cache abstraction;
- define typed view models between query layer and UI.

**Acceptance:** existing core/search/query tests pass without importing Streamlit.

## Phase 1 — NiceGUI shell + Search

Build:

1. native NiceGUI app shell;
2. navigation rail;
3. connection/first-run state;
4. Search idle + results;
5. case-number direct navigation;
6. basic case-detail shell.

**Acceptance:** user can install, connect, search, and open a case on both Windows and macOS with no browser interaction.

## Phase 2 — Lean case detail

Build:

1. extended header;
2. Comments-first stream;
3. Messages tab;
4. Timeline tab;
5. Files tab;
6. Copy summary;
7. Related cases if minimum scope permits.

**Acceptance:** a support user can understand a case primarily from one scrolling Comments view.

## Phase 3 — Operational Lists

Build:

1. `triage_list()` query;
2. Open Cases landing view;
3. five priority filters;
4. sort-by-column;
5. freshness banner;
6. Data Broker Triage preset;
7. metadata-only export in overflow.

**Acceptance:** Open Cases and Data Broker Triage reproduce the agreed minimum Salesforce list logic against the BigQuery snapshot.

## Phase 4 — Saved Views

Build:

1. built-in `views.json` presets;
2. personal local filter/sort definitions;
3. Saved Views screen;
4. minimal save flow;
5. optional copy/share definition.

**Acceptance:** no result row, case body, snippet, or description is written as part of saved-view persistence.

## Phase 5 — Ask + SQL utilities

Port:

1. Gemini availability probe;
2. Ask question → SQL preview → Run;
3. read-only SQL workspace;
4. cost preview;
5. result tables.

**Acceptance:** power features exist without adding chrome to Lists/Search/Case Detail.

## Phase 6 — Cross-platform UX verification

Validate on clean macOS and Windows machines:

- install;
- ADC flow;
- native window startup;
- resizing/minimum width;
- keyboard Enter behavior;
- clipboard;
- tables/scrolling;
- pywebview compatibility;
- no network exposure outside loopback;
- no case data persisted by the application.

---

# Appendix A — Target file inventory

```text
pyproject.toml
uv.lock

casefinder/
  __init__.py
  main.py
  config.py
  models.py
  bq.py
  queries.py
  ask.py
  cache.py
  views.py
  ui/
    shell.py
    lists.py
    search.py
    case_detail.py
    ask_page.py
    sql_page.py
    settings.py
    components/
      table.py
      filters.py
      freshness.py
      empty_state.py
      metadata.py

views.json
install-mac.sh
install-windows.ps1
run-mac.sh
run-windows.bat

tests/
  test_queries.py
  test_bq.py
  test_search_semantics.py
  test_triage.py
  test_read_only.py
  test_ui_actions.py
  test_visual.py

README.md
PROPOSAL.md
SPECS.md
```

---

# Appendix B — Lean UI requirement traceability

| Design requirement | Implementation | Verification |
|---|---|---|
| One dominant task per page | flat page composition | UX-T1 / visual tests |
| ≤1 primary visible action | primary-button rule | UX-T1 |
| No Search button | Enter handler | UX-T2 |
| No Open button per row | row/case link navigation | UX-T3 |
| Comments-first | default detail tab | UX-T4 |
| No list admin toolbar | overflow menu | UX-T5 |
| Progressive disclosure | filter disclosure / overflow | UX-T6 |
| Flat, minimal surfaces | dividers/tables over nested cards | UX-T7 |
| Native desktop | NiceGUI `native=True` | cross-platform phase |
| Loopback only | runtime host policy | socket/security test |
| No PHI persistence | memory cache only | code inspection + persistence test |

---

# Appendix C — Stakeholder traceability

| Stakeholder ask | v2.1 location |
|---|---|
| Read-only lookup | §9.4, FR-SQL-3 |
| Triage columns | FR-LIST-4, §5.5 |
| Personal/shared views | FR-LIST-8–11 |
| 4–5 priority filters | FR-LIST-6 |
| PI/dept/IRB/comments case detail | FR-CASE-3–5 |
| Don’t open individual emails by default | FR-CASE-1, FR-CASE-5, FR-CASE-7 |
| Case-number search | FR-SEARCH-3 |
| Related historical cases | FR-CASE-10 |
| Default 2022+ | §5.2 / Settings |
| Copyable ServiceNow context | FR-CASE-6 |
| Mac + Windows | §11, Phase 6 |
| No attachment migration; use Box | FR-CASE-9 |
| Active sort/filter | FR-LIST-5–7 |
| Data Broker / Open Cases lists | FR-LIST-1, FR-LIST-8 |
| Warehouse freshness | §5.6, FR-LIST-1 |

---

# Appendix D — Explicit UI removals from the earlier concept

The following controls are intentionally removed or demoted in the lean NiceGUI design:

| Earlier concept | v2.1 decision |
|---|---|
| Search button | Remove; Enter searches |
| Open button on each result | Remove; result is clickable |
| Open button on each list row | Remove; row/case number is clickable |
| Persistent Saved button | Move to overflow/context |
| Persistent Export button | Move to overflow |
| Persistent Columns button | Move to overflow |
| Apply Filters button | Remove; filters apply automatically |
| Large filter sidebar on every list | Use compact row; reveal sidebar only for advanced/custom view |
| Five separate metric cards in case header | Flatten into one metric strip |
| Individual email expanders as default | Move to Messages tab |
| Multiple nested cards | Replace with whitespace/dividers/table rows |
| Large status/cost panels | Render muted inline information unless action is needed |
| Separate About destination | Move into Settings |
| Dashboard/home landing page | Remove; land on Open Cases |

**Design intent:** Case Finder should feel closer to Spotlight, Linear, or a compact mail client than to a BI dashboard.
