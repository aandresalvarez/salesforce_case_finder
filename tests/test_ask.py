"""Natural-language mode — FR-ASK-1..5 and the PHI rule in spec section 9.3.

The property that matters most here cannot be checked by reading the feature's
description: what actually leaves the machine. Everything else about Ask is a
convenience, but a prompt that carried one case body would put PHI in a hosted
model, so the prompt is captured and inspected rather than trusted.

Nothing in this file reaches Vertex. A fake client records the requests it was
handed, which is the whole subject.
"""

from __future__ import annotations

import pytest

from casefinder import ask, config

CURRENT = config.ERAS["current"]
ARCHIVE = config.ERAS["archive"]


class FakeModels:
    def __init__(self, reply: str = "SELECT 1", fail: Exception | None = None) -> None:
        self.reply = reply
        self.fail = fail
        self.requests: list[dict] = []

    def generate_content(self, *, model, contents, config=None):
        self.requests.append({"model": model, "contents": contents, "config": config})
        if self.fail is not None:
            raise self.fail
        return type("Response", (), {"text": self.reply})()


class FakeClient:
    def __init__(self, **kwargs) -> None:
        self.models = FakeModels(**kwargs)


@pytest.fixture
def gemini(monkeypatch):
    """Install a client that has already answered the availability probe."""
    client = FakeClient()
    monkeypatch.setattr(ask, "_CLIENT", client)
    monkeypatch.setattr(ask, "_MODEL_NAME", "gemini-2.5-flash")
    monkeypatch.setattr(ask, "_PROBE_FAILURE", None)
    return client


# --------------------------------------------------------------------------
# What crosses the wire
# --------------------------------------------------------------------------


def test_the_prompt_is_the_question_and_the_schema_and_nothing_else(gemini):
    """Spec section 9.3: no PHI to Gemini.

    Asserted by reconstructing the prompt from its two declared parts. A scan
    for suspicious words would only prove that this particular test data did
    not leak; equality proves there is no third thing in there at all.
    """
    ask.to_sql("  How many cases mention omop?  ", CURRENT)
    sent = gemini.models.requests[0]["contents"]
    expected = (
        f"{ask._system_prompt(CURRENT)}\n\n"
        "Question: How many cases mention omop?\n\nSQL:"
    )
    assert sent == expected


def test_the_schema_brief_carries_column_names_not_values(gemini):
    """It describes the tables. A sample row would be a sample of the corpus."""
    brief = ask._system_prompt(CURRENT)
    assert "body_clean STRING" in brief
    assert "PI_Name__c STRING" in brief
    # The one literal case number in the brief is the format example from the
    # spec, which is also the case number used throughout the public docs.
    assert brief.count("CASE-") == 1


def test_the_archive_brief_does_not_offer_tables_it_does_not_have():
    """Known limitation: `salesforce_marts` has no history or attachments.

    A model told about a table that is not there writes a query that fails on
    a join the user cannot see.
    """
    brief = ask._system_prompt(ARCHIVE)
    assert "case_history" not in brief.replace(
        "(There is no case_history or attachment_blob table in this dataset.)", ""
    )
    assert ARCHIVE.dataset in brief
    assert CURRENT.dataset not in brief


def test_the_current_brief_does_offer_them():
    brief = ask._system_prompt(CURRENT)
    assert "case_history" in brief
    assert "attachment_blob" in brief


def test_generation_is_deterministic_and_toolless(gemini):
    """Same question, same query. And no function-calling loop for a model
    that was given no functions."""
    ask.to_sql("anything", CURRENT)
    cfg = gemini.models.requests[0]["config"]
    assert cfg.temperature == 0
    assert cfg.automatic_function_calling.disable is True


# --------------------------------------------------------------------------
# What comes back
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "```sql\nSELECT 1\n```",
        "```\nSELECT 1\n```",
        "SELECT 1",
        "   SELECT 1   ",
        "```SQL\nSELECT 1\n```",
    ],
)
def test_markdown_fences_are_stripped(gemini, reply):
    """The brief asks for no fences; models add them anyway, and a fence would
    fail the read-only guard as "not a SELECT"."""
    gemini.models.reply = reply
    assert ask.to_sql("q", CURRENT) == "SELECT 1"


def test_an_empty_answer_is_an_error_the_user_can_act_on(gemini):
    gemini.models.reply = ""
    with pytest.raises(RuntimeError, match="rephrasing"):
        ask.to_sql("q", CURRENT)


def test_model_written_sql_still_goes_through_the_read_only_guard(monkeypatch):
    """FR-ASK-4. The model is not a trusted author.

    `run_sql` is the only way the Ask page executes anything, and it refuses
    before it reaches BigQuery — the fake client here would record a call if
    the guard let one through.
    """
    from casefinder import bq, data

    calls: list[str] = []
    monkeypatch.setattr(bq, "get_client", lambda: calls.append("contacted"))
    with pytest.raises(ValueError, match="DELETE"):
        data.run_sql("DELETE FROM `p.d.dim_case` WHERE TRUE")
    assert calls == []


# --------------------------------------------------------------------------
# Availability — FR-ASK-1
# --------------------------------------------------------------------------


def test_a_probe_failure_is_remembered(monkeypatch):
    """`available()` is called on every render of two pages. Re-probing every
    candidate model each time would make Settings take seconds to open."""
    attempts: list[str] = []

    class Failing(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.models.generate_content = self._record

        def _record(self, *, model, contents, config=None):
            attempts.append(model)
            raise RuntimeError("404 model not found")

    monkeypatch.setattr(ask, "_CLIENT", None)
    monkeypatch.setattr(ask, "_MODEL_NAME", None)
    monkeypatch.setattr(ask, "_PROBE_FAILURE", None)
    monkeypatch.setattr(ask, "_generation_config", lambda: None)

    import google.genai

    monkeypatch.setattr(google.genai, "Client", lambda **kwargs: Failing())

    assert ask.available() is False
    first = len(attempts)
    assert first == len(config.VERTEX_MODEL_CANDIDATES)

    assert ask.available() is False
    assert len(attempts) == first, "the second call re-probed the network"


def test_the_unavailable_reason_says_what_to_switch_on(monkeypatch):
    monkeypatch.setattr(ask, "_CLIENT", None)
    monkeypatch.setattr(ask, "_PROBE_FAILURE", None)
    monkeypatch.setattr(ask, "_generation_config", lambda: None)

    import google.genai

    def explode(**kwargs):
        raise RuntimeError("Vertex AI API has not been used in project")

    monkeypatch.setattr(google.genai, "Client", explode)
    reason = ask.why_unavailable()
    assert config.VERTEX_LOCATION in reason
    assert "Vertex AI" in reason


def test_the_model_in_use_is_only_named_once_one_has_answered(gemini):
    assert ask.model_name() == "gemini-2.5-flash"


def test_a_pinned_model_skips_the_search(monkeypatch):
    """`CASEFINDER_VERTEX_MODEL` exists so a site that knows what it has does
    not pay for three failing probes to find out."""
    tried: list[str] = []

    class Recording(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.models.generate_content = self._record

        def _record(self, *, model, contents, config=None):
            tried.append(model)
            return type("Response", (), {"text": "ok"})()

    monkeypatch.setattr(ask, "_CLIENT", None)
    monkeypatch.setattr(ask, "_MODEL_NAME", None)
    monkeypatch.setattr(ask, "_PROBE_FAILURE", None)
    monkeypatch.setattr(ask, "_generation_config", lambda: None)
    monkeypatch.setattr(config, "VERTEX_MODEL", "gemini-9-experimental")

    import google.genai

    monkeypatch.setattr(google.genai, "Client", lambda **kwargs: Recording())

    assert ask.available() is True
    assert tried == ["gemini-9-experimental"]
