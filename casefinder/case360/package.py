"""Local private packages with explicit integrity checks and side-by-side runtimes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from . import platforms
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
    links = {}
    for file in platforms.payload_files(root):
        if platforms.is_link(file):
            name = file.relative_to(root).as_posix()
            target = manifest.get("links", {}).get(name, "")
            if (not target or Path(target).is_absolute()
                    or not file.resolve(strict=True).is_relative_to(root)
                    or file.resolve() != (file.parent / target).resolve()):
                raise ValueError("A release link may not leave its package.")
            links[name] = target
            continue
        if file.is_file() and file != root / "release.json":
            actual.add(file.relative_to(root).as_posix())
    if actual != set(manifest["files"]) or links != manifest.get("links", {}):
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
    # Carry personal settings to a new release; keep old run roots and evidence intact.
    if not previous and (data_root() / "active-release.json").is_file():
        active = json.loads((data_root() / "active-release.json").read_text())
        old_release = json.loads((Path(active["root"]) / "release.json").read_text())["release_id"]
        old_context = data_root() / "installations" / old_release / "context.json"
        if old_context.is_file():
            old = json.loads(old_context.read_text())
            previous = {
                key: old[key]
                for key in (
                    "google_account",
                    "google_credentials",
                    "authorization_policy",
                    "tester_budget_file",
                )
                if key in old
            }
    build = root / "build.json"
    value = {
        **previous,
        "schema": "case360_runtime_context/1",
        "engine_root": str(root / "engine"),
        "node_executable": str(platforms.node_path(root)),
        "python_executable": str(platforms.python_path(root)),
        "resource_root": str(location / "resources"),
        "runs_root": str(location / "runs"),
        "installation_id": "release-"
        + hashlib.sha256(manifest["release_id"].encode()).hexdigest()[:32],
        "runtime_manifest": str(build),
        "runtime_manifest_sha256": hashlib.sha256(build.read_bytes()).hexdigest(),
        "source_profile": previous.get("source_profile"),
        "authorization_policy": previous.get(
            "authorization_policy", {"live_enabled": False, "max_paid_usd": 0}
        ),
    }
    atomic_json(context, value)
    return context


def install(source: Path, expected: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("Supply the manifest SHA256 from the private delivery channel.")
    manifest = verify(source, expected)
    if manifest.get("platform") and manifest["platform"] != platforms.target():
        raise ValueError("This package is for a different operating system or processor.")
    # Short Windows paths leave room for the bundled SDK's nested modules even
    # on machines which have not enabled the system-wide long-path policy.
    folder = data_root() / ("r" if os.name == "nt" else "releases")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.resolve() != folder:
        raise ValueError("Release storage must not contain links.")
    name = hashlib.sha256(manifest["release_id"].encode()).hexdigest()[:16] \
        if os.name == "nt" else manifest["release_id"]
    target = folder / name
    if target.exists():
        verify(target, expected)
        return target
    temporary = folder / (".install-" + uuid.uuid4().hex)
    try:
        platforms.copy_payload(source, temporary, manifest.get("links", {}))
        verify(temporary, expected)
        # Windows junctions are absolute. Recreate them after moving the stage.
        if os.name == "nt":
            for name in manifest.get("links", {}):
                os.rmdir(temporary / name)
        os.rename(temporary, target)
        platforms.restore_links(target, manifest.get("links", {}))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    context_for(target, manifest)
    return target


def installed() -> list[Path]:
    roots = {p for name in ("releases", "r") for p in (data_root() / name).glob("*")
             if (p / "release.json").is_file()}
    # Include the original app bundle so the first update can roll back to it.
    for context in (data_root() / "installations").glob("*/context.json"):
        try:
            root = Path(json.loads(context.read_text())["engine_root"]).parent
            release = json.loads((root / "release.json").read_text())
            if root.is_absolute() and release["release_id"] == context.parent.name:
                roots.add(root)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(roots)


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
        if not (
            snapshot
            and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", principal)
            and 0 < cap <= 1000
            and re.fullmatch(r"[a-f0-9]{64}", route)
        ):
            raise ValueError("Live preparation needs a snapshot, account, route proof and budget.")
        policy = {
            "live_enabled": True,
            "max_paid_usd": cap,
            "expected_principal": principal,
            "bigquery_job_project": "som-rit-phi-starr-trek",
            "route_verification_sha256": route,
        }
    value.update(source_profile=snapshot or None, authorization_policy=policy)
    if principal:
        from . import budgets

        limits = budgets.ensure(principal, cap)
        budgets.save(principal, limits["total_usd"], cap)
        value["tester_budget_file"] = str(budgets.database())
    atomic_json(context, value)
