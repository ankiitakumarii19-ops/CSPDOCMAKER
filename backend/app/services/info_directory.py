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

A fifth block (added 23 Oct 2026, No. 141) is the bank's side, one row per
district:

    LHO | LHO Email ID | State | AO | AO Email ID | District | RBO Name |
    RBO Code | RBO Email ID | Branch Name

Branch Name lists that district's branches, comma-separated. It fills a
blank AO and RBO Name (No. 142): by the CSP's branch first, then by their
district. RBO Name is written "RBO <RBO Code>", as KOData has it (all 462
such KOData rows agree with the code); a row with no code gives its name.

A lookup only answers when exactly one person matches. Two ASMs share the
Chandigarh LHO (one for Haryana, one for Punjab), so an LHO alone is not
always enough; where a match is ambiguous this returns nothing and the field
stays missing data for the RM to fill, rather than guessing.

This directory says who covers a territory. It does NOT say who may log in —
that remains the authorization sheet's job alone.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

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

# The AO block's header row starts with "LHO" and has an "AO" column; the
# bare "LHO" list above it has neither, and is ignored.
AO_COLUMNS: Dict[str, str] = {
    "state": "state",
    "ao": "ao",
    "district": "district",
    "rbo name": "rbo_name",
    "rbo code": "rbo_code",
    "branch name": "branches",
}


def normalize(value: str) -> str:
    """Case- and space-insensitive form used for every comparison."""
    return " ".join((value or "").split()).strip().lower()


def split_list(value: str) -> List[str]:
    """'Bihar, Jharkhand' → ['bihar', 'jharkhand']."""
    return [normalize(part) for part in (value or "").split(",") if normalize(part)]


def place_key(value: str) -> str:
    """Branch and district names compared on letters and digits only:
    'LAXMIPUR ( DISTJAMUI)' and 'Laxmipur (DistJamui)' are the same."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split())


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


AO_BLOCK = "ao_block"


@dataclass
class AOArea:
    """One row of the AO block: a district, its AO, RBO and branches."""
    ao: str
    rbo: str = ""
    state: str = ""                                      # normalize()d
    district: str = ""                                   # place_key()
    branches: List[str] = field(default_factory=list)    # place_key()s


class InfoDirectory:
    """Parsed INFO tab, queryable by territory."""

    def __init__(self, people: Sequence[Person],
                 ao_areas: Sequence[AOArea] = ()):
        self.people = list(people)
        self.ao_areas = list(ao_areas)

    # ---- construction ---------------------------------------------------

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[str]]) -> "InfoDirectory":
        people: List[Person] = []
        ao_areas: List[AOArea] = []
        role: Optional[str] = None
        columns: Dict[int, str] = {}

        for raw in rows:
            cells = [c.strip() if isinstance(c, str) else "" for c in (raw or [])]
            if not any(cells):
                role, columns = None, {}   # a blank row closes the block
                continue

            if (normalize(cells[0]) == "lho"
                    and "ao" in {normalize(c) for c in cells}):
                role, columns = AO_BLOCK, {}
                for index, heading in enumerate(cells):
                    attribute = AO_COLUMNS.get(normalize(heading))
                    if attribute:
                        columns[index] = attribute
                continue

            if role == AO_BLOCK:
                values = {attribute: (cells[i] if i < len(cells) else "")
                          for i, attribute in columns.items()}
                ao = " ".join(values.get("ao", "").split())
                code = values.get("rbo_code", "").strip()
                rbo = (f"RBO {code}" if code else
                       " ".join(values.get("rbo_name", "").split()))
                if ao or rbo:
                    ao_areas.append(AOArea(
                        ao=ao, rbo=rbo,
                        state=normalize(values.get("state", "")),
                        district=place_key(values.get("district", "")),
                        branches=[place_key(b) for b in
                                  values.get("branches", "").split(",")
                                  if place_key(b)]))
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
            "info_directory: parsed %d people (%s), %d AO rows",
            len(people),
            ", ".join(f"{r}={sum(1 for p in people if p.role == r)}"
                      for r in (RM, ASM, CIRCLE_HEAD, DC)),
            len(ao_areas),
        )
        return cls(people, ao_areas)

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
        return self.territory_match(role, lho, state)[0]

    def territory_match(
        self, role: str, lho: str = "", state: str = ""
    ) -> Tuple[Optional[Person], str]:
        """find_by_territory, plus what decided it, in words (No. 146):
        "LHO 'X' and State 'Y'", "LHO 'X'" or "State 'Y'"."""
        candidates = self._of_role(role)

        if lho and state:
            match = self._only([p for p in candidates
                                if p.covers_lho(lho) and p.covers_state(state)])
            if match:
                return match, f"LHO '{lho}' and State '{state}'"

        if lho:
            match = self._only([p for p in candidates if p.covers_lho(lho)])
            if match:
                return match, f"LHO '{lho}'"

        if state:
            match = self._only([p for p in candidates if p.covers_state(state)])
            if match:
                return match, f"State '{state}'"

        return None, ""

    def find_ao(self, branch_name: str = "", district: str = "",
                state: str = "") -> str:
        """The CSP's AO, or '' when the AO block cannot say for certain."""
        return self._from_ao_block("ao", branch_name, district, state)

    def find_rbo(self, branch_name: str = "", district: str = "",
                 state: str = "") -> str:
        """The CSP's RBO Name ("RBO 4"), or '' when not certain."""
        return self._from_ao_block("rbo", branch_name, district, state)

    def _from_ao_block(self, attribute: str, branch_name: str,
                       district: str, state: str) -> str:
        return self.ao_block_match(attribute, branch_name, district, state)[0]

    def ao_block_match(self, attribute: str, branch_name: str,
                       district: str, state: str) -> Tuple[str, str]:
        """The branch decides first (a branch has one AO and RBO); the
        district only when the branch is not listed. Either answers only
        when every match gives the same value — Lucknow district is split
        between two AOs, so it alone answers nothing. Within the CSP's
        State when the block lists that State, so a branch name used in
        two States cannot pick wrongly.
        """
        areas = [a for a in self.ao_areas if getattr(a, attribute)]
        if normalize(state) and any(a.state == normalize(state) for a in areas):
            areas = [a for a in areas if a.state == normalize(state)]

        for key, matches in (
                (place_key(branch_name), lambda a, k: k in a.branches),
                (place_key(district), lambda a, k: a.district == k)):
            if not key:
                continue
            found = {normalize(getattr(a, attribute)): getattr(a, attribute)
                     for a in areas if matches(a, key)}
            if len(found) == 1:
                by = (f"branch '{branch_name.strip()}'"
                      if key == place_key(branch_name)
                      else f"district '{district.strip()}'")
                return next(iter(found.values())), by
        return "", ""

    # ---- what a CSP row is missing --------------------------------------

    def fill_missing(self, mapped: Dict[str, str],
                     why: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Return the values INFO can supply for blanks in one CSP row.

        Only genuinely empty fields are filled: the CSP sheet stays the source
        of truth wherever it has a value. Circle Head is not returned because
        no CSP column or document field holds one.

        `why`, when given, receives {field: the reason in words} for every
        value returned — shown on the CSP's panel (No. 146).
        """
        why = {} if why is None else why
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
                because = (f"INFO DC block: district '{district}' is in one "
                           f"LHO and State")
                if blank("lho") and coordinator.sole_lho():
                    lho = filled["lho"] = coordinator.sole_lho()
                    why["lho"] = because
                if blank("state") and coordinator.sole_state():
                    state = filled["state"] = coordinator.sole_state()
                    why["state"] = because

        # District Coordinator — matched on the district they cover.
        if blank("dc") or blank("dc_email") or blank("dc_contact"):
            person = self.find_by_district(DC, district)
            if person:
                because = f"INFO DC block, by district '{district}'"
                if blank("dc") and person.name:
                    filled["dc"] = person.name
                    why["dc"] = because
                if blank("dc_email") and person.email:
                    filled["dc_email"] = person.email
                    why["dc_email"] = because
                if blank("dc_contact") and person.mobile:
                    filled["dc_contact"] = person.mobile
                    why["dc_contact"] = because

        # ASM — matched on territory.
        if blank("asm_name") or blank("asm_email") or blank("asm_contact"):
            person, by = self.territory_match(ASM, lho, state)
            if person:
                because = f"INFO ASM block, by {by}"
                if blank("asm_name") and person.name:
                    filled["asm_name"] = person.name
                    why["asm_name"] = because
                if blank("asm_email") and person.email:
                    filled["asm_email"] = person.email
                    why["asm_email"] = because
                if blank("asm_contact") and person.mobile:
                    filled["asm_contact"] = person.mobile
                    why["asm_contact"] = because

        # AO and RBO Name — from the AO block, by branch then district
        # (No. 141, No. 142).
        branch = mapped.get("branch_name", "")
        if blank("ao"):
            ao, by = self.ao_block_match("ao", branch, district, state)
            if ao:
                filled["ao"] = ao
                why["ao"] = f"INFO AO block, by {by}"
        if blank("rbo_name"):
            rbo, by = self.ao_block_match("rbo", branch, district, state)
            if rbo:
                filled["rbo_name"] = rbo
                why["rbo_name"] = f"INFO AO block, by {by}"

        # Circle Head — matched on territory. No document prints one; it is
        # stored so an admin can filter by it.
        if blank("circle_head"):
            person, by = self.territory_match(CIRCLE_HEAD, lho, state)
            if person and person.name:
                filled["circle_head"] = person.name
                why["circle_head"] = f"INFO Circle Head block, by {by}"

        # The RM is deliberately NOT filled here. rm_resolution decides the
        # owner, and it distinguishes "the CSP sheet named an RM" (matched by
        # name) from "INFO covers this territory" (matched by email). Writing
        # the INFO name into rm_name first would make it look like the sheet
        # had named someone, and the lookup would then fail on the spelling —
        # INFO says "Vandana Kumar", the authorization sheet says "Vandana".
        # The worker sets rm_name from INFO after resolution instead.
        return filled
