# CSPdocMaker — Project Tracker (plain-language version)

This is the one place that lists everything you have asked for, what is done,
and what is still left. Claude updates it every time you ask for something new.

**Last updated:** 10 October 2026

**Where this information came from:** Claude's saved notes (22 Sep – 1 Oct) and
the two project files `CHANGELOG.md` and `PROJECT-STATUS.md` (up to 6 Oct).
Claude cannot see older chats. Nothing was re-tested today, so "Done" means
"the records show it working", not "checked again today".

**What the words mean**

- **Done** — finished, and there is proof it worked
- **Not sure** — the records say it was done, but Claude has not checked
- **Waiting for you** — needs your answer, permission or a file from you
- **Stuck** — cannot move until something else happens first
- **To do** — nobody has started it yet
- **Replaced** — you later asked for something different instead

---

## 1. What the project is for

**At the start:** Make four documents for SBI Kiosk agents (CSPs) — the
**ID Card**, the **CSP Certificate**, the **Training Certificate** and the
**BCP** — using your Word templates, and email them to the agent.

- When a **new** agent is added to the Google Sheet, everything happens on
  its own: documents are made and emailed within about 3 minutes.
- For an **existing** agent, their manager (the RM) logs in and sends them.

**Now:** The same thing, but built so it could be sold to other companies too
(each company keeps its own separate data). Payment/billing is **not** part of
it — you said so.

**Your very first request** (before 22 Sep) is **not available** to Claude.

---

## 2. Everything you have asked for, in order

### September

| No. | Date | What you asked for | Status |
|---|---|---|---|
| 1 | Before 11 Sep | Your first brief | **Missing — please share** |
| 2 | 22 Sep | Keep every document (Word and PDF) forever, safely in the database | Done |
| 3 | 22 Sep | Agents already in the sheet on day one are "old" — don't email them automatically. Only newly added agents get automatic emails | Done |
| 4 | 22 Sep | If a new agent's details are complete, send automatically. If something is missing, tell their RM | Done |
| 5 | 22 Sep | The Google Sheet is always correct; check it every minute | Done |
| 6 | 22 Sep | Text the agent (SMS) after emailing | Replaced by No. 7 |
| 7 | 22 Sep | Use **WhatsApp** instead of SMS | **Stuck** (see list below) |
| 8 | 22 Sep | Admins can only watch, not send | Done |
| 9 | 22 Sep | Claude advised replacing a leaked Google access key | **Not sure** it was done |
| 10 | 23 Sep | The dates on certificates are the day the certificate is made | Done |
| 11 | 23 Sep | Only people listed in the "Authorization" sheet can log in; nobody gets an account made for them | Done |
| 12 | 23 Sep | If no RM can be found for an agent, **every** RM can see that agent | Done |
| 13 | 23 Sep | 15–20 people must be able to use it at once | Done (tested with 60) |
| 14 | 23 Sep | Pause the PDF work | Replaced by No. 15 |
| 15 | 24 Sep | Restart PDFs; agents receive PDFs only | Done |
| 16 | 24 Sep | **"I'll give my feedback on the ID Card and photo layout later — don't forget to ask me"** | **Waiting for you** |
| 17 | 24 Sep | Send emails from a Gmail account | Done |
| 18 | 24 Sep | RM can fill in missing details inside the app | Done |
| 19 | 24 Sep | Use the INFO tab to fill in DC, ASM and RM names automatically | Done |
| 20 | 24 Sep | Put the eko KIOSK logo top-left ("we'll talk about it later") | Logo done; rest of branding **to do** |
| 21 | 24–25 Sep | Pull the agent's photo out of their papers in Zoho | Done |
| 22 | 25 Sep | Only accept a Zoho record if both the agent code and phone match | Done |
| 23 | 25 Sep | Save each agent's documents in a folder named after their code | Done |
| 24 | 28 Sep | **No photo = don't make the documents.** Never use a blank photo box | Done |
| 25 | 28 Sep | **"Use the exact screens I gave you. Do not change them."** | Standing rule |
| 26 | 28 Sep | Remove SMS login codes completely | Done |
| 27 | 28 Sep | 12 screen changes from your prototype (one Login button, 6-box code, forgot password, etc.) | Behind-the-scenes part done; **screens Not sure** |

### October

| No. | Date | What you asked for | Status |
|---|---|---|---|
| 28 | 1 Oct | WhatsApp through Meta (Facebook) directly | Decided; sending **Stuck** |
| 29 | 1 Oct | Send agents a private link to fill in their own missing details; message in English, Hindi and Hinglish | Link works; **the page itself — Not sure** (records disagree) |
| 30 | 1 Oct | Write answers back into the Google Sheet | Done |
| 31 | 1 Oct | **Every photo is passport size (35×45 mm). Don't ask again.** | Standing rule — Done |
| 32 | 1 Oct | Always look in Zoho "Leads" for agent papers too | Done |
| 33 | 2 Oct | Make it a product other companies could use (separate data, Super Admin, upload your own templates, custom dashboards, automatic helpers) | Mostly done; **uploading new templates still won't work** |
| 34 | 2 Oct | No payment or billing features | Standing rule |
| 35 | 3 Oct | Messages actually get sent; block any message with a broken link | Done |
| 36 | 4 Oct | Security: limit wrong-password attempts, hide technical pages | Done |
| 37 | 5 Oct | Fix photo cut-off on ID Card, tidy addresses, proper capital letters on names, new ID Card look | Done |
| 38 | 5 Oct | Every number on the dashboard can be clicked to see the list behind it | Done |
| 39 | 6 Oct | Automatic helpers really run on a timer | Done |
| 40 | 6 Oct | Super Admin can view and edit the Google Sheets from inside the app | Done |
| 41 | 6 Oct | Ask the agent (not the RM) for Branch Name and Code | Done |
| 42 | 6 Oct | Record every login, viewable by Super Admin | Done |
| 43 | 6 Oct | Show photos as pictures in the sheet screen | Done |
| 44 | 7–9 Oct | Whatever happened on these days | **Missing — please tell me** |
| 45 | 10 Oct | Keep this tracker and update it every time | Done — this file |
| 46 | 10 Oct | Make this tracker readable, in plain language | Done — this version |
| 47 | 10 Oct | **One central database under the Super Admin.** Super Admin sees everything; RMs see their own agents; Admins only watch; each agent's sheet details, photos, original papers and documents are kept together on their record. **No company-by-company separation for now**, but build so it can be added later. A new searchable "Database" section for the Super Admin. Back up before any big change. Ask before changing anything existing. | **Waiting for you** — plan proposed, see section 3 (S1–S9). Partly replaces No. 33 (company separation is paused) |
| 48 | 11 Oct | **Super Admins create workspaces.** A Super Admin creates a workspace and adds other Super Admins, Admins or RMs to it. Anyone new who signs up as a Super Admin gets their **own empty workspace**, and cannot see any other workspace unless a Super Admin there adds them. | **Decided 11 Oct:** (a) Yes, turn workspaces on — **replaces the "no separation" part of No. 47**. (b) The present workspace is renamed **"Eko SBI Kiosk CSP"**; every new Super Admin is asked to **name their own** workspace. (c) Anyone with an @eko.co.in or @ekosupport.in email may sign up as a Super Admin and get a new workspace — **changes No. 11** for Super Admins only. (d) Super Admins add Super Admins, Admins and RMs **inside the app**; the Authorization sheet keeps working for Eko SBI Kiosk CSP only. Status: **Waiting for you** — screen designs shown 11 Oct, need approval (W1–W8) |

---

## 3. What is still left

### Needs something from you

| No. | What | Why it matters |
|---|---|---|
| A | Give the app's Google account **edit access to the Authorization sheet** | So you can add/remove RMs from inside the app |
| B | Tell me **where the full list of agents is** | Needed before WhatsApp can start |
| C | Give the **real web address** the app will live at | Right now every link sent to an agent only works on this laptop |
| D | Allow **4 new columns** in the agent sheet ("Has ID Card?", etc.) | To record which documents an agent already has |
| E | Your **feedback on the ID Card and photo layout** (promised 24 Sep) | You asked me to remind you |
| F | Is the BCP line **"CSP Operational Since"** right to show the month the certificate was made? | Possible wrong wording on the document |
| G | **INFO sheet fixes:** two Circle Heads both cover Patna/Bihar; AO and RBO columns are missing; Narottam has no email | The app can't fill these in until the sheet is fixed |
| H | "Yamunagar" vs "Yamunanagar" — the two sheets spell it differently | One district can't be filled in |
| I | What should messages be signed as? (Right now just "— Team") | Agents may not know who it's from |
| J | Was the leaked Google key replaced? | Security |

### Claude can do (some need your OK)

| No. | What | Why it matters |
|---|---|---|
| K | ~~Save a backup copy of all the code~~ **Done 11 Oct** | Right now the whole project exists only on this one laptop |
| L | ~~Back up the database~~ **Done 11 Oct** (one-off; automatic regular backups still to do) | All documents and agent data are in one place that already broke once (5 Oct) |
| M | Check whether the agent's "fill in your details" page exists | The two project files disagree |
| N | Make uploading a new template actually work | Upload is accepted but would fail when used |
| O | Check the 12 prototype screen changes are all in place | Not confirmed |
| P | Bring the two older project files up to date | They contradict each other |
| Q | Prepare it to run on a proper server (Linux) | It only runs on this laptop today |
| R | Test with lots of agents | Only ever tried with 8 |

### Central database (request No. 47) — nothing started; waiting for your OK

| No. | What | Status |
|---|---|---|
| S1 | Look at what the app already has | Done (10 Oct) — findings in Claude's reply |
| S2 | **Back up** code, database and files before any change | **Done 11 Oct** — code saved in git (save point `050737d`); database, photos and documents copied to `C:\CSPDOCMAKER-backups6-10-11\`; database test-restored and matched exactly |
| S3 | Existing "company" setup | Decided 10 Oct: **leave it as it is** — one company, nothing removed |
| S4 | Original papers | Decided 10 Oct: **keep only the photo**; papers stay in Zoho. (This changes your request No. 47, which listed original papers) |
| S5 | Move photos and papers into private storage | To do |
| S6 | Link each RM / Admin to a Super Admin | **On hold** — No. 48 (11 Oct) may replace this with workspaces. Waiting for you |
| S7 | Build the new **Database** section for the Super Admin | To do — it is a new screen, needs your OK |
| S8 | Security checks: nobody can see records by changing the web address | To do |
| S9 | Testing of all the above | To do |

### Workspaces (request No. 48)

| No. | What | Status |
|---|---|---|
| W1 | Rename present workspace to "Eko SBI Kiosk CSP" | **Done 11 Oct** — live database checked |
| W2 | Let one person belong to several workspaces, with a different role in each | **Done 11 Oct** (behind the scenes) — tested |
| W3 | Sign-up as Super Admin creates a new, empty, named workspace | Behind the scenes **done & tested**; the screen box **to do** (approved) |
| W4 | Choosing a workspace at every login when someone belongs to more than one | Behind the scenes **done & tested**; the screen **to do** (approved) |
| W5 | Super Admin adds / removes people in the app | Behind the scenes **done & tested**; the screen **to do** (approved) |
| W6 | New workspaces never read Eko's Google Sheets | **Done 11 Oct** — tested |
| W7 | Security tests: nobody sees another workspace | **Done 11 Oct** — 20 new tests; all 771 tests pass |
| W8 | Backup again just before the change | **Done 11 Oct** — database-before-workspaces.dump |

### Stuck until something else is done

- **WhatsApp messages** — waits on B and C, and Meta must approve the message wording.
- **RM access screen** — waits on A.
- **Logo and branding** — waits for a better-quality logo from you.

---

## 4. Rules you've set that always apply

- Use your screens exactly as given; ask before changing anything.
- Every photo is passport size, 35×45 mm.
- Never make documents without a real photo.
- Always search Zoho "Leads" too.
- Only people on the Authorization sheet can log in.
- No payment or billing features.


---

## 5. What to do next (my suggestion)

1. **Let me save a backup of the code and the database** (K and L) — biggest risk right now.
2. **Answer C (web address) and B (agent list)** — this unlocks WhatsApp and the agent links.
3. Give me your **ID Card feedback** (E).

---

## Change log for this tracker

| Date | Change |
|---|---|
| 10 Oct 2026 | Tracker created |
| 10 Oct 2026 | Rewritten in plain language at your request |
| 10 Oct 2026 | Added No. 47 (central database) and tasks S1–S9 |
| 10 Oct 2026 | Your 4 answers recorded on S2, S3, S4, S6 |
| 11 Oct 2026 | Backup done and checked (S2, K, L). Found and excluded a copy of the passwords file from git |
| 11 Oct 2026 | Added No. 48 (workspaces created by Super Admins); flagged 2 conflicts; S6 on hold |
| 11 Oct 2026 | Your answers on No. 48 recorded; tasks W1–W8 added |
| 11 Oct 2026 | Workspaces built behind the scenes and tested (W1, W2, W6, W7, W8 done). Screens still to do |
