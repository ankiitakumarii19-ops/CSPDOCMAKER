# Release checklist — before every push to the live server

No. 173 (1 Nov 2026), from the *Agentic AI Development Principles & Standards*
v1.0 (B12 testing, B13 controlled deployment, F definition of done). Copy
this list into the push's register row, or into the commit message, with
each box ticked or a reason it does not apply. Claude follows it too.

## 1. Before the push (laptop)

- [ ] **The request is in PROJECT-REGISTER.md** with its number, the owner's
      choices, and what was built.
- [ ] **Full automatic tests passed** — from `backend/`:
      `PYTHONPATH=. PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
      Write the count: `____ passed, ____ failed`. Zero failed, or each failure
      explained.
- [ ] **Golden cases passed** (`tests/test_golden_cases.py`); a rule changed
      on purpose changed its case in the same commit.
- [ ] **Screens type-check and lint** — from `frontend/`:
      `npx tsc --noEmit -p .` and `npx eslint <changed files>` (no new errors).
- [ ] **No secret in the change**: no `.env`, credentials, tokens, test logins;
      no control characters in edited files.
- [ ] **AI_SPEC.md** has the new or changed decision; **SKILL.md** if what the
      app does changed.
- [ ] **A database change** has a migration with a downgrade, and the
      register says "back up first".

## 2. On the test copy (server)

- [ ] **Deployed to the test copy first** (DEPLOY.md → "Test copy"):
      `git pull` then
      `docker compose -p cspdocmaker-test -f docker-compose.prod.yml --env-file deploy/.env.test up -d --build`
- [ ] **Seen working in a browser** on the test copy: every changed screen
      opened, the main path tried, nothing red in the browser console.
      Write what was checked.
- [ ] **Reviewed by a second person** (not the one who made the change):
      name ________, date ________. For a change to what is sent to CSPs or
      written to a sheet, the reviewer reads the register row first.

## 3. On the live app (server)

- [ ] **Database backed up** first (DEPLOY.md → "Backups"); file name noted.
- [ ] `git pull` and `docker compose -f docker-compose.prod.yml --env-file deploy/.env.production up -d --build`
- [ ] **Health**: `curl -s https://indev.eko.in/csp-docmaker/api/health`
      says healthy; the coloured sheet chips turn green within a few minutes.
- [ ] **Watched for 30 minutes**: no alert email, Agents page has no new
      failures, `logs -f api worker` shows no errors.

## 4. If it goes wrong — rollback

1. `git log --oneline -5` → the last good commit.
2. `git checkout <good commit>` then the `up -d --build` line above.
3. If the change altered the database and the old code cannot read it:
   restore the backup taken in step 3
   (`gunzip -c ~/cspdocmaker-<date>.sql.gz | docker compose ... exec -T postgres psql -U cspdocmaker cspdocmaker`
   into an empty database) — ask before doing this: it removes everything
   written since the backup.
4. Record what happened in the register.
