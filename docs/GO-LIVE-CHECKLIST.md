# Go-live checklist — a new workspace

PROJECT-REGISTER No. 216 (Stage 9, TK-074). For a Super Admin taking a new
company's workspace live, and for whoever checks it with them. Every step is
on a screen (Setup menu) or can be asked of the chat. Nothing here needs code.

## Before going live

| # | Step | Where | Done when |
|---|---|---|---|
| 1 | Share the main sheet with the robot address; paste its link; **Test** | Setup → Connections → Google Sheets | Test says "opened" and finds the tab |
| 2 | Check which column is which field (**Guess from my sheet**, correct, Save) | Setup → Columns | Every field you use has a column |
| 3 | Records type, words, who fills what | Settings → Records and words | Looks right for this company |
| 4 | Email account; **Send a test email to me** | Setup → Connections → Email | The test email arrives |
| 5 | WhatsApp platform address; **Test** | Setup → Connections → WhatsApp | Test says the platform answered |
| 6 | CRM, only if used; **Test** | Setup → Connections → CRM | Test gets a token |
| 7 | Document templates: upload or review; every blank has a field (use the suggestions); switch on | Setup → Document Templates | Each needed document is active with 0 unmapped |
| 8 | Message wordings; send for Meta's approval once | Setup → Messaging | Wordings approved |
| 9 | Sending hours, days, holidays, limits | Settings → Sending hours; Going live | As the company wants |
| 10 | People and what each may use | Setup → Access; Setup → Feature access | Each person has only their screens |
| 11 | Setup guide shows every essential step **Done** | Setup → Setup guide | "Go live" is no longer refused |

## Try it before real people see it

| # | Step | Done when |
|---|---|---|
| 12 | Setup guide → **Test mode** with your own WhatsApp number and email | Test messages and documents reach only you, marked as a test |
| 13 | **Run the dry run** | For the 5 newest records it says what would happen, and it is right |
| 14 | Download the settings (Excel) and keep it | A copy of every choice, to restore or reuse |

## Going live

| # | Step | Done when |
|---|---|---|
| 15 | Switch test mode off; **Go live** | Setup guide says "live" |
| 16 | Watch the first day: WhatsApp messages, Emails, Action Required | Nothing unexpected failed |
| 17 | The weekly health email arrives (Settings → Look and weekly email) | Its "what to fix" list is empty |

## If something goes wrong

- **Pause everything** (Setup guide): nothing more is sent; messages wait.
- Undo a setting: Settings → History → Undo. Undo a feature change: Feature
  access → "changed ↺".
- Close the workspace: Setup guide → "Download all data", then "Close this workspace". Nothing is deleted; the
  server administrator can open it again.

## Never possible, whatever the settings

One workspace never sees another's data (tested on every list screen);
passwords and keys are never shown back or put in the chat or a log; the
change history cannot be switched off; a Super Admin always keeps every
feature; Eko's sheets, mail account, WhatsApp and Zoho are never another
workspace's.
