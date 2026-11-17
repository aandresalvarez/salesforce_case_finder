# Case 360 P3: history, recovery and local cleanup

The optional Case 360 view now includes local history and **Clean data**.
Use matching P3 frontend and private runtime components: the client checks the
exact protocol schema. The beta remains disabled by default. No provider or
warehouse access is needed to inspect history or clear local content.

## Reopen and recover

Refresh history to see saved requests, revisions, progress and budget state.
Open a request to inspect its artifact; a prepared request can be edited as a
new revision with its original requirement text and center selection. Reconnect
local runtime explicitly after a controller failure. Reconnection does not
repeat the interrupted command.

For a stopped request, Check saved checkpoint asks the private engine to verify
its contract, SQL, evidence, settled model responses, resource files, code build
and authorization. Resume verified checkpoint continues from a supported saved
boundary and retains prior charges. The currently supported boundaries are the
settled initial generation before review, and a completed run whose presentation
needs rebuilding. An uncertain response, modified evidence or an unsupported
boundary blocks recovery. Starting again requires explicit new preparation and
authorization; the app never silently resets a budget or repeats paid work.

The native close button and the reconnect notice's Close action share a stop
gate. Active work offers Return to app or Stop and close. The latter blocks new
actions, cancels owned work and verifies process exit before approving the window
close. If the server has already died, its closed pipe triggers the controller's
crash handling; the orphan window can close without a server callback.

## Clean data

1. Refresh history and select requests, or choose All local history.
2. Optionally select unused imported resources. Snapshots still referenced by
   retained work are protected; removed snapshots must be prepared again.
3. Press Clean data and inspect the exact request revisions, file counts,
   sizes and blocked items. Cancel does not delete anything.
4. Confirm cleanup removes only the previewed scope. Newly created work and
   changed revisions are not added to an earlier confirmation.

Stop selected work and open a fresh preview if a process is active. Unverified
process ownership blocks deletion of that request while other selected work can
still be cleared. A partial result lists retained items and offers a retry of
the same scope. Deleted work cannot be resumed or reconstructed from controller
receipts after reopening.

Cleanup removes request text, contracts, sessions, evidence, SQL and feedback.
Minimal technical accounting remains, including recorded charges, uncertain
reservations and hashed authorization identity. It does not erase credentials,
source systems, installed code or exports outside the app. This is local logical
erasure, not a guarantee about physical media or backups. Other already-open
views may need reloading to discard previously loaded content.

## Validation and limits

Synthetic UI callbacks exercise preview, cancel, exact-scope confirmation,
partial results, return versus stop, unverified process refusal and explicit
reconnect. Cross-repository tests use actual subprocess pipes and a code-only
runtime without network, credentials or Git. No paid model request, clinical
query or live pilot validation is part of these checks.

The private runtime uses POSIX process groups and a Windows kernel Job adapter
for owned descendants. macOS subprocess behavior is tested; Windows execution
and native visual acceptance on both platforms remain release checks. P3 does
not supply an installer, signing or judge calibration.
