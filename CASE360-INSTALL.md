# Optional Case 360 Beta

Case Finder still ships as a universal Python wheel for Mac and Windows. Its
ordinary release updater is unchanged. Once a release containing this PR is
published, updating Case Finder adds a **Case 360 Beta** entry alongside Search,
Lists and SQL. Installing this wheel does not authorize model calls or replace
Case Finder's configuration.

The beta uses a private companion ZIP containing pinned Python, Node, Google
tools and pilot documentation. Get the ZIP for your computer from the pilot
owner. In Case Finder select **Case 360 Beta → Install beta or update beta**,
choose the ZIP, then **Open beta**. A new tester can also use the installer in
the extracted ZIP without installing Python or Node separately.

In the beta, sign in with your own work account, check access, and select
**Continue to Case 360**. The pilot has a $500 total limit per tester on this
computer and a $50 request limit, editable in Beta settings. Setup makes no
paid model calls. The account still needs the required dataset/model access.

Companion updates install alongside previous versions. They retain requests,
account configuration, previous contexts and budget usage. Close an older beta
window before opening a newly installed version. Use **History and clean data**
when you decide to remove research work. Regular Case Finder settings and the
beta's Google credentials remain separate.

Windows x64 uses WebView2 for the native window. If it is absent, the launcher
opens the same localhost UI in the default browser. Mac keeps its native window.
Windows images use installed Windows OCR language packs; documents and meeting
notes share the same parser and workflow on both platforms.

This PR provides the private test package and update entry. It does **not**
publish a general Case Finder release or distribute private documentation through
the public wheel channel. The existing Windows public updater continues to ask
users to close the running app before replacing its wheel environment.
