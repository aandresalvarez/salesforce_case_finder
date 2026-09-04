"""The invented people the fixtures are allowed to name.

Every person named anywhere in this repository comes from here. Not because
these particular names matter — they are arbitrary, and any other invented ones
would do — but because having one list makes "where do I get a name?" a
question with an obvious answer. Without it the answer is whatever is on screen
at the time, and what is on screen while you are fixing a rendering bug is a
real requester.

That is not hypothetical. On 4 September 2026 a requester's name and personal
address reached `models.py` and three fixtures, copied out of a case body being
used to diagnose the description column; a support owner's real name had
reached a pushed commit before that. See `tests/corpus_guard.py` for the checks
that came out of it and for the rule those checks enforce.

Addresses use the documentation domains, so the guard can prove they are not
real. The shapes are deliberate rather than uniform, because the corpus is not
uniform: a requester writing from a personal account and a staff member writing
from a university one are different-looking rows, and a fixture that flattens
that difference stops exercising the thing it was written for.
"""

from __future__ import annotations

# A requester writing in from a personal address, which is the common case in
# the corpus and the reason the description column had an address in it at all.
REQUESTER = "Dana Whitfield"
REQUESTER_EMAIL = "dana.whitfield@example.com"

# A researcher writing from a university account.
RESEARCHER = "Priya Raman"
RESEARCHER_EMAIL = "praman@example.edu"

# The support side: a team alias, and two named analysts who own cases. Two,
# because the owner filter takes a list and a list of one proves nothing about
# it. They differ in shape on purpose — a hyphenated surname is longer than the
# fixed-width control that has to show it.
SUPPORT_ALIAS = "RIT Support"
SUPPORT_EMAIL = "support@example.edu"
OWNER = "Alex Rivera"
OWNER_2 = "Kwame Osei-Bonsu"

# A principal investigator, kept obviously generic — it appears in fixtures
# where the value is only ever passed through to a cell.
PI = "Dr Example"


def attribution(who: str, email: str, when: str) -> str:
    """The mail client's quoted-reply header, which `models.preview` strips.

    Built rather than written out at each site so a test that needs one gets
    the real shape — `On <date> <name> (<address>) wrote:` — without another
    opportunity to paste a real one in. The length matters as well as the
    shape: `models._ATTRIBUTION` bounds how much text it will treat as a
    header, and a fixture longer than that bound would silently stop
    exercising the strip.
    """
    return f"On {when} {who} ({email}) wrote:"


def intake_payload(*, narrative: str | None = None) -> str:
    """The web intake form as it arrives inside a case body.

    Two JSON objects joined by `~#~#~`, the second carrying the request itself
    in a `Description` field with escaped newlines. Built here rather than
    written at the call site for the same reason as `attribution`: it is fiddly
    enough to get right that the tempting shortcut is to copy a real one off
    the screen, and a real one is an entire requester — name, personal address,
    telephone number, IRB protocol and study title in a single string.

    The awkward parts are the ones worth keeping, because they are what the
    parser is for: a boolean spelled three different ways by three different
    writers, a field left empty, the same value arriving under two names, and
    a value that is itself a semicolon-delimited list.
    """
    if narrative is None:
        narrative = (
            attribution(REQUESTER, REQUESTER_EMAIL, "Apr 23, 2026 at 4:57 PM")
            + "\\n\\nSummary: Linkage of a tumour registry extract to identified records"
            + "\\n\\nDescription: We maintain a model that predicts clinical outcomes "
            "and would like to evaluate it against registry data."
            + "\\n\\nQuestion: Is this feasible, and what would the approval route be?"
            + "\\n\\nAvailability: \\n\\nRequested For: "
            + REQUESTER
            + "\\nContact E-mail: "
            + REQUESTER_EMAIL
        )
    person = (
        '{"LastName":"Whitfield","FirstName":"Dana","SUNet_ID__c":"dwhitfld",'
        f'"Email":"{REQUESTER_EMAIL}","Phone":"5550143","Department":"Anaesthesia",'
        # The slash arrives JSON-escaped as `\/`, which is legal and which a
        # reader should never see.
        '"suaffiliation__c":"","Rank__c":"Graduate Student \\/ Post-Doc"}'
    )
    request = (
        '{"SUnet_ID_case__c":"dwhitfld","Subject":"Registry linkage",'
        f'"Availability__c":"","Origin":"Web","ContactEmail":"{REQUESTER_EMAIL}",'
        f'"Description":"{narrative}",'
        '"Funding_status__c":"Funded - Grant","I_am_PI_case__c":"false",'
        f'"IRB_Protocol__c":"TBD","PI_Name__c":"{PI}","Project_Record_ID__c":"10001",'
        '"Publication_Plans__c":"Yes","DICOM__c":" false",'
        '"Original_Queue_Name__c":"queuename=Level 1;shortname=Research IT;'
        f'email={SUPPORT_EMAIL}",'
        '"Shared_consult__c":false,"CancerCenter__c":"true"}'
    )
    return f"{person}~#~#~{request}"
