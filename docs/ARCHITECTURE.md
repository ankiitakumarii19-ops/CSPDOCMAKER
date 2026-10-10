# CSPdocMaker — architecture

Complete enough to rebuild the system from. Where a number appears it was
measured on the running system, not estimated.

---

## 1. The problem

A bank Customer Service Point (CSP) needs four documents:

| Document | Carries |
|---|---|
| CSP ID Card | Photo, code, name, branch. The one they carry. |
| CSP Certificate | Issued in their name, dated the day it is made |
| Training Certificate | Photo, name, branch, date |
| Business Continuity Plan (BCP) | Branch, module, RBO and ASM details |

Before this system, each was made by opening the bank's Word file,
retyping 23 fields, cropping a photograph into a frame, exporting a PDF
and writing an email — four times, for every CSP. The work is not hard. It
is repetitive and unforgiving, which means it gets skipped under pressure
and comes back as a reissue when a branch code is mistyped.

---

## 2. The shape of the system

```
Google Sheets ──► sync (60s) ──► Postgres ──► pipeline ──► PDF ──► email
     ▲                                          │
     │                                          ▼
     └──────── CSP's answers ◄── tokenised link ──┘
```

| Part | Technology |
|---|---|
| API | FastAPI (Python), async SQLAlchemy 2.0, asyncpg |
| Database | PostgreSQL 16 — including the documents themselves |
| Scheduling | Celery 5.4 + beat, Redis broker |
| Front end | Next.js 16, React 19, TypeScript, Tailwind |
| Documents | python-docx, headless LibreOffice, PyMuPDF, Pillow |
| Sources | Google Sheets API; Zoho CRM v2 (**read-only by scope**) |
| Migrations | Alembic, 18 of them |

**Documents live in Postgres**, both DOCX and PDF, not on disk. A reissue
needs no regeneration, and there is one thing to back up rather than two.

---

## 3. The data model

26 tables. The ones that matter:

| Table | Holds |
|---|---|
| `workspaces` | One customer. Every scoped table carries `workspace_id`. |
| `csp_records` | The CSPs. 40 columns, mapped from 23 sheet columns. |
| `stored_documents` | The generated DOCX and PDF bytes |
| `processing_jobs`, `document_jobs`, `email_jobs` | What was attempted, and what happened |
| `data_requests` | The tokenised links sent to CSPs |
| `data_sources` | Where a workspace's records come from |
| `document_templates` | Templates as data — uploadable, not code |
| `dashboards`, `dashboard_widgets` | Configurable screens |
| `message_channels`, `message_templates` | How and what to send |
| `agent_states`, `agent_runs`, `agent_findings` | The agents |
| `audit_logs` | Sign-ins. The only thing writing to it so far. |

### Multi-tenancy

Scoping is **not** written into each endpoint, where one forgotten line
leaks a bank's data. A `ContextVar` holds the current workspace and a
SQLAlchemy `do_orm_execute` listener adds `with_loader_criteria` to every
SELECT against any model carrying `workspace_id`. It covers async and sync
sessions alike.

Proved, not assumed: two workspaces in a real database, where a record
from one does not appear in the other's list, count, **or** a direct
lookup by primary key.

---

## 4. The pipeline

Three things run on a timer. This is the engine.

| Every | Task |
|---|---|
| 60 seconds | Read the CSP sheet. New rows become records; changed cells update them. |
| 3 minutes | Process any CSP that is new or RM-enrolled and not yet done |
| 15 minutes | Read the Authorization sheet — who may sign in |
| 3/10/15/30/60 min | The five scheduled agents |

### A new CSP, start to finish

1. **Detected** — a row appears; the sync makes it a record.
2. **Selected** — `(origin='new' OR auto_enrolled) AND not yet processed`.
   Deliberately *not* a time window: an earlier version looked at "created
   in the last few minutes", so anyone added while the worker was down was
   skipped forever. A CSP merely present at first sync is never touched,
   which is what stops a first run emailing an entire organisation.
3. **Photograph** — fetched from the KYC documents in Zoho, the photo
   region located on the page.
4. **The gate** — if any required field or the photograph is missing, it
   **stops and alerts**. Nothing goes out with a blank field or a grey box.
5. **Generated** — placeholders replaced run by run inside the real
   `.docx`, so fonts, frames, text boxes and embedded images survive.
6. **Photo placed** at exactly 35 × 45 mm, cropped to fill, never squeezed.
7. **Converted** by headless LibreOffice.
8. **Validated** — the PDF is read back: no placeholder survived, the
   photograph is really on the page. A failure is raised loudly and
   **nothing is sent**.
9. **Stored and stamped in one transaction** — both formats and the
   processed stamp commit together. A crash between them would leave a CSP
   who looks unprocessed but already has documents, and the next run would
   email them twice.
10. **Emailed**, only after that commit succeeds. A delivery failure never
    causes regeneration.

An existing CSP enrolled by an RM joins at step 2 and is otherwise
identical.

---

## 5. Templates

A placeholder is **the field name in double quotes** — `"CSP Name"` — not
`{{...}}`, because the templates arrived that way and Word's autocorrect
produces curly quotes, which the regex accepts.

Word splits a placeholder across runs (`"` + `CSP ` + `Name"`), so a
run-level replace finds almost nothing. Replacement works on the
concatenated paragraph text and writes back into the runs the placeholder
covers, preserving each paragraph's formatting.

Content lives in body paragraphs, tables, headers, footers and text boxes —
the ID Card is entirely text boxes — so every paragraph in the package is
visited.

**Two rules applied at fill time**, decided from the template's own
placeholders rather than the document's name, so an uploaded template gets
the same treatment:

- **Title casing** — names, addresses and places are capitalised word by
  word. Codes, numbers and email addresses are untouched. Only the printed
  value changes; the stored record keeps what was typed.
- **Address trimming** — when a template prints the district *and* state
  separately, a district, state or pincode at the **end** of the address is
  removed, so the certificate does not read `… gorakhpur up 273404, DIST-
  Gorakhpur, Uttar Pradesh`. Only the tail, never the middle: a district at
  the start is part of the place name.

### The photo

Always 35 × 45 mm, cropped to that ratio rather than fitted — fitting a
square scan gives 35 × 35, which is not a passport photo.

Two layout facts, both measured:

- A frame drawn exactly 35 × 45 mm cannot hold a 35 × 45 mm photo:
  LibreOffice reserves **3.2 mm on each side** of a text box whatever
  `inset` says, and negative insets are clamped to zero. The frame is
  widened by that amount and shifted left, so the image lands on exactly
  the rectangle the template drew.
- Anything between frame and photo — a caption's space-before, a cell
  margin — pushes the image out and it is silently clipped. All of it is
  cleared before the picture is placed.

---

## 6. Who is asked for a missing field

The 23 sheet columns split by **who is in a position to know**. Chasing the
wrong person wastes everyone's time: an RM cannot tell you a CSP's gender,
and a CSP has never heard of their RBO.

**The CSP's own (11)** — asked of the CSP, via a tokenised link:
`csp_code, name, mobile, email, gender, address, district, state,
branch_name, branch_code, photo_url`

**The hierarchy (10)** — asked of the RM, or derived:
`ao, dc, dc_email, dc_contact, lho, rm_name, asm_name, asm_email,
asm_contact, rbo_name`

Of those ten, **eight are answered by the INFO sheet** without troubling
anyone: every one of the 79 districts belongs to exactly one DC, and that
row names the DC, their email and contact, the LHO and the state; LHO plus
state then picks the ASM and the RM.

**Only two ever reach a person: `ao` and `rbo_name`.** The INFO sheet is
Eko's own org chart and has no column for either.

**Chased by nobody:** `branch_contact` and `rbo_contact`. No template
prints either and neither is in `FIELD_TO_CSP_ATTR`, so no document could
carry one. They are still read and stored; they are simply never asked for.

### The CSP's link

One-time, seven-day expiry, SHA-256 **hash** stored rather than the token.
It shows only the fields that are missing, labelled in English and Hindi.
A wrong token, an expired one and a used one all return the same answer, so
the link cannot be probed. Answers are written **straight back to the
Google Sheet**, and the next sync completes the record.

---

## 7. Roles

| Role | May |
|---|---|
| **RM** | See their own CSPs only. Search, select, hand to the automation. Supply the two hierarchy fields. |
| **Admin** | Everything in the workspace: templates, dashboards, messaging, agents. **Not** who gets in. |
| **Super Admin** | All of Admin, plus access control, the Sheets screen, and the agents' run history. |

Enforced on the server for every request. Hiding a button is a courtesy;
the refusal is the control.

Super Admins come from **configuration** (`SUPER_ADMIN_EMAILS`), read at
every login — so adding or removing someone takes effect next time they
sign in.

---

## 8. The agents

Six, each owning one question, each a standalone function that reads the
database and writes findings. **They do not call each other.** See
[agents/](agents/) for one document per agent.

They coordinate through shared state, not messages. The Data Agent does not
*tell* the Communication Agent anything; it changes a record, and the
Communication Agent notices on its own next run — exactly as it would
notice a change an RM made by hand. That means one failing agent stays one
failing agent, order never matters, and any of them can be switched off.

The only exception: the Monitoring Agent reads `agent_states` to spot an
agent failing repeatedly, and **proposes** disabling it. It cannot act.

---

## 9. Configuration, not code

Five things that used to need a developer:

- **Document templates** — upload a `.docx`; its placeholders are read out
  of the file and matched. Proved: an uploaded template produced a real
  52,626-byte document with no leftover placeholder.
- **Dashboards** — built from 17 metrics in three groups. Add, hide, bring
  back. The main one cannot be removed. Every number opens into the records
  behind it.
- **Messages** — channel, subject and wording belong to the workspace.
  Three placeholders are substituted; anything else is left as typed.
- **Agents** — switched on or off per workspace.
- **Data sources** — declared rather than hard-wired.

---

## 10. Safety rules that are load-bearing

1. **It refuses rather than guesses.** No photograph, no ID card. A missing
   field stops the job and names what is wanted.
2. **It checks its own output.** The PDF is re-read after generation.
3. **It will not send a link nobody can open.** A message whose link points
   at `localhost` is refused with the reason. Being asked with a dead link
   is worse than not being asked, because the record is marked as chased.
4. **Above 25 recipients the Communication Agent proposes and sends
   nothing.** A bad template cannot reach a thousand CSPs before anyone
   notices.
5. **Zoho is read-only by scope**, not by convention. A write is rejected by
   Zoho itself.
6. **Login is throttled** — 8 failures per account, 20 per source address,
   both expiring after 15 minutes so nobody can be locked out permanently.

---

## 11. What is not finished

| Gap | State |
|---|---|
| **Version control** | Zero commits. The project exists on one laptop. |
| **Backups** | None. The only copy of 64 documents and all CSP data is one Docker volume — which failed once, on 5 Oct. |
| **Deployment** | Runs on Windows; target is Linux. No container image, no CI. |
| **WhatsApp** | A channel can be configured; no sender is written. It says so rather than failing quietly. |
| **Audit log** | Sign-ins are recorded. Template changes, access grants and sends are not. |
| **Seven fields** | `dc, dc_email, dc_contact, lho, rm_name, branch_contact, rbo_contact` are stored but cannot be printed by any document. |
| **Scale** | Every sync so far read 8 rows or fewer. Nothing is load-tested. |
| **Photo paths** | Stored as Windows file paths; they break on Linux. Photos should move into the database as documents already have. |
| **Message wording** | Signed "— Team", with no mention of EKO or SBI. |

---

## 12. Running it

```bash
docker compose up -d                 # Postgres :5433, Redis
cd backend
alembic upgrade head
uvicorn app.main:app --port 8000
celery -A app.celery_app worker --pool=solo   # --pool=solo on Windows
celery -A app.celery_app beat
cd ../frontend && npm run dev        # :3000, proxies /api to :8000
```

Login: `http://localhost:3000/auth/login`

Secrets live in `backend/.env` (git-ignored) and the Google service account
JSON in `credentials/` (git-ignored). Neither is ever printed or copied
into a generated file.

**Celery does not hot-reload.** Restart the worker after any change under
`app/`.
