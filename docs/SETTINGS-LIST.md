# Every server setting, and where it stands

PROJECT-REGISTER No. 204 (Stage 1, TK-005), brought up to date with No. 213-216 (Stages 3-9). Made from `backend/app/config.py` and
`backend/app/services/settings_catalog.py` on 24 Nov 2026. The rules that were
fixed inside the code and are now settings are marked “(was in the code)”.

**Workspace setting now** = each workspace's Super Admin changes it on Setup → Settings
(or by chat); the value below is the standard one — Eko's — used until they do.

| Where it stands | How many |
|---|---|
| **Workspace setting now** | 96 |
| **Workspace connection now** | 27 |
| Server only (base timer) | 11 |
| Workspace Rules (already per workspace) | 3 |
| Server only | 42 |

| Setting (server name) | Standard value | Where it stands | Why / where |
|---|---|---|---|
| `ALERTS_ENABLED` | True | **Workspace setting now** | Setup → Settings → Alerts: “Send alerts” |
| `ALERT_AGENT_FAILURES` | 3 | **Workspace setting now** | Setup → Settings → Alerts: “Alert after an agent fails” |
| `ALERT_REPEAT_HOURS` | 4 | **Workspace setting now** | Setup → Settings → Alerts: “Repeat an alert every” |
| `ALERT_TO` | '' | **Workspace setting now** | Setup → Settings → Alerts: “Who gets alerts” |
| `ALERT_WHATSAPP_FAILURES` | 5 | **Workspace setting now** | Setup → Settings → Alerts: “Alert after WhatsApps fail” |
| `ASKED_ONCE_FIELDS` | 'ao,rbo_name' | **Workspace setting now** | Setup → Settings → Records and words: “Office fields asked once” |
| `AUTO_DOCUMENTS_NEW` | True | **Workspace setting now** | Setup → Settings → Records and words: “Make documents for new records by itself” |
| `ASM_FROM_DC` | True (No. 270) | **Workspace setting now** | Setup → Settings → Records and words: “ASM is the DC” |
| `NEW_CSP_MONTHS` | 3 (No. 273) | **Workspace setting now** | Setup → Settings → Records and words: “New CSPs stay new for” |
| `EXISTING_ACTIVE_ONLY` | True (No. 275) | **Workspace setting now** | Setup → Settings → Records and words: “Existing CSPs: Active only” |
| `CALLING_SHEET_UPDATES` | True (No. 270) | **Workspace setting now** | Setup → Settings → Records and words: “Take later changes from the Calling sheet” |
| `BRAND_COLOR` | '#00B259' | **Workspace setting now** | Setup → Settings → Look and weekly email: “Main colour” |
| `BRAND_COLOR_2` | '' | **Workspace setting now** | Setup → Display → Branding: “Second colour” (No. 240) |
| `ALLOW_PERSONAL_LOOK` | True | **Workspace setting now** | Setup → Display → Branding: “People pick their own colours” (No. 240) |
| `BRAND_NAME` | 'CSPdocMaker' | **Workspace setting now** | Setup → Settings → Look and weekly email: “App name” |
| `CONTACT_FIX_MAX_TRIES` (was in the code) | 3 | **Workspace setting now** | Setup → Settings → When a message fails: “Tries before giving up on a contact” |
| `CONTACT_LOOP_BATCH` | 10 | **Workspace setting now** | Setup → Settings → When a message fails: “CSPs tried per run” |
| `CONTACT_LOOP_ENABLED` | True | **Workspace setting now** | Setup → Settings → When a message fails: “Find another way to reach the CSP” |
| `CRM_FILL_FIELDS` | 'email,address,state,gender' | **Workspace setting now** | Setup → Settings → Records and words: “Blanks the CRM fills” |
| `CSP_DATA_REQUESTS_BY_EMAIL` | False | **Workspace setting now** | Setup → Settings → Asking CSPs for details: “Ask by email when WhatsApp does not work” |
| `DATA_REQUEST_EXPIRY_DAYS` | 3 | **Workspace setting now** | Setup → Settings → Asking CSPs for details: “Form link stays open” |
| `DOCUMENTS_FEEDBACK_AFTER_MINUTES` | 15 | **Workspace setting now** | Setup → Settings → Feedback question: “Feedback asked after” |
| `DOCUMENTS_FEEDBACK_ENABLED` | True | **Workspace setting now** | Setup → Settings → Feedback question: “Ask the feedback question” |
| `DOCUMENTS_LINK_DAYS` (was in the code) | 7 | **Workspace setting now** | Setup → Settings → Documents and photo: “Document download link works for” |
| `DOCUMENTS_NOT_FOR_SECOND_TYPE` | 'BCP' | **Workspace setting now** | Setup → Settings → Documents and photo: “Documents the second type never gets” |
| `EMAILS_PAUSED` | False | **Workspace setting now** | Setup → Settings → Email: “Pause all emails” |
| `FEEDBACK_WORDING` | '' | **Workspace setting now** | Setup → Settings → Feedback question: “Feedback question wording” |
| `HEALTH_EMAIL_DAY` | 'mon' | **Workspace setting now** | Setup → Settings → Look and weekly email: “Weekly email: day” |
| `HEALTH_EMAIL_HOUR` | 9 | **Workspace setting now** | Setup → Settings → Look and weekly email: “Weekly email: hour” |
| `HEALTH_EMAIL_ON` | True | **Workspace setting now** | Setup → Settings → Look and weekly email: “Weekly health email” |
| `HEALTH_EMAIL_TO` | '' | **Workspace setting now** | Setup → Settings → Look and weekly email: “Weekly email: to” |
| `CONTACT_REPORT_ON` (No. 237) | True | **Workspace setting** | Setup → Settings → Look and weekly email: “Daily contact email” |
| `CONTACT_REPORT_HOUR` (No. 237) | 20 | **Workspace setting** | Setup → Settings → Look and weekly email: “Daily contact email: hour” |
| `CONTACT_REPORT_TO` (No. 237) | '' | **Workspace setting** | Setup → Settings → Look and weekly email: “Daily contact email: to” (blank = every Super Admin) |
| `INFO_AUTO_FIX_ENABLED` | True | **Workspace setting now** | Setup → Settings → Fixing data by itself: “Fix the lookup table by itself” |
| `JOB_CONTACT_LOOP_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Finding another way to reach a CSP: at most every” |
| `JOB_CONTACT_LOOP_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Finding another way to reach a CSP” |
| `JOB_DELIVERY_STATUS_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Checking WhatsApp delivery: at most every” |
| `JOB_DELIVERY_STATUS_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Checking WhatsApp delivery” |
| `JOB_INFO_FIX_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Fixing the lookup table: at most every” |
| `JOB_INFO_FIX_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Fixing the lookup table” |
| `JOB_NEW_RECORDS_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Making documents for new records: at most every” |
| `JOB_NEW_RECORDS_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Making documents for new records” |
| `JOB_RECORDS_SHEETS_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Reading the old / new records sheets: at most every” |
| `JOB_RECORDS_SHEETS_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Reading the old / new records sheets” |
| `JOB_REPLIES_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Answering CSP replies: at most every” |
| `JOB_REPLIES_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Answering CSP replies” |
| `JOB_RESEND_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Sending failed WhatsApps again: at most every” |
| `JOB_RESEND_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Sending failed WhatsApps again” |
| `JOB_SHEET_PHOTOS_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Taking photos from the sheet: at most every” |
| `JOB_SHEET_PHOTOS_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Taking photos from the sheet” |
| `JOB_SHEET_READ_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Reading the main sheet: at most every” |
| `JOB_SHEET_READ_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Reading the main sheet” |
| `JOB_SIGNIN_READ_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Reading the sign-in list: at most every” |
| `JOB_SIGNIN_READ_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Reading the sign-in list” |
| `JOB_VERIFY_EVERY` | 0 | **Workspace setting now** | Setup → Settings → Background jobs: “Checking old CSPs' details: at most every” |
| `JOB_VERIFY_ON` | True | **Workspace setting now** | Setup → Settings → Background jobs: “Checking old CSPs' details” |
| `LEAD_LIVE_REMARK` | 'Go Live Done' | **Workspace setting now** | Setup → Settings → Records and words: “Words that mean 'live'” |
| `LOOKUP_FILL_ENABLED` | True | **Workspace setting now** | Setup → Settings → Records and words: “Fill blanks from the lookup table” |
| `MAX_DOCUMENTS_PER_DAY` | 0 | **Workspace setting now** | Setup → Settings → Going live: “Most documents a day” |
| `MAX_WHATSAPP_PER_DAY` | 0 | **Workspace setting now** | Setup → Settings → Going live: “Most WhatsApps a day (whole workspace)” |
| `MSG_DOCUMENTS_READY` | True | **Workspace setting now** | Setup → Settings → Feedback question: ““Documents ready” WhatsApp” |
| `PASSPORT_PHOTO_DPI` | 500 | **Workspace setting now** | Setup → Settings → Documents and photo: “Photo sharpness” |
| `PASSPORT_PHOTO_HEIGHT_MM` | 45 | **Workspace setting now** | Setup → Settings → Documents and photo: “Photo height” |
| `PASSPORT_PHOTO_WIDTH_MM` | 35 | **Workspace setting now** | Setup → Settings → Documents and photo: “Photo width” |
| `PAUSE_ALL` | False | **Workspace setting now** | Setup → Settings → Going live: “Pause everything” |
| `PHOTO_PLACEHOLDER_ALLOWED` | True | **Workspace setting now** | Setup → Settings → Documents and photo: “Make documents without a photo” |
| `PHOTO_TOUCH_UP` | True | **Workspace setting now** | Setup → Settings → Documents and photo: “Touch up the photo” |
| `PHOTO_WHITE_BACKGROUND` | True | **Workspace setting now** | Setup → Settings → Documents and photo: “White background on the photo” |
| `QUALITY_SUGGEST_MIN_CSPS` | 2 | **Workspace setting now** | Setup → Settings → Fixing data by itself: “Same correction needed from” |
| `RECORD_MAIN_LENGTHS` | '8' | **Workspace setting now** | Setup → Settings → Records and words: “Main type: code length(s)” |
| `RECORD_SECOND_LENGTHS` | '9,10' | **Workspace setting now** | Setup → Settings → Records and words: “Second type: code length(s)” |
| `RECORD_TYPE_RULE` | 'code_length' | **Workspace setting now** | Setup → Settings → Records and words: “Record types” |
| `REPLY_AUTO_PER_DAY` (was in the code) | 3 | **Workspace setting now** | Setup → Settings → Replies to CSPs: “Automatic replies per CSP a day” |
| `REPLY_LOOKBACK_HOURS` (was in the code) | 72 | **Workspace setting now** | Setup → Settings → Replies to CSPs: “Read CSP messages from the last” |
| `REPLY_NEVER_ANSWER_WORDS` | '' | **Workspace setting now** | Setup → Settings → Replies to CSPs: “Never answer these topics” |
| `REPLY_QUIET_MINUTES` (was in the code) | 5 | **Workspace setting now** | Setup → Settings → Replies to CSPs: “Wait before answering” |
| `RESEND_FAILED_BATCH` | 20 | **Workspace setting now** | Setup → Settings → When a message fails: “Failed WhatsApps sent again per run” |
| `RESEND_FAILED_ENABLED` | True | **Workspace setting now** | Setup → Settings → When a message fails: “Send a failed WhatsApp again” |
| `RESEND_FIRST_WAIT_MINUTES` (was in the code) | 30 | **Workspace setting now** | Setup → Settings → When a message fails: “First wait before sending again” |
| `RESEND_HANDOVER_TRIES` (No. 237; replaces `RESEND_GIVE_UP_DAYS` - a failed WhatsApp is never given up on) | 5 | **Workspace setting** | Setup → Settings → When a message fails: “Try the alternate number after” |
| `RESEND_LONGEST_WAIT_HOURS` (was in the code) | 4 | **Workspace setting now** | Setup → Settings → When a message fails: “Longest wait between tries” |
| `SEND_DAYS` | 'mon,tue,wed,thu,fri,sat,sun' | **Workspace setting now** | Setup → Settings → Sending hours: “Sending days” |
| `SEND_HOLIDAYS` | '' | **Workspace setting now** | Setup → Settings → Sending hours: “Holidays (no sending)” |
| `SEND_MAX_PER_PERSON_DAY` | 0 | **Workspace setting now** | Setup → Settings → Sending hours: “Most messages to one person a day” |
| `SEND_TIME_ZONE` (was in the code) | '+05:30' | **Workspace setting now** | Setup → Settings → Sending hours: “Time zone” |
| `SMTP_FROM_NAME` | 'CSP DocMaker' | **Workspace setting now** | Setup → Settings → Email: “Sender name on emails” |
| `TEST_MODE` | False | **Workspace setting now** | Setup → Settings → Going live: “Test mode” |
| `TEST_MODE_EMAIL` | '' | **Workspace setting now** | Setup → Settings → Going live: “Test email address” |
| `TEST_MODE_PHONE` | '' | **Workspace setting now** | Setup → Settings → Going live: “Test WhatsApp number” |
| `VERIFY_BATCH_SIZE` | 25 | **Workspace setting now** | Setup → Settings → Asking CSPs for details: “Old CSPs checked per batch” |
| `VERIFY_END_HOUR` | 20 | **Workspace setting now** | Setup → Settings → Sending hours: “Messages stop at (hour)” |
| `VERIFY_OLD_CSPS_ENABLED` | True | **Workspace setting now** | Setup → Settings → Asking CSPs for details: “Check old CSPs' details” |
| `VERIFY_START_HOUR` | 8 | **Workspace setting now** | Setup → Settings → Sending hours: “Messages start at (hour)” |
| `VERIFY_STOP_AFTER` | 5 | **Workspace setting now** | Setup → Settings → Asking CSPs for details: “Stop a batch after failures” |
| `VERIFY_WAIT_FOR_ADDRESS` | True | **Workspace setting now** | Setup → Settings → Asking CSPs for details: “Wait for the Address tab first” |
| `WHATSAPP_NOT_RECEIVED_HOURS` (was in the code) | 24 | **Workspace setting now** | Setup → Settings → When a message fails: “Count a WhatsApp as not received after” |
| `WHATSAPP_STATUS_DAYS` | 7 | **Workspace setting now** | Setup → Settings → When a message fails: “Check delivery for” |
| `WORD_MAIN_TYPE` | 'KO' | **Workspace setting now** | Setup → Settings → Records and words: “Name of the main type” |
| `WORD_OWNER` | 'RM' | **Workspace setting now** | Setup → Settings → Records and words: “Word for the owner” |
| `WORD_RECORD` | 'CSP' | **Workspace setting now** | Setup → Settings → Records and words: “Word for a record” |
| `WORD_SECOND_TYPE` | 'Sub-KO' | **Workspace setting now** | Setup → Settings → Records and words: “Name of the second type” |
| `WORKSPACE_LIVE` | True | **Workspace setting now** | Setup → Settings → Going live: “Live” |
| `ADDRESS_SHEET_ID` | '' | **Workspace connection now** | Setup → Connections → Google Sheets: “Address sheet (optional)”. Blank outside Eko's workspace until set. |
| `ADDRESS_SHEET_TAB` | 'Address' | **Workspace connection now** | Setup → Connections → Google Sheets: “Tab in the address sheet”. |
| `CALLING_HEADER_ROW` | 2 | **Workspace connection now** | Setup → Connections → Google Sheets: “Old records sheet: heading row”. |
| `CALLING_SHEET_ID` | '' | **Workspace connection now** | Setup → Connections → Google Sheets: “Old records sheet (optional)”. Blank outside Eko's workspace until set. |
| `CALLING_SHEET_TAB` | 'Calling Sheet New' | **Workspace connection now** | Setup → Connections → Google Sheets: “Tab in the old records sheet”. |
| `GOOGLE_SHEETS_ADMIN_SHEET_NAME` | 'Admins' | **Workspace connection now** | Setup → Connections → Google Sheets: “Sign-in list: Admins tab”. |
| `GOOGLE_SHEETS_CSP_SHEET_ID` | '' | **Workspace connection now** | Setup → Connections → Google Sheets: “Main CSP sheet”. Blank outside Eko's workspace until set. |
| `GOOGLE_SHEETS_CSP_SHEET_NAME` | 'KOData' | **Workspace connection now** | Setup → Connections → Google Sheets: “Tab: main records”. |
| `GOOGLE_SHEETS_ID` | '' | **Workspace connection now** | Setup → Connections → Google Sheets: “Sign-in list sheet”. Blank outside Eko's workspace until set. |
| `GOOGLE_SHEETS_INFO_TAB_NAME` | 'INFO' | **Workspace connection now** | Setup → Connections → Google Sheets: “Tab: lookup table”. |
| `GOOGLE_SHEETS_RM_SHEET_NAME` | 'RMs' | **Workspace connection now** | Setup → Connections → Google Sheets: “Sign-in list: RMs tab”. |
| `GOOGLE_SHEETS_SUBKO_SHEET_NAME` | 'SUBKOData' | **Workspace connection now** | Setup → Connections → Google Sheets: “Tab: second record type”. |
| `GOOGLE_SHEETS_SUPER_ADMIN_SHEET_NAME` | 'SuperAdmins' | **Workspace connection now** | Setup → Connections → Google Sheets: “Sign-in list: Super Admins tab”. |
| `IMAP_HOST` | 'imap.gmail.com' | **Workspace connection now** | Setup → Connections → Email: “Inbox server (bounces)”. |
| `LEAD_HEADER_ROW` | 1 | **Workspace connection now** | Setup → Connections → Google Sheets: “New records sheet: heading row”. |
| `LEAD_SHEET_ID` | '' | **Workspace connection now** | Setup → Connections → Google Sheets: “New records sheet (optional)”. Blank outside Eko's workspace until set. |
| `LEAD_SHEET_TAB` | 'Lead raw data' | **Workspace connection now** | Setup → Connections → Google Sheets: “Tab in the new records sheet”. |
| `SMTP_FROM_EMAIL` | '' | **Workspace connection now** | Setup → Connections → Email: “Send from”. Blank outside Eko's workspace until set. |
| `SMTP_HOST` | 'smtp.gmail.com' | **Workspace connection now** | Setup → Connections → Email: “Mail server”. Blank outside Eko's workspace until set. |
| `SMTP_PASSWORD` | (secret — not shown) | **Workspace connection now** | Setup → Connections → Email: “Password”. Locked (never shown back). Blank outside Eko's workspace until set. |
| `SMTP_PORT` | 587 | **Workspace connection now** | Setup → Connections → Email: “Port”. |
| `SMTP_USERNAME` | '' | **Workspace connection now** | Setup → Connections → Email: “Sign-in address”. Blank outside Eko's workspace until set. |
| `WHATSAPP_LANGUAGE` | 'en_US' | **Workspace connection now** | Setup → Connections → WhatsApp: “Template language”. |
| `WHATSAPP_PLATFORM_URL` | 'https://indev.eko.in/whatsapp/mcp' | **Workspace connection now** | Setup → Connections → WhatsApp: “WhatsApp platform address”. Blank outside Eko's workspace until set. |
| `ZOHO_CLIENT_ID` | '' | **Workspace connection now** | Setup → Connections → CRM (Zoho, optional): “Zoho client id”. Blank outside Eko's workspace until set. |
| `ZOHO_CLIENT_SECRET` | (secret — not shown) | **Workspace connection now** | Setup → Connections → CRM (Zoho, optional): “Zoho client secret”. Locked (never shown back). Blank outside Eko's workspace until set. |
| `ZOHO_REFRESH_TOKEN` | (secret — not shown) | **Workspace connection now** | Setup → Connections → CRM (Zoho, optional): “Zoho refresh token”. Locked (never shown back). Blank outside Eko's workspace until set. |
| `ALERT_MINUTES` | 15 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `CONTACT_LOOP_MINUTES` | 30 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `CSP_SYNC_INTERVAL_MINUTES` | 1 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `EMAIL_BOUNCE_MINUTES` | 15 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `GOOGLE_SHEETS_SYNC_INTERVAL_MINUTES` | 15 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `INFO_AUTO_FIX_MINUTES` | 30 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `RESEND_FAILED_MINUTES` | 10 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `SHEET_PHOTO_MINUTES` | 15 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `SOURCE_SHEETS_INTERVAL_MINUTES` | 5 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `VERIFY_INTERVAL_MINUTES` | 15 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `WHATSAPP_STATUS_MINUTES` | 10 | Server only (base timer) | How often the server wakes the job; each workspace switches it off or slows it on Settings → Background jobs. |
| `ALLOWED_EMAIL_DOMAIN` | 'eko.co.in,ekosupport.in' | Workspace Rules (already per workspace) | Set on Setup → Workspace Rules since No. 120; this server value is the starting point. |
| `SESSION_HOURS` | 24 | Workspace Rules (already per workspace) | Set on Setup → Workspace Rules since No. 120; this server value is the starting point. |
| `SUPREME_OWNER_EMAILS` | '' | Server only | Who may open the Supreme Owner console (/platform), above every workspace (No. 240). Never a workspace setting. |
| `SUPER_ADMIN_EMAILS` | '' | Workspace Rules (already per workspace) | Set on Setup → Workspace Rules since No. 120; this server value is the starting point. |
| `APP_DEBUG` | True | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `APP_ENV` | 'development' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `APP_SECRET_KEY` | (secret — not shown) | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `ASSISTANT_DRAFT_MINUTES` | 30 | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `BACKUP_ALERT_HOURS` | 26 | Server only | The server's daily backup (BACKUP_KEEP / BACKUP_ALERT_HOURS) covers every workspace and is never switched off. |
| `BACKUP_STATUS_FILE` | '' | Server only | The server's daily backup (BACKUP_KEEP / BACKUP_ALERT_HOURS) covers every workspace and is never switched off. |
| `CELERY_BROKER_URL` | None | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `CELERY_RESULT_BACKEND` | None | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `DATABASE_ECHO` | False | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `DATABASE_HOST` | 'localhost' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `DATABASE_NAME` | 'cspdocmaker' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `DATABASE_PASSWORD` | (secret — not shown) | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `DATABASE_PORT` | 5432 | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `DATABASE_USER` | 'cspdocmaker' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `DOCUMENTS_ARCHIVE_DIR` | '' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `DOCUMENT_OUTPUT_DIR` | 'generated_documents' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `DOCUMENT_TEMPLATES_DIR` | '../templates/documents' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `EMAIL_METHOD` | 'smtp' | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |
| `GMAIL_CREDENTIALS_FILE` | (secret — not shown) | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |
| `GMAIL_SENDER_EMAIL` | 'noreply@eko.co.in' | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |
| `GOOGLE_CLIENT_ID` | '' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `GOOGLE_SHEETS_CREDENTIALS_FILE` | (secret — not shown) | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |
| `JWT_ALGORITHM` | 'HS256' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | (secret — not shown) | Server only | A sign-in code is sent before the person chooses a workspace. |
| `JWT_SECRET_KEY` | (secret — not shown) | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `LIBREOFFICE_PATH` | '' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `LOG_LEVEL` | 'INFO' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `OTP_EXPIRY_SECONDS` | 300 | Server only | A sign-in code is sent before the person chooses a workspace. |
| `OTP_LENGTH` | 6 | Server only | A sign-in code is sent before the person chooses a workspace. |
| `OTP_MAX_ATTEMPTS` | 3 | Server only | A sign-in code is sent before the person chooses a workspace. |
| `OTP_RATE_LIMIT_PER_MINUTE` | 3 | Server only | A sign-in code is sent before the person chooses a workspace. |
| `PDF_CONVERSION_TIMEOUT_SECONDS` | 120 | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `PUBLIC_APP_URL` | 'http://localhost:3000' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `REDIS_HOST` | 'localhost' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `REDIS_PORT` | 6379 | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `SESSION_COOKIE_NAME` | 'cspdm_session' | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `SMTP_USE_TLS` | True | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |
| `TEST_COPY` | False | Server only | How this server runs (addresses, keys, folders); never one workspace's choice. |
| `WHATSAPP_API_KEY` | (secret — not shown) | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |
| `WHATSAPP_API_URL` | 'https://indev.eko.in/whatsapp/mcp' | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |
| `WHATSAPP_PLATFORM_TIMEOUT_SECONDS` | 300 (was 60; No. 268) | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |
| `WHATSAPP_PLATFORM_CONNECT_TIMEOUT_SECONDS` | 15 (No. 268) | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |
| `ZOHO_DATA_CENTRE` | 'in' | Server only | How this server connects: one Google robot account (each workspace shares its sheets with it), one mail method, India's Zoho data centre. |

Never a setting (fixed for safety, plan tab “Fixed for safety”): one workspace never sees
another's data; keys are never shown back; the change history cannot be switched off;
a Super Admin can never lock themselves out.
