"""Explicit local runtime discovery. Never installs or contacts a provider."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Runtime:
    engine_root: Path
    runs_root: Path
    node: str

    def command(self) -> list[str]:
        if os.environ.get("NODE_OPTIONS"):
            raise RuntimeError("NODE_OPTIONS must be unset for the beta runtime.")
        root = self.engine_root.resolve(strict=True)
        loader = root / "pi_harness/node_modules/tsx/dist/loader.mjs"
        worker = root / "desktop_bridge/worker.mjs"
        if not loader.is_file() or not worker.is_file():
            raise RuntimeError("The compatible Case 360 desktop runtime is not installed.")
        return [self.node, "--import", str(loader), str(worker), str(self.runs_root.resolve())]

    def environment(self) -> dict[str, str]:
        # Carry only OS essentials. Ask configuration and provider credentials are
        # unnecessary for this synthetic preview and must not select its runtime.
        names = ("PATH", "HOME", "USERPROFILE", "SystemRoot", "SYSTEMROOT", "WINDIR",
                 "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
        return {**{key: os.environ[key] for key in names if key in os.environ}, "PI_OFFLINE": "1"}


def discover() -> Runtime:
    engine = os.environ.get("CASE360_ENGINE_ROOT")
    node = shutil.which(os.environ.get("CASE360_NODE", "node"))
    if not engine or not node:
        raise RuntimeError("Configure the Case 360 runtime location and its Node executable.")
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    runs = Path(os.environ.get("CASE360_RUNS_ROOT", base / "Case360Beta/runs"))
    return Runtime(Path(engine), runs, node)
