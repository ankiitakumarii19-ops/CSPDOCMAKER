"""A district names its LHO and its State.

The DC block is the only one listing districts, and each of its rows carries
an LHO and a State. Every district in the live sheet belongs to exactly one
DC, so knowing the district is enough to know both — which turns a CSP row
that gives only a district into one that can also resolve its RM and ASM.

Where a DC covers more than one LHO the district cannot say which applies,
and the field stays missing rather than being guessed.
"""

import pytest

from app.services.info_directory import InfoDirectory

pytestmark = pytest.mark.asyncio(loop_scope="session")

ROWS = [
    ["Relationship Manager Name", "Email ID", "Mobile Number", "LHO", "State"],
    ["Vandana Kumar", "vandana@eko.co.in", "900", "Patna", "Bihar, Jharkhand"],
    [],
    ["ASM Name", "Email ID", "Mobile Number", "LHO", "State"],
    ["Munna Pathak", "munna@eko.co.in", "901", "Patna", "Bihar, Jharkhand"],
    [],
    ["District Coordinator Name", "Email ID", "Mobile Number", "LHO", "State",
     "Districts Covered"],
    ["Ashutosh Pathak", "ashutosh@eko.co.in", "902", "Patna", "Bihar",
     "Patna, Nalanda, Buxar"],
    # Covers two LHOs, so a district of theirs cannot name one.
    ["Vijay Dhangar", "vijay@eko.co.in", "903", "Maharashtra, Mumbai Metro",
     "Maharashtra", "Pune, Thane"],
    # Capitalisation that must survive the round trip.
    ["Shiwani Kumari", "shiwani@eko.co.in", "904", "New Delhi", "NCT of Delhi",
     "New Delhi"],
]


@pytest.fixture
def directory():
    return InfoDirectory.from_rows(ROWS)


async def test_a_district_names_its_lho_and_state(directory):
    filled = directory.fill_missing({"district": "Patna", "lho": "", "state": ""})
    assert filled["lho"] == "Patna"
    assert filled["state"] == "Bihar"


async def test_a_dc_covering_two_lhos_names_neither(directory):
    """Picking the first would put a CSP in the wrong circle."""
    filled = directory.fill_missing({"district": "Pune", "lho": "", "state": ""})
    assert "lho" not in filled
    assert filled["state"] == "Maharashtra", "state is still unambiguous"


async def test_the_sheets_own_capitalisation_is_kept(directory):
    """Comparison is lowercased; what gets stored must not be."""
    filled = directory.fill_missing({"district": "New Delhi", "lho": "",
                                     "state": ""})
    assert filled["state"] == "NCT of Delhi"
    assert filled["lho"] == "New Delhi"


async def test_an_unknown_district_fills_nothing(directory):
    assert directory.fill_missing(
        {"district": "Nowhere", "lho": "", "state": ""}) == {}


async def test_a_district_already_carrying_an_lho_is_left_alone(directory):
    """The CSP sheet stays the source of truth wherever it has a value."""
    filled = directory.fill_missing(
        {"district": "Patna", "lho": "Something Else", "state": ""})
    assert "lho" not in filled


async def test_matching_ignores_case_and_spacing(directory):
    filled = directory.fill_missing({"district": "  nalanda ", "lho": "",
                                     "state": ""})
    assert filled["lho"] == "Patna"


# ---- the point of deriving them at all ----------------------------------

async def test_a_derived_lho_then_resolves_the_asm(directory):
    """Before this, a row with only a district could not reach the ASM.

    The derived LHO and State feed the territory lookups in the same pass,
    so one district now answers eight fields instead of three.
    """
    filled = directory.fill_missing({"district": "Patna", "lho": "", "state": ""})
    assert filled["asm_name"] == "Munna Pathak"
    assert filled["dc"] == "Ashutosh Pathak"
    assert filled["lho"] == "Patna"


async def test_no_district_means_no_derivation(directory):
    filled = directory.fill_missing({"district": "", "lho": "", "state": ""})
    assert "lho" not in filled and "state" not in filled


# ---- the property the live sheet must keep ------------------------------

async def test_a_district_shared_by_two_dcs_answers_nothing():
    """If the sheet ever puts one district under two DCs, it must go quiet."""
    rows = ROWS + [
        ["Someone Else", "other@eko.co.in", "905", "Lucknow", "Uttar Pradesh",
         "Patna"],
    ]
    directory = InfoDirectory.from_rows(rows)
    filled = directory.fill_missing({"district": "Patna", "lho": "", "state": ""})
    assert "lho" not in filled
    assert "state" not in filled
    assert "dc" not in filled
