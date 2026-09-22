"""`casefinder` on the command line: the flags, then the window.

The console script points here rather than at `main` because of what `main`
imports. `from nicegui import app, ui` is the first thing it does, so while this
function lived there every flag paid for NiceGUI before it was read — and when
NiceGUI could not import, every flag failed with it. On Python 3.14 that is
exactly what happened (D37). `--check`, the command written to diagnose a broken
machine, answered with a traceback. `--update`, the command written to deliver a
fix, could not run to deliver one.

So nothing on the way to a flag imports the UI. `--version` needs `config`.
`--check` needs `selfcheck`, which imports the application only as one of its
checks, where a failure becomes a line of output. `--update` needs `update`.
`main` is imported after all three have been ruled out, to open the window.
"""

from __future__ import annotations

import sys

from . import config, selfcheck

USAGE = "usage: casefinder [--check] [--update] [--version]"


def cli(argv: list[str] | None = None) -> int:
    """Console-script entry point. Returns the process exit code.

    `main.main` deliberately takes no arguments and reads no argv. Two tests
    call it directly to assert on what it passes to `ui.run`, and they run under
    pytest's own command line — a `main` that parsed `sys.argv` would see
    pytest's flags and fail on them.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--version" in args:
        print(f"{config.APP_NAME} {config.VERSION}")
        return 0
    if "--check" in args:
        return selfcheck.run()
    if "--update" in args:
        # Imported here rather than at module scope: it is the one module that
        # opens a socket to somewhere other than BigQuery, and launching the app
        # should not load it at all.
        from . import update

        return update.run()
    unknown = [a for a in args if a.startswith("-")]
    if unknown:
        print(f"unrecognised option: {unknown[0]}\n{USAGE}")
        return 2
    if not config.python_supported():
        # Said before `main` is imported, because importing it is what fails —
        # as a traceback out of a dependency nobody using the app has heard of.
        _, message, remedy = selfcheck.check_python()
        print(f"{config.APP_NAME} {config.VERSION} cannot start on this Python.")
        print(f"  {message}")
        for line in remedy:
            print(f"  {line}")
        return 1

    from . import main

    main._pin_main_module()
    main.main()
    return 0
