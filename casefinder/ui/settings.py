"""Settings — read-mostly, and honest about it.

FR-SET-1: almost nothing here is editable, because almost nothing here is a
preference. The project, the datasets, and the cost cap come from environment
variables so that a different site can point the app elsewhere without editing
code — but changing them from inside a running window would mean invalidating
every cache and re-probing access, which is what restarting already does.

So this page shows what the app is connected to and names the variable that
changes it. The only interactive things are the two that are genuinely
session-scoped: the era, and clearing the in-memory cache.
"""

from __future__ import annotations

from nicegui import ui

from .. import ask, config, data, views
from ..config import ERAS
from .components import filters as filter_ui
from .components import loading
from .components.actions import muted, quiet, secondary
from .state import state


def render() -> None:
    with ui.column().classes("w-full cf-reading").style("gap:0"):
        ui.label("Settings").classes("cf-h1")
        muted("Configuration comes from the environment. This page shows what took effect.")

        _connection()
        _era()
        _cost_and_cache()
        _saved_views()
        _about()


def _section(title: str) -> None:
    ui.element("div").classes("cf-divider w-full").style("margin-top:22px")
    ui.label(title).classes("cf-h2").style("margin:16px 0 8px 0")


def _rows(pairs: list[tuple[str, str]]) -> None:
    with ui.grid(columns="200px 1fr").classes("w-full").style("gap:8px 20px"):
        for label, value in pairs:
            ui.label(label).classes("cf-muted")
            ui.label(value).style("font-size:13px; overflow-wrap:anywhere")


def _connection() -> None:
    _section("Connection")
    ok, reason = data.check_access()
    with ui.row().classes("items-center").style("gap:7px; margin-bottom:10px"):
        ui.icon("check_circle" if ok else "error_outline").style(
            f"font-size:15px; color:{'#15803d' if ok else '#b91c1c'}"
        )
        ui.label(reason.splitlines()[0]).style("font-size:13px")

    _rows(
        [
            ("Project", config.PROJECT),
            ("Billing project", config.BILLING_PROJECT),
            ("Credentials", "Application Default Credentials (no key file)"),
        ]
    )
    with ui.row().style("margin-top:10px"):
        quiet("Re-check connection", _recheck, icon="refresh")


def _era() -> None:
    _section("Data era")

    def set_era(key: str) -> None:
        state.era_key = key
        ui.navigate.reload()

    filter_ui.era_select(state.era_key, ERAS, set_era)
    muted(state.era.blurb).style("margin-top:8px; max-width:560px")

    # A warehouse round trip for one line of text. Deferred rather than
    # dropped: coming straight to Settings from a cold start is the one path
    # where nothing else has asked for it yet, and the rest of the page has
    # nothing to wait for.
    loading.while_loading(
        "Checking the snapshot date…",
        lambda: data.freshness(state.era, config.STALE_DAYS),
        lambda fresh: muted(fresh.label).style("margin-top:8px"),
        # The date is context, not the point of the page. If the warehouse
        # cannot say, the section is still correct without it.
        on_error=lambda _exc: None,
    )

    _rows([("Dataset", f"{config.PROJECT}.{state.era.dataset}")])


def _cost_and_cache() -> None:
    _section("Cost and cache")
    _rows(
        [
            (
                "Per-query cap",
                f"{config.MAX_BYTES_BILLED / 1024**3:,.0f} GB scanned "
                "(CASEFINDER_MAX_BYTES)",
            ),
            ("Assumed price", f"${config.USD_PER_TIB:,.2f} per TiB (CASEFINDER_USD_PER_TIB)"),
            (
                "Result cache",
                f"{config.CACHE_TTL_SECONDS // 60} minutes, in memory only, "
                f"at most {config.CACHE_MAX_ENTRIES} entries "
                "(CASEFINDER_CACHE_TTL, CASEFINDER_CACHE_MAX_ENTRIES)",
            ),
            (
                "Filter-value cache",
                f"{config.FACET_CACHE_TTL_SECONDS // 60} minutes "
                "(CASEFINDER_FACET_CACHE_TTL)",
            ),
            (
                "Expired entries",
                (
                    f"deleted every {config.CACHE_REAP_SECONDS} seconds"
                    if config.CACHE_REAP_SECONDS
                    else "deleted when their key is next read"
                )
                + " (CASEFINDER_CACHE_REAP_SECONDS)",
            ),
            ("Stale-data warning", f"after {config.STALE_DAYS} days (CASEFINDER_STALE_DAYS)"),
        ]
    )
    with ui.row().classes("items-center").style("gap:10px; margin-top:12px"):
        secondary("Clear cached results", _clear_cache, icon="delete_sweep")
        muted(
            "Cached rows live in this process only, are deleted when they "
            "expire, and disappear entirely when it exits."
        )


def _saved_views() -> None:
    _section("Saved views")
    shared = views.shared_views()
    personal = views.personal_views()
    # Through `config.tilde` because these two lines are the ones people
    # screenshot when asking where their views went, and an absolute path names
    # the person whose machine it is. Same reason `selfcheck` does it.
    _rows(
        [
            ("Shared presets", f"{len(shared)} · {config.tilde(config.VIEWS_PATH)}"),
            ("Your views", f"{len(personal)} · {config.tilde(config.personal_views_path())}"),
        ]
    )
    muted(
        "Saved views hold filter and column choices only — never case rows, "
        "message text, or descriptions."
    ).style("margin-top:8px; max-width:560px")


def _about() -> None:
    """About lives inside Settings, not beside it — nav rule 1."""
    _section("About")
    rows = [
        ("Version", f"{config.APP_NAME} {config.VERSION}"),
        ("Window", "native desktop" if config.NATIVE else "browser"),
    ]
    # Named only when the feature is on. Reporting "Vertex AI · unavailable" to
    # someone who has no Ask destination reads as a broken dependency rather
    # than as a switch nobody threw, and it advertises a model to a reader who
    # was never offered one.
    if config.ASK_ENABLED:
        model = ask.model_name() or ("available" if ask.available() else "unavailable")
        rows.append(("Natural language", f"Vertex AI in {config.VERTEX_LOCATION} · {model}"))
    _rows(rows)
    muted(
        "Case data is read from BigQuery into memory and never written to disk. "
        "Exports contain case metadata only."
    ).style("margin-top:10px; max-width:560px")


def _recheck() -> None:
    data.reset_connection()
    ui.navigate.reload()


def _clear_cache() -> None:
    data.clear_caches()
    ui.notify("Cached results cleared", type="positive")
    ui.navigate.reload()
