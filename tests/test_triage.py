"""Operational lists and saved views — spec FR-LIST-4 through 12, section 9.3.

Two separate concerns share this file because they are two halves of one
feature. `TriageFilters` decides what a list *is*; `SavedView` decides what of
that may be written to disk. The second is the only place in the application
where PHI could come to rest, so it is tested structurally: not "does the
current code avoid writing bodies" but "can a body reach the file at all".
"""

from __future__ import annotations

import json

import pytest
from google.cloud.bigquery import ArrayQueryParameter

from casefinder import config, queries, views
from casefinder.queries import TriageFilters

# --------------------------------------------------------------------------
# Filters — FR-LIST-6
# --------------------------------------------------------------------------


def test_the_default_list_is_a_queue_not_an_archive():
    """`open_only` on by default is the whole premise of the landing page."""
    sql, params = TriageFilters().clauses()
    assert sql == ["NOT c.is_closed"]
    assert params == []


def test_open_only_off_stops_narrowing():
    sql, params = TriageFilters(open_only=False).clauses()
    assert sql == []
    assert params == []


@pytest.mark.parametrize(
    "field,param,column",
    [
        ("statuses", "f_status", "c.status"),
        ("departments", "f_dept", queries.DEPARTMENT),
        ("pis", "f_pi", queries.PI),
        ("irbs", "f_irb", queries.IRB),
        ("funding", "f_funding", queries.FUNDING),
    ],
)
def test_each_filter_binds_an_array(field, param, column):
    filters = TriageFilters(open_only=False, **{field: ["x", "y"]})
    sql, params = filters.clauses()
    assert sql == [f"{column} IN UNNEST(@{param})"]
    assert len(params) == 1
    bound = params[0]
    assert isinstance(bound, ArrayQueryParameter)
    assert bound.name == param
    assert bound.values == ["x", "y"]


def test_an_empty_filter_list_is_not_a_filter():
    """A cleared dropdown must widen the list, not match nothing."""
    sql, params = TriageFilters(open_only=False, statuses=[], pis=[]).clauses()
    assert sql == []
    assert params == []


def test_filters_compose_with_and():
    filters = TriageFilters(statuses=["Open"], departments=["Cardiology"])
    sql, params = filters.clauses()
    assert len(sql) == 3  # open_only + two dimensions
    assert len(params) == 2
    built, _ = queries.triage_list(config.ERAS["current"], filters)
    assert " AND " in built


# --------------------------------------------------------------------------
# The active-filter count — FR-LIST-7
# --------------------------------------------------------------------------


def test_active_count_ignores_open_only():
    """The collapsed chip reads "Filters (2)".

    `Open only` is a default rather than something the user chose, so counting
    it would show "Filters (1)" on a screen where nothing has been narrowed.
    """
    assert TriageFilters().active_count == 0
    assert TriageFilters(open_only=False).active_count == 0
    assert TriageFilters(statuses=["Open"]).active_count == 1
    assert TriageFilters(statuses=["Open"], pis=["Dr X"]).active_count == 2
    assert TriageFilters(statuses=["a", "b", "c"]).active_count == 1  # one dimension


def test_active_count_covers_every_dimension():
    every = TriageFilters(
        statuses=["a"], departments=["b"], pis=["c"], irbs=["d"], funding=["e"]
    )
    assert every.active_count == 5


# --------------------------------------------------------------------------
# Sorting — FR-LIST-5
# --------------------------------------------------------------------------


def test_every_sortable_column_has_a_sort_key():
    """A header the user can click must have somewhere to map to.

    `description` is the exception: it is the truncated free-text column and
    sorting a queue alphabetically by prose is not a thing anyone wants.
    """
    sortable = set(views.ALL_COLUMNS) - {"description"}
    assert sortable <= set(queries.TRIAGE_SORTS)


def test_sort_direction_is_a_flag_not_a_string(era):
    ascending, _ = queries.triage_list(era, TriageFilters(), descending=False)
    descending, _ = queries.triage_list(era, TriageFilters(), descending=True)
    assert "ORDER BY last_activity ASC" in ascending
    assert "ORDER BY last_activity DESC" in descending


def test_nulls_sort_last_in_both_directions(era):
    """An unfilled PI column should not push real rows off the first screen."""
    for descending in (True, False):
        sql, _ = queries.triage_list(era, TriageFilters(), sort="pi", descending=descending)
        assert "NULLS LAST" in sql


# --------------------------------------------------------------------------
# Saved views: round trip
# --------------------------------------------------------------------------


def _round_trip(view: views.SavedView) -> views.SavedView:
    return views.SavedView.from_json(json.loads(json.dumps(view.to_json())))


def test_a_view_survives_a_round_trip():
    original = views.SavedView(
        name="Cardiology backlog",
        description="Open cardiology work",
        filters=TriageFilters(
            open_only=True,
            statuses=["Open", "On Hold"],
            departments=["Cardiology"],
            pis=["Dr X"],
            irbs=["IRB-123"],
            funding=["Funded"],
        ),
        sort="created_at",
        descending=False,
        columns=("case_number", "status", "pi"),
    )
    restored = _round_trip(original)
    assert restored.name == original.name
    assert restored.description == original.description
    assert restored.filters == original.filters
    assert restored.sort == "created_at"
    assert restored.descending is False
    assert restored.columns == ("case_number", "status", "pi")


def test_a_restored_view_still_builds_the_same_query(era):
    original = views.SavedView(
        name="x", filters=TriageFilters(statuses=["Open"], departments=["Cardiology"])
    )
    restored = _round_trip(original)
    before, _ = queries.triage_list(era, original.filters, sort=original.sort)
    after, _ = queries.triage_list(era, restored.filters, sort=restored.sort)
    assert before == after


def test_defaults_are_restored_when_the_file_says_nothing():
    view = views.SavedView.from_json({})
    assert view.name == "Untitled view"
    assert view.filters.open_only is True
    assert view.sort == queries.DEFAULT_TRIAGE_SORT
    assert view.columns == views.DEFAULT_COLUMNS


def test_a_hand_edited_file_cannot_name_a_column_that_no_longer_exists():
    view = views.SavedView.from_json({"columns": ["case_number", "invented_column"]})
    assert view.columns == ("case_number",)
    # All of them invented is treated as "unset" rather than "show nothing".
    assert views.SavedView.from_json({"columns": ["nope"]}).columns == views.DEFAULT_COLUMNS


def test_junk_types_in_a_filter_list_are_dropped_not_crashed():
    view = views.SavedView.from_json(
        {"statuses": ["Open", "", "   ", None, {"a": 1}, ["nested"], 7]}
    )
    assert "Open" in view.filters.statuses
    assert all(isinstance(v, str) and v.strip() for v in view.filters.statuses)


def test_a_filter_that_is_not_a_list_is_ignored():
    view = views.SavedView.from_json({"statuses": "Open"})
    assert view.filters.statuses == []


# --------------------------------------------------------------------------
# Saved views: the no-PHI-at-rest rule — spec section 9.3
# --------------------------------------------------------------------------


def test_only_allowlisted_keys_are_written():
    view = views.SavedView(name="n", description="d", filters=TriageFilters(statuses=["Open"]))
    written = set(view.to_json())
    assert written <= set(views._PERSISTABLE) | {"name", "description"}


def test_a_new_dataclass_field_does_not_reach_the_file():
    """The allowlist is walked, not the object.

    This is the test the module docstring points at: adding a field to
    `SavedView` must not be enough to persist it. Someone has to name it in
    `_PERSISTABLE`, which is a line a reviewer sees.
    """
    view = views.SavedView(name="n")
    view.last_result_rows = [{"description": "subject has ..."}]  # type: ignore[attr-defined]
    view.snippet = "…matched body text…"  # type: ignore[attr-defined]
    payload = json.dumps(view.to_json())
    assert "last_result_rows" not in payload
    assert "snippet" not in payload
    assert "subject has" not in payload


@pytest.mark.parametrize(
    "key", ["rows", "results", "snippets", "bodies", "description_text", "summary"]
)
def test_result_shaped_keys_are_ignored_on_load(key):
    """A file that somehow contains case text does not put it back in memory."""
    view = views.SavedView.from_json({"name": "n", key: ["PHI would live here"]})
    assert "PHI would live here" not in json.dumps(view.to_json())
    assert "PHI would live here" not in view.summary


def test_a_withdrawn_filter_dimension_stops_being_honoured(monkeypatch):
    """Spec section 9.3 requires a way to retire a dimension.

    Dropping it from `_PERSISTABLE_FILTERS` must make existing files stop
    applying it, not merely stop writing new ones.
    """
    monkeypatch.setattr(views, "_PERSISTABLE_FILTERS", ("statuses",))
    view = views.SavedView.from_json({"statuses": ["Open"], "pis": ["Dr X"]})
    assert view.filters.statuses == ["Open"]
    assert view.filters.pis == []


def test_the_written_file_says_what_it_may_not_contain(tmp_path, monkeypatch):
    path = tmp_path / "personal_views.json"
    monkeypatch.setenv("CASEFINDER_PERSONAL_VIEWS_PATH", str(path))
    views.save_personal(views.SavedView(name="mine"))
    payload = json.loads(path.read_text())
    assert "never contain case rows" in payload["_comment"]


# --------------------------------------------------------------------------
# Saved views: files
# --------------------------------------------------------------------------


@pytest.fixture
def personal(tmp_path, monkeypatch):
    path = tmp_path / "personal_views.json"
    monkeypatch.setenv("CASEFINDER_PERSONAL_VIEWS_PATH", str(path))
    return path


def test_save_and_read_back(personal):
    views.save_personal(views.SavedView(name="mine", filters=TriageFilters(pis=["Dr X"])))
    loaded = views.personal_views()
    assert [v.name for v in loaded] == ["mine"]
    assert loaded[0].filters.pis == ["Dr X"]
    assert loaded[0].shared is False


def test_saving_the_same_name_twice_replaces_rather_than_duplicates(personal):
    views.save_personal(views.SavedView(name="mine", filters=TriageFilters(pis=["A"])))
    views.save_personal(views.SavedView(name="mine", filters=TriageFilters(pis=["B"])))
    loaded = views.personal_views()
    assert len(loaded) == 1
    assert loaded[0].filters.pis == ["B"]


def test_delete_reports_whether_it_did_anything(personal):
    views.save_personal(views.SavedView(name="mine"))
    assert views.delete_personal("mine") is True
    assert views.personal_views() == []
    assert views.delete_personal("mine") is False


def test_an_interrupted_save_leaves_no_temp_file_behind(personal):
    views.save_personal(views.SavedView(name="mine"))
    assert list(personal.parent.glob("*.tmp")) == []


def test_a_missing_personal_file_is_not_an_error(personal):
    assert not personal.exists()
    assert views.personal_views() == []


@pytest.mark.parametrize("content", ["", "not json", "[1, 2, 3]", '{"views": "nope"}', "null"])
def test_a_corrupt_shared_file_falls_back_to_the_builtins(content, tmp_path, monkeypatch):
    """A bad views.json must not stop the app from starting."""
    path = tmp_path / "views.json"
    path.write_text(content)
    monkeypatch.setattr(config, "VIEWS_PATH", path)
    assert [v.name for v in views.shared_views()] == [v.name for v in views.builtin_views()]


def test_the_shipped_views_file_parses_and_carries_the_required_presets():
    """FR-LIST-8 names two presets; they ship in the file, not only in code."""
    raw = json.loads(config.VIEWS_PATH.read_text(encoding="utf-8"))
    names = [item["name"] for item in raw["views"]]
    assert "Open Cases (weekly review)" in names
    assert "Data Broker Triage" in names


def test_the_shipped_views_file_carries_definitions_only():
    """Checked against the allowlist rather than against a list of bad words.

    The file's own banner mentions "snippets" and "bodies" — it is telling a
    maintainer what not to paste in — so a substring scan would flag the very
    warning that keeps the file clean. The keys are what matter.
    """
    raw = json.loads(config.VIEWS_PATH.read_text(encoding="utf-8"))
    allowed = set(views._PERSISTABLE) | {"name", "description", "builtin"}
    for item in raw["views"]:
        assert set(item) <= allowed, f"{item.get('name')}: {set(item) - allowed}"


def test_shared_views_are_marked_read_only(tmp_path, monkeypatch):
    path = tmp_path / "views.json"
    path.write_text(json.dumps({"views": [{"name": "team"}]}))
    monkeypatch.setattr(config, "VIEWS_PATH", path)
    assert all(v.shared for v in views.shared_views())


def test_a_builtin_is_added_back_if_the_shared_file_drops_it(tmp_path, monkeypatch):
    """The landing view has to exist even if someone edits it out."""
    path = tmp_path / "views.json"
    path.write_text(json.dumps({"views": [{"name": "only mine"}]}))
    monkeypatch.setattr(config, "VIEWS_PATH", path)
    names = [v.name for v in views.shared_views()]
    assert names[0] == "only mine"
    assert views.OPEN_CASES.name in names


def test_a_shared_file_may_override_a_builtin_by_name(tmp_path, monkeypatch):
    path = tmp_path / "views.json"
    path.write_text(
        json.dumps({"views": [{"name": views.OPEN_CASES.name, "sort": "case_number"}]})
    )
    monkeypatch.setattr(config, "VIEWS_PATH", path)
    found = [v for v in views.shared_views() if v.name == views.OPEN_CASES.name]
    assert len(found) == 1
    assert found[0].sort == "case_number"


def test_shared_views_come_before_personal_ones(personal, tmp_path, monkeypatch):
    path = tmp_path / "views.json"
    path.write_text(json.dumps({"views": [{"name": "team"}]}))
    monkeypatch.setattr(config, "VIEWS_PATH", path)
    views.save_personal(views.SavedView(name="mine"))
    names = [v.name for v in views.all_views()]
    assert names.index("team") < names.index("mine")


def test_find_looks_across_both_tiers(personal):
    views.save_personal(views.SavedView(name="mine"))
    assert views.find("mine") is not None
    assert views.find(views.OPEN_CASES.name) is not None
    assert views.find("no such view") is None


# --------------------------------------------------------------------------
# The presets themselves
# --------------------------------------------------------------------------


def test_the_data_broker_preset_says_it_is_provisional():
    """Spec SR-13. Nothing in the warehouse is named "Data Broker", so the
    preset filters on the nearest real status and admits it on screen."""
    assert "Provisional" in views.DATA_BROKER.description
    assert views.DATA_BROKER.filters.statuses == ["Data Queue"]


def test_every_preset_builds_a_valid_query(era):
    from casefinder.bq import assert_read_only

    for view in views.builtin_views():
        sql, _ = queries.triage_list(
            era, view.filters, sort=view.sort, descending=view.descending
        )
        assert_read_only(sql)


def test_every_preset_sorts_on_an_allowlisted_key():
    for view in views.builtin_views():
        assert view.sort in queries.TRIAGE_SORTS, view.name


def test_the_default_columns_are_the_spec_order():
    """FR-LIST-4 fixes the order; funding is last because it drops first."""
    assert views.DEFAULT_COLUMNS[:3] == ("case_number", "owner", "status")
    assert views.DEFAULT_COLUMNS[-1] == "funding"


def test_a_summary_line_never_leaks_more_than_two_values():
    view = views.SavedView(
        name="n", filters=TriageFilters(pis=["A", "B", "C", "D"])
    )
    assert "PI: A, B +2" in view.summary


def test_share_text_is_the_same_definition_as_the_file():
    view = views.SavedView(name="n", filters=TriageFilters(statuses=["Open"]))
    assert json.loads(view.share_text()) == view.to_json()
