# CSPdocMaker — documentation

Everything about this system, written so that a colleague can understand it
and an engineer (or an AI) could rebuild it from scratch.

Start wherever your question is.

| If you want to know | Read |
|---|---|
| What this is and why it exists | **[ARCHITECTURE.md](ARCHITECTURE.md)** §1 |
| How a document actually gets made | **[ARCHITECTURE.md](ARCHITECTURE.md)** §4 |
| What each agent does | **[agents/](agents/)** — one file per agent |
| Why something is built the way it is | **[DECISIONS.md](DECISIONS.md)** |
| What changed, and when | **[../CHANGELOG.md](../CHANGELOG.md)** |
| What is not finished | **[ARCHITECTURE.md](ARCHITECTURE.md)** §11 |

## What this system does, in one paragraph

A row appears in a Google Sheet describing a bank Customer Service Point.
Within a minute the system notices it, checks that every field four Word
documents need is present, fetches the CSP's photograph, fills the bank's
own `.docx` templates, converts them to PDF, reads the PDF back to confirm
nothing went wrong, stores both formats, and emails them to the CSP. If
anything is missing it stops and asks exactly the person who can answer —
the CSP for their own details, their RM for the bank's. Nobody has to
notice any of it happening.

## Status, as of 6 October 2026

| | |
|---|---|
| Tests | 748, all passing |
| API endpoints | 74 |
| Database | 26 tables, 18 migrations |
| Source | ~34,200 lines (backend, frontend, tests) |
| CSP records | 8 |
| Documents generated | 64 |
| Running on | one Windows laptop; **not deployed** |
| In version control | **no — zero commits** |

The last two lines are the honest headline: this works, and it exists in
exactly one place.

## For an AI asked to replicate this

Read [ARCHITECTURE.md](ARCHITECTURE.md) end to end before writing anything.
It states the data model, the pipeline, the ownership rules and the
invariants, and [DECISIONS.md](DECISIONS.md) explains which of those are
load-bearing. Several things that look like arbitrary choices are not: the
placeholder format, the one-transaction rule around sending, the workspace
scoping, and the refusal to generate from incomplete data each exist
because the alternative failed in a specific, recorded way.
