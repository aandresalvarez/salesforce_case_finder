"""Intake transport helpers. The controller owns source versions and scope decisions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re

SCOPE_LABELS = {
    "cohort": "Cohort",
    "inclusion_exclusion": "Inclusion and exclusion",
    "institution": "Institution",
    "facility": "Facility or campus",
    "index_event": "Index event",
    "age_reference": "Age reference",
    "date_window": "Dates and boundaries",
    "variables": "Data variables",
    "measurement_windows": "Measurement windows",
    "counting_rule": "Counting rule",
    "output_grain": "One output row represents",
    "deliverables": "Deliverables",
}


def researcher_text(question: dict) -> str:
    value = question.get("researcher_text", "")
    if not value or re.search(
        r"`|\b\w+_\w+\b|\b(?:SELECT|JOIN|WHERE|INFORMATION_SCHEMA)\b|\b[\w-]+\.[\w-]+\.[\w-]+\b",
        value,
    ):
        return "Please ask the analyst to provide researcher wording."
    return value


def question_suggestions(question: dict) -> list[dict]:
    """Project only plain-language advice; technical detail stays in the analyst view."""
    supplied = question.get("suggestions")
    if not isinstance(supplied, list):
        return []
    return [
        s for s in supplied[:3]
        if isinstance(s, dict)
        and s.get("basis") in {"documented", "inference"}
        and all(
            isinstance(s.get(key), str) and s[key].strip()
            and researcher_text({"researcher_text": s[key]}) == s[key]
            for key in ["answer", "rationale"]
        )
    ]


def researcher_export(state: dict) -> str:
    blocks = []
    for i, q in enumerate(state.get("questions", []), 1):
        lines = [f"{i}. {researcher_text(q)}"]
        if not state.get("analysis_stale"):
            for s in question_suggestions(q):
                label = "AI inference" if s["basis"] == "inference" else "Source-based suggestion"
                lines.extend(
                    [f"Suggested answer ({label}): {s['answer']}", f"Why: {s['rationale']}"]
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


class IntakeSession:
    def __init__(self, client, remember=lambda run_id: None):
        self.client = client
        self.remember = remember
        self.run_id = None
        self.state: dict = {}
        self.lock = asyncio.Lock()

    async def load(self, run_id: str) -> dict:
        self.run_id = run_id
        result = await self.client.request("intake_get", run_id=run_id)
        self.state = await self.client.artifact(run_id, result["artifact"])
        self.remember(run_id)
        return self.state

    async def ensure(self, text: str) -> None:
        if not self.run_id:
            result = await self.client.request("intake_create", {"text": text})
            await self.load(result["run_id"])

    async def update(self, action: str, value: dict, text: str = "") -> None:
        async with self.lock:
            await self.ensure(text)
            result = await self.client.request(
                "intake_update",
                {
                    "expected_revision": self.state["revision"],
                    "action": action,
                    "value": value,
                },
                run_id=self.run_id,
            )
            self.state = await self.client.artifact(self.run_id, result["artifact"])

    async def upload(
        self, name: str, data: bytes, *, text="", kind="document", date="", reference=""
    ) -> None:
        if not 0 < len(data) <= 20 * 1024 * 1024:
            raise ValueError("Choose a nonempty file up to 20 MB.")
        async with self.lock:
            await self.ensure(text)
            source = await self.client.request(
                "intake_upload_begin",
                {
                    "expected_revision": self.state["revision"],
                    "name": name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "kind": kind,
                    "date": date,
                    "reference": reference,
                },
                run_id=self.run_id,
            )
            for offset in range(0, len(data), 49152):
                await self.client.request(
                    "intake_upload_chunk",
                    {
                        "source_id": source["source_id"],
                        "offset": offset,
                        "data_base64": base64.b64encode(data[offset : offset + 49152]).decode(),
                    },
                    run_id=self.run_id,
                )
            result = await self.client.request(
                "intake_upload_finish",
                {
                    "expected_revision": self.state["revision"],
                    "source_id": source["source_id"],
                },
                run_id=self.run_id,
            )
            self.state = await self.client.artifact(self.run_id, result["artifact"])

    async def original(self, source: dict) -> bytes:
        data = bytearray()
        while len(data) < source["bytes"]:
            part = await self.client.request(
                "intake_source_read",
                {
                    "source_id": source["id"],
                    "offset": len(data),
                    "original": True,
                },
                run_id=self.run_id,
            )
            chunk = base64.b64decode(part["data_base64"], validate=True)
            if not chunk:
                raise ValueError("The saved attachment could not be read completely.")
            data.extend(chunk)
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("The saved attachment has changed.")
        return bytes(data)

    async def prepare(self, action: str) -> dict:
        async with self.lock:
            result = await self.client.request(
                "prepare_intake",
                {
                    "expected_revision": self.state["revision"],
                    "action": action,
                },
                run_id=self.run_id,
            )
            await self.load(result["run_id"])
            return result
