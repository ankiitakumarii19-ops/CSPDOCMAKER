"""
CSP DocMaker — each person's own look (No. 240, SaaS upgrade Stage 2)

What a person may change on Settings -> Appearance, and the checks a choice
must pass before it is saved. Pure functions: no database, no request.

Order on the screen (frontend lib/myLook.ts): the app's built-in look ->
the workspace's Display choice (Setup -> Display, No. 228-229) -> what the
person chose here. A choice left out = "as the workspace has it".

Only the look changes. Nothing here is read by any rule, job or message.

Readability (brief: "customisation must not compromise readability"):
  * background / card colours are used in light mode under the app's normal
    dark text, so they must keep a 4.5 : 1 contrast with it (WCAG AA);
  * the side-menu colour sits under light-grey menu text: 4.5 : 1 with it;
  * accent / button colours carry white text: refused under 2.4 : 1 (Eko's
    own green is 2.6 : 1, so the brand stays allowed) and a warning is
    returned under 4.5 : 1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# The text colours the checks compare against (Tailwind's, as the app uses).
BODY_TEXT = "#1f2937"      # text-gray-800, the normal text in light mode
MENU_TEXT = "#d1d5db"      # text-gray-300, the side menu's text
BUTTON_TEXT = "#ffffff"    # text-white on bg-eko buttons

NEEDED = 4.5               # WCAG AA for normal text
BUTTON_FLOOR = 2.4         # below this a coloured button is refused

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Choice:
    key: str
    label: str
    group: str
    kind: str                       # "pick" | "number" | "switch" | "colour"
    values: tuple = ()              # pick: allowed values
    low: int = 0                    # number: smallest
    high: int = 0                   # number: largest
    step: int = 1
    unit: str = ""
    help: str = ""
    names: dict = field(default_factory=dict)  # pick: value -> words

    def public(self) -> dict:
        out = {"key": self.key, "label": self.label, "group": self.group,
               "kind": self.kind, "help": self.help}
        if self.kind == "pick":
            out["values"] = [{"value": v, "name": self.names.get(v, v)}
                             for v in self.values]
        if self.kind == "number":
            out.update(low=self.low, high=self.high, step=self.step,
                       unit=self.unit)
        return out


FONTS = {
    "inter": "Inter", "roboto": "Roboto", "poppins": "Poppins",
    "open_sans": "Open Sans", "lato": "Lato", "system": "This device's font",
}

CHOICES: tuple[Choice, ...] = (
    # ---- Appearance ----
    Choice("mode", "Light or dark", "appearance", "pick",
           ("light", "dark", "system"),
           names={"light": "Light", "dark": "Dark",
                  "system": "Follow this device"},
           help="The moon / sun button in the header changes this too."),
    Choice("background", "Page background", "appearance", "colour",
           help="Used in light mode. Must stay easy to read with the normal text."),
    Choice("menu", "Side menu", "appearance", "colour",
           help="The menu on the left of the Admin pages."),
    Choice("accent", "Accent", "appearance", "colour",
           help="Highlights, links, the chosen tab, progress bars."),
    Choice("button", "Buttons", "appearance", "colour",
           help="The main buttons (Save, Send …)."),
    Choice("card", "Cards", "appearance", "colour",
           help="The white boxes the screens are made of. Light mode."),
    Choice("border", "Borders", "appearance", "colour",
           help="Lines around cards and tables. Light mode."),
    # ---- Typography ----
    Choice("font", "Font", "typography", "pick", tuple(FONTS), names=FONTS),
    Choice("text_size", "Text size", "typography", "number",
           low=85, high=130, step=5, unit="%"),
    Choice("heading_size", "Heading size", "typography", "number",
           low=85, high=140, step=5, unit="%"),
    Choice("weight", "Text weight", "typography", "pick",
           ("light", "normal", "medium"),
           names={"light": "Light", "normal": "Normal", "medium": "Bolder"}),
    Choice("line_spacing", "Line spacing", "typography", "pick",
           ("tight", "normal", "relaxed", "loose"),
           names={"tight": "Tight", "normal": "Normal",
                  "relaxed": "Relaxed", "loose": "Loose"}),
    # ---- Layout ----
    Choice("menu_state", "Side menu", "layout", "pick",
           ("expanded", "collapsed"),
           names={"expanded": "Open (icons and names)",
                  "collapsed": "Narrow (icons only)"},
           help="Admin pages on a laptop or larger screen."),
    Choice("menu_side", "Side menu position", "layout", "pick",
           ("left", "right"), names={"left": "Left", "right": "Right"},
           help="Admin pages on a laptop or larger screen."),
    Choice("density", "Spacing", "layout", "pick",
           ("compact", "comfortable", "spacious"),
           names={"compact": "Compact", "comfortable": "Comfortable",
                  "spacious": "Spacious"}),
    Choice("cards", "Card corners", "layout", "pick",
           ("rounded", "square"), names={"rounded": "Rounded",
                                         "square": "Square"}),
    Choice("table_density", "Table rows", "layout", "pick",
           ("compact", "normal", "spacious"),
           names={"compact": "Compact", "normal": "Normal",
                  "spacious": "Spacious"}),
    # ---- Accessibility ----
    Choice("high_contrast", "High contrast", "accessibility", "switch",
           help="Darker grey text and stronger lines."),
    Choice("motion", "Movement", "accessibility", "pick",
           ("standard", "reduce", "device"),
           names={"standard": "Normal", "reduce": "Less movement",
                  "device": "Follow this device"},
           help="Turns off sliding and fading."),
    Choice("scale", "Size of everything", "accessibility", "number",
           low=90, high=150, step=10, unit="%",
           help="Makes the whole screen bigger or smaller, like zoom."),
    Choice("focus_outline", "Clear keyboard outline", "accessibility", "switch",
           help="A thick outline on whatever the Tab key is on."),
)

BY_KEY = {c.key: c for c in CHOICES}

# What a workspace may keep its own (Settings -> "People may pick their own
# colours", No. 240 Stage 3). Light / dark, sizes, layout and accessibility
# always stay the person's.
WORKSPACE_LOCKABLE = ("background", "menu", "accent", "button", "card",
                      "border", "font")


def options() -> list[dict]:
    """What the Appearance page offers, in order."""
    return [c.public() for c in CHOICES]


# ---- contrast (WCAG 2.1) ------------------------------------------------

def _luminance(hex_colour: str) -> float:
    n = int(hex_colour[1:], 16)
    parts = []
    for c in ((n >> 16) & 255, (n >> 8) & 255, n & 255):
        s = c / 255
        parts.append(s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4)
    r, g, b = parts
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


# ---- checking a whole set of choices -------------------------------------

class LookError(ValueError):
    """A choice that cannot be saved; the message says which and why."""


def check(raw: Any) -> tuple[dict, list[str]]:
    """The choices to save and any warnings. Unknown keys, wrong values and
    unreadable colours are refused (LookError) — nothing is half-saved.
    A value of None means 'as the workspace has it' and is dropped."""
    if not isinstance(raw, dict):
        raise LookError("The appearance must be a set of choices.")
    clean: dict = {}
    warnings: list[str] = []
    for key, value in raw.items():
        choice = BY_KEY.get(key)
        if choice is None:
            raise LookError(f"'{key}' is not something you can change here.")
        if value is None:
            continue
        if choice.kind == "pick":
            if value not in choice.values:
                raise LookError(f"{choice.label}: '{value}' is not one of the choices.")
            clean[key] = value
        elif choice.kind == "switch":
            if not isinstance(value, bool):
                raise LookError(f"{choice.label}: must be on or off.")
            clean[key] = value
        elif choice.kind == "number":
            if isinstance(value, bool) or not isinstance(value, int):
                raise LookError(f"{choice.label}: must be a whole number.")
            if not choice.low <= value <= choice.high:
                raise LookError(f"{choice.label}: must be between {choice.low}"
                                f"{choice.unit} and {choice.high}{choice.unit}.")
            if (value - choice.low) % choice.step:
                raise LookError(f"{choice.label}: goes in steps of {choice.step}.")
            clean[key] = value
        elif choice.kind == "colour":
            if not isinstance(value, str) or not HEX.match(value):
                raise LookError(f"{choice.label}: must be a colour like #1e293b.")
            colour = value.lower()
            warning = _colour_problem(choice, colour)
            if warning and warning.startswith("refuse:"):
                raise LookError(warning[len("refuse:"):])
            if warning:
                warnings.append(warning)
            clean[key] = colour
    return clean, warnings


def _colour_problem(choice: Choice, colour: str) -> str | None:
    if choice.key in ("background", "card"):
        ratio = contrast(colour, BODY_TEXT)
        if ratio < NEEDED:
            return (f"refuse:{choice.label}: {colour} is too dark for the normal "
                    f"text (contrast {ratio} : 1, needs {NEEDED}). Pick a "
                    f"lighter colour, or use dark mode.")
    elif choice.key == "menu":
        ratio = contrast(colour, MENU_TEXT)
        if ratio < NEEDED:
            return (f"refuse:{choice.label}: {colour} is too light for the "
                    f"menu's light text (contrast {ratio} : 1, needs {NEEDED}). "
                    f"Pick a darker colour.")
    elif choice.key in ("accent", "button"):
        ratio = contrast(colour, BUTTON_TEXT)
        if ratio < BUTTON_FLOOR:
            return (f"refuse:{choice.label}: {colour} is too light for white "
                    f"button text (contrast {ratio} : 1). Pick a darker colour.")
        if ratio < NEEDED:
            return (f"{choice.label}: white text on {colour} is harder to read "
                    f"(contrast {ratio} : 1); a darker shade reads better.")
    return None
