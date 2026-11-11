"""One controller per desktop process, shared by all views."""

from .client import Client
from .runtime import discover

_client: Client | None = None
_closing = False


def client() -> Client:
    global _client
    if _closing:
        raise RuntimeError("The app is closing. Return before starting another action.")
    if _client is None:
        _client = Client(discover())
    return _client


async def reconnect() -> Client:
    """Explicit reconnection never resubmits an interrupted command."""
    global _client
    if _closing:
        raise RuntimeError("The app is closing.")
    if _client is not None:
        if not _client.closed:
            return _client
        await _client.close()
    _client = Client(discover())
    await _client.open()
    return _client


async def history(c: Client) -> list[dict]:
    rows: list[dict] = []
    while True:
        page = await c.request("list_runs", {"offset": len(rows), "limit": 100})
        rows.extend(page["runs"])
        if len(rows) >= page["total"] or not page["runs"]:
            return rows


async def begin_close() -> list[dict]:
    global _closing
    _closing = True
    if _client is None:
        return []
    _client.quiescing = True
    return [row for row in await history(_client) if row["process_active"]]


def return_to_app() -> None:
    global _closing
    _closing = False
    if _client is not None:
        _client.quiescing = False


async def stop_for_close() -> None:
    if _client is not None:
        for row in await history(_client):
            if row["process_active"] and row["execution_status"] == "RUNNING":
                await _client.request("cancel_run", run_id=row["run_id"])
        if any(row["process_active"] for row in await history(_client)):
            raise RuntimeError(
                "Process exit could not be verified. Return to the app and inspect history."
            )
    await close()


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def prepare_reconfigure() -> None:
    """No active or unverified owner may be hidden by switching configuration."""
    if _client is None:
        return
    try:
        if await begin_close():
            raise RuntimeError("Stop active work before changing installation settings.")
        await stop_for_close()
    finally:
        return_to_app()
