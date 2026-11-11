# Case 360 new requests — P2

The optional Case 360 page prepares a new request from requirement lines,
explicit center selection, an optional external case ID and external input
names. It shows the contract, pending decisions, resource coverage, relevant
evidence and source comparison before exact-hash confirmation. Editing a
request requires a new revision and confirmation.

The private engine validates the contract, imports versioned resources and
owns authorization and execution. The frontend collects the analyst's explicit
choices. External inputs remain unbound string lists; this form does not
collect their values. Requests and evidence stay in the private runtime.
History, manual cleanup and restart recovery remain P3 work.

## Configure the private runtime

The pilot owner prepares the runtime context and pinned build/resource manifests
using the private engine's `desktop_bridge/P2_PREPARATION.MD`. Point Case Finder
at that context:

```sh
CASEFINDER_CASE360=1 CASE360_RUNTIME_CONTEXT="$HOME/private-user-data/context.json" casefinder
```

An explicit context takes precedence over legacy engine/Node/run-root settings.
The engine checks its manifest, interpreter, private roots and resource hashes.
It can use an external Python interpreter and needs no Git at runtime. The
development fixtures share installed dependencies; they do not constitute an
installer or Windows validation.

Requests can be drafted without installed resources. Missing evidence and
pending interpretation remain visible. Preparing and confirming make no paid
calls. Live mode is disabled by default; the synthetic demonstration remains
available in its own expansion.

## Check, authorize and start

With an owner-configured live policy and verified serving-route record:

1. Prepare the request, inspect its contract and confirm that revision.
2. Select **Check connection**. This explicit remote action checks ADC/CLI
   identity and a BigQuery dry run. It sends no model request and executes no
   clinical SQL. The result expires after five minutes.
3. Enter a maximum spend and select **Authorize this budget**. The private
   engine binds the amount, identity, contract, resources and runtime. The
   installation ceiling alone grants no run authorization.
4. Select **Start authorized request**. The engine uses the existing author,
   reviewer, evidence tools and validators. The UI shows execution, quality
   and charged/reserved, uncertain and remaining budget separately.

**Cancel request** stops the active child and retains uncertain reservations.
A failed start displays its guard code. Changes, or an expired check after
approval, require a new preparation and authorization. There is no automatic
budget increase. Clinical SQL execution is disabled. A completed execution
can still have quality HOLD; judge evaluation is not run by this workflow.

## Validation boundary

The P2 source tree has 768 offline tests; the combined development checkout has
784 including 16 pre-existing local tests. The added coverage includes shared
protocol validation, real NiceGUI event wiring, revision invalidation and the
separate check/authorize/start steps. Private-engine tests exercise fresh
orders, surgery and payer requests through independent review, identity and
scope refusal, cap exhaustion, uncertain responses, and cancellation.

No real resource export, credential probe or model request was performed.
Code-only runtime tests deny network and ADC reads on macOS. Live pilot setup,
Windows, installers and second-analyst acceptance remain unverified.
