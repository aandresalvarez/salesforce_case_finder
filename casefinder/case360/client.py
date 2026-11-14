"""Asynchronous, bounded NDJSON transport; the engine owns all run decisions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from .models import valid_message
from .runtime import Runtime

PROTOCOL = "case360.desktop/1"
MAX_LINE = 256 * 1024
SCHEMA_HASH = hashlib.sha256(Path(__file__).with_name("protocol.json").read_bytes()).hexdigest()


class BridgeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class Client:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.process: asyncio.subprocess.Process | None = None
        self.events: deque[dict[str, Any]] = deque(maxlen=256)
        self.diagnostics_bytes = 0
        self.progress_events_dropped = 0
        self._pending: dict[str, asyncio.Future] = {}
        self._opening = asyncio.Lock()
        self._writing = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._ready = False
        self._closed = False
        self.quiescing = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def open(self) -> None:
        async with self._opening:
            if self._ready:
                return
            if self._closed:
                raise BridgeError("CLIENT_CLOSED", "Reconnect to the local runtime.")
            command = self.runtime.command()
            self.process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=MAX_LINE, env=self.runtime.environment(),
            )
            self._tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._drain())]
            try:
                hello = await self._exchange("hello", {}, None, uuid.uuid4().hex)
                if (hello.get("protocol") != PROTOCOL or hello.get("schema_sha256") != SCHEMA_HASH
                        or hello.get("max_line_bytes") != MAX_LINE):
                    raise BridgeError("PROTOCOL_INCOMPATIBLE", "Install matching beta components.")
                self._ready = True
            except BaseException:
                await self.close()
                raise

    async def request(
        self, method: str, params: dict[str, Any] | None = None, *,
        run_id: str | None = None, request_id: str | None = None,
    ) -> dict[str, Any]:
        if self.quiescing and method not in {
            "list_runs", "get_run", "read_events", "read_artifact", "cancel_run", "get_accounting"
        }:
            raise BridgeError("CLOSING", "Return to the app before starting another action.")
        await self.open()
        return await self._exchange(method, params or {}, run_id, request_id or uuid.uuid4().hex)

    async def _exchange(self, method, params, run_id, request_id) -> dict[str, Any]:
        if not self.process or self.process.returncode is not None:
            raise BridgeError("RUNTIME_UNAVAILABLE", "The local controller has stopped.")
        message = {"protocol": PROTOCOL, "kind": "command", "request_id": request_id,
                   "run_id": run_id, "method": method, "params": params}
        line = (json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        if len(line) > MAX_LINE:
            raise BridgeError("MESSAGE_TOO_LARGE", "Use an artifact for large content.")
        if not valid_message(message):
            raise BridgeError("INVALID_COMMAND", "The command does not match the pinned protocol.")
        future = asyncio.get_running_loop().create_future()
        async with self._writing:
            if request_id in self._pending:
                raise BridgeError("REQUEST_PENDING", "This request is already pending.")
            self._pending[request_id] = future
            try:
                assert self.process.stdin is not None
                self.process.stdin.write(line)
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionError):
                self._pending.pop(request_id, None)
                raise BridgeError(
                    "RUNTIME_UNAVAILABLE", "The local controller has stopped."
                ) from None
        try:
            return await asyncio.wait_for(
                future, timeout=150 if method in {
                    "prepare_request", "prepare_conversation",
                    "prepare_intake", "intake_upload_finish"
                } else 30
            )
        finally:
            self._pending.pop(request_id, None)

    async def _read(self) -> None:
        assert self.process and self.process.stdout
        reason = BridgeError("RUNTIME_UNAVAILABLE", "The local controller has stopped.")
        try:
            while line := await self.process.stdout.readline():
                if len(line) > MAX_LINE or not line.endswith(b"\n"):
                    raise ValueError("Invalid framing")
                value = json.loads(line.decode("utf-8"))
                if not valid_message(value):
                    raise ValueError("Invalid envelope")
                kind = value.get("kind")
                if kind == "event":
                    if (not isinstance(value.get("seq"), int) or value["seq"] <= 0
                            or not isinstance(value.get("payload"), dict)):
                        raise ValueError("Invalid event")
                    if len(self.events) == self.events.maxlen:
                        self.progress_events_dropped += 1
                    self.events.append(value)
                    continue
                if kind not in {"result", "error"}:
                    raise ValueError("Invalid response")
                future = self._pending.get(value.get("request_id"))
                if not future or future.done():
                    continue
                if kind == "error":
                    error = value["error"]
                    future.set_exception(BridgeError(error["code"], error["message"]))
                else:
                    if not isinstance(value.get("result"), dict):
                        raise ValueError("Invalid result")
                    future.set_result(value["result"])
        except (ValueError, UnicodeError, KeyError, TypeError):
            reason = BridgeError("INVALID_PROTOCOL", "The controller returned an invalid message.")
            if self.process.returncode is None:
                self.process.terminate()
        finally:
            self._ready = False
            self._closed = True
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(reason)

    async def _drain(self) -> None:
        assert self.process and self.process.stderr
        while chunk := await self.process.stderr.read(65536):
            self.diagnostics_bytes += len(chunk)

    async def artifact(self, run_id: str, reference: dict[str, Any]) -> dict[str, Any]:
        total = reference["bytes"]
        if not isinstance(total, int) or not 0 <= total <= 32 * 1024 * 1024:
            raise BridgeError("ARTIFACT_TOO_LARGE", "This preview cannot display the artifact.")
        content = bytearray()
        while len(content) < total:
            offset = len(content)
            part = await self.request("read_artifact", {
                "artifact_id": reference["artifact_id"], "sha256": reference["sha256"],
                "offset": offset, "length": 65536}, run_id=run_id)
            decoded = base64.b64decode(part["data_base64"], validate=True)
            if (part["offset"] != offset or part["next_offset"] != offset + len(decoded)
                    or part["bytes"] != total or part["sha256"] != reference["sha256"]
                    or not decoded or len(content) + len(decoded) > total):
                raise BridgeError("ARTIFACT_CHANGED", "The result could not be verified.")
            content.extend(decoded)
        if hashlib.sha256(content).hexdigest() != reference["sha256"]:
            raise BridgeError("ARTIFACT_CHANGED", "The result could not be verified.")
        return json.loads(content.decode("utf-8"))

    async def close(self) -> None:
        self._closed = True
        self._ready = False
        if self.process and self.process.returncode is None:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 8)
            except TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 5)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
        for task in self._tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
