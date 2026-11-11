# Case 360 desktop preview — P1

This optional route connects the Python UI to a separately installed private
runtime. It prepares a synthetic contract, records confirmation of its hash,
starts the existing harness in a fresh child, and displays its evidence,
independent review, SQL checks and pending decisions. `COMPLETED` and `HOLD`
remain separate. No clinical query or paid model request is enabled.

The stable Case Finder reader retains its existing storage behavior. This
preview stores synthetic runs in a separate private user directory. History,
manual cleanup, restart recovery, resource preparation, installers and live
authorization are later phases; this is not a distributable beta release.

## Developer launch

Prepare the matching private runtime and its locked dependencies, then set
`CASE360_ENGINE_ROOT` to its local directory. `CASE360_NODE` optionally names the
Node 24 executable and `CASE360_RUNS_ROOT` optionally names a private run root.
The application discovers platform-specific user storage by default.

```sh
CASEFINDER_CASE360=1 CASE360_ENGINE_ROOT="$HOME/path/to/private-runtime" casefinder
```

Select **Case 360 Beta** in the navigation, choose a synthetic upper bound,
prepare and inspect the contract, confirm it, and start the demonstration.
The optional route also works in browser mode at `/case360`, without the
BigQuery connection gate. Changing the numeric input requires a new contract.
The default Case Finder launch keeps the beta disabled.

The current developer demo is verified on macOS. Windows remains an explicit
target, but the legacy verifier paths and synthetic CLI shim still require
adaptation and native validation. The runtime health check refuses that demo
on Windows instead of claiming support.

## Protocol and checks

`casefinder/case360/protocol.json` and the shared protocol fixtures are copied
from the private runtime's `desktop_bridge/schemas`. Edit the owning source
there, copy both files, and run both implementations' tests. The initial
handshake rejects a different schema hash before preparing a request.

The client uses an argument list, concurrent stdout/stderr readers and a
256 KiB control-line limit. Large result artifacts are paged and hash-checked.
Only bounded progress events may be dropped; a counter records that condition.
Evidence is retrieved in full from the result artifact, never from that queue.
There is no automatic replay after losing the controller. Request idempotency
lasts for the controller session; durable recovery is P3 work.

Thirty-five added offline tests cover protocol fixtures, Unicode/partial
messages, malformed or oversized output, abundant stderr, artifact integrity,
runtime discovery and the actual NiceGUI element tree. Cross-repository tests
in the private runtime exercise the full harness and process lifecycle.
The exact P1 source tree passes 744 tests. The combined working copy passes
760 tests, including 16 pre-existing
uncommitted free-form-result tests; those unrelated changes are not part of
the P1 implementation commit. Warehouse tests remain excluded.
