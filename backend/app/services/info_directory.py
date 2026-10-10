"""
CSP DocMaker — INFO directory (CSPDATA ▸ INFO tab)

Who covers what. The INFO tab lists Relationship Managers, ASMs, Circle Heads
and District Coordinators with the LHOs, States and Districts each one looks
after. When a CSP row leaves one of those people blank, the value is looked up
here instead of being asked for.

The tab is four blocks stacked in one sheet, separated by blank rows, each
starting with its own header row:

    Relationship Manager Name | Email ID | Mobile Number | LHO | State
    ASM Name                  | ...
    Circle Head Name          | ...
    District Coordinator Name | ... | Districts Covered

LHO, State and Districts hold comma-separated lists, so one person can cover
several of each.

A lookup only answers when exactly one person matches. Two ASMs share the
Chandigarh LHO (one for Haryana, one for Punjab), so an LHO alone is not
always enough; where a match is ambiguous this returns nothing and the field
stays missing data for the RM to fill, rather than guessing.

This directory says who covers a territory. It does NOT say who may log in —
that remains the authorization sheet's job alone.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

RM = "rm"
ASM = "asm"
CIRCLE_HEAD = "circle_head"
DC = "dc"

# First cell of a block's header row → the role that block describes.
BLOCK_HEADERS: Dict[str, str] = {
    "relationship manager name": RM,
    "asm name": ASM,
    "circle head name": CIRCLE_HEAD,
    "district coordinator name": DC,
}

# Header text → the attribute it fills. The first column is always the name.
COLUMN_ALIASES: Dict[str, str] = {
    "email id": "email",
    "email": "email",
    "mobile number": "mobile",
    "contact number": "mobile",
    "lho": "lhos",
    "state": "states",
    "states": "states",
    "districts covered": "districts",
    "district": "districts",
}

MULTI_VALUE_ATTRS = ("lhos", "states", "districts")


def normalize(value: str) -> str:
    """Case- and space-insensitive form used for every comparison."""
    return " ".join((value or "").split()).strip().lower()


def split_list(value: str) -> List[str]:
    """'Bihar, Jharkhand' → ['bihar', 'jharkhand']."""
    return [normalize(part) for part in (value or "").split(",") if normalize(part)]


def split_raw(value: str) -> List[str]:
    """Same split, keeping the sheet's own capitalisation."""
    return [" ".join(part.split()) for part in (value or "").split(",")
            if part.strip()]


@dataclass
class Person:
    role: str
    name: str
    email: str = ""
    mobile: str = ""
    lhos: List[str] = field(default_factory=list)
    states: List[str] = field(default_factory=list)
    districts: List[str] = field(default_factory=list)
    # The sheet's own spelling of the multi-value columns. lhos/states are
    # lowercased for comparison, which is the wrong thing to copy into a CSP
    # record: "NCT of Delhi" must not come back as "nct of delhi".
    lhos_raw: List[str] = field(default_factory=list)
    states_raw: List[str] = field(default_factory=list)

    def sole_lho(self) -> str:
        """This person's LHO when they have exactly one, else ''.

        A DC covering two LHOs cannot say which one a district belongs to,
        so it answers nothing rather than picking the first.
        """
        return self.lhos_raw[0] if len(self.lhos_raw) == 1 else ""

    def sole_state(self) -> str:
        return self.states_raw[0] if len(self.states_raw) == 1 else ""

    def covers_lho(self, lho: str) -> bool:
        return normalize(lho) in self.lhos

    def covers_state(self, state: str) -> bool:
        return normalize(state) in self.states

    def covers_district(self, district: str) -> bool:
        return normalize(district) in self.districts


class InfoDirectory:
    """Parsed INFO tab, queryable by territory."""

    def __init__(self, people: Sequence[Person]):
        self.people = list(people)

    # ---- construction ---------------------------------------------------

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[str]]) -> "InfoDirectory":
        people: List[Person] = []
        role: Optional[str] = None
        columns: Dict[int, str] = {}

        for raw in rows:
            cells = [c.strip() if isinstance(c, str) else "" for c in (raw or [])]
            if not any(cells):
                role, columns = None, {}   # a blank row closes the block
                continue

            header_role = BLOCK_HEADERS.get(normalize(cells[0]))
            if header_role:
                role = header_role
                columns = {}
                for index, heading in enumerate(cells[1:], start=1):
                    attribute = COLUMN_ALIASES.get(normalize(heading))
                    if attribute:
                        columns[index] = attribute
                continue

            if role is None:
                continue  # data outside any block

            name = cells[0]
            if not name:
                continue

            person = Person(role=role, name=" ".join(name.split()))
            for index, attribute in columns.items():
                value = cells[index] if index < len(cells) else ""
                if attribute in MULTI_VALUE_ATTRS:
                    setattr(person, attribute, split_list(value))
                    if attribute in ("lhos", "states"):
                        setattr(person, f"{attribute}_raw", split_raw(value))
                else:
                    setattr(person, attribute, value.strip())
            people.append(person)

        logger.info(
            "info_directory: parsed %d people (%s)",
            len(people),
            ", ".join(f"{r}={sum(1 for p in people if p.role == r)}"
                      for r in (RM, ASM, CIRCLE_HEAD, DC)),
        )
        return cls(people)

    @classmethod
    def load(cls) -> "InfoDirectory":
        """Read the INFO tab from Google Sheets."""
        from app.services import csp_gsheet_service
        return cls.from_rows(csp_gsheet_service.read_info_sheet())

    # ---- lookups --------------------------------------------------------

    def _of_role(self, role: str) -> List[Person]:
        return [p for p in self.people if p.role == role]

    @staticmethod
    def _only(matches: List[Person]) -> Optional[Person]:
        """One match answers; none or several do not."""
        return matches[0] if len(matches) == 1 else None

    def find_by_district(self, role: str, district: str) -> Optional[Person]:
        if not district:
            return None
        return self._only(
            [p for p in self._of_role(role) if p.covers_district(district)])

    def find_by_territory(
        self, role: str, lho: str = "", state: str = ""
    ) -> Optional[Person]:
        """Narrowest match first: LHO and State together, then either alone.

        Two ASMs cover the Chandigarh LHO, so LHO alone cannot answer for them
        — but LHO plus State can.
        """
        candidates = self._of_role(role)

        if lho and state:
            match = self._only([p for p in candidates
                                if p.covers_lho(lho) and p.covers_state(state)])
            if match:
                return match

        if lho:
            match = self._only([p for p in candidates if p.covers_lho(lho)])
            if match:
                return match

        if state:
            match = self._only([p for p in candidates if p.covers_state(state)])
            if match:
                return match

        return None

    # ---- what a CSP row is missing --------------------------------------

    def fill_missing(self, mapped: Dict[str, str]) -> Dict[str, str]:
        """Return the values INFO can supply for blanks in one CSP row.

        Only genuinely empty fields are filled: the CSP sheet stays the source
        of truth wherever it has a value. Circle Head is not returned because
        no CSP column or document field holds one.
        """
        district = mapped.get("district", "")
        lho = mapped.get("lho", "")
        state = mapped.get("state", "")
        filled: Dict[str, str] = {}

        def blank(field_name: str) -> bool:
            return not (mapped.get(field_name) or "").strip()

        # LHO and State from the district, before anything else uses them.
        #
        # The DC block is the only one that lists districts, and it carries
        # the LHO and State for each row. Every district in it belongs to
        # exactly one DC, so a district names both — which turns a row that
        # gives only a district into one that can also resolve its RM and ASM.
        #
        # A DC covering more than one LHO (Maharashtra + Mumbai Metro) cannot
        # say which applies, so sole_lho() declines rather than taking the
        # first. The field then stays missing data, as it would have anyway.
        if blank("lho") or blank("state"):
            coordinator = self.find_by_district(DC, district)
            if coordinator:
                if blank("lho") and coordinator.sole_lho():
                    lho = filled["lho"] = coordinator.sole_lho()
                if blank("state") and coordinator.sole_state():
                    state = filled["state"] = coordinator.sole_state()

        # District Coordinator — matched on the district they cover.
        if blank("dc") or blank("dc_email") or blank("dc_contact"):
            person = self.find_by_district(DC, district)
            if person:
                if blank("dc") and person.name:
                    filled["dc"] = person.name
                if blank("dc_email") and person.email:
                    filled["dc_email"] = person.email
                if blank("dc_contact") and person.mobile:
                    filled["dc_contact"] = person.mobile

        # ASM — matched on territory.
        if blank("asm_name") or blank("asm_email") or blank("asm_contact"):
            person = self.find_by_territory(ASM, lho, state)
            if person:
                if blank("asm_name") and person.name:
                    filled["asm_name"] = person.name
                if blank("asm_email") and person.email:
                    filled["asm_email"] = person.email
                if blank("asm_contact") and person.mobile:
                    filled["asm_contact"] = person.mobile

        # Circle Head — matched on territory. No document prints one; it is
        # stored so an admin can filter by it.
        if blank("circle_head"):
            person = self.find_by_territory(CIRCLE_HEAD, lho, state)
            if person and person.name:
                filled["circle_head"] = person.name

        # The RM is deliberately NOT filled here. rm_resolution decides the
        # owner, and it distinguishes "the CSP sheet named an RM" (matched by
        # name) from "INFO covers this territory" (matched by email). Writing
        # the INFO name into rm_name first would make it look like the sheet
        # had named someone, and the lookup would then fail on the spelling —
        # INFO says "Vandana Kumar", the authorization sheet says "Vandana".
        # The worker sets rm_name from INFO after resolution instead.
        return filled
