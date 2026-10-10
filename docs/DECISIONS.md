# Why it is built this way

Each of these looks like an arbitrary choice and is not. Every one replaced
something that failed in a specific, recorded way. If you are rebuilding
this system, these are the parts where the obvious approach is the wrong
one.

---

### Documents are stored in Postgres, not on disk

A reissue needs no regeneration, and there is one thing to back up rather
than two. The cost is a larger database; the benefit is that "where is this
CSP's ID card" has one answer.

---

### The stored documents and the "processed" stamp commit together

They were two statements. A crash between them leaves a CSP who looks
unprocessed but already has documents — and the next run emails them a
second time. The email is sent only **after** that commit succeeds, so a
send failure can never cause a regeneration.

---

### Work is selected by state, never by a time window

An earlier version looked for CSPs created in the last few minutes. Anyone
added while the worker was down was skipped **forever**, silently. The
query is now `(origin='new' OR auto_enrolled) AND not yet processed`, which
cannot miss anybody however long the worker was away.

---

### A CSP merely present at the first sync is never processed

Without this, the first run against a real sheet would email an entire
organisation their documents unannounced. Only a genuinely new row, or one
an RM deliberately enrolled, is acted on.

---

### Workspace scoping lives under the ORM, not in endpoints

Written per endpoint, one forgotten `.where()` leaks a bank's data, and
nothing about the code would look wrong. A `do_orm_execute` listener adds
the filter to every SELECT against any model carrying `workspace_id`.

Verified against a real database with two workspaces: a record from one
does not appear in the other's list, count, **or** a direct lookup by its
primary key.

---

### Placeholders are quoted text, not `{{...}}`

The templates arrived using `"CSP Name"`. Changing them would mean the bank
re-approving four documents. Word's autocorrect produces curly quotes, so
the regex accepts straight and curly alike.

Replacement works on the **concatenated paragraph text**, then writes back
into the runs the placeholder covers — because Word splits a placeholder
across runs (`"` + `CSP ` + `Name"`) and a run-level replace finds almost
nothing.

---

### The photo frame is widened at generation time

A frame drawn exactly 35 × 45 mm cannot hold a 35 × 45 mm photograph:
LibreOffice reserves **3.2 mm on each side** of a text box whatever `inset`
asks for, and negative insets are clamped to zero. Both measured, not
assumed. The frame is widened by that amount and shifted left so the image
lands on exactly the rectangle the template drew.

The related failure: a caption's 50pt space-before was inherited by the
photograph, pushing it 19 mm down and out of its frame, where it was
silently clipped at the eyes. Anything between frame and photo is now
cleared.

---

### Photos are cropped to 35 × 45, never fitted

Fitting a square scan inside the box gives 35 × 35 mm — the right shape for
nothing. The source is cropped to the passport ratio first, keeping the top
where the head is.

---

### The address is trimmed only on templates that print the district separately

The CSP Certificate prints the address and then `DIST- <district>, <state>`
beside it, and people write their address ending with both. The ID Card and
BCP print the address **alone**, so there the tail is the only copy of the
district and pincode and trimming would destroy data.

The rule reads the template's own placeholders rather than the document's
name, so an uploaded template gets the same treatment.

Only the **end** is trimmed. A district at the start is part of the place
name — "Patna City Main Road" in Patna district must keep its first word —
and position is the only way to tell them apart.

---

### Both the filler and the validator go through one function

They disagreed once: the certificate's address was trimmed on the way in
and not on the way out, so validation hunted for text the document was
never going to contain. `template_service.values_for()` is now the single
place anything template-specific happens.

---

### Agents do not call each other

They declare intervals of 3, 10, 15, 30 and 60 minutes, so they interleave
unpredictably. Anything depending on "Data ran before Communication" would
be a race. Reading current state is safe in any order, one failure stays
one failure, and any agent can be switched off.

---

### The agent schedule is generated from the registry

The agents were built, registered, enabled, and shown on screen as
"Running — every 15 min" while **nothing invoked them** for four days. The
beat schedule is now built from the same registry the screen reads, so an
agent is scheduled by being registered and the two cannot disagree.

A second trap found the same day: the `@performs` decorators were imported
only by the agent *router*, so the API process had them and the Celery
worker did not. Every scheduled run would have recorded "has no
implementation yet" and done nothing — worse than not running, because the
screen would have looked right. The runner now loads them itself.

---

### A metric's drill-down and its number come from the same place

A tile that says 2 and opens three rows makes every other figure on the
screen suspect. A test walks **every** drillable metric, computes it the
way the dashboard does, opens it the way a click does, and insists they
agree — on an empty workspace and with records present.

---

### "Documents CSPs already hold" shows three answers, not two

It showed only the Yes count, so "CSP ID Card — 0" read as *nobody has one*
when the truth was *one said they do not and two were never asked*. Those
lead to different work. Yes, No and Not-answered always add up to every CSP
in the workspace.

---

### A field nobody can print is chased from nobody

`branch_contact` and `rbo_contact` appear on no template and are not in
`FIELD_TO_CSP_ATTR`, so no document could carry them. They are still read
and stored — a value typed in the sheet is not dropped — but nobody is ever
asked for them. Chasing someone for a value no document can use is pure
cost.

---

### A link that nobody outside the machine can open is never sent

`PUBLIC_APP_URL` defaults to localhost so the system runs on a laptop
without configuration. Sending that link is worse than sending nothing: the
CSP gets an official-looking message they cannot act on, and the record is
marked as asked. The send is refused and the request cancelled, so the next
attempt issues a fresh link.

This stopped a real email to a real CSP on 3 October.

---

### Above 25 recipients the Communication Agent proposes and sends nothing

A bad template or a bad link cannot reach a thousand CSPs before anyone
notices.

---

### The CSP's link is one-use, hashed, and silent about why it failed

The token is never stored — only its SHA-256 hash. A wrong token, an
expired one and an already-used one return **the same** answer, so the link
cannot be probed. It can write only the fields it was issued for.

---

### Login is throttled per account *and* per source

Two counters stop different attacks: one account guessed at from anywhere,
and one source spraying a common password across many accounts. Both expire
after 15 minutes — a permanent lockout would hand anyone a way to deny a
real RM their job by failing to log in as them.

---

### Zoho is read-only by scope

Not by convention, and not by careful coding. The credentials granted to
this system are READ scopes; a write is rejected by Zoho itself.

---

### Deleting a sheet row returns what it deleted

There is no undo. The contents come back in the response so the screen can
show them and somebody can type them again; Google Sheets' own version
history is the real recovery. The action is logged at warning level with
who did it.

---

### A photo path from a sheet cell is validated before it is opened

The Sheets screen renders the Photo column as an image. That path comes out
of a spreadsheet cell anyone with the sheet can edit, so it is resolved and
checked to be inside the photos directory first. Without that, a cell
reading `..\..\.env` would be a way to read any file on the server.

---

### Recording a sign-in can never cost somebody their login

The person is already authenticated when the record is written. Refusing
them because a log row would not write is the worse outcome, so the
recorder catches everything.
