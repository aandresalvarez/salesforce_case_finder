"""Packaged beta entry point; isolate settings before importing the UI."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from .case360 import package, preferences

    args = sys.argv[1:] if argv is None else argv
    root = Path(os.environ["CASE360_BUNDLE_ROOT"]).resolve(strict=True)
    active = preferences.data_root() / "active-release.json"
    if active.exists() and "--check-package" not in args:
        selection = json.loads(active.read_text())
        selected = Path(selection["root"]).resolve(strict=True)
        if selected != root:
            package.verify(selected, selection["manifest_sha256"])
            os.execv(str(selected / "launch"), [str(selected / "launch"), *args])
    manifest = package.verify(root)
    context = package.context_for(root, manifest)
    from .case360 import onboarding

    onboarding.provision(root, context)
    saved = json.loads(context.read_text())
    os.environ.update(onboarding.runtime_environment(saved, root))
    if onboarding.pilot(root) and not saved.get("authorization_policy", {}).get("live_enabled"):
        os.environ["CASE360_OPEN_SETUP"] = "1"
    os.environ.update(CASE360_CHANNEL="private-beta", CASE360_RUNTIME_CONTEXT=str(context),
                      CASEFINDER_CASE360="1", CASEFINDER_UPDATE_CHECK="0",
                      CASE360_RELEASE_VERSION=manifest["version"],
                      CASEFINDER_PERSONAL_VIEWS_PATH=str(preferences.data_root() / "views.json"))
    if args == ["--version"]:
        print("Case 360 Beta " + manifest["version"])
        return 0
    if args in (["--check"], ["--check-package"]):
        from .case360.client import Client
        from .case360.runtime import discover

        async def check():
            client = Client(discover())
            try:
                hello = await client.request("hello")
                health = await client.request("health")
                print(json.dumps({"release": manifest["release_id"], "hello": hello,
                                  "health": health, "remote_calls": 0}))
                return 0 if health["ready"] else 1
            finally:
                await client.close()
        return asyncio.run(check())
    if args == ["--review"]:
        # The first window goes directly to saved local work, without loading Search.
        os.environ["CASE360_OPEN_SAVED_REVIEW"] = "1"
        args = []
    if args == ["--setup"]:
        os.environ["CASE360_OPEN_SETUP"] = "1"
        args = []
    if args:
        print("usage: case360-beta [--version | --check | --review]; "
              "manage private updates in the app")
        return 2
    from .cli import cli

    if "__main__" in sys.modules:
        sys.modules["__main__"].__spec__ = importlib.util.find_spec("casefinder.main")
    return cli([])


if __name__ == "__main__":
    raise SystemExit(main())
