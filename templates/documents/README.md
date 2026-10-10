# DOCX templates — drop your files here

Put the four supplied Word templates in this folder, named exactly:

| File name | Document |
|---|---|
| `csp_id_card.docx` | CSP ID Card |
| `csp_certificate.docx` | CSP Certificate |
| `training_certificate.docx` | Training Certificate |
| `bcp.docx` | Business Continuity Plan |

Notes:

- Use the **real templates**, exactly as they are used today — logos, fonts,
  tables, headers, footers and signatures included. Do not clean them up or
  re-save them from a different program; the file is the source of truth for
  layout.
- If a template already contains placeholder text for the variable fields
  (for example `{{CSP_NAME}}`, `<CSP Name>` or a blank table cell), leave it
  exactly as it is. How each field is marked is what determines how the code
  fills it in.
- A filled-in real example next to a blank template is very helpful. Name it
  `<same-name>.EXAMPLE.docx`.
- `.gitkeep` can stay. It only keeps the empty folder in git.

These templates are read at generation time; nothing needs to be added to the
code by hand.
