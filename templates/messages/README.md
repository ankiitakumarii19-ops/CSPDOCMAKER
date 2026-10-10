# WhatsApp / SMS message templates — drop your files here

The notification sent to the CSP **after** the document email succeeds.

| File name | Contents |
|---|---|
| `document_delivery.whatsapp.txt` | The message text |

Use the same `{{variable}}` style as the email templates.

Also needed before this can go live:

- Which provider will send it (Meta Cloud API, Gupshup, MSG91, …).
- The **approved template name and ID**. WhatsApp only allows
  business-initiated messages from a template that Meta has approved in
  advance, so the wording here has to match that approved template exactly.

Until the provider is chosen, this channel stays stubbed and will not claim a
successful send.
