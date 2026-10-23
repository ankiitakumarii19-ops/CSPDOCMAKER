"""The INFO tab: who covers which LHO, State and District.

The fixture mirrors the real tab's shape — four blocks separated by blank
rows, comma-separated territories, stray spaces, one person with no email, and
the same name appearing in two blocks.
"""

import pytest

from app.services import rm_resolution
from app.services.info_directory import (
    ASM, CIRCLE_HEAD, DC, RM, InfoDirectory,
)

# Trimmed from the real sheet, keeping every awkward case it contains.
INFO_ROWS = [
    ["Relationship Manager Name", "Email ID", "Mobile Number", "LHO", "State"],
    ["Vandana Kumar", "vandana.kumar.intern@eko.co.in", "9812345673 / 9812345672",
     "Patna", "Bihar, Jharkhand"],
    ["Shiwani Kumari", "shiwani.kumari@ekosupport.in", "9812345672",
     "Lucknow, New Delhi, Jaipur", "Uttar Pradesh, NCT of Delhi, Rajasthan"],
    [" Amuda Murgesh", "amuda.murgesh@eko.co.in", "9217060639",
     "Chandigarh", "Haryana, Punjab, Himachal Pradesh"],
    [],
    [],
    ["ASM Name", "Email ID", "Mobile Number", "LHO ", "State"],
    ["Munna Pathak", "munna.pathak@eko.co.in", "94714 69396", "Patna ", "Bihar, Jharkhand"],
    ["Anil Sharma", "anil.sharma@eko.co.in", "9306252773", "Chandigarh", "Haryana"],
    ["Narottam", "", "7986622751", "Chandigarh", "Punjab"],
    [],
    ["Circle Head Name", "Email ID", "Mobile Number", "LHO", "State"],
    ["Munna Pathak", "munna.pathak@eko.co.in", "94714 69396", "Patna", "Bihar, Jharkhand"],
    [],
    ["District Coordinator Name", "Email ID", "Mobile Number", "LHO", "State",
     "Districts Covered"],
    ["Balram", "kumarbalram.0055@gmail.com", "7631817471", "Patna", "Bihar",
     "Araria, Banka, Bhagalpur, Katihar, Saharsa, Supaul"],
    ["Ashutosh Pathak", "ashutosh.pathak@eko.co.in", "9296168058", "Patna", "Bihar",
     "Arwal, Aurangabad, Patna, Nalanda"],
]


@pytest.fixture
def info():
    return InfoDirectory.from_rows(INFO_ROWS)


# ---- parsing -------------------------------------------------------------

def test_every_block_is_parsed_separately(info):
    counts = {role: sum(1 for p in info.people if p.role == role)
              for role in (RM, ASM, CIRCLE_HEAD, DC)}
    assert counts == {RM: 3, ASM: 3, CIRCLE_HEAD: 1, DC: 2}


def test_comma_separated_territories_become_lists(info):
    vandana = next(p for p in info.people if p.name == "Vandana Kumar")
    assert vandana.states == ["bihar", "jharkhand"]
    assert vandana.lhos == ["patna"]


def test_stray_spaces_are_ignored(info):
    """The real sheet has ' Amuda Murgesh' and an LHO of 'Patna '."""
    assert any(p.name == "Amuda Murgesh" for p in info.people)
    munna = next(p for p in info.people if p.role == ASM)
    assert munna.covers_lho("patna")


def test_the_same_person_in_two_blocks_is_not_conflated(info):
    """Munna Pathak is both an ASM and a Circle Head."""
    roles = {p.role for p in info.people if p.name == "Munna Pathak"}
    assert roles == {ASM, CIRCLE_HEAD}


def test_an_empty_sheet_parses_to_nothing():
    assert InfoDirectory.from_rows([]).people == []


def test_rows_outside_any_block_are_ignored():
    directory = InfoDirectory.from_rows([["Stray", "data", "with no header"]])
    assert directory.people == []


# ---- lookups -------------------------------------------------------------

def test_the_district_coordinator_is_found_by_district(info):
    assert info.find_by_district(DC, "Saharsa").name == "Balram"
    assert info.find_by_district(DC, "Nalanda").name == "Ashutosh Pathak"


def test_an_uncovered_district_has_no_coordinator(info):
    assert info.find_by_district(DC, "Nowhere") is None


def test_territory_lookup_prefers_lho_and_state_together(info):
    """Two ASMs share the Chandigarh LHO; the state decides between them."""
    assert info.find_by_territory(ASM, "Chandigarh", "Haryana").name == "Anil Sharma"
    assert info.find_by_territory(ASM, "Chandigarh", "Punjab").name == "Narottam"


def test_an_ambiguous_lho_answers_nothing_rather_than_guessing(info):
    assert info.find_by_territory(ASM, "Chandigarh", "") is None


def test_state_alone_resolves_when_it_is_unique(info):
    assert info.find_by_territory(RM, "", "Jharkhand").name == "Vandana Kumar"


# ---- filling a CSP row ---------------------------------------------------

def _row(**overrides):
    row = {"district": "", "lho": "", "state": "", "dc": "", "dc_email": "",
           "dc_contact": "", "asm_name": "", "asm_email": "", "asm_contact": "",
           "rm_name": ""}
    row.update(overrides)
    return row


def test_blank_people_are_filled_from_info(info):
    filled = info.fill_missing(_row(district="Saharsa", lho="Patna", state="Bihar"))
    assert filled["dc"] == "Balram"
    assert filled["dc_email"] == "kumarbalram.0055@gmail.com"
    assert filled["dc_contact"] == "7631817471"
    assert filled["asm_name"] == "Munna Pathak"
    # The RM is deliberately not filled here — rm_resolution owns that, and
    # the worker records the name only after resolution has run.
    assert "rm_name" not in filled


def test_values_already_in_the_sheet_are_never_overwritten(info):
    """The CSP sheet stays the source of truth where it has an answer."""
    filled = info.fill_missing(_row(
        district="Saharsa", lho="Patna", state="Bihar",
        dc="Someone Else", asm_name="Another Asm",
    ))
    assert "dc" not in filled
    assert "asm_name" not in filled
    # The parts that were blank are still filled in.
    assert filled["dc_email"] == "kumarbalram.0055@gmail.com"


def test_a_missing_email_in_info_is_not_invented(info):
    filled = info.fill_missing(_row(lho="Chandigarh", state="Punjab"))
    assert filled["asm_name"] == "Narottam"
    assert "asm_email" not in filled, "Narottam has no email in INFO"


def test_nothing_is_filled_when_info_cannot_answer(info):
    assert info.fill_missing(_row(district="Nowhere", lho="Nowhere", state="Nowhere")) == {}


def test_circle_head_is_filled_from_the_territory(info):
    """No document prints one; it is stored so an admin can filter by it."""
    filled = info.fill_missing(_row(district="Saharsa", lho="Patna", state="Bihar"))
    assert filled["circle_head"] == "Munna Pathak"


def test_a_circle_head_the_row_already_has_is_left_alone(info):
    row = _row(district="Saharsa", lho="Patna", state="Bihar")
    row["circle_head"] = "Someone Else"
    assert "circle_head" not in info.fill_missing(row)


# ---- RM resolution through INFO ------------------------------------------

AUTHORIZED = {"vandana.kumar.intern@eko.co.in"}
NAME_TO_EMAIL = {"vandana": "vandana.kumar.intern@eko.co.in"}


def test_the_csp_rows_own_rm_column_still_wins(info):
    email, how = rm_resolution.resolve_rm(
        {"rm_name": "Vandana", "lho": "Chandigarh", "state": "Haryana"},
        NAME_TO_EMAIL, {}, info=info, authorized_emails=AUTHORIZED)
    assert (email, how) == ("vandana.kumar.intern@eko.co.in", rm_resolution.BY_SHEET)


def test_an_empty_rm_cell_resolves_through_the_info_lho(info):
    email, how = rm_resolution.resolve_rm(
        {"rm_name": "", "lho": "Patna", "state": "Bihar"},
        NAME_TO_EMAIL, {}, info=info, authorized_emails=AUTHORIZED)
    assert (email, how) == ("vandana.kumar.intern@eko.co.in",
                            rm_resolution.BY_INFO_LHO)


def test_state_resolves_when_the_lho_does_not(info):
    email, how = rm_resolution.resolve_rm(
        {"rm_name": "", "lho": "", "state": "Jharkhand"},
        NAME_TO_EMAIL, {}, info=info, authorized_emails=AUTHORIZED)
    assert (email, how) == ("vandana.kumar.intern@eko.co.in",
                            rm_resolution.BY_INFO_STATE)


def test_info_matching_is_by_email_not_by_name(info):
    """INFO says 'Vandana Kumar'; the authorization sheet says 'Vandana'."""
    email, how = rm_resolution.resolve_rm(
        {"rm_name": "", "lho": "Patna", "state": "Bihar"},
        {}, {}, info=info,   # no name map at all
        authorized_emails=AUTHORIZED)
    assert email == "vandana.kumar.intern@eko.co.in"


def test_someone_in_info_who_cannot_log_in_leaves_it_unresolved(info):
    """Shiwani covers Lucknow but is not authorized, so every RM is alerted."""
    email, how = rm_resolution.resolve_rm(
        {"rm_name": "", "lho": "Lucknow", "state": "Uttar Pradesh"},
        NAME_TO_EMAIL, {}, info=info, authorized_emails=AUTHORIZED)
    assert email is None
    assert how == rm_resolution.UNRESOLVED


def test_being_in_info_never_grants_access(info):
    """Amuda Murgesh is in INFO but not in the authorization sheet."""
    email, how = rm_resolution.resolve_rm(
        {"rm_name": "", "lho": "Chandigarh", "state": "Haryana"},
        NAME_TO_EMAIL, {}, info=info, authorized_emails=AUTHORIZED)
    assert email is None
    assert how == rm_resolution.UNRESOLVED


def test_territory_nobody_covers_is_unresolved(info):
    email, how = rm_resolution.resolve_rm(
        {"rm_name": "", "lho": "Atlantis", "state": "Atlantis"},
        NAME_TO_EMAIL, {}, info=info, authorized_emails=AUTHORIZED)
    assert (email, how) == (None, rm_resolution.UNRESOLVED)


def test_resolution_still_works_without_info():
    """A failed INFO read must not break resolution."""
    email, how = rm_resolution.resolve_rm(
        {"rm_name": "", "lho": "Patna"},
        {"vandana": "vandana.kumar.intern@eko.co.in"},
        {"patna": "vandana"}, info=None)
    assert (email, how) == ("vandana.kumar.intern@eko.co.in", rm_resolution.BY_LHO)


# ---- the AO block (No. 141) ----------------------------------------------
# Rows from the real tab (23 Oct 2026), with the bare "LHO" list above it.

AO_ROWS = INFO_ROWS + [
    [], [],
    ["LHO"], ["Patna"], ["Chandigarh"],
    [],
    ["LHO", "LHO Email ID", "State", "AO", "AO Email ID", "District",
     "RBO Name", "RBO Code", "RBO Email ID", "Branch Name"],
    ["Patna", "x@sbi.co.in", "Bihar", "AO BHAGALPUR", "", "Jamui", "Jamui",
     "2", "", "GOPALPUR, CHAKAI BAZAR, LAXMIPUR ( DISTJAMUI), JAMUI"],
    ["Patna", "x@sbi.co.in", "Bihar", "AO BHAGALPUR", "", "Madhepura",
     "Saharsa", "3", "", "MURLIGANJ"],
    ["Mumbai Metro", "y@sbi.co.in", "Maharashtra", "AO NASHIK", "",
     "Nandurbar", "Nandurbar", "1", "", "VISARWADI"],
    ["Lucknow", "z@sbi.co.in", "Uttar Pradesh", "AO LUCKNOW EAST", "",
     "Lucknow", "RBO 1", "1", "", "CHINHAT"],
    ["Lucknow", "z@sbi.co.in", "Uttar Pradesh", "AO LUCKNOW WEST", "",
     "Lucknow", "RBO 2", "2", "", "ALAMBAGH"],
    ["Chandigarh", "c@sbi.co.in", "Haryana", "AO-PANCHKULA", "",
     "Yamuna Nagar", "RBO 3", "1", "", "ACB JAGADHRI, JAMUI"],
]


@pytest.fixture
def ao_info():
    return InfoDirectory.from_rows(AO_ROWS)


def test_the_ao_block_is_read_and_the_people_still_are(ao_info):
    assert len(ao_info.ao_areas) == 6
    assert sum(1 for p in ao_info.people if p.role == DC) == 2


def test_a_blank_ao_is_filled_from_the_branch(ao_info):
    """Yogesh (1A851379): Nandurbar, branch VISARWADI, AO blank in KOData."""
    filled = ao_info.fill_missing({"ao": "", "branch_name": "Visarwadi",
                                   "district": "Nandurbar",
                                   "state": "Maharashtra"})
    assert filled["ao"] == "AO NASHIK"


def test_branch_names_match_ignoring_spaces_and_brackets(ao_info):
    assert ao_info.find_ao("Laxmipur (DistJamui)", state="Bihar") \
        == "AO BHAGALPUR"


def test_the_district_answers_when_the_branch_is_not_listed(ao_info):
    assert ao_info.find_ao("", "Madhepura", "Bihar") == "AO BHAGALPUR"


def test_a_district_split_between_two_aos_answers_nothing(ao_info):
    assert ao_info.find_ao("Some New Branch", "Lucknow",
                           "Uttar Pradesh") == ""


def test_the_branch_still_decides_in_a_split_district(ao_info):
    assert ao_info.find_ao("Alambagh", "Lucknow", "Uttar Pradesh") \
        == "AO LUCKNOW WEST"


def test_the_state_keeps_a_shared_branch_name_apart(ao_info):
    """JAMUI is a branch in Bihar and (here) in Haryana."""
    assert ao_info.find_ao("Jamui", state="Bihar") == "AO BHAGALPUR"
    assert ao_info.find_ao("Jamui", state="Haryana") == "AO-PANCHKULA"
    assert ao_info.find_ao("Jamui") == "", "two AOs and no State: no guess"


def test_an_ao_already_in_the_sheet_is_never_replaced(ao_info):
    filled = ao_info.fill_missing({"ao": "AO SOMEWHERE",
                                   "branch_name": "Visarwadi",
                                   "state": "Maharashtra"})
    assert "ao" not in filled


def test_without_the_ao_block_nothing_is_filled(info):
    assert "ao" not in info.fill_missing({"ao": "", "branch_name": "Jamui",
                                          "district": "Jamui",
                                          "state": "Bihar"})
