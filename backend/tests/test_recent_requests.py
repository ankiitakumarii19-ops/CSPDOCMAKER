"""GET /api/workflows/recent — an RM's own request history.

The rule that matters here is scope: an RM sees the requests they made and
nobody else's. The route is also registered above /{job_id}, so this pins
that "recent" is not read as a job id.
"""

import pytest

from app.models.csp_record import CSPRecord
from app.models.enums import AccountStatus, JobState, UserRole, WorkflowType
from app.models.processing_job import ProcessingJob
from app.models.user import User
from app.services import jwt_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

MINE = "rm.mine@eko.co.in"
THEIRS = "rm.theirs@eko.co.in"


def _headers(email: str, role: UserRole = UserRole.RM) -> dict:
    token = jwt_service.create_access_token(
        {"sub": email, "role": role.value, "name": email.split("@")[0]})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def history(db):
    """Three requests by one RM, one by another."""
    users = {}
    for email in (MINE, THEIRS):
        user = User(email=email, name=email.split("@")[0], mobile="9876543210",
                    role=UserRole.RM, account_status=AccountStatus.ACTIVE,
                    password_hash="x")
        db.add(user)
        users[email] = user
    db.add(CSPRecord(csp_id="R-CSP-1", source_row_identifier="R-CSP-1",
                     name="Recent Csp"))
    await db.flush()

    for index in range(3):
        db.add(ProcessingJob(
            job_id=f"JOB-MINE-{index}", csp_id="R-CSP-1",
            workflow_type=WorkflowType.EXISTING_CSP,
            current_state=JobState.EMAIL_SENT,
            requested_by=users[MINE].id,
        ))
    db.add(ProcessingJob(
        job_id="JOB-THEIRS-0", csp_id="R-CSP-1",
        workflow_type=WorkflowType.EXISTING_CSP,
        current_state=JobState.EMAIL_SENT,
        requested_by=users[THEIRS].id,
    ))
    await db.commit()


async def test_an_rm_sees_only_their_own_requests(client, history):
    body = (await client.get("/api/workflows/recent",
                             headers=_headers(MINE))).json()
    assert body["total"] == 3
    assert all(r["job_id"].startswith("JOB-MINE-") for r in body["requests"])


async def test_another_rms_requests_are_not_visible(client, history):
    body = (await client.get("/api/workflows/recent",
                             headers=_headers(THEIRS))).json()
    assert [r["job_id"] for r in body["requests"]] == ["JOB-THEIRS-0"]


async def test_the_csp_name_comes_back_with_each_row(client, history):
    body = (await client.get("/api/workflows/recent",
                             headers=_headers(MINE))).json()
    assert {r["csp_name"] for r in body["requests"]} == {"Recent Csp"}


async def test_recent_is_not_mistaken_for_a_job_id(client, history):
    """The route order is what makes this work; a 404 would mean it broke."""
    r = await client.get("/api/workflows/recent", headers=_headers(MINE))
    assert r.status_code == 200
    assert "requests" in r.json()


async def test_it_pages(client, history):
    first = (await client.get("/api/workflows/recent?limit=2&page=1",
                              headers=_headers(MINE))).json()
    second = (await client.get("/api/workflows/recent?limit=2&page=2",
                               headers=_headers(MINE))).json()
    assert first["pages"] == 2
    assert len(first["requests"]) == 2 and len(second["requests"]) == 1
    ids = {r["job_id"] for r in first["requests"] + second["requests"]}
    assert len(ids) == 3


async def test_page_zero_is_rejected(client, history):
    r = await client.get("/api/workflows/recent?page=0", headers=_headers(MINE))
    assert r.status_code == 400


async def test_an_rm_with_no_history_gets_an_empty_list(client, db):
    email = "rm.empty@eko.co.in"
    db.add(User(email=email, name="Empty", mobile="9876543210",
                role=UserRole.RM, account_status=AccountStatus.ACTIVE,
                password_hash="x"))
    await db.commit()
    body = (await client.get("/api/workflows/recent",
                             headers=_headers(email))).json()
    assert body == {"total": 0, "page": 1, "page_size": 10, "pages": 1,
                    "requests": []}


async def test_it_needs_a_token(client):
    r = await client.get("/api/workflows/recent")
    assert r.status_code in (401, 403)
