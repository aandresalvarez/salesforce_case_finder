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


def _selection(*, verify_payload: bool = True) -> tuple[Path, dict] | None:
    file = preferences.data_root() / "active-release.json"
    if not file.exists():
        return None
    value = json.loads(file.read_text())
    root = Path(value["root"])
    read = package.verify if verify_payload else package.read_manifest
    manifest = read(root, value["manifest_sha256"])
    if manifest.get("platform") != platforms.target():
        raise ValueError("The installed beta is for a different operating system.")
    return root, manifest


def selected(*, verify_payload: bool = True) -> Path | None:
    selected_package = _selection(verify_payload=verify_payload)
    return selected_package[0] if selected_package else None


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


def open_beta() -> bool:
    selected_package = _selection()
    if selected_package is None:
        return False
    root, manifest = selected_package
    data_root = preferences.data_root()
    context_path = data_root / "installations" / manifest["release_id"] / "context.json"
    context = json.loads(context_path.read_text()) if context_path.is_file() else {}
    # All shipped companions can open the local review. Only the pilot package
    # has onboarding, and a configured pilot should reopen its saved work.
    bundled_setup = "pilot-resources/bootstrap.json" in manifest["files"]
    needs_setup = bundled_setup and not context.get("authorization_policy", {}).get("live_enabled")
    start = "--setup" if needs_setup else "--review"
    log = data_root / "startup.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "NODE_OPTIONS", "CASE360_RUNTIME_CONTEXT"):
        env.pop(name, None)
    with log.open("ab") as output:
        options = (
            {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt" else {"start_new_session": True}
        )
        subprocess.Popen(platforms.launch_command(root, start, windowed=True), env=env,
                         stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                         **options)
    return True
