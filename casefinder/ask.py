"""Optional natural-language mode: a question in, BigQuery SQL out.

This runs on Vertex AI Gemini using the *same* Application Default Credentials
the app already uses for BigQuery. That is the point — it adds a capability
without adding a secret to distribute, an API key to rotate, or a service to
run. If the Vertex AI API is not enabled on the project, the app hides this tab
and everything else keeps working.

The model only ever writes a query. It never sees case data, and the SQL it
produces is dry-run for cost and checked for read-only-ness before anything
executes.

The client is the Google Gen AI SDK (`google-genai`) pointed at Vertex, not
`vertexai.generative_models`. The older SDK still imports, but Google marked it
deprecated with a removal date that has now passed, and it drags in the whole
`google-cloud-aiplatform` stack — storage, resource manager, IAM — to send one
prompt. Known limitation 9 is that Gemini availability changes over time; the
answer to that is to sit on the SDK Google is still maintaining.
"""

from __future__ import annotations

import re

from . import config
from .config import Era

SCHEMA_BRIEF = """
You write BigQuery Standard SQL for a Salesforce support-case warehouse.

Tables (dataset is given below as {dataset}):

`{project}.{dataset}.dim_case` — one row per case
  case_id STRING, case_number STRING (e.g. 'CASE-056576'), subject STRING,
  description STRING, status STRING, origin STRING, origin_class STRING,
  type STRING, reason STRING, priority STRING, is_closed BOOL,
  owner_id STRING, created_at TIMESTAMP, closed_at TIMESTAMP,
  last_modified_at TIMESTAMP, created_year INT64, hours_to_close INT64,
  turn_count INT64, customer_turn_count INT64, agent_turn_count INT64,
  email_count INT64, comment_count INT64, first_turn_at TIMESTAMP,
  last_turn_at TIMESTAMP, has_conversation BOOL

`{project}.{dataset}.fct_conversation_turn` — one row per message in a case
  case_id STRING, turn_seq INT64, turn_ts TIMESTAMP,
  source_object STRING ('EmailMessage'/'CaseComment'),
  direction STRING ('inbound'/'outbound'/'internal' — lowercase),
  actor_role STRING ('customer'/'agent' — lowercase), actor_email STRING,
  actor_name STRING, actor_user_id STRING, subject STRING,
  body_clean STRING, body_clean_len INT64
{extra_tables}
`{project}.salesforce_raw.Case` — the raw Salesforce object, keyed by Id, which
  joins to dim_case.case_id. It carries the fields dim_case does not:
  PI_Name__c STRING, Project_Department__c STRING, IRB_Protocol__c STRING,
  IRB_Status__c STRING, Funding_Status__c STRING. These use the empty string
  rather than NULL for "not recorded", so filter with
  NULLIF(TRIM(col), '') IS NOT NULL.

`{project}.salesforce_raw.User` — Id STRING, Name STRING. Join to resolve
  owner_id or actor_user_id into a person's name.

Rules you must follow:
- Standard SQL only. One SELECT statement. Never write, create, or delete.
- Always end with a LIMIT of 200 or fewer.
- String literals are case-sensitive. The enumerated values above are lowercase
  and must be written lowercase.
- To count cases, aggregate dim_case. To count messages, use
  fct_conversation_turn. Never count cases off the turn table without
  COUNT(DISTINCT case_id) — it has one row per message.
- When joining turns to cases, aggregate the turns to one row per case FIRST,
  otherwise the case repeats once per message.
- For free-text matching use STRPOS(LOWER(col), 'term') > 0, lowercase literal.
- Beware boilerplate: terms like 'redcap' and 'irb' appear in email footers on
  almost every case, so a raw match count for them is meaningless.
- Return ONLY the SQL. No prose, no markdown fences, no explanation.
"""

_EXTRA = """
`{project}.{dataset}.case_history` — audit trail, one row per field change
  case_id STRING, case_number STRING, event_ts TIMESTAMP, field STRING,
  event STRING, old_value STRING, new_value STRING, changed_by STRING

`{project}.{dataset}.attachment_blob` — files on a case
  case_id STRING, case_number STRING, file_name STRING, bytes INT64, mb FLOAT64,
  gcs_uri STRING, console_url STRING
"""


class VertexUnavailable(RuntimeError):
    """Vertex AI is not reachable; the caller should hide the feature."""


_CLIENT = None
_MODEL_NAME: str | None = None
_PROBE_FAILURE: str | None = None

_PROBE = "Reply with the single word: ok"


def _generation_config():
    """Deterministic output, and no function-calling loop.

    Temperature 0 because the same question should produce the same query —
    a user who reruns Ask and gets different SQL cannot tell whether the
    warehouse changed or the model did.

    Automatic function calling is switched off because the model is given no
    tools. Left on, the SDK arms a call loop that can never fire and logs a
    warning about it on every request.
    """
    from google.genai import types

    return types.GenerateContentConfig(
        temperature=0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def _model():
    """Return a client and a model name that have actually answered a request.

    Constructing a client does no network I/O, so it succeeds for a project
    that cannot use Gemini at all — the 403 or 404 only arrives on the first
    generation. Checking availability without a real call would put an Ask tab
    in front of the user that fails the moment they use it, so each candidate
    is probed with a two-token prompt and the first that answers is kept.

    The failure is cached as well as the success. Without that, a page that
    asks `available()` on every render re-probes every candidate model over the
    network each time the user visits Settings.
    """
    global _CLIENT, _MODEL_NAME, _PROBE_FAILURE
    if _CLIENT is not None:
        return _CLIENT, _MODEL_NAME
    if _PROBE_FAILURE is not None:
        raise VertexUnavailable(_PROBE_FAILURE)

    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        _PROBE_FAILURE = (
            "The natural-language extra is not installed. Install it with:\n"
            "    uv sync --extra ask"
        )
        raise VertexUnavailable(_PROBE_FAILURE) from exc

    try:
        client = genai.Client(
            vertexai=True,
            project=config.BILLING_PROJECT,
            location=config.VERTEX_LOCATION,
        )
    except Exception as exc:
        _PROBE_FAILURE = f"Could not reach Vertex AI in {config.VERTEX_LOCATION}: {exc}"
        raise VertexUnavailable(_PROBE_FAILURE) from exc

    candidates = (
        [config.VERTEX_MODEL] if config.VERTEX_MODEL else config.VERTEX_MODEL_CANDIDATES
    )
    errors: list[str] = []
    for name in candidates:
        try:
            client.models.generate_content(
                model=name, contents=_PROBE, config=_generation_config()
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {type(exc).__name__}")
            continue
        _CLIENT, _MODEL_NAME = client, name
        return _CLIENT, _MODEL_NAME

    _PROBE_FAILURE = (
        f"No Gemini model is available to this project in "
        f"{config.VERTEX_LOCATION}. Tried: {', '.join(errors)}.\n"
        "Enable the Vertex AI API, or set CASEFINDER_VERTEX_MODEL to a model "
        "you do have access to."
    )
    raise VertexUnavailable(_PROBE_FAILURE)


def reset() -> None:
    """Forget the probe result, whichever way it went.

    The failure is cached for the life of the process so that a page asking
    `available()` on every render does not re-probe four models over the
    network each time. That is right as a cache and wrong as a verdict: a
    project whose Vertex API was switched on a minute ago, or a laptop whose
    network has come back, would otherwise need the application restarted
    before Ask reappeared. `data.reset_connection` calls this, so Retry on the
    connection screen and "Clear cached results" in Settings both mean it.
    """
    global _CLIENT, _MODEL_NAME, _PROBE_FAILURE
    _CLIENT = None
    _MODEL_NAME = None
    _PROBE_FAILURE = None


def model_name() -> str | None:
    """The model actually in use, once one has answered."""
    return _MODEL_NAME


def available() -> bool:
    try:
        _model()
        return True
    except Exception:  # noqa: BLE001
        return False


def why_unavailable() -> str:
    """The reason the Ask tab is switched off, for showing to the user."""
    try:
        _model()
        return ""
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def _system_prompt(era: Era) -> str:
    extra = (
        _EXTRA.format(project=config.PROJECT, dataset=era.dataset)
        if era.has_history
        else "\n(There is no case_history or attachment_blob table in this dataset.)\n"
    )
    return SCHEMA_BRIEF.format(
        project=config.PROJECT, dataset=era.dataset, extra_tables=extra
    )


_FENCE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def to_sql(question: str, era: Era) -> str:
    """Translate a plain-English question into a single SELECT statement.

    What crosses the wire is the question and the table schema. No case row,
    no message body, and no search result is ever part of a prompt — see the
    PHI table in spec section 9.3.
    """
    client, name = _model()
    prompt = f"{_system_prompt(era)}\n\nQuestion: {question.strip()}\n\nSQL:"
    response = client.models.generate_content(
        model=name, contents=prompt, config=_generation_config()
    )
    sql = _FENCE.sub("", (response.text or "").strip()).strip()
    if not sql:
        raise RuntimeError("The model returned an empty query. Try rephrasing.")
    return sql
