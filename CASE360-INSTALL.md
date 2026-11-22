# Optional Case 360 Beta

Case Finder still ships as a universal Python wheel for Mac and Windows. Its
ordinary release updater is unchanged. Updating to version 2.2.0 adds a **Case 360 Beta** entry alongside Search,
Lists and SQL. Installing this wheel does not authorize model calls or replace
Case Finder's configuration.

The beta uses a private companion ZIP containing pinned Python, Node, Google
tools and pilot documentation. Get the ZIP for your computer from the pilot
owner. In Case Finder select **Case 360 Beta**. Choose **Install beta** the first
time, or choose **Open beta** if it is already installed. To apply a new pilot
ZIP, expand **Manage beta installation** and choose **Update from private ZIP**.
A new tester can also use the installer in the extracted ZIP without installing
Python or Node separately.

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

The public Case Finder update provides the beta entry. Private documentation
and companion tools are supplied separately through the pilot owner. The existing Windows public updater continues to ask
users to close the running app before replacing its wheel environment.
