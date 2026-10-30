# CSPdocMaker

Eko's internal web app that makes and sends the official documents of
**SBI Kiosk CSPs** (Customer Service Points), and keeps in touch with them on
WhatsApp and email.

Live: **https://indev.eko.in/csp-docmaker** · Owner: Ankita (Eko)

---

## What it does

- **Makes 4 documents** per CSP from Word templates — **CSP ID Card,
  Appointment Letter, Training Certificate, BCP** (Sub-KOs get no BCP) — checks
  them, turns them into PDF, stores them and **emails** them.
- **Finds new CSPs by itself** in the CSPDATA Google Sheet (read every minute)
  and the Calling / Lead sheets, and handles them with nobody logging in.
- **Asks the CSP, never the RM,** for missing details through a one-time form
  link on WhatsApp. Old CSPs get a **data verification** message to check
  their details.
- **Fills org fields from the INFO tab** (DC, ASM, RM, LHO, State, AO, RBO)
  and blank email / address / state / gender from **Zoho**.
- **Passport photo** for every CSP, always printed **35 × 45 mm**.
- **Reads CSPs' WhatsApp replies** and drafts an answer from fixed rules and
  the Knowledge Base; a person sends it (or Automatic mode).
- **Asks whether the documents arrived** (reply 1 / 2 / 3) 15 minutes after
  sending them.
- **Never loses a message:** a failed WhatsApp is sent again until it goes; a
  number not on WhatsApp → alternate number → email; a bounced email → ask on
  WhatsApp.
- **Checks itself:** every auto-filled value and correction is recorded;
  Setup → Data quality shows what the app reads and how it checks itself.

**No AI anywhere.** Every decision is a fixed rule — same input, same result.

Full description: [.claude/skills/cspdocmaker/SKILL.md](.claude/skills/cspdocmaker/SKILL.md)

---

## Who uses it

| Role | Can |
|---|---|
| **Super Admin** | Everything: access, agents, sheets, reply mode |
| **Admin** | See everything; templates, messaging, Knowledge Base, data quality, replies |
| **RM** | Search their CSPs, choose and send documents |

Sign-in: email + emailed code; @eko.co.in and @ekosupport.in.

---

## Built with

| Part | Technology |
|---|---|
| Website | Next.js 16, React 19, Tailwind |
| API | Python, FastAPI |
| Database | PostgreSQL 16 (also holds the PDFs) |
| Scheduled jobs | Celery + Redis |
| Documents | python-docx → LibreOffice → PDF |
| Data | Google Sheets, Zoho CRM (read only) |
| WhatsApp | Eko's WhatsApp platform (Meta) |
| Server | Docker Compose + Caddy on one Linux machine |

---

## Folders

```
backend/      API, database models, scheduled jobs, tests
  app/services/   the rules (documents, messages, INFO, replies, loops)
  app/workers/    scheduled jobs (sync, new CSPs, verification, retries, ...)
  alembic/        database changes
  tests/          automatic tests + golden cases (tests/golden/cases.json)
frontend/     the website (admin, RM and CSP form screens)
templates/    document, email and message templates
deploy/       server settings and Caddy
docs/         architecture and decisions
```

---

## Run it on a laptop

```bash
docker compose up -d                       # Postgres + Redis
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
celery -A app.celery_app worker --loglevel=info
celery -A app.celery_app beat --loglevel=info
cd ../frontend && npm install && npm run dev   # http://localhost:3000
```

Settings go in `backend/.env` (never committed). Nothing is sent to CSPs from
a laptop — only from the public server.

**Tests** (from `backend/`):
```bash
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q
```

---

## Update the server

```bash
cd /home/Ankita/Csp_Doc_Maker
# back up first if the update changes the database:
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production exec -T postgres pg_dump -U cspdocmaker cspdocmaker | gzip > ~/cspdocmaker-$(date +%F-%H%M).sql.gz
git pull
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production up -d --build
```

Details: [DEPLOY.md](DEPLOY.md)

---

## More

| File | What |
|---|---|
| [PROJECT-REGISTER.md](PROJECT-REGISTER.md) | Every request, numbered, and what was done |
| [AI_SPEC.md](AI_SPEC.md) | Every design decision and why |
| [AGENT.md](AGENT.md) | Rules for any AI agent working on this code |
| [SYSTEM_PROMPT.md](SYSTEM_PROMPT.md) | Prompt for an assistant that answers about this project |
| [DEPLOY.md](DEPLOY.md) | Server setup and updates |

Internal — Eko proprietary.
