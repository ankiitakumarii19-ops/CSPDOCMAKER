# CSPdocMaker — what is built, what works, what is waiting

Maintained by Claude. Updated **2 October 2026**.

This file records what was asked for, what actually works, and what is
blocked and on whom. It is deliberately honest about the difference between
"built", "tested" and "proven on real data" — those are not the same thing,
and only the third means you can rely on it.

---

## 1. What the system does

Issues four official documents to SBI Kiosk CSPs and emails them:
CSP ID Card, CSP Certificate, Training Certificate, BCP.

Work enters two ways, through the **same pipeline** — there is no second
code path that could drift:

- **Automated** — a new row appears in the CSP Google Sheet, and within
  ~3 minutes the documents are generated and emailed. Nobody logs in.
- **Manual** — an RM signs in, searches a CSP, picks documents, reviews,
  confirms, sends.

### The pipeline

```
 detect -> fill gaps -> find photo -> validate data -> generate
        -> validate document -> convert to PDF -> store -> email
```

Every job records which of those states it reached, so a stalled CSP can
always be traced to a step.

| Step | What happens |
|---|---|
| Detect | Sheet read every minute, diffed against Postgres |
| Fill gaps | INFO tab supplies RM / ASM / DC / Circle Head by territory |
| Find photo | Zoho CRM — **both** `sbi_kiosk` and `Leads` |
| Validate data | Missing required fields raise an alert instead of a half-filled document |
| Generate | python-docx fills your templates; photo cropped to 35×45 mm |
| Validate document | Reopened and every placeholder checked against source data |
| Convert | LibreOffice headless → PDF |
| Store | DOCX **and** PDF into Postgres with SHA-256 and a version |
| Email | SMTP, with per-document rows so you can see what was attached |

**A document that fails validation is never sent.** That check is
deterministic — there is no AI anywhere in this path.

---

## 2. The background workers

No AI agents run against this project. The automation is **three Celery
tasks** on a beat schedule, plus one worker process that executes them.

| Task | Runs every | What it does |
|---|---|---|
| `workers.sync_csp_data` | **1 min** | Reads CSPData, inserts/updates records, fills gaps from INFO |
| `workers.process_new_csps` | **3 min** | Picks up new CSPs, runs the full pipeline, emails them |
| `workers.sync_authorization` | **15 min** | Mirrors the RMs/Admins tabs into `authorization_records` |

Each task carries an `expires` just under its own interval. They are
refreshes, not work that must eventually happen — without this, a worker
outage once left a 255-task backlog whose draining hammered Google Sheets
into the connection resets that crashed the worker four times.

**Celery does not hot-reload.** Any change under `backend/app/` needs the
worker restarted or it keeps running the old code.

---

## 3. Features, and how far each one actually got

Legend:
**PROVEN** — run end to end on real data ·
**TESTED** — covered by tests, not yet run on real data ·
**PARTIAL** — backend done, no UI ·
**BLOCKED** — waiting on something outside the code ·
**NOT STARTED**

### Document generation

| Feature | State | Notes |
|---|---|---|
| Four documents from your templates | **PROVEN** | 64 documents stored, 8 emails sent |
| Document validation before sending | **PROVEN** | Reads text boxes, headers, footers — a body-only walk read the ID Card as empty |
| PDF conversion | **PROVEN** | LibreOffice headless |
| Both DOCX and PDF kept in Postgres | **PROVEN** | Versioned, checksummed |
| Passport photos everywhere (35×45 mm) | **PROVEN** | Measured in the stored PDFs. Cropped, not merely scaled — scaling a square scan gives 35×35 |
| Gender-based salutation | **TESTED** | `Shri/Ms/Mrs.` → `Mr.` / `Mrs./Miss`. Unknown gender keeps the general form; the name is never used to guess |
| Font and size consistency | **PROVEN** | See §5 — this was a real defect in two templates |

### Automation

| Feature | State | Notes |
|---|---|---|
| New row detected automatically | **PROVEN** | Nitasha `1A851727`, full run, email `SENT` |
| Photo found in Zoho | **PROVEN** | Searches both modules; a Lead needs **two** independent facts to match |
| Photo extracted from a PDF | **PROVEN** | Including single-page PDFs that *are* the photo |
| RM resolved from INFO | **PROVEN** | Falls back to "unresolved", visible to every RM — no CSP is stranded |
| Worker stability | **PROVEN** | 14 clean cycles after the httplib2 client-reuse fix |

### Admin and auth

| Feature | State | Notes |
|---|---|---|
| Login, OTP, two email domains | **PROVEN** | `@eko.co.in` and `@ekosupport.in` |
| Forgot password | **TESTED** | |
| Admin dashboard, drill-down, filters | **PROVEN** | Generated / Mailed / Pending / Failed, CH column, date filter, clear |
| **Document template management** | **PARTIAL** | Backend only — see §4 |
| **RM access screen** | **BLOCKED** | Needs Editor on the Authorization sheet |

### Missing-data chasing (this session's main work)

| Feature | State | Notes |
|---|---|---|
| Field ownership — who gets chased | **TESTED** | 9 CSP-owned, 14 org-owned, 4 survey questions |
| INFO fills 7 of 14 org fields | **PROVEN** | 6 can **never** be filled — they are bank facts, see §6 |
| District → LHO **and** State | **PROVEN** | All 79 districts belong to exactly one DC. One district can fill 8 fields |
| Tokenised CSP link | **TESTED** | Hashed, one-time, 7-day expiry, scoped to named fields |
| Trilingual message | **TESTED** | English + Hindi + Hinglish, Meta's rules enforced in code |
| **Write-back to CSPData** | **PROVEN** | Live round trip on Nitasha's row, restored afterwards |
| **WhatsApp sending** | **BLOCKED** | Platform verified reachable; needs a CSP list and a real URL |
| **The CSP form page** | **NOT STARTED** | The link resolves on the backend; there is no screen yet |

---

## 4. Known gaps that will bite if forgotten

**`DocumentType` is still a Python enum.** The database now accepts any
document code (the Postgres enum was dropped, all 64 documents preserved),
but 16 files still import a fixed four-value enum. **An uploaded template
would store and then fail to load.** This is the larger half of the
template feature and it is not done.

**The four `Has ...` columns do not exist in CSPData.** `Has CSP ID Card`,
`Has CSP Certificate`, `Has Training Certificate`, `Has BCP`. Until they
are added, those answers come back from write-back as *skipped* — reported,
not silently dropped.

**`PUBLIC_APP_URL` is `http://localhost:3000`.** Every CSP link generated
today is dead on a phone.

**Circle Head is ambiguous in INFO.** Two people both claim Patna + Bihar,
so the lookup correctly declines and the CH filter stays empty. This is a
data question, not a code one.

**District spelling.** The sheet says "Yamunagar", INFO says "Yamunanagar".
Blocks the DC fill for that district only.

**Not built at all:** WhatsApp sending, the CSP form page, both admin
screens, audit logging (table exists, 0 rows). `SMSJob`/`SMSStatus` are
dead code awaiting removal.

---

## 5. Defects found and fixed

Worth recording because several were silent — they produced wrong output
without failing.

| Defect | Consequence |
|---|---|
| Photo search never reached Zoho `Leads` | The one CSP that worked, worked by luck |
| Sheet sync wiped `photo_url` every minute | Photo re-downloaded from the CRM on every pass |
| Automated worker created no job rows | The whole admin dashboard was blind to automated CSPs |
| Cached httplib2 client reused after a reset | Worker segfaulted four times |
| CSP Certificate: name printed at 11 pt inside a 22 pt sentence | The placeholder carries no font size at all |
| Training Certificate: name printed in **Aptos** beside Calibri | Those runs carry no typeface; the theme font is Aptos |
| Legacy unlayered CSS overrode every Tailwind utility | The UI did not match the design |

The last two formatting ones were in the templates themselves and had been
shipping on every document.

---

## 6. What the INFO sheet can and cannot do

Measured against the live sheet, not assumed.

**Fills automatically (7 of your 14 org fields):** DC, DC Email Id, DC
Contact Number, ASM, ASM Email Id, ASM Contact Number, Relationship Manager.
**Plus LHO and State**, derived from District.

**Can never fill (6):** Branch Name, Branch Code, Branch Contact Number,
AO, RBO Name, RBO Contact No.

They cluster for a reason: every one is a **bank** fact, and INFO is Eko's
own org chart. No code fixes that. **The only way to automate AO and RBO is
to add those columns to the INFO sheet** — then they fill like the rest.

Two data gaps: **Narottam** (ASM/DC, Punjab) has no email in INFO, so ASM
Email Id can never fill for Punjab. And a DC covering two LHOs (Maharashtra
+ Mumbai Metro) cannot name one, so Pune derives its State but not its LHO.

---

## 7. Waiting on you

| # | What | Unblocks |
|---|---|---|
| 1 | Share the **Authorization sheet** with `cspdocmaker@csp-document-maker.iam.gserviceaccount.com` as Editor | RM grant/revoke |
| 2 | The **bigger CSP list** — where is it? | All WhatsApp sending |
| 3 | A real **`PUBLIC_APP_URL`** | Every CSP link |
| 4 | Permission to add **4 columns** to CSPData | The "do you already have it" answers |

CSPDATA already has Editor — verified by a live write that was restored.

---

## 8. How to check it yourself

```bash
cd backend
PYTHONPATH=. ./.venv/Scripts/python.exe -m pytest -q     # 446 tests

docker exec cspdocmaker-redis redis-cli -n 1 llen celery  # queue depth, want 0
docker exec cspdocmaker-postgres psql -U cspdocmaker -d cspdocmaker \
  -c "select source, max(started_at) from sync_runs group by source;"
```

**446 tests pass.** The suite is the contract: several tests exist
specifically to fail when a template is edited in Word in a way that would
break generation — a shrunk photo frame, a renamed placeholder, a renamed
photo marker. If one of those fails after you edit a template, the test is
doing its job.
