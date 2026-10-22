# WhatsApp template: "documents emailed" (no attachment)

Tracker No. 135 (22 Oct 2026). The documents are NOT sent on WhatsApp; this
message only tells the CSP they were emailed. (Replaces No. 90's template
with a Document header, which is no longer used.)

The app's WhatsApp platform submits this wording to Meta by itself the first
time a CSP's documents are emailed; until Meta approves it (minutes to about
a day) that notice shows as "waiting for Meta's approval" on the WhatsApp
messages screen and is not re-sent — the CSP still has the email. To have it
approved BEFORE the first CSP, create it yourself in Eko's WhatsApp console:
https://indev.eko.in/whatsapp-console/ → **Templates** → new template.

| Field | Value |
|---|---|
| Category | **Utility** |
| Language | **English (en_US)** |
| Header | **None** |
| Footer / buttons | none |

## Body — paste EXACTLY (every character, line break and dash)

```
Namaste {{1}}, your CSP documents ({{2}}) have been issued and sent to your email {{3}}. Please check your inbox, and the Spam folder too.

नमस्ते {{4}}, आपके CSP दस्तावेज़ ({{5}}) जारी कर दिए गए हैं और आपके ईमेल {{6}} पर भेज दिए गए हैं। कृपया अपना इनबॉक्स और Spam फ़ोल्डर भी देखें।

Namaste {{7}}, aapke CSP documents ({{8}}) jaari kar diye gaye hain aur aapke email {{9}} par bhej diye gaye hain. Kripya apna inbox aur Spam folder bhi dekhein.

— Team Eko
```

## Sample values Meta asks for

| Variable | Fills in | Sample |
|---|---|---|
| {{1}}, {{4}}, {{7}} | name | Ramesh Kumar |
| {{2}}, {{5}}, {{8}} | documents | CSP ID Card, Appointment Letter |
| {{3}}, {{6}}, {{9}} | email | ramesh@example.com |

If Meta REJECTS it, send the rejection reason to the developer: the wording
in `backend/app/services/documents_whatsapp.py` must then change to match.
