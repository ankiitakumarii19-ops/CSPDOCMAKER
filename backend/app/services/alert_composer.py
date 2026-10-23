# -*- coding: utf-8 -*-
"""
CSP DocMaker — the message a CSP is sent

One message, three languages: English, Hindi and Hinglish. A CSP reads
whichever they are comfortable with, and nobody has to decide in advance
which that is.

Two rules Meta enforces on template messages shape the wording, and both are
checked here rather than discovered when a send is rejected:

  * A variable may not be the first or last thing in the message. There has
    to be real text before the first and after the last — which is why every
    message opens with "Namaste" and closes with a fixed signature.

  * A variable's value may not contain a newline. The link and the name are
    single-line by construction, but a value arriving from a sheet cell is
    not trustworthy, so it is flattened.

The platform derives the template from these finished messages, so every CSP's
message must differ ONLY in the parts that genuinely vary — the name and the
link. Any other variation and the derivation fails.
"""

import logging
import re

logger = logging.getLogger(__name__)

# What the platform is told the message is: an account update tied to
# something the CSP already signed up for, not a promotion.
CATEGORY = "UTILITY"
LANGUAGE = "en_US"

# Fixed text that closes every message. Its job is twofold: it signs the
# message, and it satisfies Meta's rule that a variable cannot be last.
SIGNATURE = "— Team Eko"

_TEMPLATE = """\
Namaste {name}, your SBI Kiosk CSP documents need your details confirmed. \
Please open this link, check what is already filled, correct anything wrong, \
and submit. You can submit only ONCE, so please check carefully before you \
send.

{link}

नमस्ते {name}, आपके SBI Kiosk CSP दस्तावेज़ों के लिए आपकी जानकारी की पुष्टि \
आवश्यक है। कृपया ऊपर दिए गए लिंक पर जाकर पहले से भरी जानकारी देखें, कुछ गलत हो \
तो सुधारें और जमा करें। आप केवल एक ही बार जमा कर सकते हैं, इसलिए भेजने से पहले \
ध्यान से जांच लें।

Namaste {name}, aapke SBI Kiosk CSP documents ke liye aapki details confirm \
karni hain. Upar diye gaye link par jaakar pehle se bhari hui details dekhein, \
kuch galat ho to sudhaarein aur submit karein. Aap sirf EK HI BAAR submit kar \
sakte hain, isliye bhejne se pehle dhyaan se jaanch lein.

{signature}"""


def flatten(value: str) -> str:
    """One line, collapsed whitespace.

    Meta rejects a send whose parameter value contains a newline, and sheet
    cells carry them more often than you would expect.
    """
    return " ".join((value or "").split())


def compose(name: str, link: str) -> str:
    """The finished message for one CSP."""
    name = flatten(name)
    link = flatten(link)
    if not name:
        raise ValueError("Cannot address a message to a CSP with no name.")
    if not link:
        raise ValueError("A message with no link asks the CSP to do nothing.")

    message = _TEMPLATE.format(name=name, link=link, signature=SIGNATURE)
    check(message, name=name, link=link)
    return message


def check(message: str, **values: str) -> None:
    """Refuse a message Meta would reject, before it is ever sent.

    Raising here costs nothing. A rejected template costs a review cycle and
    leaves the CSPs unmessaged in the meantime.
    """
    if not message.strip():
        raise ValueError("Empty message.")

    for key, value in values.items():
        if "\n" in (value or "") or "\r" in (value or ""):
            raise ValueError(
                f"{key!r} contains a newline; Meta rejects the send with a "
                f"parameter-format error. Pass it through flatten() first."
            )
        if not str(value).strip():
            continue
        # A value sitting at the very start or very end makes it the
        # template's first or last element once the platform derives one.
        if message.strip().startswith(str(value)):
            raise ValueError(
                f"The message begins with {key!r}. Meta requires fixed text "
                f"before the first variable."
            )
        if message.strip().endswith(str(value)):
            raise ValueError(
                f"The message ends with {key!r}. Meta requires fixed text "
                f"after the last variable — that is what {SIGNATURE!r} is for."
            )


def contacts_for(records) -> list:
    """Rows ready for the sender: one dict per CSP.

    Only CSPs reachable on WhatsApp appear here. One without a mobile is left
    out rather than silently dropped later — the caller emails them instead.
    """
    rows = []
    for record, link in records:
        mobile = normalize_mobile(getattr(record, "mobile", ""))
        if not mobile:
            continue
        rows.append({
            "phone": mobile,
            "name": flatten(getattr(record, "name", "")),
            "csp_code": getattr(record, "csp_id", ""),
            "message": compose(getattr(record, "name", ""), link),
        })
    return rows


_DIGITS = re.compile(r"\D+")
# Between two numbers in one cell: / \ , ; or "or".
_SEPARATORS = re.compile(r"\s*(?:[/\\,;]|\bor\b)\s*", re.IGNORECASE)
INDIA_CC = "91"


def normalize_mobile(value: str) -> str:
    """A WhatsApp number: digits only, with the country code.

    Sheet cells carry '+91 98123 45670', '09812345670' and '9812345670' for
    the same person. Anything that is not a plausible Indian mobile returns
    empty rather than being sent to a wrong number.

    A cell with two numbers ("9905985993/ 7563993807", No. 144) gives the
    first one that is plausible.
    """
    parts = _SEPARATORS.split(value or "")
    if len(parts) > 1:
        for part in parts:
            number = normalize_mobile(part)
            if number:
                return number
        return ""
    digits = _DIGITS.sub("", value or "")
    if len(digits) == 10:
        return INDIA_CC + digits
    if len(digits) == 11 and digits.startswith("0"):
        return INDIA_CC + digits[1:]
    if len(digits) == 12 and digits.startswith(INDIA_CC):
        return digits
    return ""
