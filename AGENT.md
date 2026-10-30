# AGENT.md — for any AI agent working in this repository

You are working on **CSPdocMaker**, Eko's app that makes and sends SBI Kiosk
CSPs' documents and messages. Work only on this project.

## Read first

1. [.claude/skills/cspdocmaker/SKILL.md](.claude/skills/cspdocmaker/SKILL.md) — what the app does.
2. [AI_SPEC.md](AI_SPEC.md) — every design decision (D1–D25) and why. Do not go against one without asking.
3. [PROJECT-REGISTER.md](PROJECT-REGISTER.md) — every request so far (No. 1 …). Check whether something was already asked or decided.

## Never

- **Add AI / an LLM / OCR** anywhere in the app (no Claude, Gemini, Cloudflare, OpenAI). Rules and the Knowledge Base only.
- **Send documents or the verification WhatsApp to an existing CSP** (in CSPDATA before the Calling / Lead import).
- **Ask the CSP for DC / ASM / RM / LHO.** AO / RBO Name only if INFO can't map them, once.
- **Print a photo at any size but 35 × 45 mm** (crop, never just scale).
- **Hide an error** (`except: pass`, fake success, a message with no error ID).
- **Put a secret** in code, logs, commits, screens or chat: `.env`, `deploy/.env.production`, `backend/credentials/`, `LOGIN-FOR-TESTING.txt`, tokens. WhatsApp `send_error` text can contain a Meta token — never repeat it.
- **Treat the two Ganesh Kumar accounts** (@eko.co.in, @ekosupport.in) as one person.
- **Build payment or billing.**
- **Commit, push or install git hooks** unless the owner asks in that moment.
- **Delete anything** without asking.

## Always

- **Before changing code:** name the problem, the part, the files and the expected result. Smallest correct change.
- **Ask before changing a screen.**
- **Database change:** add an Alembic migration with a downgrade; tell the owner to **back up first**.
- **Test before saying done** — from `backend/`:
  `PYTHONPATH=. PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
  Needs Docker (Postgres + Redis). The full run takes 9–18 minutes: run it in the background and never run two at once.
  Tests that set a fixed `NOW` must pass `now=NOW` to the code, or they fail on a slow run.
- **Every code fix adds a golden case** in `backend/tests/golden/cases.json` in the same commit (or say why it can't).
- **Record the request** in `PROJECT-REGISTER.md`: a numbered row in plain words + a change-log line.
- **Update `AI_SPEC.md`** when a design decision is added or changed.
- **Log what happens** (start, result, failure with traceback); a new scheduled job also gets a Harness row on Data quality.
- **Reply to the owner in plain language:** what changed, what to do, what's left. No technical detail they did not ask for.

## How the code is laid out

| Where | What |
|---|---|
| `backend/app/services/` | The rules: `info_directory`, `message_sender`, `csp_replies`, `documents_feedback`, `feedback_loops`, `resend_failed`, `field_quality`, … |
| `backend/app/workers/` | Scheduled jobs (e.g. `csp_sync_worker`; schedule in `celery_app.py`) |
| `backend/app/routers/` | API |
| `backend/app/models/` | Database tables |
| `backend/alembic/versions/` | Database changes (one head) |
| `backend/tests/` | Tests; `tests/golden/cases.json` business cases |
| `frontend/app/admin/` | Admin screens; `frontend/app/rm/` RM; `frontend/app/csp/` the CSP's form |
| `config.py` | Every setting, with its environment variable name |

## Good to know

- **Sending happens only on the server** (public `PUBLIC_APP_URL`), 8 am – 8 pm, never to a CSP on hold.
- A send records **why** with `send_reason.because(...)`.
- New WhatsApp wordings need Meta approval once; until then the send is "pending" and retried.
- Celery does not reload code — restart workers after a change.
- On Windows, edit scripts with backslashes go in a file written with the Write tool, not a bash heredoc; scan for control characters before committing.
- Server: `/home/Ankita/Csp_Doc_Maker`; database service `postgres`, user and database `cspdocmaker`.
