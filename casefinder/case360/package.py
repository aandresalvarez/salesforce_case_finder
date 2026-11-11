"""Local private packages with explicit integrity checks and side-by-side runtimes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from .preferences import atomic_json, data_root


def verify(root: Path, expected: str | None = None) -> dict:
    root = root.resolve(strict=True)
    raw = (root / "release.json").read_bytes()
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Package manifest does not match the private channel digest.")
    manifest = json.loads(raw)
    if (manifest.get("schema") != "case360_private_release/1"
            or manifest.get("channel") != "private-beta"
            or manifest.get("protocol") != "case360.desktop/1"
            or not re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", manifest.get("release_id", ""))):
        raise ValueError("Incompatible private beta package.")
    actual = set()
    for file in root.rglob("*"):
        if file.is_symlink():
            raise ValueError("A release may not depend on symbolic links.")
        if file.is_file() and file != root / "release.json":
            actual.add(file.relative_to(root).as_posix())
    if actual != set(manifest["files"]):
        raise ValueError("Package file inventory changed.")
    for name, expected_hash in manifest["files"].items():
        file = root / name
        if file.resolve() != file or not file.is_relative_to(root):
            raise ValueError("Package path escapes its root.")
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected_hash:
            raise ValueError("Package content changed: " + name)
    return manifest


def context_for(root: Path, manifest: dict) -> Path:
    root = root.resolve(strict=True)
    location = data_root() / "installations" / manifest["release_id"]
    context = location / "context.json"
    previous = json.loads(context.read_text()) if context.exists() else {}
    if previous.get("engine_root") == str(root / "engine"):
        return context
    build = root / "build.json"
    value = {**previous, "schema": "case360_runtime_context/1",
             "engine_root": str(root / "engine"), "node_executable": str(root / "node/bin/node"),
             "python_executable": str(root / "python/bin/python3.13"),
             "resource_root": str(data_root() / "resources"),
             "runs_root": str(location / "runs"), "installation_id": manifest["release_id"],
             "runtime_manifest": str(build),
             "runtime_manifest_sha256": hashlib.sha256(build.read_bytes()).hexdigest(),
             "source_profile": previous.get("source_profile"),
             "authorization_policy": previous.get("authorization_policy", {
                 "live_enabled": False, "max_paid_usd": 0})}
    atomic_json(context, value)
    return context


def install(source: Path, expected: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("Supply the manifest SHA256 from the private delivery channel.")
    manifest = verify(source, expected)
    folder = data_root() / "releases"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.resolve() != folder:
        raise ValueError("Release storage must not contain links.")
    target = folder / manifest["release_id"]
    if target.exists():
        verify(target, expected)
        return target
    temporary = folder / (".install-" + uuid.uuid4().hex)
    try:
        shutil.copytree(source, temporary, symlinks=True)
        verify(temporary, expected)
        os.rename(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    context_for(target, manifest)
    return target


def installed() -> list[Path]:
    folder = data_root() / "releases"
    return sorted(p for p in folder.iterdir() if (p / "release.json").is_file()) \
        if folder.exists() else []


def activate(root: Path) -> None:
    manifest = verify(root)
    context_for(root, manifest)
    atomic_json(data_root() / "active-release.json", {"root": str(root.resolve()),
                "manifest_sha256": hashlib.sha256(
                    (root / "release.json").read_bytes()).hexdigest()})


def configure(context: Path, snapshot: str, principal: str, cap: float, route: str) -> None:
    value = json.loads(context.read_text())
    if snapshot and not re.fullmatch(r"[a-f0-9]{64}", snapshot):
        raise ValueError("Choose a verified resource snapshot SHA256.")
    policy = {"live_enabled": False, "max_paid_usd": 0}
    if cap:
        if not (snapshot and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", principal)
                and 0 < cap <= 1000 and re.fullmatch(r"[a-f0-9]{64}", route)):
            raise ValueError("Live preparation needs a snapshot, account, route proof and budget.")
        policy = {"live_enabled": True, "max_paid_usd": cap, "expected_principal": principal,
                  "bigquery_job_project": "som-rit-phi-starr-trek",
                  "route_verification_sha256": route}
    value.update(source_profile=snapshot or None, authorization_policy=policy)
    atomic_json(context, value)
