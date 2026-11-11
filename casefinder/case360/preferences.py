"""Per-installation analyst settings; no analyst, host or credential is built in."""
from __future__ import annotations

import json
import os
import platform
import tempfile
from pathlib import Path


def data_root() -> Path:
    override = os.environ.get("CASE360_DATA_ROOT")
    if override:
        root = Path(override).expanduser()
    elif platform.system() == "Darwin":
        root = Path.home() / "Library/Application Support/Case360Beta"
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Case360Beta"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Case360Beta"
    if not root.is_absolute():
        raise ValueError("Choose an absolute private data location.")
    return root


def read() -> dict:
    path = data_root() / "analyst-profile.json"
    if not path.exists():
        return {"analyst": "", "environment": "", "runtime_context": ""}
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("The analyst profile must stay inside the private data location.")
    value = json.loads(path.read_text())
    return {key: str(value.get(key, "")) for key in ("analyst", "environment", "runtime_context")}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError("The configuration path must not contain links.")
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def save(analyst: str, environment: str, runtime_context: str) -> dict:
    if any(len(value) > 128 for value in (analyst, environment)):
        raise ValueError("Analyst and environment labels must be at most 128 characters.")
    if runtime_context and not Path(runtime_context).expanduser().is_absolute():
        raise ValueError("Choose an absolute runtime configuration file.")
    value = {"analyst": analyst.strip(), "environment": environment.strip(),
             "runtime_context": str(Path(runtime_context).expanduser()) if runtime_context else ""}
    atomic_json(data_root() / "analyst-profile.json", value)
    return value
