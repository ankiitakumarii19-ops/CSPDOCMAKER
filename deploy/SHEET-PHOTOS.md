# CSP photos in the Google Sheet (tracker No. 91)

Whenever the app gets or changes a CSP's photo, that CSP's **Photo** cell in
the CSP sheet (KOData / SUBKOData) shows it as a real picture — automatically.

| Where a photo comes from | When it appears in the sheet |
|---|---|
| Taken from Zoho for a new CSP | when the new-CSP job runs |
| Documents are made (the 35 × 45 mm passport version) | right after the RM's request |
| An RM uploads one | right after the upload |
| You give one (the command below) | right away |

How: the app writes `=IMAGE("<private link>")` into the cell (the link opens
only that photo and expires after a day), and a small script in the sheet
replaces it with a real in-cell picture within 5 minutes. The picture shown
is the passport version once documents have been made, otherwise the photo as
obtained. This works on the server (indev.eko.in); a laptop copy cannot do it
because Google cannot reach a laptop.

## Photos you put in the sheet (tracker No. 99)

The app also **reads** the Photo column. When it has no photo for a CSP, it
takes the picture in that CSP's own row, in the Photo column of KOData or
SUBKOData — as soon as an RM asks for an ID Card, and on the regular run
that finishes waiting requests. Nothing to switch on.

* Put **one** picture in the CSP's Photo cell, in that CSP's row. A cell
  with two pictures is not used (the app cannot tell whose it is).
* A picture in another column, or in a row with no CSP Code, is not used.
* No picture anywhere: the request waits and the CSP is asked for the
  details that are missing, the photo among them. Add the picture and the
  documents are made and sent on the next run.

Once the app has a photo it keeps it; changing the picture in the sheet
later does not replace it (use `set_photo.py` below for that).

## One-time set-up of the sheet script

1. Open the CSP sheet → **Extensions → Apps Script**.
2. Delete what is in the editor, paste the whole of `deploy/sheet-photo-script.gs`.
3. **Save** (the disk icon).
4. In the function list at the top choose **installTrigger** → **Run**.
5. Google asks for permission → **Review permissions** → your account →
   **Advanced → Go to (unsafe)** → **Allow**. (It is your own script; it only
   reads and writes this sheet and fetches the photo links.)

Done. It now runs every 5 minutes by itself.

## Giving a CSP a photo yourself

Copy the photo to the server, then (on the server, in the app folder):

```bash
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \
    cp "/path/to/photo.png" api:/tmp/photo.png
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \
    exec api python scripts/set_photo.py 1A852458 /tmp/photo.png
```

It saves the photo for that CSP, makes the passport version for the
documents, keeps both in the database and puts it in the sheet.

## If a Photo cell shows a broken image

The link expired before the script turned it into a picture (e.g. the script
was not installed yet). Run `set_photo.py` again for that CSP, or wait for its
next document request — a fresh link is written either way.
