"""Who gets asked for a missing field.

Chasing the wrong person is the failure here. A CSP cannot name their RBO and
an RM cannot state a CSP's gender, so each field belongs to exactly one of
them, and an ORG field is only ever put to a human after the INFO tab has
declined to answer it.
"""

import pytest

from app.models.csp_record import CSPRecord
from app.services import csp_mapping
from app.services import field_ownership as fo

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _record(**fields):
    record = CSPRecord(csp_id="1A000001")
    for key, value in fields.items():
        setattr(record, key, value)
    return record


# ---- the two buckets ----------------------------------------------------

async def test_every_field_has_exactly_one_owner():
    overlap = set(fo.CSP_OWNED) & set(fo.ORG_OWNED)
    assert not overlap, f"{overlap} would be chased with two people at once"


async def test_the_csp_is_asked_only_for_their_own_details():
    assert fo.owner_of("gender") == fo.CSP
    assert fo.owner_of("photo_url") == fo.CSP
    assert fo.owner_of("address") == fo.CSP


async def test_the_csp_is_never_asked_for_the_hierarchy():
    """A CSP has not heard of their RBO and must not be invited to invent one."""
    for field in ("rbo_name", "ao", "dc", "asm_name", "lho"):
        assert fo.owner_of(field) == fo.ORG


async def test_an_unowned_field_is_refused_loudly():
    """Silently returning a default would let a field block with nobody told."""
    with pytest.raises(KeyError):
        fo.owner_of("certificate_date")


async def test_every_field_has_a_label_for_the_person_asked():
    missing = [f for f in fo.ALL_FIELDS if f not in fo.LABELS]
    assert not missing, f"{missing} would be shown to a human as a column name"


async def test_every_field_is_a_real_column():
    """The canonical name is the CSPRecord attribute — no third vocabulary."""
    for field in fo.ALL_FIELDS:
        assert hasattr(CSPRecord, field), f"{field} is not a CSPRecord column"


# ---- what INFO can and cannot answer ------------------------------------

async def test_the_bank_facts_are_always_manual():
    """INFO is Eko's org chart; it holds no AO or RBO column.

    Two fields left this list for different reasons. The branch NAME and
    CODE went to the CSP, who knows them. The branch and RBO CONTACT
    numbers went nowhere: no document prints either, so nobody is asked.
    """
    assert set(fo.ALWAYS_MANUAL) == {"ao", "rbo_name"}


async def test_info_answers_the_people_fields():
    for field in ("dc", "dc_email", "dc_contact",
                  "asm_name", "asm_email", "asm_contact", "rm_name"):
        assert field in fo.INFO_CAN_FILL


async def test_unfillable_by_info_keeps_only_what_a_human_must_supply():
    asked = fo.unfillable_by_info(["dc", "ao", "asm_name", "rbo_name"])
    assert asked == ["ao", "rbo_name"]


async def test_nothing_is_asked_for_when_info_covers_it_all():
    assert fo.unfillable_by_info(["dc", "dc_email", "rm_name"]) == []


# ---- splitting one record -----------------------------------------------

async def test_a_blank_record_is_split_by_owner():
    split = fo.missing(_record())
    assert split[fo.CSP] == list(fo.CSP_OWNED)
    assert split[fo.ORG] == list(fo.ORG_OWNED)


async def test_a_filled_field_is_not_chased():
    split = fo.missing(_record(gender="Female", ao="Panchkula"))
    assert "gender" not in split[fo.CSP]
    assert "ao" not in split[fo.ORG]


async def test_whitespace_is_not_a_value():
    """A cell holding a space must still be chased."""
    assert "gender" in fo.missing(_record(gender="   "))[fo.CSP]


async def test_the_order_asked_is_the_declared_order():
    split = fo.missing(_record(name="X", address="Y"))
    assert split[fo.CSP] == ["csp_code", "mobile", "email", "gender",
                             "district", "state", "branch_name",
                             "branch_code", "photo_url"]


async def test_the_branch_is_asked_of_the_csp_not_the_rm():
    """A CSP knows their own branch and its code — it is on their own
    paperwork. Asking an RM to look it up for every CSP was chasing the
    wrong person for something the CSP can answer at once."""
    split = fo.missing(_record())
    for field in ("branch_name", "branch_code"):
        assert fo.owner_of(field) == fo.CSP
        assert field in split[fo.CSP]
        assert field not in split[fo.ORG]
        # And it has to actually appear on the form the CSP is sent.
        assert field in fo.CSP_EDITABLE
        assert field in fo.form_fields()


@pytest.mark.parametrize("field", ["branch_contact", "rbo_contact"])
async def test_a_field_no_document_can_print_is_chased_from_nobody(field):
    """Neither is in FIELD_TO_CSP_ATTR, so no template could carry one even
    if a placeholder asked. Chasing somebody for a value no document can
    use is pure cost, so these are asked of nobody."""
    from app.models.enums import DocumentType
    from app.services import csp_mapping as cm

    assert field not in cm.FIELD_TO_CSP_ATTR, (
        f"{field} became printable — it should be chased again")
    for doc_type in DocumentType:
        assert field not in cm.required_fields_for(doc_type)

    split = fo.missing(_record())
    assert field not in split[fo.CSP]
    assert field not in split[fo.ORG]
    assert field not in fo.CSP_EDITABLE


async def test_the_branch_fields_are_asked_in_both_languages():
    """They are on the CSP's form now, and that form is bilingual."""
    for field in ("branch_name", "branch_code"):
        assert field in fo.LABELS_HI, f"{field} has no Hindi label"
        assert "/" in fo.label_bilingual(field)


# ---- the three columns that used to map to nothing ----------------------

async def test_the_formerly_unused_columns_still_map():
    """These sheet columns are still read and still stored.

    Branch Contact and RBO Contact are no longer chased — no document can
    print them — but the sheet column must still map, or a value somebody
    typed there would be dropped on sync.
    """
    for column, field in (("Gender", "gender"),
                          ("Branch Contact Number", "branch_contact"),
                          ("RBO Contact No.", "rbo_contact")):
        assert csp_mapping.SHEET_COLUMN_TO_FIELD[column] == field
    assert "gender" in fo.ALL_FIELDS


async def test_every_sheet_column_round_trips_to_its_header():
    """Write-back needs the inverse map to be complete and lossless."""
    for column, field in csp_mapping.SHEET_COLUMN_TO_FIELD.items():
        assert csp_mapping.FIELD_TO_SHEET_COLUMN[field] == column


# ---- the CSP's own form -------------------------------------------------

async def test_the_form_shows_everything_not_only_the_blanks():
    """Confirmed behaviour: the CSP verifies their record, not a gap list.

    A value already on file can be wrong, so it is shown pre-filled and
    editable rather than hidden because it is non-empty.
    """
    record = _record(name="Nitasha", mobile="9812345670", gender="Female")
    assert set(fo.form_fields()) >= {"name", "mobile", "gender"}


async def test_the_csp_code_cannot_be_edited_on_the_form():
    """It identifies the record. Editing it could only point elsewhere."""
    assert "csp_code" in fo.CSP_OWNED
    assert "csp_code" not in fo.CSP_EDITABLE
    assert "csp_code" not in fo.form_fields()


async def test_the_form_covers_every_detail_the_csp_owns():
    for field in fo.CSP_OWNED:
        if field == "csp_code":
            continue
        assert field in fo.form_fields(), f"{field} is never asked"


# ---- the four 'do you already have it' questions ------------------------

async def test_the_document_questions_are_answered_by_the_csp():
    for field in fo.DOCUMENTS_HELD:
        assert fo.owner_of(field) == fo.CSP


async def test_the_document_questions_never_become_required_data():
    """They block nothing. A CSP without a BCP still gets their documents."""
    from app.models.enums import DocumentType
    from app.services import csp_mapping

    for doc_type in DocumentType:
        required = set(csp_mapping.required_fields_for(doc_type))
        assert not (required & set(fo.DOCUMENTS_HELD)), (
            f"{doc_type.value} would refuse to generate over a survey answer")


async def test_the_document_questions_are_not_missing_data():
    """A blank one must not show up as something an RM has to chase."""
    split = fo.missing(_record())
    for field in fo.DOCUMENTS_HELD:
        assert field not in split[fo.CSP]
        assert field not in split[fo.ORG]


async def test_each_document_question_has_a_sheet_column():
    """The answers have to land somewhere, or asking is pointless."""
    for field in fo.DOCUMENTS_HELD:
        assert field in csp_mapping.FIELD_TO_SHEET_COLUMN


async def test_a_document_question_renders_as_yes_no_plus_upload():
    for field in fo.DOCUMENTS_HELD:
        assert fo.input_type_of(field) == "yesno_upload"
