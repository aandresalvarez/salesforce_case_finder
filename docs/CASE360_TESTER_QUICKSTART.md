# Case Finder + Case 360 Beta — Mac quick start

For the private internal pilot. Use an **Apple Silicon Mac (M1 or later), macOS 13 or later**, and your own work account with the pilot's data and Vertex AI permissions. Connect to Stanford VPN when required.

## Install

1. Download the private **Case360-Mac-Pilot.zip** supplied by the pilot owner. Unzip it.
2. Double-click **Install Case Finder Beta.command**. A Terminal window opens and installs the included Python wheel and its companion tools automatically. **You do not need to type commands, install Homebrew, or download developer tools.** Allow a few minutes; the app opens when installation finishes.
3. Keep **Case Finder Beta.command** in your home **Applications** folder for future launches. You can close the installer window and remove the downloaded installer afterward.

This installs a separate beta. Your existing Case Finder installation is unchanged. The frontend is still distributed as a Python wheel; the installer also supplies the Node engine, Python validators, Google sign-in tool and private documentation resources. It does not install an account or copy another analyst's requests.

## Set up your account in the app

1. In **Set up your beta**, enter **Your work email** and select **Sign in with Google**. Complete Google/Stanford sign-in and MFA in your browser, then return to the app. Never paste passwords or sign-in codes into a request.
2. Select **Check my access**. The app checks your identity, dataset metadata, BigQuery dry-run permission and model-project permissions. It makes no paid model call and executes no data query. If a check fails, first confirm your VPN connection. Signing in cannot grant missing organizational permissions; the pilot owner must arrange these for your account before testing.
3. Enter your tester label and a **Maximum USD per request**, then select **Save my settings**. Zero disables live analysis. Saving does not spend money. Select **Start a request** when ready.

The included Epic/SHC/LPCH/STARR snapshot has recorded versions; a snapshot does not establish current table availability or clinical meaning. The agent checks relevant sources during analysis. You do not need repository access, resource paths or hashes for setup.

## Try the flow

Describe a study, attach its scoping document, and use **Add meeting notes** for later decisions. Select **Analyze request** to authorize work within your saved budget. The AI reads the documents, offers clarification suggestions, and shows the scope for your confirmation. Then build the SQL and review its evidence and dry-run result. Longer requests can take 20–30 minutes or more; use the activity panel to follow progress.

**Dry run: Passed** means the current SQL and its outputs compiled. **Quality: HOLD** means a human must review the draft; it is separate from an execution failure. The beta does not execute the generated clinical SQL.

## If you need to reconnect

- Google sign-in expired: **Beta settings → Sign in and tester setup → Sign in with Google**. Return to the saved request and use **Retry and continue** or **Continue saved review**, when offered.
- Interrupted work: open **History and clean data** and reopen the saved request. Do not create a duplicate merely to reconnect.
- Missing permissions: share only the failed resource names shown in **Check my access** with the pilot owner. Do not send credential files or tokens.
- macOS blocks the downloaded installer: follow your organization's software policy and [Apple's instructions for opening a trusted downloaded app](https://support.apple.com/en-us/102445). The pilot does not require disabling Gatekeeper or other security controls.
- An existing Case 360 beta is detected: this new-tester installer leaves it unchanged. Use the beta update process so its saved requests remain attached to the correct runtime.

Requests, answers and credentials stay in your macOS user's private application data. **History and clean data** removes only the work you select; it is not a Google sign-out action. Windows and Intel Mac delivery are not included in this installer.
