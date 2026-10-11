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
| D5 | **DOCX and PDF stored permanently in Postgres**, versioned, SHA-256 checksummed. | No document is ever lost or overwritten. |
| D6 | **Certificate date = the day the document is made**, always. | Decided 11 Oct 2026. |
| D7 | **The RM fills nothing.** Missing details keep a request PENDING_DATA and are asked of the CSP; INFO fills organisation fields. | Decided 11 Oct 2026. |
| D8 | **Photos: deterministic, local, real face.** Find face (OpenCV YuNet) → level → cut out (rembg `u2net_human_seg`) → white → passport framing → light touch-up. 35 × 45 mm. AI portrait code (Cloudflare/Gemini) exists but is **off**. | User chose free + real over generative (12 Oct 2026). |
| D9 | **Zoho CRM read-only**, search both `sbi_kiosk` and `Leads`; code AND phone must match. | KYC packs live on Leads. |
| D10 | **WhatsApp through Eko's internal WhatsApp Bulk Sender** (hosted MCP connection, Meta Cloud API underneath). No key stored in this app. Nothing is sent while `PUBLIC_APP_URL` is localhost. | Eko's own platform handles Meta approval (12 Oct 2026). |
| D11 | **Workspaces**: Super Admins create workspaces; membership per workspace re-checked on every request. Sheet-reading jobs run only for the Eko workspace. | Decided 11 Oct 2026. |
| D12 | **Roles**: Super Admin (configures, adds people), Admin (watches only), RM (searches, chooses documents). | Confirmed. |
| D13 | **Secrets only in environment variables** (`backend/.env`, never committed; `.env.example` lists names only). | Security. |

---

## 4. Telemetry specification

### 4.1 Today (verified 12 Oct 2026)

| Where | What is recorded |
|---|---|
| Console (Python `logging`, text) | Module-level log lines from API and workers. **No run/request/operation IDs. No file.** |
| `sync_runs` table | Each sheet/authorisation sync: status, counts, error. |
| `agent_runs` / `agent_findings` | Each agent run: status, summary, error text (no traceback). |
| `processing_jobs` + `validation_results` | Each document request's state and validation issues. |
| `email_jobs` / `email_documents` | Each email and the documents it carried. |
| `audit_logs` | Sign-ins only. |
| API global handler (`main.py`) | Unhandled errors: full traceback in the log; the user sees a generic message (**no error ID** — gap). |

Known gaps: two silent `except: pass` sites (`agent_runner.py`, `document_template_service.py`); 61 broad `except Exception` sites not yet audited; no shared correlation ID; external calls not timed or classified.

### 4.2 Planned (awaiting approval — PROJECT-REGISTER No. 79)

- Structured JSON logs with `run_id`, `request_id`, `operation_id`, component, function, duration, status, retry count.
- One trace per external call (Google Sheets, Zoho, SMTP, WhatsApp platform, LibreOffice): service, operation, duration, outcome class (timeout / connection / auth / rate-limit / server / malformed / empty).
- Error responses carry an error ID the user can quote; full detail stays in logs.
- A run-history view (steps → failure → retry → end) for debugging.
- **Never logged:** passwords, tokens, API keys, OTPs, full phone numbers, email addresses, photos, document contents.

LLM telemetry (tokens, temperature, raw response): **not applicable** while D1 holds. If an LLM is introduced, its calls must be traced with those fields before it ships.

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
