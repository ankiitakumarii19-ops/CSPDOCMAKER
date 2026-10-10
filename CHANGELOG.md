# CSPdocMaker — what was built, and when

A date-by-date record of the project from its first commit-less day to
6 October 2026.

**How this was reconstructed.** The repository has no git history — nothing
has ever been committed — so this is assembled from file modification
times, the 18 Alembic migrations, and the database itself (sync runs, agent
runs, stored documents) — and, from 5 October on, from the work itself as
it happened. That evidence is good for *when* something
appeared and reliable for *what* a file contains, but a file edited later
carries the later date, so a few items may sit a day after they were first
written. Where a date is inferred rather than recorded, it says so.

Making the first git commit would remove this guesswork permanently, and it
is still the single most valuable half-hour available to this project.

---

## Where it stands today

| | |
|---|---|
| Tests | **748**, all passing |
| API endpoints | 74 |
| Database | 26 tables, 18 migrations |
| Source | ~34,200 lines across backend, frontend and tests |
| CSP records | 8 |
| Documents generated and stored | 64 |
| Sheet syncs run | 5,800+ |

---

## September

### 11 Sep — first files
The earliest files in the tree: `models/sms_job.py`,
`models/validation_result.py`, and the worker package. An SMS path was
imagined at this point and never built; the `sms_jobs` table still exists
with zero rows.

### 18 Sep — skeleton
Router and service packages created. `jwt_service.py` — token issuing and
verification, the first piece of authentication.

### 19 Sep — the database exists
**Migration 1: `af39c78429f2_initial_schema`**, recorded 15:37. The first
real schema. `docker-compose.yml` written the same day: Postgres on port
5433 and Redis, which is still how the system runs.

### 22 Sep — Celery, and the first schema correction
`README.md`. **Migration 2: `b7d2e4a91c03_fix_csp_columns_and_document_type_enum`**
— the CSP columns and the document-type enum were wrong on the first pass
and were corrected here. First test file: `test_celery_config.py`.

### 23 Sep — the sheets become the source of truth
Three migrations in one day:

- `12a52cf9d205_csp_canonical_fields_from_csp_sheet` (13:43) — the CSP
  record reshaped around the columns the Google Sheet actually has.
- `35b92a20d9d7_dc_contact_columns` (14:28)
- `774a9b5ba15c_sync_runs_and_csp_origin_rm_resolution` (14:29) — sync runs
  become a recorded thing, and a CSP gains an origin and an RM resolution.

`document_router.py` and the Authorization-sheet test.

### 24 Sep — documents get stored, and RMs get resolved
- **`34687b6e26c0_stored_documents_pdf_and_docx_in_`** (09:47) — the
  decision to keep both the DOCX and the PDF **in Postgres** rather than on
  disk. Every one of the 64 documents held today lives because of this.
- **`a89eedf44aea_job_state_failed_pdf_conversion`** (09:53) — a failed PDF
  conversion becomes a state a job can be in, rather than an exception.
- `pdf_service.py` — headless LibreOffice conversion.
- `rm_resolution.py` — working out which RM owns a CSP.
- `.gitignore` — credentials, `.env`, service-account JSON and real CSP
  sample data excluded. It has held ever since; nothing secret has ever
  been stageable.
- Four test files, including `test_csp_access.py` — the first access-control
  tests.

### 25 Sep — alerting
**`a95824a7332b_rm_alerts`** (14:46). `test_zoho_client.py`. The first
Zoho CRM work.

### 27 Sep — `alert_service.py`
Deciding who to tell when something is missing.

### 28 Sep — authentication, email, and the first screens
A large day. **`6710620488c9_email_documents_and_csp_circle_head`** (08:23).

- `email_service.py` — SMTP delivery.
- `otp_service.py` — the one-time code that login requires.
- `workflow_router.py`.
- **Nine test files at once**: OTP delivery, password reset, allowed
  domains, notification safety, admin drill-down, the info directory, the
  template service, recent requests, email documents.
- **The front end begins**: `layout.tsx`, `page.tsx`, the signup page,
  `BrandLogo.tsx`, and the session and theme hooks.

`.env.example` written the same day.

### 29 Sep – 30 Sep
No file changes recorded.

---

## October

### 1 Oct — photographs, and the CSP's own form
- `photo_extraction.py` and `csp_photo_service.py` — pulling a CSP's
  photograph out of the KYC documents held in Zoho, using face detection to
  find the photo region on the page.
- `zoho_client.py` — Zoho CRM, read-only by scope. A write from this
  system is rejected by Zoho itself, not merely avoided in code.
- `info_directory.py` — the INFO sheet, from which a district settles the
  DC, LHO and several contacts at once.
- **`c3f1a7e82b40_csp_owned_gender_and_bank_contacts`** (15:31) — gender
  arrives, which is what makes the Mr./Mrs. salutation possible.
- **`d8b4e1c06f73_data_requests`** (17:47) — the tokenised one-time link a
  CSP uses to confirm their own details.
- `data_request_service.py` — SHA-256 hashed tokens, single use, seven-day
  expiry, and the same answer for a wrong token, an expired one and a used
  one so the link cannot be probed.
- Five test files.
- **The passport-photo rule**: templates backed up to
  `reference/original-templates/pre-passport-fix/` before the photo frames
  were resized to a true 35 × 45 mm.

### 2 Oct — the platform day
By far the largest day in the project: **44 backend files, 15 test files,
5 front-end files, and 5 migrations.** This is the day CSPdocMaker stopped
being one bank's script.

**Migrations, in order:**

| Time | Migration | What it introduced |
|---|---|---|
| 00:21 | `e5a9c2d41f88_documents_the_csp_already_holds` | Asking a CSP which documents they already have |
| 01:05 | `f7c3b85d20a9_document_templates_as_data` | Templates move from code into the database — uploadable |
| 11:59 | `a1d6f0b39c45_super_admin_role` | A third role, distinct from Admin |
| 13:59 | `b2e8c4a71d30_workspaces` | **Multi-tenancy** |
| 14:42 | `c9f2a570e81b_dashboards` | Dashboards become configurable |
| 17:10 | `d4e7b1983fa2_messaging_and_agents` | Channels, templates, and the six agents |
| 19:10 | `e8c04b2719d6_auto_enrol_an_existing_csp` | An existing CSP handed to the automation |

**What came with them:**

- **Workspace isolation** — `workspace_runner.py` and the scoping that
  applies a filter underneath *every* query the application makes, rather
  than in each endpoint where one forgotten line leaks a customer's data.
  `test_workspace_isolation.py` proves a record from one workspace is
  invisible to another even when asked for by primary key.
- **Documents as data** — `document_registry.py` and
  `document_template_service.py`. Upload a `.docx`, its placeholders are
  read out of the file and matched automatically.
- **Roles** — `csp_access.py`, `test_role_separation.py`,
  `test_super_admin_roles.py`. RM sees only their own CSPs; Admin
  configures; Super Admin decides who gets in.
- **The six agents** — `agent_registry.py`, `agent_runner.py`: Setup,
  Data, Verification, Document, Communication, Monitoring.
- **Sheet write-back** — `sheet_writeback_service.py`, so a CSP's answer
  reaches the Google Sheet.
- **Front end** — the admin console gains Document Templates, Access
  Control and the Dashboard Builder; the login page; and the public
  tokenised CSP form at `csp/details/[token]`.
- `PROJECT-STATUS.md` and `PLATFORM-MIGRATION.md` written.
- Templates edited: CSP Certificate and Training Certificate.

### 3 Oct — messages actually send
- `message_sender.py` — the piece that was missing. Everything else
  existed; nothing had ever been put on the wire.
- `agents.py` — the six agent implementations, with a 25-person threshold
  above which the Communication Agent proposes and sends nothing.
- `messaging_router.py`, and the Agents and Messaging admin screens.
- The admin and RM pages reworked.
- **The unreachable-link guard**: a message whose link nobody outside the
  machine could open is refused before it is sent. This stopped a real
  email to a real CSP the same day.

### 4 Oct — security hardening
- `APP_DEBUG=false`, `APP_ENV=production` — the API docs at `/docs` now
  return 404.
- `login_throttle.py` — the login had **no limit at all**. Two counters:
  eight failures per account, twenty per source address, both expiring
  after fifteen minutes so nobody can be locked out permanently. Verified
  live: eight 401s, then 429.
- CORS widened to the public app URL.

### 5 Oct — a long day of corrections
**Documents**

- **The ID Card photograph was being clipped.** The frame and the
  photograph were both exactly 35 × 45 mm, and the caption carried 50 pt of
  space before it — which centred the words "Affix Passport Size Photo" in
  the empty box, and cut the face off at the eyes once a real photograph
  replaced them. Fixed by clearing the frame's padding at generation time;
  three regression tests added, each verified to fail without the fix.
- **LibreOffice reserves 3.2 mm inside a text box** whatever the file asks
  for, so a 35 mm photo could never fit a 35 mm frame. Measured, not
  guessed. The frame is now widened and shifted so the photograph lands on
  exactly the rectangle the template drew for it.
- **Addresses stopped repeating themselves.** The CSP Certificate prints
  the address and then the district and state beside it, and people write
  their address ending with both. `Samvapur belghat gorakhpur up 273404,
  DIST- Gorakhpur, Uttar Pradesh` now reads `Samvapur Belghat, DIST-
  Gorakhpur, Uttar Pradesh`. Only the tail is trimmed, and only on a
  template that prints those fields separately — the ID Card and BCP keep
  the full address, because for them it is the only copy there is.
- **Title casing** — names, places and addresses are capitalised word by
  word on the way out. `ANIRUDH KUMAR KUSHWAHA` prints as `Anirudh Kumar
  Kushwaha`. Codes, numbers and email addresses are untouched, and the
  stored record keeps exactly what was typed.
- **A validator bug caught in passing**: the filler trimmed the address and
  the validator did not, so validation would have hunted for text the
  document was never going to contain. Both now go through one function.
- **The ID Card restyled** — a rule under every row instead of three
  hand-placed line shapes, Arial instead of a heavy substituted serif, and
  a hanging indent so a wrapped address lines up under itself.
- **The ID Card page became card-sized** — 131 × 131 mm instead of an A4
  sheet with a card in the corner.

**Dashboards**

- **Every number is now clickable.** `metric_drilldown.py` — 14 metrics
  open into the records behind them, and the completeness metrics name the
  blank fields rather than just counting them.
- **"Documents CSPs already hold" was hiding something.** It showed only
  the Yes count, so "CSP ID Card — 0" read as *nobody has one* when the
  truth was *one said they do not and two were never asked*. It now shows
  Yes, No and Not answered, and the three always account for every CSP.

**Operations**

- Docker's engine failed with a 500 on every call, taking Postgres with it.
  Restarted; all data intact.
- The public tunnel was stopped and `PUBLIC_APP_URL` returned to localhost,
  because it still pointed at a dead tunnel — and the unreachable-link
  guard only refuses *localhost*, so a dead public URL would have sailed
  straight through it.

### 6 Oct — the agents start running, and the sheets become editable

**The agents were never running.** Built, registered, enabled, and shown on
screen as "Running — every 15 min" since 2 October, with no Celery task and
no schedule entry. They had run three times, each a person clicking "Run
now".

- `agent_worker.py` and a beat schedule **generated from the registry**, so
  an agent is scheduled by being registered and the screen cannot claim an
  interval nothing honours.
- A second trap, caught on a pre-flight run: the `@performs` decorators
  were imported only by the agent *router*, so the API process had them and
  the Celery worker did not. Every scheduled run would have recorded "has
  no implementation yet" and done nothing — worse than not running, because
  the screen would have looked right.
- Confirmed live: beat sent `agent-document`, the worker ran it, and the
  database shows scheduled runs 3 minutes apart.
- Their first real run found 8 incomplete records, 1 record belonging to no
  RM, and 17 failed syncs from the Docker outage. **Nothing was sent to any
  CSP** — the unreachable-link guard refused all six attempts.

**Sheets, for a Super Admin** — a new screen to view, edit, add and delete
rows in any sheet the system reads, written straight to the Google Sheet.

- Tabs are read live, so one created or deleted in Google Sheets appears or
  disappears with nothing to configure.
- Rows are addressed by their **real spreadsheet row number**, not a
  position in a list that moves under a concurrent edit.
- The header row cannot be edited or deleted: it names the columns the
  whole system matches on.
- Deleting returns what it deleted, because there is no undo.
- Verified by a full round-trip against the live API on a scratch tab,
  which was then removed.

**Performance** — the Sheets screen took 3.9 seconds: six round trips to
Google to describe three sources, because the title and tabs were fetched
separately and two sources share one spreadsheet. One call per distinct
spreadsheet now: **~1.0s**. A parallel version was tried and reverted — the
Google client is not thread-safe and returned empty tab lists.

**Photographs**

- The five supplied photographs were attached to their records and written
  into the sheet's Photo column, so the automatic pipeline finds them. The
  `#ERROR!` in row 5 was overwriting one every minute until it was replaced.
- The Photo column now renders as an **image** rather than a path. The path
  comes from a sheet cell anyone can edit, so it is checked to be inside the
  photos directory before anything is opened; five traversal attempts are
  tested.

**Field ownership changed twice**

- **Branch Name and Branch Code moved from the RM to the CSP.** A CSP knows
  which branch they are attached to — it is on their own paperwork. Asking
  an RM to look it up for every CSP was chasing the wrong person.
- **Branch Contact and RBO Contact are now chased from nobody.** Verified
  first: neither appears on any template and neither is in
  `FIELD_TO_CSP_ATTR`, so no document could carry them. Still read and
  stored; simply never asked for.
- Effect: the fields nobody can derive went from **six to two** (AO and RBO
  Name), and seven of the eight live CSPs now have nothing outstanding for
  an RM at all.

**Sign-in history** — every login is now recorded in `audit_logs`, a table
that had existed since the initial schema with **zero rows**. The Access
screen's date is clickable and opens day, date, time, role and source for
every recorded sign-in. Super Admin only. It cannot show history from
before it existed, and says so rather than implying an account was unused.

**Access tightening** — the agents' run history is Super Admin only. An
Admin runs the agents and reads their findings; the history records who
operated the workspace and what failed, which belongs with access control.

**Interface fixes**

- "CSPdocMaker" was clipped by the sidebar's edge — the 36px logo plus the
  title needed more than `w-56` left after its padding.
- Clicking a number on any dashboard now scrolls its list into view, so the
  answer is not below the fold. In the shared component, so it applies to
  every dashboard built later.
- The Sheets screen lists one card per spreadsheet rather than one per
  source, which was showing the same file and tabs twice.
- Empty cells are blank rather than showing an em-dash.

**This documentation** — `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, and a
`SKILL.md` for each of the six agents, generated from the registry so they
cannot drift from the code.

---

## Known gaps

Recorded here so they are not mistaken for oversights.

| Gap | State |
|---|---|
| **Version control** | Zero commits. The project exists only on one laptop. |
| **Backups** | None. The only copy of 64 documents and all CSP data is one Docker volume — which failed once on 5 Oct. |
| **The six agents** | Built, enabled, shown as "Running" in the UI — but there is no Celery task and no schedule for them. They have not run since 2 Oct, and those runs were manual clicks. |
| **WhatsApp** | A channel can be configured; no sender is written. It says so rather than failing quietly. |
| **Audit log** | Table exists, correctly indexed, **zero rows**. Nothing writes to it. |
| **Deployment** | Runs on Windows; the target is Linux. No container image, no CI. |
| **Seven fields** | DC, DC email, DC contact, LHO, RM, branch contact and RBO contact are collected and chased but cannot be printed on any document. |
| **Data volume** | Every one of the 5,800 syncs read 8 rows or fewer. Nothing has been tested at scale. |
| **Message wording** | Signed "— Team", with no mention of EKO or SBI. |
