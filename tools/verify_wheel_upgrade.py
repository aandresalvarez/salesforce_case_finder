"""Install the old and new wheels in a disposable user environment; preserve saved state."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def fixture(root: Path) -> tuple[dict[str, str], Path]:
    """Use an executable local stand-in for the private, platform-specific runtime."""
    runtime = root / "Synthetic beta with spaces"
    runtime.mkdir()
    marker = root / "companion-launched.txt"
    if os.name == "nt":
        # The real adapter calls pythonw.exe in the selected runtime. Use the
        # CI Python installation so the test exercises process creation too.
        shutil.copytree(sys.base_prefix, runtime / "python",
                        ignore=shutil.ignore_patterns("__pycache__", "site-packages"))
        assert (runtime / "python/pythonw.exe").is_file()
        with (runtime / "launch.py").open("w", encoding="utf-8") as stream:
            stream.write("import os, sys\nfrom pathlib import Path\n"
                         "with Path(os.environ['CASEFINDER_SMOKE_MARKER']).open('a') as log:\n"
                         "    log.write(sys.argv[1] + '\\n')\n")
    else:
        launch = runtime / "launch"
        launch.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$CASEFINDER_SMOKE_MARKER"\n')
        launch.chmod(0o700)
    settings = runtime / "pilot-resources/bootstrap.json"
    settings.parent.mkdir()
    settings.write_text("{}")
    assets = {p.relative_to(runtime).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in runtime.rglob("*") if p.is_file()}
    manifest = runtime / "release.json"
    platform = "windows-x64" if os.name == "nt" else "darwin-arm64"
    release_id = "retained-private-beta"
    manifest.write_text(json.dumps({
        "schema": "case360_private_release/1", "channel": "private-beta",
        "protocol": "case360.desktop/1", "release_id": release_id,
        "platform": platform, "files": assets,
    }))
    return {
        "personal_views.json": '{"views":[{"name":"Synthetic saved view"}]}',
        "beta/analyst-profile.json": '{"analyst":"Synthetic tester"}',
        "beta/active-release.json": json.dumps({
            "root": str(runtime),
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        }),
        "beta/active-conversation.json": '{"run_id":"run-synthetic"}',
        "beta/assignments.json": '{"example":"saved settings"}',
        f"beta/installations/{release_id}/context.json": (
            '{"authorization_policy":{"live_enabled":true,"max_paid_usd":50}}'
        ),
        f"beta/installations/{release_id}/runs/run-synthetic/answers.json": (
            '{"counting_rule":"Distinct patients"}'
        ),
        f"beta/installations/{release_id}/runs/run-synthetic/query-v1.sql": "SELECT 'synthetic'",
        f"beta/installations/{release_id}/runs/run-synthetic/attachment.md": "Synthetic document",
        "beta/budget.json": '{"total_cap_usd":500,"used_usd":12}',
    }, marker


def check_sidebar(python: Path, root: Path, env: dict[str, str], marker: Path) -> None:
    """Click the real installed page and observe the detached process on this OS."""
    server_code = """
from pathlib import Path
from casefinder import data, main
from nicegui import ui
data.check_access = lambda: (True, 'Synthetic test connection')
port = main._free_port()
Path('test-port.txt').write_text(str(port))
ui.run(host=main.HOST, port=port, reload=False, show=False)
"""
    with (root / "browser-server.log").open("w+", encoding="utf-8") as log:
        process = subprocess.Popen([str(python), "-c", server_code], env=env, cwd=root,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            port_file = root / "test-port.txt"
            deadline = time.monotonic() + 25
            while not port_file.is_file() and time.monotonic() < deadline:
                assert process.poll() is None, "Case Finder exited before serving"
                time.sleep(0.1)
            port = port_file.read_text()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                origin = f"http://127.0.0.1:{port}"
                response = page.request.get(origin + "/case360")
                assert response.ok and not marker.exists(), "An HTTP probe launched the beta"
                page.goto(origin + "/settings", wait_until="domcontentloaded")
                page.get_by_role("link", name="Manage beta installation").click()
                expect(page.get_by_role("button", name="Update from private ZIP")).to_be_visible()
                assert not marker.exists(), "Opening Settings launched the beta"
                page.locator(".cf-rail").get_by_text("Case 360 Beta", exact=True).click()
                launched = page.get_by_text("Case 360 Beta is opening in a separate window.")
                expect(launched).to_be_visible(timeout=20_000)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if marker.is_file() and marker.stat().st_size:
                        break
                    time.sleep(0.1)
                assert marker.read_text().splitlines() == ["--review"]
                expect(page.get_by_role("button", name="Update from private ZIP")).to_have_count(0)
                browser.close()
        except Exception:
            log.seek(0)
            print(log.read())
            raise
        finally:
            process.terminate()
            process.wait(timeout=15)


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
        saved, marker = fixture(root)
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
               "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1",
               "CASEFINDER_SMOKE_MARKER": str(marker)}
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
             f"{repo}/v2.2.1/casefinder-2.2.1-py3-none-any.whl"])
        entry = root / "bin" / ("casefinder.exe" if os.name == "nt" else "casefinder")
        assert "2.2.1" in run([str(entry), "--version"]).stdout
        if args.published:
            update = subprocess.run([str(entry), "--update"], env=env, cwd=root,
                                    text=True, capture_output=True, timeout=180)
            if os.name == "nt":
                assert published in update.stdout, update.stdout + update.stderr
            assert update.returncode == (1 if os.name == "nt" else 0), (
                update.stdout + update.stderr)
        if not args.published or os.name == "nt":
            run(["uv", "tool", "install", "--force", "--python", "3.13", candidate])
        assert args.version in run([str(entry), "--version"]).stdout
        python = root / "tools/casefinder" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python")
        if args.published:
            run([str(python), "-c", "import json,sys; "
                 "from importlib.metadata import distribution; "
                 "receipt=json.loads(distribution('casefinder').read_text('direct_url.json')); "
                 "assert receipt['url']==sys.argv[1], receipt", published])
        run([str(python), "-c", "from casefinder import config,main; from nicegui import app; "
             "assert config.CASE360_AVAILABLE and not config.CASE360_ENABLED; "
             "assert {'/search','/lists','/sql','/case360'} <= {r.path for r in app.routes}; "
             "assert config._resolve_views_path().is_file()"])
        check_sidebar(python, root, env, marker)
        assert before == {name: hashlib.sha256((profile / name).read_bytes()).hexdigest()
                          for name in saved}
        args.report.write_text(json.dumps({"version": args.version, "old_version": "2.2.1",
            "platform": os.name, "published_updater": args.published,
            "beta_available": True, "legacy_routes_available": True,
            "sidebar_click_launched_companion_once": True, "zip_management_in_settings": True,
            "preserved_saved_files": len(saved), "clinical_queries": 0}, indent=2) + "\n")


if __name__ == "__main__":
    main()
