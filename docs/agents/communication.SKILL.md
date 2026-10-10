# Communication Agent — SKILL.md

> **The question it owns**
> *Who needs to hear something, and has it reached them?*

Knowing who should be asked is useless if nobody asks them. This agent is the only thing that puts a message on the wire.

## At a glance

| | |
|---|---|
| Key | `communication` |
| Schedule | Every 60 minutes |
| On by default | **no** |
| Implementation | `backend/app/services/agents.py` — `@performs("communication")` |
| Registered in | `backend/app/services/agent_registry.py` |

## What it does

- Finds CSPs who should be asked for their details
- Chooses the workspace's configured channel and wording
- Sends, and records what happened to each message
- Retries a failure according to the workspace's own rules
- Falls back to email when a CSP has no usable mobile number

## What it may do on its own

- Send a message a workspace has configured and enabled
- Retry a failed send

## What it must ask a person about

- Messaging a large group for the first time
- Sending through a channel that has never succeeded

## What it reads and writes

**Reads:** `csp_records`, `data_requests`, `message_channels`, `message_templates`

**Writes:** `data_requests`, `message_channels (last used, last error)`, `agent_findings`, `and sends messages`

## Things to be careful about

- OFF by default. It is the only agent that contacts real people, and turning it on should be a decision somebody made.
- Above 25 recipients it proposes and sends NOTHING. A bad template or a bad link cannot reach a thousand CSPs before anyone notices.
- A message whose link nobody outside the machine could open is refused before it is sent, and the request is cancelled. Being asked with a dead link is worse than not being asked, because the record is then marked as chased.
- Nobody is messaged twice about the same thing: an open request means they have already been asked and are being waited on.

## How it runs

It is a plain function taking a database session. It does not call any
other agent and no other agent calls it — they coordinate through the
database, not through each other. The runner records every pass in
`agent_runs`: when, who triggered it, what it concluded and how long it
took. A Super Admin can read that history on the Agents screen.

Scheduled runs happen once inside each active workspace, because an agent
reads workspace-scoped tables and would otherwise see nothing.

A disabled agent is not skipped silently — the run record says it was
switched off, which is the difference between "it found nothing" and "it
never looked".
