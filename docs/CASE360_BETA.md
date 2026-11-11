# Case 360 private beta

The beta runs the existing private engine as a separate local process. It does
not execute generated clinical SQL. Execution status and quality status are
separate: a completed run can remain HOLD and require human review.

Case Finder remains the application: Search is the home page, and Lists, Ask
(when enabled), SQL and Settings keep their original routes and behavior.
**Case 360 Beta** is an additional navigation option. All interface controls are
in English; requests and analyst answers are preserved as entered.

## Install and configure

Use the macOS Apple Silicon app supplied through the private delivery channel.
Move **Case 360 Beta.app** to `~/Applications` and open it. Python, Node and the
locked dependencies are included. The stable Case Finder installation and its
preferences are separate. This local candidate has ad-hoc signatures; it is not
Developer ID signed or notarized. Windows acceptance is deferred.

Open **Case 360 Beta**, then **Beta settings**, then **Analyst and installation settings**. Enter an analyst label and an
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
explicit approval through **Analyze request**. The maximum appears beside
that action; the app binds the request and checks the connection automatically.
Saved snapshot locations, account and budget policy are restored when the
settings page is reopened. Editing the display labels does not change Google
credentials.

The packaged command below runs only local diagnostics:

```sh
"$HOME/Applications/Case 360 Beta.app/Contents/MacOS/case360-beta" --check
```

## Review a request

Write a request in the single **Your request** text field and press **Analyze request**. Free text does not need one requirement per line. Settings, source
locations and budgets stay in **Beta settings**. The app does not assume SHC or LPCH
when the request leaves the site unclear.

The agent receives relevant imported evidence before interpreting the request.
The activity panel reports actual source lookups, metadata checks, generation
and review. It does not expose private model reasoning or simulate progress.
Candidate sources and their complete evidence are available for inspection.

If the agent identifies material ambiguity, SQL generation pauses. Answer the
questions and press **Continue with my answers**. Each revision preserves
the original request, literal questions and answers, and searches with the
updated scope. Earlier model charges count against the same request budget;
continuing cannot create a second authorization for the same remaining funds.
No new model request is sent merely by reopening a conversation.

The SQL tab opens when a draft is available. The result remains experimental
and requires human review. **New request** starts a separate conversation;
**History and clean data** opens saved work, recovery and confirmed cleaning.

Results separate the requirement/field/center matrix, evidence, draft SQL,
compilation checks, semantic checks, independent review, pending decisions and
cost. Missing fields and unverified centers remain visible. Select a matrix row
to inspect its citations, columns, keys and dependencies.
Large JSON details are displayed in pages to keep the native window responsive.
Every page remains available, and **Download complete JSON** preserves the
entire record without changing the saved evidence.

Feedback records the analyst, affected requirements, issue category, proposed
correction and correction time. It is append-only and bound to the exact result
and contract hashes. It does not replace the independent review or approve SQL.
Exports contain only the chosen sections plus mandatory provenance, pending
decisions and an experimental-use notice. Raw traces and prompts are not
included by default.

## History, cleaning and versions

History, recovery and **Clean data** are described in [P3](CASE360_P3.md).
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

If admission fails, the request remains saved. **Retry and continue** is offered
for connection failures and can start the analysis after reconnection. An internal
package failure instead directs you to repair or update the beta. Opening a saved
draft does not start it; **Continue this request** is the explicit next action.
