"""The read-only guard — spec FR-SQL-3 and section 9.4.

This is the only thing standing between "an analyst pasted something" and a
write against the warehouse, because the ADC the app runs under is a person's
own credential and very likely *can* write. So the guard is tested against the
ways a mutation can hide rather than only against the obvious `DELETE FROM`.
"""

from __future__ import annotations

import pytest

from casefinder.bq import assert_read_only

ALLOWED = [
    "SELECT 1",
    "select case_number from t limit 10",
    "  SELECT 1  ",
    "SELECT 1;",
    "SELECT 1 ;  ",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "-- a leading comment\nSELECT 1",
    "/* block */ SELECT 1",
    # 'created_at' contains 'create' but is not the CREATE keyword.
    "SELECT created_at, created_year FROM t",
    # So does a column literally named after one.
    "SELECT is_deleted FROM t",
]

REFUSED = [
    "",
    "   ",
    "-- only a comment",
    "DELETE FROM dim_case",
    "delete from dim_case",
    "DROP TABLE dim_case",
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET x = 1",
    "MERGE INTO t USING s ON TRUE WHEN MATCHED THEN DELETE",
    "TRUNCATE TABLE t",
    "ALTER TABLE t ADD COLUMN x INT64",
    "CREATE TABLE t AS SELECT 1",
    "CREATE OR REPLACE VIEW v AS SELECT 1",
    "GRANT SELECT ON t TO 'x'",
    "CALL some_procedure()",
    "BEGIN SELECT 1; END",
    "EXPORT DATA OPTIONS(uri='gs://x') AS SELECT 1",
    # Two statements, the second of which is the point.
    "SELECT 1; DROP TABLE dim_case",
    "SELECT 1; DELETE FROM dim_case;",
    # Not a statement at all.
    "EXPLAIN SELECT 1",
    "SHOW TABLES",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_reads_are_allowed(sql):
    assert_read_only(sql)


@pytest.mark.parametrize("sql", REFUSED)
def test_writes_are_refused(sql):
    with pytest.raises(ValueError):
        assert_read_only(sql)


def test_keywords_hidden_in_comments_do_not_smuggle_a_write():
    """Comments are stripped *before* the check, not after.

    Checking first would let `SELECT 1 -- DELETE` trip the guard on a harmless
    query; stripping first and checking after is what makes the guard both
    accurate and not fooled by `/* SELECT */ DROP TABLE t`.
    """
    assert_read_only("SELECT 1 -- DELETE FROM t")
    assert_read_only("SELECT 1 /* DROP TABLE t */")
    with pytest.raises(ValueError):
        assert_read_only("/* SELECT 1 */ DROP TABLE t")
    with pytest.raises(ValueError):
        assert_read_only("-- SELECT\nDELETE FROM t")


def test_the_error_says_what_was_wrong():
    """Spec section 12: the message is for a person, not a log.

    A mutation is named, wherever in the statement it appears. "Only SELECT is
    allowed" is the fallback for text that is not a mutation and not a read
    either, where there is no keyword to point at.
    """
    with pytest.raises(ValueError, match="'DELETE' is not allowed"):
        assert_read_only("DELETE FROM t")
    with pytest.raises(ValueError, match="'DELETE' is not allowed"):
        assert_read_only("WITH x AS (DELETE FROM t RETURNING 1) SELECT * FROM x")
    with pytest.raises(ValueError, match="'DROP' is not allowed"):
        assert_read_only("/* SELECT 1 */ DROP TABLE t")
    with pytest.raises(ValueError, match="one statement"):
        assert_read_only("SELECT 1; SELECT 2")
    with pytest.raises(ValueError, match="Only SELECT"):
        assert_read_only("EXPLAIN SELECT 1")
    with pytest.raises(ValueError, match="Only SELECT"):
        assert_read_only("SHOW TABLES")
    with pytest.raises(ValueError, match="Empty query"):
        assert_read_only("-- only a comment")


def test_reordering_the_guard_did_not_widen_it():
    """The keyword check moved ahead of the shape check to get a better
    message. The set of refused queries has to be the same either way, so both
    rules are re-run here in the opposite order against the same corpus."""
    import re

    from casefinder.bq import _FORBIDDEN, _strip_sql_comments

    def refused_the_old_way(sql: str) -> bool:
        stripped = _strip_sql_comments(sql).strip().rstrip(";").strip()
        if not stripped or ";" in stripped:
            return True
        if not re.match(r"^(SELECT|WITH)\b", stripped, re.IGNORECASE):
            return True
        return bool(_FORBIDDEN.search(stripped))

    def refused_now(sql: str) -> bool:
        try:
            assert_read_only(sql)
        except ValueError:
            return True
        return False

    for sql in ALLOWED + REFUSED:
        assert refused_now(sql) == refused_the_old_way(sql), sql


def test_data_layer_guards_before_it_estimates(monkeypatch):
    """`run_sql` must refuse without touching BigQuery at all.

    A dry run of a DELETE is still a round trip to a warehouse with a writable
    credential attached, so the guard has to come first.
    """
    from casefinder import bq, data

    def explode(*args, **kwargs):
        raise AssertionError("BigQuery was contacted for a rejected query")

    monkeypatch.setattr(bq, "get_client", explode)
    monkeypatch.setattr(bq, "estimate_bytes", explode)

    with pytest.raises(ValueError):
        data.run_sql("DELETE FROM dim_case")
    with pytest.raises(ValueError):
        data.estimate_sql("DROP TABLE dim_case")
