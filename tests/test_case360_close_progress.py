"""Closing must block new work while allowing an existing result to finish loading."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from casefinder.case360.client import BridgeError, Client
from casefinder.case360.runtime import Runtime


def test_close_gate_allows_progress_and_artifacts_but_not_new_execution(tmp_path, monkeypatch):
    client = Client(Runtime(tmp_path, tmp_path / "runs", "node"))
    client.quiescing = True
    monkeypatch.setattr(client, "open", AsyncMock())
    exchange = AsyncMock(return_value={"observed": True})
    monkeypatch.setattr(client, "_exchange", exchange)

    async def check():
        for method in ("get_run", "read_events", "read_artifact"):
            assert (await client.request(method, run_id="run-synthetic"))["observed"]
        for method in ("start_run", "resume_run", "authorize_run", "prepare_request"):
            with pytest.raises(BridgeError) as error:
                await client.request(method, run_id="run-synthetic")
            assert error.value.code == "CLOSING"
        assert exchange.await_count == 3

    asyncio.run(check())
