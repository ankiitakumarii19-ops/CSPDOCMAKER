# SaaS upgrade plan (No. 239, 25 Nov 2026)

Request: the "Productize existing CSPDOCMAKER into a customizable, multi-tenant
SaaS platform" brief, with the instruction **"don't change logic"**.

Ground rule for every stage below: **nothing that decides what happens to a CSP
changes** — documents, sending, retries, matching, holds, RM-to-CSP rules,
sheets, Zoho, WhatsApp. Golden cases (125) must pass unchanged after every stage.
All database changes only ADD tables or columns; no existing row is rewritten.

---

## Stage 1 — Audit: what already exists (checked in the code, 25 Nov)

| Brief section | Already in the app | Where |
|---|---|---|
| 4 Multi-tenant | Workspaces = organisations. Every record carries `workspace_id`; one filter scopes every query; membership re-checked on every request; a test reads 40+ list screens as another workspace and must see nothing. | `workspace_context.py`, `workspace_member.py`, `tests/test_safety*`, AI_SPEC D51 |
| 4 Storage per org | PDFs stored in Postgres per workspace; `Workspace.document_storage` / `storage_config`. | `models/workspace.py`, D5 |
| 5 Roles | Super Admin / Admin / RM, plus **own roles** built on RM or Admin, a role × feature grid (28 features), per-person exceptions, server refuses on every route. RM "own / all CSPs" scope. | `feature_catalog.py`, `feature_access.py`, Setup → Feature access, D44 |
| 3 Org branding | App name + main colour per workspace; 9 colour looks + 15 design styles chosen by the Super Admin for the whole workspace. | `settings_catalog.py` (brand_name, brand_color, ui_theme, ui_style), `admin/Display.tsx`, D49 |
| 3 / 9 Org email + integrations | Own sheets, SMTP sender, IMAP, WhatsApp platform, Zoho per workspace; secrets encrypted, never returned or logged; Test button per connection; Eko's connections invisible to other workspaces. | `connection_catalog.py`, `secret_store.py`, Setup → Connections, D45 |
| 3 Org workflow settings | 36+ settings per workspace (hours, retries, feedback, replies, photo, alerts, jobs) with history and undo. | Setup → Settings, D43, D46–D50 |
| 6 Templates | Word templates per workspace: upload, placeholder map, "use suggestion", photo cell, active on/off, a version number. | `document_template.py`, Document Templates, D47 |
| 7 Dashboards | Workspace dashboards with widgets (metric / table / breakdown), order and width, built by Admins. | `dashboard.py`, `DashboardBuilder.tsx` |
| 10 Org admin | Export a workspace (zip), close a workspace (switch off, delete nothing), go-live checklist, pause all, test mode. | `workspace_admin_router.py`, Setup guide, D50–D51 |
| 12 UI | Every screen size checked (360 → 1920), dark mode, loading/empty states, confirmations. | D39, D40 |

### What is missing (the real work)

1. **Each person's own look** — today only light/dark is personal, and it sits in the browser, not the account. Colours, fonts, sizes, spacing, menu, accessibility are workspace-wide only.
2. **Each person's own dashboard** — order and show/hide are set for everyone.
3. **Organisation logo, second colour, "may people change their own look"** switch.
4. **Notification choices per person** (in-app / email / WhatsApp / SMS for staff alerts), with the must-have ones locked on.
5. **Named starter roles** Manager / Employee / Reviewer / Viewer (own roles exist; these ready-made ones don't).
6. **Template versions** kept and restorable, draft → test with a sample record → publish, categories, required fields.
7. **Platform owner console** above all workspaces — today "Super Admin" means the owner of one workspace; nobody sees across workspaces.
8. **Two-organisation tests** for look and branding, and "workspace admin cannot open the platform console".

Not in the app and not proposed now: SMS sending (no SMS provider exists), Google Drive storage, outgoing webhooks / REST connections, Postgres row-level security (see "Decisions").

---

## Stage 2 — My Appearance (each person)

Settings → **Appearance & Personalization**, for every role including RMs.

- Mode: light / dark / follow the device.
- Colours: background, side menu, accent, buttons, cards, borders (each "use the workspace's").
- Text: font (Inter, Roboto, Poppins, Open Sans, Lato, device font), text size, heading size, weight, line spacing.
- Layout: menu open/closed, menu left/right, compact / comfortable / spacious, rounded / square cards, table density.
- Accessibility: high contrast, reduced motion, interface scale (90–150 %), visible keyboard focus everywhere.
- Live preview, Save, Reset to the workspace's look, Undo to last saved.
- Order applied at sign-in: built-in Eko look → workspace Display choice → the person's own choices.
- A colour pair that fails readable contrast is refused with a reason.

Stored: new table `user_preferences` (user, workspace, JSON of choices, updated). Applied as variables on the page only for that person — never in shared CSS or shared state. Fonts loaded by Next.js itself (no new package).

## Stage 3 — Organisation branding + notifications

- Setup → Display gains: logo upload (PNG/SVG, size-checked, stored in the database per workspace), second colour, switch "people may change their own look" (on by default; when off, personal colours are ignored but accessibility choices still apply).
- Settings → **Notifications** (each person): Action Required, alerts emails, weekly health email, daily contact email — in-app / email / WhatsApp. Locked on: sign-in codes, failure alerts to Super Admins. SMS shown as "not connected".
- Messages to CSPs are not touched.

New tables: `user_notification_prefs`; logo as a workspace file row.

## Stage 4 — Roles and isolation checks

- "Add starter roles" button on Feature access: Manager, Employee, Reviewer, Viewer as ordinary own roles (editable, removable). Nothing changes for existing people.
- Tests added: two workspaces with different branding; one person's font never reaches another; a workspace Super Admin is refused the platform console; existing RM / Admin screens unchanged.
- RM-to-CSP rules (No. 234) unchanged.

## Stage 5 — Templates and my dashboard

- Templates: every upload kept as a version (today's file becomes version 1 automatically, as a copy); draft → **Test** (makes a PDF from a chosen record, sends nothing, saves nothing to the CSP) → Publish; restore an old version; category; required fields. Generation keeps reading the active published file exactly as today.
- Dashboard: each person can reorder and hide widgets and pick a layout; "Back to workspace default". Admins' dashboards stay the default. Numbers and rules behind widgets unchanged.

New tables: `document_template_versions`, `user_dashboard_layouts`.

## Stage 6 — Platform owner console

- Separate page `/platform`, only for emails in `PLATFORM_OWNER_EMAILS` (server setting, not in any sheet or screen).
- Shows: workspaces (active / closed), people, documents made, failed generations, storage per workspace, sheet / WhatsApp / email health, backup state.
- Actions: suspend / reactivate a workspace (uses the existing on/off), announcement banner to all or one workspace.
- Never opens a workspace's documents, photos or CSP details — counts only.

New table: `platform_announcements`.

## Stage 7 — Testing and hand-over

- Full test run + golden cases + the brief's 12 checks (list below).
- Migrations tried on a copy of the live database (from the daily backup) before the server: row counts before = after.
- Screens checked at 360 / 768 / 1024 / 1440 / 1920.
- AI_SPEC.md, FEATURE-LIST.md, SETTINGS-LIST.md, register updated.

The brief's checks → where tested: 1–2 Stage 2; 3 Stage 3; 4–5 Stage 4; 6–8 golden + full suite every stage; 9–10 Stage 2; 11 Stage 7; 12 Stage 7.

---

## Owner's answers (25 Nov 2026, No. 240)

1. **Billing: IN.** "For now we are doing billing." Stage 6 also builds plans, trials, usage counters, quotas (documents, storage, people), subscription status, payment-gateway readiness, white-label / custom domain fields. No charging is switched on; Eko (workspace 1) is on an unlimited plan; a limit only applies where the Supreme Owner sets one. Replaces the 2 Oct 2026 "no billing" rule.
2. **Super Owner = the workspace's owner** (today's Super Admin). A new **Supreme Owner** sits above all workspaces: sees only non-personal numbers (counts, health, storage, usage, plans) and manages workspaces (suspend / reactivate, plans, announcements). Who: emails in the server setting SUPREME_OWNER_EMAILS (the owner fills it in).
3. **Each workspace sees only its own data** — kept as today (one filter + the safety test); Stage 4 adds two-workspace tests.

## Progress

| Stage | State |
|---|---|
| 1 Audit | Done 25 Nov |
| 2 Each person's own look | Built 25 Nov, tested — not pushed |
| 3 Branding + notifications | Built 25 Nov, tested — not pushed |
| 4 Ready-made roles + isolation checks | Built 25 Nov, tested — not pushed |
| 5 Template versions / test / category + my dashboard | Built 25 Nov, tested — not pushed |
| 6 Supreme Owner console, plans, announcements | Built 25 Nov, tested — not pushed |
| 7 Testing, migration check, documents | Done 25 Nov (see below) |

## Database changes (all only ADD; each can be undone)

| Step | Adds |
|---|---|
| c8e0a2b4d6f9 | table `user_preferences` (each person's look) |
| d9f1b3c5e7a0 | table `workspace_files` (logo); `user_preferences.notifications`, `.dashboards` |
| e0a2c4e6b8d1 | table `document_template_versions`; `document_templates.category` |
| f2b4d6a8c0e3 | tables `plans`, `workspace_subscriptions`, `platform_announcements`; rows: plan Unlimited, Eko on it |

Checked 25 Nov on throwaway copies of the local databases (`livedb`: 56 rows; the working database: 8,133 rows in 45 tables): upgrade → every existing table identical over its existing columns; undo → identical and the new tables gone; upgrade again → identical.

## The brief's 12 checks

| # | Check | Where | Result |
|---|---|---|---|
| 1 | Two people in one workspace keep different looks | test_my_look + browser | pass |
| 2 | One person's font never reaches another | test_my_look + browser | pass |
| 3 | Two organisations, completely different branding | test_branding_and_notifications | pass |
| 4 | No access to another organisation's records | test_safety (40+ list routes) + test_roles_and_isolation (by id, forged sign-in) | pass |
| 5 | Workspace admins refused the platform console | test_platform_console + browser | pass |
| 6 | Existing RM / Admin work | full suite | see register No. 241 |
| 7 | CSP documents still made | full suite + golden cases + template test run | see register No. 241 |
| 8 | Validation and notification work | full suite + golden cases | see register No. 241 |
| 9 | Look kept after signing in again | test_my_look + browser reload | pass |
| 10 | Reset to defaults | test_my_look + browser | pass |
| 11 | Every screen size | browser, 360-1920 | pass |
| 12 | Existing data kept by the database changes | migration check above | pass |

## Not done, on purpose
- Postgres row-level security (owner: isolation as today).
- A payment gateway, charging, SMS for staff, outgoing webhooks / REST connections, Google Drive storage — readiness fields only where the brief asked (plans, subscription, provider reference, white-label, own domain).
- Custom domains and white-labelling are recorded per workspace but not yet served (needs the server's front door set up per domain).
