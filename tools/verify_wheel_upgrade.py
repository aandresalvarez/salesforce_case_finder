"""Install the old and new wheels in a disposable user environment; preserve saved state."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--published", action="store_true")
    parser.add_argument("--version", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    repo = "https://github.com/aandresalvarez/salesforce_case_finder/releases/download"
    published = f"{repo}/v{args.version}/casefinder-{args.version}-py3-none-any.whl"
    candidate = published if args.published else str(args.wheel.resolve())
    with tempfile.TemporaryDirectory(prefix="casefinder-wheel-upgrade-") as temporary:
        root = Path(temporary)
        profile = root / "saved-state"
        profile.mkdir()
        saved = {
            "personal_views.json": '{"views":[{"name":"Synthetic saved view"}]}',
            "beta/analyst-profile.json": '{"analyst":"Synthetic tester"}',
            "beta/active-release.json": '{"release_id":"retained-private-beta"}',
            "beta/request/answers.json": '{"counting_rule":"Distinct patients"}',
            "beta/request/query-v1.sql": "SELECT 'synthetic' AS example",
            "beta/request/attachment.md": "Synthetic scope document",
            "beta/context.json": '{"total_cap_usd":500,"max_paid_usd":50}',
        }
        for name, text in saved.items():
            file = profile / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text, encoding="utf-8")
        before = {name: hashlib.sha256((profile / name).read_bytes()).hexdigest()
                  for name in saved}
        env = {**os.environ, "UV_TOOL_DIR": str(root / "tools"),
               "UV_TOOL_BIN_DIR": str(root / "bin"), "UV_NO_CONFIG": "1",
               "CASEFINDER_PERSONAL_VIEWS_PATH": str(profile / "personal_views.json"),
               "CASE360_DATA_ROOT": str(profile / "beta"), "CASEFINDER_UPDATE_CHECK": "0",
               "CLOUDSDK_CONFIG": str(root / "no-google-account"),
               "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1"}
        for name in ("CASE360_CHANNEL", "CASEFINDER_CASE360", "CASE360_RUNTIME_CONTEXT",
                     "CASEFINDER_CASE360_AVAILABLE", "PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)

        def run(command: list[str]) -> subprocess.CompletedProcess:
            result = subprocess.run(command, env=env, cwd=root, text=True,
                                    capture_output=True, timeout=180)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            return result

        run(["uv", "tool", "install", "--python", "3.13",
             f"{repo}/v2.1.4/casefinder-2.1.4-py3-none-any.whl"])
        entry = root / "bin" / ("casefinder.exe" if os.name == "nt" else "casefinder")
        assert "2.1.4" in run([str(entry), "--version"]).stdout
        if args.published:
            update = subprocess.run([str(entry), "--update"], env=env, cwd=root,
                                    text=True, capture_output=True, timeout=180)
            assert published in update.stdout, update.stdout + update.stderr
            assert update.returncode == (1 if os.name == "nt" else 0), update.stderr
        if not args.published or os.name == "nt":
            run(["uv", "tool", "install", "--force", "--python", "3.13", candidate])
        assert args.version in run([str(entry), "--version"]).stdout
        python = root / "tools/casefinder" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(python), "-c", "from casefinder import config,main; from nicegui import app; "
             "assert config.CASE360_AVAILABLE and not config.CASE360_ENABLED; "
             "assert {'/search','/lists','/sql','/case360'} <= {r.path for r in app.routes}; "
             "assert config._resolve_views_path().is_file()"])
        assert before == {name: hashlib.sha256((profile / name).read_bytes()).hexdigest()
                          for name in saved}
        args.report.write_text(json.dumps({"version": args.version, "old_version": "2.1.4",
            "platform": os.name, "published_updater": args.published,
            "beta_available": True, "legacy_routes_available": True,
            "preserved_saved_files": len(saved), "clinical_queries": 0}, indent=2) + "\n")


if __name__ == "__main__":
    main()
