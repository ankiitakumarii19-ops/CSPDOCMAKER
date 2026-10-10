# Reference data — drop sheet exports and assets here

Everything in `reference/samples/` is **git-ignored**, so real CSP data placed
there is never committed.

## 1. CSP sheet structure

Either:

**(a) Give me read access instead of a file** — put the spreadsheet ID in
`backend/.env` as `GOOGLE_SHEETS_CSP_SHEET_ID` and share the sheet with the
service account's `client_email` (Viewer is enough to start). I can then read
the real headers myself, which removes any guesswork about column names.

or

**(b) Export a sample** to `reference/samples/csp_sheet.csv` — File → Download →
CSV in Google Sheets. Keep the header row exactly as it is. Blank out personal
data in the rows if you prefer; I need the **column names and value formats**
(date formats, how codes look), not real people.

## 2. Authorization sheets

`reference/samples/rm_sheet.csv` and `reference/samples/admin_sheet.csv` —
header rows, plus a couple of rows so I can see the formats.

This also needs to answer: **where is the RM-to-district assignment held?** The
fallback rule (when a CSP row has no RM, find the RM who covers that district)
needs a column somewhere that says which districts each RM owns.

## 3. Logo and brand assets

Put the official EKO logo in `frontend/public/brand/` (SVG preferred, otherwise
a high-resolution PNG). Include the exact brand colours if you have them.

---

Nothing here needs to be wired into the code by you. Drop the files in, tell me
they are there, and I'll inspect them first and produce the field mapping table
for your review before writing any code against them.
