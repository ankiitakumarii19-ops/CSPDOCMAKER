# WhatsApp — cURL for every step (tracker No. 107)

CSPdocMaker sends WhatsApp through **Eko's WhatsApp platform**
(`https://indev.eko.in/whatsapp/mcp`). The platform holds Eko's Meta
credentials; this app stores none (only `WHATSAPP_PLATFORM_URL`).

Every call is the same shape — a JSON-RPC POST naming one tool:

```bash
curl -s -X POST https://indev.eko.in/whatsapp/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"TOOL","arguments":{ ... }}}'
```

The answer comes back as `event: message` / `data: {...}`; the useful part is
the `text` inside `result.content`. Run these on the server (or any machine
that can reach indev.eko.in). On Windows PowerShell use `curl.exe` and put the
JSON in a file (`-d @body.json`), because PowerShell mangles the quotes.

> Replace `91XXXXXXXXXX` with a real number (country code, digits only).
> Never paste a CSP's real number into a shared chat or document.

---

## 0. Which account is this? (credentials check)

```bash
curl -s -X POST https://indev.eko.in/whatsapp/mcp -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"whoami","arguments":{}}}'
```

Today it answers `sumit.kumar@eko.co.in` — a **shared Eko account**. The
sending WhatsApp number, the Meta Business account ID, the phone-number ID and
the access token are kept by the platform, not by this app and not by this
API: see them in the console (https://indev.eko.in/whatsapp-console/) or ask
the account owner.

## 1. Send a template to Meta for approval

```bash
curl -s -X POST https://indev.eko.in/whatsapp/mcp -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"create_meta_template","arguments":{
        "name":"cspdocmaker_example_v1",
        "body":"Namaste {{1}}, your CSP documents ({{2}}) are ready.\n\n— Team Eko",
        "category":"UTILITY",
        "language":"en_US"}}}'
```

Rules Meta enforces: lower-case name with `_`, placeholders numbered
`{{1}} {{2}} …`, a placeholder may not be the first or last thing, no line
break inside a filled-in value. **This tool cannot add a header** — a template
that carries a PDF (Document header) must be made in the console; see
`WHATSAPP-DOCUMENTS-TEMPLATE.md`.

## 2. Approval status and Meta's feedback

```bash
curl -s -X POST https://indev.eko.in/whatsapp/mcp -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_meta_templates","arguments":{}}}' \
  | grep -o '\\"name\\": \\"[^\\]*\\"\|\\"status\\": \\"[^\\]*\\"\|\\"rejected_reason\\": \\"[^\\]*\\"'
```

For each template: `status` is `APPROVED`, `PENDING` or `REJECTED`, and
`rejected_reason` is Meta's feedback (`NONE` when approved). Approval takes
minutes to about a day. To withdraw a pending or rejected one:
tool `delete_meta_template` with `{"name":"..."}`.

## 3. Send a message (two calls)

**3a. Upload the recipient** → returns a `job_id`:

```bash
curl -s -X POST https://indev.eko.in/whatsapp/mcp -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"upload_contacts","arguments":{
        "contacts":[{"phone":"91XXXXXXXXXX","name":"Ramesh Kumar","documents":"ID Card"}],
        "source_name":"CSPdocMaker manual test"}}}'
```

**3b. Send an APPROVED template by its exact name** to that job:

```bash
curl -s -X POST https://indev.eko.in/whatsapp/mcp -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"send_template_message","arguments":{
        "job_id":"JOB_ID_FROM_3a",
        "template_name":"cspdocmaker_example_v1",
        "phone_column":"phone",
        "language":"en_US",
        "mapping":{"1":{"type":"column","value":"name"},"2":{"type":"column","value":"documents"}}}}}'
```

With a PDF (only for a template that has a Document header), add:
`"header_type":"document","header_media_url":"https://…/the.pdf"` — the URL
must be public; Meta fetches it.

The app itself uses `smart_send_template` (same arguments but `body` instead
of `template_name`): the platform finds an approved template matching the
wording, or submits it for approval and answers `pending`.

## 4. Was it delivered / read?

```bash
curl -s -X POST https://indev.eko.in/whatsapp/mcp -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_delivery_status","arguments":{"job_id":"JOB_ID"}}}'
```

`sent_status` (`sent` / `failed`), then Meta's `delivery_status`
(`sent` → `delivered` → `read`, or `failed` with `delivery_error`). A send
with no `wamid` never reached WhatsApp at all.

## 5. Recent sends, and replies people sent back

```bash
# the account's last 200 sends (all teams): template, time, sent/failed/skipped
curl -s -X POST https://indev.eko.in/whatsapp/mcp -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_send_history","arguments":{}}}'

# messages people sent TO the number (optionally for one phone)
curl -s -X POST https://indev.eko.in/whatsapp/mcp -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_incoming_messages","arguments":{"phone":"91XXXXXXXXXX"}}}'
```

This app's sends are named `CSPdocMaker details request <code>` and
`CSPdocMaker documents <code>` in the history.

The same checks without cURL, from the app folder on the server:

```bash
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production exec -T api python scripts/check_whatsapp.py
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production exec -T api python scripts/check_whatsapp.py --status JOB_ID
```
