# AI_SPEC.md — CSPdocMaker engineering memory

The single source of truth for how this system is built and why. Any AI
session working on this repository reads this first and keeps to it.
**Update it after every major change that is deployed** (see the last section).

- Created: 12 Oct 2026
- Request history: `PROJECT-REGISTER.md` (every request, numbered)
- Longer design notes: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`

---

## 1. What the system is

CSPdocMaker issues four official documents to SBI Kiosk agents (CSPs) and
sends them: **CSP ID Card, Appointment Letter, Training Certificate, BCP**.
New agents are detected in a Google Sheet and handled automatically; for
existing agents an RM chooses the documents. Missing details are asked of the
agent; documents are generated from Word templates, validated, converted to
PDF, stored, emailed and announced on WhatsApp.

**There is no LLM anywhere in the system** (the chat's was removed 19 Oct 2026).
Generation, validation, photo processing, the chat and every "agent" are
deterministic code. See §3, decision D1.

---

## 2. Core terms (as used in THIS project)

| Term | Meaning here |
|---|---|
| **CSP / agent (business)** | An SBI Kiosk Customer Service Point — the person documents are issued to. In conversation "agent" usually means this. |
| **KO / Sub-KO** | A CSP whose code has 8 characters (KO) or 9–10 (Sub-KO, = KO code + 1–2). Decided by length only (`ko_level.py`). Sub-KOs never get a BCP. |
| **Agent (software)** | One of six **deterministic scheduled jobs** (Setup, Data, Verification, Document, Communication, Monitoring) in `agent_registry.py` / `agents.py`, run by Celery. **Not an AI model.** They check, propose and send; each run is an `agent_runs` row. |
| **Pipeline** | The fixed document path: detect → fill gaps (INFO) → find photo → validate data → generate → validate document → PDF → store → email → WhatsApp. One path for automatic and RM-started work. |
| **Run** | One execution of a scheduled job or agent (sync run, agent run, worker task). |
| **Processing job** | One document request for one CSP (`processing_jobs`), with a state machine (`JobState`), incl. `PENDING_DATA` while waiting for the CSP. |
| **Workspace** | A tenant. Every row carries `workspace_id`; one filter scopes every query (`workspace_context.py`). The original is "Eko SBI Kiosk CSP". |
| **Baseline / new CSP** | Rows present at the first sync are baseline (never auto-sent); rows added later are new (automatic). |
| **Data request** | A one-time, hashed, 7-day link asking a CSP for missing details. |
| **INFO tab** | Eko's org chart in the CSP spreadsheet; fills DC/ASM/RM/LHO/State by territory. |
| **Studio photo** | The agent's photo with white background and passport framing, made locally (`studio_photo.py`), always printed 35 × 45 mm. |
| **Template (document)** | A Word file with `"Placeholder"` fields and a photo cell. |
| **Template (WhatsApp)** | A Meta-approved message wording with `{{1}}` slots, managed by Eko's WhatsApp platform. |
| **Context window** | **Not applicable** — no LLM is called. If an LLM is ever added, define its context budget here first. |

---

## 3. Architecture decisions (and why)

| ID | Decision | Why |
|---|---|---|
| D1 | **No LLM anywhere** (since 19 Oct 2026, No. 116 — the chat's Cloudflare model and the switched-off Cloudflare/Gemini photo-portrait code were removed; the old unused `AI_*` settings too). The ask-anything chat (`assistant_engine.py` rules → `assistant_tools.py` lookups → `assistant_router.py`) reads a question by fixed keyword rules (English/Hinglish/Hindi) and answers from the records; process questions come from the **Knowledge Base** (`knowledge_entries`, kept by Admins/Super Admins on Admin → Knowledge Base; matched by `knowledge_service.rank`: filler words dropped, rare words weighted, Dice overlap per phrasing + keyword bonus; answer ≥ 0.5, "did you mean" ≥ 0.25). Unanswered questions are counted in `knowledge_misses` for an Admin. Same question → same answer. Lookups apply `csp_access` (RMs: own + unresolved CSPs). A message is only ever a DRAFT (Redis, `ASSISTANT_DRAFT_MINUTES`): fixed wordings for photo / missing details / documents-sent (the last only once the documents were emailed), otherwise the person's own words; a Send press sends it once (GETDEL), re-checking access, writing `audit_logs` action `assistant_message`. WhatsApp goes in one fixed wording with `{name}`/`{message}` so Meta approves it once. **Workspace setup through the chat (No. 117):** `workspace_setup.py` builds the Owner's checklist (team, records sheet opened live, CSP records, document templates, message wordings, channel, Communication agent, Knowledge Base, PUBLIC_APP_URL) as done/todo/problem/blocked, adds built-in setup how-to answers (matched with the Knowledge Base, for Admins and Owners), and lets the chat PROPOSE setup actions (add member, connect sheet, create wordings, add email channel, enable agent) kept in Redis `assistant:action:*`; `POST /api/assistant/actions/{id}/run` (super_admin, proposer only, once) runs them through the Setup screens' own router functions and audits `assistant_setup_action`. Known gap it reports as Blocked: CSP records sync only for the Eko workspace. | Answers must be exactly right and reproducible, and cost nothing per question (user, 19 Oct 2026). |
| D2 | **FastAPI + SQLAlchemy (async) + PostgreSQL; Celery + Redis** for scheduled work. Next.js 16 / React 19 front end. | Already in place and proven; Postgres holds the documents themselves. |
| D3 | **Google Sheet is the source of truth** for CSP data; synced every minute, field-level diff. Tabs `KOData`, `SUBKOData`, `INFO`; Authorization sheet tabs `RMs`, `Admins`, `SuperAdmins`. | The business works in the sheet. |
| D4 | **Documents from the supplied Word templates** (python-docx), **PDF via LibreOffice headless** on Windows and Linux. | One renderer everywhere. LibreOffice reserves 3.19 mm inside a cell; the photo is pulled left to compensate (`_LIBREOFFICE_CELL_OFFSET_TWIPS`). |
| D5 | **The PDF is stored permanently in Postgres**, versioned, SHA-256 checksummed. The DOCX is only a working file (template → DOCX → LibreOffice → PDF) and is deleted once its PDF is stored (changed 12 Oct 2026, No. 87; it used to be kept too). Photos: working files in `generated_documents/photos`, and kept in the `csp_photos` table (original + passport version, No. 89). Shown in the CSP sheet's Photo column automatically (No. 91): `=IMAGE(private 1-day link)` turned into an in-cell picture by `deploy/sheet-photo-script.gs`; the sync never reads that column. When the app has **no** photo for a CSP, it takes the picture in that CSP's Photo cell (No. 99, `sheet_photo_reader.py`): the Sheets API returns pictures as empty, so the sheet is exported as .xlsx through the Drive API and each picture is matched to its row's CSP Code. Order: the app's own photo → the sheet → the CRM (the CRM only in background runs, too slow for an RM's request). A Photo cell with two pictures is not used. Every photo (sheet, RM upload, CSP's own form) enters through `photo_intake.accept` (No. 102): it becomes the photo, the passport version is made, both are filed; a job every `SHEET_PHOTO_MINUTES` (15) takes sheet pictures for CSPs without a photo. Screens show the passport version via `GET /api/csps/{id}/photo` (fetched with the token; a plain <img> sends none). | No document a CSP received is ever lost or overwritten; the PDF is what they receive. |
| D6 | **Certificate date = the day the document is made**, always. | Decided 11 Oct 2026. |
| D7 | **The RM fills nothing.** Missing details keep a request PENDING_DATA and are asked of the CSP; INFO fills organisation fields. | Decided 11 Oct 2026. |
| D8 | **Photos: deterministic, local, real face.** Find face (OpenCV YuNet) → level → cut out (rembg `u2net_human_seg`) → white → passport framing → light touch-up. 35 × 45 mm. The AI portrait code (Cloudflare/Gemini) and its face-similarity check were removed 19 Oct 2026 (No. 116); `face_match.py` now only finds the face. | User chose free + real over generative (12 Oct 2026). |
| D9 | **Each workspace sets its own rules** (No. 120, 19 Oct 2026) in `Workspace.settings` via `workspace_rules.py` / `PUT /api/admin/workspace-rules` (Owner; GET also Admins): `allowed_email_domains` ([] = any; unset = server ALLOWED_EMAIL_DOMAIN, so Eko is unchanged; a new workspace starts with its Owner's domain), `session_hours` (token expiry at `_issue_tokens`), `members_added_by` (owner | owner_and_admins → `access_router.member_manager`; Admins never grant/revoke Super Admins), `message_signoff` (rewrites the last "— …" line of message wordings; chat email drafts). The domain rule is applied in `workspace_service.memberships`, which sign-in, workspace selection and the per-request membership check all use. No server-wide domain gate at sign-up/login: anyone may create a workspace (user's choice). A rule locking out the workspace's own Super Admin is refused. Changes audited `workspace_rules_change`. | Different companies, different rules; one enforcement point so no path can skip it. |
| D10 | **Eko's CSPs come from two more sheets** (No. 121, 21 Oct 2026). `source_sheets.run` (worker `workers.sync_source_sheets`, every SOURCE_SHEETS_INTERVAL_MINUTES, Eko only, off without CALLING_SHEET_ID / LEAD_SHEET_ID) reads the Calling sheet (old; Terminal Status ≠ Active → hold) and Lead raw data (Remarks = LEAD_LIVE_REMARK → live, else hold), keeps `source_sheet_states` (first run = baseline: already-live CSPs are not new), appends missing codes to KOData/SUBKOData in one RAW batch (`append_rows`): Calling codes as origin `baseline`, a code that newly goes live and is not in the Calling sheet as `new` with blanks filled from Zoho Leads (`find_lead`, phone + name/branch). `csp_sync_worker` takes origin and hold from `state_for_new_record` when it creates a record. `csp_records.send_hold` is checked by new_csp_worker, pending_request_worker, workflow_router (process + confirm), csp_router.auto_issue, message_sender.ask_for_details, documents_whatsapp.notify, assistant draft + send. Existing KOData rows are never rewritten. Run it on ONE host only (shared CSPDATA sheet). | The status lives in other teams' sheets; the app must notice the change to live and never mail an inactive or pending CSP. |
| D11 | **No OCR anywhere** (No. 132, 22 Oct 2026). The Aadhaar reading of Zoho attachments (No. 123: kyc_ocr, the read_aadhaar_addresses worker, the csp_ocr_suggestions table, RapidOCR) was removed completely. A CSP's address comes from the Address tab (old CSPs), else the Zoho Lead's `Shop_Address_with_Shop_Name`, else its Business Address section (`zoho_client.lead_address`; needs a Street or Landmark; a shop box with no digit is rejected), else the CSP is asked. `Home_Address` is not used. Attachments are still read only for the photograph (csp_photo_service). | Asked by the user: "I will never need it". OCR addresses always carried misreads (10-CSP trial). |
| D12 | **Zoho before WhatsApp** (No. 124, 21 Oct 2026): `message_sender.ask_for_details` first calls `zoho_fill.fill_from_zoho` (Eko workspace only): blank email / address (Shop / Business Address, D11) / state / gender filled from the Zoho Lead's typed fields (`find_lead`), written with `sheet_writeback_service.write_values` and only then onto the record (a record-only value would be wiped by the sync). Nothing left missing → no message. Tests always run with ZOHO_* blank. | The CSP is bothered only for what Eko does not already have. |
| D13 | **Old CSPs verify on WhatsApp; every CSP email is tracked** (No. 126–127, 21 Oct 2026). `workers.verify_old_csps`: origin baseline, no hold, has mobile, never emailed (EmailJob SENT), never answered a DataRequest, not asked in 3 days → `ask_for_details(verify=True)` (sends even with nothing blank; "all your details"), VERIFY_BATCH_SIZE per VERIFY_INTERVAL_MINUTES within VERIFY_START/END_HOUR IST, stops after VERIFY_STOP_AFTER failures in a row, only where CALLING_SHEET_ID is set. `email_messages` (`email_log`): recorded in `email_service.send_documents_email` and `message_sender._send_email` (Message-ID + 1-px GIF at `/api/public/email-open/{token}.gif`); `workers.check_email_bounces` reads mailer-daemon notices by IMAP (SMTP login) across all workspaces. The CSP form page scrolls itself: `layout.tsx` is h-screen overflow-hidden. Form no longer asks DOCUMENTS_HELD. | Old CSPs' records are checked by the people they describe, without a mail; email delivery is as visible as WhatsApp. |
| D14 | **Who is asked what** (No. 128, 21 Oct 2026): the verify job selects only `source_sheet_states.imported_as = 'baseline'` codes (Calling-sheet copies), never CSPs already in CSPDATA. The CSP's form (`field_ownership.request_fields`) and asks (`data_request_service.fields_to_ask`) are the CSP's own fields plus `ASKED_FROM_CSP_WHEN_BLANK` = RBO Name; DC / ASM / RM / LHO / AO are never asked from the CSP (RM alert + INFO). AO (No. 141, 23 Oct 2026) is filled in the sync from INFO's AO block (`info_directory.find_ao`: branch, else district, only when one AO matches) and is only on the verification form (`ON_VERIFICATION_FORM` = AO, RBO Name) for checking. A CSP who has already answered a form gets the missing-data wording (`message_sender.template_for`, No. 139). DOCUMENTS_HELD is not on the form. | CSPs know their own details and RBO; not Eko's staff. AO is the bank's mapping, kept in INFO. |
| D9 | **Zoho CRM read-only**, search both `sbi_kiosk` and `Leads`; code AND phone must match. | KYC packs live on Leads. |
| D10 | **WhatsApp through Eko's internal WhatsApp Bulk Sender** (hosted MCP connection, Meta Cloud API underneath). No key stored in this app. Nothing is sent while `PUBLIC_APP_URL` is localhost. | Eko's own platform handles Meta approval (12 Oct 2026). |
| D11 | **Workspaces**: Super Admins create workspaces; membership per workspace re-checked on every request. Sheet-reading jobs run only for the Eko workspace. | Decided 11 Oct 2026. |
| D12 | **Roles**: Super Admin — everything, incl. access, sheets and acting on agents (run, on/off, approve). Admin — watches everything; may also build dashboards, edit document templates and send messages to CSPs; may not act on agents (updated 12 Oct 2026, No. 88). RM — searches, chooses documents. Enforced on the server; screens hide what a role cannot do. | Confirmed by the user 12 Oct 2026. |
| D13 | **Secrets only in environment variables** (`backend/.env`, never committed; `.env.example` lists names only). | Security. |
| D14 | **Server = Docker Compose on one Linux machine, Caddy in front** (`docker-compose.prod.yml`, `DEPLOY.md`). Caddy gets HTTPS itself and sends `/api/*` to the backend, the rest to the website. LibreOffice uses Carlito/Caladea in place of Calibri/Cambria (same letter widths). Server settings in `deploy/.env.production` (git-ignored). | One command to start or update; HTTPS without manual certificates; documents lay out as on Windows (verified 12 Oct 2026). |

---

## 4. Telemetry specification

Implemented 12 Oct 2026 (PROJECT-REGISTER No. 79). Code: `backend/app/telemetry.py`.

### 4.1 Where things are written

| File (in `backend/logs/`, or `LOG_DIR`) | What |
|---|---|
| `app.jsonl` (rotates 20 MB × 10) | One JSON object per log line, API and workers. |
| `traces.jsonl` | OpenTelemetry spans (one per step and per external call), parent/child linked. |
| `crash.log` | Interpreter-level crashes (faulthandler) and uncaught exceptions on any thread. |

Database tables (`sync_runs`, `agent_runs`, `processing_jobs`, `email_jobs`, `audit_logs`) still hold business history; `agent_runs.error` now keeps type, message and traceback.

### 4.2 Fields on every log line

`time, severity, run_id, request_id, operation_id, operation, trace_id, component, function, file, message` — plus, when relevant: `event` (start / success / failed / call_ok / call_failed / call_http_error / retry / crash / unhandled), `status`, `duration_ms`, `service`, `error_type`, `error_message`, `failure_kind`, `attempt`, `max_attempts`, `retryable`, `recovered`, `failed_function`, `failed_at`, `raised_in`, `context`, `traceback`.

- **run_id:** one per HTTP request (= the `X-Request-ID` response header = the Error ID shown to a user) and one per Celery task (= the task id).
- **Steps:** `telemetry.operation(...)` / `@telemetry.traced(...)` log `START`, then `SUCCESS in N ms` or `FAILED` with traceback, and re-raise.
- **External calls:** `telemetry.external_call(service, op, attempt, max_attempts)` around Google Sheets (patched once at `HttpRequest.execute`), Zoho, SMTP, the WhatsApp platform, LibreOffice. No AI service is called. Failures are classified: timeout, connection, auth, rate_limit, server, client, malformed, empty, schema, unknown. Retryable = timeout, connection, rate_limit, server (logged WARNING while a retry remains, ERROR otherwise).
- **User-facing errors:** an unhandled API error returns 500 with `error_id`, the failing operation and a next action; internals stay in the logs.
- **Never logged** (masked by a filter on every line): bearer tokens, JWTs, `wabs_` keys, password/token/secret/api_key/otp values, email addresses, Indian phone numbers. Photos and document contents are never logged.

### 4.3 How to inspect

```
cd backend
python scripts/show_run.py <run / request / error id>      # timeline + ERROR REPORT
python scripts/show_run.py <id> --full                     # whole tracebacks
python scripts/show_run.py --failures 10                   # latest failed runs
```

### 4.4 LLM telemetry

No part of the system calls an LLM (D1). Any LLM call that is added — including an eval judge — must be wrapped in `telemetry.external_call` and record `input_tokens`, `output_tokens`, latency, temperature and the raw response on its span before it ships.

---

## 5. Working rules for any AI session

1. **Change control:** before changing code, name the problem, the component, the files and the expected result. Smallest correct change. Explain any architectural change before making it. Report Problem / Root cause / Files / Changes / Tests / Result after.
2. **Never hide errors:** no `except: pass`, no fake success, no generic message without an error ID.
3. **Test before calling anything done:** run `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q` in `backend/` (needs Docker: Postgres + Redis). Real faces/agent data never go into tests.
4. **Secrets:** never in code, logs, commits, API responses or the front end.
5. **The user's standing rules:** screens follow the user's design — ask before changing; photos always 35 × 45 mm; ask before deleting anything; back up before database changes; record every request in `PROJECT-REGISTER.md` in plain language.

---

## 6. Keeping this file current

After every major change that is **deployed** (merged and running), update:
§3 if a decision changed, §4 if what is logged or where changed, §2 if a term
changed meaning. The AI session that makes the change reminds the user to do
this (or does it, with the user's OK).

| Date | Change |
|---|---|
| 12 Oct 2026 | Initial version |
| 12 Oct 2026 | §4 rewritten: telemetry layer implemented (No. 79) |
| 12 Oct 2026 | D14 added: server deployment (No. 86) |
| 12 Oct 2026 | D5 changed: PDF only is stored (No. 87) |
| 12 Oct 2026 | D12 updated: Admin rights (No. 88) |
| 12 Oct 2026 | D5: photos kept in the database; Database page for the Super Admin (No. 89) |
| 13 Oct 2026 | D5: photos shown in the CSP sheet automatically (No. 91) |
| 14 Oct 2026 | D5: photos read from the CSP sheet's Photo column when the app has none (No. 99) |
| 14 Oct 2026 | D5: one photo intake, sheet photos every 15 min, passport version on every screen (No. 102) |
| 14 Oct 2026 | D5: every stored PDF also written to DOCUMENTS_ARCHIVE_DIR/<CSP name> (<CSP code>)/<Document> v<n>.pdf (folder found by code; renamed, never duplicated, when the name changes — No. 106) (server: ../CSP_Documents, i.e. /home/Ankita/CSP_Documents, beside the app folder); a copy, never the record; catch-up job every 15 min (No. 105) |
| 14 Oct 2026 | Roles (No. 104): Database = RM+Admin+Super Admin (all CSPs, read-only); Sheets = RM+Admin edit CSP tabs only, Super Admin everything; Agents and Access = Super Admin only; Messaging and Templates = Admin+Super Admin |
