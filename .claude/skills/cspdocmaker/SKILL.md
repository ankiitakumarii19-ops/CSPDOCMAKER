---
name: cspdocmaker
description: What the CSPdocMaker project does, end to end — who it serves, which sheets it reads, which documents it makes, every WhatsApp / email it sends and why, the reply agent, feedback, retries, INFO mapping, data quality, screens, roles and the rules it must never break. Use for ANY question or task about CSPdocMaker, Eko's SBI Kiosk CSPs, their documents, messages, INFO / CSPDATA / Calling / Lead sheets, or this app's screens and database.
---

# CSPdocMaker — what this project does

Use this as the knowledge for anything about this project. **Stay inside it:**
answer only about CSPdocMaker. If something is not covered here, say so and
look in the sources listed at the end — never guess or fill gaps from general
knowledge. Explain in plain words; the owner prefers "what happens, what to do,
what's left" over technical detail.

---

## 1. In one paragraph

CSPdocMaker is Eko's internal web app for **SBI Kiosk CSPs** (Customer Service
Points — the agents who run SBI kiosks). It makes their four official
documents — **CSP ID Card, Appointment Letter, Training Certificate, BCP** —
from Word templates, turns them into PDFs, stores them, **emails** them to the
CSP and tells them on **WhatsApp**. When details are missing it **asks the CSP**
(never the RM) through a one-time form link. It also checks old CSPs' details,
answers CSPs' WhatsApp replies, asks whether the documents arrived, and keeps
trying when a message fails. **There is no AI anywhere** — every decision is a
fixed rule, so the same input always gives the same result.

Live at **https://indev.eko.in/csp-docmaker**. Owner: Ankita (Eko).

---

## 2. Words used in this project

| Word | Meaning |
|---|---|
| **CSP** | An SBI Kiosk agent; the person the documents are for. Identified by a **CSP code** (e.g. 1A850498). |
| **KO / Sub-KO** | Code of 8 characters = KO; 9–10 = Sub-KO. **Sub-KOs never get a BCP.** |
| **CSPDATA** | The main Google Sheet of CSPs (tabs **KOData**, **SUBKOData**, **INFO**, **Address**). The source of truth. |
| **INFO tab** | Eko's org chart inside CSPDATA. Fills DC, ASM, RM, LHO, State, and (AO block) AO and RBO Name, by branch / district. INFO is **not** copied into the database — it is read live each sync. |
| **Calling sheet** | Old CSPs (already working). Copied into KOData as **old / baseline**. |
| **Lead sheet ("Lead raw data")** | New CSPs being onboarded; "Go Live Done" = live. Copied in as **new**. |
| **Old (baseline) CSP** | Gets a **data verification** WhatsApp to check their details. No documents mailed automatically. |
| **New CSP** | Goes live after the start → documents made and emailed automatically. |
| **Existing CSP** | Already in CSPDATA before the Calling / Lead import. **Never mailed documents, never sent the verification WhatsApp.** |
| **Data request / form link** | One-time, 7-day link where the CSP fills or checks their own details. |
| **Hold** | CSP not active / not live → nothing is sent to them. |
| **RM** | Relationship Manager who owns the CSP (matched **by name** from the sheet). |
| **AO / RBO / LHO / DC / ASM** | Bank and Eko org fields. AO and RBO Name come from INFO's AO block; DC / ASM / RM / LHO from INFO. |
| **Agent** (in the app) | A scheduled job, **not** an AI. |

---

## 3. Where the data comes from

1. **CSPDATA Google Sheet** — read every minute; changes copied into the database.
2. **INFO tab** — fills org fields that are blank (an existing value is never replaced).
3. **Calling + Lead sheets** — new codes are appended to KOData / SUBKOData; status decides hold / live.
4. **Address tab → Zoho Lead "Shop Address" → Zoho "Business Address"** → else the CSP is asked. No OCR, no Home Address.
5. **Zoho CRM (read only)** — search **both** `sbi_kiosk` and **Leads** (KYC packs live on Leads); code AND phone must match. Used for blank email / address / state / gender and the photo.
6. **Photo** — app's own → the sheet's Photo cell → Zoho. Always made into a white-background passport photo, **printed 35 × 45 mm** (cropped, never just scaled).
7. **Authorization sheet** — who may sign in (RMs, Admins, Super Admins).

---

## 4. What happens to a CSP

**New CSP (goes live):**
detect → fill blanks from INFO / Zoho → find photo → check data → if something
is missing, WhatsApp the CSP a form link and wait → make the 4 documents (3 for
Sub-KO) → check each document → PDF → store → **email** the PDFs → **WhatsApp**
"documents ready" → **15 minutes later** the feedback question.

**Old CSP (from the Calling sheet):** WhatsApp **data verification** message
with the form showing all their details to confirm or correct; batches of 25
every 15 minutes, 8 am–8 pm. After they answer, anything still blank is asked
once more ("details still needed").

**RM-started:** an RM searches a CSP, picks documents, confirms — same pipeline.

The **certificate date is the day the document is made.** The RM never fills
anything in.

---

## 5. Every message the app sends, and why

| Message | When |
|---|---|
| Details request / data verification (WhatsApp) | Details missing (new CSP) or checking (old CSP) |
| Details still needed | After a form, if something is still blank |
| Documents email | Documents made |
| Documents ready (WhatsApp) | After the email |
| **Feedback question** (Hinglish) | 15 min after "documents ready": "Kya aapko mil gaye? Reply karein: 1 - mil gaye aur sab sahi hai, 2 - nahi mile, 3 - kuch galat hai" |
| Reply to a CSP | When a CSP writes back (see §6) |

Rules for sending:
- Only **8 am – 8 pm**; never from a laptop (only a public server address sends).
- **Nothing to a CSP on hold.**
- **Emails can be paused** with `EMAILS_PAUSED=true` (OTPs still go). Sender: ganesh.kumar@eko.co.in.
- WhatsApp goes through **Eko's WhatsApp platform** (Meta underneath). A **new wording must be approved by Meta once**; until then it waits and is tried again.
- Every message records **why it was sent** (usual flow, email bounced, WhatsApp didn't reach, alternate number, CSP asked, documents not received, reply, **sent again after an error**). Shown on the WhatsApp messages and Emails screens.

**When a message fails:**
- **Any error except "number not on WhatsApp"** → sent again after 30 min, 1 h, 2 h, then every 4 h, up to 7 days.
- **Number not on WhatsApp / not received** → **contact loop**: try the alternate number (second number in the mobile cell → Calling sheet → Zoho Lead); if it reaches them, **it replaces the number in CSPDATA**; otherwise email them the form.
- **Email bounced** → ask the CSP on WhatsApp to correct their email; resend once corrected.
- A wording **Meta rejected** → a person changes the wording.

---

## 6. Replies to CSPs (the reply agent — rules, not AI)

Every 10 minutes it reads what CSPs wrote back (only numbers the app messaged,
last 3 days) and drafts an answer from fixed rules (English / Hinglish / Hindi)
and the **Knowledge Base, category "CSP replies"**:

| CSP says | Reply |
|---|---|
| Link doesn't open / change my details / photo change | New **data verification link** |
| Where are my documents | When and where they were emailed |
| Upload / police verification / agreement | Contact your RM (name + number) |
| Thanks / ok | No reply |
| Technical (machine, network, portal, OTP, transactions, money) | **No reply** |
| Feedback **1** (got them, all correct) | Thank you — **no link** |
| Feedback **2** (didn't get them) | Documents emailed again **+ data verification link** (email may be wrong) |
| Feedback **3** (something wrong) | Data verification link |
| Anything else | Knowledge Base answer, else "contact your RM" |

**Modes** (Super Admin only): **Drafts** (default — a person presses Send or
Skip; can edit, can tick "also send the data verification link"), **Automatic**
(8 am–8 pm, max 3 a day per CSP), **Off**. The owner reviews drafts for a week
before switching to Automatic. The app learns which drafts were sent as-is or
changed ("What the agent learned").

---

## 7. INFO and data quality

- Every value the app fills by itself is recorded with **why** (e.g. "INFO AO block, by branch") and whether a person confirmed or corrected it.
- **Kept rate** target: above 75%.
- **Loop 1:** when 2+ CSPs get the same AO / RBO correction, the app **fixes INFO itself** (only those branches move). DC / ASM email / phone too. Names, LHO, State stay suggestions.
- **Loop 2:** contact loop (above). **Loop 3:** unanswered chat questions → add to Knowledge Base. **Loop 4:** 60+ golden cases run before every push. **Loop 5:** feedback answers.
- **Freshness chips** in the header: sheet read on time (green), late (amber), failed / stuck (red), never (grey).
- Screen: **Setup → Data quality** (Context table, Harness table, Auto-filled values, Loops).

---

## 8. Screens and who sees them

**Roles:** **Super Admin** (everything; access, agents, reply mode) · **Admin**
(sees everything; templates, messaging, Knowledge Base, data quality) · **RM**
(searches CSPs, chooses documents; sees own CSPs + unresolved ones). Sign-in
with email + emailed code; domains @eko.co.in and @ekosupport.in.

Admin menu: Dashboard Overview · Build a dashboard · Database · Sheets ·
Document Templates · Messaging · **WhatsApp messages** (sent / rejected / not
received / delivered / read / responded; feedback card with 1 / 2 / 3 counts) ·
**Replies** · **Emails** · Knowledge Base · Agents · Access · Workspace Rules ·
Setup → **Data quality**.

The staff **chat** answers from records and the Knowledge Base by keyword rules
(English / Hinglish / Hindi) — no AI.

---

## 9. Where things are stored

- **Postgres database `cspdocmaker`** on the server (Docker service `postgres`). Holds CSP records, the **PDFs themselves** (versioned, never overwritten), photos, every WhatsApp / email, replies, feedback, Knowledge Base, audit log.
- Main tables: `csp_records`, `stored_documents`, `csp_photos`, `whatsapp_messages`, `email_messages`, `data_requests`, `csp_replies`, `csp_feedback`, `contact_fixes`, `field_provenance`, `field_corrections`, `quality_suggestions`, `knowledge_entries`, `audit_logs`, `sync_runs`.
- A copy of every PDF also in `/home/Ankita/CSP_Documents/<CSP name> (<code>)/` on the server.
- **INFO, CSPDATA, Calling, Lead** stay in Google Sheets.
- Server: one Linux machine, Docker Compose + Caddy, app folder `/home/Ankita/Csp_Doc_Maker`.

---

## 10. Rules that must never be broken

1. **No AI / LLM anywhere** (no Claude, Gemini, Cloudflare, OCR).
2. **Existing CSPs** (in CSPDATA before the import) are never mailed documents or sent the verification WhatsApp.
3. **Photo is always 35 × 45 mm.**
4. The CSP fills **their own** details only; never DC / ASM / RM / LHO. AO / RBO Name asked once, only if INFO can't map them.
5. **Never hide errors**; every failure is logged and visible.
6. **Secrets never** in code, logs, screenshots or chat (`.env`, `deploy/.env.production`, credentials).
7. **Back up the database before any database change.** Ask before deleting anything.
8. **Ask before changing a screen.**
9. Two Ganesh Kumar accounts (@eko.co.in and @ekosupport.in) are **different people**.
10. **No payment / billing** — out of scope.
11. Every request is recorded in `PROJECT-REGISTER.md` with a number (No. 1 … No. 166+).

---

## 11. Sources (read these when this file is not enough)

| File | What's in it |
|---|---|
| `PROJECT-REGISTER.md` | Every request, numbered, in plain words, with what was built |
| `AI_SPEC.md` | Every design decision (D1–D25) and why |
| `DEPLOY.md` | How the server is set up and updated |
| `backend/tests/golden/cases.json` | The business rules as worked examples |
| Knowledge Base (in the app) | Staff answers and the "CSP replies" wordings |
