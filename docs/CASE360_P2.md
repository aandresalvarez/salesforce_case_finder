# Case 360 request preparation — P2 increment

The optional Case 360 page can now prepare a new request from requirement lines,
explicit center selection, an optional external case ID and external input
names. It shows the contract, pending decisions, resource coverage, relevant
evidence and source comparison before exact-hash confirmation. Editing a
request creates a new revision and requires confirmation again.

The separate private engine validates the contract and imports versioned
resources. The frontend does not infer clinical rules, construct source maps
or authorize model calls. External inputs remain unbound string lists; this
form does not collect their values. Requests and evidence are stored privately
by the engine. History, manual cleanup and restart recovery remain P3 work.

## Configure the private runtime

The pilot owner prepares the private runtime context and pinned build/resource
manifests using the private engine's `desktop_bridge/P2_PREPARATION.MD`. Point
Case Finder at that context:

```sh
CASEFINDER_CASE360=1 CASE360_RUNTIME_CONTEXT="$HOME/private-user-data/context.json" casefinder
```

An explicit context takes precedence over legacy engine/Node/run-root settings.
The engine checks its manifest, interpreter, private roots and resource hashes.
This path can use a Python interpreter outside the engine directory and does
not require Git at runtime. The development fixtures still share installed
dependencies; they do not constitute an installer or Windows validation.

A request can be drafted without installed resources. Missing evidence and
pending interpretation remain visible. Confirmation does not authorize live
execution: the private engine rejects it until a live identity, serving route
and scoped budget authorization adapter is implemented and verified. Opening
the page, preparing a request and confirming it make no paid provider calls.
The synthetic demonstration remains available in a separate expansion.

## Validation boundary

The added tests cover protocol commands, context precedence, the real NiceGUI
form, edit invalidation and prepare/confirm/revise event wiring. The private
engine exercises resource preparation, metadata scope, missing permissions,
new IDs, immutable revisions and hashes, symlink rejection and real-route
refusal. No real resource export or model request was performed.

The P2 source tree has 758 offline tests; the combined development checkout has
774 including 16 pre-existing local free-form tests. P1 PRs remain separate;
this is a P2 preparation increment, not completion of P2 live-run admission.
