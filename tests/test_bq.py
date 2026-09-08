"""Cost guardrails — spec Q-INV-2 and section 8.

The invariant is one line long: every job the app submits carries
`maximum_bytes_billed`. It is worth its own file because the failure mode is
invisible in review and expensive in production — a query with no cap runs to
completion and bills for whatever it scanned, and the app would look like it
was working perfectly the whole time.

Nothing here touches BigQuery. A fake client stands in and records the job
configs it was handed, which is exactly what these tests are about.
"""

from __future__ import annotations

import pytest
from google.cloud.bigquery import ScalarQueryParameter

from casefinder import bq, config, data
from casefinder.bq import CostError, QueryResult

# --------------------------------------------------------------------------
# A fake client that remembers what it was asked to do
# --------------------------------------------------------------------------


class FakeJob:
    def __init__(self, rows, bytes_processed, cache_hit, statement_type="SELECT"):
        self._rows = rows
        self.total_bytes_processed = bytes_processed
        self.cache_hit = cache_hit
        # What BigQuery says it parsed. Real jobs carry this; the preflight
        # guard reads it, so the fake has to have one or every preflight test
        # would be exercising the "client too old to report a type" fallback.
        self.statement_type = statement_type

    def result(self):
        return list(self._rows)


class FakeClient:
    def __init__(self, rows=(), bytes_processed=1024, cache_hit=False, statement_type="SELECT"):
        self.rows = list(rows)
        self.bytes_processed = bytes_processed
        self.cache_hit = cache_hit
        self.statement_type = statement_type
        self.calls: list[tuple[str, object]] = []

    def query(self, sql, job_config=None):
        self.calls.append((sql, job_config))
        return FakeJob(self.rows, self.bytes_processed, self.cache_hit, self.statement_type)

    @property
    def configs(self):
        return [cfg for _sql, cfg in self.calls]


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(bq, "get_client", lambda: fake)
    return fake


# --------------------------------------------------------------------------
# The cap
# --------------------------------------------------------------------------


def test_a_real_job_is_capped():
    cfg = bq._job_config(None)
    assert cfg.maximum_bytes_billed == config.MAX_BYTES_BILLED


def test_a_dry_run_leaves_the_cap_unset():
    """Not "sets it to None" — unset.

    The client serialises an explicit None as the string "None", which BigQuery
    rejects as an invalid INT64, so a dry run configured that way fails with a
    type error rather than estimating anything. A dry run scans nothing and
    needs no cap.
    """
    cfg = bq._job_config(None, dry_run=True)
    assert cfg.dry_run is True
    assert "maximumBytesBilled" not in cfg.to_api_repr()["query"]


def test_the_cap_survives_a_round_trip_to_the_api_shape():
    """Checked on the serialised form, because that is what is sent."""
    api = bq._job_config(None).to_api_repr()["query"]
    assert api["maximumBytesBilled"] == str(config.MAX_BYTES_BILLED)


def test_parameters_are_carried_as_parameters_not_text():
    cfg = bq._job_config([ScalarQueryParameter("t0", "STRING", "omop")])
    api = cfg.to_api_repr()["query"]
    assert api["parameterMode"] == "NAMED"
    assert api["queryParameters"][0]["name"] == "t0"
    assert api["queryParameters"][0]["parameterValue"]["value"] == "omop"


def test_the_query_cache_is_left_on():
    """Re-running the same search inside BigQuery's own window is free."""
    assert bq._job_config(None).use_query_cache is True


def test_every_run_goes_out_capped(client):
    bq.run("SELECT 1")
    bq.run("SELECT 2", [ScalarQueryParameter("x", "INT64", 1)])
    assert client.configs
    for cfg in client.configs:
        assert cfg.maximum_bytes_billed == config.MAX_BYTES_BILLED


def test_the_startup_probe_is_capped_too(monkeypatch):
    """`check_access` builds its own job config rather than going through
    `run`, so it is the one place the cap could quietly be missing."""
    fake = FakeClient()
    monkeypatch.setattr(bq, "get_client", lambda: fake)
    ok, _message = bq.check_access()
    assert ok
    assert fake.configs[0].maximum_bytes_billed == config.MAX_BYTES_BILLED
    assert int(fake.configs[0].job_timeout_ms) == config.QUERY_TIMEOUT_SECONDS * 1000


# --------------------------------------------------------------------------
# The other ceiling: wall clock
# --------------------------------------------------------------------------


def test_a_real_job_carries_a_time_limit_as_well_as_a_byte_limit():
    """Bytes billed measures input scanned and says nothing about runtime.

    `SELECT t.*, c.* FROM turns CROSS JOIN cases` scans 275 MB on this
    warehouse — under the cap, priced by a dry run at a fraction of a cent — and
    then produces eleven billion rows. The byte cap lets it start. Without a
    time limit the desktop window waits for it with no way to cancel.
    """
    cfg = bq._job_config(None)
    # The client round-trips this one through the API representation, so it
    # reads back as a string even though it is set as an int.
    assert int(cfg.job_timeout_ms) == config.QUERY_TIMEOUT_SECONDS * 1000
    # Top level, not under "query": this is a property of the job rather than of
    # the query, unlike the byte cap.
    assert cfg.to_api_repr()["jobTimeoutMs"] == str(config.QUERY_TIMEOUT_SECONDS * 1000)


def test_a_dry_run_gets_no_time_limit():
    """A dry run does not execute, so a ceiling on execution is meaningless —
    and the same "None serialises as the string None" trap applies."""
    assert "jobTimeoutMs" not in bq._job_config(None, dry_run=True).to_api_repr()


def test_a_job_stopped_by_the_ceiling_is_explained_rather_than_reported_raw(monkeypatch):
    """BigQuery reports the expiry as a cancellation.

    Passed through, the user reads "Job was cancelled" and reasonably concludes
    something crashed. What actually happened is that their query was slow, and
    the fix is theirs to make, so the message has to say which of the two
    guardrails stopped them and why the cost one did not.
    """

    class Slow(FakeClient):
        def query(self, sql, job_config=None):
            self.calls.append((sql, job_config))

            class Job:
                def result(self):
                    raise RuntimeError("Job execution was cancelled: Job timed out after 120s")

            return Job()

    monkeypatch.setattr(bq, "get_client", lambda: Slow())
    with pytest.raises(bq.QueryTimeout) as caught:
        bq.run("SELECT 1")
    assert str(config.QUERY_TIMEOUT_SECONDS) in str(caught.value)
    assert "cost guard did not catch it" in str(caught.value)


def test_an_ordinary_failure_is_not_relabelled_as_a_timeout(monkeypatch):
    """The translation matches on message text, which is the only thing that
    distinguishes a ceiling expiry from a user pressing cancel. A rule that
    loose has to be checked in the other direction too."""

    class Broken(FakeClient):
        def query(self, sql, job_config=None):
            class Job:
                def result(self):
                    raise RuntimeError("Syntax error: Unexpected keyword FROM at [1:8]")

            return Job()

    monkeypatch.setattr(bq, "get_client", lambda: Broken())
    with pytest.raises(RuntimeError, match="Syntax error") as caught:
        bq.run("SELECT FROM")
    assert not isinstance(caught.value, bq.QueryTimeout)


def test_the_timeout_message_reaches_the_user_intact():
    """`friendly()` replaces most BigQuery text with one plain sentence, which
    would throw away the only explanation the user gets here."""
    from casefinder.ui.errors import friendly

    message = friendly(bq.QueryTimeout("That query ran for more than 120 seconds"))
    assert "120 seconds" in message


# --------------------------------------------------------------------------
# Preflight — refusing before spending
# --------------------------------------------------------------------------


def _planned(monkeypatch, size, statement_type="SELECT"):
    """Answer the preflight dry run without a round trip."""
    monkeypatch.setattr(bq, "dry_run", lambda *a, **k: bq.DryRun(size, statement_type))


def test_preflight_refuses_a_query_that_is_too_big(client, monkeypatch):
    _planned(monkeypatch, config.MAX_BYTES_BILLED + 1)
    with pytest.raises(CostError, match="safety cap"):
        bq.run("SELECT 1", preflight=True)
    assert client.calls == [], "the query ran anyway"


def test_the_cost_error_says_how_big_and_what_to_do(client, monkeypatch):
    _planned(monkeypatch, 20 * 1024**3)
    with pytest.raises(CostError) as caught:
        bq.run("SELECT 1", preflight=True)
    message = str(caught.value)
    assert "20.0 GB" in message
    assert "Narrow it" in message


def test_preflight_lets_a_query_under_the_cap_through(client, monkeypatch):
    _planned(monkeypatch, 1024)
    bq.run("SELECT 1", preflight=True)
    assert len(client.calls) == 1


def test_the_app_s_own_queries_do_not_pay_for_a_dry_run(client):
    """Preflight is for text the app did not write.

    Every builder-generated query has a known shape and a bound LIMIT, so
    dry-running each one would double the round trips to save nothing.
    """
    bq.run("SELECT 1")
    assert len(client.calls) == 1


# --------------------------------------------------------------------------
# Rows come back plain
# --------------------------------------------------------------------------


def test_rows_are_plain_dicts(monkeypatch):
    """No DataFrame, so nothing depends on pandas extension dtypes for
    TIMESTAMP/NUMERIC — a common Windows install failure."""
    fake = FakeClient(rows=[{"case_number": "CASE-1", "n": 3}])
    monkeypatch.setattr(bq, "get_client", lambda: fake)
    result = bq.run("SELECT 1")
    assert result.rows == [{"case_number": "CASE-1", "n": 3}]
    assert type(result.rows[0]) is dict


def test_a_missing_byte_count_reads_as_zero_not_as_a_crash(monkeypatch):
    fake = FakeClient(bytes_processed=None)
    monkeypatch.setattr(bq, "get_client", lambda: fake)
    assert bq.run("SELECT 1").bytes_processed == 0


# --------------------------------------------------------------------------
# What the user is told it cost
# --------------------------------------------------------------------------


def test_a_cache_hit_is_reported_as_free():
    note = QueryResult(rows=[], bytes_processed=10**9, cache_hit=True).cost_note
    assert "free" in note
    assert "$" not in note


def test_small_queries_do_not_quote_a_price():
    """"$0.00" reads as a number someone should think about. "Under a cent"
    reads as "ignore this", which is the truth for almost every query here."""
    note = QueryResult(rows=[], bytes_processed=250 * 1024**2, cache_hit=False).cost_note
    assert "250 MB" in note
    assert "under a cent" in note


def test_a_query_worth_noticing_quotes_a_price():
    note = QueryResult(rows=[], bytes_processed=4 * 1024**4, cache_hit=False).cost_note
    assert "$" in note
    assert f"{4 * config.USD_PER_TIB:,.2f}" in note


def test_the_price_follows_the_configured_rate():
    result = QueryResult(rows=[], bytes_processed=1024**4, cache_hit=False)
    assert result.usd == pytest.approx(config.USD_PER_TIB)


# --------------------------------------------------------------------------
# The data layer's view of the same thing
# --------------------------------------------------------------------------


def test_free_form_sql_is_preflighted(monkeypatch):
    """FR-SQL-4: a hand-written query is the one most likely to be expensive."""
    seen: list[bool] = []

    def fake_run(sql, params=None, *, preflight=False):
        seen.append(preflight)
        return QueryResult(rows=[], bytes_processed=0, cache_hit=False)

    monkeypatch.setattr(bq, "run", fake_run)
    data.run_sql("SELECT 1")
    assert seen == [True]


def test_free_form_results_are_not_cached(monkeypatch):
    """Pressing Run means run it, and the rows may carry PHI worth not keeping."""
    calls: list[str] = []

    def fake_run(sql, params=None, *, preflight=False):
        calls.append(sql)
        return QueryResult(rows=[], bytes_processed=0, cache_hit=False)

    monkeypatch.setattr(bq, "run", fake_run)
    data.run_sql("SELECT 1")
    data.run_sql("SELECT 1")
    assert len(calls) == 2


def test_prefetch_runs_each_load_exactly_once():
    """It buys latency, not extra queries. A prefetch that double-fetched
    would double the bill for the page it was meant to speed up."""
    calls: list[str] = []
    data.prefetch(lambda: calls.append("a"), lambda: calls.append("b"))
    assert sorted(calls) == ["a", "b"]


def test_prefetch_actually_overlaps():
    """Three one-second loads have to take about one second, not three.

    Timing is normally a bad thing to assert on, but concurrency is the entire
    point of this function — a version that silently ran the loads in sequence
    would pass every other test in this file while doing nothing at all. The
    threshold is loose enough that only a serial implementation trips it.
    """
    import time

    def slow() -> None:
        time.sleep(0.2)

    started = time.monotonic()
    data.prefetch(slow, slow, slow)
    assert time.monotonic() - started < 0.45


def test_prefetch_leaves_a_failure_for_the_page_to_report():
    """The value is requested again through the cached path a moment later,
    and that call is the one attached to the part of the screen that needs
    it. Raising here would blame the wrong panel."""
    reached: list[str] = []

    def explode() -> None:
        raise RuntimeError("403 Access Denied")

    data.prefetch(explode, lambda: reached.append("ran anyway"))
    assert reached == ["ran anyway"]


def test_prefetch_with_nothing_to_do_does_nothing():
    data.prefetch()


def test_a_page_stays_quiet_about_trivial_cost():
    assert data.Page(rows=[], bytes_processed=1024, cache_hit=False).is_trivial_cost
    assert data.Page(rows=[], bytes_processed=10**9, cache_hit=True).is_trivial_cost
    assert not data.Page(rows=[], bytes_processed=200 * 1024**2, cache_hit=False).is_trivial_cost


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------


def test_a_missing_credential_explains_the_fix(monkeypatch):
    """Spec section 12: the error is the instruction."""
    from google.cloud import bigquery

    monkeypatch.setattr(bq, "_CLIENT", None)

    def explode(*args, **kwargs):
        raise RuntimeError("no ADC")

    monkeypatch.setattr(bigquery, "Client", explode)
    with pytest.raises(bq.AuthError, match="gcloud auth application-default login"):
        bq.get_client()


def test_an_identity_is_only_claimed_when_it_is_known(monkeypatch):
    """ADC user credentials carry no email; the quota project sitting in its
    place is not an identity, and printing it would name the wrong account."""

    class NoEmail:
        quota_project_id = "som-rit-phi-starr-dev"

    class WithEmail:
        service_account_email = "loader@example.iam.gserviceaccount.com"

    class Stub:
        def __init__(self, creds):
            self._credentials = creds

    assert bq._whoami(Stub(NoEmail())) == "your signed-in account"
    assert bq._whoami(Stub(None)) == "your signed-in account"
    assert "loader@" in bq._whoami(Stub(WithEmail()))


def test_a_failed_probe_says_which_project_the_grant_is_missing_on(monkeypatch):
    class Broken:
        def query(self, *a, **k):
            raise RuntimeError("Access Denied")

    monkeypatch.setattr(bq, "get_client", Broken)
    ok, message = bq.check_access()
    assert not ok
    assert config.PROJECT in message
    assert "granted BigQuery access" in message


# --------------------------------------------------------------------------
# Network exposure — spec section 9.6, Appendix B "socket/security test"
# --------------------------------------------------------------------------


def test_the_server_binds_to_loopback_and_nothing_else():
    """A PHI corpus on a laptop must not be reachable from the laptop's network.

    NiceGUI's default host is `0.0.0.0`, so this is a property the app has to
    set rather than inherit, and setting it in one place is only useful if
    something checks that place.
    """
    from casefinder import main

    assert main.HOST == "127.0.0.1"
    assert main._free_port() > 0  # the probe binds on the same host it returns


def test_there_is_no_tunnel_switch_to_flip():
    """`ui.run(on_air=...)` proxies the window through a third-party relay.

    The argument is absent from the entry point rather than present and set to
    False, because a False that someone can flip is a switch. Asserting on the
    source is crude, but the alternative — asserting on a keyword that is
    deliberately not there — cannot be written any other way.
    """
    import inspect

    from casefinder import main

    source = inspect.getsource(main.main)
    assert "on_air" not in source
    assert "0.0.0.0" not in inspect.getsource(main)
    assert "reload=False" in source  # a reloader would open a second window and client


# --------------------------------------------------------------------------
# The parser has the last word — finding #01
# --------------------------------------------------------------------------


def test_preflight_refuses_what_bigquery_parsed_as_a_mutation(client, monkeypatch):
    """The keyword scan is a pre-filter; this is the check that decides.

    Text that reads as a SELECT and plans as something else is exactly the case
    a regex cannot catch, so the verdict comes from the dry run instead.
    """
    _planned(monkeypatch, 1024, statement_type="DELETE")
    with pytest.raises(ValueError, match="DELETE statement"):
        bq.run("SELECT 1", preflight=True)
    assert client.calls == [], "the query ran anyway"


def test_a_multi_statement_script_is_refused_by_its_type(client, monkeypatch):
    """BigQuery reports a script as SCRIPT, whatever its first statement is."""
    _planned(monkeypatch, 1024, statement_type="SCRIPT")
    with pytest.raises(ValueError, match="SCRIPT statement"):
        bq.run("SELECT 1", preflight=True)


def test_statement_type_is_checked_before_cost(client, monkeypatch):
    """A mutation is not reported to the user as an expense."""
    _planned(monkeypatch, config.MAX_BYTES_BILLED + 1, statement_type="CREATE_TABLE")
    with pytest.raises(ValueError, match="CREATE TABLE statement"):
        bq.run("SELECT 1", preflight=True)


def test_a_client_that_reports_no_type_falls_back_to_the_keyword_guard(client, monkeypatch):
    """An absent verdict is not a failing one — the syntactic guard already ran."""
    _planned(monkeypatch, 1024, statement_type=None)
    bq.run("SELECT 1", preflight=True)
    assert len(client.calls) == 1


def test_the_cost_estimate_shares_the_read_only_round_trip(client, monkeypatch):
    """`Check cost` must not be a way to plan a mutation without the guard."""
    _planned(monkeypatch, 1024, statement_type="MERGE")
    with pytest.raises(ValueError, match="MERGE statement"):
        data.estimate_sql("SELECT 1")


def test_the_apps_own_queries_are_never_planned(client):
    """Only untrusted text pays for a dry run, and only it is type-checked."""
    bq.run("SELECT 1")
    assert len(client.calls) == 1
    assert client.configs[0].dry_run in (False, None)


def test_no_path_sends_untrusted_text_without_the_parser_verdict(client, monkeypatch):
    """The text scan is best-effort; this is the check that cannot be skipped.

    `assert_read_only` reads SQL without parsing it, and anything short of a
    parser can be argued with — an unclosed block comment, a raw string whose
    backslash rules differ from the reader's. That is why it is a pre-filter.
    Both entry points for text the application did not write are pinned here to
    go through `plan`, which is the only function that asks BigQuery what it
    actually parsed.
    """
    planned: list[str] = []

    def plan(sql, params=None):
        planned.append(sql)
        return bq.DryRun(1024, "SELECT")

    monkeypatch.setattr(bq, "plan", plan)

    data.run_sql("SELECT 1")
    data.estimate_sql("SELECT 2")

    assert planned == ["SELECT 1", "SELECT 2"]
