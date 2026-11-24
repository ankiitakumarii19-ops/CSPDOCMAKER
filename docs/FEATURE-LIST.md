# Every feature, and who has it today

PROJECT-REGISTER No. 206 (Stage 2, TK-015). Made from `backend/app/services/feature_catalog.py`
on 24 Nov 2026 (Stages 2-9). A test (`tests/test_feature_access.py`) checks every server route belongs to
one of these and that “Today” is exactly what the route allowed before Stage 2.

The Super Admin always has every feature (except making documents, which is the RM's screen
today) and that cannot be switched off. On Setup → Feature access the Super Admin gives or takes
each feature for a role (RM, Admin, or a role they make) or one person.

## Working on CSPs

| Feature | What it is | Today | Can be given to | Note |
|---|---|---|---|---|
| Find and open CSPs | Search CSPs, open one, its photo, chat and form links; the header search. | RM, Admin | RM, Admin |  |
| Message a CSP by hand | Send one CSP a WhatsApp or email from their page. | RM, Admin | RM, Admin |  |
| Make and send documents | Choose a CSP's documents, check missing details, upload a photo, confirm and send. | RM | RM | not the Super Admin's screen |
| Action Required | The bell: CSPs with details missing, and what was done. | RM, Admin | RM, Admin |  |
| Database | Every CSP's full record, photos and documents (another RM's CSP opens view only). | RM, Admin | RM, Admin |  |
| Edit a CSP | Change a CSP's details from the Database (saved to the sheet). | RM, Admin | RM, Admin |  |
| Sheets: see and edit rows | The connected sheets' rows: read, change, add, remove. | RM, Admin | RM, Admin |  |
| Chat assistant | Ask the chat about CSPs; drafts it offers to send. | RM, Admin | RM, Admin |  |

## Watching what happened

| Feature | What it is | Today | Can be given to | Note |
|---|---|---|---|---|
| Dashboard overview | Counts, filters, CSP list and its CSV download, audit log. | Admin | RM, Admin | shows every CSP |
| Build dashboards | Make, change and see the extra dashboards. | Admin | RM, Admin | shows every CSP |
| WhatsApp messages | Every WhatsApp sent: delivered, read, replied, failed. | Admin | RM, Admin | shows every CSP |
| Emails | Every email sent: opened, bounced. | Admin | RM, Admin | shows every CSP |
| Replies to CSPs | What CSPs wrote back; send, change or skip the drafts. | Admin | RM, Admin | shows every CSP |
| Data quality | Filled-in values, corrections, guardrails, loops, feedback. | Admin | RM, Admin | shows every CSP |

## Setting up the workspace

| Feature | What it is | Today | Can be given to | Note |
|---|---|---|---|---|
| Document templates | Upload and change the Word templates. | Admin | RM, Admin |  |
| Messaging | Message wordings and channels; ask many CSPs at once. | Admin | RM, Admin | shows every CSP |
| Knowledge Base | The answers the chat and the reply agent use. | Admin | RM, Admin |  |
| Settings | See the settings; change the groups handed to Admins. | Admin | Admin |  |
| See the workspace rules | Read Workspace Rules (who may join, sign-in length). | Admin | Admin |  |
| Reply mode | Switch the reply agent between Drafts, Automatic and Off. | Super Admin only | Admin |  |
| Agents | See the background jobs; run, switch on / off, decide findings. | Super Admin only | Admin |  |

## Super Admin only

| Feature | What it is | Today | Can be given to | Note |
|---|---|---|---|---|
| Access: add and remove people | Admins may do it only if Workspace Rules says so. | Admin | — (locked) |  |
| Sign-in history and sheet sync | Who signed in when; read the access sheet now. | Super Admin only | — (locked) |  |
| Feature access | This page: who has which feature. | Super Admin only | — (locked) |  |
| Change the workspace rules | — | Super Admin only | — (locked) |  |
| Hand settings groups to Admins | — | Super Admin only | — (locked) |  |
| Connect or remove sheets | — | Super Admin only | — (locked) |  |
| Connections | The workspace's own sheets, email, WhatsApp and CRM; their passwords and keys. | Super Admin only | — (locked) |  |
| Columns | Which sheet column is which field (guessed from the sheet). | Super Admin only | — (locked) |  |
| Setup guide | Every setup step, test mode, going live, the dry run. | Super Admin only | — (locked) |  |
| Export or close the workspace | Download all its data; switch the workspace off. | Super Admin only | — (locked) |  |
| Setup done by the chat (Do it) | — | Super Admin only | — (locked) |  |

Always kept by everyone signed in: signing in, their own profile picture, the sheet freshness
chips, and “what may I use”.

**Which CSPs:** an RM acts on their own CSPs and unowned ones (as today); the Super Admin can
set an RM-type role to “every CSP”. Admins always see every CSP. Splitting by team or state
waits for each workspace's own data shape (Stage 4).
