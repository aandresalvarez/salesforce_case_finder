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

# The support side: a team alias, and a named analyst who owns cases.
SUPPORT_ALIAS = "RIT Support"
SUPPORT_EMAIL = "support@example.edu"
OWNER = "Alex Rivera"

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
