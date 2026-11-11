"""Explicit local runtime discovery. Never installs or contacts a provider."""

from __future__ import annotations

import json
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
    context_file: Path | None = None

    def command(self) -> list[str]:
        if os.environ.get("NODE_OPTIONS"):
            raise RuntimeError("NODE_OPTIONS must be unset for the beta runtime.")
        root = self.engine_root.resolve(strict=True)
        loader = root / "pi_harness/node_modules/tsx/dist/loader.mjs"
        worker = root / "desktop_bridge/worker.mjs"
        if not loader.is_file() or not worker.is_file():
            raise RuntimeError("The compatible Case 360 desktop runtime is not installed.")
        arguments = (["--context", str(self.context_file.resolve(strict=True))]
                     if self.context_file else [str(self.runs_root.resolve())])
        return [self.node, "--import", str(loader), str(worker), *arguments]

    def environment(self) -> dict[str, str]:
        # Carry only OS essentials. Ask configuration and provider credentials are
        # unnecessary for this synthetic preview and must not select its runtime.
        names = ("PATH", "HOME", "USERPROFILE", "SystemRoot", "SYSTEMROOT", "WINDIR",
                 "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
        return {**{key: os.environ[key] for key in names if key in os.environ}, "PI_OFFLINE": "1"}


def discover() -> Runtime:
    context = os.environ.get("CASE360_RUNTIME_CONTEXT")
    if context:
        location = Path(context).resolve(strict=True)
        data = json.loads(location.read_text())
        if data.get("schema") != "case360_runtime_context/1":
            raise RuntimeError("The Case 360 runtime context is incompatible.")
        if any(not isinstance(data.get(key), str) or not Path(data[key]).is_absolute()
               for key in ("engine_root", "runs_root", "node_executable")):
            raise RuntimeError("The Case 360 context requires explicit absolute runtime paths.")
        # The engine verifies the pinned manifest, root confinement and policy.
        # Do not merge Ask settings or legacy overrides into an explicit context.
        return Runtime(Path(data["engine_root"]), Path(data["runs_root"]),
                       data["node_executable"], location)
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
