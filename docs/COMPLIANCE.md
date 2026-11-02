# CSPdocMaker — compliance note

Written 1 Nov 2026 (register No. 172–173) against the *Agentic AI Development
Principles & Standards* v1.0. **Not legal advice.** Which RBI and DPDP
obligations apply to Eko for this app is for Eko's compliance, risk and legal
teams to confirm (standards §B8: "applicability must be determined for the
specific institution, service and use case"). Every row marked *to confirm*
waits for them.

Note first: the app has **no AI model** (AI_SPEC D1). Its "agents" are
scheduled jobs following fixed rules, so the standards' concerns about a
model's reasoning (prompt injection, the model enforcing its own security)
mostly do not arise. The controls still apply to what the jobs do.

---

## 1. Personal data the app holds (DPDP — B5)

| Whose | What | Where | Why (purpose) | Who can see it | Kept for |
|---|---|---|---|---|---|
| CSPs | Name, CSP code, mobile, email, address, gender, branch, district, state, bank / Eko org fields | Postgres `csp_records`; Eko's CSPDATA Google Sheet (the source) | Making and sending the CSP's own documents; checking their details with them | Super Admins, Admins; RMs only their own CSPs (+ unresolved) | As long as the record exists — **kept, owner's decision 1 Nov 2026** |
| CSPs | Photo (original + 35 × 45 mm passport version) | Postgres `csp_photos`; the sheet's Photo cell; working files on the server | Printed on the ID card / documents | Same as above; a private 1-day link for the sheet | **Kept, owner's decision 1 Nov 2026** |
| CSPs | The four documents (PDF, every version) | Postgres `stored_documents`; `/home/Ankita/CSP_Documents/` on the server | The CSP's official documents, re-sent on request | Same as above; a private 7-day link in the CSP's email / WhatsApp | **Kept, owner's decision 1 Nov 2026** |
| CSPs | Their WhatsApp replies; what was sent to them and why | `csp_replies`, `whatsapp_messages`, `email_messages` | Answering them; proving what was sent | Super Admins, Admins | **Kept** |
| CSPs | What they typed in their details form (before / after) | `data_requests` | Traceability of a changed value | Super Admins, Admins | **Kept** |
| CSPs | KYC attachments on the Zoho Lead | **Not stored**: read from Zoho only to take the photograph (no OCR, D11) | The photo | — | — |
| Staff | Email, name, mobile, role, password hash, profile picture | `users`, `workspace_members`, `user_photos` | Signing in; who did what | Super Admins (access list) | While they have access |
| Staff | Sign-in times and the network address they signed in from | `audit_logs` (action `login`) | Security: who signed in when | Super Admin only | **Kept** |

**Shared with (processors / third parties):** Google (Sheets, Drive — the
CSP data lives there; Gmail / SMTP for email), Zoho CRM (read only), Eko's
WhatsApp platform → Meta (the message text and the CSP's mobile).
Nothing is sent to any AI service.

**Not yet decided — to confirm:** the lawful basis for each purpose; a
retention period and deletion rule (today nothing is deleted, as the owner
chose on 1 Nov 2026); how a CSP asks to see, correct or erase their data;
the breach-notification procedure; whether a consent notice is needed on
the CSP's form.

---

## 2. Regulatory mapping (B8) — *to confirm*

| Possible source (to confirm with compliance) | Requirement area | Control in the app today |
|---|---|---|
| Digital Personal Data Protection Act, 2023 and its Rules | Purpose, minimisation, security safeguards, retention, data principal rights, breach notice | §1 above; role-based access; HTTPS; audit log; **gaps: retention, rights process, breach procedure** |
| RBI directions on IT governance, risk, controls and assurance | Access control, change management, logging, testing, backups | Roles enforced on the server; release checklist; test copy; audit log; daily backup command (DEPLOY.md) |
| RBI directions on outsourcing of IT services / Business Correspondents (Eko as BC / service provider to SBI) | Data confidentiality, audit rights, the bank's oversight | Data stays in Eko's sheets and server; *to confirm with SBI's requirements* |
| RBI cyber-security expectations | Secure configuration, monitoring, incident response | Secrets in settings files only; alerts to Super Admins (No. 173); **gap: written incident-response procedure** |

Evidence that a control works: the automatic tests (1,500+), the 66 golden
cases, the register (every change with its date), `audit_logs`.

---

## 3. The standards, point by point

Status: **Met** · **Partly** · **Gap** · **Owner's decision** (a deliberate
choice, recorded).

| # | Standard | Status | How / what is missing |
|---|---|---|---|
| A1 | Understand the problem | Met | The owner's choices are asked before building (register rows quote them) |
| A2 | Plan before building | Partly | Plans in the register and `docs/Productize plan…xlsx`; no separate written architecture approval per change |
| A3 | Tasks with owner, deadline, Friday review | Partly | `docs/Project tracker.xlsx` (No. 173) has owners and dates; the Friday review is a habit to start |
| A4 | Central tracker in a Google Sheet | Partly | `docs/Project tracker.xlsx` — **upload it to Google Drive as a Google Sheet** to make it the central one |
| B1 | Harness | Met | Server-only sending, 8 am – 8 pm, one run at a time (database locks), retry limits, switches per job |
| B2 | Context | Met | Fixed sources (sheets, INFO, Zoho, Knowledge Base); uploaded files read as data, never as instructions; workspaces kept apart |
| B3 | Guardrails | Met | In code (Data quality → Guardrails lists them); fail safe: blanks never overwrite, holds stop sending |
| B4 | Security by design | Partly | Hashed passwords, emailed code / Google, throttling, secrets in settings, sign-in in a protected cookie (No. 173); **gap: no formal security test / risk assessment; data at rest not encrypted by the app** |
| B5 | DPDP | Gap | §1 — retention, rights, breach procedure to decide |
| B6 | Identity and access | Partly | Roles re-checked on every request; jobs cannot grant access; test copy separate from live (No. 173); **gap: one service account for all Google access** |
| B7 | Banking-grade architecture | Partly | Duplicate prevention (one decision / message per key), retry limits, timeouts, backups; **gap: no threat model** |
| B8 | Regulatory | Gap | §2 — to confirm with compliance |
| B9 | Zero-UI, stop switch | Met | Jobs run themselves; each can be switched off (Agents, EMAILS_PAUSED, reply mode Off, *_ENABLED settings) |
| B10 | Maker-checker | **Owner's decision** | The verification agent's sheet write (No. 171) and the INFO auto-fix (No. 153) run **without a second person** — the owner chose to keep both automatic on 1 Nov 2026. Both log every change with old / new value and time. Replies to CSPs: Drafts mode is maker-checker |
| B11 | Audit and observability | Met | `audit_logs`, send reasons, decisions log, freshness chips, harness, **email alerts (No. 173)**; no passwords / codes logged; **gap: audit rows can be changed by a database administrator** |
| B12 | Testing | Partly | Full automatic tests + golden cases; **release checklist (No. 173)** adds browser check and a second reviewer — to be followed |
| B13 | Controlled deployment | Partly | Git, test copy, release checklist with rollback (No. 173); **needs the test copy set up on the server** |
| B14 | Continuous monitoring | Met | Harness table, kept rate, reply learning, alerts |
| C1 | Risk class per agent | Met | §4 |
| C2 | Human in the loop | Partly | Drafts mode for replies; Super Admin acts on agents; see B10 |
| C3 | Agent-to-agent security | n/a | Jobs do not talk to each other |
| C4 | Prompt injection | n/a | No AI model; uploads parsed by fixed rules |
| C5 | Kill switch | Met | Per job (see B9) |
| C6 | Metrics | Partly | Kept rate, sending failures, reply learning; no cost / latency report |
| D | Proposal → policy → execution → audit | Partly | Fixed rules decide; audit records outcomes; B10 decision above |
| F | Definition of done | Met from No. 173 | `docs/RELEASE-CHECKLIST.md` |

---

## 4. Risk class of every automatic job (C1)

| Job | What it can do by itself | Class | Controls |
|---|---|---|---|
| Verification agent | Writes a CSP's answer to the CSP sheet (No. 171) | High | Newest-wins rule, server only, every decision logged; owner's decision: no second person |
| INFO auto-fix | Rewrites AO / RBO in the INFO tab (No. 153) | High | Only on 2+ matching corrections, rivals left for a person, logged; owner's decision: automatic |
| Contact loop | Messages CSPs; replaces a CSP's mobile in CSPDATA when an alternate works | High | Server only, 8–8, max tries, logged with reason |
| Old-CSP verification / details requests | Messages CSPs | High | Batches of 25, stops after failures in a row, never existing CSPs |
| Feedback question, failed-message resend | Messages CSPs | High | 8–8, limits, no-WhatsApp numbers excluded |
| Reply agent | Messages CSPs (Automatic mode) | High (Automatic) / Medium (Drafts) | Drafts by default, max 3 a day per CSP, Super Admin switches |
| Communication agent | Messages CSPs | High | Off until switched on |
| Calling & Lead import | Appends rows to CSPDATA | High | Existing codes untouched; baseline on first run |
| CSP sync | Copies the sheet into the database; fills blanks from INFO | Medium | Never overwrites a value with INFO; field-level history |
| Data agent, Document agent | Fill a blank from INFO; start documents for a complete record | Medium | Fixed checks for every document |
| Sheet photo job | Puts the photo picture in the sheet's Photo cell | Medium | Only CSPs with no photo |
| Alerts | Emails the Super Admins | Low | Once per problem; 8–8 |
| Messages a person sends (Action Required, Ask CSPs — No. 174) | Messages CSPs, many at once | High | A person chooses and confirms; on hold never; details form never to existing CSPs; server only; every message logged with who |
| Action Required re-check | Closes an RM's card when the details are there | Low | Uses the same check as the documents job; records how it was filled |
| A person editing a CSP (Database / Sheets tab — No. 175) | Writes the CSP sheet | High | A person saves; RMs only their own CSPs; checked fields; refused if changed meanwhile; every field logged with old / new / who / when |
| Setup, Monitoring agents; bounce check; WhatsApp status | Read and report | Low | — |

---

## 5. Owner's decisions recorded here

* **1 Nov 2026 (No. 173):** keep the verification agent's sheet write and the
  INFO auto-fix automatic, without a second person (B10).
* **1 Nov 2026 (No. 173):** keep all CSP data as it is — nothing is deleted
  (B5 retention).
* **2 Nov 2026 (No. 175):** RMs edit only their own (and unowned) CSPs, on
  the Database page and the Sheets tab; RMs may change the RM Name; an RM's
  search finds every CSP, another RM's opens view only.
* **2 Nov 2026 (No. 174):** RMs may message and open the chat of their own
  (and unowned) CSPs; CSPs on hold are never messaged; existing CSPs may get a
  custom message but never the details form; custom WhatsApp text goes inside
  the approved wording.
* **1 Nov 2026 (No. 173):** alerts by email to Super Admins; a release
  checklist; a test copy; the sign-in in a protected cookie.
