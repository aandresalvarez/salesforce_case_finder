"""Install an explicitly selected private delivery without replacing Case Finder."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

from . import package, platforms, preferences


def selected() -> Path | None:
    file = preferences.data_root() / "active-release.json"
    if not file.exists():
        return None
    value = json.loads(file.read_text())
    root = Path(value["root"])
    manifest = package.verify(root, value["manifest_sha256"])
    if manifest.get("platform") != platforms.target():
        raise ValueError("The installed beta is for a different operating system.")
    return root


def _digest(file: Path) -> str:
    with file.open("rb") as stream:
        return _legacy_digest(stream)


def _legacy_digest(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def install_archive(archive: Path) -> Path:
    """ZIP comes from the pilot owner, not from the public wheel update channel."""
    with tempfile.TemporaryDirectory(prefix="case360-delivery-") as temporary:
        stage = Path(temporary).resolve()
        with zipfile.ZipFile(archive) as opened:
            members = opened.infolist()
            if sum(item.file_size for item in members) > 5 * 1024**3:
                raise ValueError("This download exceeds the beta package size limit.")
            for item in members:
                destination = stage / item.filename
                if ("\\" in item.filename or not destination.resolve().is_relative_to(stage)
                        or (item.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("The download contains an invalid file path.")
            opened.extractall(stage)
        metadata_files = list(stage.glob("*/installer.json"))
        if len(metadata_files) != 1:
            raise ValueError("Choose the original Case Finder Beta pilot ZIP.")
        metadata_file = metadata_files[0]
        metadata = json.loads(metadata_file.read_text())
        if metadata.get("schema") != "case360_wheel_installer/1":
            raise ValueError("This download is not a compatible beta installer.")
        if metadata.get("platform") != platforms.target():
            raise ValueError("Choose the pilot ZIP for your operating system and processor.")
        delivery = metadata_file.parent
        wheel = delivery / metadata["wheel"]
        if wheel.parent != delivery or _digest(wheel) != metadata["wheel_sha256"]:
            raise ValueError("The included Case Finder wheel has changed.")
        resources = delivery / "runtime"
        if not resources.is_dir():
            payload = delivery / "runtime.tar.gz"
            if _digest(payload) != metadata["runtime_archive_sha256"]:
                raise ValueError("The beta download is incomplete or changed.")
            with tarfile.open(payload) as opened:
                opened.extractall(delivery, filter="data")
        manifest = json.loads((resources / "release.json").read_text())
        platforms.restore_links(resources, manifest.get("links", {}))
        target = package.install(resources, metadata["manifest_sha256"])
        package.activate(target)
        return target


def open_beta(root: Path) -> None:
    package.verify(root)
    log = preferences.data_root() / "startup.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "NODE_OPTIONS", "CASE360_RUNTIME_CONTEXT"):
        env.pop(name, None)
    with log.open("ab") as output:
        subprocess.Popen(platforms.launch_command(root, "--setup"), env=env,
                         stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                         start_new_session=True)
