# Email templates — drop your files here

The email that delivers the generated PDFs to the CSP.

| File name | Contents |
|---|---|
| `document_delivery.subject.txt` | One line: the subject |
| `document_delivery.html` | The HTML body |
| `document_delivery.txt` | The plain-text body (optional but recommended) |

If you have the wording in a Word file or an email you already send, just drop
that in instead — any format is fine, and I'll convert it.

Mark the variable parts with double braces, for example:

```
Dear {{csp_name}},

Please find attached the documents for CSP code {{csp_code}}.
```

Tell me which variables the business wants and I'll map each one to a CSP
field. Do not invent variable names in the code — the template decides them.
