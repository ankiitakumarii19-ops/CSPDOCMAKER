# WhatsApp template: "documents ready" (with the PDF attached)

Tracker No. 90. Create this ONCE in Eko's WhatsApp console:
https://indev.eko.in/whatsapp-console/ → **Templates** → new template.

| Field | Value |
|---|---|
| Name | `cspdocmaker_documents_ready_pdf_v1` |
| Category | **Utility** |
| Language | **English (en_US)** |
| Header | **Document** — upload any small sample PDF (Meta uses it only as the example) |
| Footer / buttons | none |

## Body — paste EXACTLY (every character, line break and dash)

```
Namaste {{1}}, your CSP documents ({{2}}) have been issued. The PDF is attached to this message and has also been emailed to {{3}}.

नमस्ते {{4}}, आपके CSP दस्तावेज़ ({{5}}) जारी कर दिए गए हैं। PDF इस संदेश के साथ संलग्न है और {{6}} पर ईमेल भी किया गया है।

Namaste {{7}}, aapke CSP documents ({{8}}) jaari kar diye gaye hain. PDF is message ke saath attached hai aur {{9}} par email bhi kiya gaya hai.

— Team Eko
```

## Sample values Meta asks for

| Variable | Fills in | Sample |
|---|---|---|
| {{1}} | name | Ramesh Kumar |
| {{2}} | documents | ID Card, Appointment Letter |
| {{3}} | email | ramesh@example.com |
| {{4}} | name | Ramesh Kumar |
| {{5}} | documents | ID Card, Appointment Letter |
| {{6}} | email | ramesh@example.com |
| {{7}} | name | Ramesh Kumar |
| {{8}} | documents | ID Card, Appointment Letter |
| {{9}} | email | ramesh@example.com |

## After Meta approves it

Nothing else to do: the app looks the wording up by its exact text and sends
with the PDF attached. Check it with `python scripts/check_whatsapp.py`
(it lists approval status) or in the console's Templates list.

If Meta REJECTS it, send the rejection reason to the developer: the wording
in `backend/app/services/documents_whatsapp.py` must then change to match a
new template.
