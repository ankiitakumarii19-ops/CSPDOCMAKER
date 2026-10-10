"""The sheet sync must not wipe the photo fetched from the CRM.

photo_url is a mapped sheet column, but in practice it is filled from Zoho,
never from the sheet. The sync compares every field against the sheet each
minute, so a blank cell was clearing the fetched path — which made the photo
be downloaded from the CRM again on every pass.

The rule pinned here: the sheet wins wherever it HAS a value; a blank cell
means "no opinion", not "delete".
"""

import pytest

from app.workers.csp_sync_worker import _KEEP_IF_SHEET_BLANK, _SYNC_EXCLUDED

pytestmark = pytest.mark.asyncio(loop_scope="session")

CRM_PHOTO = r"generated_documents\photos\1A851727.png"
SHEET_PHOTO = r"C:\from\the\sheet.png"


class _Record:
    """Just enough of CSPRecord to exercise the diff."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def _apply_sync(existing, mapped):
    """The sync's field-level diff, as csp_sync_worker runs it."""
    changed = False
    for field, value in mapped.items():
        if field in _SYNC_EXCLUDED:
            continue
        if (not value and field in _KEEP_IF_SHEET_BLANK
                and getattr(existing, field, None)):
            continue
        if (getattr(existing, field, None) or "") != value:
            setattr(existing, field, value or None)
            changed = True
    return changed


async def test_a_blank_sheet_cell_does_not_clear_the_crm_photo():
    record = _Record(photo_url=CRM_PHOTO, name="Nitasha")
    _apply_sync(record, {"photo_url": "", "name": "Nitasha"})
    assert record.photo_url == CRM_PHOTO


async def test_a_photo_in_the_sheet_still_wins():
    """The sheet remains the source of truth where it has a value."""
    record = _Record(photo_url=CRM_PHOTO, name="Nitasha")
    _apply_sync(record, {"photo_url": SHEET_PHOTO, "name": "Nitasha"})
    assert record.photo_url == SHEET_PHOTO


async def test_a_photo_can_still_be_set_on_a_record_that_has_none():
    record = _Record(photo_url=None, name="Nitasha")
    _apply_sync(record, {"photo_url": SHEET_PHOTO, "name": "Nitasha"})
    assert record.photo_url == SHEET_PHOTO


async def test_other_fields_are_still_cleared_by_a_blank_cell():
    """Only the protected fields survive a blank; the rest follow the sheet."""
    record = _Record(photo_url=CRM_PHOTO, ao="Panchkula")
    _apply_sync(record, {"photo_url": "", "ao": ""})
    assert record.photo_url == CRM_PHOTO
    assert record.ao is None


async def test_a_blank_on_an_empty_record_reports_no_change():
    """Protecting the field must not make the sync think something changed."""
    record = _Record(photo_url=None)
    assert _apply_sync(record, {"photo_url": ""}) is False


async def test_the_protected_set_is_deliberate():
    """A reminder to think before widening this — the sheet is the truth."""
    assert _KEEP_IF_SHEET_BLANK == {"photo_url"}
