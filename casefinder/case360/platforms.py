"""Platform-specific executables; UI, requests and protocol stay shared."""
from __future__ import annotations

import os
import platform
import shutil
import stat
from pathlib import Path


def target() -> str:
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "darwin-arm64"
    if system == "Darwin" and machine in {"x86_64", "amd64"}:
        return "darwin-x64"
    raise ValueError("This beta package supports Windows x64 and compatible Mac releases.")


def python_path(root: Path, *, windows: bool | None = None) -> Path:
    windows = os.name == "nt" if windows is None else windows
    return root / ("python/python.exe" if windows else "python/bin/python3.13")


def node_path(root: Path, *, windows: bool | None = None) -> Path:
    windows = os.name == "nt" if windows is None else windows
    return root / ("node/node.exe" if windows else "node/bin/node")


def google_command(root: Path, *, windows: bool | None = None) -> list[str]:
    windows = os.name == "nt" if windows is None else windows
    if windows:
        # Avoid shell parsing of the user's email and credential paths.
        return [str(python_path(root, windows=True)), "-B",
                str(root / "google-cloud-sdk/lib/gcloud.py")]
    return [str(root / "google-cloud-sdk/bin/gcloud")]


def launch_command(root: Path, *args: str, windowed: bool = False) -> list[str]:
    if os.name == "nt":
        python = python_path(root)
        if windowed:
            python = python.with_name("pythonw.exe")
        return [str(python), "-X", "utf8", "-P", "-B", str(root / "launch.py"), *args]
    return [str(root / "launch"), *args]


def is_link(file: Path) -> bool:
    if file.is_symlink():
        return True
    # Case Finder's public wheel also supports Python 3.10/3.11, before
    # Path.is_junction was added. Windows reports the reparse tag via lstat.
    return os.name == "nt" and getattr(file.lstat(), "st_reparse_tag", None) == getattr(
        stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003
    )


def payload_files(root: Path):
    """Walk a payload once, without following the Windows dependency junction."""
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in list(directories):
            file = Path(folder) / name
            if is_link(file):
                directories.remove(name)
                yield file
        for name in files:
            yield Path(folder) / name


def restore_links(root: Path, links: dict[str, str]) -> None:
    for name, relative in links.items():
        file = root / name
        target = (file.parent / relative).resolve(strict=True)
        if (Path(name).is_absolute() or ".." in Path(name).parts
                or not target.is_relative_to(root.resolve()) or Path(relative).is_absolute()):
            raise ValueError("A release link may not leave its package.")
        if file.exists():
            if not is_link(file) or file.resolve() != target:
                raise ValueError("Release dependency link changed.")
            continue
        if os.name == "nt":
            # Junctions need neither administrator access nor Developer Mode.
            import _winapi

            _winapi.CreateJunction(str(target), str(file))
        else:
            file.symlink_to(relative, target_is_directory=target.is_dir())


def copy_payload(source: Path, target: Path, links: dict[str, str]) -> None:
    def ignore(folder, names):
        return [name for name in names if is_link(Path(folder) / name)]

    shutil.copytree(source, target, ignore=ignore)
    restore_links(target, links)
