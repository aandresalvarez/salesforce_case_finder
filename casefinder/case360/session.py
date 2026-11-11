"""One controller per desktop process, shared by all views."""

from .client import Client
from .runtime import discover

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = Client(discover())
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
