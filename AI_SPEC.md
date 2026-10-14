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

**There is no LLM in any production path.** Generation, validation, photo
processing and every "agent" are deterministic code. See §3, decision D1.

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
| D1 | **No LLM in production paths.** Validation is deterministic; the AI layer exists but is off (`AI_PROVIDER` unused; `openai` package unused). | Official documents must be exactly right and reproducible. |
| D2 | **FastAPI + SQLAlchemy (async) + PostgreSQL; Celery + Redis** for scheduled work. Next.js 16 / React 19 front end. | Already in place and proven; Postgres holds the documents themselves. |
| D3 | **Google Sheet is the source of truth** for CSP data; synced every minute, field-level diff. Tabs `KOData`, `SUBKOData`, `INFO`; Authorization sheet tabs `RMs`, `Admins`, `SuperAdmins`. | The business works in the sheet. |
| D4 | **Documents from the supplied Word templates** (python-docx), **PDF via LibreOffice headless** on Windows and Linux. | One renderer everywhere. LibreOffice reserves 3.19 mm inside a cell; the photo is pulled left to compensate (`_LIBREOFFICE_CELL_OFFSET_TWIPS`). |
| D5 | **The PDF is stored permanently in Postgres**, versioned, SHA-256 checksummed. The DOCX is only a working file (template → DOCX → LibreOffice → PDF) and is deleted once its PDF is stored (changed 12 Oct 2026, No. 87; it used to be kept too). Photos: working files in `generated_documents/photos`, and kept in the `csp_photos` table (original + passport version, No. 89). Shown in the CSP sheet's Photo column automatically (No. 91): `=IMAGE(private 1-day link)` turned into an in-cell picture by `deploy/sheet-photo-script.gs`; the sync never reads that column. When the app has **no** photo for a CSP, it takes the picture in that CSP's Photo cell (No. 99, `sheet_photo_reader.py`): the Sheets API returns pictures as empty, so the sheet is exported as .xlsx through the Drive API and each picture is matched to its row's CSP Code. Order: the app's own photo → the sheet → the CRM (the CRM only in background runs, too slow for an RM's request). A Photo cell with two pictures is not used. Every photo (sheet, RM upload, CSP's own form) enters through `photo_intake.accept` (No. 102): it becomes the photo, the passport version is made, both are filed; a job every `SHEET_PHOTO_MINUTES` (15) takes sheet pictures for CSPs without a photo. Screens show the passport version via `GET /api/csps/{id}/photo` (fetched with the token; a plain <img> sends none). | No document a CSP received is ever lost or overwritten; the PDF is what they receive. |
| D6 | **Certificate date = the day the document is made**, always. | Decided 11 Oct 2026. |
| D7 | **The RM fills nothing.** Missing details keep a request PENDING_DATA and are asked of the CSP; INFO fills organisation fields. | Decided 11 Oct 2026. |
| D8 | **Photos: deterministic, local, real face.** Find face (OpenCV YuNet) → level → cut out (rembg `u2net_human_seg`) → white → passport framing → light touch-up. 35 × 45 mm. AI portrait code (Cloudflare/Gemini) exists but is **off**. | User chose free + real over generative (12 Oct 2026). |
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
- **External calls:** `telemetry.external_call(service, op, attempt, max_attempts)` around Google Sheets (patched once at `HttpRequest.execute`), Zoho, SMTP, the WhatsApp platform, LibreOffice, Gemini/Cloudflare (switched off). Failures are classified: timeout, connection, auth, rate_limit, server, client, malformed, empty, schema, unknown. Retryable = timeout, connection, rate_limit, server (logged WARNING while a retry remains, ERROR otherwise).
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

No production path calls an LLM (D1). Any LLM call that is added — including an eval judge — must be wrapped in `telemetry.external_call` and record `input_tokens`, `output_tokens`, latency, temperature and the raw response on its span before it ships.

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
| 14 Oct 2026 | D5: every stored PDF also written to DOCUMENTS_ARCHIVE_DIR/<CSP code>/<Document> v<n>.pdf (server: ../CSP_Documents, i.e. /home/Ankita/CSP_Documents, beside the app folder); a copy, never the record; catch-up job every 15 min (No. 105) |
| 14 Oct 2026 | Roles (No. 104): Database = RM+Admin+Super Admin (all CSPs, read-only); Sheets = RM+Admin edit CSP tabs only, Super Admin everything; Agents and Access = Super Admin only; Messaging and Templates = Admin+Super Admin |
