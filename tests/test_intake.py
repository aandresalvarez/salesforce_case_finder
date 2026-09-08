"""Reading the web intake form out of a case body — `casefinder/intake.py`.

The payload under test is built by `synthetic.intake_payload`, never pasted:
a real one is a whole requester in a single string. What the fixture keeps from
the real shape is the awkwardness — three spellings of a boolean, empty answers,
the same field arriving twice under different names, an escaped slash — because
that awkwardness is the entire reason the parser exists.

Two properties matter more than any particular rendering, and both are about
what happens when the guess is wrong. A body that is not a form has to come out
the other side untouched, because most of them are prose and prose mangled into
field labels is worse than JSON. And the original text has to survive on the
result, because a support person acting on a case has to be able to check the
formatted view against what the record literally says.
"""

from __future__ import annotations

import pytest
import synthetic

from casefinder import intake

# --------------------------------------------------------------------------
# Recognising a form
# --------------------------------------------------------------------------


def test_the_web_form_comes_apart_into_fields():
    form = intake.parse(synthetic.intake_payload())

    assert form is not None
    labels = [field.label for field in form.fields]
    assert "Funding status" in labels
    assert "IRB protocol" in labels
    # The point of the exercise: the reader gets a list of answers, not one
    # seven-hundred-character line.
    assert len(labels) > 10


def test_prose_is_left_alone():
    body = "Hi — could you pull an OMOP cohort for the study we discussed? Thanks."

    assert intake.parse(body) is None


def test_prose_that_happens_to_contain_the_separator_is_left_alone():
    """One unparseable segment condemns the whole body, deliberately.

    Half a form is not a form. Splitting on a separator that appears inside
    ordinary text and then rendering whichever half was valid JSON would
    silently drop the other half — the half a person wrote.
    """
    body = f'Pasting what the system sent: {{"a":"1"}}{intake.SEPARATOR}and it looked wrong.'

    assert intake.parse(body) is None


def test_a_json_object_is_not_a_form_if_it_holds_almost_nothing():
    """Below a few fields, restructuring buys the reader nothing."""
    assert intake.parse('{"Subject":"Extract","Origin":"Web"}') is None
    assert intake.parse('{"Subject":"Extract","Origin":"Web","Status":"New"}') is not None


def test_a_json_array_is_not_a_form():
    assert intake.parse('[{"Subject":"Extract"},{"Origin":"Web"}]') is None


def test_nothing_is_not_a_form():
    assert intake.parse(None) is None
    assert intake.parse("") is None
    assert intake.parse("   ") is None


def test_a_single_object_is_enough():
    """The separator is what the integration happens to emit, not a contract."""
    form = intake.parse('{"Subject":"Extract","Origin":"Web","Status":"New"}')

    assert form is not None
    assert [field.label for field in form.fields] == ["Subject", "Origin", "Status"]


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------


def test_the_three_spellings_of_a_boolean_all_read_as_yes_or_no():
    """`true`, `"true"` and `" false"` are the same answer written by three
    different things, and a reader should not have to know that."""
    form = intake.parse(
        '{"Shared_consult__c":false,"CancerCenter__c":"true",'
        '"DICOM__c":" false","Publication_Plans__c":true}'
    )

    assert form is not None
    assert {field.label: field.value for field in form.fields} == {
        "Shared consult": "No",
        "Cancer center": "Yes",
        "DICOM": "No",
        "Publication plans": "Yes",
    }


def test_an_unanswered_question_does_not_get_a_row():
    form = intake.parse(synthetic.intake_payload())

    assert form is not None
    labels = [field.label for field in form.fields]
    # Both are present in the payload with an empty string for a value.
    assert "Suaffiliation" not in labels
    assert "Availability" not in labels


def test_an_escaped_slash_is_not_shown_to_the_reader():
    form = intake.parse(synthetic.intake_payload())

    assert form is not None
    rank = next(field for field in form.fields if field.label == "Rank")
    assert rank.value == "Graduate Student / Post-Doc"


def test_a_nested_value_does_not_take_the_page_down():
    """Not a shape the form emits — but the page must not be the thing that
    finds that out."""
    form = intake.parse(
        '{"Subject":"Extract","Origin":"Web","Attachments":["a.csv","b.csv"]}'
    )

    assert form is not None
    nested = next(field for field in form.fields if field.label == "Attachments")
    assert nested.value == '["a.csv", "b.csv"]'


def test_a_number_survives_as_a_number():
    form = intake.parse('{"Subject":"Extract","Origin":"Web","Project_Record_ID__c":10001}')

    assert form is not None
    assert {field.label: field.value for field in form.fields}["Project record ID"] == "10001"


def test_the_first_object_wins_when_both_carry_the_same_field():
    """The two objects overlap; the earlier one is the more specific."""
    form = intake.parse(
        f'{{"Email":"{synthetic.REQUESTER_EMAIL}","Origin":"Web","Status":"New"}}'
        f"{intake.SEPARATOR}"
        f'{{"Email":"{synthetic.SUPPORT_EMAIL}","Subject":"Extract"}}'
    )

    assert form is not None
    values = {field.label: field.value for field in form.fields}
    assert values["Email"] == synthetic.REQUESTER_EMAIL


def test_a_long_answer_gets_a_row_to_itself():
    """A grid cell 240px wide renders a sentence one word per line."""
    long_one = "Extract " * 20
    form = intake.parse(
        f'{{"Subject":"Extract","Origin":"Web","Notes__c":"{long_one.strip()}"}}'
    )

    assert form is not None
    by_label = {field.label: field for field in form.fields}
    assert by_label["Notes"].block is True
    assert by_label["Origin"].block is False


# --------------------------------------------------------------------------
# The request itself
# --------------------------------------------------------------------------


def test_the_request_keeps_the_paragraphs_the_requester_typed():
    form = intake.parse(synthetic.intake_payload())

    assert form is not None
    assert "\n\n" in form.narrative
    assert form.narrative.startswith("Summary:")


def test_the_request_is_not_also_a_field():
    form = intake.parse(synthetic.intake_payload())

    assert form is not None
    assert "Description" not in [field.label for field in form.fields]


def test_the_mail_clients_attribution_line_is_not_part_of_the_request():
    header = synthetic.attribution(
        synthetic.REQUESTER, synthetic.REQUESTER_EMAIL, "Apr 23, 2026 at 4:57 PM"
    )
    form = intake.parse(synthetic.intake_payload())

    assert form is not None
    assert header not in form.narrative


def test_windows_line_endings_do_not_reach_the_screen():
    """The narrative renders with whitespace preserved, so a stray `\\r` is a
    glyph on the page rather than nothing."""
    form = intake.parse(
        '{"Subject":"Extract","Origin":"Web","Description":"First line.\\r\\nSecond line."}'
    )

    assert form is not None
    assert "\r" not in form.narrative
    assert form.narrative == "First line.\nSecond line."


def test_a_run_of_blank_lines_collapses_to_one_gap():
    form = intake.parse(
        '{"Subject":"Extract","Origin":"Web","Description":"First.\\n\\n\\n\\n\\nSecond."}'
    )

    assert form is not None
    assert form.narrative == "First.\n\nSecond."


def test_a_request_on_its_own_is_worth_formatting():
    """Two fields plus the narrative clears the bar; the narrative is the part
    that was unreadable."""
    form = intake.parse(
        '{"Subject":"Extract","Origin":"Web","Description":"Line one.\\n\\nLine two."}'
    )

    assert form is not None
    assert form.narrative == "Line one.\n\nLine two."


# --------------------------------------------------------------------------
# Getting back to what the record says
# --------------------------------------------------------------------------


def test_the_original_payload_is_carried_verbatim():
    payload = synthetic.intake_payload()
    form = intake.parse(payload)

    assert form is not None
    assert form.raw == payload


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Funding_status__c", "Funding status"),
        ("IRB_Protocol__c", "IRB protocol"),
        ("Project_Record_ID__c", "Project record ID"),
        ("ContactEmail", "Contact email"),
        ("SUNet_ID__c", "SUNet ID"),
        ("PI_Name__c", "PI name"),
        ("Subject", "Subject"),
        # An acronym the source spelled out is left as it was, rather than
        # being lowercased into a word.
        ("NIH_Grant__c", "NIH grant"),
        # Degenerate, and it still has to answer something a person can read.
        ("__c", "__c"),
    ],
)
def test_a_salesforce_api_name_reads_as_a_label(name, expected):
    assert intake.label_for(name) == expected


# --------------------------------------------------------------------------
# Reconciling the form against the case that already shows half of it
# --------------------------------------------------------------------------


def _form():
    return intake.parse(synthetic.intake_payload())


def _by(form, label):
    return next(f for f in form.fields if f.label == label)


def test_a_value_the_case_already_shows_is_marked_as_an_echo():
    """The case page showed its subject as the title and again in the form, its
    PI in the metadata and again in the form, and so on for nine values on a
    form of twenty-eight. Repetition on that scale stops reading as
    confirmation and becomes noise to skim — which is how the one field that
    disagrees gets skimmed past too."""
    form = intake.reconcile(_form(), {"Subject": "Registry linkage", "PI name": synthetic.PI})

    assert _by(form, "Subject").echoes == "Subject"
    assert _by(form, "PI name").echoes == synthetic.PI or _by(form, "PI name").echoes
    assert not _by(form, "Rank").echoes, "a field the case does not show was dropped"


def test_a_value_that_disagrees_is_flagged_rather_than_hidden():
    """The one part of a form worth interrupting somebody for. A requester who
    wrote `TBD` before the protocol existed leaves a form that disagrees with
    the record, and shown flat and far apart the two read as the page repeating
    itself rather than as a fact that changed."""
    form = intake.reconcile(_form(), {"IRB protocol": "41288"})

    irb = _by(form, "IRB protocol")
    assert irb.value == "TBD"
    assert irb.conflicts == "41288"
    assert not irb.echoes, "a disagreement was folded away as a duplicate"


def test_the_comparison_ignores_case_and_spacing_and_nothing_else():
    """Loose enough to see two spellings of one answer, tight enough to keep a
    disagreement: `41288` and `IRB 41288` are not the same answer."""
    form = intake.reconcile(_form(), {"Funding status": "  funded - GRANT "})
    assert _by(form, "Funding status").echoes

    form = intake.reconcile(_form(), {"IRB protocol": "TBD (pending)"})
    assert _by(form, "IRB protocol").conflicts == "TBD (pending)"


def test_the_form_folds_its_own_repeats():
    """The integration collects some answers from more than one place, so the
    address arrives as `Email` and again as `ContactEmail`, and the SUNet id on
    both objects. Nobody typed them twice."""
    form = _form()

    assert _by(form, "Contact email").echoes == "Email"
    assert _by(form, "SUNet ID case").echoes == "SUNet ID"
    assert not _by(form, "Email").echoes, "the first spelling should win"


def test_a_shared_yes_or_no_is_a_coincidence_not_a_duplicate():
    """`DICOM: No` and `Is the requester the PI: No` are two different
    questions that happen to agree. Folding the second into the first would
    delete an answer rather than a repetition, and nothing on screen would
    admit it."""
    form = _form()

    assert not _by(form, "DICOM").echoes
    assert not _by(form, "I am PI case").echoes


def test_routing_fields_are_moved_out_of_the_way_not_deleted():
    """A queue name is true and is never the reason anybody opened the case."""
    form = _form()

    assert _by(form, "Original queue name").echoes == "the routing record"
    assert _by(form, "Project record ID").echoes == "the routing record"
    # And the payload behind `Original record` is still the whole thing.
    assert "Original_Queue_Name__c" in form.raw


def test_reconciling_never_removes_a_field_from_the_record():
    """Folding is a rendering decision. The parsed form keeps every field, so
    the disclosure that shows the payload verbatim still can."""
    before = _form()
    after = intake.reconcile(before, {"Subject": "Registry linkage"})

    assert len(after.fields) == len(before.fields)
    assert after.raw == before.raw
