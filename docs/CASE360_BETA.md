# Case 360 private beta

The beta runs the existing private engine as a separate local process. It does
not execute generated clinical SQL. Execution status and quality status are
separate: a completed run can remain HOLD and require human review.

## Install and configure

Use the macOS Apple Silicon app supplied through the private delivery channel.
Move **Case 360 Beta.app** to `~/Applications` and open it. Python, Node and the
locked dependencies are included. The stable Case Finder installation and its
preferences are separate. This local candidate has ad-hoc signatures; it is not
Developer ID signed or notarized. Windows acceptance is deferred.

Open **Analyst and installation settings**. Enter an analyst label and an
environment label, then save. These are editable settings, not compiled names.
The packaged runtime is selected automatically; an explicit configuration file
can select another prepared runtime. **Check local installation** makes no
remote call and incurs no model cost.

Resources and policy are also configured here. Import the source profile,
metadata for each requested center, an Epic export folder or prepared index,
and a STARR checkout or prepared index. Choose one origin for each resource.
Imported snapshots record provenance and integrity, not freshness or confirmed
meaning. Set the snapshot, expected account, verified route proof and maximum
budget. Zero disables live operation. Existing local Google credentials are
used; the analyst profile stores no credentials. Each live request still needs
a confirmed contract, a remote connection check and explicit budget approval.

The packaged command below runs only local diagnostics:

```sh
"$HOME/Applications/Case 360 Beta.app/Contents/MacOS/case360-beta" --check
```

## Review a request

Enter the original requirements and requested centers. Optional fields capture
the objective, period, cohort, exclusions, deliverables, sources and pending
decisions. Review the exact contract before confirming it. Editing starts a new
revision and invalidates the previous confirmation.

Results separate the requirement/field/center matrix, evidence, draft SQL,
compilation checks, semantic checks, independent review, pending decisions and
cost. Missing fields and unverified centers remain visible. Select a matrix row
to inspect its citations, columns, keys and dependencies.

Feedback records the analyst, affected requirements, issue category, proposed
correction and correction time. It is append-only and bound to the exact result
and contract hashes. It does not replace the independent review or approve SQL.
Exports contain only the chosen sections plus mandatory provenance, pending
decisions and an experimental-use notice. Raw traces and prompts are not
included by default.

## History, cleaning and versions

History, recovery and **Limpiar datos** are described in [P3](CASE360_P3.md).
Cleaning a request also removes its local feedback and generated export
artifacts. Copies downloaded elsewhere must be deleted separately. Pilot
assessments have their own confirmed **Clear saved pilot assessments** action.

Install a new private package from its Resources folder and the manifest SHA256
supplied through the private channel. Installation verifies the complete file
inventory and content. Activate a retained version, then close and reopen the
app. The original version is also available for rollback. Requests and resource
snapshots remain scoped to their runtime version; switching versions does not
migrate or silently reauthorize them. To inspect or clean older work, select its
version. Updates do not delete user evidence or replace the stable updater.

## Pilot assessment

Any analyst can configure their own installation. Record the synthetic journey,
interruption/recovery and manual-cleaning checks, then export the pilot
assessment with reasons for DEMO_ONLY, BLOCKED or LIMITED_PILOT. This is a human
report; it does not independently establish the identity or participation of a
second analyst. Live runs remain optional and separately authorized. Synthetic
passes do not establish clinical quality or generalization.
