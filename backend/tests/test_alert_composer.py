# -*- coding: utf-8 -*-
"""The message a CSP is sent.

Two of Meta's rules are easy to break and expensive to break: a variable may
not open or close the message, and a parameter value may not contain a
newline. Both are checked before a send rather than discovered by a rejected
template, which costs a review cycle and leaves the CSPs unmessaged.
"""

import pytest

from app.services import alert_composer as c

pytestmark = pytest.mark.asyncio(loop_scope="session")

LINK = "https://csp.eko.co.in/csp/details/abc123"


# ---- the three languages -------------------------------------------------

async def test_the_message_carries_all_three_languages():
    message = c.compose("Nitasha", LINK)
    assert "your SBI Kiosk CSP documents" in message          # English
    assert "नमस्ते" in message   # Hindi: Namaste
    assert "aapki details confirm karni hain" in message       # Hinglish


async def test_submit_once_is_said_in_english_and_hindi():
    """The user asked for this specifically, in both languages."""
    message = c.compose("Nitasha", LINK)
    assert "only ONCE" in message
    assert "एक ही बार" in message  # ek hi baar
    assert "EK HI BAAR" in message


async def test_the_name_and_link_both_appear():
    message = c.compose("Nitasha", LINK)
    assert message.count("Nitasha") == 3, "once per language"
    assert message.count(LINK) == 1, "the link is given once, not repeated"


# ---- what Meta would reject ---------------------------------------------

async def test_the_message_never_begins_with_a_variable():
    assert c.compose("Nitasha", LINK).startswith("Namaste ")


async def test_the_message_never_ends_with_a_variable():
    """This is what the signature is for."""
    assert c.compose("Nitasha", LINK).rstrip().endswith(c.SIGNATURE)


async def test_a_newline_in_a_value_is_refused():
    with pytest.raises(ValueError, match="newline"):
        c.check("Namaste X, see below.\n— Team Eko", name="Two\nLines")


async def test_a_message_that_opens_with_its_value_is_refused():
    with pytest.raises(ValueError, match="begins with"):
        c.check("Nitasha, please confirm. — Team Eko", name="Nitasha")


async def test_a_message_that_closes_with_its_value_is_refused():
    with pytest.raises(ValueError, match="ends with"):
        c.check("Namaste, please open " + LINK, link=LINK)


async def test_a_name_with_newlines_is_flattened_not_refused():
    """A sheet cell carries newlines more often than you would expect."""
    message = c.compose("  Abhishek\n Anand  ", LINK)
    assert "Abhishek Anand" in message


async def test_a_csp_with_no_name_is_refused():
    with pytest.raises(ValueError, match="no name"):
        c.compose("", LINK)


async def test_a_message_with_no_link_is_refused():
    """It would ask the CSP to do something with nothing."""
    with pytest.raises(ValueError, match="no link"):
        c.compose("Nitasha", "")


# ---- it must reduce to ONE template -------------------------------------

async def test_two_csps_differ_only_where_they_should():
    """The platform derives one template; anything else varying breaks it."""
    a = c.compose("Nitasha", "https://x/csp/details/aaa")
    b = c.compose("Abhishek Anand", "https://x/csp/details/bbb")
    strip = lambda m, n, l: m.replace(n, "{}").replace(l, "{}")
    assert strip(a, "Nitasha", "https://x/csp/details/aaa") == \
           strip(b, "Abhishek Anand", "https://x/csp/details/bbb")


# ---- phone numbers -------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("9671943504", "919671943504"),
    ("+91 96719 43504", "919671943504"),
    ("09671943504", "919671943504"),
    ("919671943504", "919671943504"),
    ("  9671943504  ", "919671943504"),
])
async def test_the_same_person_normalizes_the_same_way(raw, expected):
    assert c.normalize_mobile(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "12345", "not a number",
                                 "7291988624 / 7291988625"])
async def test_an_implausible_number_is_refused_not_guessed(raw):
    """Sending to a wrong number is worse than not sending."""
    assert c.normalize_mobile(raw) == ""


# ---- building the send list ---------------------------------------------

class _CSP:
    def __init__(self, csp_id, name, mobile):
        self.csp_id, self.name, self.mobile = csp_id, name, mobile


async def test_a_csp_without_a_mobile_is_left_out():
    """They are emailed instead; they must not silently fail at send time."""
    rows = c.contacts_for([
        (_CSP("1A1", "Has Phone", "9671943504"), LINK),
        (_CSP("1A2", "No Phone", ""), LINK),
    ])
    assert [r["csp_code"] for r in rows] == ["1A1"]
    assert rows[0]["phone"] == "919671943504"


async def test_each_row_carries_its_own_message():
    rows = c.contacts_for([
        (_CSP("1A1", "Nitasha", "9671943504"), "https://x/a"),
        (_CSP("1A2", "Abhishek", "9955776279"), "https://x/b"),
    ])
    assert "Nitasha" in rows[0]["message"]
    assert "Abhishek" in rows[1]["message"]
    assert "https://x/a" in rows[0]["message"]
