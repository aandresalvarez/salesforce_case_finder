"""Protocol failures exercise real subprocess pipes without any private runtime."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

from casefinder.case360.client import MAX_LINE, PROTOCOL, SCHEMA_HASH, BridgeError, Client
from casefinder.case360.models import valid_message

FIXTURES = json.loads((Path(__file__).parent / "case360_fixtures/protocol.json").read_text())


@pytest.mark.parametrize("message", FIXTURES["valid"])
def test_shared_valid_commands(message):
    assert valid_message(message)


@pytest.mark.parametrize("message", FIXTURES["invalid"])
def test_shared_invalid_commands(message):
    assert not valid_message(message)


class FakeRuntime:
    def __init__(self, script: Path):
        self.script = script

    def command(self):
        return [sys.executable, "-u", str(self.script)]

    def environment(self):
        return {}


def fake(tmp_path: Path, operation: str) -> Client:
    script = tmp_path / "fake_worker.py"
    script.write_text(
        "import sys,json,time\n"
        f"P={PROTOCOL!r}\nS={SCHEMA_HASH!r}\n"
        "for line in sys.stdin.buffer:\n"
        " c=json.loads(line)\n"
        " if c['method']=='hello':\n"
        "  result={'protocol':P,'schema_sha256':S,'max_line_bytes':262144}\n"
        " else:\n" + "\n".join("  " + s for s in operation.splitlines()) + "\n"
        " response=json.dumps({'protocol':P,'kind':'result',"
        "'request_id':c['request_id'],'result':result},ensure_ascii=False).encode()+b'\\n'\n"
        " for i in range(0,len(response),7):\n"
        "  sys.stdout.buffer.write(response[i:i+7]);sys.stdout.buffer.flush()\n"
    )
    return Client(FakeRuntime(script))


def test_partial_utf8_and_abundant_stderr_do_not_block(tmp_path):
    async def check():
        client = fake(tmp_path, "sys.stderr.write('synthetic diagnostic\\n'*100000)\n"
                      "sys.stderr.flush()\nresult={'text':'síntesis μL 🧪'}")
        try:
            assert (await client.request("health"))["text"] == "síntesis μL 🧪"
            assert client.diagnostics_bytes > MAX_LINE
        finally:
            await client.close()
    asyncio.run(check())


@pytest.mark.parametrize("operation", [
    "sys.stdout.write('not json\\n');sys.stdout.flush();time.sleep(2)",
    "sys.stdout.write('x'*262145+'\\n');sys.stdout.flush();time.sleep(2)",
    "sys.stdout.buffer.write(b'\\xff\\n');sys.stdout.buffer.flush();time.sleep(2)",
])
def test_corrupt_or_oversize_stdout_is_a_visible_error(tmp_path, operation):
    async def check():
        client = fake(tmp_path, operation + "\nresult={}")
        try:
            with pytest.raises(BridgeError, match="invalid message"):
                await client.request("health")
        finally:
            await client.close()
    asyncio.run(check())


def test_schema_mismatch_stops_before_commands(tmp_path):
    async def check():
        client = fake(tmp_path, "raise AssertionError('must not reach another command')")
        path = client.runtime.script
        path.write_text(path.read_text().replace(SCHEMA_HASH, "0" * 64))
        with pytest.raises(BridgeError) as error:
            await client.open()
        assert error.value.code == "PROTOCOL_INCOMPATIBLE"
        assert client.process.returncode is not None
    asyncio.run(check())


def test_oversize_command_is_rejected_before_write(tmp_path):
    async def check():
        client = fake(tmp_path, "raise AssertionError('oversize command reached worker')")
        try:
            with pytest.raises(BridgeError) as error:
                await client.request("health", {"text": "é" * MAX_LINE})
            assert error.value.code == "MESSAGE_TOO_LARGE"
        finally:
            await client.close()
    asyncio.run(check())


def test_large_artifact_is_reassembled_and_hash_checked():
    payload = json.dumps({"text": "síntesis 🧪 " * 40000}, ensure_ascii=False).encode()
    reference = {"artifact_id": "result", "bytes": len(payload),
                 "sha256": hashlib.sha256(payload).hexdigest()}

    class PagedClient(Client):
        async def request(self, method, params=None, **kwargs):
            offset = params["offset"]
            chunk = payload[offset:offset + params["length"]]
            return {**reference, "offset": offset, "next_offset": offset + len(chunk),
                    "data_base64": base64.b64encode(chunk).decode()}

    async def check():
        client = PagedClient(None)
        assert await client.artifact("run-1", reference) == json.loads(payload)
        with pytest.raises(BridgeError, match="verified"):
            await client.artifact("run-1", {**reference, "sha256": "0" * 64})
    asyncio.run(check())
