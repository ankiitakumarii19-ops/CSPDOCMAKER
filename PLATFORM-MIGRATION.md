# CSPdocMaker → configurable multi-tenant platform

**Pre-implementation analysis.** 2 October 2026. No code has been changed
for this document.

Section 19 of the brief requires this inspection before any modification.
What follows is measured from the running system, not recalled.

---

## 1. Current architecture map

```
                       Google Sheets                  Zoho CRM
                   (CSPDATA, Authorization)     (sbi_kiosk, Leads)
                             |                          |
                     csp_gsheet_service          zoho_client
                   google_sheets_service      csp_photo_service
                             |                          |
                             +-----------+--------------+
                                         |
   Celery beat ──> workers/  ──>  services/  <──  routers/  <──  Next.js
   (3 tasks)       4 files        26 files        7 files        7 pages
                                         |
                                  SQLAlchemy async
                                         |
                                  PostgreSQL 16
```

| Layer | Files | Lines |
|---|---|---|
| `app/services` | 26 | 6,237 |
| `app/routers` | 7 | 2,149 |
| `app/models` | 17 | 1,219 |
| `app/workers` | 4 | 607 |
| `app/schemas` | 7 | 387 |
| `frontend/app` | 7 | 1,491 |

**25 API endpoints. 60 `select()` calls. 446 tests.**

The service layer holds the business logic and is where almost all SBI
assumptions live. Routers are thin. That is good news for this migration:
most of the work is in one layer.

---

## 2. Current database schema

15 tables.

| Table | Cols | Rows | Purpose |
|---|---|---|---|
| `csp_records` | 40 | 3 | The entity. One row per CSP |
| `stored_documents` | 12 | 64 | DOCX + PDF bytes, versioned, checksummed |
| `processing_jobs` | 13 | 18 | Pipeline state machine |
| `document_jobs` | 7 | — | Per-document validation outcome |
| `email_jobs` | 9 | 8 | Delivery |
| `email_documents` | 4 | 4 | Which documents an email carried |
| `validation_results` | 6 | 46 | Why a document passed or failed |
| `document_templates` | 14 | 4 | **New.** Templates as data |
| `data_requests` | 13 | 0 | **New.** Tokenised CSP links |
| `rm_alerts` | 10 | 2 | What an RM must fix |
| `authorization_records` | 8 | 5 | Mirror of the auth sheet |
| `users` | 10 | 2 | Registered logins |
| `sync_runs` | 11 | 4,657 | Every sync, for diagnosis |
| `audit_logs` | 9 | **0** | Table exists, **nothing writes to it** |
| `sms_jobs` | 8 | 0 | Dead code |

### The single most important finding

```
columns named workspace / tenant / org_id / customer : 0
```

**There is no tenancy concept anywhere.** Not a column, not a scope, not a
filter. Every one of the 60 queries currently assumes one customer.

This is the defining risk of the whole programme. Tenant isolation retrofitted
late is the classic cause of cross-customer data leaks, because isolation is
only as strong as the one query somebody forgot. It must be enforced
structurally — not by remembering to add `WHERE workspace_id = ?` in 60
places.

---

## 3. Hard-coded SBI assumptions

The enum is **not** the main coupling. These six registries are — they are
Python dictionaries that a new customer would need a developer to edit.

| Where | What is hard-coded | Blocks |
|---|---|---|
| `csp_mapping.SHEET_COLUMN_TO_FIELD` | 23 sheet columns → fields | §3 data sources, §4 fields |
| `csp_mapping.FIELD_TO_CSP_ATTR` | Template field → DB column | §4 fields |
| `csp_mapping.FIELD_LABELS` | Display labels | §4 fields |
| `template_service.PLACEHOLDER_FIELDS` | Placeholder → field, per document | §6, §7 templates |
| `template_service.TEMPLATE_FILES` | Document → filename on disk | §5, §6 |
| `template_service.PHOTO_MARKERS` | Where the photo goes | §6 |
| `field_ownership.CSP_OWNED / ORG_OWNED` | Who is chased for what | §11 |
| `field_ownership.INFO_CAN_FILL` | What the directory answers | §11 |
| `info_directory.BLOCK_HEADERS` | The INFO tab's 4-block layout | §3 |
| `zoho_client.MODULE = "sbi_kiosk"` | The CRM module | §3 |
| `alert_composer._TEMPLATE` | "your SBI Kiosk CSP documents…" | §13 |

Plus the entity itself: `csp_records` is a **40-column table with named
columns** — `branch_code`, `asm_email`, `rbo_name`. A customer whose entity
is an employee, not a CSP, has nowhere to put their data.

**Already configurable** (worth noting, since it is less work than feared):
sheet IDs, tab names, sync intervals, SMTP, Zoho data centre, allowed email
domains and the photo policy are all environment settings already.

---

## 4. Document enum dependencies

Partly resolved already. Migration `f7c3b85d20a9` dropped the PostgreSQL
enum; `document_jobs`, `stored_documents` and `email_documents` now hold
plain text. All 64 existing documents were preserved.

**The database will accept any document code. The application will not.**

`DocumentType` remains a 4-value Python enum in 16 files:

| Binding | Count | Difficulty |
|---|---|---|
| `Dict[DocumentType, …]` registries | 4 | **Hard** — these become tables |
| Named members (`DocumentType.BCP`) | 9 | Medium — mostly branch logic |
| Type hints `: DocumentType` | ~16 | Easy — widen to `str` |
| `list(DocumentType)` / iteration | 2 | Easy — query the table |
| `SAEnum(...)` columns | 3 | **Done** |

The nine named-member uses are the interesting ones: they encode rules like
"the BCP prints month and year" and "the ID Card has a photo". Those are
**per-document configuration**, and each must become a column on
`document_templates`, not a branch.

---

## 5. Dashboard structure

One dashboard today: `frontend/app/admin/page.tsx`, backed by four endpoints
under `/api/admin` — `csp-metrics`, `csp-filters`, `csp-list`, `csp-list.csv`.

It covers Generated / Mailed / Pending / Failed, per document type, with
drill-down, RM and CH filters, date filter and CSV export. That is
**Dashboard A (Document Operations)** in the brief, and it substantially
exists.

**Dashboard B (CSP Data & Verification) does not exist.** Nothing today
reports verified / waiting-for-CSP / waiting-for-RM / conflicts / rejected /
WhatsApp status. The `data_requests` table can source most of it but has
no `conflict` or `rejected` state yet.

The brief says do not merge them. Today's single dashboard is A, so this is
additive — no unpicking required.

---

## 6. Authentication and authorization

**Authentication:** email + password → 6-digit OTP → JWT. Domain-restricted
to `@eko.co.in` and `@ekosupport.in`. Who may log in is decided **solely** by
the Authorization sheet, mirrored every 15 minutes into
`authorization_records`; `Status` must equal `Active`.

**Authorization:** two roles, `RM` and `ADMIN`. Enforced in the query layer
(`csp_access.py`), not in the router — an RM cannot reach another RM's CSP by
changing an ID in a request. Admin is read-only by design.

### Gaps against the brief

- **No Super Admin.** §9 requires three roles; there are two.
- **No permission model.** Roles are hard-coded booleans, not assignable
  permissions. "assign permissions" has nothing to assign.
- **Login is tied to one organisation's sheet and two email domains.** A
  second customer cannot log in at all.
- The existing rule that an *unresolved* CSP is visible to **every** RM is
  correct within one workspace and would be a **data leak across** workspaces.
  It must become workspace-scoped before tenancy ships.

---

## 7. Celery tasks

| Task | Every | Does |
|---|---|---|
| `workers.sync_csp_data` | 1 min | Read CSPData, diff into Postgres, fill from INFO |
| `workers.process_new_csps` | 3 min | Full pipeline for new CSPs, then email |
| `workers.sync_authorization` | 15 min | Mirror RMs/Admins tabs |

Each carries `expires` just under its interval. Without it, an outage left a
255-task backlog whose draining caused the connection resets that crashed the
worker four times.

**All three assume exactly one customer.** Multi-tenant scheduling means
either a per-workspace schedule or one task that iterates workspaces. The
second is simpler and keeps the beat schedule static; the first isolates a
slow customer from everyone else. Recommend starting with iteration.

---

## 8. Template generation code

`template_service.py` — fills your DOCX in place rather than rebuilding it,
which is why text boxes, VML photo frames and embedded signatures survive.

Already general, needs no change:
- run-spanning placeholder replacement
- formatting completion (size/typeface merged property-by-property)
- passport crop to 35×45 mm
- leftover-placeholder detection
- gender-driven salutation

Already configuration-driven:
- `document_template_service.py` reads placeholders out of any uploaded
  `.docx`, auto-maps them, guesses the photo marker, and edits wording
  run-by-run. **All 29 placeholders across the four supplied templates
  auto-map with no human input.**

Missing for §6:
- **versioning and publish state.** `document_templates.version` exists as a
  column but nothing increments it, and there is no draft/published
  distinction. The brief requires only a published version be used in
  production. This is the single biggest gap in the template feature.
- preview with sample data; test generate before publish.

---

## 9. Tests

**446 tests, all passing.** The distribution shows where the risk was found:

| Area | Tests |
|---|---|
| INFO directory / territory | 34 |
| Field ownership | 24 |
| Photo placement & passport size | 21 |
| Template upload / mapping / editing | 20 |
| Zoho (client + Leads lookup) | 30 |
| Sheet write-back | 17 |
| Tokenised links | 17 |
| Message composition | 16 |
| Admin dashboard | 24 |
| Templates & certificate dates | 36 |
| Everything else | ~207 |

Several tests exist specifically to **fail when a template is edited in Word**
— a shrunk photo frame, a renamed placeholder, a renamed photo marker. Those
have already caught four real regressions.

**Honest assessment against "446 must keep passing":** many assert SBI
specifics by design — that `"CSP Name"` maps to `csp_name`, that there are
exactly four documents. Once those become configuration, the *assertion* is
still valid but its *subject* moves from a constant to a seeded workspace
fixture. Expect roughly **60–80 tests to need their fixtures rewritten**,
not their intent changed. That is a rewrite, not a deletion, and is
consistent with the brief's rule.

---

## 10. Migration plan

Ordered so that each phase ships working software and the SBI workspace keeps
running throughout.

### Phase 0 — Tenancy foundation *(do first, alone)*

Add `workspace_id` to all 15 tables, seed one workspace holding today's data,
and enforce scoping **structurally** — a base query class or session-level
filter, not 60 hand-edited `WHERE` clauses. Add a test that fails if any
tenant-scoped table is queried without a workspace filter.

*Why first:* retrofitting isolation after features are built is how
cross-customer leaks happen. Nothing else should start until this holds.

*Risk:* high. Touches everything. But it is mechanical and testable.

### Phase 1 — Finish document types as data

Replace the remaining `DocumentType` enum with `document_templates` lookups.
Move the nine named-member rules (BCP prints month/year, ID Card has a photo)
to columns. Add version + publish state.

*Unblocks:* §5, §6, §7. Ends the state where an upload stores but will not
load.

### Phase 2 — Fields and mapping as data

Move the six registries from §3 into tables. The hardest part is
`csp_records`: a 40-column named table becomes an entity with configurable
attributes. Recommend a hybrid — keep the hot, queried columns physical and
put customer-defined fields in JSONB — rather than full EAV, which would make
the dashboard queries considerably worse.

*Unblocks:* §4. This is the largest single phase.

### Phase 3 — Data source abstraction

Extract the Google Sheets reader behind a `DataSource` interface, then add
CSV, Excel, Postgres and MySQL. The normalisation layer already exists in
spirit — `map_sheet_row()` is the seam.

*Unblocks:* §3.

### Phase 4 — Roles, permissions, audit

Add Super Admin, an assignable permission model, and make `audit_logs`
actually written to. The table and its indexes exist and are well shaped;
**nothing writes to it today.**

*Unblocks:* §9, §16.

### Phase 5 — Verification workflow and Dashboard B

The CSP page, WhatsApp sending, conflict and rejection states, and the second
dashboard.

*Unblocks:* §10, §11, §12, §13.

### Phase 6 — Agents

Only after the configuration surface exists, because every agent in §14 acts
*on* configuration. Building them earlier means building against a moving
target.

---

## Judgement

Three things worth saying plainly.

**The enum is not the hard part.** It reads like the blocker but is a few
days' work. The hard parts are tenancy (Phase 0) and turning a 40-column
`csp_records` into configurable fields (Phase 2). Those two carry most of the
risk in the programme.

**Phase 0 must not be deferred.** It is tempting to build visible features
first and add tenancy later. Every system that does this leaks data between
customers eventually, because isolation enforced by discipline fails the
first time someone writes a query in a hurry.

**The brief is right that the pipeline should be preserved.** Having worked
through it, the deterministic core — generation, validation, PDF, storage,
email — is the most valuable and most proven part of this codebase, and it is
already largely entity-agnostic. It needs configuration fed into it, not
rewriting.

Nothing here has been implemented. Say which phase to start and I will begin
with Phase 0 unless you direct otherwise.
