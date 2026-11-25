"""
CSP DocMaker — the settings each workspace's Super Admin chooses
(PROJECT-REGISTER No. 199 / 204, Stage 1: Settings centre, TK-005 - TK-013)

Every entry here is a server setting (app/config.py) that a workspace may
now set for itself. A workspace that never changes one keeps the server's
value — Eko's value today — so nothing changes for Eko until its Super Admin
changes something.

How a value reaches the code: get_settings() returns a view that, inside a
workspace, answers these keys with that workspace's own value
(app/config.py, services/workspace_settings.py). The code that uses them
did not have to change.

Only settings read at the moment they are used are here. Not here yet, on
purpose:
  * how often each job runs — the scheduler's timings are fixed when the
    server starts (Stage 7: each job on / off and how often);
  * the sign-in code (length, minutes, tries) — a code is sent before the
    person has chosen a workspace, so it cannot be one workspace's;
  * the photo size — the documents' photo box is fixed in the Word
    templates; it moves with the documents (Stage 5);
  * connections, keys and addresses (Stage 3), and anything that keeps one
    workspace's data from another (never a setting).

No AI (No. 116): the chat finds a setting by the fixed words listed in
`words`, never by guessing.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

INT, BOOL, TEXT, CHOICE, LIST = "int", "bool", "text", "choice", "list"

# No. 228: the looks on Setup → Display (frontend/app/admin/Display.tsx and
# globals.css hold what each one looks like).
UI_THEMES = ("classic", "ocean", "royal", "sunset", "rose", "forest",
             "graphite", "compact", "large")
# No. 229: design styles — shapes, shadows and surfaces, on top of a look.
UI_STYLES = ("standard", "clay", "neumorph", "glass", "maximal", "minimal",
             "brutal", "flat", "material", "skeuo", "neon", "retro", "paper",
             "bento", "aurora")

# Record fields a list setting may name (field_ownership.ALL_FIELDS).
RECORD_FIELDS = ("csp_code", "name", "mobile", "email", "gender", "address",
                 "district", "state", "branch_name", "branch_code",
                 "branch_contact", "ao", "rbo_name", "rbo_contact", "lho",
                 "dc", "dc_email", "dc_contact", "rm_name", "asm_name",
                 "asm_email", "asm_contact")

# Fixed UTC offsets (no daylight saving needed for the places Eko works;
# a fixed offset also needs no time-zone database on the server).
TIME_ZONES = ["-08:00", "-05:00", "+00:00", "+01:00", "+03:00", "+04:00",
              "+05:00", "+05:30", "+05:45", "+06:00", "+07:00", "+08:00",
              "+09:00", "+10:00"]


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    about: str


@dataclass(frozen=True)
class Setting:
    key: str              # the attribute on app.config.Settings
    group: str
    label: str            # plain words, shown on the screen and in the chat
    help: str             # what it is
    effect: str           # what changing it does — shown before saving
    kind: str = INT
    unit: str = ""
    min: Optional[int] = None
    max: Optional[int] = None
    choices: Tuple[str, ...] = ()
    words: Tuple[str, ...] = field(default_factory=tuple)  # chat words


GROUPS: List[Group] = [
    Group("hours", "Sending hours",
          "When messages to CSPs may go out. Outside these hours they wait."),
    Group("asking", "Asking CSPs for details",
          "The form link, and checking old CSPs' details."),
    Group("retries", "When a message fails",
          "Sending again, and finding another way to reach the CSP."),
    Group("feedback", "Feedback question",
          "“Did you get your documents? 1 / 2 / 3”."),
    Group("replies", "Replies to CSPs",
          "How the reply agent reads and answers what CSPs write back."),
    Group("documents", "Documents and photo",
          "Download links and how the photo is prepared."),
    Group("email", "Email", "Emails the app sends."),
    Group("alerts", "Alerts",
          "Emails to the Super Admins when something keeps failing."),
    Group("selffix", "Fixing data by itself",
          "When the app corrects its lookup table on its own."),
    Group("jobs", "Background jobs",
          "Each job on / off for this workspace, and at most how often."),
    Group("look", "Look and weekly email",
          "The app's name and colour, and the weekly health email."),
    Group("golive", "Going live",
          "Test mode, going live and the pause-all switch (also on Setup → "
          "Setup guide)."),
    Group("data", "Records and words",
          "Your record types, the words the app uses, and who fills what. "
          "Which sheet column is which field: Setup → Columns."),
]

SETTINGS: List[Setting] = [
    # ---- sending hours -------------------------------------------------
    Setting("verify_start_hour", "hours", "Messages start at (hour)",
            "The first hour of the day messages may go (24-hour clock).",
            "Messages waiting overnight start going from this hour.",
            unit="o'clock", min=0, max=23,
            words=("start hour", "sending starts", "messages start",
                   "start time", "start at")),
    Setting("verify_end_hour", "hours", "Messages stop at (hour)",
            "No message goes from this hour on (24-hour clock).",
            "Messages due after this hour wait until the next morning.",
            unit="o'clock", min=1, max=24,
            words=("end hour", "stop hour", "sending stops", "messages stop",
                   "end time", "stop at")),
    Setting("send_time_zone", "hours", "Time zone",
            "The clock the sending hours follow (hours from UTC; India is "
            "+05:30).",
            "The sending hours are read on this clock.",
            kind=CHOICE, choices=tuple(TIME_ZONES),
            words=("time zone", "timezone")),
    # ---- asking CSPs ---------------------------------------------------
    Setting("data_request_expiry_days", "asking", "Form link stays open",
            "How long a CSP's form link works. An unanswered link that runs "
            "out is replaced by a new one.",
            "New links last this long (links already sent keep their end "
            "date). The reply wording that says “3 din” is not changed — "
            "edit it in the Knowledge Base if you change this.",
            unit="days", min=1, max=30,
            words=("link days", "form link", "link stays open", "link expiry",
                   "link length")),
    Setting("csp_data_requests_by_email", "asking",
            "Ask by email when WhatsApp does not work",
            "If off, a CSP is asked for details on WhatsApp only and waits "
            "until WhatsApp works.",
            "On: a CSP WhatsApp cannot reach is emailed the form instead.",
            kind=BOOL, words=("ask by email", "email fallback",
                              "requests by email")),
    Setting("verify_old_csps_enabled", "asking", "Check old CSPs' details",
            "Send old CSPs (from the Calling sheet) the data verification "
            "message.",
            "Off: no new verification messages go; ones already sent are "
            "kept.",
            kind=BOOL, words=("verification", "verify old", "check old csps",
                              "data verification")),
    Setting("verify_batch_size", "asking", "Old CSPs checked per batch",
            "How many old CSPs get the verification message in each batch.",
            "More per batch = everyone asked sooner, more replies at once.",
            unit="CSPs", min=1, max=200,
            words=("batch size", "verification batch", "per batch")),
    Setting("verify_stop_after", "asking", "Stop a batch after failures",
            "A batch stops when this many sends in a row fail.",
            "Lower = stops sooner when WhatsApp is having trouble.",
            unit="failures in a row", min=1, max=50,
            words=("stop after", "failures in a row")),
    Setting("verify_wait_for_address", "asking",
            "Wait for the Address tab first",
            "Old CSPs are checked only after the Address tab has been read "
            "once, so their form shows the address.",
            "Off: verification can start before addresses are read.",
            kind=BOOL, words=("wait for address", "address first")),
    # ---- retries -------------------------------------------------------
    Setting("resend_failed_enabled", "retries",
            "Send a failed WhatsApp again",
            "A WhatsApp the platform failed to send is sent again until it "
            "goes (not when the number is not on WhatsApp).",
            "Off: a failed WhatsApp stays failed until someone sends it.",
            kind=BOOL, words=("resend", "send again", "retry", "retries")),
    Setting("resend_first_wait_minutes", "retries", "First wait before sending again",
            "Wait after the first failure; each later wait doubles.",
            "Shorter = sent again sooner after a failure.",
            unit="minutes", min=5, max=720,
            words=("first wait", "retry wait", "resend wait")),
    Setting("resend_longest_wait_hours", "retries", "Longest wait between tries",
            "The doubling waits never grow past this.",
            "Shorter = tried more often after many failures.",
            unit="hours", min=1, max=48,
            words=("longest wait", "max wait")),
    Setting("resend_handover_tries", "retries", "Try the alternate number after",
            "A failed WhatsApp is never given up on (No. 237). After this "
            "many failed tries to the same number, the alternate number(s) "
            "are tried, then email. A WhatsApp or Meta outage does not count.",
            "Fewer = moves to the alternate number sooner.",
            unit="tries", min=1, max=20,
            words=("handover", "alternate after", "tries before alternate",
                   "give up", "stop retrying")),
    Setting("resend_failed_batch", "retries", "Failed WhatsApps sent again per run",
            "How many are sent again each time the job runs.",
            "Higher = clears a backlog faster.",
            unit="messages", min=1, max=200,
            words=("resend batch",)),
    Setting("contact_loop_enabled", "retries", "Find another way to reach the CSP",
            "When a WhatsApp does not reach the phone or an email bounces: "
            "try the alternate number, else ask on the other channel.",
            "Off: an unreachable CSP is only listed, not contacted another "
            "way.",
            kind=BOOL, words=("contact loop", "alternate number",
                              "another way")),
    Setting("contact_loop_batch", "retries", "CSPs tried per run",
            "How many unreachable CSPs the contact loop works on each run.",
            "Higher = clears a backlog faster.",
            unit="CSPs", min=1, max=100, words=("contact batch",)),
    Setting("contact_fix_max_tries", "retries", "Tries before giving up on a contact",
            "How many times the contact loop tries one CSP.",
            "Higher = keeps trying the same CSP longer.",
            unit="tries", min=1, max=10, words=("contact tries", "max tries")),
    Setting("whatsapp_not_received_hours", "retries",
            "Count a WhatsApp as not received after",
            "A sent WhatsApp not delivered after this long is marked “not "
            "received”, which starts the contact loop.",
            "Shorter = the contact loop starts sooner.",
            unit="hours", min=1, max=168,
            words=("not received", "not delivered after")),
    Setting("whatsapp_status_days", "retries", "Check delivery for",
            "For how long after sending the app checks delivered / read / "
            "replied.",
            "Longer = later replies are still caught.",
            unit="days", min=1, max=30, words=("status days", "check delivery")),
    # ---- feedback ------------------------------------------------------
    Setting("documents_feedback_enabled", "feedback", "Ask the feedback question",
            "After “documents ready”, ask whether they arrived: 1 got them, "
            "2 did not, 3 something wrong.",
            "Off: no feedback question is sent.",
            kind=BOOL, words=("feedback", "feedback question")),
    Setting("documents_feedback_after_minutes", "feedback", "Feedback asked after",
            "How long after the “documents ready” WhatsApp the question goes.",
            "Questions not yet sent wait this long from their documents "
            "message.",
            unit="minutes", min=1, max=10080,
            words=("feedback delay", "feedback after", "feedback time")),
    # ---- replies -------------------------------------------------------
    Setting("reply_lookback_hours", "replies", "Read CSP messages from the last",
            "Messages older than this are not answered by the reply agent.",
            "Longer = older messages also get a reply.",
            unit="hours", min=1, max=336,
            words=("reply lookback", "lookback", "look back")),
    Setting("reply_quiet_minutes", "replies", "Wait before answering",
            "An automatic reply waits until the CSP has been quiet this long, "
            "so it answers everything they wrote at once.",
            "Shorter = answers sooner, maybe before they finish writing.",
            unit="minutes", min=0, max=120, words=("quiet", "reply wait")),
    Setting("reply_auto_per_day", "replies", "Automatic replies per CSP a day",
            "The most automatic replies one CSP gets in a day.",
            "Higher = more replies; lower = less risk of a loop.",
            unit="replies", min=1, max=20,
            words=("replies per day", "auto replies", "reply limit")),
    # ---- documents -----------------------------------------------------
    Setting("documents_link_days", "documents", "Document download link works for",
            "The link in the “documents ready” WhatsApp.",
            "New links last this long; links already sent keep theirs.",
            unit="days", min=1, max=90,
            words=("download link", "document link")),
    Setting("photo_touch_up", "documents", "Touch up the photo",
            "A light studio touch-up: colour, contrast, brightness, a little "
            "sharpening. Nothing is moved or removed.",
            "Applies to documents made from now on.",
            kind=BOOL, words=("touch up", "touch-up")),
    Setting("photo_white_background", "documents", "White background on the photo",
            "Passport framing with a white background, made on the server "
            "with the person's real face.",
            "Applies to documents made from now on.",
            kind=BOOL, words=("white background", "background")),
    Setting("photo_placeholder_allowed", "documents", "Make documents without a photo",
            "If on, a document can be made with an empty photo box when no "
            "photo is found.",
            "Off: a missing photo stops the documents until a photo is found.",
            kind=BOOL, words=("without photo", "placeholder", "no photo")),
    # ---- email ---------------------------------------------------------
    Setting("emails_paused", "email", "Pause all emails",
            "Hold every email (documents, chat emails…). Sign-in codes still "
            "go.",
            "On: emails wait and go out once this is turned off.",
            kind=BOOL, words=("pause emails", "emails paused", "pause email",
                              "email pause")),
    Setting("smtp_from_name", "email", "Sender name on emails",
            "The name people see the emails come from.",
            "Emails sent from now on show this name.",
            kind=TEXT, min=1, max=100,
            words=("sender name", "from name", "email name")),
    # ---- alerts --------------------------------------------------------
    Setting("alerts_enabled", "alerts", "Send alerts",
            "Email the Super Admins when a sheet read is stuck, an agent "
            "keeps failing or WhatsApps are failing.",
            "Off: problems are still shown in the app but not emailed.",
            kind=BOOL, words=("alerts", "alert emails")),
    Setting("alert_repeat_hours", "alerts", "Repeat an alert every",
            "An unfixed problem is emailed again after this long.",
            "Shorter = more reminder emails.",
            unit="hours", min=1, max=72, words=("alert repeat", "repeat alert")),
    Setting("alert_agent_failures", "alerts", "Alert after an agent fails",
            "Runs in a row that must fail before an agent's alert.",
            "Lower = told sooner, more false alarms.",
            unit="times in a row", min=1, max=20,
            words=("agent failures",)),
    Setting("alert_whatsapp_failures", "alerts", "Alert after WhatsApps fail",
            "Failed WhatsApps in the last hour before an alert.",
            "Lower = told sooner, more false alarms.",
            unit="failures", min=1, max=100,
            words=("whatsapp failures",)),
    # ---- self-fixing ---------------------------------------------------
    Setting("info_auto_fix_enabled", "selffix", "Fix the lookup table by itself",
            "When enough CSPs give the same AO / RBO correction, the app "
            "corrects its lookup table (INFO) itself.",
            "Off: corrections stay suggestions for a person to apply.",
            kind=BOOL, words=("auto fix", "info fix", "fix info")),
    Setting("quality_suggest_min_csps", "selffix", "Same correction needed from",
            "How many CSPs must give the same correction before it counts.",
            "Higher = fewer, surer corrections.",
            unit="CSPs", min=2, max=50,
            words=("same correction", "min csps")),
]

SETTINGS += [
    # ---- No. 211 (Stage 4): records, words, who fills what ---------------
    Setting("record_type_rule", "data", "Record types",
            "Two types told apart by the code's length (Eko: KO and Sub-KO), "
            "or one type for every record.",
            "Decides each record's type from now on (documents and wording "
            "that depend on the type follow).",
            kind=CHOICE, choices=("code_length", "one_type"),
            words=("record types", "record type")),
    Setting("record_main_lengths", "data", "Main type: code length(s)",
            "Code lengths of the main type, e.g. 8.",
            "Records with these code lengths are the main type.",
            kind=TEXT, min=1, max=20, words=("main type length",)),
    Setting("record_second_lengths", "data", "Second type: code length(s)",
            "Code lengths of the second type, e.g. 9,10.",
            "Records with these code lengths are the second type.",
            kind=TEXT, min=0, max=20, words=("second type length",)),
    Setting("word_record", "data", "Word for a record",
            "What a record is called (Eko: CSP).",
            "Used where the app names a record.", kind=TEXT, min=1, max=30,
            words=("word for a record", "record word")),
    Setting("word_owner", "data", "Word for the owner",
            "What the person who owns records is called (Eko: RM).",
            "Used where the app names the owner.", kind=TEXT, min=1, max=40,
            words=("word for the owner", "owner word")),
    Setting("word_main_type", "data", "Name of the main type",
            "Eko: KO.", "Printed where the type is named (e.g. the Training "
            "Certificate).", kind=TEXT, min=1, max=30,
            words=("main type name",)),
    Setting("word_second_type", "data", "Name of the second type",
            "Eko: Sub-KO.", "Printed where the type is named.", kind=TEXT,
            min=1, max=30, words=("second type name",)),
    Setting("asked_once_fields", "data", "Office fields asked once",
            "Office fields a record's person is asked for when the lookup "
            "table cannot fill them (Eko: AO, RBO Name).",
            "These are added to the form when blank.", kind=LIST,
            choices=RECORD_FIELDS, words=("asked once",)),
    Setting("crm_fill_fields", "data", "Blanks the CRM fills",
            "Fields filled from the CRM when blank (Eko: email, address, "
            "state, gender).", "Only these are taken from the CRM.",
            kind=LIST, choices=("email", "address", "state", "gender"),
            words=("crm fills", "crm fill")),
    Setting("lookup_fill_enabled", "data", "Fill blanks from the lookup table",
            "Blank office fields are filled from the lookup table (Eko: "
            "INFO). A filled value is never replaced.",
            "Off: blank office fields stay blank until a person fills them.",
            kind=BOOL, words=("lookup fill", "fill from info")),
    Setting("auto_documents_new", "data", "Make documents for new records by itself",
            "A new record that goes live gets its documents made and sent "
            "without anyone pressing a button.",
            "Off: documents are made only when someone starts them.",
            kind=BOOL, words=("auto documents", "documents by itself")),
    # ---- No. 212 (Stage 5): documents and photo -------------------------
    Setting("documents_not_for_second_type", "documents",
            "Documents the second type never gets",
            "Document codes (Setup → Document Templates) the second record "
            "type is never sent (Eko: BCP — a Sub-KO never gets one).",
            "Those documents are left out for the second type, whoever asks.",
            kind=LIST, words=("not for second type", "never gets")),
    Setting("passport_photo_width_mm", "documents", "Photo width",
            "The printed width of the photo on every document (Eko: 35).",
            "Documents made from now on; check a template's photo box fits.",
            unit="mm", min=20, max=60, words=("photo width",)),
    Setting("passport_photo_height_mm", "documents", "Photo height",
            "The printed height of the photo (Eko: 45).",
            "Documents made from now on.", unit="mm", min=20, max=70,
            words=("photo height",)),
    Setting("passport_photo_dpi", "documents", "Photo sharpness",
            "Dots per inch the photo is made at (Eko: 500).",
            "Higher = sharper, bigger files.", unit="DPI", min=150, max=1200,
            words=("photo sharpness", "dpi")),
    # ---- No. 213 (Stage 6): messages ------------------------------------
    Setting("send_days", "hours", "Sending days",
            "Days of the week the app's own messages may go (Eko: every day).",
            "On other days they wait for the next sending day. A message a "
            "person sends goes any day.",
            kind=LIST, choices=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
            words=("sending days", "send days")),
    Setting("send_holidays", "hours", "Holidays (no sending)",
            "Dates the app sends nothing by itself, e.g. 2026-12-25, "
            "2027-01-26.", "Messages due on these dates wait for the next "
            "sending day.", kind=TEXT, min=0, max=2000,
            words=("holidays", "holiday")),
    Setting("send_max_per_person_day", "hours", "Most messages to one person a day",
            "The app's own WhatsApps to one number in a day (0 = no limit, "
            "Eko's today). Messages a person sends do not count.",
            "Above it, the rest wait for the next day.", unit="messages",
            min=0, max=50, words=("max per person", "messages per day",
                                  "daily limit")),
    Setting("msg_documents_ready", "feedback", "“Documents ready” WhatsApp",
            "After the documents are emailed, tell the CSP on WhatsApp.",
            "Off: only the email goes — and so no feedback question either "
            "(it follows this message).", kind=BOOL,
            words=("documents ready", "documents ready message")),
    Setting("feedback_wording", "feedback", "Feedback question wording",
            "Blank = Eko's Hinglish wording. Use {name} for the CSP's name. "
            "A new wording needs Meta's approval once before it is "
            "delivered.", "Questions from now on use this wording.",
            kind=TEXT, min=0, max=900, words=("feedback wording",)),
    Setting("reply_never_answer_words", "replies", "Never answer these topics",
            "Words that mean a topic the reply agent never answers, besides "
            "Eko's technical list (machine, network, money…), comma "
            "separated.", "Messages with these words get no automatic reply.",
            kind=TEXT, min=0, max=1000, words=("never answer",)),
    # ---- No. 214 (Stage 7) ----------------------------------------------
    Setting("job_sheet_read_on", "jobs", "Reading the main sheet",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("reading the main sheet",)),
    Setting("job_sheet_read_every", "jobs", "Reading the main sheet: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_signin_read_on", "jobs", "Reading the sign-in list",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("reading the sign-in list",)),
    Setting("job_signin_read_every", "jobs", "Reading the sign-in list: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_records_sheets_on", "jobs", "Reading the old / new records sheets",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("reading the old / new records sheets",)),
    Setting("job_records_sheets_every", "jobs", "Reading the old / new records sheets: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_sheet_photos_on", "jobs", "Taking photos from the sheet",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("taking photos from the sheet",)),
    Setting("job_sheet_photos_every", "jobs", "Taking photos from the sheet: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_delivery_status_on", "jobs", "Checking WhatsApp delivery",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("checking whatsapp delivery",)),
    Setting("job_delivery_status_every", "jobs", "Checking WhatsApp delivery: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_replies_on", "jobs", "Answering CSP replies",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("answering csp replies",)),
    Setting("job_replies_every", "jobs", "Answering CSP replies: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_verify_on", "jobs", "Checking old CSPs' details",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("checking old csps' details",)),
    Setting("job_verify_every", "jobs", "Checking old CSPs' details: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_contact_loop_on", "jobs", "Finding another way to reach a CSP",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("finding another way to reach a csp",)),
    Setting("job_contact_loop_every", "jobs", "Finding another way to reach a CSP: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_resend_on", "jobs", "Sending failed WhatsApps again",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("sending failed whatsapps again",)),
    Setting("job_resend_every", "jobs", "Sending failed WhatsApps again: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_info_fix_on", "jobs", "Fixing the lookup table",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("fixing the lookup table",)),
    Setting("job_info_fix_every", "jobs", "Fixing the lookup table: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("job_new_records_on", "jobs", "Making documents for new records",
            "Whether this background job runs for this workspace.",
            "Off: it does not run here until switched on again.",
            kind=BOOL, words=("making documents for new records",)),
    Setting("job_new_records_every", "jobs", "Making documents for new records: at most every",
            "0 = every time the server runs it (as today). More = less often.",
            "It runs for this workspace at most this often.",
            unit="minutes", min=0, max=1440),
    Setting("alert_to", "alerts", "Who gets alerts",
            "Email addresses, comma separated. Blank = every Super Admin.",
            "Alerts from now on go to these addresses.", kind=TEXT, min=0,
            max=1000, words=("alert to", "who gets alerts")),
    Setting("health_email_on", "look", "Weekly health email",
            "A short email each week: what was sent, what failed, documents "
            "made, what is stuck, and what to fix in the setup.",
            "Off: no weekly email.", kind=BOOL,
            words=("weekly email", "health email")),
    Setting("health_email_day", "look", "Weekly email: day", "",
            "The email goes on this day.", kind=CHOICE,
            choices=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
            words=("weekly email day",)),
    Setting("health_email_hour", "look", "Weekly email: hour",
            "On the workspace's clock (24-hour).", "The email goes at this "
            "hour.", unit="o'clock", min=0, max=23,
            words=("weekly email hour",)),
    Setting("health_email_to", "look", "Weekly email: to",
            "Email addresses, comma separated. Blank = every Super Admin.",
            "The weekly email goes to these addresses.", kind=TEXT, min=0,
            max=1000, words=("weekly email to",)),
    Setting("contact_report_on", "look", "Daily contact email",
            "Each evening: how many messages went out today, how many times "
            "each CSP has been contacted, and who cannot be reached and why.",
            "Off: no daily contact email.", kind=BOOL,
            words=("daily email", "contact email", "daily report",
                   "contact report")),
    Setting("contact_report_hour", "look", "Daily contact email: hour",
            "On the workspace's clock (24-hour).", "The email goes at this "
            "hour each day.", unit="o'clock", min=0, max=23,
            words=("daily email hour", "contact report hour")),
    Setting("contact_report_to", "look", "Daily contact email: to",
            "Email addresses, comma separated. Blank = every Super Admin.",
            "The daily contact email goes to these addresses.", kind=TEXT,
            min=0, max=1000, words=("daily email to", "contact report to")),
    Setting("brand_name", "look", "App name",
            "Shown at the top of every page (Eko: CSPdocMaker).",
            "Every page shows this name.", kind=TEXT, min=1, max=40,
            words=("app name", "brand name")),
    Setting("ui_theme", "look", "Display",
            "The look of the app for everyone in this workspace: colours, "
            "menu, text size and spacing. Pick one on Setup → Display.",
            "Every page changes to this look (each person's light / dark "
            "choice stays theirs).", kind=CHOICE,
            choices=UI_THEMES, words=("display", "ui type", "theme", "look")),
    Setting("ui_style", "look", "Design style",
            "Shapes, shadows and surfaces on top of the Display look — e.g. "
            "claymorphism, glassmorphism, brutalism, minimalism. Pick one on "
            "Setup → Display.", "Every page changes to this style.",
            kind=CHOICE, choices=UI_STYLES,
            words=("design style", "ui design", "style")),
    Setting("brand_color", "look", "Main colour",
            "A colour like #00B259 (Eko's green).",
            "Buttons and highlights use this colour.", kind=TEXT, min=7,
            max=7, words=("colour", "color", "main colour")),
    # ---- No. 240 (SaaS upgrade Stage 3) ----------------------------------
    Setting("brand_color_2", "look", "Second colour",
            "A colour like #12305C, or blank for none (Eko: none).",
            "The strip behind the logo and the profile circles use it.",
            kind=TEXT, min=0, max=7,
            words=("second colour", "second color", "secondary colour")),
    Setting("allow_personal_look", "look", "People may pick their own colours",
            "On: each person may choose their own colours and font on "
            "Settings -> Appearance. Off: everyone sees the workspace's; "
            "light / dark, sizes, layout and accessibility stay theirs.",
            "Off: people's own colours and fonts are no longer shown.",
            kind=BOOL, words=("own colours", "personal look")),
    # ---- No. 215 (Stage 8) ---------------------------------------------
    Setting("workspace_live", "golive", "Live",
            "On: messages and emails go to real people. A new workspace "
            "starts off; go live from Setup → Setup guide.",
            "Off: nothing goes to real people (test mode still works).",
            kind=BOOL, words=("live", "go live")),
    Setting("pause_all", "golive", "Pause everything",
            "Stops every WhatsApp and email at once (sign-in codes still go).",
            "On: nothing is sent until switched off; due messages wait.",
            kind=BOOL, words=("pause everything", "pause all")),
    Setting("test_mode", "golive", "Test mode",
            "Everything is sent only to the test number and email below, "
            "marked as a test.", "On: no message reaches a real person.",
            kind=BOOL, words=("test mode",)),
    Setting("test_mode_phone", "golive", "Test WhatsApp number",
            "Your own mobile, for test mode.", "Test messages go here.",
            kind=TEXT, min=0, max=20, words=("test number", "test phone")),
    Setting("test_mode_email", "golive", "Test email address",
            "Your own email, for test mode.", "Test emails go here.",
            kind=TEXT, min=0, max=200, words=("test email",)),
    # ---- No. 216 (Stage 9): limits, so a wrong setting cannot flood ------
    Setting("max_whatsapp_per_day", "golive", "Most WhatsApps a day (whole workspace)",
            "A ceiling on everything this workspace sends on WhatsApp in a "
            "day (0 = no ceiling, Eko's today).",
            "Above it, the rest wait for the next day.", unit="messages",
            min=0, max=100000, words=("whatsapp limit", "most whatsapps")),
    Setting("max_documents_per_day", "golive", "Most documents a day",
            "A ceiling on documents made in a day (0 = no ceiling, Eko's "
            "today).", "Above it, the rest wait for the next day.",
            unit="documents", min=0, max=100000,
            words=("document limit", "most documents")),
    Setting("lead_live_remark", "data", "Words that mean 'live'",
            "In the new records sheet's status column (Eko: Go Live Done).",
            "Records whose status says this are treated as live.", kind=TEXT,
            min=1, max=100, words=("live words", "go live words")),
]

BY_KEY: Dict[str, Setting] = {s.key: s for s in SETTINGS}
GROUP_KEYS = tuple(g.key for g in GROUPS)
KEYS = frozenset(BY_KEY)

assert len(BY_KEY) == len(SETTINGS), "a setting is listed twice"
assert all(s.group in GROUP_KEYS for s in SETTINGS)


class SettingError(ValueError):
    """A value that cannot be saved; the text says why, in plain words."""


_TRUE = {"on", "yes", "true", "1", "haan", "ha", "chalu", "enable",
         "enabled", "start"}
_FALSE = {"off", "no", "false", "0", "nahi", "nahin", "band", "disable",
          "disabled", "stop"}


def parse(s: Setting, raw: Any) -> Any:
    """A value as typed (screen, chat or sheet) -> the stored value, or
    SettingError saying what is allowed."""
    if s.kind == BOOL:
        if isinstance(raw, bool):
            return raw
        t = str(raw).strip().lower()
        if t in _TRUE:
            return True
        if t in _FALSE:
            return False
        raise SettingError(f"{s.label}: say on or off.")
    if s.kind == INT:
        if isinstance(raw, bool):
            raise SettingError(f"{s.label}: give a number.")
        try:
            if isinstance(raw, float) and raw.is_integer():
                raw = int(raw)
            value = int(str(raw).strip().split()[0]) if not isinstance(
                raw, int) else raw
        except (ValueError, IndexError):
            raise SettingError(f"{s.label}: give a whole number"
                               + (f" ({s.unit})" if s.unit else "") + ".")
        if (s.min is not None and value < s.min) or (
                s.max is not None and value > s.max):
            raise SettingError(f"{s.label} must be from {s.min} to {s.max}"
                               + (f" {s.unit}" if s.unit else "") + ".")
        return value
    if s.kind == LIST:
        items = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(",")
        out = []
        for item in items:
            t = str(item).strip()
            if not t:
                continue
            if not s.choices:          # document codes: any code-like word
                t = t.upper()
                if not re.fullmatch(r"[A-Z0-9_]{2,40}", t):
                    raise SettingError(f"{s.label}: {t!r} is not a document "
                                       "code (e.g. BCP).")
            elif t not in s.choices:
                raise SettingError(f"{s.label}: {t!r} is not one of "
                                   + ", ".join(s.choices) + ".")
            if t not in out:
                out.append(t)
        return ",".join(out)
    if s.kind == CHOICE:
        t = str(raw).strip()
        if t not in s.choices:
            raise SettingError(f"{s.label}: choose one of "
                               + ", ".join(s.choices) + ".")
        return t
    t = str(raw if raw is not None else "").strip()
    if len(t) < (s.min or 0) or len(t) > (s.max or 1000):
        raise SettingError(f"{s.label} must be {s.min}-{s.max} characters.")
    return t


def show(s: Setting, value: Any) -> str:
    """A value in plain words: 'On', '30 minutes', '+05:30'."""
    if s.kind == BOOL:
        return "On" if value else "Off"
    if s.kind == INT and s.unit:
        return f"{value} {s.unit}"
    if s.kind == LIST:
        return ", ".join(v for v in str(value or "").split(",") if v) or "none"
    if s.key == "record_type_rule":
        return {"code_length": "by code length",
                "one_type": "one type"}.get(value, str(value))
    return str(value)


def check_together(values: Dict[str, Any]) -> None:
    """Rules between settings, given the values that would be in force."""
    start, end = values.get("verify_start_hour"), values.get("verify_end_hour")
    if start is not None and end is not None and start >= end:
        raise SettingError(
            f"Messages must start before they stop: start {start}, stop "
            f"{end}. Change the other one first.")
    for key in ("record_main_lengths", "record_second_lengths"):
        text = values.get(key)
        if text is not None:
            parts = [p.strip() for p in str(text).split(",") if p.strip()]
            if not all(p.isdigit() and 1 <= int(p) <= 40 for p in parts):
                raise SettingError("Code lengths are whole numbers from 1 to "
                                   "40, separated by commas (e.g. 9,10).")
    main = {p.strip() for p in str(values.get("record_main_lengths") or "").split(",") if p.strip()}
    second = {p.strip() for p in str(values.get("record_second_lengths") or "").split(",") if p.strip()}
    if main & second:
        raise SettingError("A code length cannot belong to both types.")
    color = values.get("brand_color")
    if color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(color)):
        raise SettingError("Main colour: a colour like #00B259.")
    color2 = values.get("brand_color_2")
    if color2 and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(color2)):
        raise SettingError("Second colour: a colour like #12305C, or blank.")
    if values.get("test_mode") and not (values.get("test_mode_phone")
                                        or values.get("test_mode_email")):
        raise SettingError("Set a test WhatsApp number or test email first, "
                           "then switch test mode on.")
    for key in ("alert_to", "health_email_to", "contact_report_to",
                "test_mode_email"):
        for part in str(values.get(key) or "").split(","):
            part = part.strip()
            if part and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", part):
                raise SettingError(f"{part!r} is not an email address.")
    holidays = values.get("send_holidays")
    if holidays:
        import datetime as _dt
        for part in str(holidays).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                _dt.date.fromisoformat(part)
            except ValueError:
                raise SettingError(f"Holidays: {part!r} is not a date like "
                                   "2026-12-25.")
    if values.get("send_days") is not None and not str(values["send_days"]).strip():
        raise SettingError("Choose at least one sending day.")
    first = values.get("resend_first_wait_minutes")
    longest = values.get("resend_longest_wait_hours")
    if first is not None and longest is not None and first > longest * 60:
        raise SettingError(
            "The first wait before sending again cannot be longer than the "
            "longest wait between tries.")


def find(text: str) -> List[Setting]:
    """Settings whose words (or label) appear in the text — fixed words,
    longest match first, so 'feedback delay' wins over 'feedback'."""
    t = " " + " ".join(text.lower().replace("-", " ").split()) + " "
    hits = []
    for s in SETTINGS:
        best = 0
        for w in s.words + (s.label.lower(),):
            if f" {w.replace('-', ' ')} " in t or (
                    len(w) > 12 and w.replace("-", " ") in t):
                best = max(best, len(w))
        if best:
            hits.append((best, s))
    if not hits:
        return []
    top = max(b for b, _ in hits)
    return [s for b, s in hits if b == top]
