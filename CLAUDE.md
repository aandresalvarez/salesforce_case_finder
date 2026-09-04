# Working in this repository

## This repository is public; the corpus is not

The BigQuery corpus this app queries holds PHI. Case bodies are pasted email:
requesters' names, personal and institutional addresses, study titles, IRB
numbers, and the names of the staff who worked the case. None of it may appear
in this repository — not in code, not in comments, not in fixtures, not in
commit messages, and not in documentation.

The leak is not carelessness, it is the shape of the work. Diagnosing a
rendering bug means looking at what actually renders, so you sample a real row;
the natural next step is to paste that sample into the comment explaining the
fix or the fixture reproducing it. **Carry over the shape, never the string.**
Same length, same punctuation, same awkwardness — invented content.

- People come from `tests/synthetic.py`. Take a name from the roster rather
  than inventing one at the call site.
- Addresses use `example.com` / `example.edu` (see `tests/corpus_guard.py` for
  why `.edu` is allowed).
- Paths use `~`, never `/Users/<someone>`.

`tests/test_no_corpus_data.py` fails the build on an address or absolute home
path that breaks this. The same check runs as a pre-commit hook — install it
once per clone with `git config core.hooksPath .githooks`. The hook is the
convenience; the test is the gate. Assume a rewritten history is not a deleted
one: once something is pushed, a force-push does not remove it.

## Conventions worth knowing before you edit

- **Lint with `ruff check .` only.** The project does not use `ruff format` —
  running it reformats 26 files and buries the real change. Fix `E501` by hand.
- `tests/` is not a package, so test helpers are imported absolutely
  (`import corpus_guard`), not relatively.
- Tests render real NiceGUI pages into an isolated client and assert on the
  element tree. `shell.theme()` uses plain `ui.add_head_html`, so a test that
  asserts on theme CSS has to render `shell.theme`.
- Fixtures fail loudly if a test reaches for BigQuery or Vertex without asking.
  Keep it that way: a test that forgets its fakes should fail, not quietly run
  on live data.
- `SPECS.md` records deviations from `CASE_FINDER_SPECS_NICEGUI_LEAN_v2.1.md`.
  If a change departs from the spec, add a numbered entry rather than editing
  the spec, and keep the test counts in `SPECS.md`, `README.md` and
  `PROPOSAL.md` in step with the suite.
